"""
Email the monthly quality report's headline + delta to Tal.

Deterministic (no LLM): reads the newest quality_reports/*.md, lifts
the headline and change-vs-last-month section, sends via Gmail SMTP
(same GMAIL_USER / GMAIL_APP_PASSWORD secrets the alert engine uses).
Skips cleanly when secrets are absent so the report never depends on
mail working. DRY_RUN=1 prints the email instead of sending it (no secrets
needed). When the report lists "New fiscal figures to check" (bills newly
flagged by a fiscal soft check, Oct 14 2026), the email opens with a numbered
TO DO item and a paste-ready Claude Code prompt.

Delivery (Oct 17 2026): with DIGEST_DELIVERY=file and OPS_DIGEST_PENDING set, the
email is not sent; the report is written to <OPS_DIGEST_PENDING>/trackers_quality.
{html,txt,json} in the premium repo for the monthly ops digest. A failed write
falls back to the email. Without DIGEST_DELIVERY=file nothing changes. Sibling of the resolution engine's
scripts/email_quality_summary.py — fix bugs in both.
"""
from __future__ import annotations

import html as html_lib
import os
import re
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

TRACKER = Path(__file__).resolve().parent.parent
REPORT_DIR = Path(os.getenv("QUALITY_REPORT_DIR") or TRACKER / "quality_reports")
NEW_FISCAL = "## New fiscal figures to check"

CHECK_WORDS = {
    "later_column_dwarfs_total": "a later column is at least 3 times the stored figure and at least $10 million",
    "narrative_multi_year_total": "the narrative states an amount totalled over several years",
    "full_impact_column_earlier_than_succeeding": "the Full Fiscal Impact column is an earlier year than a larger succeeding year",
}


def plain(text: str) -> str:
    """The email is plain text: drop the markdown marks the report carries."""
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"^#+ ", "", text, flags=re.M)


def fiscal_todo(section: str) -> str:
    """Numbered TO DO item and paste-ready prompt from the report's
    "New fiscal figures to check" lines ("- <label>: <check>, <check>")."""
    items = []
    for line in section.splitlines():
        m = re.match(r"- (.+?): (\w+(?:, \w+)*)$", line.strip())
        if m:
            items.append((m.group(1), m.group(2).split(", ")))
    if not items:
        return ""
    out = ["TO DO", "",
           (f"1. Check the new fiscal figure on {items[0][0]} before it misleads a reader." if len(items) == 1 else f"1. Check {len(items)} new fiscal figures before they mislead a reader.")]
    for lab, checks in items:
        out.append(f"   {lab}: {'; '.join(CHECK_WORDS.get(c, c) for c in checks)} ({', '.join(checks)})")
    bills = "; ".join(f"{lab} flagged by {', '.join(checks)}" for lab, checks in items)
    out += ["", "PASTE INTO CLAUDE CODE (from ~/nycur):", "-" * 60,
            "Read the fiscal-impacts-tracker skill (sections 'Row links, multi-year plans' and 'Extraction model and "
            "audit overrides'). The monthly quality report flagged these bills in the Fiscal Impacts Tracker as new "
            f"this month: {bills}. For each one, open its fiscal impact statement on Legistar, read the narrative "
            "and the table, and decide whether the stored figure is the annual cost, the first year, or a whole-program "
            "total. If it is wrong, propose an entry for pipeline/fiscal_overrides.json (keyed by matter_id, with the "
            "statement's attachment_id, a set block, a reason, and a figure_note that says in one sentence what the "
            "figure is and where the statement gives it). If it is right, say why the flag does not apply. "
            "Follow the voice rules in CLAUDE.md in every sentence you write. "
            "Show me the diff before committing or pushing anything.",
            "-" * 60, ""]
    return "\n".join(out)


def todo_count(section: str) -> int:
    return sum(1 for line in section.splitlines() if re.match(r"- (.+?): (\w+(?:, \w+)*)$", line.strip()))


def write_section(subject: str, body: str, needs_tal: int) -> bool:
    """DIGEST_DELIVERY=file: write the section for the monthly ops digest.
    False (email mode, no folder, or the write failed) means send the email."""
    if (os.getenv("DIGEST_DELIVERY") or "email").strip().lower() != "file":
        return False
    pending = os.getenv("OPS_DIGEST_PENDING")
    if not pending:
        return False
    sys.path.append(str(Path(__file__).resolve().parents[3] / "seo"))
    try:
        from common import write_digest_section
        page = ("<pre style=\"font-family:ui-monospace,Menlo,monospace;font-size:13px;white-space:pre-wrap\">"
                + html_lib.escape(body) + "</pre>")
        write_digest_section(pending, "trackers_quality", "trackers_quality", subject, page, body, needs_tal)
        print(f"DIGEST_DELIVERY=file: wrote trackers_quality section to {pending}")
        return True
    except Exception as e:  # noqa: BLE001 - any failure means "email instead"
        print(f"Could not write the ops digest section ({e}); emailing instead.")
        return False


def main() -> int:
    user = os.getenv("GMAIL_USER")
    password = os.getenv("GMAIL_APP_PASSWORD")
    dry = os.getenv("DRY_RUN") == "1"
    file_mode = (os.getenv("DIGEST_DELIVERY") or "email").strip().lower() == "file" and bool(os.getenv("OPS_DIGEST_PENDING"))
    if not dry and not file_mode and (not user or not password):
        print("GMAIL_* not set — skipping email (report is committed).")
        return 0

    reports = sorted(REPORT_DIR.glob("quality_report_*.md"), reverse=True)
    if not reports:
        print("No report found.")
        return 0
    report = reports[0]
    body_md = report.read_text()
    head = body_md.split("## validate_obligations.py")[0].strip()
    todo = ""
    n_todo = 0
    if NEW_FISCAL in head:
        head, _, section = head.partition(NEW_FISCAL)
        head = head.strip()
        todo = fiscal_todo(section)
        n_todo = todo_count(section)
    regressions = head.count("REGRESSION")
    hard_dirty = "RUN A QUALITY LOOP" in head
    subject = (
        "Legislation trackers quality report "
        + report.stem.replace("quality_report_", "") + ": "
        + ("VALIDATOR CRASHED" if "VALIDATOR CRASHED" in head
           else "HARD FAILURES" if hard_dirty
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

    body = plain((todo + "\n" if todo else "") + head + link)
    # Action items for the ops digest: each new fiscal figure, plus one for a
    # crashed validator, hard failures or regressions.
    needs_tal = n_todo + (1 if ("VALIDATOR CRASHED" in head or hard_dirty or regressions) else 0)
    if not dry and write_section(subject, body, needs_tal):
        return 0
    if dry:
        print(f"DRY RUN, not sent.\nTo: {to}\nSubject: {subject}\n\n{body}")
        return 0
    if not user or not password:
        print("GMAIL_* not set and the ops digest write failed — nothing sent (report is committed).")
        return 0
    msg = MIMEText(body)
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
