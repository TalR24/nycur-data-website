"""
Email the monthly quality report's headline + delta to Tal.

Deterministic (no LLM): reads the newest quality_reports/*.md, lifts
the headline and change-vs-last-month section, sends via Gmail SMTP
(same GMAIL_USER / GMAIL_APP_PASSWORD secrets the alert engine uses).
Skips cleanly when secrets are absent so the report never depends on
mail working. Sibling of the resolution engine's
scripts/email_quality_summary.py — fix bugs in both.
"""
from __future__ import annotations

import os
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

TRACKER = Path(__file__).resolve().parent.parent
REPORT_DIR = TRACKER / "quality_reports"


def main() -> int:
    user = os.getenv("GMAIL_USER")
    password = os.getenv("GMAIL_APP_PASSWORD")
    if not user or not password:
        print("GMAIL_* not set — skipping email (report is committed).")
        return 0

    reports = sorted(REPORT_DIR.glob("quality_report_*.md"), reverse=True)
    if not reports:
        print("No report found.")
        return 0
    report = reports[0]
    body_md = report.read_text()
    head = body_md.split("## validate_obligations.py")[0].strip()
    regressions = head.count("REGRESSION")
    hard_dirty = "RUN A QUALITY LOOP" in head
    subject = (
        "Legislation trackers quality report "
        + report.stem.replace("quality_report_", "") + ": "
        + ("HARD FAILURES" if hard_dirty
           else f"{regressions} regression(s)" if regressions
           else "quiet month")
    )
    repo = os.getenv("GITHUB_REPOSITORY", "")
    link = (
        f"\n\nFull report: https://github.com/{repo}/blob/main/"
        f"civic_reference/legislation_implementation_tracker/"
        f"quality_reports/{report.name}" if repo else ""
    )
    to = os.getenv("QUALITY_EMAIL_TO", "troded24@gmail.com")

    msg = MIMEText(head + link)
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(user, password)
        smtp.sendmail(user, [to], msg.as_string())
    print(f"Sent: {subject} → {to}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
