#!/usr/bin/env python3
"""
Send member alert emails for newly tracked legislation.

Runs in the monthly refresh Action after the data rebuild. Reads member alert
preferences and the already-announced state from a checkout of the PRIVATE
premium repo (subscriber emails are PII and never live in the public repo),
matches newly added records in BOTH trackers against each subscriber's
watched trackers, agencies, council members, and keywords, and sends one
plain-text digest per subscriber via Gmail SMTP.

Inputs (public repo):
  civic_reference/legislation_implementation_tracker/data/laws.json
  civic_reference/legislation_implementation_tracker/data/obligations.json
  civic_reference/nyc_council_fiscal_impacts_tracker/data/fiscal_impacts.json
  civic_reference/nyc_council_legislation_trackers/data/members.json

Inputs (premium checkout, path via PREMIUM_DIR):
  civic_reference/legislation_implementation_tracker/data/alert_subscriptions.csv
      columns: email,
               trackers  (semicolon-separated: "impl;fiscal"; blank = both),
               agencies  (semicolon-separated canonical abbrevs),
               members   (semicolon-separated member slugs from members.json),
               keywords  (semicolon-separated words/phrases, matched on word
                          boundaries against titles, summaries, obligation
                          text, and fiscal narratives),
               added     (date, informational)
  civic_reference/legislation_implementation_tracker/data/alerts_state.json
      {"announced_matter_ids": [...], "announced_fiscal_ids": [...]}
      Seeded with the full backlog at launch so subscribers only hear about
      genuinely new records.

Env:
  PREMIUM_DIR   path to the premium repo checkout (required)
  GMAIL_USER    sending Gmail address (required unless DRY_RUN)
  GMAIL_APP_PASSWORD  app password (required unless DRY_RUN)
  DRY_RUN=1     print what would be sent, send nothing, do not update state

The caller commits the updated alerts_state.json in the premium checkout.

Usage:
    PREMIUM_DIR=/tmp/premium python3 pipeline/send_alerts.py
"""
from __future__ import annotations

import csv
import json
import os
import re
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
IMPL_DATA = BASE.parent / "legislation_implementation_tracker" / "data"
FISCAL_JSON = BASE.parent / "nyc_council_fiscal_impacts_tracker" / "data" / "fiscal_impacts.json"
MEMBERS_JSON = BASE / "data" / "members.json"

TRACKER_URL = "https://data.nycuriosity.com/civic_reference/legislation_implementation_tracker"
FISCAL_URL = "https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/"
ALERTS_URL = "https://premium.nycuriosity.com/civic_reference/legislation_implementation_tracker/alerts/"


def load_premium_paths() -> tuple[Path, Path]:
    premium = os.environ.get("PREMIUM_DIR")
    if not premium:
        sys.exit("PREMIUM_DIR not set")
    pdata = Path(premium) / "civic_reference" / "legislation_implementation_tracker" / "data"
    return pdata / "alert_subscriptions.csv", pdata / "alerts_state.json"


def kw_hit(keywords: set[str], blob: str) -> list[str]:
    """Keywords found in blob on word boundaries, case-insensitive."""
    hits = []
    for kw in keywords:
        if re.search(r"\b" + re.escape(kw) + r"\b", blob, re.I):
            hits.append(kw)
    return sorted(hits)


def fmt_money(n) -> str:
    if n is None:
        return "n/a"
    sign = "-" if n < 0 else ""
    a = abs(n)
    if a >= 1e9:
        return f"{sign}${a/1e9:.1f}B"
    if a >= 1e6:
        return f"{sign}${a/1e6:.1f}M"
    if a >= 1e3:
        return f"{sign}${round(a/1e3)}K"
    return f"{sign}${a:,.0f}"


def main() -> None:
    dry = os.environ.get("DRY_RUN") == "1"
    subs_path, state_path = load_premium_paths()

    laws = json.loads((IMPL_DATA / "laws.json").read_text())["laws"]
    obligations = json.loads((IMPL_DATA / "obligations.json").read_text())["obligations"]
    fiscal = json.loads(FISCAL_JSON.read_text())["records"]
    members_doc = json.loads(MEMBERS_JSON.read_text())

    state = (json.loads(state_path.read_text())
             if state_path.exists() else {})
    known_impl = set(state.get("announced_matter_ids", []))
    known_fiscal = set(state.get("announced_fiscal_ids", []))
    new_laws = [l for l in laws if l["matter_id"] not in known_impl]
    new_fiscal = [r for r in fiscal if r["matter_id"] not in known_fiscal]
    if not new_laws and not new_fiscal:
        print("Nothing newly tracked; no alerts to send.")
        return
    print(f"{len(new_laws)} new laws (implementation), "
          f"{len(new_fiscal)} new bills (fiscal).")

    new_law_ids = {l["matter_id"] for l in new_laws}
    agencies_by_law: dict[str, set] = {}
    impl_text: dict[str, list] = {}
    for o in obligations:
        mid = o["matter_id"]
        if mid not in new_law_ids:
            continue
        if o["agency_matched"]:
            agencies_by_law.setdefault(mid, set()).add(o["agency"])
        impl_text.setdefault(mid, []).append(
            f"{o.get('action_summary','')} {o.get('deliverable_type','')} "
            f"{o.get('agency_full','')} {o.get('quote','')}")
    impl_blob = {l["matter_id"]:
                 f"{l.get('title','')} {l.get('summary','')} "
                 + " ".join(impl_text.get(l["matter_id"], []))
                 for l in new_laws}

    fiscal_blob = {}
    for r in new_fiscal:
        bits = [r.get("title") or "", r.get("impact_narrative_revenue") or "",
                r.get("impact_narrative_expenditure") or ""]
        for pb in r.get("program_breakdowns") or []:
            bits.append(f"{pb.get('program') or ''} {pb.get('description') or ''}")
        fiscal_blob[r["matter_id"]] = " ".join(bits)

    # member slug -> matter_ids per tracker
    impl_by_member: dict[str, set] = {}
    fiscal_by_member: dict[str, set] = {}
    member_names: dict[str, str] = {}
    for m in members_doc["members"]:
        member_names[m["id"]] = m["full_name"]
        impl_by_member[m["id"]] = {
            x["k"].split(":", 1)[1] for x in m.get("legislation", [])
            if x["k"].startswith("impl:")}
        fiscal_by_member[m["id"]] = {
            x["k"].split(":", 1)[1] for x in m.get("legislation", [])
            if x["k"].startswith("fiscal:")}

    if not subs_path.exists():
        print("No alert_subscriptions.csv; skipping sends.")
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

        want_trackers = {t.lower() for t in splitfield("trackers")} or {"impl", "fiscal"}
        want_ag = splitfield("agencies")
        want_mem = splitfield("members")
        want_kw = {k.lower() for k in splitfield("keywords")}

        impl_matches, fiscal_matches = [], []
        if "impl" in want_trackers:
            for l in new_laws:
                mid = l["matter_id"]
                why = []
                hit_ag = sorted(want_ag & agencies_by_law.get(mid, set()))
                hit_mem = sorted(s for s in want_mem if mid in impl_by_member.get(s, set()))
                hit_kw = kw_hit(want_kw, impl_blob[mid])
                if hit_ag:
                    why.append("agencies: " + ", ".join(hit_ag))
                if hit_mem:
                    why.append("sponsors: " + ", ".join(member_names.get(s, s) for s in hit_mem))
                if hit_kw:
                    why.append("keywords: " + ", ".join(hit_kw))
                if why:
                    impl_matches.append((l, why))
        if "fiscal" in want_trackers:
            for r in new_fiscal:
                mid = r["matter_id"]
                why = []
                hit_ag = sorted(want_ag & set(r.get("agencies_abbrev") or []))
                hit_mem = sorted(s for s in want_mem if mid in fiscal_by_member.get(s, set()))
                hit_kw = kw_hit(want_kw, fiscal_blob[mid])
                if hit_ag:
                    why.append("agencies: " + ", ".join(hit_ag))
                if hit_mem:
                    why.append("sponsors: " + ", ".join(member_names.get(s, s) for s in hit_mem))
                if hit_kw:
                    why.append("keywords: " + ", ".join(hit_kw))
                if why:
                    fiscal_matches.append((r, why))

        total = len(impl_matches) + len(fiscal_matches)
        if not total:
            continue

        lines = [
            f"{total} newly tracked item{'s' if total != 1 else ''} "
            f"match{'' if total != 1 else 'es'} your alert preferences:",
            ""]
        if impl_matches:
            lines.append("NEW ENACTED LAWS (Implementation Tracker)")
            lines.append("")
            for l, why in impl_matches:
                lines += [
                    f"- {l['law_number_display'] or l['file_number']}: {l['title']}",
                    f"  Matched {'; '.join(why)}",
                    f"  Checklist: {TRACKER_URL}/law/?law={l['matter_id']}",
                    ""]
        if fiscal_matches:
            lines.append("NEW BILLS WITH FISCAL IMPACT STATEMENTS (Fiscal Impacts Tracker)")
            lines.append("")
            for r, why in fiscal_matches:
                lines += [
                    f"- {r.get('file_number')}: {r.get('title')}",
                    f"  Net fiscal impact: {fmt_money(r.get('net_fiscal_impact'))}",
                    f"  Matched {'; '.join(why)}",
                    f"  Bill on Legistar: {r.get('legistar_url')}",
                    f"  Explore: {FISCAL_URL}",
                    ""]
        lines += [
            "--",
            "You receive these alerts as an NYCuriosity member.",
            f"Update your preferences: {ALERTS_URL}",
            "To stop receiving alerts, reply to this email.",
        ]
        body = "\n".join(lines)
        subject = (f"NYCuriosity alert: {total} new item"
                   f"{'s' if total != 1 else ''} on your legislation watchlist")

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
            print(f"Sent to {email}: {total} matches")
        sent += 1

    if not dry:
        state["announced_matter_ids"] = sorted({l["matter_id"] for l in laws})
        state["announced_fiscal_ids"] = sorted({r["matter_id"] for r in fiscal})
        state_path.write_text(json.dumps(state, indent=1))
        print(f"State updated. {sent} emails sent.")


if __name__ == "__main__":
    main()
