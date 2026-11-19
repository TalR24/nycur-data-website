#!/usr/bin/env python3
"""Draw the nightly 20-law audit sample (11 per auditor, 2 shared) plus 2 gold calibration laws per auditor.
Usage: draw_sample.py --night YYYYMMDD [--source tonight|unaudited|gold] [--batch TAG] --out FILE [--packets DIR] [--data-dir DIR] [--nightly-dir DIR] [--gold PATH]
Seed = the night number (a trailing letter becomes a digit: 20261013b -> 202610132). Prints the JSON."""
import argparse
import glob
import json
import os
import random
import re

HERE = os.path.dirname(os.path.abspath(__file__))
T = os.path.dirname(HERE)


def load(p):
    with open(p) as f:
        return json.load(f)


def seed_of(night):
    m = re.fullmatch(r"(\d{8})([a-z]?)", night)
    if not m:
        raise SystemExit("night must look like 20261019 or 20261013b")
    return int(m.group(1) + (str(ord(m.group(2)) - 96 + 0) if m.group(2) else ""))


def latest_batch(packets):
    dirs = sorted(d for d in glob.glob(os.path.join(packets, "batches", "*")) if os.path.isdir(d))
    return dirs[-1] if dirs else None


def batch_laws(batch):
    laws = set()
    for f in glob.glob(os.path.join(batch, "*.lst")) + glob.glob(os.path.join(batch, "reask", "*.lst")):
        with open(f) as fh:
            laws |= {os.path.basename(l.strip())[:-4] for l in fh if l.strip().endswith(".txt")}
    return laws


def answered(packets, laws):
    return {l for l in laws if os.path.exists(os.path.join(packets, l[:4], "results", l + ".json"))
            or os.path.exists(os.path.join(packets, l[:4], "results_reask", l + ".json"))}


def deferred(data_dir):
    out = set()
    for n in ("deferred_long", "deferred_skipped"):
        p = os.path.join(data_dir, n + ".json")
        if os.path.exists(p):
            out |= {x["key"] if isinstance(x, dict) else x for x in load(p)["laws"]}
    return out


def audited_laws(nightly_dir):
    out = set()
    for f in glob.glob(os.path.join(nightly_dir, "*_[AB].json")):
        d = load(f)
        if "stored" in d and "auditor" in d:
            out |= {k[: k.rindex("-")] for k in d["stored"]}
            out |= {m["law"] for m in d.get("missed", []) if m.get("law")}
        else:
            out |= {k for k, v in d.items() if not k.startswith("_") and isinstance(v, dict)}
    return out


def reask_laws(packets, laws):
    return sorted(l for l in laws if os.path.exists(os.path.join(packets, l[:4], "results_reask", l + ".json")))


def calibration(gold, seed, exclude, per=2):
    """Gold laws with 1-12 live items, not in the sample; each carries its gold verdicts so the orchestrator can compare."""
    cands = []
    for law, g in sorted(gold["laws"].items()):
        live = [i for i in g["items"] if not i.get("excluded") and not i.get("disputed") and not str(i["gold_id"]).count(":")]
        if law not in exclude and 1 <= len(live) <= 12 and any(i["status"] == "real" for i in live):
            cands.append(law)
    picks = random.Random(seed + 1).sample(cands, 2 * per)
    out = {"A": picks[:per], "B": picks[per:], "gold_verdicts": {}}
    for law in picks:
        out["gold_verdicts"][law] = [
            {"gold_id": i["gold_id"], "status": i["status"], "expected_fields": i.get("expected_fields", {}), "quote": (i.get("quote") or "")[:200]}
            for i in gold["laws"][law]["items"] if not i.get("excluded") and not i.get("disputed")]
    return out


def draw(night, source, packets, data_dir, nightly_dir, gold_path, size=20, shared=2, batch_tag=None):
    seed = seed_of(night)
    gold = load(gold_path)
    if source == "gold":
        pool = sorted(gold["laws"])
    else:
        batch = os.path.join(packets, "batches", batch_tag) if batch_tag else latest_batch(packets)   # --batch: a re-ask-only batch may be the newest (Oct 30 2026)
        base = answered(packets, batch_laws(batch)) if batch else set()
        pool = base - deferred(data_dir)
        if source == "unaudited":
            pool -= audited_laws(nightly_dir)
        pool = sorted(pool)
    if len(pool) < size:
        raise SystemExit(f"pool has {len(pool)} laws, need {size}")
    d = random.Random(seed).sample(pool, size)
    per = (size + shared) // 2
    A, B = d[:per], d[:shared] + d[per:]
    cal = calibration(gold, seed, set(d))
    return {"seed": seed, "pool": len(pool), "source": source, "A": A, "B": B, "shared": d[:shared],
            "reask_laws_in_sample": [l for l in d if os.path.exists(os.path.join(packets, l[:4], "results_reask", l + ".json"))] if source != "gold" else [],
            "calibration": cal}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--night", required=True)
    ap.add_argument("--source", default="tonight", choices=["tonight", "unaudited", "gold"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--packets", default=os.path.join(T, "pipeline", "cache", "packets"))
    ap.add_argument("--data-dir", default=os.path.join(T, "data"))
    ap.add_argument("--nightly-dir", default=os.path.join(HERE, "nightly"))
    ap.add_argument("--gold", default=os.path.join(HERE, "gold.json"))
    ap.add_argument("--batch", default=None, help="batch tag to draw from instead of the newest batch folder")
    a = ap.parse_args(argv)
    res = draw(a.night, a.source, a.packets, a.data_dir, a.nightly_dir, a.gold, batch_tag=a.batch)
    # Blinding (Oct 20 2026): the auditors read a.out, so the gold verdicts of the calibration laws go to a sibling file
    # the orchestrator alone reads; the auditors' file names the calibration laws but never their verdicts.
    gv = (res.get("calibration") or {}).pop("gold_verdicts", None)
    if gv is not None:
        root, ext = os.path.splitext(a.out)
        with open(root + "_calibration_gold" + (ext or ".json"), "w") as f:
            json.dump({"gold_verdicts": gv}, f, indent=1)
    with open(a.out, "w") as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    main()
