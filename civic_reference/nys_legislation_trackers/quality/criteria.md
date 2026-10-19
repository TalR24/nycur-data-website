# Audit criteria and rules (verbatim)

Copied verbatim from the 20261019 audit brief and the nys-legislation-trackers skill. The nightly audit brief must reference this file by path and never paraphrase it; update it here, only when a decision changes.

## Method (blind, in this order, per law)
1. Read the marked text FIRST. List every duty and power the law gives a New York State or local government actor in NEW matter (inside {{ }} for amended sections; a wholly new section is all new matter). Record for each: actor, duty or power, quote (10-60 words), deadline if any, extends_existing if it widens an existing authority (new sunset date, amount, place, class, or a deletion that widens). Save this blind list before step 2.
2. Only then open the stored records for the law and compare.
3. Verdict per stored record: "correct", "wrong" (a real record with one or more wrong fields; list the fields and the correct values), or "not_real" (should not exist). Every "wrong" or "not_real" verdict cites one or more criteria numbers from section 4 and a one-line note that quotes the law.
4. Missed: every item on your blind list with no stored record (check dropped records too; if it was dropped, say which rule dropped it).
5. Effective date: compute from the act clause and the signing date and compare with the stored effective date.

## Criteria (number them exactly like this in the output)
1. Real record: a concrete duty or power on a State or local government actor, in new matter, not a goal, finding, appropriation amount, exemption, cap, residency rule, Local Finance Law useful-life entry, early-rulemaking boilerplate, a condition of another record, reprinted unchanged text, or a private party's obligation.
2. Quote: verbatim from the law as it reads after amendment (deleted text left out), 10-60 words, in new matter.
3. Actor and agency: the government body that holds the duty or power (never a passive sentence's subject such as "the application"); local governments resolve to the group (Counties, Cities, Towns, Villages, School districts, Fire districts, Special districts...) with the named locality in agency_unit; a locality's assessor, tax office or governing body is the locality, never DTF; NYC actors resolve through the Council crosswalk first; named public authorities and boards keep their own name.
4. Kind: duty (shall, must, is directed) vs power (may, is authorized, is empowered); "authorized and directed" is a duty.
5. Deadline: a one-time setup duty with no stated deadline keeps on_effective_date; a duty triggered by a request, event, precondition or "promptly" has none; a stated date is fixed_date; a period after the effective date is an offset; a cutoff or sunset date is not a deadline.
6. Recurrence and deliverable_type sensible for the text.
7. extends_existing: true when the record widens an existing authority (sunset, amount, place, class, deletion that widens), false when the provision is wholly new.
8. Effective date: act clause applied to the signing date; "same as chapter N of YYYY" resolves to that chapter's date; an amendment signed after the referenced chapter's original effective date leaves that date standing.
9. Duplicate: two stored records for the same provision.

## Pilot rules (orchestrator decisions, Oct 7 2026; reversible, each a field or filter)
- Local governments: `agency` = the group (Counties, Cities, Towns, Villages, School districts, Fire districts, Special
  districts...), `agency_unit` = the named locality, normalised. A locality's assessor, tax office or governing body is the
  locality, never DTF. NYC actors resolve through the Council crosswalk (jurisdiction nyc) BEFORE the State crosswalk.
- Deadlines: Tal's Council rule (option a): a setup duty with no stated deadline keeps on_effective_date; a duty triggered by
  a request, event, precondition or "promptly" gets none.
- Extensions of an existing authority (new sunset date, amount, place, class) ARE records, flagged extends_existing.
- No records: early-rulemaking boilerplate in act clauses, cap/residency exemptions that bind no government actor, Local
  Finance Law useful-life entries, goals/findings, appropriation amounts.
- Text: 2017+ new matter from HTML <b><u>, deletions [<b><s>]; 2009-2015 plain text new matter is UPPERCASE (digits after a
  deletion and single tokens between braced runs braced by rule; status words and citations not); line-break hyphens rejoined.
- Effective dates: act-clause parser plus "same as chapter N of YYYY" resolved through the API (data/chapter_index.json).
- Decided Oct 16 2026 (quality/open_items_decisions_20261016.json): "shall be reviewed as if it had been received on or before the taxable
  status date" is a consequence of the accept-late-application power, not a record (rule reviewed_as_if_condition); legislative bill
  drafting commission notices and the act's own effective/sunset clause are boilerplate (rules act_clause_boilerplate, act_clause),
  while an EARLIER chapter's sunset sentence quoted inside an amendment IS an extension record; omnibus Parts take their own
  "This act shall take effect" clause (Part-scoped section_dates); "... and shall be deemed repealed therewith" is expires_rule
  with_referenced_section; "the state" resolves to the State agencies group with unit State of New York; code ABC displays as
  State Liquor Authority (Division of Alcoholic Beverage Control); relocated quotes are trimmed to 60 words around the new matter;
  every model record the ingest excludes is logged in data/dropped (rules excluded_*), so no id is ever silent.
- Decided Oct 19 2026: a sunset extension of an earlier chapter whose amended sentence names no holder IS a record; the holder
  comes from the act's title or act clause ("relating to authorizing the town of Islip to impose a hotel tax" -> the town of
  Islip), kind power, extends_existing true, record_source sunset_extension_from_title; when the title names no government
  body the law goes to re-ask (check sunset_extension_unnamed_holder). 734 packet laws carry such sentences.
