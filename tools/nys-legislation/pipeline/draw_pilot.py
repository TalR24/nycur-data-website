"""Stratified random pilot: per session 5 signed laws and 25 random bills of any status.
Usage: python3 draw_pilot.py --seed 20261007  (writes ../data/pilot.json)"""
import argparse, json, os, random, datetime
import openleg

SESSIONS = list(range(2009, 2026, 2))
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")


def one(path, params, offset):
    p = dict(params); p.update({"limit": 1, "offset": offset})
    d = openleg.get(path, p)
    items = d["result"]["items"]
    if not items:
        return None, d["total"]
    it = items[0]
    return (it.get("result") or it)["basePrintNo"], d["total"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261007)
    ap.add_argument("--signed", type=int, default=5)
    ap.add_argument("--random", type=int, default=25)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    out = {"method": {
        "seed": a.seed, "drawn_at": datetime.date.today().isoformat(),
        "signed_endpoint": "/api/3/bills/{y}/search?term=status.statusType:SIGNED_BY_GOV AND session:{y}&limit=1&offset=K (K uniform in 1..total, 1-based)",
        "random_endpoint": "/api/3/bills/{y}?limit=1&offset=K (K uniform in 1..total, 1-based, default sort)",
        "per_session": {"signed": a.signed, "random": a.random}, "sessions": SESSIONS}, "bills": []}
    seen = set()
    for y in SESSIONS:
        for kind, path, params, n in (
            ("signed", "/api/3/bills/%d/search" % y, {"term": "status.statusType:SIGNED_BY_GOV AND session:%d" % y}, a.signed),
            ("random", "/api/3/bills/%d" % y, {}, a.random)):
            _, total = one(path, params, 1)
            got, tries = 0, 0
            used = set()
            while got < n and tries < n * 10:
                tries += 1
                k = rng.randint(1, total)
                if k in used:
                    continue
                used.add(k)
                pn, _ = one(path, params, k)
                if not pn or (y, pn) in seen:
                    continue
                seen.add((y, pn))
                out["bills"].append({"session": y, "print_no": pn, "stratum": kind, "offset": k, "stratum_total": total})
                got += 1
        print(y, "done", flush=True)
    json.dump(out, open(os.path.join(DATA, "pilot.json"), "w"), indent=1)
    print("bills", len(out["bills"]), "requests", openleg.STATS)


if __name__ == "__main__":
    main()
