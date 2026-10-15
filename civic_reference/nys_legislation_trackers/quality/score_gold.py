#!/usr/bin/env python3
"""Score the stored database against quality/gold.json. No model calls.
Usage: score_gold.py [--data-dir DIR] [--gold PATH] [--json OUT]"""
import argparse
import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gold_lib import SCORED_FIELDS, agency_code, agency_equal, is_act_clause, quote_score, quotes_match, wilson

T = os.path.dirname(HERE)


def load(p):
    with open(p) as f:
        return json.load(f)


def stored_records(data_dir):
    out = []
    for sub, key in (("duties", "obligations"), ("powers", "powers")):
        for p in sorted(glob.glob(os.path.join(data_dir, sub, "*.json"))):
            out += [dict(r, _table=sub) for r in load(p)[key]]
    return out


def best_match(rec, items):
    """Item for a stored record: same-generation id first, else best quote overlap >= 0.5."""
    qs = [q for q in (rec.get("quote"), rec.get("quote_original")) if q]
    for it in items:
        s = it["source"]
        if s.get("obligation_id") == rec["obligation_id"]:
            if it["quote"] is None or any(quotes_match(q, it["quote"]) for q in qs):
                return it
    best, bs = None, 0.0
    for it in items:
        if not it["quote"]:
            continue
        sc = max((quote_score(q, it["quote"]) for q in qs), default=0.0)
        if sc >= 0.5 and sc > bs:
            best, bs = it, sc
    return best


def norm(v):
    return None if v in ("", None) else v


def rate(k, n):
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "wilson95": [lo, hi]}


def fmt(r):
    if not r["n"]:
        return "n/a"
    return f"{r['k']}/{r['n']}={r['rate']*100:.1f}% [{r['wilson95'][0]*100:.1f}-{r['wilson95'][1]*100:.1f}]"


def score(gold, data_dir):
    laws = gold["laws"]
    recs = [r for r in stored_records(data_dir) if r["matter_id"] in laws]
    by_law = collections.defaultdict(list)
    for r in recs:
        by_law[r["matter_id"]].append(r)
    n_all = strict = real_ok = ignored = nr_stored = act_clause = 0
    unmatched_stored, field_mismatches, nr_ids = [], [], []
    exp_agencies = set()
    covered = set()
    field_tot, field_ok = collections.Counter(), collections.Counter()
    cls = collections.defaultdict(lambda: collections.Counter())
    unmatched_real = collections.defaultdict(list)
    total_real = 0
    unmatched_items = []
    for law, g in laws.items():
        items = g["items"]
        live = lambda i: not i.get("excluded") and not i["disputed"]
        total_real += sum(1 for i in items if live(i) and i["status"] == "real")
        for r in by_law.get(law, []):
            if is_act_clause(r.get("quote")):
                act_clause += 1
                continue
            it = best_match(r, items)
            if it is not None and not live(it):
                ignored += 1
                continue
            n_all += 1
            if it is None:
                unmatched_stored.append({"obligation_id": r["obligation_id"], "actor_raw": r.get("actor_raw"), "agency": r.get("agency"),
                                         "kind": r.get("kind"), "quote": (r.get("quote") or "")[:160]})
                continue
            if it["status"] == "not_real":
                nr_stored += 1
                nr_ids.append(r["obligation_id"])
                for c in it.get("classes", []):
                    cls[c]["not_real_still_stored"] += 1
                continue
            real_ok += 1
            covered.add((law, it["gold_id"]))
            ok = True
            for f, exp in it["expected_fields"].items():
                if f not in SCORED_FIELDS:
                    continue
                field_tot[f] += 1
                if f in ("agency", "agency_unit"):
                    if exp:
                        exp_agencies.add(exp)
                    same = agency_equal(norm(r.get(f)), norm(exp), r.get("agency_full") if f == "agency" else None)
                else:
                    same = norm(r.get(f)) == norm(exp)
                if same:
                    field_ok[f] += 1
                else:
                    ok = False
                    field_mismatches.append({"obligation_id": r["obligation_id"], "field": f, "stored": r.get(f), "expected": exp, "gold_id": it["gold_id"]})
            strict += ok
            for c in it.get("classes", []):
                cls[c]["matched"] += 1
                cls[c]["strict_ok"] += ok
        for it in items:
            if live(it) and it["status"] == "real":
                for c in it.get("classes", []):
                    cls[c]["real_items"] += 1
                if (law, it["gold_id"]) not in covered:
                    unmatched_real[law].append(it["gold_id"])
                    unmatched_items.append({"gold_id": it["gold_id"], "law": law, "quote": (it["quote"] or "")[:160]})
    ed_k = ed_n = 0
    ed_cache = {}
    for law, g in laws.items():
        e = g.get("effective_date")
        if not e:
            continue
        y = law[:4]
        if y not in ed_cache:
            p = os.path.join(data_dir, "effective_dates", y + ".json")
            ed_cache[y] = load(p) if os.path.exists(p) else {}
        ed_n += 1
        ed_k += (ed_cache[y].get(law) or {}).get("effective_date") == e["expected"]
    n_cov = len(covered)
    res = {
        "gold_built_at": gold["built_at"],
        "data_dir": data_dir,
        "gold_laws": len(laws),
        "stored_records_in_gold_laws": n_all,
        "records_ignored_disputed_or_excluded": ignored,
        "precision_strict": rate(strict, n_all),
        "precision_real": rate(real_ok, n_all),
        "recall": rate(n_cov, total_real),
        "field_accuracy": {f: rate(field_ok[f], field_tot[f]) for f in SCORED_FIELDS},
        "not_real_still_stored": nr_stored,
        "act_clause_records": act_clause,
        "gold_expected_agencies": {"total": len(exp_agencies), "normalize_to_code": sum(1 for e in exp_agencies if agency_code(e)),
                                   "not_normalized": sorted(e for e in exp_agencies if not agency_code(e))},
        "unmatched_stored": unmatched_stored,
        "field_mismatches": field_mismatches,
        "unmatched_real_items": unmatched_items,
        "not_real_still_stored_ids": nr_ids,
        "effective_date_accuracy": rate(ed_k, ed_n),
        "classes": {c: dict(v) for c, v in sorted(cls.items())},
        "unmatched_real_by_law": {l: v for l, v in sorted(unmatched_real.items(), key=lambda kv: -len(kv[1]))},
    }
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.join(T, "data"))
    ap.add_argument("--gold", default=os.path.join(HERE, "gold.json"))
    ap.add_argument("--json", default=os.path.join(HERE, "gold_score.json"))
    ap.add_argument("--laws", help="JSON file with a \"laws\" list of keys: score only those gold laws (pilot comparisons on the same laws)")
    a = ap.parse_args(argv)
    gold = load(a.gold)
    if a.laws:
        keep = set(load(a.laws)["laws"])
        gold = dict(gold, laws={k: v for k, v in gold["laws"].items() if k in keep})
        if a.json == ap.get_default("json"):       # do not overwrite the full-gold score file with a subset
            a.json = os.path.join(HERE, "gold_score_" + os.path.splitext(os.path.basename(a.laws))[0] + ".json")
    res = score(gold, a.data_dir)
    with open(a.json, "w") as f:
        json.dump(res, f, indent=1)
    print(f"gold {res['gold_laws']} laws, {res['stored_records_in_gold_laws']} stored | precision_strict {fmt(res['precision_strict'])} | "
          f"precision_real {fmt(res['precision_real'])} | recall {fmt(res['recall'])} | not_real_still_stored {res['not_real_still_stored']} | "
          f"effective_date {fmt(res['effective_date_accuracy'])}")
    print("field accuracy: " + "; ".join(f"{f} {fmt(r)}" for f, r in res["field_accuracy"].items()))
    print(f"{'class':62} {'real':>5} {'match':>5} {'strict':>6} {'nr_stored':>9}")
    for c, v in res["classes"].items():
        print(f"{c[:62]:62} {v.get('real_items',0):5} {v.get('matched',0):5} {v.get('strict_ok',0):6} {v.get('not_real_still_stored',0):9}")
    return res


if __name__ == "__main__":
    main()
