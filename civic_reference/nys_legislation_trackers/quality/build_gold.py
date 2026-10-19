#!/usr/bin/env python3
"""Build quality/gold.json from the nightly blind audits, adjudications and gold_overrides.json.
Usage: build_gold.py [--out PATH] [--data-dir DIR] [--nightly-dir DIR] [--overrides PATH]"""
import argparse
import datetime
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gold_lib import SCORED_FIELDS, quotes_match

T = os.path.dirname(HERE)
ID_RE = re.compile(r"\b(\d{4}-[AS]\d+-\d+)\b")
VERDICTS = {"correct": "correct", "wrong": "wrong", "not_real": "not_real", "not real": "not_real"}


def load(p):
    with open(p) as f:
        return json.load(f)


def law_of(oid):
    return oid[: oid.rindex("-")]


def stored_index(data_dir):
    recs, dropped = {}, {}
    for sub, key in (("duties", "obligations"), ("powers", "powers")):
        for p in glob.glob(os.path.join(data_dir, sub, "*.json")):
            for r in load(p)[key]:
                recs[r["obligation_id"]] = dict(r, _table=sub)
    for p in glob.glob(os.path.join(data_dir, "dropped", "*.json")):
        for r in load(p)["dropped"]:
            dropped[r["obligation_id"]] = r
    return recs, dropped


def read_night(path, skipped):
    """Return (laws, ed) where laws = {law: {"records": {id: entry}, "missed": [..]}}, ed = {law: dict}."""
    d = load(path)
    laws, ed = {}, {}
    if "stored" in d and "auditor" in d:  # 20261008_B shape
        for oid, v in d["stored"].items():
            laws.setdefault(law_of(oid), {"records": {}, "missed": []})["records"][oid] = v
        for m in d.get("missed", []):
            if m.get("law"):
                laws.setdefault(m["law"], {"records": {}, "missed": []})["missed"].append(m)
        for k in ("wrongly_dropped", "effective_dates", "pipeline_findings", "metrics", "blind_items_core"):
            if d.get(k):
                skipped.add(f"{os.path.basename(path)}:{k}")
        return laws, ed
    for k, v in d.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        laws[k] = {"records": v.get("records", {}), "missed": v.get("missed", [])}
        if isinstance(v.get("effective_date"), dict):
            ed[k] = v["effective_date"]
        if v.get("wrongly_dropped"):
            skipped.add(f"{os.path.basename(path)}:wrongly_dropped")
    return laws, ed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "gold.json"))
    ap.add_argument("--data-dir", default=os.path.join(T, "data"))
    ap.add_argument("--nightly-dir", default=os.path.join(HERE, "nightly"))
    ap.add_argument("--overrides", default=os.path.join(HERE, "gold_overrides.json"))
    ap.add_argument("--additions", default=os.path.join(HERE, "gold_verified_additions.json"))
    a = ap.parse_args(argv)

    ov = load(a.overrides)
    rec_ov = ov.get("records", {})
    excl_classes = set(ov.get("exclude_classes", []))
    kept = ov.get("kept_not_real", {})  # Oct 19 2026: not_real items kept on purpose; treated as real
    recs, dropped = stored_index(a.data_dir)

    files = sorted(glob.glob(os.path.join(a.nightly_dir, "*_[AB].json")))
    nights = sorted({os.path.basename(f).rsplit("_", 1)[0] for f in files})
    skipped, report = set(), {"adjudication_not_applied": [], "adjudication_applied": []}
    class_of, excluded_ids = {}, {}  # id -> [class names]
    entries = {}  # (law, oid) -> list of (night, auditor, entry)
    missed = {}  # law -> list of (night, auditor, m)
    eds = {}  # law -> list of (night, auditor, ed)
    audited = set()
    for f in files:
        night, aud = os.path.basename(f)[:-5].split("_")
        laws, ed = read_night(f, skipped)
        d = load(f)
        for c in (d.get("_classes") or []) if isinstance(d, dict) else []:
            for oid in ID_RE.findall(" ".join(map(str, c.get("instances", [])))):
                class_of.setdefault(oid, []).append(c["name"])
        for law, v in laws.items():
            audited.add(law)
            for oid, e in v["records"].items():
                entries.setdefault((law, oid), []).append((night, aud, e))
            for m in v["missed"]:
                missed.setdefault(law, []).append((night, aud, m))
        for law, e in ed.items():
            eds.setdefault(law, []).append((night, aud, e))

    # adjudication entries
    adj_rec = {}
    for f in sorted(glob.glob(os.path.join(a.nightly_dir, "*_adjudication.json"))):
        night = os.path.basename(f).split("_")[0]
        for e in load(f).get("adjudication", []):
            v = str(e.get("verdict", "")) if isinstance(e, dict) else ""
            if not v.startswith(("REFUTED", "NOT CONFIRMED")):
                continue
            rid = e.get("record")
            if rid:
                adj_rec[rid] = (v, night)
            else:
                ids = ID_RE.findall(e.get("claim", ""))
                tag = {"night": night, "claim": e.get("claim", "")[:110], "verdict": v[:40]}
                if ids and all(i in rec_ov for i in ids):
                    tag["covered_by_overrides"] = ids
                    report["adjudication_applied"].append(tag)
                else:
                    report["adjudication_not_applied"].append(tag)

    gold_laws = {}
    counts = {"excluded_override": 0, "excluded_class": 0, "excluded_commission": 0, "excluded_unresolved": 0, "disputed": 0}

    def law_bucket(law):
        return gold_laws.setdefault(law, {"session": int(law[:4]), "items": [], "effective_date": None})

    for (law, oid), lst in sorted(entries.items()):
        latest = max(n for n, _, _ in lst)
        cur = [(n, au, e) for n, au, e in lst if n == latest]
        verdicts = {VERDICTS.get(e.get("verdict"), e.get("verdict")) for _, _, e in cur}
        disputed = len(verdicts) > 1
        verdict = sorted(verdicts)[0] if not disputed else None
        fields = {}
        if verdict == "wrong":
            for _, _, e in cur:
                for k, val in (e.get("fields") or {}).items():
                    if k in fields and fields[k] != val:
                        disputed = True
                    fields[k] = val
        excluded = None
        if oid in rec_ov:
            o = rec_ov[oid]
            if o["verdict"] == "exclude":
                excluded = "override: " + o.get("why", "")
            else:
                verdict, disputed = VERDICTS.get(o["verdict"], o["verdict"]), False
                fields = dict(o.get("fields", {})) if verdict == "wrong" else {}
        elif oid in adj_rec:
            v, nt = adj_rec[oid]
            if v.startswith("NOT CONFIRMED"):
                excluded = f"adjudication {nt}: {v[:60]}"
            else:
                verdict, disputed, fields = "correct", False, {}
        if oid in kept and excluded is None:
            verdict, disputed, fields = "correct", False, {}
        classes = class_of.get(oid, [])
        cur_rec = recs.get(oid)
        drop_rec = dropped.get(oid)
        src = cur_rec or drop_rec
        quote = src.get("quote") if src else None
        if excluded is None and any(c in excl_classes for c in classes):
            excluded = "class: " + ",".join(c for c in classes if c in excl_classes)
            counts["excluded_class"] += 1
        elif excluded is None and quote and re.search(r"reviewed as if it had been received", quote, re.I) and "reviewed_as_if" in excl_classes:
            excluded = "class: reviewed_as_if (quote)"
            counts["excluded_class"] += 1
        elif excluded:
            counts["excluded_override"] += 1
        if excluded is None and quote and re.search(r"legislative bill drafting commission", quote, re.I):
            excluded = "policy: legislative bill drafting commission"
            counts["excluded_commission"] += 1
        if excluded is None and not src:
            excluded = "unresolved: record not in current duties, powers or dropped data"
            counts["excluded_unresolved"] += 1
        if disputed:
            counts["disputed"] += 1
        exp, other = {}, {}
        for k, val in fields.items():
            (exp if k in SCORED_FIELDS else other)[k] = val
        if verdict == "correct" and cur_rec:
            for k in ("agency", "kind", "deadline_kind", "extends_existing", "agency_unit"):
                if k in cur_rec:
                    exp[k] = cur_rec[k]
        n0, a0, _ = cur[0]
        item = {
            "gold_id": oid,
            "kind": (src or {}).get("kind") or (src or {}).get("kind_model") or ("power" if cur_rec and cur_rec["_table"] == "powers" else "duty"),
            "status": "not_real" if verdict == "not_real" else "real",
            "source": {"night": n0, "auditor": a0, "obligation_id": oid},
            "quote": quote,
            "expected_fields": exp,
            "disputed": bool(disputed),
        }
        if src and src.get("quote_original"):
            item["quote_original"] = src["quote_original"]
        if other:
            item["other_fields"] = other
        if excluded:
            item["excluded"] = excluded
        if classes:
            item["classes"] = classes
        if oid in kept:
            item["kept_not_real"] = kept[oid].get("why")
        if len({(n, au) for n, au, _ in lst}) > 1:
            item["also"] = sorted({f"{n}_{au}" for n, au, _ in lst})
        if disputed:
            item["verdicts_seen"] = sorted(str(x) for x in verdicts)
        law_bucket(law)["items"].append(item)

    # blind-verified records the auditors never listed (list of {obligation_id, law, quote, kind, agency, verdict, source})
    added = 0
    if os.path.exists(a.additions):
        have = {i["gold_id"] for g in gold_laws.values() for i in g["items"]}
        for ad in load(a.additions):
            oid, law = ad["obligation_id"], ad.get("law") or law_of(ad["obligation_id"])
            if oid in have or ad.get("verdict") not in ("real", "not_real"):
                continue
            rec = recs.get(oid)
            src_rec = rec or dropped.get(oid) or {}
            item = {
                "gold_id": oid,
                "kind": ad.get("kind") or src_rec.get("kind") or "duty",
                "status": ad["verdict"],
                "source": {"night": "bulk_verification", "auditor": "bulk_verification", "obligation_id": oid, "note": ad.get("source")},
                "quote": ad.get("quote") or src_rec.get("quote"),
                "expected_fields": {k: rec[k] for k in ("agency", "kind", "deadline_kind", "extends_existing", "agency_unit") if k in rec}
                if ad["verdict"] == "real" and rec else {},
                "disputed": False,
            }
            if ad.get("agency"):
                item["agency_hint"] = ad["agency"]
            law_bucket(law)["items"].append(item)
            have.add(oid)
            added += 1
    counts["bulk_verification_added"] = added

    for law, lst in sorted(missed.items()):
        kept_m = []
        for n, au, m in lst:
            q = m.get("quote") or ""
            dup = next((k for k in kept_m if quotes_match(k[1]["quote"], q)), None)
            if dup:
                dup[1].setdefault("also", []).append(f"{n}_{au}:{m.get('blind')}")
                continue
            excl = "policy: legislative bill drafting commission" if re.search(r"legislative bill drafting commission", q, re.I) else None
            if excl:
                counts["excluded_commission"] += 1
            item = {
                "gold_id": f"{law}:{n}:{au}:{m.get('blind')}",
                "kind": m.get("kind") if m.get("kind") in ("duty", "power") else "duty",
                "status": "real",
                "source": {"night": n, "auditor": au, "blind": m.get("blind")},
                "quote": q,
                "expected_fields": {},
                "disputed": False,
            }
            if m.get("agency"):
                item["agency_hint"] = m["agency"]
            if m.get("dropped_by"):
                item["dropped_by"] = m["dropped_by"]
            if excl:
                item["excluded"] = excl
            kept_m.append((None, item))
        for _, it in kept_m:
            law_bucket(law)["items"].append(it)

    ed_conflicts = []
    for law, lst in eds.items():
        latest = max(n for n, _, _ in lst)
        vals = set()
        for n, au, e in lst:
            if n != latest:
                continue
            exp = e.get("stored") if e.get("verdict") == "correct" else e.get("computed")
            if exp:
                vals.add((exp, n))
        if len({v for v, _ in vals}) == 1:
            law_bucket(law)["effective_date"] = {"expected": next(iter(vals))[0], "source_night": latest}
        elif len(vals) > 1:
            ed_conflicts.append(law)
    for law in audited:
        law_bucket(law)

    excluded_laws = sorted(l for l, v in gold_laws.items() if v["items"] and not [i for i in v["items"] if not i.get("excluded")] and not v["effective_date"])
    out = {
        "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "nights": nights,
        "audited_laws": len(audited),
        "excluded_laws": excluded_laws,
        "laws": {l: v for l, v in sorted(gold_laws.items()) if l not in excluded_laws},
        "counts": counts,
        "skipped": sorted(skipped),
        "effective_date_conflicts": ed_conflicts,
        "adjudication": report,
    }
    for l in out["laws"].values():
        l["items"].sort(key=lambda i: i["gold_id"])
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    items = [i for l in out["laws"].values() for i in l["items"]]
    live = [i for i in items if not i.get("excluded") and not i["disputed"]]
    print(f"gold: {len(out['laws'])} laws ({len(excluded_laws)} excluded of {len(audited)} audited), {len(items)} items: "
          f"real {sum(i['status']=='real' for i in live)}, not_real {sum(i['status']=='not_real' for i in live)}, "
          f"disputed {sum(i['disputed'] for i in items)}, excluded {sum(1 for i in items if i.get('excluded'))} -> {a.out}")
    return out


if __name__ == "__main__":
    main()
