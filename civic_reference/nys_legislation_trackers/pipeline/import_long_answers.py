#!/usr/bin/env python3
"""Copy long-law window answers downloaded from the workflow artifact into cache/packets/{Y}/long/results/ (no overwriting).

  import_long_answers.py ARTIFACT_DIR [--packets-dir DIR] [--text-dir DIR]

ARTIFACT_DIR is searched for <key>__w<i>.json files. Each answer must fit SCHEMA_V2 and its window number must exist in the law's split.
The long/manifest.json entry {key: {"windows": n}} is created the way emit_long_packets writes it (merged with the existing entries), so
ingest_long finds the law. A manifest entry with a different window count is left alone and reported. The nightly ingest does the rest.
"""
import argparse, json, os, re, sys
from pathlib import Path

HERE = Path(os.path.abspath(__file__)).parent
sys.path.insert(0, str(HERE))
import extract_duties as ed   # noqa: E402
import extract_obligations as eo   # noqa: E402

NAME = re.compile(r"^(\d{4}-[A-Za-z]+\d+)__w(\d+)\.json$")


def import_answers(src, packets_dir=None, text_dir=None):
    """Returns {"copied": n, "existing": n, "invalid": n, "mismatch": [keys], "no_text": [keys]}."""
    packets_dir = Path(packets_dir or ed.PACKETS_ROOT)
    text_dir = Path(text_dir or ed.TEXT_MARKED)
    found = {}
    for f in sorted(Path(src).rglob("*.json")):
        m = NAME.match(f.name)
        if m:
            found.setdefault(m.group(1), {})[int(m.group(2))] = f
    res = {"copied": 0, "existing": 0, "invalid": 0, "mismatch": [], "no_text": []}
    for key, files in sorted(found.items()):
        tp = text_dir / (key + ".txt")
        if not tp.exists():
            res["no_text"].append(key)
            continue
        n = len(ed.split_long(tp.read_text()))
        d = ed.long_dir(key, packets_dir)
        mf = d / "manifest.json"
        manifest = json.loads(mf.read_text()) if mf.exists() else {}
        if key in manifest and manifest[key].get("windows") != n:
            res["mismatch"].append(key)
            continue
        wrote = False
        for i, f in sorted(files.items()):
            dest = d / "results" / ("%s__w%d.json" % (key, i))
            if dest.exists():
                res["existing"] += 1
                continue
            try:
                raw = json.loads(f.read_text())
            except json.JSONDecodeError:
                raw = None
            if raw is None or not 1 <= i <= n or not eo.validate_against_schema(raw, ed.SCHEMA_V2):
                res["invalid"] += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(raw))
            res["copied"] += 1
            wrote = True
        if wrote and key not in manifest:
            manifest[key] = {"windows": n}
            d.mkdir(parents=True, exist_ok=True)
            mf.write_text(json.dumps(manifest, indent=1))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("artifact_dir")
    ap.add_argument("--packets-dir")
    ap.add_argument("--text-dir")
    a = ap.parse_args()
    r = import_answers(a.artifact_dir, a.packets_dir, a.text_dir)
    print("copied %(copied)d, already present %(existing)d, invalid %(invalid)d; manifest window-count mismatch %(mismatch)s; no cached text %(no_text)s" % r)
