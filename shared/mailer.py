"""The one Gmail SMTP sender for every script in this repo.

Every sender (the alert engines, the monitors, the health and quality emails, seo/common.py)
builds its own subject and body, then hands the message to send_gmail(). A fix to connecting,
logging in, retrying or logging is made here once.

Import from a script anywhere in the repo (all workflows run from the repo root):
    sys.path.insert(0, str(Path(__file__).resolve().parents[N] / "shared"))   # N = depth below the repo root
    import mailer

Logging is count-only: a failed attempt prints the exception type, never an address or a message.
"""
from __future__ import annotations

import smtplib
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

GMAIL_HOST = "smtp.gmail.com"
GMAIL_PORT = 465


def compose(subject, sender, to, body, html=None, charset=None):
    """A message with the headers in the order every sender has always used (Subject, From, To).
    `to` is the header string (join a list before passing it). With `html`, multipart/alternative
    holding the plain part then the html part; `charset` None keeps MIMEText's own default."""
    if html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain", charset))
        msg.attach(MIMEText(html, "html", charset))
    else:
        msg = MIMEText(body, "plain", charset)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    return msg


def is_retryable(exc):
    """True for a transient failure (dropped connection, timeout, 4xx reply); False for a permanent
    one (bad login, refused recipient or sender, 5xx reply, anything unexpected)."""
    if isinstance(exc, (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError)):
        return True
    if isinstance(exc, smtplib.SMTPResponseException):
        return 400 <= exc.smtp_code < 500
    if isinstance(exc, smtplib.SMTPException):
        return False
    return isinstance(exc, OSError)          # socket timeouts, connection resets


def send_gmail(msg, user, password, timeout=None, envelope_to=None, retries=0, retry_delay=5.0, sleep=time.sleep):
    """Connect to Gmail over SSL, log in, send, close.

    timeout       seconds for the connection (None leaves smtplib's default, as the older senders did)
    envelope_to   list of recipients: send with sendmail(user, envelope_to, msg.as_string());
                  None uses send_message(msg)
    retries       extra attempts after a retryable failure (default 0: one attempt, as before);
                  the wait before attempt n is retry_delay * n
    Raises the last exception when the send fails for good."""
    kwargs = {} if timeout is None else {"timeout": timeout}
    attempt = 0
    while True:
        attempt += 1
        try:
            with smtplib.SMTP_SSL(GMAIL_HOST, GMAIL_PORT, **kwargs) as s:
                s.login(user, password)
                if envelope_to is None:
                    s.send_message(msg)
                else:
                    s.sendmail(user, envelope_to, msg.as_string())
            return
        except Exception as e:  # noqa: BLE001
            if attempt > retries or not is_retryable(e):
                raise
            print(f"SMTP attempt {attempt} of {retries + 1} failed: {type(e).__name__}; retrying", file=sys.stderr)
            sleep(retry_delay * attempt)
