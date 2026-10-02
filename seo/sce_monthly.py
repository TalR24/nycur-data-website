#!/usr/bin/env python3
"""
The one monthly email for State Capacity Ecosystem (statecapacityecosystem.com
and substack.statecapacityecosystem.com): site health, the review routine's
fixes, and search recommendations, as a to-do list where every item carries
its steps and a prompt to paste into Claude Code.

    python3 seo/sce_monthly.py                     # build files only
    python3 seo/sce_monthly.py --email             # also send to Tal + the SCE inbox
    python3 seo/sce_monthly.py --health-report path/to/site_health_report.md

Inputs, in the order the 1st of the month produces them:
  13:00 UTC  statecapacityecosystem site_health.yml runs data/site_health.py
             and opens the "Site health: YYYY-MM" issue
  14:05 UTC  the "SCE site health review" routine opens a site-health/YYYY-MM
             PR and comments its findings on that issue (when it has write access)
  15:30 UTC  this script (data_website sce_monthly.yml) reruns site_health.py on
             a fresh clone, reads the issue, comment and PR from the public repo,
             pulls sc-domain:statecapacityecosystem.com from Search Console, and
             sends one email

Search numbers go only to the email and the private premium repo, never to the
public SCE issue. Deterministic rules only: no model calls.
"""

import argparse
import html
import json
import os
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ALERT_TO, WORKSPACE, send_email  # noqa: E402
import gsc_pull  # noqa: E402
import report_email  # noqa: E402
from report_email import plural  # noqa: E402

PROPERTY = "sc-domain:statecapacityecosystem.com"
REPO = "TalR24/statecapacityecosystem"
SCE_INBOX = "statecapacityecosystem@gmail.com"
RECIPIENTS = [ALERT_TO, SCE_INBOX]
ROUTINE_URL = "https://claude.ai/code/routines/trig_01RA9ajrtSmyXoTWKZRmwEXo"
GITHUB_APP_URL = "https://github.com/apps/claude/installations/select_target"


# ---------------------------------------------------------- site health ---

def run_site_health(sce_root):
    subprocess.run([sys.executable, "data/site_health.py", "--external"], cwd=sce_root,
                   capture_output=True, text=True, timeout=900)
    report = Path(sce_root) / "site_health_report.md"
    return report.read_text(encoding="utf-8") if report.exists() else ""


def parse_health(md):
    """{'summary': '17 checks, 0 hard failures, 3 warnings', 'sections': [{name, status, findings}]}"""
    lines = md.splitlines()
    summary = next((l.strip() for l in lines if re.match(r"^\d+ checks", l.strip())), "")
    sections, cur = [], None
    for line in lines:
        m = re.match(r"^## (\S+)\s+(.*)$", line)
        if m:
            cur = {"num": m.group(1).rstrip("."), "name": re.sub(r"\s*\((WARN|WARN, network|network.*?)\)$", "",
                                                                     m.group(2)).strip(),
                   "status": "", "findings": []}
            sections.append(cur)
            continue
        if cur is None:
            continue
        s = re.match(r"^\*\*(PASS|WARN|FAIL)\*\*", line.strip())
        if s:
            cur["status"] = s.group(1)
        elif line.startswith("- ") and line.strip() != "- No issues found.":
            cur["findings"].append(line[2:].strip())
    return {"summary": summary, "sections": sections}


# --------------------------------------------------------------- GitHub ---

def gh_get(session, path):
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = session.get(f"https://api.github.com/repos/{REPO}/{path}", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def review_outputs(session, month):
    """This month's health issue, the routine's comments on it, and its PR."""
    out = {"issue": None, "comments": [], "pr": None, "error": None}
    try:
        issues = gh_get(session, "issues?labels=site-health&state=all&per_page=10")
        out["issue"] = next((i for i in issues if i["title"] == f"Site health: {month}"), None)
        if out["issue"]:
            out["comments"] = gh_get(session, f"issues/{out['issue']['number']}/comments?per_page=50")
        pulls = gh_get(session, "pulls?state=all&per_page=20")
        out["pr"] = next((p for p in pulls if p["head"]["ref"] == f"site-health/{month}"), None)
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
    return out


# -------------------------------------------------------------- actions ---

FIX_RULES = ("Fix only dates, counts, links, expired event calls to action, and Latest band cards copied from "
             "existing markup with the post's own title and subtitle; any new sentence is mine to write.")


def health_actions(health, review, month):
    acts = []
    for s in health["sections"]:
        if s["status"] not in ("FAIL", "WARN") or not s["findings"]:
            continue
        hard = s["status"] == "FAIL"
        n = len(s["findings"])
        acts.append({
            "tag": "Fix first" if hard else "Check", "who": "Claude Code",
            "title": f"Site health, {s['name']}: {plural(n, 'hard failure' if hard else 'warning')}",
            "why": ("site_health.py counts these as broken on the live site." if hard else
                    "site_health.py flags these for a look; some are false alarms (bot-blocked links, symbols "
                    "that read as dashes)."),
            "findings": s["findings"],
            "steps": ["Paste the prompt into Claude Code.",
                      "Approve the fixes it proposes" + ("." if hard else ", or tell it which flags to ignore."),
                      "It reruns site_health.py, then commits and pushes after you approve the diff."],
            "prompt": (f"Use the state-capacity-ecosystem skill. In ~/nycur/statecapacityecosystem (pull first), "
                       f"`python3 data/site_health.py` reports {plural(n, 'hard failure' if hard else 'warning')} "
                       f"under check {s['num']} ({s['name']}): " + " | ".join(s["findings"][:12])
                       + (f" | and {n - 12} more" if n > 12 else "") + ". "
                       + ("Fix them. " if hard else "Tell me which are real and which are false alarms, and "
                          "propose fixes for the real ones. ")
                       + FIX_RULES + " Rerun site_health.py, show me the diff, and commit and push after I approve."),
        })

    pr, comments = review["pr"], review["comments"]
    if pr and pr["state"] == "open":
        acts.append({
            "tag": "Review", "who": "You on GitHub, or Claude Code",
            "title": f"The review routine opened fix PR #{pr['number']}: merge it to publish its fixes",
            "why": f"\"{pr['title']}\". Nothing on the live site changes until it is merged.",
            "steps": ["Open the PR and read the diff, or paste the prompt for a summary first.",
                      "Merge it; GitHub Pages publishes within a few minutes."],
            "links": [(f"PR #{pr['number']} on GitHub", pr["html_url"])],
            "prompt": (f"Use the state-capacity-ecosystem skill. Summarize every change in PR #{pr['number']} of "
                       f"{REPO} ({pr['html_url']}), check it out locally, run `python3 data/site_health.py`, and "
                       f"merge it after I approve."),
        })
    if comments:
        c = comments[-1]
        n_items = len(re.findall(r"(?m)^\s*\d+\.\s", c["body"]))
        acts.append({
            "tag": "Check", "who": "You, with Claude Code",
            "title": (f"The monthly review found {plural(n_items, 'item')} that need your wording" if n_items else
                      "The monthly review left notes on the health issue"),
            "why": "These are facts the site no longer matches; the review names the page, line and fact, and you "
                   "write the sentence.",
            "steps": ["Paste the prompt; Claude walks you through each item.",
                      "Give it your wording; it applies it, reruns site_health.py, and commits after you approve."],
            "links": [("The review's comment on GitHub", c["html_url"])],
            "prompt": (f"Use the state-capacity-ecosystem skill. Walk me through the findings in {c['html_url']} "
                       f"one at a time: show the page, the line and the fact it should reflect. I write the "
                       f"wording; apply it in ~/nycur/statecapacityecosystem, rerun site_health.py, and commit and "
                       f"push after I approve."),
        })
    if not pr and not comments:
        acts.append({
            "tag": "Fix first", "who": "You, then Claude Code",
            "title": "The monthly review routine could not post its fixes",
            "why": ("The SCE site health review routine runs on the 1st at 14:05 UTC and opens a PR plus an issue "
                    "comment. Neither exists for " + month + ". On Oct 1 2026 the cause was the Claude GitHub App "
                    "having read-only access to the repo, so the routine's fixes stayed in its container."),
            "steps": ["Give the Claude GitHub App write access to TalR24/statecapacityecosystem (link below), so "
                      "next month's run can post.",
                      "Paste the prompt to run this month's review from your machine, where pushing works."],
            "links": [("Claude GitHub App access", GITHUB_APP_URL), ("The routine", ROUTINE_URL)],
            "prompt": ("Use the state-capacity-ecosystem skill. Run this month's SCE site health review in "
                       "~/nycur/statecapacityecosystem (pull first): run `python3 data/site_health.py --external`; "
                       "find events that have passed (check each Luma link's date) but still say Sign up, Upcoming "
                       "or NEXT; compare the homepage Latest band and the TOOLS · PLAYBOOKS · POSTS kicker with "
                       "https://substack.statecapacityecosystem.com/api/v1/archive?sort=new&limit=20 ; check that "
                       "the Methodology page, README and data/build_affinity.py agree on weights, K and the "
                       f"embedding model. On branch site-health/{month}, {FIX_RULES[0].lower() + FIX_RULES[1:]} "
                       "Rerun site_health.py and show me the diff before pushing and opening the PR. List "
                       "everything else as findings with page and line."),
        })
    order = {"Fix first": 0, "Review": 1, "Check": 2}
    return sorted(acts, key=lambda x: order.get(x["tag"], 3))


def health_block(health, review):
    e = html.escape
    passed = [s["name"] for s in health["sections"] if s["status"] == "PASS"]
    issue = review["issue"]
    link = (f' <a href="{e(issue["html_url"])}">Full report on GitHub (issue #{issue["number"]})</a>.'
            if issue else "")
    body = (f'<p style="margin:0 0 8px;"><b>{e(health["summary"] or "site_health.py produced no report")}</b>.'
            f'{link}</p>')
    if passed:
        body += (f'<p style="margin:0;font-size:13px;">Passed: {e(", ".join(passed))}.</p>')
    if review["error"]:
        body += f'<p style="font-size:13px;">Could not read GitHub: {e(review["error"])}</p>'
    md = (health["summary"] or "site_health.py produced no report") + "."
    if issue:
        md += f" Full report: {issue['html_url']}"
    if passed:
        md += "\nPassed: " + ", ".join(passed) + "."
    return body, md


# ----------------------------------------------------------------- main ---

def main():
    import requests
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sce-repo", default=str(WORKSPACE / "statecapacityecosystem"))
    ap.add_argument("--health-report", help="use this site_health_report.md instead of running the script")
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--end", help="search period end YYYY-MM-DD (default: today minus data lag)")
    ap.add_argument("--month", help="health month YYYY-MM (default: this month)")
    ap.add_argument("--key", help="service account JSON path")
    ap.add_argument("--changes", help="seo_reports/changes.md (default: the premium repo copy if present)")
    ap.add_argument("--out", help="folder for the files (default: nycur-data-premium/seo_reports/)")
    ap.add_argument("--email", action="store_true")
    ap.add_argument("--preview", action="store_true", help="email Tal only, not the SCE inbox")
    args = ap.parse_args()

    today = date.today()
    month = args.month or today.strftime("%Y-%m")
    end = date.fromisoformat(args.end) if args.end else today - timedelta(days=gsc_pull.DATA_LAG_DAYS)
    start = end - timedelta(days=args.days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=args.days - 1)

    session = requests.Session()
    health_md = (Path(args.health_report).read_text(encoding="utf-8") if args.health_report
                 else run_site_health(args.sce_repo))
    health = parse_health(health_md)
    review = review_outputs(session, month)

    creds = gsc_pull.credentials(args.key)
    sections, snapshot = gsc_pull.collect(session, creds, [PROPERTY], start, end, prev_start, prev_end)
    changes = args.changes or WORKSPACE / report_email.CHANGES_REL
    plan = report_email.build(sections, (start, end), session, changes,
                              extra_actions=health_actions(health, review, month))
    snapshot["actions"] = plan["actions"]
    snapshot["health"] = health

    block_html, block_md = health_block(health, review)
    md = gsc_pull.render((start, end), (prev_start, prev_end), sections,
                         report_email.render_markdown(plan, sections, [("Site health", block_md)]),
                         title="State Capacity Ecosystem monthly report")

    out_dir = Path(args.out) if args.out else (
        WORKSPACE / "nycur-data-premium" / "seo_reports" if (WORKSPACE / "nycur-data-premium").exists()
        else Path("seo_reports"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"sce-{month}"
    n = len(plan["actions"])
    page = report_email.render_html(plan, sections, stem.name + ".md", theme=report_email.sce_theme(args.sce_repo),
                                    blocks=[("Site health", block_html)])
    stem.with_suffix(".md").write_text(md, encoding="utf-8")
    stem.with_suffix(".json").write_text(json.dumps(snapshot, indent=1, default=str), encoding="utf-8")
    stem.with_suffix(".html").write_text(page, encoding="utf-8")
    sys.stdout.write(md)
    print(f"\nwrote {stem}.md, {stem}.json and {stem}.html", file=sys.stderr)

    if args.email:
        label = date.fromisoformat(month + "-01").strftime("%B %Y")
        send_email(f"SCE monthly report, {label}: {health['summary'] or 'no health report'}, "
                   f"{plural(n, 'action')}", md, to=[ALERT_TO] if args.preview else RECIPIENTS, html=page)


if __name__ == "__main__":
    main()
