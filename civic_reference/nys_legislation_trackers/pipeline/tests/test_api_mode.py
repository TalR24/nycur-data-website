"""Plain script: API-mode request builder, cost projection, resume state, compact index row. No network, no model call."""
import json, os, sys, tempfile
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed
import fetch_bills

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

def mk(n, title):
    return (fetch_bills.law_record({"session": 2023, "base_print_no": "S%d" % n, "chapter": {"number": n, "year": 2023, "signed_date": "2023-12-01"},
                                    "title": title, "act_clause": "AN ACT to amend the labor law", "law_section": "Labor Law",
                                    "sponsor": {"full_name": "A. Smith"}, "openleg_url": "u"}),
            "Section 1. The department shall publish a report {{annually}}.\n\n§ 2. This act shall take effect immediately. (law %d)" % n)
todo = [mk(1001, "First alpha title about reports"), mk(1002, "Second beta title about notices"), mk(1003, "Third")]
a, b = todo[0], todo[1]
ca, pa = ed.build_request(a[0], a[1], ttl="1h")
cb, pb = ed.build_request(b[0], b[1], ttl="1h")
blocks_a, blocks_b = pa["messages"][0]["content"], pb["messages"][0]["content"]
check("custom id is the law key", ca == a[0]["key"] and cb == b[0]["key"] and ca != cb)
check("fixed prompt identical across laws", blocks_a[0]["text"] == blocks_b[0]["text"] == ed.FIXED_PROMPT)
check("fixed block carries the cache breakpoint (1h in batches)", blocks_a[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"})
check("law text is last and uncached", blocks_a[-1]["text"].rstrip().endswith(a[1].rstrip()[-40:]) and "cache_control" not in blocks_a[-1])
check("variable block holds this law's metadata", a[0]["title"][:30] in blocks_a[-1]["text"] and b[0]["title"][:30] not in blocks_a[-1]["text"])
check("model, token cap and schema", pa["model"] == "claude-sonnet-5" and pa["max_tokens"] == 18000 and pa["output_config"]["format"]["schema"] is ed.SCHEMA)
check("schema has extends_existing", "extends_existing" in ed.SCHEMA["properties"]["obligations"]["items"]["properties"])
check("sync canary cache is 5 minutes", ed.build_request(a[0], a[1])[1]["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"})

# cost projection: 1,000 laws, 1,500 uncached in, 500 out, 3,400 cached prefix
sync = ed.project_cost(1000, 1500, 500, 3400, batch=False, cached=True)
expect = (1000 * (1500 * 2 + 3400 * 0.2 + 500 * 10) + 3400 * 2 * 1.25) / 1e6
check("sync projection", abs(sync - expect) < 1e-9)
check("batch is half", abs(ed.project_cost(1000, 1500, 500, 3400, batch=True) - expect / 2) < 1e-9)
check("no caching costs more", ed.project_cost(1000, 1500, 500, 3400, True, cached=False) > ed.project_cost(1000, 1500, 500, 3400, True, cached=True))

# resume state: answered laws are not re-sent; chunks respect the caps
tmp = Path(tempfile.mkdtemp())
ed.API_DIR = tmp
(tmp / "results").mkdir()
(tmp / "results" / (todo[0][0]["key"] + ".json")).write_text("{}")
left = ed.pending(todo)
check("answered law is not pending", todo[0][0]["key"] not in [l["key"] for l, _ in left] and len(left) == len(todo) - 1)
ed.write_manifest(todo[:3])
check("manifest lists the laws", set(json.loads((tmp / "manifest.json").read_text())) >= {l["key"] for l, _ in todo[:3]})
ed.BATCH_MAX_REQUESTS = 2
check("chunks respect the request cap", [len(c) for c in ed.chunks_of([("a", {}), ("b", {}), ("c", {}), ("d", {}), ("e", {})])] == [2, 2, 1])
ed.BATCH_MAX_REQUESTS, ed.BATCH_MAX_BYTES = 100, 30
check("chunks respect the byte cap", len(ed.chunks_of([("a", {"x": "y" * 20}), ("b", {"x": "y" * 20})])) == 2)

# compact index row
rec = {"session": 2023, "print_no": "S1234A", "base_print_no": "S1234", "chamber": "Senate", "is_resolution": False, "title": "T" * 400,
       "sponsor": {"member_id": 55, "short_name": "SMITH"}, "cosponsors": [{}, {}], "committee": "Rules",
       "status": {"type": "SIGNED_BY_GOV", "date": "2023-12-01"}, "signed": True, "chapter": {"number": 12, "year": 2023, "signed_date": "2023-12-01"},
       "vetoed": False, "same_as": [{"print_no": "A99", "session": 2023}], "law_section": "Labor Law", "published_at": "2023-01-05T10:00:00"}
row = fetch_bills.index_row(rec)
check("row matches the column list", len(row) == len(fetch_bills.COLS))
d = dict(zip(fetch_bills.COLS, row))
check("row values", d["print_no"] == "S1234A" and len(d["title"]) == 300 and d["cosponsors"] == 2 and d["chapter"] == 12 and d["same_as"] == "A99" and d["published"] == "2023-01-05" and d["sponsor_id"] == 55)
law = fetch_bills.law_record({**rec, "act_clause": "AN ACT", "sponsor": {"full_name": "A. Smith"}, "openleg_url": "u"})
check("law record", law["key"] == "2023-S1234" and law["chapter_number"] == 12 and law["law_number_display"] == "Chapter 12 of 2023")
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
