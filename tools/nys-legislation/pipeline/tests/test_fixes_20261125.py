"""Nov 24 2026 B110 (Tal's appointment ruling): an appointment clause is a duty of each appointing actor. Synthetic quotes only; the flag is turned on for the checks and restored."""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
if not (HERE / "cache" / "packets").is_dir():
    print("0 passed, 0 failed (skipped: cache/packets is not present here)"); sys.exit(0)
import extract_duties as ed
passed = failed = 0
def check(name, ok):
    global passed, failed
    if ok: passed += 1
    else: failed += 1; print("FAIL", name)
def gate(quote, actor="the board"):
    o = {"quote": quote, "quote_verified": True, "actor_raw": actor, "agency": "Unspecified", "kind_model": "duty"}
    return ed.gate_record(o, quote, False)
def split(quote, actor="the board"):
    res = {"obligations": [{"obligation_id": "2026-S1-01", "quote": quote, "actor_raw": actor, "agency": "Unspecified", "deadline_kind": "none"}]}
    ed.b110_split(res, "2026-S1"); return res["obligations"]
saved = ed.APPLY_B110
try:
    one = "The board shall consist of twelve members to be appointed by the governor."
    three = "The council shall consist of seven members, three appointed by the governor, two by the temporary president of the senate and two by the speaker of the assembly."
    ex = "The board shall consist of the commissioner of health, the attorney general and the director of the budget."
    elec = "The offices of trustee of the village shall be filled by election at the next general election."
    qual = "One member shall be a licensed engineer who shall be a resident of the state."
    ed.APPLY_B110 = False
    g = gate(one); check("flag off drops the composition sentence", bool(g) and g[0] == "designation_composition")
    check("flag off splits nothing", len(split(three)) == 1)
    ed.APPLY_B110 = True
    check("single appointer is kept", gate(one) is None)
    r = split(one); check("single appointer: one record, actor the governor", len(r) == 1 and r[0]["actor_raw"] == "the governor")
    check("three appointers are found in order", ed.b110_appointers(three) == ["governor", "temporary president of the senate", "speaker of the assembly"])
    r = split(three)
    check("three-appointer split makes three records", len(r) == 3)
    check("split actors", [x["actor_raw"] for x in r] == ["the governor", "the temporary president of the senate", "the speaker of the assembly"])
    check("split ids continue after the last and point at the origin", [x["obligation_id"] for x in r] == ["2026-S1-01", "2026-S1-02", "2026-S1-03"] and r[1]["joint_actor_split_from"] == "2026-S1-01")
    check("a three-appointer sentence is kept", gate(three) is None)
    check("recommendation clause names the recommender", ed.b110_appointers("One member upon the recommendation of the speaker of the assembly.") == ["speaker of the assembly"])
    g = gate(ex); check("ex officio membership stays dropped", bool(g) and g[0] == "designation_composition")
    check("ex officio has no appointer", ed.b110_appointers(ex) == [])
    g = gate(elec); check("election mechanics stay dropped", bool(g) and g[0] == "designation_composition")
    check("qualification names no appointer", ed.b110_appointers(qual) == [])
    g = gate(qual); check("qualification stays dropped", bool(g) and g[0] == "qualification")
    g = gate("Each member shall be a resident of the county and shall be appointed by the county executive."); check("a qualification clause stays dropped", bool(g) and g[0] == "qualification")
    check("an actor that already appoints is untouched", len(split(three, actor="the governor")) == 1 and split(three, actor="the governor")[0]["actor_raw"] == "the governor")
    check("q1_item keeps an item naming its appointer", ed.q1_item("Two members appointed by the county executive.", "The board shall consist of:") is False)
    check("q1_item still drops a plain item", ed.q1_item("One member who is a resident of the hamlet.", "The board shall consist of:") is True)
finally:
    ed.APPLY_B110 = saved
check("flag restored to its shipped value", ed.APPLY_B110 is saved and saved is False)
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
