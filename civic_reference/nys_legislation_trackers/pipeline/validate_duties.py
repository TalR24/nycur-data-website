#!/usr/bin/env python3
"""Regression checks for the NYS duties and powers, the same classes as the Council validate_obligations.py that apply
to state law (quote present in its law text and not drawn from deleted matter, kind sorted into the right file, deadline
sanity, unique ids, agency matched share). Offline, no model calls.

    python3 validate_duties.py [--duties F] [--powers F] [--strict]
Prints HARD FAILURES: N. Hard = structural problems with an objectively right answer; soft = counts to track.
"""
import argparse, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
COUNCIL = HERE.parent.parent / "legislation_implementation_tracker" / "pipeline"
sys.path.insert(0, str(COUNCIL))
import extract_obligations as eo  # noqa: E402

TEXT = HERE / "cache" / "text_marked"
JURISDICTIONS = {"state", "local", "nyc", None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duties", default=str(DATA / "duties.json"))
    ap.add_argument("--powers", default=str(DATA / "powers.json"))
    ap.add_argument("--text", default=str(TEXT))
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    duties = json.loads(Path(a.duties).read_text())["obligations"] if Path(a.duties).exists() else []
    powers = json.loads(Path(a.powers).read_text())["powers"] if Path(a.powers).exists() else []
    allrec = [(o, "duty") for o in duties] + [(o, "power") for o in powers]
    texts = {}
    hard, soft = defaultdict(list), defaultdict(list)

    def text_of(o):
        k = o["matter_id"]
        if k not in texts:
            p = Path(a.text) / (k + ".txt")
            texts[k] = p.read_text() if p.exists() else ""
        return texts[k]

    for oid, n in Counter(o["obligation_id"] for o, _ in allrec).items():
        if n > 1:
            hard["duplicate_obligation_id"].append(oid)
    for o, filekind in allrec:
        oid, t = o["obligation_id"], text_of(o)
        if o.get("kind") != filekind:
            hard["kind_in_wrong_file"].append("%s kind=%s in %s file" % (oid, o.get("kind"), filekind))
        if len(t) < 400:
            hard["law_text_missing"].append(oid)
        elif not (o.get("quote") or "").strip():
            hard["quote_empty"].append(oid)
        elif not eo.quote_present(o["quote"], t):
            (hard if o.get("quote_verified") else soft)["quote_not_in_law_text"].append("%s (%s)" % (oid, "flagged verified" if o.get("quote_verified") else "already unverified"))
        if "{{" in (o.get("quote") or "") or "}}" in (o.get("quote") or ""):
            hard["quote_carries_marker"].append(oid)
        if o.get("quote_has_deleted_text"):
            soft["quote_had_deleted_text_stripped"].append(oid)
        dd, ed = o.get("deadline_date"), o.get("enactment_date")
        if dd and ed and dd < ed:
            hard["deadline_precedes_enactment"].append("%s %s < %s" % (oid, dd, ed))
        if dd and ed and int(dd[:4]) - int(ed[:4]) > 40:
            hard["deadline_absurdly_distant"].append("%s %s" % (oid, dd))
        if filekind == "power" and (dd or o.get("deadline_kind") not in (None, "none")):
            hard["power_with_deadline"].append(oid)
        if o.get("jurisdiction") not in JURISDICTIONS:
            hard["bad_jurisdiction"].append("%s %s" % (oid, o.get("jurisdiction")))
        if re.search(r"<[^>]{3,}>", o.get("action_summary") or "") and o.get("action_summary", "").startswith("<"):
            hard["schema_placeholder_left"].append(oid)
        if o.get("effective_date") and not re.match(r"^\d{4}-\d{2}-\d{2}$", o["effective_date"]):
            hard["bad_effective_date"].append(oid)
        ag = o.get("agency") or ""
        if not o.get("agency_matched") and ag not in ("Unspecified", "All agencies"):
            soft["agency_unmatched"].append("%s: %s" % (oid, ag[:60]))
        if ag and ag not in ("Unspecified", "All agencies") and eo.is_vague_actor(ag):
            soft["agency_tag_vague"].append("%s: %s" % (oid, ag[:60]))
    n = len(allrec)
    matched = sum(1 for o, _ in allrec if o.get("agency_matched"))
    print("records: %d duties, %d powers" % (len(duties), len(powers)))
    if n:
        print("agency matched: %d of %d (%.1f%%)" % (matched, n, 100.0 * matched / n))
        print("jurisdiction:", dict(Counter(o.get("jurisdiction") for o, _ in allrec)))
    for title, d in (("HARD", hard), ("SOFT", soft)):
        for k, v in sorted(d.items()):
            print("%5d  %s: %s" % (len(v), k, "; ".join(v[:3])))
    n_hard = sum(len(v) for v in hard.values())
    print("HARD FAILURES: %d" % n_hard)
    sys.exit(1 if (a.strict and n_hard) else 0)


if __name__ == "__main__":
    main()
