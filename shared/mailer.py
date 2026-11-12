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


def _plain_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        return ""
    return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")


def archive_copy(msg, dest=None, role=None, when=None):
    """File the plain-text body of a sent message as <dest>/<YYYY-MM-DD>_<subject slug>.md (subject, date,
    recipient role, body; never an address). dest defaults to $SENT_ARCHIVE_DIR and role to $SENT_ARCHIVE_ROLE
    or "Tal"; with no folder nothing is written. The workflow commits the folder (premium planning/sent/).
    Added Nov 11 2026 so every email Tal gets is on file for the Sunday and monthly digests."""
    import os
    import re
    from datetime import datetime, timezone
    from pathlib import Path
    dest = dest or os.environ.get("SENT_ARCHIVE_DIR")
    if not dest:
        return None
    when = when or datetime.now(timezone.utc)
    subject = str(msg.get("Subject") or "no subject")
    slug = re.sub(r"[^a-z0-9]+", "_", subject.lower()).strip("_")[:60] or "email"
    folder = Path(dest)
    folder.mkdir(parents=True, exist_ok=True)
    path, n = folder / f"{when:%Y-%m-%d}_{slug}.md", 2
    while path.exists():
        path, n = folder / f"{when:%Y-%m-%d}_{slug}-{n}.md", n + 1
    role = role or os.environ.get("SENT_ARCHIVE_ROLE") or "Tal"
    path.write_text(f"Subject: {subject}\nDate: {when:%Y-%m-%d %H:%M} UTC\nRecipient role: {role}\n\n"
                    f"{_plain_body(msg).rstrip()}\n", encoding="utf-8")
    return path


def send_gmail(msg, user, password, timeout=None, envelope_to=None, retries=0, retry_delay=5.0, sleep=time.sleep, archive=True):
    """Connect to Gmail over SSL, log in, send, close.

    timeout       seconds for the connection (None leaves smtplib's default, as the older senders did)
    envelope_to   list of recipients: send with sendmail(user, envelope_to, msg.as_string());
                  None uses send_message(msg)
    retries       extra attempts after a retryable failure (default 0: one attempt, as before);
                  the wait before attempt n is retry_delay * n
    archive       after a successful send, file a copy when $SENT_ARCHIVE_DIR is set (archive_copy); False
                  for a caller that files its own copy
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
            if archive:
                try:
                    archive_copy(msg)
                except OSError as e:  # an archive failure never fails a send
                    print(f"sent-mail archive not written: {type(e).__name__}", file=sys.stderr)
            return
        except Exception as e:  # noqa: BLE001
            if attempt > retries or not is_retryable(e):
                raise
            print(f"SMTP attempt {attempt} of {retries + 1} failed: {type(e).__name__}; retrying", file=sys.stderr)
            sleep(retry_delay * attempt)
