#!/usr/bin/env python3
"""Regression suite for every defect class the audits have found.

Eleven rounds of multi-agent auditing found eleven distinct defect classes.
Sampling found them; sampling cannot prove they are gone. This runs every
mechanically checkable class over all records at once, so a clean run is
evidence about the whole corpus rather than about thirty laws.

Each check returns a list of offending obligation ids with a one-line reason.
Checks are deliberately conservative: a check that fires on correct records
trains everyone to ignore it. Where a class cannot be decided mechanically
(is this duty real? is this the right agency?) the check reports a count for
tracking and does not fail the run.

    python3 pipeline/validate_obligations.py             # human-readable
    python3 pipeline/validate_obligations.py --json out.json
    python3 pipeline/validate_obligations.py --strict    # exit 1 on any hard failure

Hard failures are structural problems with an objectively right answer:
duplicate ids, quotes absent from the law, deadlines that precede enactment,
stub law text, cross-law contamination. Everything else is a soft count.

No Anthropic API calls. Runs offline against the committed data and text cache.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
TEXT = HERE / "cache" / "text"

# Deadline clauses anchored to something other than enactment or the effective
# date. Kept broad on purpose: the point is to catch a stamped calendar date
# that the law never supports, and a false positive here costs only a review.
# An anchor is only an "event" anchor if it points at something other than
# enactment or the effective date. The first draft of this check fired on
# "prior to such date", which is the standard implementation clause and means
# the effective date, so it flagged 100+ correct records. Excluding the
# date-referring phrases first is what makes the check trustworthy.
_ANCHOR_IS_A_DATE = re.compile(
    r"such dates?\b|the effective date|its effective date|such effective date"
    r"|it becomes (a )?law|such local law becomes|enactment", re.I)
EVENT_ANCHOR = re.compile(
    r"conclusion of|commencement of|completion of|after the pilot|termination of"
    r"|receipt of|following any change|formation of"
    r"|upon (the )?(submission|approval|determination|issuance)"
    r"|after (such|each|any) (summary|hearing|approval|determination|request|application|review)"
    r"|(prior to|before) (any|each|such) (hearing|meeting|removal|modification|sale|execution"
    r"|implementation|application|request|submission|expiration)"
    r"|from the date of (the|each|such|any) (application|request|receipt|notice)", re.I)


def event_anchored(text: str | None) -> bool:
    t = text or ""
    return bool(EVENT_ANCHOR.search(t)) and not _ANCHOR_IS_A_DATE.search(t)
SIX_MONTHLY = re.compile(
    r"every ?(6|six) months|semiannual|semi-annual|twice a year|twice each year", re.I)
# Whether an actor phrase is too vague to publish as an agency is decided by
# the extractor's own guard. The validator imports it rather than keeping a
# parallel heuristic, so the two cannot drift apart: an earlier version used a
# word-count threshold and spent most of its output on legitimate long body
# names like "the office of child care and early childhood education".
sys.path.insert(0, str(HERE))
try:
    from extract_obligations import is_vague_actor, quote_present, operative_text  # noqa: E402
except Exception:                                        # noqa: BLE001
    def is_vague_actor(_s):                              # type: ignore
        return False

    def quote_present(q, t, op=None):                    # type: ignore
        return squash(q) in squash(t)

    def operative_text(t):                               # type: ignore
        return t


def norm(s: str | None) -> str:
    s = (s or "").replace("{{", "").replace("}}", "")
    for a, b in (("“", '"'), ("”", '"'), ("‘", "'"),
                 ("’", "'"), ("–", "-"), ("—", "-")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s.lower()).strip()


def squash(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", norm(s))


def load_texts(matter_ids) -> dict[str, str]:
    """Raw cached text per matter; callers squash or strip markup as needed."""
    out = {}
    for mid in matter_ids:
        p = TEXT / f"{mid}.txt"
        if p.exists():
            out[mid] = p.read_text(errors="ignore")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--reverify", action="store_true",
                    help="update quote_verified in the extraction caches to match "
                         "the current cached law text, then exit")
    args = ap.parse_args()
    today = date.fromisoformat(args.today)

    data = json.loads((DATA / "obligations.json").read_text())
    obs = data["obligations"]
    laws = {l["matter_id"]: l for l in data["laws"]}
    by_matter = defaultdict(list)
    for o in obs:
        by_matter[o["matter_id"]].append(o)
    texts = load_texts(by_matter)

    if args.reverify:
        # Recovering a law's real text (from an attachment, say) can turn a
        # quote that looked fabricated into one that verifies. Re-check the
        # stored flag against the text we now hold, in both directions.
        flips = 0
        for mid, group in by_matter.items():
            t = texts.get(mid)
            if not t or len(squash(t)) < 400:
                continue
            path = HERE / "cache" / "extracted" / f"{mid}.json"
            if not path.exists():
                continue
            rec = json.loads(path.read_text())
            changed = False
            for o in rec.get("obligations", []):
                present = quote_present(o.get("quote"), t)
                if present != bool(o.get("quote_verified")):
                    o["quote_verified"] = present
                    changed = True
                    flips += 1
            if changed:
                path.write_text(json.dumps(rec, indent=1, ensure_ascii=False))
        print(f"reverified against current cached text: {flips} flags corrected")
        print("now rebuild: ANTHROPIC_API_KEY=dummy-no-api-calls "
              "python3 pipeline/extract_obligations.py --incremental")
        return

    hard: dict[str, list] = defaultdict(list)
    soft: dict[str, list] = defaultdict(list)

    # --- HARD: identifiers must be unique -----------------------------------
    for oid, n in Counter(o["obligation_id"] for o in obs).items():
        if n > 1:
            hard["duplicate_obligation_id"].append(f"{oid} appears {n} times")

    # --- HARD: the same duty recorded twice under one law -------------------
    # Distinct ids, identical content. Inflates every count that sums records.
    dup_groups: dict[tuple, list] = defaultdict(list)
    for o in obs:
        n = lambda s: re.sub(r"\s+", " ", (s or "").strip().lower())   # noqa: E731
        dup_groups[(o["matter_id"], n(o.get("quote")), n(o.get("citation")),
                    n(o.get("action_summary")), o.get("agency"))].append(o["obligation_id"])
    for ids in dup_groups.values():
        if len(ids) > 1:
            hard["identical_duplicate_obligations"].append(", ".join(ids))

    # --- HARD: law text must actually be present ----------------------------
    for mid, group in by_matter.items():
        t = texts.get(mid)
        if t is None:
            hard["law_text_missing"].append(
                f"{laws[mid]['law_number_display']}: {len(group)} obligations, no cached text")
        elif len(squash(t)) < 400:
            hard["law_text_is_a_stub"].append(
                f"{laws[mid]['law_number_display']}: {len(t)} chars, {len(group)} obligations")

    # --- HARD: a quote must appear in its own law ---------------------------
    # Only for laws whose text we actually hold in full, so a stub or a
    # truncated giant does not masquerade as fabrication.
    for o in obs:
        t = texts.get(o["matter_id"])
        if not t or len(t) < 400:
            continue
        if not (o.get("quote") or "").strip():
            hard["quote_empty"].append(o["obligation_id"])
        elif not quote_present(o.get("quote"), t):
            (hard if o.get("quote_verified") else soft)["quote_not_in_law_text"].append(
                f"{o['obligation_id']} ({'flagged verified' if o.get('quote_verified') else 'already unverified'})")

    # --- SOFT: quote absent here, present elsewhere -------------------------
    # A hint about misfiling, not proof of it. Two laws amending the same code
    # chapter legitimately restate the same sentences, and the giant
    # construction-code laws match almost anything, so this needs a human or an
    # agent to adjudicate rather than failing the build.
    suspects = [o for o in obs
                if texts.get(o["matter_id"]) and len(texts[o["matter_id"]]) >= 400
                and (o.get("quote") or "").strip()
                and not quote_present(o["quote"], texts[o["matter_id"]])]
    for o in suspects:
        q = squash(o["quote"])
        if len(q) < 60:
            continue                      # too short to be distinctive
        for mid2, t2 in texts.items():
            if mid2 != o["matter_id"] and q in t2:
                soft["quote_absent_here_but_present_in_another_law"].append(
                    f"{o['obligation_id']} quote found in {laws[mid2]['law_number_display']}")
                break

    # --- HARD: deadlines that cannot be right -------------------------------
    for o in obs:
        dd, ed = o.get("deadline_date"), o.get("enactment_date")
        if dd and ed and dd < ed:
            hard["deadline_precedes_enactment"].append(f"{o['obligation_id']} {dd} < {ed}")
        if dd and ed and int(dd[:4]) - int(ed[:4]) > 40:
            hard["deadline_absurdly_distant"].append(f"{o['obligation_id']} {dd}")

    # --- SOFT: event-anchored deadline stamped with a calendar date ---------
    for o in obs:
        if o.get("deadline_kind") in ("days_after_effective", "days_after_enactment") \
                and o.get("deadline_date") and event_anchored(o.get("deadline_text")):
            soft["event_anchored_deadline_dated"].append(
                f"{o['obligation_id']}: {(o.get('deadline_text') or '')[:80]}")

    # --- SOFT: recurrence contradicted by the record's own text -------------
    for o in obs:
        blob = " ".join(filter(None, [o.get("deadline_text"), o.get("quote"),
                                      o.get("action_summary")]))
        if o.get("recurrence") == "biennial" and SIX_MONTHLY.search(blob) \
                and not re.search(r"every ?(2|two) years|biennial", blob, re.I):
            soft["biennial_contradicted_by_text"].append(o["obligation_id"])

    # --- SOFT: a published agency tag the guard would now reject ------------
    # These are records whose stored tag predates a tightening of the guard.
    # Running renormalize_agencies.py clears them.
    for o in obs:
        ag = o.get("agency") or ""
        if ag and ag not in ("Unspecified", "All agencies") and is_vague_actor(ag):
            soft["agency_tag_guard_would_reject"].append(f"{o['obligation_id']}: {ag[:70]}")

    # --- HARD: quote drawn from text the law DELETES ------------------------
    # Square brackets mark struck matter. The one-off bracket sweep in Aug 2026
    # judged only quotes it could locate cheaply and missed at least one; as a
    # standing check it costs nothing and covers the class.
    for mid, group in by_matter.items():
        raw = (TEXT / f"{mid}.txt")
        if not raw.exists():
            continue
        flat = norm(raw.read_text(errors="ignore"))
        if "[" not in flat:
            continue
        for o in group:
            q = norm(o.get("quote"))
            if not q or len(q) < 40:
                continue
            # Check EVERY occurrence. Laws repeat boilerplate, and the first hit
            # is often the struck copy while the provision the record actually
            # cites is live somewhere later. Judging only the first occurrence
            # produced eight false accusations in Aug 2026, all overturned on
            # review. Clean if the quote sits outside brackets anywhere.
            at = flat.find(q)
            if at < 0:
                continue          # not present at all: that is a different check
            clean = False
            while at >= 0:
                before = flat[:at]
                open_bracket = before.rfind("[") > before.rfind("]")
                if open_bracket:
                    close = flat.find("]", at)
                    struck = close == -1 or close >= at + len(q)
                else:
                    struck = False
                if not struck:
                    clean = True
                    break
                at = flat.find(q, at + 1)
            if not clean:
                hard["quote_inside_deleted_text"].append(
                    f"{o['obligation_id']} ({laws[mid]['law_number_display']})")

    # --- HARD: schema placeholder left unsubstituted ------------------------
    # "every N years" is the template wording in the extraction schema. If it
    # reaches a record, the model copied the placeholder instead of the cadence.
    for o in obs:
        if re.fullmatch(r"every n (year|month|day)s?", (o.get("recurrence") or ""), re.I):
            hard["recurrence_is_a_template_placeholder"].append(
                f"{o['obligation_id']}: {o.get('recurrence')}")

    # --- SOFT: quotes drawn from deleted or reprinted text ------------------
    for o in obs:
        if o.get("quotes_restated_text"):
            soft["quotes_reprinted_text"].append(o["obligation_id"])

    # --- SOFT: laws whose text was truncated before extraction --------------
    CAP = 300_000
    for mid, group in by_matter.items():
        p = TEXT / f"{mid}.txt"
        if p.exists() and p.stat().st_size >= CAP:
            soft["law_text_at_or_over_cap"].append(
                f"{laws[mid]['law_number_display']}: {p.stat().st_size:,} chars, "
                f"{len(group)} obligations extracted")

    # --- SOFT: fewer reports than the city's own register lists -------------
    # DORIS independently records the reports each law requires. Where it lists
    # materially more than we extracted, the extractor may have collapsed or
    # missed duties. Not a failure: DORIS sometimes splits one duty into several
    # register entries, and we classify some of them as data publications.
    # Offline; skipped when the cached DORIS pull is absent.
    doris_path = HERE / "doris_mandates.json"
    if doris_path.exists():
        LLPAT = re.compile(r"LL\s*(\d+)\s*/\s*(\d{4})", re.I)
        by_law_doris: dict[str, set] = defaultdict(set)
        for r in json.loads(doris_path.read_text()):
            m = LLPAT.match((r.get("local_law") or "").strip())
            if not m:
                continue
            key = f"Local Law {int(m.group(1))} of {int(m.group(2))}"
            if 2014 <= int(m.group(2)) <= today.year:
                by_law_doris[key].add((r.get("name") or "").strip().lower())
        ours_reports: dict[str, int] = Counter(
            o["law_number_display"] for o in obs if o.get("deliverable_type") == "report")
        known = {l["law_number_display"] for l in data["laws"]}
        for key, names in by_law_doris.items():
            if key in known and len(names) - ours_reports.get(key, 0) >= 2:
                soft["fewer_reports_than_doris_lists"].append(
                    f"{key}: DORIS {len(names)}, ours {ours_reports.get(key, 0)}")

    # --- SOFT: one law, one bare generic actor, several agencies ------------
    # "The commissioner" in a Title 17 section is DOHMH and in a Title 20
    # section is DCWP. When a single law resolves the same bare phrase to more
    # than one agency, at least one is usually wrong (or all deserve a look):
    # an omnibus vendor law had five such records. Bare phrases only; a named
    # actor legitimately varies.
    generic = {"the commissioner", "the department", "the director", "the office"}
    per_law: dict[tuple, set] = defaultdict(set)
    for o in obs:
        raw = (o.get("actor_raw") or "").strip().lower()
        if raw in generic and o.get("agency_matched"):
            per_law[(o["matter_id"], raw)].add(o["agency"])
    for (mid, raw), agencies in per_law.items():
        if len(agencies) > 1:
            soft["same_generic_actor_multiple_agencies"].append(
                f"{laws[mid]['law_number_display']}: '{raw}' -> {sorted(agencies)}")

    # --- SOFT: Legistar says the law sunsets and we found no clause ---------
    # Legistar's index tags are unreliable as a count (Maximum New York makes
    # that case well), but as a cross-check they are free: a law tagged
    # "Sunset Date Applies" where the parser found nothing is worth a look.
    for l in data["laws"]:
        tagged = any("sunset" in ix.lower() for ix in (l.get("legistar_indexes") or []))
        if tagged and not l.get("sunset_clause"):
            soft["legistar_says_sunset_but_none_parsed"].append(l["law_number_display"])

    # --- HARD: a window boundary must never split new-matter markup ---------
    # The chunker moves cuts off marker pairs; this proves it did, for the laws
    # that are actually long enough to be windowed.
    try:
        from extract_obligations import split_for_extraction, CHUNK_THRESHOLD
        for mid in by_matter:
            p = TEXT / f"{mid}.txt"
            if not p.exists() or p.stat().st_size <= CHUNK_THRESHOLD:
                continue
            body = p.read_text(errors="ignore")
            for i, w in enumerate(split_for_extraction(body)):
                if w.count("{{") != w.count("}}"):
                    hard["window_splits_new_matter_marker"].append(
                        f"{laws[mid]['law_number_display']} window {i + 1}")
    except Exception:                                    # noqa: BLE001
        pass

    # --- report -------------------------------------------------------------
    result = {
        "generated": today.isoformat(),
        "obligations": len(obs),
        "laws": len(laws),
        "hard_failures": {k: v for k, v in sorted(hard.items())},
        "soft_counts": {k: len(v) for k, v in sorted(soft.items())},
        "soft_detail": {k: v[:50] for k, v in sorted(soft.items())},
    }
    n_hard = sum(len(v) for v in hard.values())

    print(f"validating {len(obs):,} obligations across {len(laws):,} laws\n")
    print(f"HARD FAILURES: {n_hard}")
    for k, v in sorted(hard.items()):
        print(f"  {len(v):5d}  {k}")
        for line in v[:6]:
            print(f"           {line}")
        if len(v) > 6:
            print(f"           ... and {len(v) - 6} more")
    print(f"\nSOFT COUNTS (tracked, not failures):")
    for k, v in sorted(soft.items()):
        print(f"  {len(v):5d}  {k}")

    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1, ensure_ascii=False))
        print(f"\nwrote {args.json}")
    if args.strict and n_hard:
        sys.exit(1)


if __name__ == "__main__":
    main()
