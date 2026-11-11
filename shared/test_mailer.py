"""Plain test script: prints 'N passed, M failed', exit 1 on failure. Run: python3 shared/test_mailer.py
smtplib.SMTP_SSL is replaced by a fake; nothing is sent."""
import contextlib, io, os, smtplib, sys, tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alert_engine
import mailer

REAL = smtplib.SMTP_SSL


class Fake:
    """Scripted SMTP_SSL: `script` is a list of exceptions (or None for success), one per connection."""
    script = []
    calls = []

    def __init__(self, *a, **k):
        Fake.calls.append(("init", a, k))
        self.step = Fake.script.pop(0) if Fake.script else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        Fake.calls.append(("exit",))
        return False

    def login(self, u, p):
        Fake.calls.append(("login", u, p))

    def send_message(self, msg):
        if self.step:
            raise self.step
        Fake.calls.append(("send_message", msg["To"]))

    def sendmail(self, f, t, s):
        if self.step:
            raise self.step
        Fake.calls.append(("sendmail", f, t))


def run(script, **kw):
    Fake.script, Fake.calls = list(script), []
    smtplib.SMTP_SSL = Fake
    sleeps, err = [], io.StringIO()
    msg = mailer.compose("S", "me@x.test", "you@x.test", "body")
    raised = None
    try:
        with contextlib.redirect_stderr(err):
            mailer.send_gmail(msg, "me@x.test", "pw", sleep=sleeps.append, **kw)
    except Exception as e:  # noqa: BLE001
        raised = e
    finally:
        smtplib.SMTP_SSL = REAL
    return raised, [c for c in Fake.calls if c[0] in ("init", "send_message", "sendmail")], sleeps, err.getvalue()


def compose_cases():
    m = mailer.compose("Subj", "a@x.test", "b@x.test", "hello")
    h = mailer.compose("Subj", "a@x.test", "b@x.test", "hello", html="<b>x</b>", charset="utf-8")
    return [
        (list(m.keys()), ["Content-Type", "MIME-Version", "Content-Transfer-Encoding", "Subject", "From", "To"]),
        (m.get_content_type(), "text/plain"),
        (h.get_content_type(), "multipart/alternative"),
        ([p.get_content_type() for p in h.get_payload()], ["text/plain", "text/html"]),
    ]


def cases():
    out = []
    # success: one connection, no timeout kwarg unless asked, send_message
    r, calls, sl, _ = run([None])
    out += [(r, None), (calls[0], ("init", ("smtp.gmail.com", 465), {})), (calls[1][0], "send_message"), (sl, [])]
    r, calls, _, _ = run([None], timeout=30, envelope_to=["a@x.test"])
    out += [(calls[0][2], {"timeout": 30}), (calls[1], ("sendmail", "me@x.test", ["a@x.test"]))]
    # retryable failure then success
    r, calls, sl, err = run([smtplib.SMTPServerDisconnected("x"), None], retries=2, retry_delay=1.5)
    out += [(r, None), ([c[0] for c in calls], ["init", "init", "send_message"]), (sl, [1.5]),
            ("SMTPServerDisconnected" in err and "@" not in err, True)]
    r, calls, sl, _ = run([smtplib.SMTPDataError(452, b"try later"), TimeoutError(), None], retries=2, retry_delay=1)
    out += [(r, None), (sl, [1, 2])]
    # retryable failure that never clears: raised after retries + 1 attempts
    r, calls, sl, _ = run([smtplib.SMTPServerDisconnected()] * 5, retries=2)
    out += [(type(r), smtplib.SMTPServerDisconnected), (len([c for c in calls if c[0] == "init"]), 3)]
    # default: no retry, the error propagates after one attempt (as every sender behaved before)
    r, calls, sl, _ = run([smtplib.SMTPServerDisconnected()])
    out += [(type(r), smtplib.SMTPServerDisconnected), (len(calls), 1), (sl, [])]
    # permanent failures: raised at once even with retries
    for perm in (smtplib.SMTPAuthenticationError(535, b"bad"), smtplib.SMTPRecipientsRefused({}), smtplib.SMTPDataError(554, b"no"), ValueError("x")):
        r, calls, sl, _ = run([perm], retries=3)
        out += [(r is perm, True), (len(calls), 1), (sl, [])]
    return out


def alert_cases():
    out = []
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "subs.csv"
        p.write_text("email,boards\na@x.test,1;2\n,3\n b@x.test ,\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            subs = alert_engine.read_subscribers(p, "subs.csv")
            none = alert_engine.read_subscribers(Path(d) / "missing.csv", "missing.csv")
        out += [([s["email"] for s in subs], ["a@x.test", " b@x.test "]), (none, []),
                (buf.getvalue(), "2 subscribers.\nNo missing.csv; skipping sends.\n0 subscribers.\n"),
                (alert_engine.splitfield(subs[0], "boards"), {"1", "2"}), (alert_engine.splitfield(subs[1], "boards"), set())]
        sp = Path(d) / "x" / "state.json"
        out += [(alert_engine.read_state(sp, {}), {})]
        alert_engine.write_state(sp, {"a": 1}, mkdir=True)
        out += [(sp.read_text(), '{\n "a": 1\n}'), (alert_engine.read_state(sp), {"a": 1})]
    # deliver: dry prints, live sends, failure returns False and logs type only
    os.environ.update(GMAIL_USER="me@x.test", GMAIL_APP_PASSWORD="pw")
    buf = io.StringIO()
    Fake.script, Fake.calls = [None, smtplib.SMTPRecipientsRefused({})], []
    smtplib.SMTP_SSL = Fake
    try:
        with contextlib.redirect_stdout(buf):
            ok_dry = alert_engine.deliver("a@x.test", "S", "B", 1, 3, 2, True)
            ok_live = alert_engine.deliver("a@x.test", "S", "B", 2, 3, 2, False)
            ok_fail = alert_engine.deliver("a@x.test", "S", "B", 3, 3, 2, False)
    finally:
        smtplib.SMTP_SSL = REAL
    out += [((ok_dry, ok_live, ok_fail), (True, True, False)),
            (buf.getvalue(), "\n=== DRY RUN to subscriber 1: S\nB\n\nSent alert 2/3: 2 matches\nSend failed for subscriber 3/3: SMTPRecipientsRefused\n")]
    return out


passed = failed = 0
for i, (got, want) in enumerate(compose_cases() + cases() + alert_cases()):
    if got == want:
        passed += 1
    else:
        failed += 1
        print("FAIL case %d: got %r want %r" % (i, got, want))
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
