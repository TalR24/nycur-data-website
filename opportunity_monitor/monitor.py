"""Opportunities radar: Saturday digest of Tal's private opportunities watch
list (nycur-data-premium/opportunities/watchlist.yaml).

Re-checks each item's official page for date and deadline changes, scores
the remaining items per profile.md, and builds an HTML + plain-text digest
email. Sibling of data_website/mention_monitor; reuses its premium-repo
state checkout and Gmail SMTP conventions.

Run with:
  python3 opportunity_monitor/monitor.py --watchlist PATH --state-dir PATH \
      [--today YYYY-MM-DD] [--no-fetch] [--email] [--out PATH]

Tests:
  python -m unittest discover -s opportunity_monitor -p "test_monitor.py" -v
"""

import argparse
import hashlib
import html as html_mod
import json
import os
import re
import smtplib
import sys
import time
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
import yaml

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128 Safari/537.36")

# Lines worth keeping from a fetched page: anything that reads like a date
# or deadline mention. \d{4} instead of a literal year so this keeps working
# past 2027 with no edit.
DATE_KEY = re.compile(
    r"(deadline|due|apply|applications?|call for|proposals?|submit|submission|"
    r"open|closes?|nominat|\d{4}|"
    r"January|February|March|April|May|June|July|August|September|October|"
    r"November|December)",
    re.I,
)

STATUS_EXCLUDE = {"skip", "done", "won", "declined"}
PURSUING_STATUSES = {"pursue", "drafting", "submitted"}

FORMAT_LABELS = {
    "remote": "remote",
    "part_time": "part-time",
    "nyc": "NYC",
    "travel_domestic": "domestic travel",
    "travel_international": "international travel",
    "full_time_leave": "full-time leave",
}

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

SECTION_TITLES = [
    ("priorities", "Your priorities"),
    ("pursuing", "Pursuing"),
    ("closing45", "Closing in the next 45 days"),
    ("new_week", "New this week"),
    ("windows", "Windows opening soon"),
    ("changed", "Pages that changed"),
    ("rolling_open", "Rolling and open"),
    ("past_deadline", "Past deadline, update or retire"),
]


# --------------------------------------------------------------- watch list

DATE_FIELDS = ("deadline", "added", "verified")


def load_watchlist(path):
    with open(path) as f:
        data = yaml.safe_load(f)
    return (data or {}).get("items") or []


def _parse_date_value(value):
    """Accept a date, a datetime (dropping the time), or an ISO string
    (quoted in yaml, so it never got PyYAML's automatic date parsing).
    Anything else, or an unparseable string, is None."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def normalize_item_dates(items):
    """Normalizes deadline/added/verified on every item in place. Returns a
    list of warnings for anything that had a value but could not be parsed,
    so those show up in the digest's Could not check footer instead of
    silently vanishing or crashing a date comparison later."""
    warnings = []
    for idx, item in enumerate(items):
        # The Friday routine edits the watch list by hand-like YAML writes:
        # a missing id or a quoted number must not crash the Saturday run.
        if not item.get("id"):
            item["id"] = f"item-{idx}"
            warnings.append(f"{item.get('name') or item['id']}: no id in the watch list")
        try:
            item["fit"] = int(item.get("fit") or 0)
        except (TypeError, ValueError):
            warnings.append(f"{item.get('name') or item['id']}: fit {item.get('fit')!r} is not a number, treated as 0")
            item["fit"] = 0
        for field in DATE_FIELDS:
            raw = item.get(field)
            if raw is None:
                continue
            parsed = _parse_date_value(raw)
            if parsed is None:
                label = item.get("name") or item.get("id") or "unknown item"
                warnings.append(f"{label}: unparseable {field} {raw!r}, treated as unset")
            item[field] = parsed
    return warnings


def filter_items(items):
    """Working set: drop skip/done/won/declined, and drop full_time_leave
    regardless of status (profile.md hard filter)."""
    out = []
    for i in items:
        if i.get("format") == "full_time_leave":
            continue
        if i.get("status") in STATUS_EXCLUDE:
            continue
        out.append(i)
    return out


# -------------------------------------------------------------------- score

def score_item(item, today):
    fit = item.get("fit") or 0
    payoffs = len(item.get("payoffs") or [])
    bonus = 0
    deadline = item.get("deadline")
    if deadline:
        days = (deadline - today).days
        if 0 <= days <= 21:
            bonus = 2
        elif 22 <= days <= 45:
            bonus = 1
    penalty = 1 if item.get("effort") == "high" else 0
    return fit + payoffs + bonus - penalty


def _next_date(item, today):
    """When the item next matters: its deadline, else the first day of its
    expected month (this year or next), else never. Orders the priorities
    section chronologically."""
    if item.get("deadline"):
        return item["deadline"]
    m = item.get("expected_month")
    if _valid_month(m):
        year = today.year if m >= today.month else today.year + 1
        return date(year, m, 1)
    return date.max


def _sort_key(item, today):
    deadline = item.get("deadline") or date.max
    return (-score_item(item, today), deadline)


def _valid_month(value):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 12


# ------------------------------------------------------------------ page check

def _strip_html_to_lines(body):
    body = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", body)
    body = re.sub(r"(?i)<br\s*/?>|</(p|li|h\d|div|tr|td|section|a)>", "\n", body)
    body = html_mod.unescape(re.sub(r"<[^>]+>", " ", body))
    return [re.sub(r"\s+", " ", l).strip() for l in body.split("\n") if len(l.strip()) > 3]


def extract_date_lines(body):
    seen, out = set(), []
    for l in _strip_html_to_lines(body):
        if len(l) < 400 and DATE_KEY.search(l) and l not in seen:
            seen.add(l)
            out.append(l)
    return out[:40]


def _http_get(url, timeout=25):
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        return r.status_code, r.text, None
    except Exception as e:
        return None, None, str(e)


def default_fetch(url, today_year):
    """Live fetch, falling back to Wayback if the live page 404s, errors,
    or comes back too thin to be real content. A Wayback success clears the
    live attempt's error; success or failure is judged only on the final
    body/code, never on a stale exception from the attempt that got
    replaced. A thin body (<2000 bytes) with no Wayback success is a
    failure, not a short "success". Returns (lines, via, http_status,
    error)."""
    code, body, err = _http_get(url)
    via = "live"
    thin = not err and code == 200 and bool(body) and len(body) < 2000
    if err or code != 200 or not body or thin:
        wb_url = f"https://web.archive.org/web/{today_year}id_/{url}"
        code2, body2, err2 = _http_get(wb_url)
        if not err2 and code2 == 200 and body2 and len(body2) >= 2000:
            code, body, via, err = code2, body2, "wayback", None
    if err:
        return None, via, code, err
    if code != 200:
        return None, via, code, f"HTTP {code}"
    if not body or len(body) < 2000:
        return None, via, code, "page too short"
    return extract_date_lines(body), via, code, None


def check_pages(items, state, today, no_fetch, fetch_fn=None):
    """Fetches each item's check_url/url (unless no_fetch), compares its
    hash to the stored one, and reports the newly-appeared date lines.
    A first-ever fetch is a baseline only, never reported as a change.
    fetch_fn(url) -> (lines, via, http_status, error); defaults to a real
    live+Wayback fetch. Returns (changes, failures, updated_state)."""
    changes, failures = [], []
    if no_fetch:
        return changes, failures, state
    fetch_fn = fetch_fn or (lambda url: default_fetch(url, today.year))
    for idx, item in enumerate(items):
        url = item.get("check_url") or item.get("url")
        if not url:
            failures.append(f"{item.get('name', item.get('id', 'unknown'))}: no url or check_url to fetch")
        else:
            lines, via, http_status, err = fetch_fn(url)
            if err:
                failures.append(f"{item['name']}: {err}")
            else:
                digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
                prev = state.get(item["id"])
                # A change is only reported when the previous and current
                # fetch came via the same route (both live or both
                # wayback); a route switch reads as a real page change
                # even when nothing moved, so it's stored as a new
                # baseline silently instead.
                if prev and prev.get("hash") != digest and prev.get("via") == via:
                    prev_lines = set(prev.get("lines") or [])
                    new_lines = [l for l in lines if l not in prev_lines][:6]
                    if new_lines:
                        changes.append({
                            "id": item["id"], "name": item.get("name") or item["id"], "url": item.get("url") or "",
                            "new_lines": new_lines,
                        })
                state[item["id"]] = {
                    "hash": digest, "lines": lines, "fetched_at": today.isoformat(),
                    "http_status": http_status, "via": via,
                }
        if idx < len(items) - 1:
            time.sleep(1)
    return changes, failures, state


# --------------------------------------------------------------- sections

def build_sections(items, today, page_changes):
    by_id_changed = {c["id"]: c for c in page_changes}

    pursuing = [i for i in items if i.get("status") in PURSUING_STATUSES]
    pursuing_ids = {i["id"] for i in pursuing}

    # Tal's named priorities show every week in their own section, so they
    # are left out of the date-driven sections below to avoid listing them
    # twice. Changed pages and past deadlines still include them.
    priorities = sorted(
        (i for i in items if i.get("priority") and i["id"] not in pursuing_ids),
        key=lambda i: (_next_date(i, today), i.get("name") or ""),
    )
    priority_ids = {i["id"] for i in priorities}
    items_np = [i for i in items if i["id"] not in priority_ids]

    closing45 = [
        i for i in items_np
        if i.get("deadline") and i["id"] not in pursuing_ids
        and today <= i["deadline"] <= today + timedelta(days=45)
    ]

    new_week = [
        i for i in items_np
        if i.get("status") == "new"
        or (i.get("added") and 0 <= (today - i["added"]).days <= 7)
    ]

    this_month = today.month
    next_month = (this_month % 12) + 1
    windows = [
        i for i in items_np
        if i.get("deadline_kind") == "expected"
        and _valid_month(i.get("expected_month"))
        and i["expected_month"] in {this_month, next_month}
    ]

    changed = [i for i in items if i["id"] in by_id_changed]

    rolling_open = []
    watching_no_date = []
    if today.day <= 7:
        rolling_open = [i for i in items_np if i.get("deadline_kind") in {"rolling", "open"}]
        # Not on the calendar at all yet: an expected call with no
        # expected_month, or an event with no deadline. Surfaced only
        # alongside rolling/open, on the same first-Saturday cadence, so
        # they get a periodic nudge to fill in a real date.
        watching_no_date = [
            i for i in items_np
            if (i.get("deadline_kind") == "expected" and not _valid_month(i.get("expected_month")))
            or (i.get("deadline_kind") == "event" and not i.get("deadline"))
        ]

    past_deadline = [
        i for i in items
        if i.get("deadline") and i["deadline"] < today
        and i.get("status") not in PURSUING_STATUSES
    ]

    def s(lst):
        return sorted(lst, key=lambda i: _sort_key(i, today))

    sections = {
        "priorities": priorities,
        "pursuing": s(pursuing),
        "closing45": s(closing45),
        "new_week": s(new_week),
        "windows": s(windows),
        "changed": s(changed),
        "rolling_open": s(rolling_open),
        "watching_no_date": s(watching_no_date),
        "past_deadline": s(past_deadline),
    }
    return sections, by_id_changed


# --------------------------------------------------------------- rendering

def _format_format(fmt):
    return FORMAT_LABELS.get(fmt, (fmt or "").replace("_", " "))


def _format_deadline(item, today):
    deadline = item.get("deadline")
    if deadline:
        days = (deadline - today).days
        days_str = f"{days} days left" if days >= 0 else f"{abs(days)} days overdue"
        return deadline.isoformat(), days_str
    kind = item.get("deadline_kind") or "unknown"
    if kind == "expected":
        month = item.get("expected_month")
        label = (f"expected around {MONTH_NAMES[month - 1]}" if _valid_month(month)
                  else "expected, month not set")
    else:
        label = kind
    return label, None


def _item_parts(item, today):
    deadline_str, days_str = _format_deadline(item, today)
    return {
        "name": item.get("name") or item["id"],
        "url": item.get("url") or "",
        "deadline": deadline_str,
        "days_left": days_str,
        "category": item.get("category") or "",
        "projects": ", ".join(item.get("projects") or []),
        "payoffs": ", ".join(item.get("payoffs") or []),
        "format": _format_format(item.get("format")),
        "notes": (item.get("notes") or "").strip(),
    }


def format_item_text(item, today):
    p = _item_parts(item, today)
    days = f", {p['days_left']}" if p["days_left"] else ""
    payoffs = p["payoffs"] or "none"
    line = (f"- {p['name']} ({p['url']}): {p['deadline']}{days}, {p['category']}, "
            f"projects: {p['projects']}, payoffs: {payoffs}, format: {p['format']}.")
    if p["notes"]:
        line += f" {p['notes']}"
    return line


def format_changed_text(entry):
    return f"- {entry['name']} ({entry['url']}): new lines, " + "; ".join(entry["new_lines"])


def _unique_total(sections):
    """Distinct items shown across every section, not the sum of section
    lengths: the same item can legitimately appear in more than one
    section (closing soon and new this week, say)."""
    ids = set()
    for entries in sections.values():
        for i in entries:
            ids.add(i["id"])
    return len(ids)


def _visible_sections(sections):
    """The ordered (key, title, entries, extra) tuples that actually have
    something to show; "Rolling and open" carries its "Watching, no date
    yet" sub-list as extra, shown even when the parent list is empty."""
    visible = []
    for key, title in SECTION_TITLES:
        entries = sections.get(key) or []
        extra = sections.get("watching_no_date") if key == "rolling_open" else None
        if entries or extra:
            visible.append((key, title, entries, extra or []))
    return visible


def build_digest_text(sections, by_id_changed, today, tracker_url, failures):
    total = _unique_total(sections)
    visible = _visible_sections(sections)
    out = [f"Opportunities radar: {today.isoformat()}",
           f"{total} item{'s' if total != 1 else ''} across "
           f"{len(visible)} section{'s' if len(visible) != 1 else ''}.", ""]
    if tracker_url:
        out += [f"Tracker: {tracker_url}", ""]
    if total == 0:
        out += ["Quiet week, nothing to flag.", ""]
    for key, title, entries, extra in visible:
        out.append(f"## {title} ({len(entries)})")
        out.append("")
        if key == "changed":
            out += [format_changed_text(by_id_changed[e["id"]]) for e in entries]
        else:
            out += [format_item_text(e, today) for e in entries]
        if extra:
            if entries:
                out.append("")
            out.append(f"### Watching, no date yet ({len(extra)})")
            out.append("")
            out += [format_item_text(e, today) for e in extra]
        out.append("")
    if failures:
        out.append(f"Could not check ({len(failures)})")
        out.append("")
        out += [f"- {f}" for f in failures]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _esc(s):
    return html_mod.escape(s or "", quote=True)


def format_item_html(item, today):
    p = _item_parts(item, today)
    days = f", {_esc(p['days_left'])}" if p["days_left"] else ""
    payoffs = _esc(p["payoffs"]) or "none"
    meta = f"{_esc(p['deadline'])}{days} &middot; {_esc(p['category'])}"
    detail = (f"projects: {_esc(p['projects'])} &middot; payoffs: {payoffs} &middot; "
              f"format: {_esc(p['format'])}")
    notes = (f'<p style="color:#444;font-size:13px;margin:4px 0;">{_esc(p["notes"])}</p>'
             if p["notes"] else "")
    return (
        '<div style="margin:0 0 14px 0;">'
        f'<a href="{_esc(p["url"])}" style="font-weight:600;color:#0b5cab;'
        f'text-decoration:none;">{_esc(p["name"])}</a>'
        f'<div style="color:#555;font-size:13px;margin:2px 0;">{meta}</div>'
        f'<div style="color:#555;font-size:12px;margin:2px 0;">{detail}</div>'
        f"{notes}"
        "</div>"
    )


def format_changed_html(entry):
    lines_html = "".join(f"<li>{_esc(l)}</li>" for l in entry["new_lines"])
    return (
        '<div style="margin:0 0 14px 0;">'
        f'<a href="{_esc(entry["url"])}" style="font-weight:600;color:#0b5cab;'
        f'text-decoration:none;">{_esc(entry["name"])}</a>'
        f'<ul style="font-size:13px;color:#444;">{lines_html}</ul>'
        "</div>"
    )


def build_digest_html(sections, by_id_changed, today, tracker_url, failures):
    total = _unique_total(sections)
    visible = _visible_sections(sections)
    body = [f'<p style="font-size:14px;color:#555;">{total} item'
            f'{"s" if total != 1 else ""} across {len(visible)} section'
            f'{"s" if len(visible) != 1 else ""}.</p>']
    if tracker_url:
        body.append(f'<p style="font-size:13px;"><a href="{_esc(tracker_url)}" '
                    f'style="color:#0b5cab;">Open the tracker</a></p>')
    if total == 0:
        body.append('<p style="font-size:14px;">Quiet week, nothing to flag.</p>')
    for key, title, entries, extra in visible:
        body.append(f'<h2 style="font-size:17px;border-bottom:1px solid #ddd;'
                    f'padding-bottom:4px;">{_esc(title)} ({len(entries)})</h2>')
        if key == "changed":
            body += [format_changed_html(by_id_changed[e["id"]]) for e in entries]
        else:
            body += [format_item_html(e, today) for e in entries]
        if extra:
            body.append(f'<h3 style="font-size:14px;color:#555;">Watching, no date yet '
                        f'({len(extra)})</h3>')
            body += [format_item_html(e, today) for e in extra]
    if failures:
        body.append(f'<h2 style="font-size:15px;color:#888;">Could not check '
                    f'({len(failures)})</h2>')
        body.append('<ul style="font-size:12px;color:#888;">'
                    + "".join(f"<li>{_esc(f)}</li>" for f in failures) + "</ul>")
    return (
        '<html><body style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,'
        'sans-serif;max-width:680px;margin:0 auto;padding:16px;color:#222;">'
        f'<h1 style="font-size:20px;">Opportunities radar: {_esc(today.isoformat())}</h1>'
        + "".join(body) +
        "</body></html>"
    )


def build_subject(sections):
    if _unique_total(sections) == 0:
        return "Opportunities radar: quiet week"
    n_closing = len(sections.get("closing45") or [])
    m_new = len(sections.get("new_week") or [])
    return f"Opportunities radar: {n_closing} closing soon, {m_new} new"


# ------------------------------------------------------------------- email

def send_email(subject, text_body, html_body):
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not (user and password):
        print("WARNING: --email set but GMAIL_USER/GMAIL_APP_PASSWORD missing; "
              "skipping email.", file=sys.stderr)
        return False
    # OPPS_DIGEST_TO first, then MENTION_DIGEST_TO, then the sender itself.
    # `or` (not .get(..., default)) so an unset secret coming through
    # Actions as an empty string still falls back.
    to = os.environ.get("OPPS_DIGEST_TO") or os.environ.get("MENTION_DIGEST_TO") or user
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(user, password)
        s.send_message(msg)
    print(f"Emailed digest to {to}.", file=sys.stderr)
    return True


# -------------------------------------------------------------------- main

def parse_args(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--watchlist", required=True)
    p.add_argument("--state-dir", required=True)
    p.add_argument("--today")
    p.add_argument("--no-fetch", action="store_true")
    p.add_argument("--email", action="store_true")
    p.add_argument("--out")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    today = date.fromisoformat(args.today) if args.today else date.today()

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "digests").mkdir(parents=True, exist_ok=True)

    raw_items = load_watchlist(args.watchlist)
    date_warnings = normalize_item_dates(raw_items)
    items = filter_items(raw_items)

    pages_path = state_dir / "pages.json"
    state = json.loads(pages_path.read_text()) if pages_path.exists() else {}

    changes, fetch_failures, state = check_pages(items, state, today, args.no_fetch)
    failures = date_warnings + fetch_failures
    if not args.no_fetch:
        pages_path.write_text(json.dumps(state, indent=2, sort_keys=True))

    sections, by_id_changed = build_sections(items, today, changes)

    tracker_url = os.environ.get("OPPS_TRACKER_URL")
    text_body = build_digest_text(sections, by_id_changed, today, tracker_url, failures)
    html_body = build_digest_html(sections, by_id_changed, today, tracker_url, failures)
    subject = build_subject(sections)

    out_base = args.out or str(state_dir / "digests" / today.isoformat())
    html_path = Path(f"{out_base}.html")
    txt_path = Path(f"{out_base}.txt")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html_body)
    txt_path.write_text(text_body)

    last_run = {
        "date": today.isoformat(),
        "counts": {k: len(v) for k, v in sections.items()},
        "failures": failures,
    }
    # Written before the email attempt: state must advance even if sending
    # fails, or the next run repeats today's page-change baseline.
    (state_dir / "last_run.json").write_text(json.dumps(last_run, indent=2, sort_keys=True))

    email_ok = True
    if args.email:
        email_ok = send_email(subject, text_body, html_body)

    print(subject)
    print(text_body)
    return 0 if email_ok else 1


if __name__ == "__main__":
    sys.exit(main())
