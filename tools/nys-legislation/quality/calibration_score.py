#!/usr/bin/env python3
"""Score an auditor's calibration laws against the gold verdicts (Oct 20 2026, audit-and-improve: calibrate every night).

usage: calibration_score.py --night TAG --audit quality/nightly/TAG_A.json --gold-verdicts /path/TAG_calibration_gold.json [--letter A]

The gold verdicts file is the sibling draw_sample.py writes next to the auditors' sample file. For each calibration law the
auditor's per-record verdict (correct / wrong / not_real) is compared with the gold item status (real -> correct or wrong,
not_real -> not_real) matched by obligation_id, else by quote overlap. Prints agreement n/N and the disagreements.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gold_lib  # noqa: E402


def gold_status(item):
    return "not_real" if item.get("status") == "not_real" else "real"


def auditor_status(rec):
    return "not_real" if rec.get("verdict") == "not_real" else "real"


def score(audit, gold_verdicts, letter):
    laws = audit.get("_scoring", {}).get("calibration_laws") or [l for l in gold_verdicts if l in audit]
    agree = total = 0
    diffs = []
    for law in laws:
        items = gold_verdicts.get(law) or []
        recs = (audit.get(law) or {}).get("records") or {}
        for rid, rec in recs.items():
            g = next((it for it in items if it.get("obligation_id") == rid or (it.get("gold_id") or "").endswith(rid)), None)
            if g is None:
                q = rec.get("quote") or ""
                g = next((it for it in items if q and gold_lib.quotes_match(q, it.get("quote") or "")), None)
            if g is None:
                continue
            total += 1
            if gold_status(g) == auditor_status(rec):
                agree += 1
            else:
                diffs.append((law, rid, gold_status(g), rec.get("verdict"), (rec.get("note") or "")[:80]))
    return agree, total, diffs, laws


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--night", required=True)
    ap.add_argument("--audit", required=True)
    ap.add_argument("--gold-verdicts", required=True)
    ap.add_argument("--letter", default="")
    a = ap.parse_args(argv)
    audit = json.load(open(a.audit))
    gv = json.load(open(a.gold_verdicts)).get("gold_verdicts") or {}
    agree, total, diffs, laws = score(audit, gv, a.letter)
    pct = (100.0 * agree / total) if total else 0.0
    print("calibration %s %s: %d/%d agree (%.0f%%) on %s" % (a.night, a.letter or "", agree, total, pct, ", ".join(laws)))
    for d in diffs:
        print("  disagree %s %s gold=%s auditor=%s | %s" % d)
    return {"agree": agree, "total": total, "diffs": diffs, "laws": laws}


if __name__ == "__main__":
    main()
