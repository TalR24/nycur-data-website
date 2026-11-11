"""Helpers shared by the member alert engines (NYC Council send_alerts.py, CB send_cb_alerts.py).

Subscriber CSV reading, field splitting, premium-repo paths, JSON state, DRY_RUN and the
send-or-print step live here, so a fix is made once. What each engine matches and says stays
in the engine. Logging is count-only: a failed send prints the subscriber's position and the
exception type, never an address.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

import mailer


def is_dry():
    return os.environ.get("DRY_RUN") == "1"


def premium_paths(rel_dir, subs_name, state_name):
    """(subscriptions csv, state json) inside the premium checkout named by $PREMIUM_DIR."""
    premium = os.environ.get("PREMIUM_DIR")
    if not premium:
        sys.exit("PREMIUM_DIR not set")
    pdata = Path(premium).joinpath(*rel_dir)
    return pdata / subs_name, pdata / state_name


def read_subscribers(subs_path, label):
    """Rows of the subscriptions csv that have an email; prints the count line."""
    if not subs_path.exists():
        print(f"No {label}; skipping sends.")
        subscribers = []
    else:
        with open(subs_path, newline="", encoding="utf-8") as f:
            subscribers = [r for r in csv.DictReader(f)
                           if (r.get("email") or "").strip()]
    print(f"{len(subscribers)} subscribers.")
    return subscribers


def splitfield(sub, name):
    """The ;-separated cells of one subscription field, as a set."""
    return {x.strip() for x in (sub.get(name) or "").split(";") if x.strip()}


def read_state(state_path, default=None):
    return json.loads(state_path.read_text()) if state_path.exists() else default


def write_state(state_path, state, mkdir=False):
    if mkdir:
        state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=1))


def deliver(email, subject, body, sub_no, total, n_matches, dry):
    """Print (dry) or send one subscriber's digest. Returns True when it counts as sent, False when
    the send failed (the caller skips that subscriber and still writes state)."""
    if dry:
        print(f"\n=== DRY RUN to subscriber {sub_no}: {subject}\n{body}\n")
        return True
    user = os.environ["GMAIL_USER"]
    msg = mailer.compose(subject, user, email, body)
    # Never let an address reach the log: on failure print only the
    # error type, keep going, and still write state below.
    try:
        mailer.send_gmail(msg, user, os.environ["GMAIL_APP_PASSWORD"])
    except Exception as e:  # noqa: BLE001
        print(f"Send failed for subscriber {sub_no}/{total}: {type(e).__name__}")
        return False
    print(f"Sent alert {sub_no}/{total}: {n_matches} matches")
    return True
