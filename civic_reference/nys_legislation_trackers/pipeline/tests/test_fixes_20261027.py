"""Plain script: Oct 27 2026 close-the-not-real-list fixes Y1 (clause inside a definition paragraph is not a record). Prints 'N passed, M failed'."""
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
    return o, text

def rule(oid):
    o, text = stored(oid)
    g = ed.gate_record(o, text, "{{" in text)
    return g[0] if g else None

# Y1: B10, 2015-A7996-05 is a clause of the 'bus rapid transit program' definition
check("Y1 A7996-05 dropped as definition", rule("2015-A7996-05") == "definition")
# the delegated-to-rules definition stays a record, and a quote with its own modal stays
check("Y1 A6772-01 (defined by rules) not dropped by Y1", rule("2009-A6772-01") != "definition")
text = '1. "Widget" shall mean a thing designated by the department in consultation with the board, and the department shall report yearly.\n'
q = "designated by the department in consultation with the board"
check("Y1 synthetic definition clause", ed.inside_definition(q, (text.index(q), text.index(q) + len(q)), text))
q2 = "the department shall report yearly"
check("Y1 own modal stays", not ed.inside_definition(q2, (text.index(q2), text.index(q2) + len(q2)), text))
text2 = '1. "Widget" shall mean a thing. The department designated by the board prepares plans.\n'
q3 = "designated by the board prepares plans"
check("Y1 later sentence stays", not ed.inside_definition(q3, (text2.index(q3), text2.index(q3) + len(q3)), text2))
# S5949-96 is a real thin duty, kept (no gate fires)
check("S5949-96 not dropped", rule("2015-S5949-96") is None)

# Y2 (Oct 27): 'the justice center' is the Justice Center for the Protection of People with Special Needs, never a court
import re as _re
import agency_resolve_nys as _ar
_court_pat = next(p for p, name, *_ in _ar.GROUPS if name == "Unified Court System") if hasattr(_ar, "GROUPS") else None
if _court_pat is not None:
    check("Y2 court group does not match 'the justice center'", not _re.search(_court_pat, "the justice center", _re.I))
    check("Y2 court group still matches 'the court'", bool(_re.search(_court_pat, "the court", _re.I)))
import json as _json, os as _os
_cw = _json.load(open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "data", "agency_crosswalk_nys.json")))
check("Y2 crosswalk alias 'the justice center'", _cw["lookup"].get("the justice center") == _cw["lookup"]["justice center for the protection of people with special needs"])

# G1 (Oct 27): provisos of a tax-power section are conditions of the power
check("G1 A209-04 joined as a party", rule("2015-A209-04") == "condition_of_tax_power")
check("G1 A209-09 three years", rule("2015-A209-09") == "condition_of_tax_power")
check("G1 A209-03 the grant's own paying clause stays", rule("2015-A209-03") != "condition_of_tax_power")
_t = "§ 1. The town of X is hereby authorized and empowered to adopt and amend local laws imposing a tax on rooms. The treasurer shall be joined as a party in any action or proceeding brought to collect the tax by the owner.\n"
_q = "The treasurer shall be joined as a party in any action or proceeding brought to collect the tax by the owner."
check("G1 synthetic proviso", (ed.gate_record({"quote": _q, "quote_verified": True}, _t, False) or [None])[0] == "condition_of_tax_power")
_t2 = _t.replace("is hereby authorized and empowered to adopt and amend local laws imposing a tax on rooms", "shall keep the books")
check("G1 no tax grant in the section stays", (ed.gate_record({"quote": _q, "quote_verified": True}, _t2, False) or [None])[0] != "condition_of_tax_power")

# G2: office-name and pronoun swaps are reprinted text
check("G2 S6390-01 verb swap stays a record", rule("2015-S6390-01") != "reprinted_name_swap")
check("G2 A11515-10 tax commission to commissioner", rule("2009-A11515-10") == "reprinted_name_swap")
_tdb = json.load(open(HERE.parent / "data" / "powers" / "2015.json"))["powers"]
_q7 = [r["quote"] for r in _tdb if r["obligation_id"] == "2015-S7160-01" and r["quote"].startswith("Anything")][0]
_t7 = (ed.TEXT_MARKED / "2015-S7160.txt").read_text()
check("G2 S7160-01 cross-reference renumbering stays a record", (ed.gate_record({"quote": _q7, "quote_verified": True}, _t7, True) or [None])[0] != "reprinted_name_swap")
check("G2 office and pronoun swap", ed.reprinted_name_swap("The [tax commission] {{commissioner}} shall act when [it] {{he or she}} finds cause."))
check("G2 new number is not a swap", not ed.reprinted_name_swap("The board shall act within [ten] {{twenty}} days."))
check("G2 new modal is not a swap", not ed.reprinted_name_swap("The board [may] {{shall}} report."))
check("G2 added clause is not a swap", not ed.reprinted_name_swap("The [department] {{office}} shall report {{to the governor}}."))

# G3: Part-aware holder and a 60-word window for sunset extensions
_T3 = ("Section 1. Section 3 of chapter 5 of the laws of 2010, relating to racing and wagering, is amended to read as follows:\n\n"
       "§ 3. This act shall expire and be deemed repealed July 1, [2011] {{2012}}.\n\n"
       "§ 2. This act shall take effect immediately. {{Part}} D\n\n"
       "Section 1. Section 4 of chapter 6 of the laws of 2010, relating to the city of New York, is amended to read as follows:\n\n"
       "§ 4. This act shall expire and be deemed repealed July 1, [2011] {{2013}}.\n\n"
       "§ 2. This act shall take effect immediately.")
_L3 = {"key": "2011-A3", "title": "AN ACT relating to the city of New York, in relation to extending sunsets", "act_clause": "", "chapter_number": "9", "chapter_year": "2011",
       "session": "2011", "print_no": "A3", "law_number_display": "Chapter 9 of 2011", "sponsor": "X", "enactment_date": "2011-06-01", "openleg_url": "u"}
_E3 = {"effective_date": "2011-06-01", "rule": "immediately", "expires_date": None, "section_dates": []}
check("G3 two Parts found", len(ed.part_starts(_T3)) == 2)
_r3, _u3 = ed.sunset_extension_records(_L3, _T3, _E3, [], {"obligations": [], "model": "m"})
check("G3 Part C racing sunset does not take the title's city", not any("2012" in r["quote"] for r in _r3) and _u3 is not None)
check("G3 Part D keeps the city", [r["actor_raw"] for r in _r3] == ["the city of New York"] and "2013" in _r3[0]["quote"])
_long = "This act shall take effect immediately, " + " ".join("word%d" % i for i in range(120)) + ", and shall expire and be deemed repealed July 1, [2011] {{2012}}; " + " ".join("tail%d" % i for i in range(120)) + "."
_T4 = "Section 1. Section 3 of chapter 5 of the laws of 2010, relating to the town of Islip, is amended to read as follows:\n\n§ 3. " + _long + "\n\n§ 2. This act shall take effect immediately."
_s4 = ed.sunset_extension_sentences(_T4)
check("G3 window at most 60 words and holds the date", len(_s4) == 1 and len(_s4[0][0].split()) <= 60 and "2012" in _s4[0][0] and _s4[0][0] in " ".join(_long.replace("[2011] {{2012}}", "2012").split()))
_ap = {r["obligation_id"]: r for r in _tdb}

print("%d passed, %d failed" % (passed, failed))
