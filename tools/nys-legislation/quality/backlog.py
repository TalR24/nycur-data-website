#!/usr/bin/env python3
"""Queue of fix items (quality/backlog.json). A night's builder gets at most 5 open items (`list --next`); the rest wait.
Usage: backlog.py add --night N --class TEXT [--instances ID,ID] [--count N] [--rule TEXT] [--id ID]
       backlog.py list [--all | --next]      backlog.py done ID [--night N] [--note TEXT]   [--file PATH]"""
import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
NEXT_LIMIT = 5


def load(path):
    if not os.path.exists(path):
        return {"items": []}
    with open(path) as f:
        return json.load(f)


def save(path, d):
    with open(path, "w") as f:
        json.dump(d, f, indent=1)
        f.write("\n")


def add(path, night, cls, instances=(), count=None, rule="", oid=None):
    d = load(path)
    ids = {i["id"] for i in d["items"]}
    oid = oid or "B%d" % (1 + max([int(i[1:]) for i in ids if i[1:].isdigit()] or [0]))
    if oid in ids:
        raise SystemExit(f"{oid} exists")
    item = {"id": oid, "added": night, "class": cls, "instances": list(instances),
            "count": count if count is not None else len(instances), "rule": rule, "status": "open"}
    d["items"].append(item)
    save(path, d)
    return item


def done(path, oid, night=None, note=None):
    d = load(path)
    for i in d["items"]:
        if i["id"] == oid:
            i["status"] = "done"
            if night:
                i["done"] = night
            if note:
                i["note"] = note
            save(path, d)
            return i
    raise SystemExit(f"{oid} not found")


def open_items(path):
    return sorted((i for i in load(path)["items"] if i["status"] == "open"), key=lambda i: (-(i.get("count") or 0), i["id"]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["add", "list", "done"])
    ap.add_argument("id", nargs="?")
    ap.add_argument("--file", default=os.path.join(HERE, "backlog.json"))
    ap.add_argument("--id", dest="newid")
    ap.add_argument("--night")
    ap.add_argument("--class", dest="cls")
    ap.add_argument("--instances", default="")
    ap.add_argument("--count", type=int)
    ap.add_argument("--rule", default="")
    ap.add_argument("--note")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--next", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "add":
        if not (a.night and a.cls):
            ap.error("add needs --night and --class")
        r = add(a.file, a.night, a.cls, [x for x in a.instances.split(",") if x], a.count, a.rule, a.newid)
        print(json.dumps(r))
    elif a.cmd == "done":
        if not a.id:
            ap.error("done needs an id")
        print(json.dumps(done(a.file, a.id, a.night, a.note)))
    else:
        items = load(a.file)["items"] if a.all else open_items(a.file)
        if a.next:
            items = items[:NEXT_LIMIT]
        for i in items:
            print(f"{i['id']:5} [{i['status']}] added {i['added']} count {i['count']}: {i['class']}\n      rule: {i['rule']}")
        print(f"{len(items)} shown, {len(open_items(a.file))} open")
    return 0


if __name__ == "__main__":
    main()
