#!/usr/bin/env python3
"""Per-bill NYS alerts for members, near real time. No model calls.

Reads the Open Legislation change feed since the cursor (data/updates_state.json), keeps the bills a member follows,
fetches each changed bill (view=no_fulltext), turns every new action into one plain line ("Passed the Senate, 61-0
(Oct 7)", "Moved to the Codes committee"), and sends ONE email per member per run through Gmail.

Private inputs live in a checkout of the premium repo (PREMIUM_DIR); emails are PII and never reach the public repo,
a log line or a commit message. Output only ever names members by their position ("member 2").
  civic_reference/nys_legislation_trackers/data/nys_bill_follows.csv      email,session,bill,added
  civic_reference/nys_legislation_trackers/data/nys_bill_alerts_state.json  {"sent": ["<hash>|<event id>", ...]}
The state holds salted-free SHA-256 prefixes of the address plus the event id, so it repeats nothing and names no one.

Env: PREMIUM_DIR, GMAIL_USER, GMAIL_APP_PASSWORD; DRY_RUN=1 prints the emails, sends nothing and writes nothing.
Flags: --days N reads the last N days instead of the cursor (always a dry run unless --live);
       --follows-file PATH reads a follow list from PATH instead of the premium checkout (tests, dry runs).
The cursor advances only after every changed followed bill was fetched and every email sent.
Exit 1 on any failure; sends that did succeed stay recorded in the state, so a retry repeats nothing."""
import argparse, csv, datetime as dt, hashlib, json, os, re, smtplib, sys
from collections import defaultdict
from email.mime.text import MIMEText

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import openleg  # noqa: E402
import poll_updates  # noqa: E402

DATA = poll_updates.DATA
FMT = poll_updates.FMT
PREMIUM_REL = os.path.join("civic_reference", "nys_legislation_trackers", "data")
FOLLOWS_NAME = "nys_bill_follows.csv"
STATE_NAME = "nys_bill_alerts_state.json"
MANAGE_URL = "https://premium.nycuriosity.com/civic_reference/nys_legislation_trackers/following/"
LAG_DAYS = 1          # actions dated up to a day before the window start still count (the feed can lag the action date)
KEEP_DAYS = 90        # sent-event ids older than this are dropped from the state
SMALL = {"and", "of", "the", "on", "for", "in", "to"}


def committee_name(s):
    words = s.strip().lower().split()
    return " ".join(w if (w in SMALL and i) else w.capitalize() for i, w in enumerate(words))


def short_date(iso):
    d = dt.date.fromisoformat(iso)
    return d.strftime("%b ") + str(d.day)


def floor_vote(bill, action):
    """'61-0' for the floor vote on the action's date and chamber, else None."""
    chamber = (action.get("chamber") or "").upper()
    matches = []
    for v in ((bill.get("votes") or {}).get("items") or []):
        if v.get("voteType") != "FLOOR" or v.get("voteDate") != action["date"]:
            continue
        mv = ((v.get("memberVotes") or {}).get("items")) or {}
        chambers = {m.get("chamber") for blk in mv.values() for m in (blk.get("items") or [])}
        if chamber and chambers and chamber not in chambers:
            continue
        ayes = sum(len((mv.get(k) or {}).get("items") or []) for k in ("AYE", "AYEWR"))
        nays = len((mv.get("NAY") or {}).get("items") or [])
        matches.append((ayes, nays))
    return "%d-%d" % matches[-1] if matches else None


def describe(bill, a, ver_hint=""):
    """One plain line for one action, or None for a bookkeeping action that carries no news."""
    t = (a.get("text") or "").strip()
    u = t.upper()
    date = a["date"]
    ver = (a.get("billId") or {}).get("version") or ver_hint
    m = re.match(r"SIGNED CHAP\.?\s*(\d+)", u)
    if m:
        return "Signed: chapter %s of %s" % (m.group(1), date[:4])
    m = re.match(r"VETOED MEMO\.?\s*(\d+)", u)
    if m:
        return "Vetoed (veto message %s, %s)" % (m.group(1), short_date(date))
    if u.startswith("VETOED"):
        return "Vetoed (%s)" % short_date(date)
    if u.startswith("DELIVERED TO GOVERNOR"):
        return "Delivered to the governor"
    m = re.match(r"PASSED (SENATE|ASSEMBLY)", u)
    if m:
        house = m.group(1).capitalize()
        vote = floor_vote(bill, a)
        return "Passed the %s, %s (%s)" % (house, vote, short_date(date)) if vote else "Passed the %s (%s)" % (house, short_date(date))
    m = re.match(r"DELIVERED TO (SENATE|ASSEMBLY)", u)
    if m:
        return "Delivered to the %s" % m.group(1).capitalize()
    m = re.match(r"AMEND(?: \(T\))? AND RECOMMIT TO (.+)", u)
    if m:
        v = " (version %s)" % ver if ver else ""
        return "Amended%s and sent back to the %s committee" % (v, committee_name(m.group(1)))
    if u.startswith("PRINT NUMBER"):
        return "Amended: version %s" % ver if ver else None
    m = re.match(r"REFERRED TO (.+)", u)
    if m:
        return "Moved to the %s committee" % committee_name(m.group(1))
    m = re.match(r"REPORTED AND COMMITTED TO (.+)", u)
    if m:
        return "Reported out of committee and sent to the %s committee" % committee_name(m.group(1))
    m = re.match(r"COMMITTEE DISCHARGED AND COMMITTED TO (.+)", u)
    if m:
        return "Discharged from committee and sent to the %s committee" % committee_name(m.group(1))
    m = re.match(r"HELD FOR CONSIDERATION IN (.+)", u)
    if m:
        return "Held for consideration in the %s committee" % committee_name(m.group(1))
    if u.startswith("REPORTED"):
        return "Reported out of committee"
    m = re.match(r"(1ST|2ND) REPORT CAL\.?\s*(\d*)", u)
    if m:
        return "Placed on the floor calendar (%s report%s)" % ("first" if m.group(1) == "1ST" else "second", ", calendar no. " + m.group(2) if m.group(2) else "")
    if u.startswith("3RD READING CAL"):
        return "On the third reading calendar"
    m = re.match(r"(DIED IN|RETURNED TO) (SENATE|ASSEMBLY)", u)
    if m:
        return ("Died in the %s" if m.group(1) == "DIED IN" else "Returned to the %s") % m.group(2).capitalize()
    if re.match(r"(ADVANCED|ORDERED) TO THIRD READING", u):
        return "Advanced to third reading"
    m = re.match(r"SUBSTITUTED BY (\S+)", u)
    if m:
        return "Replaced by %s, the other house's version" % m.group(1)
    if u.startswith("STRICKEN"):
        return "Stricken"
    if u.startswith("ADOPTED"):
        return "Adopted (%s)" % short_date(date)
    return t[:1].upper() + t[1:].lower() if t else None


def bill_events(bill, since_date):
    """[(event_id, date, line)] for the bill's actions dated on or after since_date, newest last."""
    key = "%s-%s" % (bill["session"], bill["basePrintNo"])
    acts = [a for a in ((bill.get("actions") or {}).get("items") or []) if a.get("date") and a["date"] >= since_date]
    acts.sort(key=lambda a: (a["date"], a.get("sequenceNo") or 0))
    # an AMEND action carries the old version; the PRINT NUMBER action filed the same day carries the new one
    amend_dates = {a["date"] for a in acts if re.match(r"AMEND", (a.get("text") or "").upper())}
    new_ver = {a["date"]: (a.get("billId") or {}).get("version") or "" for a in acts if (a.get("text") or "").upper().startswith("PRINT NUMBER")}
    out = []
    for a in acts:
        if (a.get("text") or "").upper().startswith("PRINT NUMBER") and a["date"] in amend_dates:
            continue          # the AMEND action already says it
        line = describe(bill, a, new_ver.get(a["date"], ""))
        if line:
            out.append(("%s|%s|%s" % (key, a["date"], a.get("sequenceNo")), a["date"], line))
    return out


def hid(email):
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]


def load_follows(path):
    """{'2025-S11': [(email, added), ...]} from the follows CSV."""
    out = defaultdict(list)
    if not os.path.exists(path):
        return out
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                out["%d-%s" % (int(r["session"]), r["bill"].strip().upper())].append((r["email"].strip(), (r.get("added") or "")[:10]))
            except (KeyError, ValueError, AttributeError):
                continue
    return out


def window_bills(start, now):
    items, t = [], start
    while t < now:
        e = min(t + dt.timedelta(days=1), now)
        items += poll_updates.fetch_window(t, e)
        t = e
    bills, _ = poll_updates.summarize(items)
    return bills


def compose(items):
    """items: [(bill dict, [(date, line)])] -> (subject, body)."""
    n = sum(len(ev) for _, ev in items)
    subject = "NYCuriosity alert: %d update%s on %d NYS bill%s you follow" % (n, "" if n == 1 else "s", len(items), "" if len(items) == 1 else "s")
    lines = []
    for b, ev in sorted(items, key=lambda x: (x[0]["session"], x[0]["basePrintNo"])):
        sess = int(b["session"])
        lines.append("%s (%d-%d): %s" % (b["basePrintNo"], sess, sess + 1, (b.get("title") or "").strip()))
        for _, line in ev:
            lines.append("  - " + line)
        lines.append("  https://www.nysenate.gov/legislation/bills/%d/%s" % (sess, b["basePrintNo"]))
        lines.append("")
    lines += ["--", "You receive these alerts as an NYCuriosity member, for the NYS bills you follow.",
              "To stop following a bill, visit %s or reply to this email." % MANAGE_URL]
    return subject, "\n".join(lines)


def send(msg_to, subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = os.environ["GMAIL_USER"]
    msg["To"] = msg_to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"])
        s.send_message(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int)
    ap.add_argument("--live", action="store_true", help="with --days: really send")
    ap.add_argument("--follows-file")
    a = ap.parse_args()
    dry = os.environ.get("DRY_RUN") == "1" or (a.days is not None and not a.live)
    pdir = os.environ.get("PREMIUM_DIR")
    if a.follows_file:
        follows_path = a.follows_file
        state_path = None
    elif pdir:
        follows_path = os.path.join(pdir, PREMIUM_REL, FOLLOWS_NAME)
        state_path = os.path.join(pdir, PREMIUM_REL, STATE_NAME)
    else:
        sys.exit("PREMIUM_DIR not set (or pass --follows-file for a dry run)")
    if not dry and not state_path:
        sys.exit("a live run needs PREMIUM_DIR for the sent-event state")
    if not dry and not (os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD")):
        sys.exit("GMAIL_USER and GMAIL_APP_PASSWORD are required for a live run")

    now = dt.datetime.now().replace(microsecond=0)         # the machine and the feed both run on Eastern time
    if a.days:
        start = now - dt.timedelta(days=a.days)
    elif os.path.exists(poll_updates.STATE):
        start = dt.datetime.strptime(json.load(open(poll_updates.STATE))["cursor"], FMT)
    else:
        start = now - dt.timedelta(days=1)
    since_date = (start - dt.timedelta(days=LAG_DAYS)).date().isoformat()

    follows = load_follows(follows_path)
    state = {"sent": []}
    if state_path and os.path.exists(state_path):
        state = json.load(open(state_path))
    sent = set(state.get("sent", []))

    changed = window_bills(start, now)
    mine = [b for b in changed if b["bill"] in follows]
    print("window %s -> %s: %d changed bills, %d followed by at least one member" % (start, now, len(changed), len(mine)))

    per_member = defaultdict(list)       # email -> [(bill, [(event_id, line)])]
    fetch_failed = 0
    for b in mine:
        try:
            d = openleg.get("/api/3/bills/%d/%s" % (b["session"], b["base_print_no"]), {"view": "no_fulltext"})
        except RuntimeError as e:
            fetch_failed += 1
            print("fetch failed for %s: %s" % (b["bill"], str(e)[:80]))
            continue
        if not d:
            continue
        bill = d["result"]
        events = bill_events(bill, since_date)
        for email, added in follows[b["bill"]]:
            mine_ev = [(eid, date, line) for eid, date, line in events
                       if (not added or date >= added) and "%s|%s" % (hid(email), eid) not in sent]
            if mine_ev:
                per_member[email].append((bill, mine_ev))

    failures = fetch_failed
    new_sent = set()
    for n, (email, items) in enumerate(sorted(per_member.items(), key=lambda kv: hid(kv[0])), 1):
        subject, body = compose([(b, [(e[1], e[2]) for e in ev]) for b, ev in items])
        if dry:
            print("\n=== DRY RUN, email to member %d of %d: %s\n%s\n" % (n, len(per_member), subject, body))
            continue
        try:
            send(email, subject, body)
        except Exception as e:  # noqa: BLE001  never let an address reach the log
            failures += 1
            print("send failed for member %d of %d: %s" % (n, len(per_member), type(e).__name__))
            continue
        for _, ev in items:
            new_sent.update("%s|%s" % (hid(email), eid) for eid, _, _ in ev)
        print("sent email %d of %d: %d updates" % (n, len(per_member), sum(len(ev) for _, ev in items)))

    if dry:
        print("dry run: %d members would get email, nothing sent, no state written" % len(per_member))
        return
    cutoff = (now - dt.timedelta(days=KEEP_DAYS)).date().isoformat()
    keep = {s for s in sent | new_sent if s.split("|")[2] >= cutoff}
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    json.dump({"sent": sorted(keep)}, open(state_path, "w"), indent=0)       # successes are recorded even when others failed
    if failures:
        print("%d failure(s): cursor not advanced; sent events are recorded so a retry repeats nothing" % failures)
        sys.exit(1)
    json.dump({"cursor": now.strftime(FMT), "last_run_updates": len(changed), "last_run_bills": len(changed)},
              open(poll_updates.STATE, "w"), indent=1)
    print("cursor advanced to %s; %d emails sent" % (now.strftime(FMT), len(per_member)))


if __name__ == "__main__":
    main()
