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
check("v2 has 10 bullets in the rules file", len(rules) == 10)
check("last bullet is the act-clause boilerplate rule", "act clause" in rules[-1] and "boilerplate" in rules[-1])
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

# Oct 15 2026 go-live: L2 act clause drop, L3 cost duty, L4 defaults, re-ask head
q = "This act shall take effect on the ninetieth day after it shall have become a law and shall expire 10 years after such effective date"
check("L2 pilot quote is an act clause", ed.is_act_clause_quote(q))
check("L2 contained in the law's act_clause", ed.is_act_clause_quote("shall expire 10 years after such effective date", "This act shall take effect on the ninetieth day and shall expire 10 years after such effective date."))
check("L2 'provided, however' amendments clause", ed.is_act_clause_quote("Provided, however, that the amendments made by section three of this act shall not affect the expiration"))
check("L2 ordinary duty is kept", not ed.is_act_clause_quote("The commissioner shall report to the legislature annually", "This act shall take effect immediately."))
rc = "The village of Rockville Centre shall pay all past service costs"
check("L3 Rockville Centre is a cost duty", bool(ed.COST_DUTY.search(rc)))
check("L3 shall bear / reimburse", bool(ed.COST_DUTY.search("the county shall reimburse the town for such costs")) and bool(ed.COST_DUTY.search("the department shall bear the cost")))
check("L3 beneficiary is not a government subject", not ed.COST_DUTY.search("eligible units shall pay nothing"))
check("L3 shall pay needs a government noun first", not ed.COST_DUTY.search("a person shall pay the fee; the village may waive it"))
r = subprocess.run([sys.executable, str(HERE / "extract_duties.py"), "--emit-packets", str(tmp / "pk_default"), "--laws", str(tmp / "laws.json")], capture_output=True, text=True)
check("default emit is version 2", r.returncode == 0 and "prompt version 2" in r.stdout and all("COVERAGE STEP" in p.read_text() for p in (tmp / "pk_default").glob("*/*.txt")))
src = (HERE / "extract_duties.py").read_text()
check("--prompt-version default is 2", 'choices=(1, 2), default=2' in src)
v1pk = ed.FIXED_PROMPT + ed.build_prompt(1)[1].replace("{", "{") + "\n\nLAW TEXT:\nbody\n\nANSWER FORMAT: write ONLY a JSON object matching this schema to results/2009-A1.json:\n" + json.dumps(ed.SCHEMA)
up = ed.upgrade_packet_v2(v1pk)
check("upgrade swaps the head to v2 and keeps the rest", up.startswith(ed.build_prompt(2)[0]) and "COVERAGE STEP" in up and "LAW TEXT:\nbody" in up and up.endswith(json.dumps(ed.SCHEMA_V2)))
check("upgrade is idempotent", ed.upgrade_packet_v2(up) == up)
rq = ed.reask_packet_text(v1pk, "2009-A1", {"reasons": [{"check": "x", "detail": "y", "sentences": []}]}, [], Path("/tmp/x/results_reask/2009-A1.json"))
check("re-ask packet head is version 2", "COVERAGE STEP" in rq and ed.REASK_MARK in rq and rq.rstrip().endswith(json.dumps(ed.SCHEMA_V2)) and "results_reask/2009-A1.json" in rq)
check("v1 answer validates under SCHEMA_V2 (default ingest schema)", eo.validate_against_schema({k: v for k, v in ex.items() if k != "excluded_sentences"}, ed.SCHEMA_V2))

print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
