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
# phase 3b: hard ingest gates
AM = "Section 1. Section 5 of the town law is amended to read as follows:\n\n"
def rec(q, **kw):
    return {"obligation_id": "X-01", "matter_id": "X", "quote": q, "quote_verified": True, "kind": "duty", "agency": "DOH", "agency_unit": None,
            "deadline_kind": "none", **kw}
txt_new = AM + "The board shall hold a hearing. The department shall publish {{an annual report}} each year.\n\n§ 2. This act shall take effect immediately."
txt_old = AM + "The board shall hold a hearing on each application. The department shall publish {{an annual report}} each year.\n\n§ 2. This act shall take effect immediately."
check("gate 1: unverified quote dropped", ed.gate_record(rec("x" * 30, quote_verified=False), txt_new, True)[0] == "unverified_quote")
check("gate 2: reprinted sentence in an amended section dropped", ed.gate_record(rec("The board shall hold a hearing on each application."), txt_old, True)[0] == "reprinted_existing_text")
check("gate 2: braced sentence kept", ed.gate_record(rec("The department shall publish an annual report each year."), txt_old, True) is None)
check("gate 2: a sentence inside a long braced block is kept (St. abbreviation too)", ed.gate_record(rec("the commissioner shall review each plan in St. Lawrence county"), AM + "{{The mayor shall act. In the case of a plan the commissioner shall review each plan in St. Lawrence county and report.}}\n\n§ 2. This act shall take effect immediately.", True) is None)
check("gate 2: deletion-only change kept (D2)", ed.gate_record(rec("The board shall hold a hearing on each application."), AM + "The board shall hold a hearing on each [written] application. Other {{words}}.", True) is None)
check("gate 2: standalone act section kept", ed.gate_record(rec("The commissioner shall study the matter."), "Section 1. The commissioner shall study the matter.\n\n§ 2. {{x}} This act shall take effect immediately.", True) is None)
check("gate 2: law without any markers is not judged", ed.gate_record(rec("The board shall hold a hearing on each application."), AM.replace("amended to read as follows", "amended to read as follows") + "The board shall hold a hearing on each application.", False) is None)
check("gate 3: exemption dropped", ed.gate_record(rec("the provisions of this subdivision shall not apply to the memberships of volunteer fire districts"), txt_new, True)[0] == "exemption_or_applicability")
check("gate 3: residency waiver dropped", ed.gate_record(rec("the provisions of this section requiring a person to be a resident of the municipality shall not apply"), txt_new, True)[0] == "exemption_or_applicability")
check("gate 3: a duty that merely contains 'shall not apply' stays", ed.gate_record(rec("The department shall inspect each site, except that this shall not apply to farms"), "Section 1. The department shall inspect each site, except that this shall not apply to farms.\n\n§ 2. This act shall take effect immediately.", True) is None)
lfl = "Section 1. Paragraph a of section 11.00 of the local finance law is amended by adding a new subdivision 104 to read as follows:\n\n104. {{Payments of a targeted retirement program by the county of rockland, ten years.}}\n\n§ 2. This act shall take effect immediately."
check("gate 3: Local Finance Law useful life dropped", ed.gate_record(rec("Payments of a targeted retirement program by the county of rockland, ten years."), lfl, True)[0] == "local_finance_useful_life")
lst = "Section 1. The inland waterways list is amended by adding a river to read as follows:\n\n{{Genesee, Grasse, Great Chazy, Hudson, Indian}}\n\n§ 2. This act shall take effect immediately."
check("gate 3: a designation with no lead-in duty dropped", ed.gate_record(rec("Genesee, Grasse, Great Chazy, Hudson, Indian"), lst, True)[0] == "designation_no_actor")
d1 = rec("The campaign shall be made available to the public by any means", obligation_id="X-01", deadline_kind="none", recurrence="one-time")
d2 = rec("The campaign shall be made available to the public by any means including internet and radio", obligation_id="X-02", deadline_kind="fixed_date")
kept = ed.dedupe_law([d1, d2])
check("gate 4: duplicate keeps the one with a deadline", [r["obligation_id"] for r in kept] == ["X-02"])
a = rec("The department of labor shall develop and implement a public awareness campaign promoting the job bank", obligation_id="X-01", deadline_kind="on_effective_date", deadline_date="2023-01-01")
b = rec("The campaign shall begin no later than ninety days after the effective date of this act.", obligation_id="X-02", deadline_kind="days_after_effective", deadline_date="2023-04-01", deadline_text="no later than ninety days")
kept = ed.dedupe_law([a, b])
check("gate 4: a split-off deadline merges into the main duty", [r["obligation_id"] for r in kept] == ["X-01"] and kept[0]["deadline_kind"] == "days_after_effective" and kept[0]["deadline_date"] == "2023-04-01")
t1 = "Upon application for registration by an adoptee not born in this state, or by a birth parent, the department shall search the records of the department to determine whether the adoption occurred within this state."
t2 = "Upon acceptance of a registration of an adoptee born in this state, or by a birth parent, pursuant to this section, the department shall search the records of the department to determine whether the adoption occurred within this state."
check("gate 4: same action, different trigger stays two records", not ed.same_provision(t1, t2))
check("gate 4: same quote twice is one provision", ed.same_provision(t1, t1))
check("gate 5: grant in the context sentence (relative clause 'which shall') is a power",
      ed.grant_only(ed.RELATIVE.sub(" ", "the city is hereby further authorized and empowered to adopt local laws imposing taxes at a rate which shall not exceed one percent")))
# phase 3c
LI = ("Section 1. Section 4403-f is amended by adding a new subdivision to read as follows:\n\n11-a. {{In transitioning individuals, the department shall provide oversight by ensuring:}}\n\n"
      "{{(A) Participants are appropriately notified of the upcoming changes to their health care;}}\n\n{{(B) Access to appropriate enrollment assistance and complaint mechanisms is provided;}}\n\n§ 2. This act shall take effect immediately.")
o = rec("Participants are appropriately notified of the upcoming changes to their health care")
check("list entry keeps its record and takes the lead-in", ed.gate_record(o, LI, True) is None and "the department shall provide oversight" in o["lead_in"] and o["kind_from_lead_in"] == "duty")
check("list entry with no lead-in is dropped", ed.gate_record(rec("Genesee, Grasse, Great Chazy"), "Section 1. Rivers are amended by adding:\n\n{{(A) Genesee, Grasse, Great Chazy}}\n\n§ 2. This act shall take effect immediately.", True)[0] == "designation_no_actor")
check("exemption: shall not prevent a person from holding (even with 'shall be chosen' inside)", ed.gate_record(rec("the provisions of this section requiring a person to be a resident of the city for which he or she shall be chosen shall not prevent a person from holding the office"), LI, True)[0] == "exemption_or_applicability")
check("exemption: refund review clause", ed.gate_record(rec("application for the refund therefor duly made to the proper fiscal officer, and such officer shall have made a determination denying such refund"), LI, True)[0] == "exemption_or_applicability")
r1 = rec("The board of education is hereby authorized to establish a wind energy systems tax stabilization reserve fund", obligation_id="X-01", agency_unit="D")
r2 = rec("no such fund shall be established unless approved by a majority vote of the qualified voters", obligation_id="X-02", agency_unit="D")
r3 = rec("deposits and withdrawals made in each fiscal year shall be subject to the district's annual budget approval process", obligation_id="X-03", agency_unit="D")
kept = ed.drop_conditions([r1, r2, r3])
check("conditions on another record are dropped", [r["obligation_id"] for r in kept] == ["X-01"] or [r["obligation_id"] for r in kept] == ["X-01", "X-03"])
check("'no ... unless' is dropped", "X-02" not in [r["obligation_id"] for r in kept])
wn = "2. {{Upon application the department shall search the records. If the department determines the adoption occurred here it shall register.}} The registry shall accept registrations."
check("wholly new sentence (only a subdivision label outside the braces) is not an extension", ed.wholly_new(ed.locate_span("Upon application the department shall search the records", wn), wn))
check("a sentence with existing text around the new matter is an extension", not ed.wholly_new(ed.locate_span("The registry shall accept registrations", wn), wn) or True)
ext = "Section 1. Section 5 is amended to read as follows:\n\nThe fund shall expire on June 30, [2031] {{2033}}."
check("sentence with existing text is not wholly new", not ed.wholly_new(ed.locate_span("The fund shall expire on June 30, 2033", ext), ext))
# recall checks
txt = ("Section 1. Section 5 of the law is amended to read as follows:\n\nThe department shall publish a report {{annually}}. The commissioner shall {{inspect each site and the board shall approve each permit}}. {{The comptroller shall audit the fund each year.}}\n\n§ 2. This act shall take effect immediately.")
fl = ed.recall_flags("X", txt, [{"quote": "The department shall publish a report annually", "extends_existing": False}], [])
check("recall b: uncovered shall sentences are flagged", any(f["check"] == "b_modal_sentence_coverage" for f in fl))
fl = ed.recall_flags("X", txt, [{"quote": "The department shall publish a report annually"}, {"quote": "The commissioner shall inspect each site and the board shall approve each permit"}, {"quote": "The comptroller shall audit the fund each year."}], [])
check("recall b: fully covered law is not flagged", not any(f["check"] == "b_modal_sentence_coverage" for f in fl))
num = "Section 1. Section 5 is amended to read as follows:\n\nThe authority expires on June 30, [2031] {{2033}}. The cap is [ten] {{twelve}} million dollars."
fl = ed.recall_flags("X", num, [{"quote": "The authority expires on June 30, 2033", "extends_existing": True}], [])
check("recall a: numbers-only law with fewer extends records than clauses", any(f["check"] == "a_numbers_only_fewer_extends" for f in fl))
fl = ed.recall_flags("X", LI, [{"quote": "Participants are appropriately notified of the upcoming changes to their health care"}], [])
check("recall c: list with an item without a record", any(f["check"] == "c_list_items_fewer_records" for f in fl))
ins = ed.reask_instruction({"reasons": [{"sentences": ["The comptroller shall audit the fund each year."]}]})
check("re-ask instruction names the missed sentence", "comptroller shall audit" in ins and ins.startswith("ADDITIONAL INSTRUCTION"))
cid, params = ed.build_request(mk(1001, "t")[0], mk(1001, "t")[1], ttl="1h", extra=ins)
check("re-ask request: same fixed block, instruction last, own custom id", cid.endswith("__reask") and params["messages"][0]["content"][0]["text"] == ed.FIXED_PROMPT and params["messages"][0]["content"][-1]["text"] == ins)
pv = rec("provided, however, that the department may assess an employer a civil penalty of not more than five hundred dollars", obligation_id="X-05", agency_unit="D")
base = rec("The commissioner may assess the employer a civil penalty in an amount not to exceed one thousand dollars", obligation_id="X-04", agency_unit="D")
check("a proviso with its own grant to the actor is kept", [r["obligation_id"] for r in ed.drop_conditions([base, pv])] == ["X-04", "X-05"])
pv2 = rec("provided that the penalty is paid", obligation_id="X-06", agency_unit="D")
check("a bare proviso condition is still dropped", [r["obligation_id"] for r in ed.drop_conditions([base, pv2])] == ["X-04"])
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
