"""Nov 14 2026 night: reworks of AJ1 (B65), AJ2 (B66), AJ3 (B67) and B58 after the blind judge's findings. Each flag is switched on only for the check and restored.
Plain script; prints 'N passed, M failed'. Skips when the law caches are absent (CI)."""
import logging, sys, tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
if not (HERE / "cache" / "text_marked").is_dir() or not (HERE / "cache" / "extracted").is_dir():
    print("0 passed, 0 failed (skipped: cache/text_marked or cache/extracted is not present here)"); sys.exit(0)
logging.disable(logging.CRITICAL)
import extract_duties as ed
passed = failed = 0
def check(name, ok):
    global passed, failed
    if ok: passed += 1
    else: failed += 1; print("FAIL", name)

# unit checks (flags on only inside)
FL = ("APPLY_AJ1", "APPLY_AJ2", "APPLY_AJ3", "APPLY_B58")
saved = {f: getattr(ed, f) for f in FL}
try:
    ed.APPLY_AJ1 = True
    check("AJ1 keeps a county may-power", bool(ed.AJ1_BODY_MAY.search("The county, cities, towns and villages may expend capital funds to conduct evaluations")))
    check("AJ1 keeps 'the department may enter into an agreement'", bool(ed.AJ1_BODY_MAY.search("The department may enter into an agreement to provide data")))
    check("AJ1 keeps 'is authorized' of the superintendent", bool(ed.AJ1_BODY_MAY.search("The superintendent is authorized to promulgate rules and regulations")))
    check("AJ1 keeps a bureau's extra penalty", bool(ed.AJ1_BODY_MAY.search("such parking violations bureau may provide for an additional penalty")))
    check("AJ1 keeps the Banking board's disclosures", bool(ed.AJ1_BODY_MAY.search("(4) such other disclosures as the Banking board may require.")))
    check("AJ1 does not protect a notice item ('he or she may contest')", not ed.AJ1_BODY_MAY.search("information advising the person charged of the manner and the time in which he or she may contest the liability") and not ed.AJ1_BODY_SUBJECT.match("The name and address of the person alleged to be liable"))
    check("AJ1 body subject: 'The department ...' is kept", bool(ed.AJ1_BODY_SUBJECT.match("The department, in consultation with the board")))
    check("AJ1 name-of-the-county phrase is not a body subject", not ed.AJ1_BODY_SUBJECT.match("The name of the county in which the vehicle was registered"))
    ed.APPLY_AJ3 = True
    check("AJ3 'fifteenth day of June' fills the next June 15 after enactment", ed.aj3_day_of_month("on or before the fifteenth day of June", "2012-07-18") == ("2013-06-15", "recurring"))
    check("AJ3 day-of-month before enactment's date in the same year", ed.aj3_day_of_month("on or before the fifteenth day of June", "2012-03-01") == ("2012-06-15", "recurring"))
    check("AJ3 due words", all(ed.AJ3_DUE.search(t) for t in ("no later than June 30, 2018", "by December first, two thousand nineteen", "on or before the fifteenth day of June")))
    check("AJ3 start words", all(ed.AJ3_START.match(t) for t in ("Commencing July first, two thousand sixteen", "On or after April first, two thousand twenty-six", "effective April 1, 2025", "The audits shall commence on October 1, 2021")))
    ed.APPLY_AJ2 = True
    check("AJ2 request pattern names the director of the budget", bool(ed.AJ2_REQUEST_OF.search("may be transferred to the general fund upon the request of the director of the budget")))
    check("AJ2 no request, no body", not ed.AJ2_REQUEST_OF.search("shall be expended to fund expansion of medical services, payable on audit and warrant of the comptroller"))
    ed.APPLY_B58 = True
    G = "The [authority] Planetarium Authority shall have power:"
    check("B58 'shall have power:' lead only grants", ed.b58_lead_power(G, "To charge or grant to the museum") and ed.item_lead_kind(G, "Charge admission fees") == "power" and ed.infinitive_lead_kind(G, "To charge fees") == "power")
    check("B58 'shall have the power to:' lead", ed.b58_lead_power("the authority shall have the power to:", "Enter into such agreements"))
    check("B58 'shall have the authority to:' lead", ed.b58_lead_power("a mentoring program agency shall have the authority to:", "Designate which eligible contracts"))
    check("B58 'shall have the following powers:' lead", ed.b58_lead_power("The board shall have the following powers:", "Report to the governor"))
    M = "The commission shall have the following powers and duties:"
    for q in ("To borrow, accept, hire or contract for services of personnel", "To sue and be sued", "To sell, convey, mortgage, pledge, lease, exchange", "To accept any and all donations and grants of money", "M. To establish a budget; N. To sue and be sued;", "adopt, amend and repeal by-laws as it deems necessary"):
        check("B58 discretionary item under powers-and-duties stays power: " + q[:30], ed.b58_lead_power(M, q) and ed.infinitive_lead_kind(M, q) == "power")
    for q in ("To enforce compliance with the compact provisions", "To adopt a seal and bylaws governing the management", "To report annually to the legislatures", "To coordinate education, training and public awareness"):
        check("B58 non-discretionary item under powers-and-duties stays a duty: " + q[:30], not ed.b58_lead_power(M, q) and ed.infinitive_lead_kind(M, q) == "duty")
    check("B58 'shall:' lead is not a grant", not ed.b58_lead_power("The commissioner shall:", "Provide grants"))
    ed.APPLY_B58 = False
    check("B58 off: nothing changes", not ed.b58_lead_power(G, "To charge"))
finally:
    for f, v in saved.items(): setattr(ed, f, v)

# real laws, flag on only for the build
_cache = {}
def build(key, flag):
    if (key, flag) not in _cache:
        sess = int(key.split("-")[0])
        laws = [l for l in ed.signed_laws(sessions=[sess]) if l["key"] == key]
        ed.EFFECTIVE.update(ed.effective_table(laws))
        tmp = Path(tempfile.mkdtemp()); (tmp / (key + ".json")).symlink_to(ed.EXTRACTED / (key + ".json"))
        real, old = ed.EXTRACTED, getattr(ed, flag)
        ed.EXTRACTED = tmp; setattr(ed, flag, True)
        try:
            ed.DROPPED.clear(); dd, pp, _ = ed.build_records(laws)
        finally:
            ed.EXTRACTED = real; setattr(ed, flag, old)
        _cache[(key, flag)] = ({o["obligation_id"]: o for o in dd + pp}, list(ed.DROPPED))
    return _cache[(key, flag)]
def byq(recs, prefix):
    return next((o for o in recs.values() if (o.get("quote") or "").startswith(prefix)), None)
def have(key): return (ed.EXTRACTED / (key + ".json")).exists()
if have("2015-S5196"):
    r, _d = build("2015-S5196", "APPLY_AJ1")
    check("AJ1 2015-S5196-02 county exemption power stays", byq(r, "the county in which such city is located") is not None)
if have("2023-S4674"):
    r, _d = build("2023-S4674", "APPLY_AJ1")
    check("AJ1 2023-S4674 DOH data-agreement power stays", byq(r, "The department may enter into an agreement") is not None)
if have("2013-A9206"):
    r, d = build("2013-A9206", "APPLY_AJ1")
    check("AJ1 2013-A9206 notice-content items still drop", byq(r, "The notice of liability shall contain information advising") is None and any(x["rule"] == "sub_item_of_parent" for x in d))
if have("2009-A41011"):
    r, d = build("2009-A41011", "APPLY_AJ2")
    t = byq(r, "monies in the fund on such date")
    check("AJ2 2009-A41011-11 transfer is reassigned to the Division of the Budget, not dropped", t is not None and t.get("agency") == "DOB")
    r3, _d = build("2009-A41011", "APPLY_AJ3")
    check("AJ3 2009-A41011 stated due dates are filled", all(o.get("deadline_date") for o in r3.values() if o.get("deadline_kind") == "fixed_date"))
if have("2017-A2660"):
    r, d = build("2017-A2660", "APPLY_AJ2")
    check("AJ2 2017-A2660-04 fund-use restriction drops like 2017-A2788-03", byq(r, "Monies of the fund shall be expended to fund expansion") is None)
if have("2011-A10391"):
    r, _d = build("2011-A10391", "APPLY_AJ3")
    o = byq(r, "the superintendent shall submit a report annually")
    check("AJ3 2011-A10391-01 keeps fixed_date with June 15", o is not None and o.get("deadline_kind") == "fixed_date" and (o.get("deadline_date") or "")[5:] == "06-15")
if have("2017-S8910"):
    r, _d = build("2017-S8910", "APPLY_AJ3")
    o = byq(r, "the assessor for the town of Neversink")
    check("AJ3 2017-S8910-01 is never set to none", o is not None and o.get("deadline_kind") == "fixed_date")
if have("2019-A7564"):
    r, _d = build("2019-A7564", "APPLY_AJ3")
    o = byq(r, "The office shall prepare and submit a written report")
    check("AJ3 2019-A7564-01 is never set to none", o is not None and o.get("deadline_kind") == "fixed_date")
if have("2015-A9200"):
    r, _d = build("2015-A9200", "APPLY_AJ3")
    o = byq(r, "Commencing July first, two thousand sixteen")
    check("AJ3 2015-A9200-01 start date is still none", o is not None and o.get("deadline_kind") == "none")
if have("2011-A55"):
    r, _d = build("2011-A55", "APPLY_B58")
    for pre, want in (("To borrow, accept, hire", "power"), ("To sell, convey", "power"), ("M. To establish a budget", "power"), ("To enforce compliance", "duty"), ("To report annually", "duty")):
        o = byq(r, pre)
        check("B58 2011-A55 %s is a %s" % (pre, want), o is not None and (o.get("kind") or o.get("kind_model")) == want)
    m = byq(r, "M. To establish a budget")
    check("B58 2011-A55 M and N stay one stored record, power", m is not None and "N. To sue" in m["quote"])
if have("2009-S3583"):
    r, _d = build("2009-S3583", "APPLY_B58")
    o = byq(r, "To charge or grant to the American Museum")
    check("B58 2009-S3583-06 'shall have power:' item stays a power", o is not None and o.get("kind") == "power")
if have("2009-A3661"):
    r, _d = build("2009-A3661", "APPLY_B58")
    o = byq(r, "Provide grants, from funds appropriated")
    check("B58 2009-A3661-09 'The commissioner shall:' item flips to a duty", o is not None and o.get("kind") == "duty")
print("%d passed, %d failed" % (passed, failed))
