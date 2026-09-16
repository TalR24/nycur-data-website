#!/usr/bin/env python3
"""Alert when the mention monitor stops producing state.

A broken Gmail app password, an expired Cloudflare token, a disabled
schedule, or a failing run all look identical from the outside: no email
arrives, which is also what a quiet week looks like. This checks the last
commit that touched the private state folder and emails if it is stale.

Run from the Site Health workflow:
    python3 mention_monitor/check_freshness.py --max-age-days 3
Needs PREMIUM_PUSH_TOKEN (repo read), GMAIL_USER, GMAIL_APP_PASSWORD.
"""
import argparse
import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

import requests

REPO = "TalR24/nycur-data-premium"
PATH = "mention_monitor_state"
API = f"https://api.github.com/repos/{REPO}/commits"


def last_state_commit(token):
    r = requests.get(API, params={"path": PATH, "per_page": 1},
                     headers={"Authorization": f"token {token}",
                              "Accept": "application/vnd.github+json"},
                     timeout=30)
    r.raise_for_status()
    commits = r.json()
    if not commits:
        return None, None
    commit = commits[0]
    when = commit["commit"]["committer"]["date"]
    return datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc), commit["sha"][:7]


def email(subject, body):
    user, password = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    if not (user and password):
        print("WARNING: Gmail env vars missing; not emailing.", file=sys.stderr)
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = os.environ.get("MENTION_DIGEST_TO") or user
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(user, password)
        s.send_message(msg)
    print(f"Emailed staleness alert to {msg['To']}.", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-days", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("PREMIUM_PUSH_TOKEN")
    if not token:
        print("PREMIUM_PUSH_TOKEN missing; cannot check state freshness.", file=sys.stderr)
        return 0

    when, sha = last_state_commit(token)
    now = datetime.now(timezone.utc)
    if when is None:
        age_text = "no state commit exists at all"
        stale = True
    else:
        age = now - when
        age_text = (f"last state commit {sha} was {age.days} day(s) and "
                    f"{age.seconds // 3600} hour(s) ago ({when:%Y-%m-%d %H:%M UTC})")
        stale = age > timedelta(days=args.max_age_days)

    print(f"Mention monitor state: {age_text}.")
    if not stale:
        return 0
    body = (f"The mention monitor has not written state in over "
            f"{args.max_age_days} days: {age_text}.\n\n"
            f"The daily run commits to {REPO}/{PATH}, so silence here means the "
            f"run is failing, the schedule is disabled, or a credential expired "
            f"(the Gmail app password and the Cloudflare token have each expired "
            f"before).\n\n"
            f"Check: https://github.com/TalR24/nycur-data-website/actions/workflows/"
            f"mention_monitor.yml\n")
    if args.dry_run:
        print(body)
    else:
        email("Mention monitor has gone quiet", body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
