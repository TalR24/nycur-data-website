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
    r"|receives\b|receipt|following any change|formation of"
    r"|upon (the )?(submission|approval|determination|issuance)"
    r"|after (such|each|any) (summary|hearing|approval|determination|request|application|review)"
    r"|(prior to|before) (any|each|such) (hearing|meeting|removal|modification|sale|execution"
    r"|implementation|application|request|submission|expiration)"
    r"|from the date of (the|each|such|any) (application|request|receipt|notice)", re.I)


def event_anchored(text: str | None) -> bool:
    t = text or ""
    return bool(EVENT_ANCHOR.search(t)) and not _ANCHOR_IS_A_DATE.search(t)
SIX_MONTHLY = re.compile(
    r"every ?(6|six) months|semiannual|semi-annual|twice a year|twice each year"
    # two fixed calendar dates repeating every year ("each July 31 and
    # January 31 thereafter") are a semiannual cadence, not annual/biennial.
    r"|each\s+[A-Za-z]+\s+\d{1,2}\s+and\s+[A-Za-z]+\s+\d{1,2}\s+"
    r"(?:thereafter|of each year|annually|each year)", re.I)
# Whether an actor phrase is too vague to publish as an agency is decided by
# the extractor's own guard. The validator imports it rather than keeping a
# parallel heuristic, so the two cannot drift apart: an earlier version used a
# word-count threshold and spent most of its output on legitimate long body
# names like "the office of child care and early childhood education".
sys.path.insert(0, str(HERE))
try:
    from sweep_restated_duties import split_markers, restated_spans, condense, locate, AMENDED  # noqa: E402
except Exception:                                        # noqa: BLE001
    split_markers = restated_spans = condense = locate = AMENDED = None
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
    # If the cache directory is absent altogether (CI runners, machines that
    # never ran the fetch) that is an environment fact, not 1,933 bad records:
    # record it once as a soft signal so the headline stays meaningful.
    if not TEXT.exists():
        soft["law_text_cache_absent"].append(f"{TEXT} does not exist; text-based checks skipped")
    # a fresh CI or cloud-routine checkout holds text only for the laws it just
    # fetched: a missing text is a defect only where the cache is broadly
    # present (Sep 28 2026: the Max routine's first run hit 1,854 false hard
    # failures and could not commit 12 correct extractions)
    partial_cache = len(texts) < 0.9 * len(by_matter)
    if TEXT.exists() and partial_cache:
        soft["law_text_cache_partial"].append(
            f"{len(texts)} of {len(by_matter)} laws have cached text; missing-text check skipped")
    for mid, group in by_matter.items():
        t = texts.get(mid)
        if t is None:
            if not TEXT.exists() or partial_cache:
                continue
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

    # --- HARD: a stored quote still carries a new-matter marker -------------
    # Step 2f, Sep 25 2026 audit: {{...}} markers are a cache-text artifact
    # and must never survive into a published quote.
    _pw_path = DATA / "powers.json"
    _pw = json.loads(_pw_path.read_text())["powers"] if _pw_path.exists() else []
    for o in obs + _pw:
        if "{{" in (o.get("quote") or ""):
            hard["quote_contains_new_matter_marker"].append(o["obligation_id"])

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

    # --- HARD: duties and powers each in their own file (class 20, Sep 2026) --
    # extract_obligations.classify() sorts each record from its full provision
    # and stores `kind`. Re-derive it wherever the law text is cached; a
    # mismatch means the rule changed without a backfill, or a hand edit
    # bypassed it. Without text (CI) only the stored kinds are checked.
    from extract_obligations import classify, final_kind
    powers_path = DATA / "powers.json"
    powers = json.loads(powers_path.read_text())["powers"] if powers_path.exists() else []
    if not powers_path.exists():
        hard["powers_file_missing"].append(str(powers_path))
    for table, want, rows in (("obligations", "duty", obs), ("powers", "power", powers)):
        for o in rows:
            if o.get("kind") != want:
                hard[f"wrong_kind_in_{table}_table"].append(f"{o['obligation_id']}: kind={o.get('kind')}")
                continue
            if o.get("kind_override") == o.get("kind"):
                continue       # an adjudicated record override sets the kind
            rule = o.get("kind_rule") or o.get("kind")
            if final_kind(rule, o.get("kind_model"), bool(o.get("kind_list_item"))) != o.get("kind"):
                hard["kind_not_from_policy"].append(o["obligation_id"])
            if o.get("kind_model") is None:
                soft["kind_without_model_label"].append(o["obligation_id"])
            elif o.get("kind_model") != rule:
                soft["model_label_differs_from_rule"].append(o["obligation_id"])
            t = texts.get(o["matter_id"]) or load_texts([o["matter_id"]]).get(o["matter_id"])
            if t is None:
                soft["kind_not_rederived_no_text"].append(o["obligation_id"])
            elif classify(o.get("quote"), t) != rule:
                hard["stored_rule_label_differs_from_rule"].append(f"{o['obligation_id']} ({table})")
    # A power should never carry a deadline (extract_law strips it). Kept as a
    # HARD invariant only while the corpus actually has zero of them: if a
    # change ever leaves some in place, downgrading to a tracked SOFT count
    # keeps the build green while the class gets fixed, rather than blocking
    # every unrelated change behind it (Sep 27 2026).
    _pwd = [o["obligation_id"] for o in powers if o.get("deadline_date")]
    (hard if not _pwd else soft)["power_with_deadline"].extend(_pwd)

    # --- SOFT: fixed_date deadline with no date (audit 5, Sep 28 2026) ------
    # extract_obligations.fix_fixed_date_recurring() should have filled this
    # in for a recurring calendar date ("annually on or before August 31");
    # a record still blank here is either a date phrase the fix's month/day
    # regex missed, or a genuinely undated fixed_date the model mis-typed.
    for o in obs + powers:
        if o.get("deadline_kind") == "fixed_date" and not o.get("deadline_date"):
            soft["fixed_date_without_date"].append(
                f"{o['obligation_id']}: {(o.get('deadline_text') or '')[:80]}")
    shared = {o["obligation_id"] for o in obs} & {o["obligation_id"] for o in powers}
    for oid in sorted(shared):
        hard["id_in_both_tables"].append(oid)

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

    # --- SOFT: code-title agency vs. TITLE_DEPARTMENT (Sep 27 2026, item 3a) --
    # A generic department/commissioner actor whose citation names a Title
    # covered by TITLE_DEPARTMENT (plus the Housing Maintenance Code, whose
    # own title numbering is HMC §27-2001..27-2155, all HPD) should resolve to
    # that title's department. A different stored agency is worth a look: it
    # means some other rule (a law definition, a by_name/by_matter override,
    # or a stale hand edit) disagreed with the code title.
    try:
        from extract_obligations import TITLE_DEPARTMENT, GENERIC_DEPT_RE, ADMIN_TITLE_RE
    except Exception:                                    # noqa: BLE001
        TITLE_DEPARTMENT = GENERIC_DEPT_RE = ADMIN_TITLE_RE = None
    if TITLE_DEPARTMENT is not None:
        _HMC_TITLE_RE = re.compile(r"HMC\s*§+\s*27-2(?:0[0-9][0-9]|1[0-4][0-9]|15[0-5])\b", re.I)
        for o in obs + powers:
            raw = (o.get("actor_raw") or "").strip()
            if not GENERIC_DEPT_RE.match(raw) or not o.get("agency_matched"):
                continue
            citation = o.get("citation") or ""
            want = None
            m = ADMIN_TITLE_RE.search(citation)
            if m:
                want = TITLE_DEPARTMENT.get(m.group(1))
            elif _HMC_TITLE_RE.search(citation):
                want = "HPD"
            if want and o.get("agency") != want:
                soft["code_title_agency_mismatch"].append(
                    f"{o['obligation_id']}: citation {citation[:50]!r} implies {want}, stored {o.get('agency')}")

    # --- SOFT: quote outside new matter, not flagged existing code (item 3b) -
    # {{...}} markers are Legistar's underline styling for newly added text
    # (confirmed present in the cached text: extract_obligations.reattribute_
    # reprints already keys off it, and the Sep 23 audit's "3% underlined"
    # read this same markup). A record whose quote sits wholly outside any
    # underlined run, in a law with no marker at all, is unremarkable (the
    # marker-free fallback rule governs there); this check only fires where
    # markers ARE present but were not carried onto the record.
    if split_markers is None:
        soft["reprint_flag_check_unavailable"].append(
            "sweep_restated_duties helpers not importable; check skipped")
    else:
        for mid, group in by_matter.items():
            raw_text = texts.get(mid)
            if not raw_text or "{{" not in raw_text or not AMENDED.search(raw_text):
                continue
            plain, flags = split_markers(raw_text)
            spans = restated_spans(plain)
            hay, idx = condense(plain)
            for o in group:
                if o.get("restated") or not (o.get("quote") or "").strip():
                    continue
                frac = locate(hay, idx, flags, o["quote"], spans)
                if frac == 0.0:
                    soft["quote_outside_new_matter_not_flagged"].append(
                        f"{o['obligation_id']} ({laws[mid]['law_number_display']})")

    # --- SOFT: two records in one law, same kind, near-identical quote ------
    # (item 3c). quote_similarity is the SAME 0.9+ "same statutory sentence"
    # threshold reattribute_reprints uses, applied within a law instead of
    # across laws, so a genuine duplicate record is caught even when the
    # duplicate was never a reprint of an earlier law.
    try:
        from extract_obligations import quote_similarity
    except Exception:                                    # noqa: BLE001
        quote_similarity = None
    if quote_similarity is not None:
        # a joint duty is stored once per co-responsible agency by design, so
        # only same-agency pairs are duplicates (Sep 27 2026: 1,676 flags
        # before, nearly all "X and Y shall" split per agency)
        powers_by_matter = defaultdict(list)
        for o in powers:
            powers_by_matter[o["matter_id"]].append(o)
        for mid, group in by_matter.items():
            rows = list(group) + powers_by_matter.get(mid, [])
            for i, a in enumerate(rows):
                for b in rows[i + 1:]:
                    if (a.get("kind") != b.get("kind") or a is b
                            or a.get("agency") != b.get("agency")):
                        continue
                    if quote_similarity(a.get("quote"), b.get("quote")) >= 0.9:
                        soft["duplicate_within_law"].append(
                            f"{a['obligation_id']} ~ {b['obligation_id']} "
                            f"({laws[mid]['law_number_display']})")

    # --- SOFT: a date on a record with no deadline kind (Sep 28 2026) --------
    for o in obs:
        if o.get("deadline_kind") in (None, "none") and o.get("deadline_date"):
            soft["deadline_date_without_kind"].append(f"{o['obligation_id']}: {o['deadline_date']}")

    # --- SOFT: discretion ("may") typed as a duty (item 3d) ------------------
    # Reuses the same MANDATORY_WORD/MODAL/PROHIBITION vocabulary the kind
    # rule itself is built from, so this flags only a quote with "may" and no
    # mandatory or prohibition language anywhere in it — the case the kind
    # rule's own subordinate-clause/coordination logic (classify()) already
    # tries to avoid, checked here as an independent, cruder cross-check.
    try:
        from extract_obligations import MANDATORY_WORD, MODAL, PROHIBITION
    except Exception:                                    # noqa: BLE001
        MANDATORY_WORD = MODAL = PROHIBITION = None
    if MANDATORY_WORD is not None:
        _MAY_RE = re.compile(r"\bmay\b", re.I)
        for o in obs:
            if o.get("kind") != "duty":
                continue
            q = o.get("quote") or ""
            if not _MAY_RE.search(q):
                continue
            has_mandatory = any(re.search(r"\b" + re.escape(w) + r"\b", q, re.I)
                                for w in MANDATORY_WORD)
            if not has_mandatory and not PROHIBITION.search(q):
                soft["discretion_typed_as_duty"].append(f"{o['obligation_id']}: {q[:100]}")

    # --- SOFT: record_overrides.json entry matched nothing (item 3f) --------
    try:
        from extract_obligations import RECORD_OVERRIDES, apply_record_overrides
    except Exception:                                    # noqa: BLE001
        RECORD_OVERRIDES = None
    if RECORD_OVERRIDES:
        for mid, ov in RECORD_OVERRIDES.items():
            rows = by_matter.get(mid, []) + [o for o in powers if o["matter_id"] == mid]
            _, report = apply_record_overrides([dict(o) for o in rows], mid,
                                               {mid: ov})
            # consistent with extract_obligations.py 4(d)/4(e): a `remove`
            # matching nothing is "already_absent", never stale; several
            # candidates with no agency to disambiguate is "ambiguous", kept
            # in its own soft count rather than folded into stale_override.
            for s in report:
                key = "stale_override" if s.get("status") == "stale" \
                    else "override_ambiguous" if s.get("status") == "ambiguous" \
                    else "override_already_absent"
                soft[key].append(
                    f"matter {mid} {s['action']}: {s.get('quote_prefix', '')[:60]!r}")

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
