#!/usr/bin/env python3
"""
Send member alert emails for newly tracked legislation.

Runs in the monthly refresh Action after the data rebuild. Reads member alert
preferences and the already-announced state from a checkout of the PRIVATE
premium repo (subscriber emails are PII and never live in the public repo),
matches newly added records in all three trackers (obligations, powers,
fiscal impacts) against each subscriber's
watched trackers, agencies, council members, and keywords, and sends one
plain-text digest per subscriber via Gmail SMTP.

Inputs (public repo):
  civic_reference/legislation_implementation_tracker/data/laws.json
  civic_reference/legislation_implementation_tracker/data/obligations.json
  civic_reference/legislation_implementation_tracker/data/powers.json
  civic_reference/nyc_council_fiscal_impacts_tracker/data/fiscal_impacts.json
  civic_reference/nyc_council_legislation_trackers/data/members.json

Inputs (premium checkout, path via PREMIUM_DIR):
  civic_reference/legislation_implementation_tracker/data/alert_subscriptions.csv
      columns: email,
               trackers  (semicolon-separated: "impl;powers;fiscal;deadlines";
                          blank = all four; "impl" = the obligations tracker,
                          duties only; "deadlines" = duties whose deadline is
                          coming up in the next 45 days, and reports that have
                          gone newly overdue),
               agencies  (semicolon-separated agency codes, either the
                          canonical abbrev used on the alerts page, e.g. "DOT",
                          or the agencies.json id used on the watchlist, e.g.
                          "dot"/"nyc-aging"; compared via build_agency_profiles
                          .slug() so either form matches),
               members   (semicolon-separated member slugs from members.json),
               keywords  (semicolon-separated words/phrases, matched on word
                          boundaries against titles, summaries, obligation
                          text, and fiscal narratives),
               added     (date, informational)
               districts (semicolon-separated council district numbers 1-51;
                          optional column, missing = none. Each requested
                          district gets a "District N this month" section:
                          the current member, last month's 311 volume vs its
                          prior-11-month average, laws the member had enacted
                          in the last 31 days, and a count of overdue duties
                          from laws they sponsored or co-sponsored)
  civic_reference/legislation_implementation_tracker/data/alerts_state.json
      {"announced_matter_ids": [...], "announced_fiscal_ids": [...],
       "deadline_state_seeded": bool, "announced_upcoming_ids": [...],
       "announced_overdue_ids": [...]}
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
from collections import defaultdict
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_agency_profiles import slug  # noqa: E402
BASE = HERE.parent
IMPL_DATA = BASE.parent / "legislation_implementation_tracker" / "data"
FISCAL_JSON = BASE.parent / "nyc_council_fiscal_impacts_tracker" / "data" / "fiscal_impacts.json"
MEMBERS_JSON = BASE / "data" / "members.json"
REPORT_FILINGS_JSON = IMPL_DATA / "report_filings.json"
MEMBER_CONTEXT_JSON = BASE / "data" / "member_context.json"

TRACKER_URL = "https://data.nycuriosity.com/civic_reference/legislation_implementation_tracker"
FISCAL_URL = "https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/"
ALERTS_URL = "https://premium.nycuriosity.com/civic_reference/legislation_implementation_tracker/alerts/"
MEMBER_PROFILE_URL = "https://data.nycuriosity.com/civic_reference/nyc_council_legislation_trackers/council-members/?member="
DISTRICT_BRIEF_URL = "https://premium.nycuriosity.com/civic_reference/nyc_council_legislation_trackers/district-briefs/?district="

DEADLINE_WINDOW_DAYS = 45


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


def parse_ymd(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def fmt_date(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def month_label(ym: str) -> str:
    y, mo = ym.split("-")
    return f"{date(int(y), int(mo), 1):%B %Y}"


def agency_hits(want_ag_slugs: set[str], agency_codes) -> list[str]:
    """Original-cased agency codes whose slug() matches a subscriber value,
    so "DOT" (alerts page) and "dot" (watchlist id) both match."""
    slugged = {slug(a): a for a in agency_codes}
    return sorted(orig for sl, orig in slugged.items() if sl in want_ag_slugs)


def main() -> None:
    dry = os.environ.get("DRY_RUN") == "1"
    subs_path, state_path = load_premium_paths()

    laws = json.loads((IMPL_DATA / "laws.json").read_text())["laws"]
    obligations = json.loads((IMPL_DATA / "obligations.json").read_text())["obligations"]
    powers_path = IMPL_DATA / "powers.json"
    powers = json.loads(powers_path.read_text())["powers"] if powers_path.exists() else []
    fiscal = json.loads(FISCAL_JSON.read_text())["records"]
    members_doc = json.loads(MEMBERS_JSON.read_text())
    report_filings = (json.loads(REPORT_FILINGS_JSON.read_text())["filings"]
                       if REPORT_FILINGS_JSON.exists() else {})
    member_context = (json.loads(MEMBER_CONTEXT_JSON.read_text())
                       if MEMBER_CONTEXT_JSON.exists() else {})

    state = (json.loads(state_path.read_text())
             if state_path.exists() else {})
    known_impl = set(state.get("announced_matter_ids", []))
    known_fiscal = set(state.get("announced_fiscal_ids", []))
    new_laws = [l for l in laws if l["matter_id"] not in known_impl]
    new_fiscal = [r for r in fiscal if r["matter_id"] not in known_fiscal]
    print(f"{len(new_laws)} new laws (implementation), "
          f"{len(new_fiscal)} new bills (fiscal).")

    # ── deadlines: upcoming duties and newly overdue reports ──────────────
    today = date.today()
    upcoming_cutoff = today + timedelta(days=DEADLINE_WINDOW_DAYS)

    def is_overdue(o) -> bool:
        status = (report_filings.get(o["obligation_id"]) or {}).get("status")
        dd = parse_ymd(o.get("deadline_date"))
        return status == "overdue" or (status == "never filed" and dd is not None and dd < today)

    upcoming_all, overdue_all = [], []
    for o in obligations:
        dd = parse_ymd(o.get("deadline_date"))
        if dd is not None and today <= dd <= upcoming_cutoff:
            upcoming_all.append(o)
        if is_overdue(o):
            overdue_all.append(o)

    deadline_seeded = bool(state.get("deadline_state_seeded"))
    known_upcoming = set(state.get("announced_upcoming_ids", []))
    known_overdue = set(state.get("announced_overdue_ids", []))
    if not deadline_seeded:
        known_upcoming = {o["obligation_id"] for o in upcoming_all}
        known_overdue = {o["obligation_id"] for o in overdue_all}
        new_upcoming: list = []
        new_overdue: list = []
        print(f"Deadline state seeded: {len(known_upcoming)} upcoming, "
              f"{len(known_overdue)} overdue ids stored without sending.")
    else:
        new_upcoming = [o for o in upcoming_all if o["obligation_id"] not in known_upcoming]
        new_overdue = [o for o in overdue_all if o["obligation_id"] not in known_overdue]
        print(f"{len(new_upcoming)} newly upcoming deadlines, "
              f"{len(new_overdue)} newly overdue reports.")

    new_law_ids = {l["matter_id"] for l in new_laws}
    agencies_by_law: dict[str, set] = {}
    impl_text: dict[str, list] = {}
    for o in obligations:
        mid = o["matter_id"]
        if mid not in new_law_ids:
            continue
        if o.get("restated"):     # existing code the law reprints, not new
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

    # powers arrive with their law, so a new law is the unit here too, and the
    # announced-laws state covers them (no backlog of powers added to old laws)
    power_agencies_by_law: dict[str, set] = {}
    powers_by_law: dict[str, list] = {}
    for o in powers:
        mid = o["matter_id"]
        if mid not in new_law_ids:
            continue
        if o.get("restated"):     # existing code the law reprints, not new
            continue
        if o.get("agency_matched"):
            power_agencies_by_law.setdefault(mid, set()).add(o["agency"])
        powers_by_law.setdefault(mid, []).append(o)
    power_blob = {mid: " ".join(
        f"{o.get('action_summary','')} {o.get('deliverable_type','')} {o.get('agency_full','')} {o.get('quote','')}"
        for o in rows) for mid, rows in powers_by_law.items()}

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
    members_by_district: dict[int, dict] = {}
    for m in members_doc["members"]:
        member_names[m["id"]] = m["full_name"]
        impl_by_member[m["id"]] = {
            x["k"].split(":", 1)[1] for x in m.get("legislation", [])
            if x["k"].startswith("impl:")}
        fiscal_by_member[m["id"]] = {
            x["k"].split(":", 1)[1] for x in m.get("legislation", [])
            if x["k"].startswith("fiscal:")}
        if m.get("current") and m.get("district"):
            members_by_district[m["district"]] = m

    obligations_by_matter: dict[str, list] = defaultdict(list)
    for o in obligations:
        obligations_by_matter[o["matter_id"]].append(o)
    laws_by_matter = {l["matter_id"]: l for l in laws}
    districts_311 = member_context.get("districts_311", {})

    district_cache: dict[int, list[str]] = {}

    def district_section(n: int) -> list[str]:
        if n in district_cache:
            return district_cache[n]
        member = members_by_district.get(n)
        lines = [f"District {n} this month", ""]
        if member:
            lines.append(
                f"Represented by {member['full_name']}: "
                f"{MEMBER_PROFILE_URL}{member['id']}")

        d311 = districts_311.get(str(n))
        monthly = (d311 or {}).get("monthly") or []
        if monthly:
            last = monthly[-1]["n"]
            label = month_label(monthly[-1]["month"])
            prior = [x["n"] for x in monthly[:-1]]
            if len(prior) >= 6:
                avg = sum(prior) / len(prior)
                pct = round(abs(last - avg) / avg * 100) if avg else 0
                direction = "above" if last >= avg else "below"
                lines.append(
                    f"District {n} filed {last} 311 requests in {label}, "
                    f"{pct}% {direction} its monthly average for the "
                    f"prior 11 months.")
            else:
                lines.append(f"District {n} filed {last} 311 requests in {label}.")

        if member:
            mid = member["id"]
            enacted = []
            for matter_id in impl_by_member.get(mid, set()):
                law = laws_by_matter.get(matter_id)
                if not law or not law.get("enactment_date"):
                    continue
                d = parse_ymd(law["enactment_date"])
                if d and d <= today and (today - d).days <= 31:
                    enacted.append((d, law, matter_id))
            for d, law, matter_id in sorted(enacted, key=lambda t: t[0], reverse=True):
                lines.append(
                    f"- {law.get('law_number_display') or law.get('file_number')}: "
                    f"{law['title']}, enacted {fmt_date(d)}. "
                    f"{TRACKER_URL}/law/?law={matter_id}")

            overdue_count = 0
            for matter_id in impl_by_member.get(mid, set()):
                for o in obligations_by_matter.get(matter_id, []):
                    if is_overdue(o):
                        overdue_count += 1
            if overdue_count:
                lines.append(
                    f"{overdue_count} overdue duties from laws "
                    f"{member['full_name']} sponsored or co-sponsored: "
                    f"{DISTRICT_BRIEF_URL}{n}")

        lines.append("")
        district_cache[n] = lines
        return lines

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

        want_trackers = ({t.lower() for t in splitfield("trackers")}
                          or {"impl", "powers", "fiscal", "deadlines"})
        want_ag = splitfield("agencies")
        want_ag_slugs = {slug(a) for a in want_ag}
        want_mem = splitfield("members")
        want_kw = {k.lower() for k in splitfield("keywords")}
        want_districts = []
        for x in splitfield("districts"):
            try:
                n = int(x)
            except ValueError:
                continue
            if 1 <= n <= 51:
                want_districts.append(n)

        impl_matches, power_matches, fiscal_matches = [], [], []
        if "impl" in want_trackers:
            for l in new_laws:
                mid = l["matter_id"]
                why = []
                hit_ag = agency_hits(want_ag_slugs, agencies_by_law.get(mid, set()))
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
        if "powers" in want_trackers:
            for l in new_laws:
                mid = l["matter_id"]
                if mid not in powers_by_law:
                    continue
                why = []
                hit_ag = agency_hits(want_ag_slugs, power_agencies_by_law.get(mid, set()))
                hit_mem = sorted(s for s in want_mem if mid in impl_by_member.get(s, set()))
                hit_kw = kw_hit(want_kw, f"{l.get('title','')} {power_blob[mid]}")
                if hit_ag:
                    why.append("agencies: " + ", ".join(hit_ag))
                if hit_mem:
                    why.append("sponsors: " + ", ".join(member_names.get(s, s) for s in hit_mem))
                if hit_kw:
                    why.append("keywords: " + ", ".join(hit_kw))
                if why:
                    power_matches.append((l, why))
        if "fiscal" in want_trackers:
            for r in new_fiscal:
                mid = r["matter_id"]
                why = []
                hit_ag = agency_hits(want_ag_slugs, r.get("agencies_abbrev") or [])
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

        upcoming_matches, overdue_matches = [], []
        if "deadlines" in want_trackers:
            def deadline_hit(o):
                hit_ag = agency_hits(want_ag_slugs, {o["agency"]}) if o.get("agency_matched") else []
                hit_mem = {s for s in want_mem if o["matter_id"] in impl_by_member.get(s, set())}
                blob = (f"{o.get('action_summary','')} {o.get('quote','')} "
                        f"{o.get('law_number_display','')} {o.get('agency_full','')}")
                hit_kw = kw_hit(want_kw, blob)
                return bool(hit_ag or hit_mem or hit_kw)

            upcoming_matches = [o for o in new_upcoming if deadline_hit(o)]
            overdue_matches = [o for o in new_overdue if deadline_hit(o)]

        district_lines: list[str] = []
        for n in sorted(want_districts):
            district_lines += district_section(n)

        total = len(impl_matches) + len(power_matches) + len(fiscal_matches)
        deadline_total = len(upcoming_matches) + len(overdue_matches)
        if not total and not deadline_total and not district_lines:
            continue

        lines = []
        if total:
            lines += [
                f"{total} newly tracked item{'s' if total != 1 else ''} "
                f"match{'' if total != 1 else 'es'} your alert preferences:",
                ""]
        if impl_matches:
            lines.append("NEW ENACTED LAWS: DUTIES ON AGENCIES (Obligations Tracker)")
            lines.append("")
            for l, why in impl_matches:
                lines += [
                    f"- {l['law_number_display'] or l['file_number']}: {l['title']}",
                    f"  Matched {'; '.join(why)}",
                    f"  Checklist: {TRACKER_URL}/law/?law={l['matter_id']}",
                    ""]
        if power_matches:
            lines.append("NEW ENACTED LAWS: POWERS GRANTED TO AGENCIES (Powers Tracker)")
            lines.append("")
            for l, why in power_matches:
                n = len(powers_by_law[l["matter_id"]])
                lines += [
                    f"- {l['law_number_display'] or l['file_number']}: {l['title']}",
                    f"  Grants {n} power{'s' if n != 1 else ''}; matched {'; '.join(why)}",
                    f"  Law page: {TRACKER_URL}/law/?law={l['matter_id']}",
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
        if upcoming_matches:
            lines.append("Deadlines coming up in the next 45 days")
            lines.append("")
            for o in upcoming_matches:
                dd = parse_ymd(o["deadline_date"])
                lines.append(
                    f"- {o['agency_full']}: {o['action_summary']} "
                    f"({o['law_number_display']}), due {fmt_date(dd)}")
            lines.append("")
        if overdue_matches:
            lines.append("Reports now overdue")
            lines.append("")
            for o in overdue_matches:
                dd = parse_ymd(o.get("deadline_date"))
                filing = report_filings.get(o["obligation_id"]) or {}
                status = filing.get("status")
                due_part = f", due {fmt_date(dd)}" if dd else ""
                line = (f"- {o['agency_full']}: {o['action_summary']} "
                        f"({o['law_number_display']}){due_part}"
                        f" · DORIS status: {status}")
                lines.append(line)
                if filing.get("doris_url"):
                    lines.append(f"  {filing['doris_url']}")
            lines.append("")
        lines += district_lines
        lines += [
            "--",
            "You receive these alerts as an NYCuriosity member.",
            f"Update your preferences: {ALERTS_URL}",
            "To stop receiving alerts, reply to this email.",
        ]
        body = "\n".join(lines)
        if total:
            subject = (f"NYCuriosity alert: {total} new item"
                       f"{'s' if total != 1 else ''} on your legislation watchlist")
        else:
            subject = "NYCuriosity alert: your monthly legislation update"

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
        if not deadline_seeded:
            state["deadline_state_seeded"] = True
            state["announced_upcoming_ids"] = sorted(known_upcoming)
            state["announced_overdue_ids"] = sorted(known_overdue)
        else:
            state["announced_upcoming_ids"] = sorted(
                known_upcoming | {o["obligation_id"] for o in new_upcoming})
            state["announced_overdue_ids"] = sorted(
                known_overdue | {o["obligation_id"] for o in new_overdue})
        state_path.write_text(json.dumps(state, indent=1))
        print(f"State updated. {sent} emails sent.")


if __name__ == "__main__":
    main()
