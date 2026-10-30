"""Plain script: Oct 30 2026 backlog B18 (relative-clause 'may' under a 'shall:' lead-in). Prints 'N passed, M failed'."""
import os, sys
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

# synthetic list: the item's only 'may' is inside a relative clause
lead = "The commissioner shall adopt rules that:"
item = "Establish the form of report which the commissioner may prescribe."
own = "Waive the fee, which the commissioner may prescribe, and the commissioner may extend the date."
check("B18 lead-in makes duty", ed.lead_in_makes_duty(lead))
check("B18 relative may stripped", not ed.GRANT_WORD.search(ed.strip_relative_may(item)))
check("B18 own may kept", bool(ed.GRANT_WORD.search(ed.strip_relative_may(own))))

# real law: stored as power, now a duty
def build(key):
    sess = int(key.split("-")[0])
    laws = [l for l in ed.signed_laws(sessions=[sess]) if l["key"] == key]
    ed.EFFECTIVE.update(ed.effective_table(laws))
    d, p, _ = ed.build_records(laws)
    return {o["obligation_id"]: o for o in d + p}
ed.STATS.clear() if hasattr(ed.STATS, "clear") else None
r = build("2009-A11353")
check("B18 2009-A11353-09 now duty", r.get("2009-A11353-09", {}).get("kind") == "duty")
check("B18 counter bumped", ed.STATS.get("b18_relative_may_list_item_duty", 0) >= 1)
# B30: content-list leads and a section sunset proviso
check("B30 agreement lead", bool(ed.CONTENT_LEAD_B30.search("The uniform agency project agreement shall, at a minimum:")))
check("B30 procedures lead", bool(ed.CONTENT_LEAD_B30.search("Such procedures shall include:")))
check("B30 plain lead not content", not ed.CONTENT_LEAD_B30.search("The contract shall be as follows:") and not ed.CONTENT_LEAD_B30.search("The commissioner shall, at a minimum:"))
check("B30 section sunset", bool(ed.SECTION_SUNSET.match("and provided further that section five of this act shall expire and be deemed repealed January 1, 2017.")))
check("B30 sunset not a duty", not ed.SECTION_SUNSET.match("provided further that the commissioner shall report by January 1, 2017."))
r = build("2015-S5867")
check("B30 S5867 imperative items dropped", not any(i in r for i in ("2015-S5867-10", "2015-S5867-12", "2015-S5867-13", "2015-S5867-14")))
r = build("2013-A8728")
check("B30 A8728-01 dropped", "2013-A8728-01" not in r)

# B16: one-time 'none' duties with no trigger get on_effective_date; transfers by operation of law are dropped
import tempfile
_cache = {}
def b16(oid):
    sess = int(oid.split("-")[0]); key = oid.rsplit("-", 1)[0]
    if key not in _cache:
        laws = [l for l in ed.signed_laws(sessions=[sess]) if l["key"] == key]
        ed.EFFECTIVE.update(ed.effective_table(laws))
        tmp = Path(tempfile.mkdtemp())          # only this law's stored file, so the build does not read the whole cache
        (tmp / (key + ".json")).symlink_to(ed.EXTRACTED / (key + ".json"))
        real = ed.EXTRACTED; ed.EXTRACTED = tmp
        try:
            d, p, _ = ed.build_records(laws)
        finally:
            ed.EXTRACTED = real
        _cache[key] = ({o["obligation_id"]: o for o in d + p}, {x["obligation_id"]: x for x in ed.DROPPED})
    return _cache[key]
r, dr = b16("2015-S5949-100")
check("B16 2015-S5949-100 on_effective_date", r.get("2015-S5949-100", {}).get("deadline_kind") == "on_effective_date")
r, dr = b16("2009-A9220-02")
check("B16 2009-A9220-02 on_effective_date", r.get("2009-A9220-02", {}).get("deadline_kind") == "on_effective_date")
check("B16 no trigger in sample quote", not ed.B16_EXTRA_TRIGGER.search("The department of state shall carefully consider potential mechanisms"))
check("B16 trigger regex keeps if", bool(ed.B16_EXTRA_TRIGGER.search("If accepted, the applications shall be reviewed")))
check("B16 trigger regex keeps unless", bool(ed.B16_EXTRA_TRIGGER.search("shall not grant the land unless application is made")))
for oid in ("2013-S5160-01", "2013-S5141-01"):
    r, dr = b16(oid)
    check("B16 %s dropped operation_of_law" % oid, oid not in r and dr.get(oid, {}).get("rule") == "operation_of_law")
check("B16 operation_of_law regex", bool(ed.OPERATION_OF_LAW.search("any existing rights shall vest in and be possessed by the city")) and bool(ed.OPERATION_OF_LAW.search("all funds shall be transferred to and vested in the authority")))

# B17: imperative / 'To <verb>' drops with a government agency and a subdivision citation are rescued
for oid, kd in (("2013-S2605-49", "duty"), ("2011-A6611-01", "power"), ("2011-A8932-01", "duty")):          # 'To ...' quotes
    r, dr = b16(oid)
    check("B17 %s rescued as %s" % (oid, kd), r.get(oid, {}).get("kind") == kd and oid not in dr)
for oid in ("2011-S6615-01", "2009-A9220-02", "2013-A9733-04"):          # capitalised imperatives
    r, dr = b16(oid)
    check("B17 %s rescued as duty" % oid, r.get(oid, {}).get("kind") == "duty" and oid not in dr)
for oid in ("2009-S4601-04", "2009-A9465-01", "2011-A6964-01"):          # Prescribing, DASNY 1676, species list
    r, dr = b16(oid)
    check("B17 %s still dropped" % oid, oid not in r and oid in dr)

# D1-D7 (builder D): each rule on its named quote; D1 and D3 ship off (over the 40 cap), so they are switched on here
_d_flags = (ed.APPLY_D1, ed.APPLY_D3); ed.APPLY_D1 = ed.APPLY_D3 = True
def dropped(oid, rule):
    r, dr = b16(oid)
    return oid not in r and dr.get(oid, {}).get("rule") == rule
for oid in ("2013-S6854-04", "2013-S6854-05", "2013-S6854-06", "2013-S6854-07", "2015-S7110-01"):
    check("D1 %s instrument_term" % oid, dropped(oid, "instrument_term"))
check("D1 body actor kept", not ed.instrument_actor({"actor_raw": "the department of health"}, "The department shall adopt rules."))
check("D2 limitation regex", bool(ed.TAX_LIMITATION.search("except in the case of a willfully false or fraudulent return with intent to evade the tax, no assessment of additional tax shall be made after the expiration of more than three years")))
check("D2 2009-A227-06 condition_of_tax_power", dropped("2009-A227-06", "condition_of_tax_power"))
check("D3/H2 2013-A7175-11 sentence holds the date, no longer dropped", not dropped("2013-A7175-11", "reprint_date_only"))
check("D3 date block", ed.date_only_block("fourteen", "two thousand [thirteen] ") and ed.date_only_block("2014") and not ed.date_only_block("fifteen") and not ed.date_only_block("fifteen", "a rate of [ten] ") and not ed.date_only_block("the commissioner shall report"))
r, dr = b16("2013-A7175-08")
check("D3 date-holding record kept", "2013-A7175-08" in r and "2013-A7175-02" in r)
for oid in ("2013-S7232-10", "2013-S7232-11", "2015-S5867-11"):
    check("D4 %s sub_item_of_parent" % oid, dropped(oid, "sub_item_of_parent"))
check("D4 nested leads", all(ed.CONTENT_LEAD_B30.search(x) for x in ("Such protocols and procedures shall include:", "Such procedures shall include:", "(B) Such procedures shall include:", "The uniform agency project agreement shall, at a minimum:")))
check("D4 own modal item kept", not ed.d4_item("The commissioner shall file a report.", "Such procedures shall include:"))
check("D5 2015-A5652-04 reprinted_name_swap", dropped("2015-A5652-04", "reprinted_name_swap"))
r, dr = b16("2015-A5652-05")
check("D5 2015-A5652-05 district attorney kept", "2015-A5652-05" in r)
check("D6 2015-S7110-02 private_actor", dropped("2015-S7110-02", "private_actor"))
check("D6 2015-S4920-01 private_actor", dropped("2015-S4920-01", "private_actor"))
check("D6 consent phrase", ed.d6_private({"actor_raw": "the commissioner"}, "A cemetery corporation may, with the consent of the commissioner, sell a plot."))
check("D6 government subject kept", not ed.d6_private({"actor_raw": "the commissioner"}, "The commissioner may, with the consent of the governor, sell a plot."))
check("D7 2015-S7258-02 qualification", dropped("2015-S7258-02", "qualification"))
check("D7 regex", all(ed.QUALIFICATION.search(x) for x in ("shall be a citizen of the United States", "shall be at least twenty-one years of age", "shall possess the following qualifications:")) and not ed.QUALIFICATION.search("shall report to the governor"))
ed.APPLY_D1, ed.APPLY_D3 = _d_flags

# G1: a lead-in search stops at the act-section marker and the amend instruction above the item
def _span(t, needle):
    a = t.index(needle); return (a, a + len(needle))
prev = "Section 1. The agency shall do the following:\n(a) First thing.\nSection 2. Definitions.\n(b) Establish the board."
check("G1 prev-section lead not taken (scan_back)", ed.scan_back_lead_in(_span(prev, "Establish"), prev) is None)
check("G1 prev-section lead not taken (full)", ed.item_lead_full(_span(prev, "Establish"), prev) is None)
amd = "Section 1. The agency shall do the following:\nSection 2. Section 5 of the law is amended to read as follows:\n(b) Establish the board."
check("G1 amend line closes the window", ed.item_lead_full(_span(amd, "Establish"), amd) is None and ed.list_lead_in(_span(amd, "Establish"), amd) is None)
own = "Section 2. Powers. The board shall have the following powers:\n(a) Hire staff.\n(b) Establish the board."
check("G1 own-section lead kept", (ed.scan_back_lead_in(_span(own, "Establish"), own) or "").endswith("powers:") and (ed.list_lead_in(_span(own, "Establish"), own) or "").endswith("powers:"))
check("G1 own-section lead kept (imperative, numbered)", bool(ed.imperative_lead_in(_span(own.replace("(a)", "1.").replace("(b)", "2."), "Establish"), own.replace("(a)", "1.").replace("(b)", "2."))))
r, dr = b16("2019-S1192-04")
check("G1 2019-S1192-04 stays a duty", r.get("2019-S1192-04", {}).get("kind") == "duty")
# H1 / H2 (Oct 30 2026 night): D1 narrowed, D3 tests the whole sentence
_h_flags = (ed.APPLY_D1, ed.APPLY_D3); ed.APPLY_D1 = ed.APPLY_D3 = True
r, dr = b16("2013-A10108-07")
check("H1 2013-A10108-07 plan quote kept", "2013-A10108-07" in r)
r, dr = b16("2011-S50002-69")
check("H1 2011-S50002-69 award rule kept", "2011-S50002-69" in r)
check("H1 award/let/make rules not instrument terms", not any(ed.INSTRUMENT_SUBJECT.search(x) for x in ("Any contract for the work shall be awarded to the lowest bidder.", "Any lease shall be let by public auction.", "Any contract or agreement shall be made in writing by the commissioner.")) and bool(ed.INSTRUMENT_SUBJECT.search("Any lease entered into shall contain an indemnity clause.")))
r, dr = b16("2013-S6854-07")
check("H1 S6854-07 lease indemnity still dropped", "2013-S6854-07" not in r and dr.get("2013-S6854-07", {}).get("rule") == "instrument_term")
def _h3(t, needle):
    a = t.index(needle); return ed.reprint_date_only((a, a + len(needle)), t, t)
_dt = "Section 1. The county of Erie may continue the tax imposed by section one, which shall expire on December 1, [2013] {{2014}}; and the county may collect arrears.\n\nThe comptroller shall audit the fund. The board shall meet monthly."
check("H2 clause of the date sentence kept", not _h3(_dt, "the county may collect arrears"))
check("H2 braceless sentence away from the date sentence dropped", _h3(_dt, "The board shall meet monthly."))
_rt = "Section 1. The tax rate is [ten] {{fifteen}} percent.\n\nThe board shall meet monthly."
check("H2 rate change section untouched", not _h3(_rt, "The board shall meet monthly."))
ed.APPLY_D1, ed.APPLY_D3 = _h_flags
print(f"{passed} passed, {failed} failed")
