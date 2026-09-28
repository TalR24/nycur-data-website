#!/usr/bin/env python3
"""
Seeded, stratified sampler for the audit harness (Q/).

Draws a sample of laws (obligations/powers tracker) or bills (fiscal tracker)
for a human audit round, excludes anything already in the gold set, and
writes a packet per item plus a key.json (labels -> record ids/snapshots) and
a manifest.json (seed, strata sizes, data file hashes) so the round can be
re-scored later with score.py and merged with ingest.py.

Usage:
    python3 sample.py --tracker obligations --n 20 --seed 1 --out DIR
    python3 sample.py --tracker fiscal --n 10 --seed 1 --strata tricky --out DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent  # data_website/
LIT = REPO / "civic_reference" / "legislation_implementation_tracker"
LIT_PIPELINE = LIT / "pipeline"
FISCAL_TRACKER = REPO / "civic_reference" / "nyc_council_fiscal_impacts_tracker"
FISCAL_PIPELINE = REPO / "pipeline"

OBLIGATIONS_PATH = LIT / "data" / "obligations.json"
POWERS_PATH = LIT / "data" / "powers.json"
EXCLUSIONS_PATH = LIT_PIPELINE / "reextract_exclusions.json"
TEXT_CACHE = LIT_PIPELINE / "cache" / "text"
FISCAL_DATA_PATH = FISCAL_TRACKER / "data" / "fiscal_impacts.json"

GOLD_OBLIGATIONS = HERE / "gold_obligations.json"
GOLD_FISCAL = HERE / "gold_fiscal.json"

sys.path.insert(0, str(LIT_PIPELINE))
from extract_obligations import normalize_quote  # noqa: E402

sys.path.insert(0, str(FISCAL_PIPELINE))


def sha256_of(path: Path) -> str:
    if not path.exists():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def gold_matter_ids(gold_path: Path) -> set[str]:
    gold = load_json(gold_path, [])
    return {str(g.get("matter_id")) for g in gold if g.get("matter_id")}


# ── Obligations / Powers ────────────────────────────────────────────────────

def load_obl_pow_by_law() -> dict[str, list[dict]]:
    obl = load_json(OBLIGATIONS_PATH, {}).get("obligations", [])
    pow_ = load_json(POWERS_PATH, {}).get("powers", [])
    by_law: dict[str, list[dict]] = {}
    for r in obl + pow_:
        by_law.setdefault(str(r["matter_id"]), []).append(r)
    return by_law


def obligations_strata(by_law: dict[str, list[dict]], today: date) -> dict[str, set[str]]:
    exclusions = set((load_json(EXCLUSIONS_PATH, {}) or {}).get("matters", {}).keys())
    strata: dict[str, set[str]] = {"sonnet": set(), "protected": set(), "definitions": set(), "recent": set()}
    for mid, records in by_law.items():
        if mid in exclusions:
            strata["protected"].add(mid)
        else:
            strata["sonnet"].add(mid)
        if any((r.get("agency_source") == "law_definition") for r in records):
            strata["definitions"].add(mid)
        enact = None
        for r in records:
            if r.get("enactment_date"):
                enact = r["enactment_date"]
                break
        if enact:
            try:
                d = datetime.strptime(enact[:10], "%Y-%m-%d").date()
                if (today - d).days <= 120:
                    strata["recent"].add(mid)
            except ValueError:
                pass
    return strata


DEFINITION_RE = re.compile(r"^[^\n]{0,400}\b(shall mean|means:?)\b[^\n]{0,400}$", re.I | re.M)


def build_law_packet(matter_id: str, records: list[dict]) -> tuple[str, dict]:
    """Returns (packet_text, key_entries) for one law. key_entries maps
    'R1'..'Rn' to {obligation_id, matter_id, snapshot}."""
    text_path = TEXT_CACHE / f"{matter_id}.txt"
    law_text = text_path.read_text(errors="ignore") if text_path.exists() else ""

    if len(law_text) > 60_000 and law_text:
        pieces = []
        seen_spans: list[tuple[int, int]] = []
        for m in DEFINITION_RE.finditer(law_text):
            pieces.append(m.group(0))
        norm_text = normalize_quote(law_text)
        for r in records:
            q = normalize_quote(r.get("quote") or "")
            if not q:
                continue
            idx = norm_text.find(q[:200])
            if idx == -1:
                continue
            # map back approximately: use proportional offset since normalize
            # collapses whitespace; good enough for a human-readable window
            approx = int(idx * len(law_text) / max(len(norm_text), 1))
            start, end = max(0, approx - 3000), min(len(law_text), approx + 3000)
            seen_spans.append((start, end))
        seen_spans.sort()
        merged = []
        for s, e in seen_spans:
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        windows = [law_text[s:e] for s, e in merged]
        body = "\n\n[...definitions...]\n\n".join(pieces) + "\n\n[...window...]\n\n" + "\n\n[...window...]\n\n".join(windows)
    else:
        body = law_text

    lines = [f"LAW {matter_id}", "", "===== ENACTED TEXT ({{...}} marks new matter) =====", body, "",
              f"===== RECORDS: {len(records)} ====="]
    key_entries: dict[str, dict] = {}
    for i, r in enumerate(records, 1):
        label = f"R{i}"
        kind = r.get("kind") or r.get("kind_rule") or r.get("kind_model")
        lines.append(
            f"- {label} kind={kind} agency={r.get('agency')} unit={r.get('agency_unit')} "
            f"actor={r.get('actor_raw')!r} existing_code={bool(r.get('restated'))}"
        )
        lines.append(f"  summary: {r.get('action_summary')}")
        lines.append(f"  citation: {r.get('citation')} | deliverable: {r.get('deliverable_type')}")
        lines.append(f"  deadline: {r.get('deadline_kind')} | {r.get('deadline_text')} | {r.get('deadline_date')} | recurrence={r.get('recurrence')}")
        lines.append(f"  quote: {r.get('quote')}")
        key_entries[label] = {
            "obligation_id": r.get("obligation_id"),
            "matter_id": matter_id,
            "snapshot": r,
        }
    return "\n".join(lines), key_entries


def sample_obligations(n: int, seed: int, strata_wanted: list[str] | None, out: Path) -> None:
    by_law = load_obl_pow_by_law()
    today = date.today()
    strata = obligations_strata(by_law, today)
    excluded = gold_matter_ids(GOLD_OBLIGATIONS)
    for k in strata:
        strata[k] -= excluded

    wanted = strata_wanted or [k for k in ("sonnet", "protected", "definitions", "recent") if strata[k]]
    rng = random.Random(seed)
    picked: list[str] = []
    picked_set: set[str] = set()
    remaining_quota = n
    active = list(wanted)
    while remaining_quota > 0 and active:
        share = -(-remaining_quota // len(active))  # ceil
        for stratum in list(active):
            pool = sorted(strata[stratum] - picked_set)
            rng.shuffle(pool)
            take = pool[:share]
            for mid in take:
                if mid not in picked_set:
                    picked.append(mid)
                    picked_set.add(mid)
            if not (strata[stratum] - picked_set):
                active.remove(stratum)
        remaining_quota = n - len(picked)
        if not active:
            break

    picked = picked[:n]
    out.mkdir(parents=True, exist_ok=True)
    key: dict[str, dict] = {}
    strata_sizes = {k: len(strata[k]) for k in strata}
    picked_strata = {mid: [k for k in strata if mid in strata[k]] for mid in picked}

    for mid in picked:
        packet, entries = build_law_packet(mid, sorted(by_law[mid], key=lambda r: r.get("obligation_id") or ""))
        (out / f"{mid}.txt").write_text(packet, encoding="utf-8")
        key[mid] = {"records": entries, "strata": picked_strata[mid]}

    manifest = {
        "tracker": "obligations",
        "seed": seed,
        "n_requested": n,
        "n_sampled": len(picked),
        "strata_requested": wanted,
        "strata_pool_sizes": strata_sizes,
        "excluded_gold_laws": len(excluded),
        "date": today.isoformat(),
        "data_hashes": {
            "obligations.json": sha256_of(OBLIGATIONS_PATH),
            "powers.json": sha256_of(POWERS_PATH),
        },
        "matter_ids": picked,
    }
    (out / "key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"sampled {len(picked)} laws -> {out}")
    print(json.dumps(manifest, indent=1))


# ── Fiscal ───────────────────────────────────────────────────────────────────

def fiscal_stratum(r: dict) -> str:
    if (r.get("time_limited_program") or r.get("total_capital") or r.get("costs_already_in_financial_plan")
            or (r.get("net_fiscal_impact") or 0) > 0):
        return "tricky"
    return "plain"


def sample_fiscal(n: int, seed: int, strata_wanted: list[str] | None, out: Path, fetch: bool = True) -> None:
    records = load_json(FISCAL_DATA_PATH, {}).get("records", [])
    excluded = gold_matter_ids(GOLD_FISCAL)
    by_stratum: dict[str, list[dict]] = {"tricky": [], "plain": []}
    for r in records:
        if str(r.get("matter_id")) in excluded:
            continue
        by_stratum[fiscal_stratum(r)].append(r)

    wanted = strata_wanted or [k for k in ("tricky", "plain") if by_stratum[k]]
    rng = random.Random(seed)
    picked: list[dict] = []
    picked_ids: set[str] = set()
    remaining = n
    active = list(wanted)
    while remaining > 0 and active:
        share = -(-remaining // len(active))
        for stratum in list(active):
            pool = [r for r in by_stratum[stratum] if str(r["matter_id"]) not in picked_ids]
            rng.shuffle(pool)
            for r in pool[:share]:
                picked.append(r)
                picked_ids.add(str(r["matter_id"]))
            if not [r for r in by_stratum[stratum] if str(r["matter_id"]) not in picked_ids]:
                active.remove(stratum)
        remaining = n - len(picked)
        if not active:
            break
    picked = picked[:n]

    out.mkdir(parents=True, exist_ok=True)
    key: dict[str, dict] = {}
    session = None
    if fetch:
        from fetch_fiscal_impacts import create_session, get_fiscal_attachment, download_docx, extract_docx_text
        session = create_session()

    for r in picked:
        mid = str(r["matter_id"])
        text = ""
        if fetch and session is not None:
            try:
                att_id, att_guid = get_fiscal_attachment(session, mid, r.get("legistar_guid", ""))
                if att_id:
                    p = download_docx(session, att_id, att_guid)
                    if p:
                        text = extract_docx_text(p)
            except Exception as e:  # noqa: BLE001
                text = f"[fetch failed: {e}]"
        packet = (
            f"BILL {mid}\n\n===== FISCAL IMPACT STATEMENT =====\n{text}\n\n"
            f"===== TRACKER RECORD =====\n{json.dumps(r, indent=1, ensure_ascii=False)}"
        )
        (out / f"{mid}.txt").write_text(packet, encoding="utf-8")
        key[mid] = {"stratum": fiscal_stratum(r), "snapshot": r}

    manifest = {
        "tracker": "fiscal",
        "seed": seed,
        "n_requested": n,
        "n_sampled": len(picked),
        "strata_requested": wanted,
        "strata_pool_sizes": {k: len(v) for k, v in by_stratum.items()},
        "excluded_gold_bills": len(excluded),
        "date": date.today().isoformat(),
        "fetched_live": fetch,
        "data_hashes": {"fiscal_impacts.json": sha256_of(FISCAL_DATA_PATH)},
        "matter_ids": [str(r["matter_id"]) for r in picked],
    }
    (out / "key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"sampled {len(picked)} bills -> {out}")
    print(json.dumps(manifest, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracker", choices=["obligations", "fiscal"], required=True)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--strata", nargs="*", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-fetch", action="store_true", help="fiscal: skip live statement fetch")
    args = ap.parse_args()
    out = Path(args.out)
    if args.tracker == "obligations":
        sample_obligations(args.n, args.seed, args.strata, out)
    else:
        sample_fiscal(args.n, args.seed, args.strata, out, fetch=not args.no_fetch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
