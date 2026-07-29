#!/usr/bin/env python3
"""
Detect new entries in connect.json vs. a previous snapshot and email them.

Usage: python3 notify_new_connect.py <prev_connect.json> <new_connect.json>

Reads GMAIL_USER and GMAIL_APP_PASSWORD from environment.
Sends to entries whose `contact` field looks like an email address.
"""
import json, os, re, smtplib, ssl, sys

EMAIL_RE = re.compile(r"[\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,}")

prev_path = sys.argv[1] if len(sys.argv) > 1 else None
curr_path = sys.argv[2] if len(sys.argv) > 2 else None

if not prev_path or not curr_path:
    print("Usage: notify_new_connect.py <prev.json> <curr.json>")
    sys.exit(1)

prev = json.loads(open(prev_path).read())
curr = json.loads(open(curr_path).read())

prev_names = {e["name"] for e in prev}
new_entries = [e for e in curr if e["name"] not in prev_names]

to_notify = []
for e in new_entries:
    m = EMAIL_RE.search(e.get("contact", ""))
    if m:
        to_notify.append((e, m.group(0)))

if not to_notify:
    print(f"New entries: {len(new_entries)}. None had an email contact — nothing to send.")
    sys.exit(0)

gmail_user = os.environ["GMAIL_USER"]
gmail_pass = os.environ["GMAIL_APP_PASSWORD"]

context = ssl.create_default_context()
sent = 0
with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as smtp:
    smtp.login(gmail_user, gmail_pass)
    for entry, email in to_notify:
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["From"] = f"State Capacity Ecosystem Hub <{gmail_user}>"
        msg["To"] = email
        msg["Subject"] = "You are now live on our Connect"
        msg.set_content(
            "This is Henry and Tal from the State Capacity Ecosystem Hub. "
            "Just a heads up that your submission to Connect is live!"
        )
        smtp.send_message(msg)
        print(f"  Emailed {entry['name']} → {email}")
        sent += 1

print(f"Done. {sent} notification(s) sent.")
