#!/usr/bin/env python3
"""
Sunday week-ahead fallback (sunday_brief_fallback.yml).

The Sunday routine writes planning/briefs/<Sunday>.md in the premium repo. This script emails the
raw mention and opportunity digests when delivery cannot be trusted:

  1. the brief file is missing, or
  2. the brief file contains the marker "EMAIL NOT SENT" (the routine's no-Gmail path writes the file
     but sends nothing), or
  3. no Saturday Gmail sweep report planning/inbox/gmail_sweep_<date>.md exists for the 8 days up to
     the Sunday (the routine archives used drops to planning/inbox/archive/, so both folders count).

    python3 seo/sunday_fallback.py --premium /tmp/premium [--dry-run] [--now 2026-11-08T17:00:00+00:00]

Delivery: seo/common.send_email (the sent body is archived when $SENT_ARCHIVE_DIR is set). No Anthropic API.
"""

import argparse
import html
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import send_email  # noqa: E402

MARKER = "EMAIL NOT SENT"
ROUTINE_URL = "https://claude.ai/code/routines/trig_01F1EJTV9kbR5MJiJQEKKoPw"


def last_sunday(now):
    # a run can start hours late, even after midnight UTC: use the most recent Sunday
    return (now - timedelta(days=(now.weekday() + 1) % 7)).date()


def delivery_problems(premium, sunday):
    """List of reasons the Sunday email cannot be trusted; empty when the brief arrived and the sweep ran."""
    premium = Path(premium)
    problems = []
    brief = premium / "planning" / "briefs" / f"{sunday:%Y-%m-%d}.md"
    if not brief.exists():
        problems.append(f"the brief file {brief.name} was not written")
    elif MARKER in brief.read_text(encoding="utf-8", errors="replace"):
        problems.append(f'the brief file {brief.name} says "{MARKER}", so the routine wrote it without sending the email')
    first = sunday - timedelta(days=8)
    found = []
    for folder in (premium / "planning" / "inbox", premium / "planning" / "inbox" / "archive"):
        for f in folder.glob("gmail_sweep_*.md") if folder.exists() else []:
            m = re.fullmatch(r"gmail_sweep_(\d{4}-\d{2}-\d{2})\.md", f.name)
            if m and first <= datetime.strptime(m.group(1), "%Y-%m-%d").date() <= sunday:
                found.append(f.name)
    if not found:
        problems.append(f"no Saturday Gmail sweep report (planning/inbox/gmail_sweep_<date>.md) exists for {first} to {sunday}")
    return problems


def newest(folder, now):
    # digests are built on Saturday (names YYYY-MM-DD or YYYY-MM-DD-2); take the newest from the last 2 days
    cutoff = (now - timedelta(days=2)).strftime("%Y-%m-%d")
    stems = sorted({p.stem for p in folder.glob("*.html") if p.stem[:10] >= cutoff})
    return folder / stems[-1] if stems else folder / "missing"


def compose(premium, now, problems):
    premium = Path(premium)
    digests = [("Mention digest", newest(premium / "mention_monitor_state" / "digests", now)),
               ("Opportunity digest", newest(premium / "opportunities" / "state" / "digests", now))]
    intro = ("The Sunday week-ahead email may not have arrived: " + "; ".join(problems) + f". Check the routine at "
             f"{ROUTINE_URL} and run the /ci-triage skill if an Action failed. The raw digests follow.")
    text, page, missing = [intro, ""], [f"<p>{html.escape(intro)}</p>"], []
    for label, base in digests:
        h, t = base.with_suffix(".html"), base.with_suffix(".txt")
        if h.exists():
            page.append(f"<hr><h2>{label}</h2>" + h.read_text(encoding="utf-8"))
            text += ["=" * 60, label.upper(), "=" * 60, t.read_text(encoding="utf-8") if t.exists() else "(HTML only)", ""]
        else:
            missing.append(label)
    if missing:
        note = "Missing (none built in the last 2 days): " + ", ".join(missing) + "."
        text.insert(2, note)
        page.insert(1, f"<p><strong>{html.escape(note)}</strong></p>")
    return "\n".join(text), "\n".join(page)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--premium", required=True)
    ap.add_argument("--dry-run", action="store_true", help="print the decision and the email; send nothing")
    ap.add_argument("--now", help="ISO time override (testing)")
    a = ap.parse_args()
    now = datetime.fromisoformat(a.now) if a.now else datetime.now(timezone.utc)
    sunday = last_sunday(now)
    problems = delivery_problems(a.premium, sunday)
    if not problems:
        print(f"The Sunday brief for {sunday} arrived and the Saturday Gmail sweep report exists. Nothing to do.")
        return 0
    # A missing sweep report alone must not trigger this fallback: the brief was delivered and reports the
    # missing sweep itself (brief_rules.md rule 8e), so sending the raw digests too would be a second Sunday email.
    if all("Gmail sweep" in p for p in problems):
        print("The Sunday brief arrived. Warning only, no email sent: " + "; ".join(problems))
        return 0
    print("Delivery problems: " + "; ".join(problems))
    text, page = compose(a.premium, now, problems)
    subject = "Sunday week-ahead email may not have arrived, raw digests below"
    if a.dry_run:
        print(f"DRY RUN, nothing sent.\nSubject: {subject}\n\n{text[:1500]}")
        return 0
    ok = send_email(subject, text, html=page, archive_slug="sunday_fallback", role="Tal (Sunday fallback)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
