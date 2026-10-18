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

The email opens with "Needs you", "Did not report" (expected sources with no
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
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "seo"))
from common import send_email  # noqa: E402

EXPECTED = ["seo", "trackers_quality", "block_party_quality", "fiscal_drafts", "copy_currency", "brand_qa"]
LABELS = {"seo": "SEO report", "trackers_quality": "Legislation trackers quality report",
          "block_party_quality": "Block Party quality report", "fiscal_drafts": "Fiscal tracker drafts",
          "copy_currency": "Copy currency review", "brand_qa": "Brand QA"}
REPOS = [("TalR24/nycur-data-website", "GITHUB_TOKEN"),
         ("TalR24/nycur-data-premium", "PREMIUM_PUSH_TOKEN"),
         ("TalR24/talroded_personal", "PREMIUM_PUSH_TOKEN"),
         ("block-party-studio/resolution_engine", "PREMIUM_PUSH_TOKEN")]
SKIP_WORKFLOWS = ("pages-build-deployment", "pages build and deployment")
DASHES = re.compile(r"^-{10,}\s*$")
URL = re.compile(r"(https?://[^\s<>\"')]+)")


# ----------------------------------------------------------- loading ----

def parse_md(text):
    """(subject, needs_tal, body) from a routine's .md section."""
    lines = text.splitlines()
    subject, needs = None, 0
    i = 0
    while i < len(lines) and i < 2:
        m = re.match(r"(?i)\s*(subject|needs_tal)\s*:\s*(.*)$", lines[i])
        if not m:
            break
        if m.group(1).lower() == "subject":
            subject = m.group(2).strip()
        else:
            digits = re.search(r"\d+", m.group(2))
            needs = int(digits.group()) if digits else 0
        i += 1
    return subject, needs, "\n".join(lines[i:]).lstrip("\n")


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


def ordered(secs):
    keys = [k for k in EXPECTED if k in secs] + sorted(k for k in secs if k not in EXPECTED)
    return [secs[k] for k in keys]


# ------------------------------------------------------- failed runs ----

def failed_runs(since, env=os.environ):
    """[(repo, note, [(workflow, date, url)])]; note is non-empty when unchecked."""
    out = []
    for repo, tok_name in REPOS:
        token = env.get(tok_name) or ""
        url = (f"https://api.github.com/repos/{repo}/actions/runs?status=failure"
               f"&created=%3E%3D{since}&per_page=100")
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "nycur-ops-digest",
                                                   **({"Authorization": f"Bearer {token}"} if token else {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                runs = json.load(r).get("workflow_runs", [])
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
    t += [f"- {LABELS[k]} ({k}): no file in ops_digest/pending/" for k in missing] or ["All expected sources reported."]
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
    h += [f"<li>{e(LABELS[k])} (<code>{k}</code>): no file in ops_digest/pending/</li>" for k in missing] or ["<li>All expected sources reported.</li>"]
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


def file_sent(premium, today):
    pend = Path(premium) / "ops_digest" / "pending"
    dest = Path(premium) / "ops_digest" / "sent" / today.strftime("%Y-%m")
    dest.mkdir(parents=True, exist_ok=True)
    moved = 0
    for f in sorted(pend.iterdir()):
        if f.name.startswith("."):
            continue
        git(premium, "mv", "-f", str(f.relative_to(premium)), str((dest / f.name).relative_to(premium)))
        moved += 1
    if moved:
        git(premium, "config", "user.name", "github-actions[bot]")
        git(premium, "config", "user.email", "github-actions[bot]@users.noreply.github.com")
        git(premium, "add", "ops_digest")
        git(premium, "commit", "-m", f"Ops digest {today.strftime('%Y-%m')}: file sent sections")
        git(premium, "pull", "--rebase", "origin", "main")
        git(premium, "push")
    return moved


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--premium", default=os.environ.get("PREMIUM_DIR", "/tmp/premium"))
    ap.add_argument("--dry-run", action="store_true", help="print the email; send nothing, move nothing")
    ap.add_argument("--since", help="failed runs created on or after YYYY-MM-DD (default: last digest's date)")
    ap.add_argument("--today", help="override today's date (testing)")
    ap.add_argument("--no-runs", action="store_true", help="skip the GitHub failed-runs lookup (testing)")
    ap.add_argument("--send-files", action="store_true", help="just email --txt/--html (fallback path)")
    ap.add_argument("--subject")
    ap.add_argument("--txt")
    ap.add_argument("--html")
    a = ap.parse_args()

    if a.send_files:
        body = Path(a.txt).read_text(encoding="utf-8") if a.txt and Path(a.txt).exists() else ""
        page = Path(a.html).read_text(encoding="utf-8") if a.html and Path(a.html).exists() else None
        return 0 if send_email(a.subject or "NYCuriosity digest", body, html=page) else 1

    today = date.fromisoformat(a.today) if a.today else datetime.now(timezone.utc).date()
    premium = Path(a.premium)
    pending = premium / "ops_digest" / "pending"
    secs = ordered(load_sections(pending)) if pending.exists() else []
    have = {s["key"] for s in secs}
    missing = [k for k in EXPECTED if k not in have]
    since = a.since or default_since(premium, today)
    runs = [] if a.no_runs else failed_runs(since)
    subject, text, page = compose(secs, missing, runs, today)

    if a.dry_run:
        print(f"DRY RUN, nothing sent or moved.\nSubject: {subject}\nFailed runs since: {since}\n\n{text}")
        print("Did not report:", ", ".join(missing) or "none")
        return 0
    if not send_email(subject, text, html=page):
        print("Email not sent; leaving pending/ untouched.", file=sys.stderr)
        return 1
    print(f"Sent: {subject}")
    print(f"Filed {file_sent(premium, today)} files under ops_digest/sent/{today.strftime('%Y-%m')}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
