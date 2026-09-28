"""One real API call per structured-output schema before a paid batch run.

Exercises the fiscal extractor, the obligations extractor, and the duty/power
labeller on tiny inputs and exits 1 if any call fails, so a rejected schema or
a bad key costs one request instead of a whole run. Run in Actions (the key is
a repo secret): the "canary" task of claude_backfill.yml.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "civic_reference/legislation_implementation_tracker/pipeline"))

import anthropic  # noqa: E402
import fetch_fiscal_impacts as fis  # noqa: E402
import extract_obligations as eo  # noqa: E402
import label_kinds as lk  # noqa: E402
import verify_fiscal as vf  # noqa: E402
import verify_obligations as vo  # noqa: E402
from claude_batch import cached_content, run_batch, clear_state  # noqa: E402

BATCH_STATE = Path("/tmp/api_canary_batch_state.json")
CANARY_LAW = {"matter_id": "canary-0", "file_number": "Int 0-2026", "law_number_display": "Local Law 1 of 2026",
             "title": "canary test law", "committee": "Test", "enactment_date": "2026-01-01",
             "legistar_indexes": []}

FIS_TEXT = """Fiscal Impact Statement. Proposed Int. No. 123-A. Committee: Transportation.
Sponsors: Council Members Smith, Jones. Effective FY27, FY Succeeding Effective FY28, Full Fiscal Impact FY28.
Expenditures: $0, $250,000, $250,000. Revenues: $0. Net: $0, ($250,000), ($250,000).
Impact on Expenditures: DOT would spend $250,000 annually on signal studies. Source of funds: General Fund.
Estimate prepared by: A. Analyst, Finance Division. Date prepared: March 3, 2026."""
LAW_TEXT = """Be it enacted by the Council as follows: Section 1. The department of transportation shall
post on its website, no later than 180 days after the effective date of this local law, a report on
signal timing. The commissioner may promulgate rules to implement this section. Section 2. This local
law takes effect 120 days after it becomes law."""


def main() -> int:
    client = anthropic.Anthropic()
    ok = True
    try:
        r = fis.extract_fiscal_data(FIS_TEXT, client)
        assert "extraction_error" not in r, r
        print("fiscal ok:", r.get("fy_full_impact"), r.get("total_expenditure"), r.get("totals_basis"))
    except Exception as e:  # noqa: BLE001
        ok = False
        print("FISCAL FAILED:", e)
    try:
        # eo.call_claude already builds cached_content internally (Sep 28
        # 2026: the fixed instructions cache, only metadata/definitions/law
        # text vary), so no separate caching wiring is needed here.
        variable_prompt = eo.render_variable_prompt(CANARY_LAW, LAW_TEXT)
        r = eo.call_claude(client, eo.DEFAULT_MODEL, variable_prompt)
        kinds = [(o["action_summary"][:40], o["provision_kind"], o["deadline"]) for o in r["obligations"]]
        assert kinds, r
        print("obligations ok:", kinds)
    except Exception as e:  # noqa: BLE001
        ok = False
        print("OBLIGATIONS FAILED:", e)
    try:
        content = cached_content(lk._FIXED_PROMPT, lk.render_variable(
            {"lead": "(none)", "clause": "The commissioner may promulgate rules to implement this section.",
             "more": "(none)", "quote": "The commissioner may promulgate rules"}))
        msg = client.messages.create(model=eo.DEFAULT_MODEL, max_tokens=300,
                                     messages=[{"role": "user", "content": content}],
                                     output_config={"format": {"type": "json_schema", "schema": lk.SCHEMA}})
        out = json.loads(next(b.text for b in msg.content if b.type == "text"))
        assert out["kind"] == "power", out
        print("label ok:", out)
    except Exception as e:  # noqa: BLE001
        ok = False
        print("LABEL FAILED:", e)
    # the two Opus verifiers' schemas (Sep 27 2026): a rejected schema must
    # cost one request, not a 358-call or 400-call run. Billing: caching
    # helps little on a one-off 3,000-char schema dump, but is applied for
    # consistency with every other canary call.
    for name, model, schema in (("verify_fiscal", vf.VERIFY_MODEL, vf.VERIFY_SCHEMA),
                                ("verify_obligations", vo.MODEL, vo.RESULT_SCHEMA)):
        try:
            fixed = "Schema test. Return a minimal valid object: one correct verdict, no errors or items "
            variable = "beyond one placeholder where the schema requires a list.\n" + json.dumps(schema)[:3000]
            msg = client.messages.create(
                model=model, max_tokens=4000,
                messages=[{"role": "user", "content": cached_content(fixed, variable)}],
                output_config={"format": {"type": "json_schema", "schema": schema}})
            out = json.loads(next(b.text for b in msg.content if b.type == "text"))
            print(f"{name} ok:", json.dumps(out)[:200])
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"{name.upper()} FAILED:", e)
    # one 1-request batch through run_batch (Sep 28 2026): proves the batch
    # path itself (half price) works before a paid monthly run relies on it.
    try:
        variable_prompt = eo.render_variable_prompt(CANARY_LAW, LAW_TEXT)
        _cid, params = eo.prepare_batch_request(CANARY_LAW, LAW_TEXT)
        out = run_batch(client, [("canary-1", params)], BATCH_STATE, max_wait_s=600, poll_s=15)
        if out is None:
            print("BATCH CANARY: still pending; will resume next run")
        else:
            status, payload = out["canary-1"]
            assert status == "succeeded", (status, payload)
            print("batch canary ok:", status)
            clear_state(BATCH_STATE)  # only after the result above is used
    except Exception as e:  # noqa: BLE001
        ok = False
        print("BATCH CANARY FAILED:", e)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
