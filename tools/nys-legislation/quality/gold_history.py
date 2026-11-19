#!/usr/bin/env python3
"""Gold score history. `append --night TAG` adds one line to gold_history.jsonl from gold_score.json (run score_gold.py first);
`check` prints PAUSE plus the reason when precision_strict fell by more than 1.0 point against the latest earlier entry with the same
gold law count (same gold build), else OK. Usage: gold_history.py append --night TAG | check [--history PATH] [--score PATH]"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DROP = 1.0


def load(p):
    with open(p) as f:
        return json.load(f)


def read_history(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def pct(r):
    return round(r["rate"] * 100, 1) if r and r.get("rate") is not None else None


def entry_from_score(score, night, prev):
    return {
        "night": night,
        "recorded_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "gold_built_at": score.get("gold_built_at"),
        "gold_laws": score["gold_laws"],
        "stored": score["stored_records_in_gold_laws"],
        "precision_strict": pct(score["precision_strict"]),
        "precision_real": pct(score["precision_real"]),
        "recall": pct(score["recall"]),
        "not_real_still_stored": score["not_real_still_stored"],
        "effective_date_accuracy": pct(score["effective_date_accuracy"]),
        "prev_strict": prev["precision_strict"] if prev else None,
    }


def append(night, history, score_path):
    rows = read_history(history)
    e = entry_from_score(load(score_path), night, rows[-1] if rows else None)
    with open(history, "a") as f:
        f.write(json.dumps(e) + "\n")
    return e


def check(history):
    rows = read_history(history)
    if len(rows) < 2:
        return "OK", "fewer than two entries"
    cur = rows[-1]
    prev = next((r for r in reversed(rows[:-1]) if r["gold_laws"] == cur["gold_laws"]), None)
    if prev is None:
        return "OK", f"no earlier entry on the same gold build ({cur['gold_laws']} laws)"
    drop = round(prev["precision_strict"] - cur["precision_strict"], 1)
    if drop > DROP:
        return "PAUSE", (f"precision_strict fell {drop} points on the same gold build ({cur['gold_laws']} laws): "
                         f"{prev['precision_strict']}% on {prev['night']} -> {cur['precision_strict']}% on {cur['night']}")
    return "OK", f"precision_strict {cur['precision_strict']}% vs {prev['precision_strict']}% on {prev['night']} (change {-drop:+.1f})"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["append", "check"])
    ap.add_argument("--night")
    ap.add_argument("--history", default=os.path.join(HERE, "gold_history.jsonl"))
    ap.add_argument("--score", default=os.path.join(HERE, "gold_score.json"))
    a = ap.parse_args(argv)
    if a.cmd == "append":
        if not a.night:
            ap.error("--night required")
        e = append(a.night, a.history, a.score)
        print(json.dumps(e))
        return e
    status, why = check(a.history)
    print(f"PAUSE: {why}" if status == "PAUSE" else f"OK ({why})")
    return status


if __name__ == "__main__":
    r = main()
    sys.exit(0)
