# Extraction audit criteria (Sep 27 2026)

Read-only. Judge each record against the source document in its packet only. Write your results file with a python heredoc via Bash (you have no Write tool); touch nothing else.

## Duties and powers (Obligations / Powers trackers)
A record is CORRECT if all hold:
(1) the quote appears in the law text (ignore {{ }} markers and whitespace);
(2) it is a real duty (the law requires a city agency or official to do something) or power (the law authorises one to act), not a private party's obligation or a construction clause;
(3) the agency is right, or honestly unresolved when the law names none; when a `unit` is shown, the unit is the office/body the law names and the agency is its parent or convening agency (offices inside a department count under the department; task forces/boards under the agency that convenes them; Mayor's Office only when the law has the mayor create or designate it; "Citywide (all agencies)" only for duties on every/each/all/any agency);
(4) kind duty/power is right;
(5) deadline and recurrence are right, or blank when the law states none (powers carry no deadline by design);
(6) it is new matter this law creates, or is flagged existing_code=True when the law only reprints it.
Otherwise WRONG: name the failed criterion. A duplicate of another record in the same law is WRONG. MISSED = a duty or power the law creates in new matter with no record.

## Fiscal estimates (Fiscal Impacts tracker)
The tracker keeps ONE figure per category per bill. Rules it applies (check the record against them, not against your own preference):
- total_expenditure/total_revenue/total_capital come from the statement's table: the "Full Fiscal Impact" column (an ANNUAL amount at full implementation); when there is no Full column, the last fiscal-year column; the sum of columns when the full column is zero (a one-time cost); the narrative's stated figure only when the table is empty. Costs are positive; a revenue loss is a cost.
- Costs the statement says are already in the city's Financial Plan/budget are left out (costs_already_in_financial_plan).
- A time-limited program (pilot) whose end the statement states: if the statement's columns cover the whole program, the figure is the sum of its years (totals_basis program_life_sum); if the program outlasts the columns, the figure is the annual full-impact amount with outlasts_statement=true and program_end_fy set.
- net_fiscal_impact = revenue - expenditure - capital (negative = cost to the city).
- totals_basis names which rule produced the figure.
A record is CORRECT if its figures, basis, flags and agencies follow those rules from the statement; else WRONG with the exact field and the right value.

## Results format

Auditors write results as structured JSON, not prose, so every round can be scored and merged
into the gold set by machine.

### Obligations / Powers (per law, keyed by matter_id)

```json
{
  "<matter_id>": {
    "records": {
      "R1": {
        "verdict": "correct" | "wrong",
        "criteria": ["3"],
        "fields": {"agency": "<the right value, when verdict is wrong>"},
        "note": "one line, cite the section"
      }
    },
    "missed": [
      {"quote": "...", "kind": "duty" | "power", "agency": "...", "note": "..."}
    ]
  }
}
```

`criteria` names every criterion number (1-6, see above) the record fails; leave it out or empty
when `verdict` is `"correct"`. `fields` carries the right value only for fields the record actually
got wrong (an auditor who does not state a right value leaves the field out; `score_gold.py` then
stores `{"not": "<the wrong value>"}` instead of a positive claim). `missed` lists a duty or power
the law creates that has no record at all.

### Fiscal (per bill, keyed by matter_id)

```json
{
  "<matter_id>": {
    "verdict": "correct" | "wrong",
    "errors": [
      {"field": "total_capital", "tracker_value": null, "right_value": 1800000,
       "evidence": "quote or citation from the statement"}
    ]
  }
}
```

One verdict per bill (the tracker keeps one figure per category), with one `errors` entry per
wrong field. `right_value` is required whenever it is knowable from the statement.
