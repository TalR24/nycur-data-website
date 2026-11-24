"""Nov 24 2026 B110 (Tal's appointment ruling): the gates stop dropping an appointment clause whose appointing phrase is new matter. Synthetic quotes only; the flag is turned on for the checks and restored."""
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
def gate(quote, actor="the board", text=None):
    o = {"quote": quote, "quote_verified": True, "actor_raw": actor, "agency": "Unspecified", "kind_model": "duty"}
    t = text or quote
    return ed.gate_record(o, t, "{{" in t)
saved = ed.APPLY_B110
try:
    one = "The board shall consist of twelve members to be appointed by the governor."
    three = "The council shall consist of seven members, three appointed by the governor, two by the temporary president of the senate and two by the speaker of the assembly."
    ex = "The board shall consist of the commissioner of health, the attorney general and the director of the budget."
    elec = "The offices of trustee of the village shall be filled by election at the next general election."
    qual = "One member shall be a licensed engineer who shall be a resident of the state."
    qual_ap = "Each member shall be a resident of the county and shall be appointed by the county executive."
    ed.APPLY_B110 = False
    g = gate(one); check("flag off drops the composition sentence", bool(g) and g[0] == "designation_composition")
    g = gate(qual_ap); check("flag off drops the qualification sentence", bool(g) and g[0] == "qualification")
    ed.APPLY_B110 = True
    check("single appointer is kept", gate(one) is None)
    check("three appointers are found in order", ed.b110_appointers(three) == ["governor", "temporary president of the senate", "speaker of the assembly"])
    check("a three-appointer sentence is kept", gate(three) is None)
    check("recommendation clause names the recommender", ed.b110_appointers("One member upon the recommendation of the speaker of the assembly.") == ["speaker of the assembly"])
    g = gate(ex); check("ex officio membership stays dropped", bool(g) and g[0] == "designation_composition")
    g = gate(elec); check("election mechanics stay dropped", bool(g) and g[0] == "designation_composition")
    g = gate(qual); check("a bare qualification stays dropped", bool(g) and g[0] == "qualification")
    # 2: the qualification gate no longer drops an appointment clause in new matter
    check("qualification gate keeps an appointment clause in new matter", gate(qual_ap) is None)
    # 3: the appointing phrase must sit in {{ }} new matter when the text has markers
    new_t = "The board shall consist of nine members {{appointed by the governor}}."
    old_t = "The board shall consist of nine members appointed by the governor {{and confirmed}}."
    check("appointing phrase inside braces counts as new matter", ed.b110_new_matter("The board shall consist of nine members appointed by the governor.", new_t.replace("{{", "").replace("}}", "")) is True)
    ed.B110_CTX["text"] = new_t; check("braced appointer is new matter (marked text)", ed.b110_new_matter("The board shall consist of nine members appointed by the governor.", new_t) is True)
    check("reprinted appointer is not new matter", ed.b110_new_matter("The board shall consist of nine members appointed by the governor and confirmed.", old_t) is False)
    g = gate("The board shall consist of nine members appointed by the governor and confirmed.", text=old_t)
    check("a reprinted appointment sentence stays dropped", bool(g))
    # 4: term-length sentences are not restored
    term = "The members of the board shall be appointed by the governor for a term of four years."
    check("term-length sentence is not kept by B110", ed.b110_keep(term) is False)
    g = gate("The board shall consist of nine members appointed by the governor, each to serve for a term of office of three years."); check("term-of-office composition stays dropped", bool(g) and g[0] == "designation_composition")
    # 5: 'upon the recommendation of X' makes X the actor of a restored record
    rec_q = "The board shall consist of one member appointed upon the recommendation of the minority leader of the senate."
    o = {"quote": rec_q, "quote_verified": True, "actor_raw": "the governor", "agency": "Governor", "kind_model": "duty"}
    check("recommendation record: actor becomes the recommender", ed.b110_recommender_actor(o, rec_q) and o["actor_raw"] == "the minority leader of the senate")
    o2 = {"quote": one, "quote_verified": True, "actor_raw": "the board", "agency": "Unspecified", "kind_model": "duty"}
    check("a plain 'appointed by' record keeps the model's actor", not ed.b110_recommender_actor(o2, one) and o2["actor_raw"] == "the board")
    check("recommendation rewrite leaves the flag on", ed.APPLY_B110 is True)
    check("q1_item keeps an item naming its appointer", ed.q1_item("Two members appointed by the county executive.", "The board shall consist of:") is False)
    check("q1_item still drops a plain item", ed.q1_item("One member who is a resident of the hamlet.", "The board shall consist of:") is True)
    check("no stored-record rewrite or split exists", not hasattr(ed, "b110_split") and not hasattr(ed, "b110_fills_body"))
finally:
    ed.APPLY_B110 = saved
check("flag restored to its shipped value (ON since Nov 24 2026, judge 24/25)", ed.APPLY_B110 is saved and saved is True)
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
