"""Plain test script: prints 'N passed, M failed', exit 1 on failure. Run: python3 shared/test_alert_senders.py
Drives the NYC Council alert engine (send_alerts.py) and the CB alert engine (send_cb_alerts.py), live with a fake
SMTP and with DRY_RUN=1, on the small inputs in shared/fixtures/. No network, no secrets, nothing is sent.
Assertions compare sets and substrings, never order, so PYTHONHASHSEED does not matter.
The NYC laws and fiscal records are built here so their dates stay inside the 120-day backfill window."""
import contextlib, email as email_lib, importlib, io, json, os, shutil, smtplib, sys, tempfile
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIX = HERE / "fixtures"
sys.path.insert(0, str(HERE))
os.environ.update(GMAIL_USER="me@example.test", GMAIL_APP_PASSWORD="pw")
os.environ.pop("DRY_RUN", None)

SENT = []


class FakeSMTP:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, u, p):
        pass

    def send_message(self, msg):
        if "fail" in msg["To"]:
            raise smtplib.SMTPRecipientsRefused({})
        SENT.append(email_lib.message_from_bytes(msg.as_bytes()))


def body_of(m):
    return m.get_payload(decode=True).decode("utf-8")


def run_main(mod, dry):
    SENT.clear()
    if dry:
        os.environ["DRY_RUN"] = "1"
    else:
        os.environ.pop("DRY_RUN", None)
    real, smtplib.SMTP_SSL = smtplib.SMTP_SSL, FakeSMTP
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            mod.main()
    finally:
        smtplib.SMTP_SSL = real
        os.environ.pop("DRY_RUN", None)
    return buf.getvalue(), {m["To"]: m for m in SENT}


def load(rel, name):
    sys.path.insert(0, str(ROOT / rel))
    sys.modules.pop(name, None)
    return importlib.import_module(name)


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


def nyc_cases(tmp):
    out = []
    mod = load("civic_reference/nyc_council_legislation_trackers/pipeline", "send_alerts")
    d = date.today() - timedelta(days=5)
    impl = tmp / "impl"
    write(impl / "laws.json", {"laws": [
        {"matter_id": "L1", "file_number": "Int 1-2026", "law_number_display": "Local Law 1 of 2026", "title": "Alpha housing law",
         "summary": "", "enactment_date": d.isoformat()},
        {"matter_id": "L2", "file_number": "Int 2-2026", "law_number_display": "Local Law 2 of 2026", "title": "Beta parks law",
         "summary": "", "enactment_date": d.isoformat()}]})
    write(impl / "obligations.json", {"obligations": []})
    write(tmp / "fiscal.json", {"records": [
        {"matter_id": "F1", "file_number": "Int 1-2026", "title": "Alpha fiscal bill", "date_prepared": d.isoformat(),
         "net_fiscal_impact": -2500000, "legistar_url": "https://legistar.example.test/F1", "agencies_abbrev": []}]})
    write(tmp / "members.json", {"members": []})
    mod.IMPL_DATA, mod.FISCAL_JSON, mod.MEMBERS_JSON = impl, tmp / "fiscal.json", tmp / "members.json"
    mod.REPORT_FILINGS_JSON, mod.MEMBER_CONTEXT_JSON = tmp / "none1.json", tmp / "none2.json"

    prem = tmp / "premium_nyc"
    pdata = prem / "civic_reference" / "legislation_implementation_tracker" / "data"
    pdata.mkdir(parents=True)
    shutil.copy(FIX / "alerts_subs.csv", pdata / "alert_subscriptions.csv")
    state = pdata / "alerts_state.json"
    shutil.copy(FIX / "alerts_state.json", state)
    os.environ["PREMIUM_DIR"] = str(prem)

    before = state.read_text()
    log, sent = run_main(mod, dry=True)
    out += [("nyc dry: nothing sent", sent, {}), ("nyc dry: state untouched", state.read_text(), before),
            ("nyc dry: 4 subscribers", "4 subscribers." in log, True),
            ("nyc dry: one block per matching subscriber", log.count("=== DRY RUN to subscriber"), 3),
            ("nyc dry: subject printed", "=== DRY RUN to subscriber 1: NYCuriosity alert: 2 new laws, 1 fiscal estimate\n" in log, True)]

    log, sent = run_main(mod, dry=False)
    out += [("nyc live: recipients", set(sent), {"a@example.test", "b@example.test"}),
            ("nyc live: a subject", sent["a@example.test"]["Subject"], "NYCuriosity alert: 2 new laws, 1 fiscal estimate"),
            ("nyc live: b subject", sent["b@example.test"]["Subject"], "NYCuriosity alert: 1 new law"),
            ("nyc live: from", sent["a@example.test"]["From"], "me@example.test"),
            ("nyc live: a body has both laws and the fiscal bill",
             all(s in body_of(sent["a@example.test"]) for s in ("Alpha housing law", "Beta parks law", "Alpha fiscal bill", "Net cost to the city: $2.5M")), True),
            ("nyc live: b body has only the beta law",
             ("Beta parks law" in body_of(sent["b@example.test"]), "Alpha housing law" in body_of(sent["b@example.test"])), (True, False)),
            ("nyc live: footer", "You receive these alerts as an NYCuriosity member." in body_of(sent["a@example.test"]), True),
            ("nyc live: failure logged by position and type only", "Send failed for subscriber 2/4: SMTPRecipientsRefused" in log, True),
            ("nyc live: no address in the log", "@" in log, False),
            ("nyc live: sent count", "State updated. 2 emails sent." in log, True)]
    st = json.loads(state.read_text())
    out += [("nyc live: state ids", (set(st["announced_matter_ids"]), set(st["announced_fiscal_ids"])), ({"L1", "L2"}, {"F1"})),
            ("nyc live: seeded flag kept", st["deadline_state_seeded"], True)]
    # second run: everything is announced, nobody is emailed
    log, sent = run_main(mod, dry=False)
    out += [("nyc rerun: nothing new, nothing sent", sent, {})]
    return out


def cb_cases(tmp):
    out = []
    mod = load("cb-tools/member-tracker/pipeline", "send_cb_alerts")
    mod.DATA = tmp / "cbdata"
    mod.DATA.mkdir()
    shutil.copy(FIX / "cb_boards.json", mod.DATA / "boards.json")
    shutil.copy(FIX / "cb_members.json", mod.DATA / "members.json")
    prem = tmp / "premium_cb"
    pdata = prem / "cb-tools" / "member-tracker" / "data"
    pdata.mkdir(parents=True)
    shutil.copy(FIX / "cb_subs.csv", pdata / "cb_alert_subscriptions.csv")
    state = pdata / "cb_alerts_state.json"
    os.environ["PREMIUM_DIR"] = str(prem)

    # no state yet: seeded, nothing sent
    log, sent = run_main(mod, dry=False)
    out += [("cb seed: nothing sent", sent, {}), ("cb seed: message", "No previous state; snapshot seeded, no alerts sent." in log, True),
            ("cb seed: snapshot written", set(json.loads(state.read_text())["snapshot"]), {"101", "102"})]

    shutil.copy(FIX / "cb_state_prev.json", state)
    before = state.read_text()
    log, sent = run_main(mod, dry=True)
    out += [("cb dry: nothing sent", sent, {}), ("cb dry: state untouched", state.read_text(), before),
            ("cb dry: 2 change events", "2 change events detected." in log, True),
            ("cb dry: one block per matching subscriber", log.count("=== DRY RUN to subscriber"), 3)]

    log, sent = run_main(mod, dry=False)
    out += [("cb live: recipients", set(sent), {"a@example.test", "b@example.test"}),
            ("cb live: a subject", sent["a@example.test"]["Subject"], "NYCuriosity alert: 2 community board changes on your watchlist"),
            ("cb live: a body", all(s in body_of(sent["a@example.test"]) for s in
                                    ("chair is now Alice Example (was Old Chair Person)", "1 member added to the published roster: Alice Example",
                                     "Board page: https://data.nycuriosity.com/cb-tools/member-tracker/board/?cd=101")), True),
            ("cb live: failure logged by position and type only", "Send failed for subscriber 2/5: SMTPRecipientsRefused" in log, True),
            ("cb live: no address in the log", "@" in log, False),
            ("cb live: sent count", "State updated. 2 emails sent." in log, True)]
    snap = json.loads(state.read_text())["snapshot"]
    out += [("cb live: state now current", (snap["101"]["chair"], snap["101"]["members"]), ("Alice Example", ["Alice Example", "Bob Example"]))]
    log, sent = run_main(mod, dry=False)
    out += [("cb rerun: no changes, nothing sent", (sent, "No leadership or roster changes" in log), ({}, True))]
    return out


tmp = Path(tempfile.mkdtemp())
try:
    results = nyc_cases(tmp) + cb_cases(tmp)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
passed = failed = 0
for name, got, want in results:
    if got == want:
        passed += 1
    else:
        failed += 1
        print("FAIL %s: got %r want %r" % (name, got, want))
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
