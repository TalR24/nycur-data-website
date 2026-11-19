"""Poll the OpenLeg change feed for BILL updates (processed time) and keep a cursor.
Usage: python3 poll_updates.py --days 7      first run / backfill window
       python3 poll_updates.py               resume from data/updates_state.json
Writes data/updates_latest.json (per changed bill: change types) and data/updates_state.json (cursor).
Timestamps from the API are naive Eastern time; latency compares two values from the same clock."""
import argparse, json, os, statistics, datetime as dt
from collections import Counter, defaultdict
import openleg

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
STATE = os.path.join(DATA, "updates_state.json")
FMT = "%Y-%m-%dT%H:%M:%S"


def parse(s):
    main, _, frac = s.partition(".")
    return dt.datetime.strptime(main, FMT) + dt.timedelta(microseconds=int((frac + "000000")[:6]) if frac else 0)


def fetch_window(a, b):
    p = {"type": "processed", "content-type": "BILL", "detail": "true", "fields": "true", "order": "asc"}
    return list(openleg.paginate("/api/3/updates/%s/%s" % (a.strftime(FMT), b.strftime(FMT)), p, page=1000))


def summarize(items):
    bills = defaultdict(lambda: {"scopes": Counter(), "fields": set(), "last_processed": None})
    lat = []
    for it in items:
        k = "%s-%s" % (it["id"]["session"], it["id"]["basePrintNo"])
        b = bills[k]
        b["scopes"][it.get("scope")] += 1
        b["fields"].update((it.get("fields") or {}).keys())
        pt = it.get("processedDateTime")
        if pt and (b["last_processed"] is None or pt > b["last_processed"]):
            b["last_processed"] = pt
        if pt and it.get("sourceDateTime"):
            lat.append((parse(pt) - parse(it["sourceDateTime"])).total_seconds())
    out = [{"bill": k, "session": int(k.split("-")[0]), "base_print_no": k.split("-", 1)[1],
            "change_types": dict(v["scopes"]), "fields": sorted(v["fields"]), "last_processed": v["last_processed"]}
           for k, v in sorted(bills.items())]
    return out, lat


def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    a = ap.parse_args()
    now = dt.datetime.now().replace(microsecond=0)  # machine runs on Eastern time
    if a.days:
        start = now - dt.timedelta(days=a.days)
    elif os.path.exists(STATE):
        start = dt.datetime.strptime(json.load(open(STATE))["cursor"], FMT)
    else:
        start = now - dt.timedelta(days=1)
    items, per_day = [], Counter()
    t = start
    while t < now:
        e = min(t + dt.timedelta(days=1), now)
        got = fetch_window(t, e)
        per_day[t.strftime("%Y-%m-%d")] += len(got)
        items += got
        t = e
    bills, lat = summarize(items)
    json.dump({"from": start.strftime(FMT), "to": now.strftime(FMT), "bills": bills}, open(os.path.join(DATA, "updates_latest.json"), "w"), indent=1)
    json.dump({"cursor": now.strftime(FMT), "last_run_updates": len(items), "last_run_bills": len(bills)}, open(STATE, "w"), indent=1)
    sc = Counter(s for b in bills for s in b["change_types"])
    print("window", start, "->", now, "update tokens", len(items), "distinct bills", len(bills))
    print("tokens per day", dict(per_day))
    print("change types (bills touched)", dict(sc.most_common()))
    if lat:
        print("latency sec processed-source: median %.0f p90 %.0f p99 %.0f max %.0f min %.0f n=%d" % (
            statistics.median(lat), pct(lat, .9), pct(lat, .99), max(lat), min(lat), len(lat)))
        print("share under 10 min: %.3f, under 1 hour: %.3f" % (sum(x < 600 for x in lat) / len(lat), sum(x < 3600 for x in lat) / len(lat)))
    print(openleg.STATS)


if __name__ == "__main__":
    main()
