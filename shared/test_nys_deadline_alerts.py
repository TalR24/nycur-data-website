"""Plain test script: prints 'N passed, M failed', exit 1 on failure. Run: python3 shared/test_nys_deadline_alerts.py
Drives the NYC Council alert engine (send_alerts.py) for the NYS deadline section: a subscriber with nys_agencies gets
"New York State deadlines" with the right duties and links, a subscriber without the column is unchanged, DRY_RUN sends
nothing and writes no state. Fake SMTP, scratch data only; no network, no secrets."""
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
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def login(self, u, p): pass
    def send_message(self, msg): SENT.append(email_lib.message_from_bytes(msg.as_bytes()))


def body_of(m): return m.get_payload(decode=True).decode("utf-8")


def run_main(mod, dry):
    SENT.clear()
    if dry: os.environ["DRY_RUN"] = "1"
    else: os.environ.pop("DRY_RUN", None)
    real, smtplib.SMTP_SSL = smtplib.SMTP_SSL, FakeSMTP
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            mod.main()
    finally:
        smtplib.SMTP_SSL = real
        os.environ.pop("DRY_RUN", None)
    return buf.getvalue(), {m["To"]: m for m in SENT}


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


def setup(tmp, subs_csv):
    sys.path.insert(0, str(ROOT / "civic_reference/nyc_council_legislation_trackers/pipeline"))
    sys.modules.pop("send_alerts", None)
    mod = importlib.import_module("send_alerts")
    d = date.today() - timedelta(days=5)
    impl = tmp / "impl"
    write(impl / "laws.json", {"laws": [{"matter_id": "L1", "file_number": "Int 1-2026", "law_number_display": "Local Law 1 of 2026",
                                          "title": "Alpha housing law", "summary": "", "enactment_date": d.isoformat()}]})
    write(impl / "obligations.json", {"obligations": []})
    write(tmp / "fiscal.json", {"records": []})
    write(tmp / "members.json", {"members": []})
    mod.IMPL_DATA, mod.FISCAL_JSON, mod.MEMBERS_JSON = impl, tmp / "fiscal.json", tmp / "members.json"
    mod.REPORT_FILINGS_JSON, mod.MEMBER_CONTEXT_JSON = tmp / "none1.json", tmp / "none2.json"
    soon = (date.today() + timedelta(days=10)).isoformat()
    later = (date.today() + timedelta(days=200)).isoformat()
    past = (date.today() - timedelta(days=3)).isoformat()
    site = tmp / "nys_site"
    write(site / "agencies.json", [{"name": "DOH", "full_name": "Department of Health"}, {"name": "DEC", "full_name": "Department of Environmental Conservation"}])
    write(site / "records_2025.json", [
        {"i": "2025-S1-01", "l": "2025-S1", "k": "d", "a": "DOH", "s": "Report on clinic wait times.", "dd": soon},
        {"i": "2025-S1-02", "l": "2025-S1", "k": "d", "a": "DEC", "s": "Adopt rules on wetlands.", "dd": soon},
        {"i": "2025-S1-03", "l": "2025-S1", "k": "d", "a": "DOH", "s": "Too far out.", "dd": later},
        {"i": "2025-S1-04", "l": "2025-S1", "k": "d", "a": "DOH", "s": "Already past.", "dd": past},
        {"i": "2025-S1-05", "l": "2025-S1", "k": "p", "a": "DOH", "s": "A power, not a duty.", "dd": soon}])
    mod.NYS_SITE = site
    prem = tmp / "premium"
    pdata = prem / "civic_reference" / "legislation_implementation_tracker" / "data"
    pdata.mkdir(parents=True)
    (pdata / "alert_subscriptions.csv").write_text(subs_csv)
    shutil.copy(FIX / "alerts_state.json", pdata / "alerts_state.json")
    os.environ["PREMIUM_DIR"] = str(prem)
    return mod, pdata / "alerts_state.json"


results = []
tmp = Path(tempfile.mkdtemp())
try:
    # column absent for old rows, present for the NYS subscriber; "nys@" has NYS agencies but nothing NYC-side
    csv_old = "email,trackers,agencies,members,keywords,districts,added\nold@example.test,impl,,,alpha,,\n"
    csv_new = ("email,trackers,agencies,members,keywords,districts,added,nys_agencies\n"
               "old@example.test,impl,,,alpha,,,\n"
               "both@example.test,impl,,,alpha,,,doh\n"
               "nys@example.test,impl,,,zzzqqq,,,doh\n"
               "empty@example.test,impl,,,alpha,,,dec-x\n"
               "other@example.test,impl,,,zzzqqq,,,dec-x\n"
               "kw@example.test,impl,,,clinic,,,dec-x\n")
    mod, state = setup(tmp, csv_old)
    log, sent_old = run_main(mod, dry=False)
    old_body = body_of(sent_old["old@example.test"])
    results += [("old csv: no NYS section", "New York State" in old_body, False),
                ("old csv: NYS data not read", "NYS deadlines" in log, False),
                ("old csv: state has no NYS key", "announced_nys_upcoming_ids" in json.loads(state.read_text()), False)]

    tmp2 = Path(tempfile.mkdtemp())
    try:
        mod, state = setup(tmp2, csv_new)
        before = state.read_text()
        log, sent = run_main(mod, dry=True)
        results += [("dry: nothing sent", sent, {}), ("dry: state untouched", state.read_text(), before),
                    ("dry: section printed", "New York State deadlines" in log, True)]
        log, sent = run_main(mod, dry=False)
        both = body_of(sent["both@example.test"])
        url = "https://data.nycuriosity.com/civic_reference/nys_legislation_trackers/duties/?id="
        results += [("new: recipients", set(sent), {"old@example.test", "both@example.test", "nys@example.test", "empty@example.test"}),
                    ("new: unchanged body for subscriber without the field", body_of(sent["old@example.test"]), old_body),
                    ("new: heading", "New York State deadlines" in both, True),
                    ("new: right duty with agency, law, date and link",
                     ("- Department of Health: Report on clinic wait times. (2025-S1), due " in both, "\n  Duty page: " + url + "2025-S1-01" in both), (True, True)),
                    ("new: other agency, far, past and power excluded",
                     any(x in both for x in ("wetlands", "Too far out", "Already past", "A power", "2025-S1-02")), False),
                    ("new: NYS-only subscriber gets an email", "Report on clinic wait times." in body_of(sent["nys@example.test"]), True),
                    ("new: NYS-only subject", sent["nys@example.test"]["Subject"], "NYCuriosity alert: 1 NYS deadline"),
                    ("new: both subject", sent["both@example.test"]["Subject"], "NYCuriosity alert: 1 new law, 1 NYS deadline"),
                    ("new: empty state when no agency match",
                     "No NYS deadlines for your public bodies this month." in body_of(sent["empty@example.test"]), True),
                    ("new: keywords do not match NYS duties", "kw@example.test" in sent, False),
                    ("new: no email for empty NYS and no NYC news", "other@example.test" in sent, False),
                    ("new: state records announced ids", json.loads(state.read_text())["announced_nys_upcoming_ids"], ["2025-S1-01", "2025-S1-02"])]
        log, sent = run_main(mod, dry=False)
        results += [("rerun: NYS duties not repeated", [b for b in (body_of(m) for m in sent.values()) if "clinic wait" in b], [])]
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

passed = failed = 0
for name, got, want in results:
    if got == want: passed += 1
    else:
        failed += 1
        print("FAIL %s: got %r want %r" % (name, got, want))
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
