#!/usr/bin/env python3
"""
Assemble ONE monthly ops digest from the sections that producers drop into the
private premium repo (ops_digest/pending/), email it, and file the sections
under ops_digest/sent/YYYY-MM/.

    python3 ops_digest/assemble.py --premium /tmp/premium [--dry-run] [--since YYYY-MM-DD]
    python3 ops_digest/assemble.py --send-files --subject S --txt T.txt --html T.html

Sections: <source>.html + .txt + .json ({source, title, generated_at, needs_tal})
written by the Actions, or <source>.md written by cloud routines:

    Subject: <subject line>
    needs_tal: <integer>
    <blank line>
    <plain-text body: CAPS headings, numbered TO DO items, dashed prompt blocks>

The tracker refresh routine's report is read from ops_digest/tracker_refresh_report.md in the public repo
(never moved or filed). The email opens with "Needs you", "Did not report" (expected sources with no
file, which is how a silent routine failure shows up) and "Failed Action runs
since the last digest", then every section in order.

Env: GMAIL_USER, GMAIL_APP_PASSWORD (via seo/common.send_email), GITHUB_TOKEN
(data_website runs), PREMIUM_PUSH_TOKEN (the other repos' runs).
Billing: no Anthropic API.
"""

import argparse
import html as html_lib
import json
import os
import re
import subprocess
import time
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "seo"))
from common import archive_sent, extract_asks, send_email, write_asks  # noqa: E402

EXPECTED = ["seo", "trackers_quality", "trackers_refresh", "block_party_quality", "fiscal_drafts", "copy_currency", "brand_qa"]
LABELS = {"seo": "SEO report", "trackers_quality": "Legislation trackers quality report",
          "trackers_refresh": "Tracker refresh report", "block_party_quality": "Block Party quality report", "fiscal_drafts": "Fiscal tracker drafts",
          "copy_currency": "Copy currency review", "brand_qa": "Brand QA"}
REPOS = [("TalR24/nycur-data-website", "GITHUB_TOKEN"),
         ("TalR24/nycur-data-premium", "PREMIUM_PUSH_TOKEN"),
         ("TalR24/talroded_personal", "PREMIUM_PUSH_TOKEN"),
         ("block-party-studio/resolution_engine", "PREMIUM_PUSH_TOKEN")]
SKIP_WORKFLOWS = ("pages-build-deployment", "pages build and deployment")
# Expected sources that cannot report yet; shown with the reason instead of as a failure (audit A3, Oct 18 2026)
SETUP_PENDING = {"block_party_quality": "no file; until the PREMIUM_PUSH_TOKEN secret exists in block-party-studio/resolution_engine this is expected (TODO_tal.md), after that check its monthly-quality-report run"}
DASHES = re.compile(r"^-{5,}\s*$")
URL = re.compile(r"(https?://[^\s<>\"')]+)")


# ----------------------------------------------------------- loading ----

def parse_md(text):
    """(subject, needs_tal, body) from a routine's .md section."""
    lines = text.splitlines()
    subject, needs, drop = None, 0, set()
    for i, line in enumerate(lines[:12]):
        t = line.strip()
        if not t or t.startswith(("#", "```")):
            continue  # titles, fences and blanks may sit above the headers
        m = re.match(r"(?i)(?:[*>`-]+\s*)?(subject|needs_tal)\s*:\s*(.*?)\**\s*$", t)
        if not m:
            break  # headers only at the top: a 'Subject:' inside a prompt box is body text (audit round 2, A2-03)
        if m.group(1).lower() == "subject" and subject is None:
            subject = m.group(2).strip().strip("*").strip()
        elif m.group(1).lower() == "needs_tal" and i not in drop:
            digits = re.search(r"\d+", m.group(2))
            needs = int(digits.group()) if digits else 0
        drop.add(i)
    if subject is None:
        print("warning: section has no Subject: header at its top", file=sys.stderr)
    return subject, needs, "\n".join(l for i, l in enumerate(lines) if i not in drop).strip("\n")


def text_to_html(body):
    """Plain text to HTML: line breaks kept, dashed prompt blocks in <pre>,
    CAPS heading lines bold, bare URLs linked. Stdlib only."""
    out, buf, in_pre = [], [], False

    def flush_text():
        if buf:
            chunk = html_lib.escape("\n".join(buf))
            chunk = URL.sub(r'<a href="\1">\1</a>', chunk)
            chunk = re.sub(r"(?m)^([A-Z][A-Z0-9 ,&/'()-]{3,})$", r"<strong>\1</strong>", chunk)
            out.append(f'<div style="white-space:pre-wrap;margin:0 0 12px">{chunk}</div>')
            buf.clear()

    for line in body.splitlines():
        if DASHES.match(line):
            if in_pre:
                chunk = html_lib.escape("\n".join(buf))
                out.append('<pre style="background:#f4efe6;border:1px solid #d9d0bf;padding:10px;'
                           'white-space:pre-wrap;font-size:13px">' + chunk + "</pre>")
                buf.clear()
                in_pre = False
            else:
                flush_text()
                in_pre = True
        else:
            buf.append(line)
    if in_pre:  # unterminated block: still keep it copyable
        out.append('<pre style="white-space:pre-wrap;font-size:13px">' + html_lib.escape("\n".join(buf)) + "</pre>")
        buf.clear()
    flush_text()
    return "\n".join(out)


def inner_html(page):
    """A producer's full HTML page reduced to its styles plus body contents."""
    m = re.search(r"<body[^>]*>(.*)</body>", page, re.S | re.I)
    if not m:
        return page
    styles = "".join(re.findall(r"<style.*?</style>", page, re.S | re.I))
    return styles + m.group(1)


def load_sections(pending):
    """{source: dict(key, title, needs, html, text)} for every stem in pending/."""
    stems = {}
    for f in sorted(Path(pending).glob("*")):
        if f.name.startswith(".") or f.suffix not in (".html", ".txt", ".md", ".json"):
            continue
        stems.setdefault(f.stem, {})[f.suffix] = f
    secs = {}
    for stem, files in stems.items():
        title, needs, text, page = LABELS.get(stem, stem), 0, "", ""
        if ".json" in files:
            try:
                meta = json.loads(files[".json"].read_text(encoding="utf-8"))
                title, needs = meta.get("title") or title, int(meta.get("needs_tal") or 0)
            except (ValueError, OSError):
                pass
        if ".md" in files:
            subject, md_needs, body = parse_md(files[".md"].read_text(encoding="utf-8"))
            title = subject or title
            needs = md_needs if ".json" not in files else needs
            text = body
            page = text_to_html(body)
        if ".txt" in files:
            text = files[".txt"].read_text(encoding="utf-8")
        if ".html" in files:
            page = inner_html(files[".html"].read_text(encoding="utf-8"))
        elif ".txt" in files and not page:
            page = text_to_html(text)
        if not (text or page):
            continue
        secs[stem] = {"key": stem, "title": title, "needs": needs, "html": page or text_to_html(text), "text": text}
    return secs


REFRESH_REPORT = Path(__file__).resolve().parent / "tracker_refresh_report.md"
REFRESH_MAX_AGE_DAYS = 35


def load_refresh_report(today, path=None):
    """The monthly tracker refresh routine writes this file into the PUBLIC repo (counts and validator lines
    only, see .github/tracker_refresh_routine_prompt.md, Reporting). Returns a section dict, or None when the
    file is missing, has no 'Report date:' line, or is older than 35 days (then it shows under Did not report)."""
    path = Path(path or REFRESH_REPORT)
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    m = re.search(r"(?m)^Report date:\s*(\d{4}-\d{2}-\d{2})", raw)
    if not m or (today - date.fromisoformat(m.group(1))).days > REFRESH_MAX_AGE_DAYS:
        return None
    subject, needs, body = parse_md(raw)
    return {"key": "trackers_refresh", "title": subject or LABELS["trackers_refresh"], "needs": needs,
            "html": text_to_html(body), "text": body}


def ordered(secs):
    keys = [k for k in EXPECTED if k in secs] + sorted(k for k in secs if k not in EXPECTED)
    return [secs[k] for k in keys]


# ------------------------------------------------------- failed runs ----

def failed_runs(since, env=os.environ):
    """[(repo, note, [(workflow, date, url)])]; note is non-empty when unchecked."""
    out = []
    for repo, tok_name in REPOS:
        token = env.get(tok_name) or ""
        runs, page = [], 1
        try:
            while True:  # every page until an empty one (counts rule: never a capped first page)
                url = (f"https://api.github.com/repos/{repo}/actions/runs?status=failure"
                       f"&created=%3E%3D{since}&per_page=100&page={page}")
                req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                           "User-Agent": "nycur-ops-digest",
                                                           **({"Authorization": f"Bearer {token}"} if token else {})})
                with urllib.request.urlopen(req, timeout=30) as r:
                    batch = json.load(r).get("workflow_runs", [])
                if not batch:
                    break
                runs += batch
                page += 1
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                out.append((repo, f"not checked (token cannot read {repo})", []))
            else:
                out.append((repo, f"not checked (HTTP {e.code})", []))
            continue
        except Exception as e:  # noqa: BLE001
            out.append((repo, f"not checked ({type(e).__name__})", []))
            continue
        rows = [(r.get("name") or "?", (r.get("created_at") or "")[:10], r.get("html_url") or "")
                for r in runs if (r.get("name") or "") not in SKIP_WORKFLOWS]
        out.append((repo, "", rows))
    return out


# ----------------------------------------------------------- compose ----

def default_since(premium, today):
    sent = Path(premium) / "ops_digest" / "sent"
    months = sorted(p.name for p in sent.glob("????-??")) if sent.exists() else []
    if months:
        y, m = map(int, months[-1].split("-"))
        return date(y, m, 5).isoformat()
    return (today - timedelta(days=35)).isoformat()


def compose(secs, missing, runs, today):
    n = sum(s["needs"] for s in secs)
    subject = (f"NYCuriosity monthly ops, {today.strftime('%B %Y')}: "
               f"{n} item{'s' if n != 1 else ''} need{'s' if n == 1 else ''} you")
    # plain text
    t = ["NEEDS YOU", ""]
    t += [f"- {s['title']}: {s['needs']}" for s in secs if s["needs"]] or ["Nothing."]
    t += ["", "DID NOT REPORT", ""]
    t += [f"- {LABELS[k]} ({k}): " + (SETUP_PENDING.get(k) or "no file in ops_digest/pending/") for k in missing] or ["All expected sources reported."]
    t += ["", "FAILED ACTION RUNS SINCE THE LAST DIGEST", ""]
    any_run = False
    for repo, note, rows in runs:
        if note:
            t.append(f"- {repo}: {note}")
        for wf, d, u in rows:
            any_run = True
            t.append(f"- {repo}: {wf}, {d}, {u}")
    if not any_run and not any(note for _, note, _ in runs):
        t.append("None.")
    for s in secs:
        t += ["", "=" * 70, s["title"].upper(), "=" * 70, "", s["text"].rstrip()]
    text = "\n".join(t) + "\n"
    # html
    e = html_lib.escape
    h = ['<div style="font-family:Georgia,serif;max-width:720px;color:#2b2118">',
         f'<h1 style="font-size:20px">{e(subject)}</h1>', '<h2 style="font-size:16px">Needs you</h2>', "<ul>"]
    h += [f'<li><a href="#sec-{s["key"]}">{e(s["title"])}</a>: {s["needs"]}</li>' for s in secs if s["needs"]] or ["<li>Nothing.</li>"]
    h += ["</ul>", '<h2 style="font-size:16px">Did not report</h2>', "<ul>"]
    h += [f"<li>{e(LABELS[k])} (<code>{k}</code>): {e(SETUP_PENDING.get(k) or 'no file in ops_digest/pending/')}</li>" for k in missing] or ["<li>All expected sources reported.</li>"]
    h += ["</ul>", '<h2 style="font-size:16px">Failed Action runs since the last digest</h2>', "<ul>"]
    li = []
    for repo, note, rows in runs:
        if note:
            li.append(f"<li>{e(repo)}: {e(note)}</li>")
        for wf, d, u in rows:
            li.append(f'<li>{e(repo)}: {e(wf)}, {e(d)}, <a href="{e(u)}">run</a></li>')
    h += li or ["<li>None.</li>"]
    h.append("</ul>")
    for s in secs:
        h += [f'<hr><h2 id="sec-{s["key"]}" style="font-size:17px">{e(s["title"])}</h2>', s["html"]]
    h.append("</div>")
    return subject, text, "\n".join(h)


def git(premium, *args):
    return subprocess.run(["git", "-C", str(premium), *args], check=True)


def build_extras(secs, subject, text, today):
    """Files for the premium repo that go in the same commit as the filed sections: the exact digest body
    under planning/sent/ and one line per ask under planning/inbox/asks_<YYYY-MM>.md (read by the Sunday
    routine). Returns (sent_body, asks) where asks is [(title, where)]."""
    asks = []
    for sec in secs:
        if sec["needs"]:
            found = extract_asks(sec["text"]) or [sec["title"]]  # no numbered list: the section's own title is the ask
            asks += [(a, LABELS.get(sec["key"], sec["title"])) for a in found]
    return text, asks


def write_extras(premium, subject, text, asks, today):
    """Write the archive and asks files under premium. Returns the two paths (asks path is None when no asks)."""
    month = today.strftime("%Y-%m")
    sent_path = archive_sent(subject, text, "Tal (monthly ops digest)", "monthly_ops_digest",
                             dest_dir=Path(premium) / "planning" / "sent",
                             when=datetime.combine(today, datetime.now(timezone.utc).time(), tzinfo=timezone.utc))
    asks_path = Path(premium) / "planning" / "inbox" / f"asks_{month}.md"
    n = write_asks(asks_path, asks, f"{today.strftime('%b')} {today.day} ops digest", today)
    return sent_path, (asks_path if n else None), n


def file_sent(premium, today, extras=None):
    """Move the sections that were just sent into sent/YYYY-MM/ and push. Each attempt starts from a fresh
    origin/main, so a section that landed while the digest ran is left in pending/ for next month instead of
    breaking the rebase (audit round 2, A2-02)."""
    pend = Path(premium) / "ops_digest" / "pending"
    names = [f.name for f in sorted(pend.iterdir()) if not f.name.startswith(".")]
    if not names and not extras:
        return 0
    month = today.strftime("%Y-%m")
    git(premium, "config", "user.name", "github-actions[bot]")
    git(premium, "config", "user.email", "github-actions[bot]@users.noreply.github.com")
    for attempt in range(3):
        try:
            git(premium, "fetch", "origin", "main")
            git(premium, "reset", "--hard", "origin/main")
            dest = Path(premium) / "ops_digest" / "sent" / month
            dest.mkdir(parents=True, exist_ok=True)
            moved = 0
            for n in names:
                if (pend / n).exists():
                    git(premium, "mv", "-f", f"ops_digest/pending/{n}", f"ops_digest/sent/{month}/{n}")
                    moved += 1
            if extras:  # written after the reset so a retry starts clean
                sent_path, asks_path, _ = write_extras(premium, *extras)
                git(premium, "add", "--", str(sent_path.relative_to(premium)))
                if asks_path:
                    git(premium, "add", "--", str(asks_path.relative_to(premium)))
            elif not moved:
                return 0
            git(premium, "commit", "-m", f"Ops digest {month}: file sent sections, archive and asks")
            git(premium, "push", "origin", "HEAD:main")
            return moved
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
            time.sleep(10 * (attempt + 1))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--premium", default=os.environ.get("PREMIUM_DIR", "/tmp/premium"))
    ap.add_argument("--dry-run", action="store_true", help="print the email; send nothing, move nothing")
    ap.add_argument("--since", help="failed runs created on or after YYYY-MM-DD (default: last digest's date)")
    ap.add_argument("--today", help="override today's date (testing)")
    ap.add_argument("--extras-dir", help="with --dry-run: write the archive and asks files under this folder (testing)")
    ap.add_argument("--no-runs", action="store_true", help="skip the GitHub failed-runs lookup (testing)")
    ap.add_argument("--send-files", action="store_true", help="just email --txt/--html (fallback path)")
    ap.add_argument("--subject")
    ap.add_argument("--to", help="recipient for --send-files (default: the seo/common ALERT_TO)")
    ap.add_argument("--txt")
    ap.add_argument("--html")
    a = ap.parse_args()

    if a.send_files:
        body = Path(a.txt).read_text(encoding="utf-8") if a.txt and Path(a.txt).exists() else ""
        page = Path(a.html).read_text(encoding="utf-8") if a.html and Path(a.html).exists() else None
        kw = {"to": a.to} if a.to else {}
        return 0 if send_email(a.subject or "NYCuriosity digest", body, html=page, **kw) else 1

    today = date.fromisoformat(a.today) if a.today else datetime.now(timezone.utc).date()
    premium = Path(a.premium)
    pending = premium / "ops_digest" / "pending"
    loaded = load_sections(pending) if pending.exists() else {}
    refresh = load_refresh_report(today)
    if refresh:
        loaded["trackers_refresh"] = refresh
    secs = ordered(loaded)
    have = {s["key"] for s in secs}
    missing = [k for k in EXPECTED if k not in have]
    since = a.since or default_since(premium, today)
    runs = [] if a.no_runs else failed_runs(since)
    subject, text, page = compose(secs, missing, runs, today)

    if a.dry_run:
        print(f"DRY RUN, nothing sent or moved.\nSubject: {subject}\nFailed runs since: {since}\n\n{text}")
        print("Did not report:", ", ".join(missing) or "none")
        _, asks = build_extras(secs, subject, text, today)
        if a.extras_dir:
            sent_path, asks_path, n = write_extras(a.extras_dir, subject, text, asks, today)
            print(f"\nArchive file: {sent_path}\nAsks file: {asks_path} ({n} lines)")
        else:
            print(f"\n{len(asks)} asks would go to planning/inbox/asks_{today.strftime('%Y-%m')}.md")
        return 0
    if not send_email(subject, text, html=page):
        print("Email not sent; leaving pending/ untouched.", file=sys.stderr)
        return 1
    print(f"Sent: {subject}")
    _, asks = build_extras(secs, subject, text, today)
    print(f"Filed {file_sent(premium, today, (subject, text, asks, today))} files under ops_digest/sent/{today.strftime('%Y-%m')}/, "
          f"plus the digest body under planning/sent/ and {len(asks)} asks under planning/inbox/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
