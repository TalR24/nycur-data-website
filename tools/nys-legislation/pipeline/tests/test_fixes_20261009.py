"""Plain script: the Oct 9 2026 audit fixes F1-F4 (effective clause, local boards of elections, parenthetical actors, proviso
extensions) and the re-ask rules J1-J4. Uses the cached marked texts of the audited laws when present. Prints 'N passed, M failed'."""
import os, sys
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed
import effective_date as efd

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

TM = HERE / "cache" / "text_marked"
def law_text(key):
    p = TM / (key + ".txt")
    return p.read_text() if p.exists() else None

# F1. the act's own sentence beats a proviso that also says "shall take effect"
clause = ("§ 1. Something is amended.\n\n§ 4. This act shall take effect July 1, 2014 provided, however, that:\n\n"
          "(a) the amendments made by section one of this act shall be subject to expiration, when upon such date section two of this act shall take effect; and\n\n"
          "(b) effective immediately, the department may adopt rules.")
eff = efd.parse_effective(clause, "2013-12-01")
check("F1 synthetic: date before 'provided'", eff["effective_date"] == "2014-07-01" and eff["raw_clause"].startswith("§ 4. This act shall take effect"))
t = law_text("2013-A9744")
if t:
    check("F1 2013-A9744 -> 2014-07-01", efd.parse_effective(t, "2013-12-01")["effective_date"] == "2014-07-01")
check("F1 plain clause unchanged", efd.parse_effective("§ 2. This act shall take effect immediately.", "2013-05-01")["effective_date"] == "2013-05-01")

# F2. boards of elections without 'state' are local
o = {"actor_raw": "The board of Elections", "actor_resolved_model": "boards of elections", "agency": "Board of Elections", "agency_full": "State Board of Elections", "jurisdiction": "state", "agency_matched": True}
check("F2 changed", ed.fix_local_board_of_elections(o))
check("F2 2015-S1848-01 resolves local", o["jurisdiction"] == "local" and o["agency"] == "Boards of elections" and o["agency_group"] == "Boards of elections")
o = {"actor_raw": "the state board of elections", "actor_resolved_model": None, "agency": "Board of Elections", "jurisdiction": "state", "agency_matched": True}
check("F2 'state board of elections' stays State", not ed.fix_local_board_of_elections(o) and o["jurisdiction"] == "state")
o = {"actor_raw": "the board of elections of the county of Erie", "actor_resolved_model": "county board of elections", "agency": "Board of Elections", "jurisdiction": "state", "agency_matched": True}
check("F2 named county -> Counties / Erie", ed.fix_local_board_of_elections(o) and o["agency"] == "Counties" and "Erie" in (o["agency_unit"] or ""))

# F3. parenthetical actors
o = {"actor_raw": "voted ballots (board of elections)", "actor_resolved_model": "boards of elections", "agency": "Board of Elections", "agency_matched": True, "jurisdiction": "state"}
check("F3 changed", ed.fix_parenthetical_actor(o))
check("F3 actor_raw is the parenthetical, model text kept", o["actor_raw"] == "board of elections" and o["actor_raw_model"] == "voted ballots (board of elections)")
ed.fix_local_board_of_elections(o)
check("F3 then F2: local", o["jurisdiction"] == "local")
o = {"actor_raw": "the commissioner (department of health)", "agency": "DOH", "agency_matched": True}
check("F3 pre-parenthesis text that resolves is untouched", not ed.fix_parenthetical_actor(o) and o["actor_raw"] == "the commissioner (department of health)" and "actor_raw_model" not in o)
o = {"actor_raw": "payments (see section 4)", "agency": "Unspecified", "agency_matched": False}
check("F3 non-actor parenthetical untouched", not ed.fix_parenthetical_actor(o))

# F4. proviso extensions
t = law_text("2013-A2327")
if t:
    q = "Provided, further that in the case of the Scarsdale union free school district, an insurance reserve fund may be established and such school district may make expenditures from such reserve fund for any loss, claim, action or judgment"
    sp = ed.locate_span(q, t)
    check("F4 proviso is a wholly-new sentence (the old rule cleared it)", bool(sp) and ed.wholly_new(sp, t))
    check("F4 2013-A2327-01 extends existing", ed.proviso_widens_existing(q, t))
syn = "§ 1. Section 5 of the general municipal law is amended to read as follows:\n\n(a) The board may establish a reserve fund to be known as the insurance reserve fund and may make expenditures from the fund for any loss; {{Provided, further that the village of X may establish a separate fund for any loss.}}\n"
check("F4 synthetic proviso", ed.proviso_widens_existing("Provided, further that the village of X may establish a separate fund for any loss.", syn))
syn2 = "§ 1. The general municipal law is amended by adding a new section 6 to read as follows:\n\n{{§ 6. Provided that the board shall keep records of all funds that it holds.}}\n"
check("F4 wholly new section is not an extension", not ed.proviso_widens_existing("Provided that the board shall keep records of all funds that it holds.", syn2))
check("F4 non-proviso quote ignored", not ed.proviso_widens_existing("The board may establish a reserve fund", syn))

# J1. passive subject -> re-ask
text = "§ 1. x\n\nThe costs of the dam shall be paid by the district.\n"
rec = {"obligation_id": "T-01", "actor_raw": "The costs and expenses of the operation of the dam", "quote": "The costs of the dam shall be paid by the district.", "session": 2011}
fl = ed.judgment_flags(text, [rec])
check("J1 passive_subject_actor flagged with quote", any(f["check"] == "passive_subject_actor" and rec["quote"] in f["sentences"] for f in fl))
check("J1 reuses the validator regex", ed.PASSIVE_SUBJECT is __import__("validate_duties").PASSIVE_SUBJECT)
check("J1 body actor not flagged", not ed.judgment_flags(text, [{**rec, "actor_raw": "the department"}]))

# J2. one-word new matter, pre-2017
text = "§ 1. Section 1 is amended to read as follows:\n\nThe assessor, upon approval by the Town of Pelham and Pelham {{ufsd}} Board, may make appropriate correction to the roll.\n"
rec = {"obligation_id": "T-02", "actor_raw": "the assessor", "quote": "The assessor, upon approval by the Town of Pelham and Pelham ufsd Board, may make appropriate correction to the roll.", "session": 2013}
check("J2 condition_only_new_matter flagged", any(f["check"] == "condition_only_new_matter" for f in ed.judgment_flags(text, [rec])))
check("J2 session 2019 not flagged", not any(f["check"] == "condition_only_new_matter" for f in ed.judgment_flags(text, [{**rec, "session": 2019}])))
num = text.replace("{{ufsd}}", "{{fifteen}}")
check("J2 a number is not flagged", not any(f["check"] == "condition_only_new_matter" for f in ed.judgment_flags(num, [{**rec, "quote": rec["quote"].replace("ufsd", "fifteen")}])))
t = law_text("2013-S3070")
if t:
    q = "the assessor, upon approval by the Town of Pelham, Village of Pelham Manor and Pelham ufsd Board, may make appropriate correction to the subject roll."
    check("J2 2013-S3070-02 flagged on the real text", any(f["check"] == "condition_only_new_matter" for f in ed.judgment_flags(t, [{"actor_raw": "the assessor", "quote": q, "session": 2013}])))

# J3. compound local actor
rec = {"actor_raw": "The town of Thompson and the Treasure Lake/Davies dam improvement district", "quote": "The town of Thompson and the district are hereby authorized to issue bonds", "session": 2011}
check("J3 compound_local_actor flagged", any(f["check"] == "compound_local_actor" for f in ed.judgment_flags("x", [rec])))
check("J3 single locality not flagged", not any(f["check"] == "compound_local_actor" for f in ed.judgment_flags("x", [{**rec, "actor_raw": "The town of Thompson"}])))

# J4. the audited one-off misses must reach the re-ask
def flags_for(key):
    t = law_text(key)
    return ed.recall_flags(key, t, [], []) if t else None
fl = flags_for("2011-A7511")
if fl is not None:
    allt = " ".join(" ".join(f["sentences"]) for f in fl)
    check("J4 2011-A7511 window sentence in re-ask", "may be made immediately following the effective date of a local law enacted pursuant to this title" in allt)
fl = flags_for("2009-S7075")
if fl is not None:
    allt = " ".join(" ".join(f["sentences"]) for f in fl)
    check("J4 2009-S7075 eligible-list sentence in re-ask", "the eligible list resulting from such examination may be established" in allt)

print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
