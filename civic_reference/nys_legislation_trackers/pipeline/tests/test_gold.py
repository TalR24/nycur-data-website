"""Plain script: gold regression set builder and scorer. Prints 'N passed, M failed'."""
import glob
import json
import os
import sys
import tempfile
from pathlib import Path

T = Path(os.path.abspath(__file__)).parent.parent.parent
Q = T / "quality"
sys.path.insert(0, str(Q))
import build_gold
import score_gold
from gold_lib import quotes_match, wilson

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

tmp = tempfile.mkdtemp()
out = os.path.join(tmp, "gold.json")
g = build_gold.main(["--out", out])
check("gold file written", os.path.exists(out))

audited = set()
for f in glob.glob(str(Q / "nightly" / "*_[AB].json")):
    d = json.load(open(f))
    if "stored" in d and "auditor" in d:
        audited |= {k[:k.rindex("-")] for k in d["stored"]}
        audited |= {m["law"] for m in d["missed"] if m.get("law")}
    else:
        audited |= {k for k, v in d.items() if not k.startswith("_") and isinstance(v, dict)}
check("law count = audited minus exclusions", len(g["laws"]) == len(audited) - len(g["excluded_laws"]) and len(g["laws"]) > 100)

item = next((i for l in g["laws"].values() for i in l["items"] if i["gold_id"] == "2011-A7511-01"), None)
check("2011-A7511-01 present", item is not None)
check("2011-A7511-01 real", item and item["status"] == "real" and not item["disputed"] and not item.get("excluded"))
check("2011-A7511-01 no corrections", item and "other_fields" not in item and "verdicts_seen" not in item)
check("reviewed_as_if override excluded", any(i["gold_id"] == "2015-A5521-02" and i.get("excluded") for l in g["laws"].values() for i in l["items"]))
check("commission items excluded", all(i.get("excluded") for l in g["laws"].values() for i in l["items"] if "legislative bill drafting commission" in (i["quote"] or "").lower()))

check("matcher: containment", quotes_match("The commissioner shall adopt rules", "the commissioner shall adopt rules by January 1, 2015"))
check("matcher: jaccard", quotes_match("a b c d e f", "a b c d e g h"))
check("matcher: unrelated", not quotes_match("the board shall report annually", "licensee may sell stock"))
check("wilson bounds", wilson(5, 10)[0] < 0.5 < wilson(5, 10)[1])

res = score_gold.main(["--gold", out, "--json", os.path.join(tmp, "score.json")])
check("scorer ran", res["gold_laws"] == len(g["laws"]) and res["stored_records_in_gold_laws"] > 0)
check("rates sane", 0 <= res["precision_strict"]["rate"] <= res["precision_real"]["rate"] <= 1)

print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
