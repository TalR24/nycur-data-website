#!/usr/bin/env python3
"""
Send CB member-tracker alert emails when leadership or rosters change.

Adapted from civic_reference/nyc_council_legislation_trackers/pipeline/
send_alerts.py (same env contract, premium-repo state pattern, and Gmail
sender). Runs in the monthly refresh Action AFTER build_tracker_data.py, and
last in the workflow so a Gmail failure cannot block the data commit.

Diffs the fresh data/boards.json against the previous snapshot kept in the
PRIVATE premium repo and emails each subscriber a digest of events on the
boards/boroughs they watch:
  chair            board chair changed
  dm               district manager changed
  committee_chair  a committee's chair changed (or a named-chair committee
                   appeared/disappeared)
  members          members added to / no longer on the published roster

Inputs (public repo):    cb-tools/member-tracker/data/boards.json + members.json
Inputs (premium checkout, path via PREMIUM_DIR):
  cb-tools/member-tracker/data/cb_alert_subscriptions.csv
      columns: email,
               boards    (semicolon-separated cd codes, e.g. "103;301"),
               boroughs  (semicolon-separated: Manhattan;Bronx;Brooklyn;
                          Queens;Staten Island),
               events    (semicolon-separated from the list above; blank = all),
               added     (date, informational)
      A row with blank boards AND blank boroughs watches the whole city.
  cb-tools/member-tracker/data/cb_alerts_state.json
      previous snapshot; seeded on first run (no emails sent that run)

Env:
  PREMIUM_DIR   path to the premium repo checkout (required)
  GMAIL_USER / GMAIL_APP_PASSWORD  (required unless DRY_RUN)
  DRY_RUN=1     print what would be sent, send nothing, do not update state

The caller commits the updated cb_alerts_state.json in the premium checkout.

Usage:
    PREMIUM_DIR=/tmp/premium python3 pipeline/send_cb_alerts.py
"""
from __future__ import annotations

import csv
import json
import os
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"

TRACKER_URL = "https://data.nycuriosity.com/cb-tools/member-tracker/"
ALERTS_URL = "https://premium.nycuriosity.com/cb-tools/member-tracker/alerts/"

EVENT_TYPES = ("chair", "dm", "committee_chair", "members")


def load_premium_paths() -> tuple[Path, Path]:
    premium = os.environ.get("PREMIUM_DIR")
    if not premium:
        sys.exit("PREMIUM_DIR not set")
    pdata = Path(premium) / "cb-tools" / "member-tracker" / "data"
    return pdata / "cb_alert_subscriptions.csv", pdata / "cb_alerts_state.json"


def snapshot(boards_doc: dict, members_doc: dict) -> dict:
    """The compact per-board state we diff between runs."""
    members_by_cd: dict[str, list] = {}
    for m in members_doc["members"]:
        members_by_cd.setdefault(str(m["cd"]), []).append(m["name"])
    snap = {}
    for b in boards_doc["boards"]:
        cd = str(b["cd"])
        snap[cd] = {
            "chair": (b["chair"] or {}).get("name"),
            "dm": b.get("district_manager"),
            "committee_chairs": {
                c["name"]: c["chair"] for c in b.get("committees", []) if c.get("chair")
            },
            "members": sorted(members_by_cd.get(cd, [])),
        }
    return snap


def diff_events(prev: dict, cur: dict, board_names: dict[str, str]) -> list[dict]:
    events = []
    for cd, now in cur.items():
        was = prev.get(cd)
        if not was:
            continue  # newly covered board: skip, everything would be "new"
        bname = board_names.get(cd, f"CD {cd}")
        if was["chair"] != now["chair"] and now["chair"]:
            events.append(
                {"cd": cd, "type": "chair",
                 "text": f"{bname}: chair is now {now['chair']}"
                         + (f" (was {was['chair']})" if was["chair"] else "")}
            )
        if was["dm"] != now["dm"] and now["dm"]:
            events.append(
                {"cd": cd, "type": "dm",
                 "text": f"{bname}: district manager is now {now['dm']}"
                         + (f" (was {was['dm']})" if was["dm"] else "")}
            )
        for cname, chair in now["committee_chairs"].items():
            old = was["committee_chairs"].get(cname)
            if old != chair:
                events.append(
                    {"cd": cd, "type": "committee_chair",
                     "text": f"{bname}: {cname} committee chair is now {chair}"
                             + (f" (was {old})" if old else "")}
                )
        added = sorted(set(now["members"]) - set(was["members"]))
        removed = sorted(set(was["members"]) - set(now["members"]))
        if added:
            events.append(
                {"cd": cd, "type": "members",
                 "text": f"{bname}: {len(added)} member"
                         f"{'s' if len(added) != 1 else ''} added to the "
                         f"published roster: {', '.join(added[:10])}"
                         + ("…" if len(added) > 10 else "")}
            )
        if removed:
            events.append(
                {"cd": cd, "type": "members",
                 "text": f"{bname}: {len(removed)} member"
                         f"{'s' if len(removed) != 1 else ''} no longer on the "
                         f"published roster: {', '.join(removed[:10])}"
                         + ("…" if len(removed) > 10 else "")}
            )
    return events


def main() -> None:
    dry = os.environ.get("DRY_RUN") == "1"
    subs_path, state_path = load_premium_paths()

    boards_doc = json.loads((DATA / "boards.json").read_text())
    members_doc = json.loads((DATA / "members.json").read_text())
    board_names = {str(b["cd"]): b["name"] for b in boards_doc["boards"]}
    boroughs = {str(b["cd"]): b["borough"] for b in boards_doc["boards"]}

    cur = snapshot(boards_doc, members_doc)

    if not state_path.exists():
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({"snapshot": cur}, indent=1))
        print("No previous state; snapshot seeded, no alerts sent.")
        return

    prev = json.loads(state_path.read_text()).get("snapshot", {})
    events = diff_events(prev, cur, board_names)
    if not events:
        print("No leadership or roster changes; no alerts to send.")
        if not dry:
            state_path.write_text(json.dumps({"snapshot": cur}, indent=1))
        return
    print(f"{len(events)} change events detected.")

    if not subs_path.exists():
        print("No cb_alert_subscriptions.csv; skipping sends.")
        subscribers = []
    else:
        with open(subs_path, newline="", encoding="utf-8") as f:
            subscribers = [r for r in csv.DictReader(f)
                           if (r.get("email") or "").strip()]
    print(f"{len(subscribers)} subscribers.")

    sent = 0
    for sub in subscribers:
        email = sub["email"].strip()

        def splitfield(name):
            return {x.strip() for x in (sub.get(name) or "").split(";") if x.strip()}

        want_boards = splitfield("boards")
        want_boroughs = splitfield("boroughs")
        want_events = {e.lower() for e in splitfield("events")} or set(EVENT_TYPES)

        matches = [
            e for e in events
            if e["type"] in want_events
            and (
                (not want_boards and not want_boroughs)
                or e["cd"] in want_boards
                or boroughs.get(e["cd"]) in want_boroughs
            )
        ]
        if not matches:
            continue

        n = len(matches)
        lines = [
            f"{n} change{'s' if n != 1 else ''} on the community boards you watch:",
            "",
        ]
        for e in matches:
            lines.append(f"- {e['text']}")
            lines.append(f"  Board page: {TRACKER_URL}board/?cd={e['cd']}")
            lines.append("")
        lines += [
            "--",
            "You receive these alerts as an NYCuriosity member.",
            f"Update your preferences: {ALERTS_URL}",
            "To stop receiving alerts, reply to this email.",
        ]
        body = "\n".join(lines)
        subject = (f"NYCuriosity alert: {n} community board change"
                   f"{'s' if n != 1 else ''} on your watchlist")

        if dry:
            print(f"\n=== DRY RUN to {email}: {subject}\n{body}\n")
        else:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = os.environ["GMAIL_USER"]
            msg["To"] = email
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
                s.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"])
                s.send_message(msg)
            print(f"Sent to {email}: {n} matches")
        sent += 1

    if not dry:
        state_path.write_text(json.dumps({"snapshot": cur}, indent=1))
        print(f"State updated. {sent} emails sent.")


if __name__ == "__main__":
    main()
