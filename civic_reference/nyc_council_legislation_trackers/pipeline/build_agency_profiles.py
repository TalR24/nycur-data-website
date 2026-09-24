#!/usr/bin/env python3
"""Build one profile per NYC agency for the Agencies view.

Joins three sources:
  1. The three legislation trackers (duties, powers, fiscal impacts, sponsors)
  2. The NYC Government Bodies Explorer's descriptive data (sector, head,
     programs, hardcoded budget/headcount estimates)
  3. Five live NYC Open Data datasets (OMB expense budget, OMB headcount,
     OPA citywide payroll, Mayor's Management Report resources, DCP capital
     projects)

All agency-name matching goes through pipeline/agency_canon.py (the same
resolver the fiscal tracker uses) plus this folder's
agency_code_overrides.json for names/codes the resolver cannot match by
itself (payroll's abbreviated names, OMB numeric codes, a few explorer
entries whose canonical form in the crosswalk isn't the abbreviation on the
explorer card).

Usage:
    python3 pipeline/build_agency_profiles.py [--refresh-gov-bodies]

--refresh-gov-bodies re-parses civic_reference/nyc-gov-bodies-explorer/index.html
and rewrites data/gov_bodies.json (a one-off extraction; the file is
committed and normally reused as-is).

Output: data/agencies.json
No Anthropic API calls. Live network calls go to data.cityofnewyork.us only;
set SOCRATA_APP_TOKEN to use an app token, otherwise runs anonymous with
polite pacing and retries.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
TRACKERS_DATA = HERE.parent / "data"
IMPL_DATA = HERE.parent.parent / "legislation_implementation_tracker" / "data"
MEMBERS_PATH = HERE.parent / "data" / "members.json"
FISCAL_DATA = HERE.parent.parent / "nyc_council_fiscal_impacts_tracker" / "data"
EXPLORER_HTML = HERE.parent.parent / "nyc-gov-bodies-explorer" / "index.html"
GOV_BODIES_PATH = TRACKERS_DATA / "gov_bodies.json"
OVERRIDES_PATH = HERE / "agency_code_overrides.json"
OUT_PATH = TRACKERS_DATA / "agencies.json"

# top-level resolver, shared with the fiscal impacts tracker
sys.path.insert(0, str(HERE.parent.parent.parent / "pipeline"))
from agency_canon import _norm, canonicalize  # noqa: E402

SOCRATA_BASE = "https://data.cityofnewyork.us/resource/{}.json"
SOCRATA_TOKEN = os.environ.get("SOCRATA_APP_TOKEN")
TODAY = date.today()

DATASETS = {
    "budget": {"id": "mwzb-yiwb", "publisher": "OMB", "label": "Expense Budget"},
    "headcount": {"id": "84ax-hg3y", "publisher": "OMB", "label": "Full-Time and FTE Headcount"},
    "payroll": {"id": "k397-673e", "publisher": "OPA", "label": "Citywide Payroll"},
    "mmr": {"id": "4qmi-txnk", "publisher": "Mayor's Office of Operations", "label": "Mayor's Management Report Agency Resources"},
    "capital": {"id": "fi59-268w", "publisher": "DCP", "label": "Capital Projects Database"},
}


# ── Socrata helpers ──────────────────────────────────────────────────────


def _headers():
    h = {"User-Agent": "nycuriosity-agency-profiles"}
    if SOCRATA_TOKEN:
        h["X-App-Token"] = SOCRATA_TOKEN
    return h


def socrata_once(dataset_id: str, params: dict) -> list[dict]:
    """A single Socrata request with retries, honoring the caller's own
    $limit (used for fixed-size queries: max(), top-N, single small groups)."""
    url = SOCRATA_BASE.format(dataset_id)
    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, headers=_headers(), timeout=90)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(1.5 * (attempt + 1))
    return []


def socrata_page(dataset_id: str, params: dict, page_limit: int = 50000) -> list[dict]:
    """Page a Socrata query with $limit/$offset until an empty page. Any
    $limit the caller passes in params is ignored: this always fetches
    everything the query matches, page by page."""
    url = SOCRATA_BASE.format(dataset_id)
    rows: list[dict] = []
    offset = 0
    while True:
        p = dict(params)
        p["$limit"] = page_limit
        p["$offset"] = offset
        batch = None
        for attempt in range(4):
            try:
                resp = requests.get(url, params=p, headers=_headers(), timeout=90)
                resp.raise_for_status()
                batch = resp.json()
                break
            except requests.RequestException:
                if attempt == 3:
                    raise
                time.sleep(1.5 * (attempt + 1))
        rows.extend(batch)
        if len(batch) < page_limit:
            break
        offset += page_limit
        time.sleep(0.15)
    return rows


# ── one-off: extract gov_bodies.json from the explorer's inline JS ──────


AGENCY_PAT = re.compile(
    r'\{\s*id:"(?P<id>[^"]+)",\s*abbr:"(?P<abbr>[^"]+)",\s*name:"(?P<name>[^"]+)",\s*'
    r'sector:"(?P<sector>[^"]+)",\s*budget_m:(?P<budget_m>\d+),\s*headcount:(?P<headcount>\d+),\s*'
    r'desc:"(?P<desc>(?:[^"\\]|\\.)*)",\s*programs:\[(?P<programs>[^\]]*)\],\s*url:"(?P<url>[^"]+)"\s*\}'
)
HEAD_PAT = re.compile(
    r'"(?P<id>[a-z0-9-]+)":\s*\{\s*title:"(?P<title>[^"]+)",\s*name:"(?P<name>[^"]+)",\s*'
    r'term:"(?P<term>[^"]+)"\s*\}'
)


def extract_gov_bodies() -> dict:
    html = EXPLORER_HTML.read_text(encoding="utf-8")
    m = re.search(r"const AGENCIES = \[(.*?)\n\];", html, re.S)
    if not m:
        raise RuntimeError("could not find AGENCIES block in explorer HTML")
    agencies = []
    for gm in AGENCY_PAT.finditer(m.group(1)):
        d = gm.groupdict()
        programs = re.findall(r'"([^"]*)"', d["programs"])
        agencies.append({
            "id": d["id"],
            "abbr": d["abbr"],
            "name": d["name"],
            "sector": d["sector"],
            "budget_m": int(d["budget_m"]),
            "headcount": int(d["headcount"]),
            "desc": d["desc"],
            "programs": programs,
            "url": d["url"],
        })

    hm = re.search(r"const AGENCY_HEADS = \{(.*?)\n\};", html, re.S)
    heads = {}
    if hm:
        for gm in HEAD_PAT.finditer(hm.group(1)):
            d = gm.groupdict()
            heads[d["id"]] = {"title": d["title"], "name": d["name"], "term": d["term"]}

    return {
        "source": "civic_reference/nyc-gov-bodies-explorer/index.html (const AGENCIES + AGENCY_HEADS)",
        "extracted_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "agencies": agencies,
        "heads": heads,
    }


# ── overrides + resolver ─────────────────────────────────────────────────


def load_overrides() -> dict:
    if OVERRIDES_PATH.exists():
        return json.loads(OVERRIDES_PATH.read_text())
    return {}


def resolve(raw: str | None, overrides: dict, extra_candidates: list[str] | None = None) -> tuple[str | None, str | None]:
    """Resolve a raw name/code/abbrev to (canon, full_name) via agency_canon,
    falling back to agency_code_overrides.json."""
    if not raw:
        return None, None
    candidates = [raw] + (extra_candidates or [])
    for cand in candidates:
        canon, full = canonicalize(cand)
        if canon:
            return canon, full
    for cand in candidates:
        ov = overrides.get(cand) or overrides.get(_norm(cand)) or overrides.get(str(cand).strip())
        if ov:
            canon, full = canonicalize(ov)
            if canon:
                return canon, full
            return ov, ov
    return None, None


def slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "agency"


# ── budget (mwzb-yiwb) ───────────────────────────────────────────────────


def fetch_budget(overrides: dict):
    ds = DATASETS["budget"]["id"]
    fy_pub = socrata_page(ds, {
        "$select": "fiscal_year, publication_date, count(*) as n",
        "$group": "fiscal_year, publication_date",
    })
    latest_pub_by_fy: dict[str, str] = {}
    for r in fy_pub:
        fy, pub = r["fiscal_year"], r["publication_date"]
        if fy not in latest_pub_by_fy or pub > latest_pub_by_fy[fy]:
            latest_pub_by_fy[fy] = pub
    keep_fys = sorted(latest_pub_by_fy, key=int, reverse=True)[:6]

    rows_fetched = 0
    code_map: dict[str, str] = {}
    unmatched_totals: defaultdict[str, float] = defaultdict(float)
    unmatched_names: dict[str, str] = {}
    per_canon: defaultdict[str, dict] = defaultdict(dict)

    for fy in keep_fys:
        pub = latest_pub_by_fy[fy]
        rows = socrata_page(ds, {
            # In the June release for fiscal year N, adopted_budget_amount is
            # FY N-1's adopted budget and financial_plan_amount is FY N's
            # (verified: FY26 release plan == FY27 release "adopted", to the
            # dollar, for every agency; independent audit Sep 24 2026).
            "$select": "agency_number, agency_name, sum(financial_plan_amount) as adopted",
            "$where": f"fiscal_year='{fy}' AND publication_date='{pub}'",
            "$group": "agency_number, agency_name",
        })
        rows_fetched += len(rows)
        fy_int = int(fy)
        for r in rows:
            code = r.get("agency_number")
            name = r.get("agency_name")
            if not code:
                continue
            canon, _full = resolve(code, overrides, [name])
            adopted = float(r.get("adopted") or 0)
            if canon:
                code_map[code] = canon
                bucket = per_canon[canon].setdefault(fy_int, {"fy": fy_int, "adopted": 0.0})
                bucket["adopted"] += adopted
            else:
                unmatched_totals[code] += adopted
                unmatched_names[code] = name

    budget_by_canon = {c: sorted(v.values(), key=lambda x: x["fy"], reverse=True) for c, v in per_canon.items()}
    unmatched = [
        {"agency_number": c, "agency_name": unmatched_names[c], "adopted_total": round(t, 2)}
        for c, t in sorted(unmatched_totals.items(), key=lambda kv: -kv[1])
    ]
    return {
        "budget_by_canon": budget_by_canon,
        "code_map": code_map,
        "rows_fetched": rows_fetched,
        "fys": keep_fys,
        "unmatched": unmatched,
    }


# ── headcount (84ax-hg3y), reuses the budget code_map ────────────────────


def fetch_headcount(overrides: dict, code_map: dict):
    ds = DATASETS["headcount"]["id"]
    fy_pub = socrata_page(ds, {
        "$select": "fyear, pub_date, count(*) as n",
        "$group": "fyear, pub_date",
    })
    latest_pub_by_fy: dict[str, str] = {}
    for r in fy_pub:
        fy, pub = r["fyear"], r["pub_date"]
        if fy not in latest_pub_by_fy or pub > latest_pub_by_fy[fy]:
            latest_pub_by_fy[fy] = pub
    # each OMB publication is a multi-year plan that includes forward years;
    # keep years up to the current city fiscal year (starts July 1) so the
    # profile never shows a projection as the latest figure. This is BUDGETED
    # headcount; actual staff counts come from payroll.
    today = date.today()
    current_fy = today.year + 1 if today.month >= 7 else today.year
    keep_fys = sorted((fy for fy in latest_pub_by_fy if int(fy) <= current_fy), key=int, reverse=True)[:6]

    rows_fetched = 0
    per_canon: defaultdict[str, dict] = defaultdict(dict)
    unmatched_totals: defaultdict[str, float] = defaultdict(float)
    unmatched_names: dict[str, str] = {}

    for fy in keep_fys:
        pub = latest_pub_by_fy[fy]
        rows = socrata_page(ds, {
            "$select": "agency, agency_name, sum(total) as total",
            "$where": f"fyear='{fy}' AND pub_date='{pub}'",
            "$group": "agency, agency_name",
        })
        rows_fetched += len(rows)
        fy_int = int(fy)
        for r in rows:
            code = r.get("agency")
            name = r.get("agency_name")
            if not code:
                continue
            total = float(r.get("total") or 0)
            canon = code_map.get(code)
            if not canon:
                canon, _full = resolve(code, overrides, [name])
            if canon:
                per_canon[canon][fy_int] = {"fy": fy_int, "total": total}
            else:
                unmatched_totals[code] += total
                unmatched_names[code] = name

    headcount_by_canon = {c: sorted(v.values(), key=lambda x: x["fy"], reverse=True) for c, v in per_canon.items()}
    unmatched = [
        {"agency": c, "agency_name": unmatched_names[c], "total": round(t)}
        for c, t in sorted(unmatched_totals.items(), key=lambda kv: -kv[1])
    ]
    return {"headcount_by_canon": headcount_by_canon, "rows_fetched": rows_fetched, "fys": keep_fys, "unmatched": unmatched}


# ── payroll (k397-673e), aggregated server-side ──────────────────────────


def fetch_payroll(overrides: dict):
    ds = DATASETS["payroll"]["id"]
    fy_rows = socrata_page(ds, {"$select": "fiscal_year, count(*) as n", "$group": "fiscal_year"})
    keep_fys = sorted((r["fiscal_year"] for r in fy_rows), key=int, reverse=True)[:6]

    rows_fetched = 0
    per_canon: defaultdict[str, dict] = defaultdict(dict)
    unmatched_totals: defaultdict[str, int] = defaultdict(int)
    unmatched_names: dict[str, str] = {}

    for fy in keep_fys:
        rows = socrata_page(ds, {
            # base_salary mixes annual, hourly and daily rates, so it is not summed
            "$select": "agency_name, count(*) as n, "
                       "sum(regular_gross_paid) as rg, sum(total_ot_paid) as ot",
            "$where": f"fiscal_year='{fy}'",
            "$group": "agency_name",
        })
        rows_fetched += len(rows)
        fy_int = int(fy)
        for r in rows:
            name = r.get("agency_name")
            n = int(float(r.get("n") or 0))
            canon, _full = resolve(name, overrides)
            entry = {
                "fy": fy_int,
                "employees": n,
                "regular_gross_paid_sum": float(r.get("rg") or 0),
                "ot_paid_sum": float(r.get("ot") or 0),
            }
            if canon:
                existing = per_canon[canon].get(fy_int)
                if existing:
                    existing["employees"] += n
                    existing["regular_gross_paid_sum"] += entry["regular_gross_paid_sum"]
                    existing["ot_paid_sum"] += entry["ot_paid_sum"]
                else:
                    per_canon[canon][fy_int] = entry
            else:
                unmatched_totals[name] += n
                unmatched_names[name] = name

    payroll_by_canon = {c: sorted(v.values(), key=lambda x: x["fy"], reverse=True) for c, v in per_canon.items()}
    unmatched = sorted(
        [{"agency_name": n, "employees": t} for n, t in unmatched_totals.items()],
        key=lambda x: -x["employees"],
    )[:15]
    return {"payroll_by_canon": payroll_by_canon, "rows_fetched": rows_fetched, "fys": keep_fys, "unmatched": unmatched}


# ── Mayor's Management Report resources (4qmi-txnk) ──────────────────────


def fetch_mmr(overrides: dict):
    ds = DATASETS["mmr"]["id"]
    latest = socrata_once(ds, {"$select": "max(reporting_fiscal_year) as m"})[0]["m"]
    rows = socrata_page(ds, {"$where": f"reporting_fiscal_year='{latest}'"})
    per_canon: defaultdict[str, list] = defaultdict(list)
    unmatched = defaultdict(int)
    for r in rows:
        canon, _full = resolve(r.get("agency"), overrides, [r.get("agency_name")])
        if not canon:
            unmatched[r.get("agency_name") or r.get("agency")] += 1
            continue
        per_canon[canon].append({
            "indicator": r.get("resource_indicators"),
            "current_fy_projected_actual": r.get("current_fy_projected_actual"),
            "current_fy_authorized_budget": r.get("current_fy_authorized_budget"),
            "next_fy_authorized_budget": r.get("next_fy_authorized_budget"),
            "trend": r.get("_5yr_trend"),
        })
    return {
        "mmr_by_canon": dict(per_canon),
        "rows_fetched": len(rows),
        "latest_fy": latest,
        "unmatched": sorted(unmatched.items(), key=lambda kv: -kv[1]),
    }


# ── capital projects (fi59-268w), reuses the budget code_map ─────────────


def fetch_capital(overrides: dict, code_map: dict):
    ds = DATASETS["capital"]["id"]
    latest = socrata_once(ds, {"$select": "max(ccpversion) as m"})[0]["m"]
    agency_rows = socrata_page(ds, {
        "$select": "magency, magencyacro, magencyname, count(*) as projects, "
                   "sum(totalplannedcommit) as total",
        "$where": f"ccpversion='{latest}'",
        "$group": "magency, magencyacro, magencyname",
    })
    rows_fetched = len(agency_rows)
    per_canon: dict[str, dict] = {}
    canon_to_magency: dict[str, str] = {}
    unmatched = []
    for r in agency_rows:
        canon, _full = resolve(r.get("magencyacro"), overrides,
                                [code_map.get(r.get("magency"), ""), r.get("magencyname"), r.get("magency")])
        if not canon:
            unmatched.append({"magency": r["magency"], "magencyacro": r["magencyacro"],
                               "magencyname": r["magencyname"], "total": float(r.get("total") or 0)})
            continue
        per_canon[canon] = {
            "version": latest,
            "projects": int(float(r.get("projects") or 0)),
            "total_planned_commit": float(r.get("total") or 0),
            "top": [],
        }
        canon_to_magency[canon] = r["magency"]

    for canon, magency in canon_to_magency.items():
        top_rows = socrata_once(ds, {
            "$select": "description, totalplannedcommit, mindate, maxdate",
            "$where": f"ccpversion='{latest}' AND magency='{magency}'",
            "$order": "totalplannedcommit DESC",
            "$limit": 5,
        })
        rows_fetched += len(top_rows)
        per_canon[canon]["top"] = [
            {
                "description": t.get("description"),
                "totalplannedcommit": float(t.get("totalplannedcommit") or 0),
                "mindate": t.get("mindate"),
                "maxdate": t.get("maxdate"),
            }
            for t in top_rows
        ]
    unmatched.sort(key=lambda x: -x["total"])
    return {"capital_by_canon": per_canon, "rows_fetched": rows_fetched, "version": latest, "unmatched": unmatched}


# ── trackers ──────────────────────────────────────────────────────────


def _norm_sponsor_name(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[.,]", "", (s or "")).strip().lower())


def load_member_impl_index() -> dict:
    """Name keys -> [(member_id, set(matter_id) of impl laws they prime-sponsored)].

    Keyed by the normalized full name and by the last name, so sponsor strings
    that carry a middle initial the roster omits ("Corey D. Johnson") still
    resolve; the shared prime-sponsored law keeps the last-name key unambiguous.
    """
    doc = json.loads(MEMBERS_PATH.read_text())
    by_name: defaultdict[str, list] = defaultdict(list)
    for m in doc["members"]:
        prime_matters = {
            leg["k"].split(":", 1)[1] for leg in m.get("legislation", [])
            if leg["k"].startswith("impl:") and leg.get("prime")
        }
        by_name[_norm_sponsor_name(m["full_name"])].append((m["id"], prime_matters))
        by_name["last:" + _norm_sponsor_name(m["last_name"])].append((m["id"], prime_matters))
    return by_name


def load_trackers(overrides: dict):
    obligations_doc = json.loads((IMPL_DATA / "obligations.json").read_text())
    powers_doc = json.loads((IMPL_DATA / "powers.json").read_text())
    fiscal_doc = json.loads((FISCAL_DATA / "fiscal_impacts.json").read_text())
    filings_path = IMPL_DATA / "report_filings.json"
    filings = json.loads(filings_path.read_text())["filings"] if filings_path.exists() else {}

    laws_by_matter = {l["matter_id"]: l for l in obligations_doc["laws"]}

    duties_by_canon: defaultdict[str, list] = defaultdict(list)
    for ob in obligations_doc["obligations"]:
        if not ob.get("agency_matched"):
            continue
        canon, _full = canonicalize(ob["agency"])
        if canon:
            duties_by_canon[canon].append(ob)

    powers_by_canon: defaultdict[str, list] = defaultdict(list)
    for pw in powers_doc["powers"]:
        if not pw.get("agency_matched"):
            continue
        canon, _full = canonicalize(pw["agency"])
        if canon:
            powers_by_canon[canon].append(pw)

    fiscal_by_canon: defaultdict[str, list] = defaultdict(list)
    fiscal_unmatched_tags = defaultdict(int)
    for rec in fiscal_doc["records"]:
        seen_canons = set()
        for abbrev in (rec.get("agencies_abbrev") or []):
            canon, _full = resolve(abbrev, overrides)
            if canon:
                if canon not in seen_canons:
                    fiscal_by_canon[canon].append(rec)
                    seen_canons.add(canon)
            else:
                fiscal_unmatched_tags[abbrev] += 1

    return {
        "laws_by_matter": laws_by_matter,
        "member_by_name": load_member_impl_index(),
        "duties_by_canon": duties_by_canon,
        "powers_by_canon": powers_by_canon,
        "fiscal_by_canon": fiscal_by_canon,
        "filings": filings,
        "obligation_matched_count": sum(1 for ob in obligations_doc["obligations"] if ob.get("agency_matched")),
        "power_matched_count": sum(1 for pw in powers_doc["powers"] if pw.get("agency_matched")),
        "fiscal_unmatched_tags": fiscal_unmatched_tags,
        "obligations_generated_at": obligations_doc.get("generated_at"),
        "powers_generated_at": powers_doc.get("generated_at"),
        "fiscal_generated_at": fiscal_doc.get("metadata", {}).get("generated_at") if isinstance(fiscal_doc.get("metadata"), dict) else None,
    }


def build_trackers_profile(canon: str, full_name: str, tr: dict) -> dict:
    duties = tr["duties_by_canon"].get(canon, [])
    powers = tr["powers_by_canon"].get(canon, [])
    fiscal = tr["fiscal_by_canon"].get(canon, [])

    laws_with_duties = len({d["matter_id"] for d in duties})
    laws_with_powers = len({p["matter_id"] for p in powers})

    open_deadlines = 0
    passed_deadlines = 0
    reports = []
    for d in duties:
        dd = d.get("deadline_date")
        if dd:
            try:
                if datetime.strptime(dd, "%Y-%m-%d").date() >= TODAY:
                    open_deadlines += 1
                else:
                    passed_deadlines += 1
            except ValueError:
                pass
        if d.get("deliverable_type") == "report":
            reports.append(d)

    report_filing: defaultdict[str, int] = defaultdict(int)
    for d in reports:
        status = tr["filings"].get(d["obligation_id"], {}).get("status")
        report_filing[status or "not tracked by DORIS"] += 1

    sponsor_counts: defaultdict[str, set] = defaultdict(set)
    for d in duties:
        if d.get("prime_sponsor"):
            sponsor_counts[d["prime_sponsor"]].add(d["matter_id"])
    for p in powers:
        if p.get("prime_sponsor"):
            sponsor_counts[p["prime_sponsor"]].add(p["matter_id"])
    member_by_name = tr["member_by_name"]
    top_sponsors = []
    for s, matter_ids in sponsor_counts.items():
        entry = {"sponsor": s, "laws": len(matter_ids)}
        candidates = [
            mid for mid, impl_matters in member_by_name.get(_norm_sponsor_name(s), [])
            if impl_matters & matter_ids
        ]
        if not candidates:
            last = re.sub(r"\s+(jr|sr|ii|iii|iv)$", "", _norm_sponsor_name(re.sub(r"\s*\(.*?\)", "", s))).split(" ")[-1]
            candidates = sorted({
                mid for key, rows in member_by_name.items()
                if key.startswith("last:") and key[5:].split(" ")[-1] == last
                for mid, impl_matters in rows if impl_matters & matter_ids
            })
        if len(candidates) == 1:
            entry["member_id"] = candidates[0]
        top_sponsors.append(entry)
    top_sponsors.sort(key=lambda x: (-x["laws"], x["sponsor"]))
    top_sponsors = top_sponsors[:5]

    matter_ids = {d["matter_id"] for d in duties} | {p["matter_id"] for p in powers}
    laws_list = []
    for mid in matter_ids:
        law = tr["laws_by_matter"].get(mid)
        if not law:
            continue
        laws_list.append({
            "matter_id": mid,
            "law": law.get("law_number_display"),
            "title": law.get("title"),
            "enacted": law.get("enactment_date"),
            "duties": sum(1 for d in duties if d["matter_id"] == mid),
            "powers": sum(1 for p in powers if p["matter_id"] == mid),
        })
    laws_list.sort(key=lambda x: (x["enacted"] or "", x["matter_id"]), reverse=True)

    fiscal_net_total = 0.0
    has_fiscal_value = False
    fiscal_list = []
    for rec in fiscal:
        net = rec.get("net_fiscal_impact")
        if net is not None:
            fiscal_net_total += net
            has_fiscal_value = True
        fiscal_list.append({
            "matter_id": rec["matter_id"],
            "bill": rec.get("legistar_file") or rec.get("file_number"),
            "title": rec.get("title"),
            "net": net,
            "fy_full_impact": rec.get("fy_full_impact"),
        })
    fiscal_list.sort(key=lambda x: ((x["net"] if x["net"] is not None else 0), x["matter_id"]))

    return {
        "duties": len(duties),
        "laws_with_duties": laws_with_duties,
        "open_deadlines": open_deadlines,
        "passed_deadlines": passed_deadlines,
        "reports": len(reports),
        "report_filing": dict(report_filing),
        "powers": len(powers),
        "laws_with_powers": laws_with_powers,
        "fiscal_bills": len(fiscal),
        "fiscal_net_total": round(fiscal_net_total, 2) if has_fiscal_value else None,
        "top_sponsors": top_sponsors,
        "laws": laws_list,
        "fiscal": fiscal_list,
    }


# ── main assembly ─────────────────────────────────────────────────────


def main():
    if "--refresh-gov-bodies" in sys.argv or not GOV_BODIES_PATH.exists():
        GOV_BODIES_PATH.write_text(json.dumps(extract_gov_bodies(), indent=2) + "\n")
        print(f"Wrote {GOV_BODIES_PATH}")

    overrides = load_overrides()
    gov_bodies = json.loads(GOV_BODIES_PATH.read_text())

    tr = load_trackers(overrides)

    print("Fetching OMB expense budget (mwzb-yiwb)...")
    budget = fetch_budget(overrides)
    print("Fetching OMB headcount (84ax-hg3y)...")
    headcount = fetch_headcount(overrides, budget["code_map"])
    print("Fetching OPA payroll (k397-673e)...")
    payroll = fetch_payroll(overrides)
    print("Fetching Mayor's Management Report resources (4qmi-txnk)...")
    mmr = fetch_mmr(overrides)
    print("Fetching DCP capital projects (fi59-268w)...")
    capital = fetch_capital(overrides, budget["code_map"])

    # explorer bodies resolved to canonical
    explorer_by_canon: dict[str, dict] = {}
    explorer_unmatched = []
    for a in gov_bodies["agencies"]:
        canon, full_name = resolve(a["abbr"], overrides, [a["name"]])
        if canon:
            explorer_by_canon[canon] = {"agency": a, "full_name": full_name}
        else:
            explorer_unmatched.append(a["id"])

    # full agency universe: explorer ∪ tracker canons with matched records
    all_canons = set(explorer_by_canon) \
        | set(tr["duties_by_canon"]) \
        | set(tr["powers_by_canon"]) \
        | set(tr["fiscal_by_canon"])

    # canonical -> crosswalk full_name lookup
    crosswalk = json.loads((IMPL_DATA / "agency_crosswalk.json").read_text())
    full_name_by_canon = {a["canonical"]: a["full_name"] for a in crosswalk["agencies"]}

    agencies = []
    for canon in sorted(all_canons):
        full_name = full_name_by_canon.get(canon, canon)
        entry = {
            "id": slug(canon),
            "name": full_name,
            "in_explorer": canon in explorer_by_canon,
        }
        if canon in explorer_by_canon:
            a = explorer_by_canon[canon]["agency"]
            head = gov_bodies["heads"].get(a["id"])
            entry.update({
                "sector": a["sector"],
                "description": a["desc"],
                "programs": a["programs"],
                "url": a["url"],
                "head": head,
                "explorer_budget_m": a["budget_m"],
                "explorer_headcount": a["headcount"],
            })
        entry["trackers"] = build_trackers_profile(canon, full_name, tr)
        entry["budget"] = budget["budget_by_canon"].get(canon, [])
        entry["headcount"] = headcount["headcount_by_canon"].get(canon, [])
        entry["payroll"] = payroll["payroll_by_canon"].get(canon, [])
        entry["mmr"] = mmr["mmr_by_canon"].get(canon, [])
        entry["capital"] = capital["capital_by_canon"].get(canon, {"version": capital["version"], "projects": 0, "total_planned_commit": 0.0, "top": []})
        agencies.append(entry)

    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    out = {
        "generated_at": now,
        "sources": {
            "obligations": {"path": "legislation_implementation_tracker/data/obligations.json", "generated_at": tr["obligations_generated_at"]},
            "powers": {"path": "legislation_implementation_tracker/data/powers.json", "generated_at": tr["powers_generated_at"]},
            "fiscal_impacts": {"path": "nyc_council_fiscal_impacts_tracker/data/fiscal_impacts.json", "generated_at": tr["fiscal_generated_at"]},
            "gov_bodies_explorer": {"path": "nyc-gov-bodies-explorer/index.html", "rows_or_groups_fetched": len(gov_bodies["agencies"]), "fetched_at": gov_bodies["extracted_at"]},
            "budget": {"id": DATASETS["budget"]["id"], "publisher": DATASETS["budget"]["publisher"], "rows_or_groups_fetched": budget["rows_fetched"], "fetched_at": now, "latest_fiscal_year": budget["fys"][0] if budget["fys"] else None},
            "headcount": {"id": DATASETS["headcount"]["id"], "publisher": DATASETS["headcount"]["publisher"], "rows_or_groups_fetched": headcount["rows_fetched"], "fetched_at": now, "latest_fiscal_year": headcount["fys"][0] if headcount["fys"] else None},
            "payroll": {"id": DATASETS["payroll"]["id"], "publisher": DATASETS["payroll"]["publisher"], "rows_or_groups_fetched": payroll["rows_fetched"], "fetched_at": now, "latest_fiscal_year": payroll["fys"][0] if payroll["fys"] else None},
            "mmr": {"id": DATASETS["mmr"]["id"], "publisher": DATASETS["mmr"]["publisher"], "rows_or_groups_fetched": mmr["rows_fetched"], "fetched_at": now, "latest_fiscal_year": mmr["latest_fy"]},
            "capital": {"id": DATASETS["capital"]["id"], "publisher": DATASETS["capital"]["publisher"], "rows_or_groups_fetched": capital["rows_fetched"], "fetched_at": now, "latest_fiscal_year": capital["version"]},
        },
        "coverage": {
            "explorer_matched": len(explorer_by_canon),
            "explorer_total": len(gov_bodies["agencies"]),
            "explorer_unmatched_ids": explorer_unmatched,
            "budget_unmatched": budget["unmatched"],
            "headcount_unmatched": headcount["unmatched"],
            "payroll_unmatched_top15": payroll["unmatched"],
            "capital_unmatched": capital["unmatched"],
            "mmr_unmatched": mmr["unmatched"],
            "fiscal_tag_unmatched": sorted(tr["fiscal_unmatched_tags"].items(), key=lambda kv: -kv[1]),
            "obligation_matched_count": tr["obligation_matched_count"],
            "power_matched_count": tr["power_matched_count"],
        },
        "agencies": agencies,
    }
    OUT_PATH.write_text(json.dumps(out, indent=2))
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size / 1024:.0f} KB, {len(agencies)} agencies)")


if __name__ == "__main__":
    main()
