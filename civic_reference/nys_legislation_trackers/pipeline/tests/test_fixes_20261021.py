"""Plain script: Oct 21 2026 close-the-not-real-list fixes X1 (V1B stays off), X2 (approver 'consent of', duplicate prepare report). Prints 'N passed, M failed'."""
import os, sys, json, copy
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

def stored(oid):
    key = oid.rsplit("-", 1)[0]
    res = json.loads((ed.EXTRACTED / (key + ".json")).read_text())
    text = (ed.TEXT_MARKED / (key + ".txt")).read_text()
    o = copy.deepcopy([x for x in res["obligations"] if x["obligation_id"] == oid][0])
    if "{{" in (o.get("quote") or ""):
        o["quote"] = ed.eo.clean_stored_quote(o["quote"], text)[0]
    return o, text, res["obligations"]

# X1: V1B stays off; the item-modal guard keeps an item that states its own modal, drops a no-modal one
check("X1 V1B on (Oct 21 adjudication)", ed.APPLY_V1B is True)
ed.APPLY_V1B = True
def rule(oid):
    o, text, _ = stored(oid)
    g = ed.gate_record(o, text, "{{" in text)
    return g[0] if g else None
check("X1 no-modal criteria item is a sub-item", rule("2011-A5318-12") == "sub_item_of_parent")
o, text, _ = stored("2011-A5318-12")
o["quote"] = "The department shall approve the withdrawal if it is limited to reasonable quantities"
g = ed.gate_record(o, text, "{{" in text)
check("X1 item with its own modal stays a record", not g or g[0] != "sub_item_of_parent")
ed.APPLY_V1B = False

# X2a: 'consent of the mayor and the comptroller of such city' makes the comptroller an approver
o, _, _ = stored("2013-A7175-05")
check("X2a consent-of approver flagged", ed.approver_only_actor(o))
check("X2a actor that also acts is not flagged", not ed.approver_only_actor({"actor_raw": "the comptroller", "quote": "The comptroller shall audit the sale with the consent of the mayor"}))

# X2b: prepare record dropped when the dated submit record carries the same report
_, _, obs = stored("2011-A10205-03")
recs = [copy.deepcopy(x) for x in obs if x["obligation_id"] in ("2011-A10205-03", "2011-A10205-04")]
out = ed.drop_prepare_duplicates(recs)
check("X2b prepare dropped, submit kept", [x["obligation_id"] for x in out] == ["2011-A10205-04"])
check("X2b prepare with no dated sibling kept", len(ed.drop_prepare_duplicates(recs[:1])) == 1)
print("%d passed, %d failed" % (passed, failed))
