"""Plain script: prompt v2 pilot harness (version flag, schema, --emit-packets --laws, sandbox ingest). Temp dirs only; no model call."""
import hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
T = HERE.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed
import extract_obligations as eo

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else:
        failed += 1
        print("FAIL:", name)

# version 1: byte-identical to the production prompt (sha256 taken before the v2 change) and to the module constants
f1, v1 = ed.build_prompt(1)
check("v1 equals FIXED_PROMPT", f1 == ed.FIXED_PROMPT and v1 == ed.VARIABLE_TEMPLATE)
check("v1 sha256 unchanged", hashlib.sha256((f1 + "\x00" + v1).encode()).hexdigest() == "afd0d6089f8d1da87cefdf9220ad35713b54af2c080e9fe2285d4cd4937389e0")
check("v1 schema unchanged", hashlib.sha256(json.dumps(ed.SCHEMA, sort_keys=True).encode()).hexdigest() == "a6a05aac92be2dd9133cb1b17a8453bd6938d1393f8e56500cf3793438df53f3")
check("v1 has no excluded_sentences", "excluded_sentences" not in f1 and "excluded_sentences" not in ed.SCHEMA["properties"])

# version 2
rules = [l for l in (HERE / "prompt_v2_rules.txt").read_text().splitlines() if l.strip()]
f2, v2 = ed.build_prompt(2)
check("v2 has 9 bullets in the rules file", len(rules) == 9)
check("v2 contains the first bullet", rules[0] in f2 and "excluded_sentences" in f2)
check("v2 contains every bullet", all(r in f2 for r in rules))
check("v2 bullets sit before 'Do not invent obligations'", f2.index(rules[-1]) < f2.index("- Do not invent obligations") and f2.index(rules[0]) > f2.index("- Do not invent obligations") - len(f2))
check("v2 differs from v1 only by the inserted bullets", f2.replace("\n".join(rules) + "\n", "") == f1 and v2 == v1)
ex = {"effective_clause": {"kind": "immediate", "offset": None, "fixed_date": None, "text": "x"}, "obligations": [], "excluded_sentences": [{"start": "The board shall meet", "reason": "private"}]}
check("v2 schema accepts excluded_sentences", eo.validate_against_schema(ex, ed.SCHEMA_V2))
check("v2 schema accepts answers without it", eo.validate_against_schema({k: v for k, v in ex.items() if k != "excluded_sentences"}, ed.SCHEMA_V2))
check("v2 schema rejects a malformed entry", not eo.validate_against_schema(dict(ex, excluded_sentences=[{"start": "x"}]), ed.SCHEMA_V2))
check("excluded_sentences is not required", "excluded_sentences" not in ed.SCHEMA_V2["required"])

# --emit-packets --laws on 2 real laws of the pilot list, into a temp dir
tmp = Path(tempfile.mkdtemp())
keys = json.load(open(T / "quality" / "pilot_v2_laws.json"))["laws"][:2]
(tmp / "laws.json").write_text(json.dumps({"laws": keys}))
out = tmp / "pk"
r = subprocess.run([sys.executable, str(HERE / "extract_duties.py"), "--emit-packets", str(out), "--laws", str(tmp / "laws.json"), "--prompt-version", "2"], capture_output=True, text=True)
check("emit exit 0", r.returncode == 0)
pk = sorted(out.glob("*/*.txt"))
check("emit wrote 2 packets", [p.stem for p in pk] == sorted(keys))
for p in pk:
    y = p.stem.split("-")[0]
    txt = p.read_text()
    check("footer names absolute results path " + p.stem, "schema to %s:" % (out.resolve() / y / "results" / (p.stem + ".json")) in txt)
    check("packet is v2 " + p.stem, rules[0] in txt and '"excluded_sentences"' in txt)
chunks = sorted((out / "chunks").glob("*.lst"))
check("one chunk list", len(chunks) == 1 and len(chunks[0].read_text().split()) == 2)

# sandbox ingest of a synthetic 1-law result: nothing under T/data may change
def snap():
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() + str(p.stat().st_mtime_ns) for p in sorted((T / "data").rglob("*")) if p.is_file()}
key = keys[0]
y = key.split("-")[0]
res = {"effective_clause": {"kind": "immediate", "offset": None, "fixed_date": None, "text": "This act shall take effect immediately."}, "obligations": [], "excluded_sentences": [{"start": "The board shall meet", "reason": "private"}, {"start": "No person shall", "reason": "private"}]}
(out / y / "results" / (key + ".json")).write_text(json.dumps(res))
before = snap()
cache_before = {str(p): p.stat().st_mtime_ns for p in (HERE / "cache" / "extracted").glob("*.json")}
sb = tmp / "sandbox"
r = subprocess.run([sys.executable, str(HERE / "extract_duties.py"), "--ingest", str(out / y), "--session", y, "--per-session", "--prompt-version", "2", "--data-dir", str(sb)], capture_output=True, text=True)
check("ingest exit 0", r.returncode == 0)
if r.returncode != 0:
    print(r.stdout[-800:], r.stderr[-800:])
check("T/data untouched (hash and mtime)", snap() == before)
check("production extracted cache untouched", {str(p): p.stat().st_mtime_ns for p in (HERE / "cache" / "extracted").glob("*.json")} == cache_before)
for rel in ("duties/%s.json" % y, "powers/%s.json" % y, "dropped/%s.json" % y, "reask/%s.json" % y, "effective_dates/%s.json" % y, "deferred_long.json", "cache/extracted/%s.json" % key):
    check("sandbox has " + rel, (sb / rel).exists())
cf = sb / "cache" / "extracted" / (key + ".json")
check("cache stores excluded_sentences_count 2", cf.exists() and json.loads(cf.read_text()).get("excluded_sentences_count") == 2)

print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
