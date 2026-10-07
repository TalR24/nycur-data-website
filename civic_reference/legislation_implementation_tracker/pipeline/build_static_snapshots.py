#!/usr/bin/env python3
"""
Pre-render static snapshots for the Obligations Tracker pages and the umbrella
hub pages (agencies, council members), so crawlers that do not run JavaScript
see real content. Each block mirrors the markup the page's own JS builds from
the same JSON, sits between <!-- static:<id>:start/end --> markers inside the
container the JS fills, and is replaced by the JS on load.

    python3 civic_reference/legislation_implementation_tracker/pipeline/build_static_snapshots.py

Paywall rule: headline counts and top-10 rows only. No download links.
Idempotent. See seo/static_snapshot.py.
"""

import json
import sys
from datetime import date
from urllib.parse import quote
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent          # legislation_implementation_tracker/
HUB = HERE.parent / "nyc_council_legislation_trackers"
sys.path.insert(0, str(HERE.parent.parent / "seo"))
from static_snapshot import inject  # noqa: E402

TOP_N = 10
changed = []


def esc(s):
    return escape("" if s is None else str(s), quote=True)


def num(n):
    return f"{n:,}"


def put(path, block_id, html):
    if inject(path, block_id, html):
        changed.append(f"{Path(path).relative_to(HERE.parent.parent)}:{block_id}")


def count_by(rows, fn):
    out = {}
    for r in rows:
        k = fn(r)
        if k:
            out[k] = out.get(k, 0) + 1
    return out


def top_n(counts, n):
    # JS sorts by count desc with a stable sort over insertion order
    return sorted(counts.items(), key=lambda kv: -kv[1])[:n]


def hbars(pairs, titles=None):
    titles = titles or {}
    if not pairs:
        return '<p class="loading-note">No data.</p>'
    mx = max(v for _, v in pairs)
    return "".join(
        '<div class="c-bar-row"><span class="c-bar-label" title="%s">%s</span>'
        '<div class="c-bar-track"><div class="c-bar-fill" data-w="%s" style="width:%s%%"></div></div>'
        '<span class="c-bar-value">%s</span></div>' % (esc(titles.get(k, k)), esc(k), round(v / mx * 100, 1), round(v / mx * 100, 1), num(v))
        for k, v in pairs)


def columns(pairs):
    mx = max(v for _, v in pairs)
    h = '<div class="col-chart">'
    for k, v in pairs:
        h += ('<div class="col-item"><span class="col-num">%s</span>'
              '<div class="col-bar" data-h="%s" style="height:%s%%"></div>'
              '<span class="col-label">%s</span></div>' % (num(v), round(v / mx * 100, 1), round(max(2, v / mx * 100), 1), esc(k)))
    return h + "</div>"


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- tracker home
def build_home(obl):
    laws, obs = obl.get("laws", []), obl.get("obligations", [])
    p = HERE / "index.html"
    put(p, "home-laws", num(len(laws)))
    put(p, "home-obs", num(len(obs)))
    matched = [o for o in obs if o.get("agency_matched")]
    put(p, "home-agencies", num(len({o["agency"] for o in matched})))
    by_agency = count_by(matched, lambda o: o["agency"])
    top10 = sum(v for _, v in top_n(by_agency, 10))
    pct = round(top10 / len(matched) * 100) if matched else 0
    put(p, "home-title", esc("The top 10 agencies carry %d%% of the Council's duties matched to an agency" % pct))
    put(p, "home-agency", hbars(top_n(by_agency, 12)))
    put(p, "home-type", hbars(top_n(count_by(obs, lambda o: o.get("deliverable_type")), 13)))
    by_year = count_by([o for o in obs if o.get("enactment_date")], lambda o: o["enactment_date"][:4])
    put(p, "home-year", columns([("'" + k[2:], by_year[k]) for k in sorted(by_year)]))
    put(p, "home-sponsor", hbars(top_n(count_by([o for o in obs if o.get("prime_sponsor")], lambda o: o["prime_sponsor"]), 10)))


# ------------------------------------------------------------- agency workload
BUCKETS = [  # mirror of BUCKETS in agency-workload/index.html
    ("report", "Reports", "#C84609", ["report"]),
    ("rule", "Rulemaking", "#89C4E1", ["rulemaking"]),
    ("program", "Programs & services", "#226287", ["program or service"]),
    ("outreach", "Outreach & education", "#6B5B4A", ["outreach or education"]),
    ("other", "Everything else", "#EDC3A5", None),
]


def bucket_of(t):
    for key, _l, _c, match in BUCKETS:
        if match and t in match:
            return key
    return "other"


def stacked_bars(ag, segs_def):
    """Top-10 stacked agency bars, mirror of the c-bar-row markup both stacked-bar pages build."""
    ranked = sorted(ag.items(), key=lambda kv: -kv[1]["total"])
    mx = ranked[0][1]["total"]
    h = ""
    for name, r in ranked[:TOP_N]:
        segs = "".join(
            '<div class="bar-seg" data-seg="%s: %d" style="background:%s;width:%s%%"></div>'
            % (esc(l), r["segs"][k], c, round(r["segs"][k] / mx * 100, 2))
            for k, l, c in segs_def if r["segs"].get(k))
        h += ('<div class="c-bar-row" data-full="%s" data-total="%d"><span class="c-bar-label">%s</span>'
              '<div class="c-bar-track">%s</div><span class="c-bar-value">%s</span></div>'
              % (esc(r["full"] or name), r["total"], esc(name), segs, num(r["total"])))
    return h


def build_workload(obl):
    obs = obl.get("obligations", [])
    p = HERE / "agency-workload" / "index.html"
    ag = {}
    laws = set()
    recurring = 0
    for o in obs:
        laws.add(o.get("matter_id"))
        if o.get("recurrence") not in ("one-time", "as-needed"):
            recurring += 1
        if not o.get("agency_matched"):
            continue
        a = ag.setdefault(o["agency"], {"total": 0, "segs": {}, "full": o.get("agency_full")})
        a["total"] += 1
        k = bucket_of(o.get("deliverable_type"))
        a["segs"][k] = a["segs"].get(k, 0) + 1
    put(p, "aw-obs", num(len(obs)))
    put(p, "aw-agencies", num(len(ag)))
    put(p, "aw-laws", num(len(laws)))
    put(p, "aw-recurring", num(recurring))
    put(p, "aw-legend", "".join(
        '<li class="c-legend-item"><span class="sw" style="background:%s"></span>%s</li>' % (c, esc(l))
        for _k, l, c, _m in BUCKETS))
    put(p, "aw-chart", stacked_bars(ag, [(k, l, c) for k, l, c, _m in BUCKETS]))


# ----------------------------------------------------------- deadline timeline
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]


def fmt_date(iso):
    y, m, d = iso.split("-")
    return "%s %d, %s" % (MONTHS[int(m) - 1][:3], int(d), y)


def tl_card(o):
    return ('<div class="tl-card" tabindex="0"><div class="tl-top">'
            + ('<span class="tl-date">%s</span>' % fmt_date(o["deadline_date"]) if o.get("deadline_date") else "")
            + '<span class="agency-badge%s" title="%s">%s</span><span class="tl-law">%s</span></div>'
            % (" unspec" if o.get("agency") == "Unspecified" else "", esc(o.get("agency_full")), esc(o.get("agency")),
               esc(o.get("law_number_display") or o.get("file_number")))
            + '<div class="tl-action">%s</div><div class="tl-detail">' % esc(o.get("action_summary"))
            + ('<div class="tl-quote">\u201c%s\u201d</div>' % esc(o["quote"]) if o.get("quote") else "")
            + '<div class="tl-meta">%s%s</div>' % (esc(o.get("citation") or ""),
                                                  " \u00b7 " + esc(o["deadline_text"]) if o.get("deadline_text") else "")
            + '<div class="tl-links"><a href="../law/?law=%s">Full law checklist \u2192</a>'
              '<a href="%s" target="_blank" rel="noopener">View on Legistar \u2197</a></div></div></div>'
            % (quote(str(o["matter_id"]), safe=""), esc(o.get("legistar_url"))))


def build_timeline(obl):
    obs = obl.get("obligations", [])
    p = HERE / "deadline-timeline" / "index.html"
    today = date.today().isoformat()  # date-dependent: rerun on each data refresh
    upcoming, overdue, recurring = [], [], []
    for o in obs:
        if o.get("recurrence") != "one-time":
            recurring.append(o)
        elif o.get("deadline_date"):
            (overdue if o["deadline_date"] < today else upcoming).append(o)
    put(p, "dt-cnt-upcoming", "(%d)" % len(upcoming))
    put(p, "dt-cnt-overdue", "(%d)" % len(overdue))
    put(p, "dt-cnt-recurring", "(%d)" % len(recurring))
    upcoming.sort(key=lambda o: o["deadline_date"])
    h, last = '<div class="timeline">', None
    for o in upcoming[:TOP_N]:
        k = o["deadline_date"][:7]
        if k != last:
            if last:
                h += "</div>"
            h += '<div class="month-group"><div class="month-label">%s %s</div>' % (MONTHS[int(k[5:7]) - 1], k[:4])
            last = k
        h += tl_card(o)
    h += "</div></div>" if last else "</div>"
    put(p, "dt-content", h if last else '<p class="empty-note">No upcoming dated deadlines match these filters.</p>')


# ------------------------------------------------------------------ methodology
def build_methodology():
    d = load(HERE / "data" / "summary.json")
    p = HERE / "methodology" / "index.html"
    st = d.get("doris_status_counts") or {}
    prot = sum(v for k, v in (d.get("model_counts") or {}).items() if "protected" in k)
    when = date.fromisoformat(d["generated_at"][:10])
    vals = {
        "protected": num(prot), "duties": num(d["duties"]), "quote-n": num(d["duty_quotes_verified"]),
        "quote-pct": "%.1f%%" % (100 * d["duty_quotes_verified"] / d["duties"]),
        "as-of": "%s %d, %d" % (MONTHS[when.month - 1], when.day, when.year),
        "agency-pct": "%.1f%%" % (100 * d["records_agency_matched"] / d["records_total"]),
        "reprinted": num(d["reprinted_existing_code"]),
        "matched": num(d["doris_matched"]), "never": num(st.get("never filed", 0)),
        "overdue": num(st.get("overdue", 0)), "current": num(st.get("current", 0)),
        "unknown": num(st.get("unknown", 0)),
    }
    for k, v in vals.items():
        put(p, "meth-" + k, v)


# ----------------------------------------------------------- obligations table
def agency_display(o):
    if o.get("agency") == "Unspecified":
        return "Unspecified"
    if o.get("agency_matched"):
        full = o.get("agency_full") or o["agency"]
        return full[len("New York City "):] if full.startswith("New York City ") else full
    return o.get("agency")


def base_row(o):
    """Open <tr> plus the Law..Enacted cells shared by the obligations and powers tables."""
    h = ('<tr class="data-row%s" data-id="%s"><td class="law-cell">%s%s<span class="file-no">%s</span></td>'
         % (" existing-code-row" if o.get("restated") else "", esc(o.get("obligation_id")),
            esc(o.get("law_number_display") or o.get("file_number")),
            ' <span class="existing-code-tag">existing code</span>' if o.get("restated") else "",
            esc(o.get("file_number"))))
    title = (o["agency"] + " \u00b7 " + (o.get("agency_full") or "")) if o.get("agency_matched") else o.get("agency_full")
    h += ('<td class="agency-cell%s" title="%s">%s%s</td>'
          % (" unspec" if o.get("agency") == "Unspecified" else "", esc(title), esc(agency_display(o)),
             '<span class="agency-unit">%s</span>' % esc(o["agency_unit"]) if o.get("agency_unit") else ""))
    h += '<td class="action-cell">%s</td><td><span class="type-badge">%s</span></td>' % (
        esc(o.get("action_summary")), esc(o.get("deliverable_type")))
    h += '<td class="meta-cell" title="%s">%s</td>' % (
        esc(o.get("committee") or ""), esc((o.get("committee") or "\u2014").removeprefix("Committee on ")))
    h += '<td class="meta-cell">%s</td>' % esc(o.get("prime_sponsor") or "\u2014")
    h += '<td class="deadline-cell">%s</td>' % (fmt_date(o["enactment_date"]) if o.get("enactment_date") else "\u2014")
    return h


def build_obligations_table(obl):
    obs = obl.get("obligations", [])
    p = HERE / "obligations-table" / "index.html"
    today = date.today().isoformat()
    ag = {o["agency"] for o in obs if o.get("agency_matched")}
    laws = {o.get("matter_id") for o in obs}
    put(p, "ot-agencies", num(len(ag)))
    put(p, "ot-laws", num(len(laws)))
    put(p, "ot-dated", num(sum(1 for o in obs if o.get("deadline_date"))))
    put(p, "ot-recurring", num(sum(1 for o in obs if o.get("recurrence") not in ("one-time", "as-needed"))))
    put(p, "ot-count", "Showing <strong>1\u2013%d</strong> of %s matching obligations" % (TOP_N, num(len(obs))))
    rows = sorted(obs, key=lambda o: o.get("deadline_date") or "9999-12-31")  # default sort: deadline
    h = ""
    for o in rows[:TOP_N]:
        dl_class = ""
        if o.get("deadline_date") and o.get("recurrence") == "one-time":
            dl_class = "overdue" if o["deadline_date"] < today else "upcoming"
        dl_text = fmt_date(o["deadline_date"]) if o.get("deadline_date") else ("\u2014" if o.get("deadline_kind") == "none" else "not dated")
        h += base_row(o)
        h += '<td class="deadline-cell %s">%s</td><td class="recur-cell">%s</td></tr>' % (dl_class, dl_text, esc(o.get("recurrence")))
    put(p, "ot-rows", h)
    notes = ["Duties a law only reprints are listed under the law that created them, or marked as existing code."]
    tracked = [o for o in obs if o.get("filing")]
    if tracked:
        miss = sum(1 for o in tracked if o["filing"].get("status") in ("never filed", "overdue"))
        notes.append(
            "%s are reports DORIS tracks by filing date, and <strong>%s</strong> of those are overdue or have never been filed. "
            "Filing status follows <a href=\"https://joshgreenman1973.github.io/nyc-overdue-reports/\" target=\"_blank\" rel=\"noopener\">Josh Greenman's NYC Overdue Reports</a> "
            "(<a href=\"https://github.com/joshgreenman1973/nyc-overdue-reports\" target=\"_blank\" rel=\"noopener\">method</a>)."
            % (num(len(tracked)), num(miss)))
    put(p, "ot-notes", " ".join(notes) + ' <a href="../methodology/">How this is measured</a>')


# ---------------------------------------------------------------- powers table
def build_powers_table(pw):
    pows = pw.get("powers", [])
    p = HERE / "powers-table" / "index.html"
    put(p, "pt-agencies", num(len({o["agency"] for o in pows if o.get("agency_matched")})))
    put(p, "pt-laws", num(len({o.get("matter_id") for o in pows})))
    put(p, "pt-count", "Showing <strong>1\u2013%d</strong> of %s matching powers" % (TOP_N, num(len(pows))))
    rows = sorted(pows, key=lambda o: o.get("enactment_date") or "", reverse=True)  # default sort: newest enacted
    put(p, "pt-rows", "".join(base_row(o) + "</tr>" for o in rows[:TOP_N]))
    put(p, "pt-notes", "Powers a law only reprints are listed under the law that created them, or marked as existing code."
                       ' <a href="../methodology/">How this is measured</a>')


# ---------------------------------------------------------------- powers home
def build_powers_home(pw):
    pows = pw.get("powers", [])
    total = len(pows)
    p = HERE / "powers" / "index.html"
    put(p, "pw-powers", num(total))
    put(p, "pw-laws", num(len({o["matter_id"] for o in pows if o.get("matter_id")})))
    put(p, "pw-agencies", num(len({o["agency"] for o in pows if o.get("agency_matched")})))
    put(p, "pw-rulemaking", num(sum(1 for o in pows if o.get("deliverable_type") == "rulemaking")))
    by_ag, full = {}, {}
    for o in pows:
        if o.get("agency_matched"):
            by_ag[o["agency"]] = by_ag.get(o["agency"], 0) + 1
            full[o["agency"]] = o.get("agency_full") or o["agency"]
    ranked = top_n(by_ag, 10)
    put(p, "pw-agency", hbars(ranked, full))
    if ranked:
        put(p, "pw-title-agency", esc("%s holds %s of the %s powers, more than any other agency"
                                      % (full[ranked[0][0]], num(ranked[0][1]), num(total))))
    types = top_n(count_by(pows, lambda o: o.get("deliverable_type")), 10)
    put(p, "pw-type", hbars(types))
    if types:
        put(p, "pw-title-type", esc("%s is the most common power laws grant: %s of %s"
                                    % (types[0][0][:1].upper() + types[0][0][1:], num(types[0][1]), num(total))))
    by_year = count_by([o for o in pows if o.get("enactment_date")], lambda o: o["enactment_date"][:4])
    if by_year:
        put(p, "pw-year", columns([("'" + k[2:], by_year[k]) for k in sorted(by_year)]))
        top_year = max(sorted(by_year), key=lambda k: by_year[k])
        put(p, "pw-title-year", esc("%s laws granted the most powers: %s" % (top_year, num(by_year[top_year]))))
    spons = top_n(count_by([o for o in pows if o.get("prime_sponsor")], lambda o: o["prime_sponsor"]), 10)
    put(p, "pw-sponsor", hbars(spons))
    if spons:
        put(p, "pw-title-sponsor", esc("%s wrote the laws behind %s powers, more than any other council member"
                                       % (spons[0][0], num(spons[0][1]))))


# ------------------------------------------------------------- agency powers
POWER_TYPES = [  # mirror of TYPES in powers/agency-powers/index.html
    ("rulemaking", "Rulemaking", "var(--b-lightblue)"),
    ("enforcement or inspection", "Enforcement or inspection", "var(--b-topic-cb-ink)"),
    ("designation or staffing", "Designation or staffing", "var(--b-topic-govtech-ink)"),
    ("program or service", "Program or service", "var(--c-good)"),
    ("monitoring or testing", "Monitoring or testing", "var(--b-ink-3)"),
    ("notice or posting", "Notice or posting", "var(--b-tangerine)"),
    ("database or data publication", "Database or data publication", "var(--b-ink-2)"),
    ("outreach or education", "Outreach or education", "var(--b-ink-4)"),
    ("report", "Report", "var(--b-tangerine-deep)"),
    ("study or audit", "Study or audit", "var(--b-fuchsia)"),
    ("other", "Everything else", "var(--blue-mid)"),
]


def build_agency_powers(pw):
    pows = pw.get("powers", [])
    p = HERE / "powers" / "agency-powers" / "index.html"
    keys = {k for k, _l, _c in POWER_TYPES}
    ag, laws, unmatched = {}, set(), 0
    for o in pows:
        laws.add(o.get("matter_id"))
        if not o.get("agency_matched"):
            unmatched += 1
            continue
        a = ag.setdefault(o["agency"], {"total": 0, "segs": {}, "full": o.get("agency_full")})
        a["total"] += 1
        k = o.get("deliverable_type") if o.get("deliverable_type") in keys else "other"
        a["segs"][k] = a["segs"].get(k, 0) + 1
    put(p, "ap-powers", num(len(pows)))
    put(p, "ap-agencies", num(len(ag)))
    put(p, "ap-laws", num(len(laws)))
    matched = sum(a["total"] for a in ag.values())
    top10 = sum(a["total"] for _n, a in sorted(ag.items(), key=lambda kv: -kv[1]["total"])[:10])
    put(p, "ap-title", esc("The top 10 agencies hold %d%% of the %s powers matched to an agency"
                           % (round(top10 / matched * 100), num(matched))))
    put(p, "ap-legend", "".join('<li class="c-legend-item"><span class="sw" style="background:%s"></span>%s</li>'
                                % (c, esc(l)) for _k, l, c in POWER_TYPES))
    put(p, "ap-chart", stacked_bars(ag, POWER_TYPES))
    put(p, "ap-foot", '<span>Created by Tal Roded \u00b7 NYCuriosity \u00b7 Source: Author\'s analysis of enacted local law text from '
        '<a href="https://legistar.council.nyc.gov" target="_blank" rel="noopener">NYC Legistar</a>'
        + ("." + " %s powers in this filter could not be matched to an agency and are left out of the bars." % num(unmatched)
           if unmatched else "") + "</span>")


# ------------------------------------------------------------------- hub home
def build_hub_home(obl, pw):
    p = HUB / "index.html"
    obs, pows = obl.get("obligations", []), pw.get("powers", [])
    put(p, "hub-obl-duties", num(obl.get("obligation_count") or len(obs)))
    put(p, "hub-obl-laws", num(sum(1 for l in obl.get("laws", []) if (l.get("obligation_count") or 0) > 0)))
    put(p, "hub-obl-agencies", num(len({o["agency"] for o in obs if o.get("agency_matched")})))
    put(p, "hub-pow-powers", num(pw.get("power_count") or len(pows)))
    put(p, "hub-pow-laws", num(len({o["matter_id"] for o in pows if o.get("matter_id")})))
    put(p, "hub-pow-agencies", num(len({o["agency"] for o in pows if o.get("agency_matched")})))
    put(p, "hub-members", num(len(load(HUB / "data" / "members.json").get("members", []))))
    put(p, "hub-agencies", num(len(load(HUB / "data" / "agencies.json")["agencies"])))
    fis = load(HERE.parent / "nyc_council_fiscal_impacts_tracker" / "data" / "fiscal_impacts.json")  # read only
    recs = fis.get("records", [])
    n = (fis.get("metadata") or {}).get("total_records") or len(recs)
    put(p, "hub-fiscal-bills", num(n))
    put(p, "hub-fiscal-agencies", num(len({a for r in recs for a in (r.get("agencies_abbrev") or [])})))
    put(p, "hub-fiscal-sponsors", num(len({r["prime_sponsor"] for r in recs if r.get("prime_sponsor")})))


# ------------------------------------------------------------ hub: agencies
SECTOR_LIGHT = {  # mirrors SECTOR_LIGHT / SECTOR_TEXT in agencies/index.html
    "Public Safety": "#F2D7C4", "Education": "#EFF7FA", "Health & Human Services": "#DCEDF4",
    "Housing & Development": "#FDF3D8", "Transportation & Infrastructure": "#FCF1EB",
    "Finance & Administration": "#F6F5F4", "Parks & Culture": "#DCEDF4",
    "Economic Development": "#F9EEC8", "Elected & Legal": "#F6E7DA", "Other offices and boards": "#F6F5F4"}
SECTOR_TEXT = {
    "Public Safety": "#692807", "Education": "#1B5670", "Health & Human Services": "#133F53",
    "Housing & Development": "#773903", "Transportation & Infrastructure": "#8A360B",
    "Finance & Administration": "#4A3B2C", "Parks & Culture": "#133F53",
    "Economic Development": "#78320F", "Elected & Legal": "#7F3E1D", "Other offices and boards": "#4A3B2C"}
OTHER_SECTOR = "Other offices and boards"
PUBLIC_BODY_DESC = {
    "Citywide (all agencies)": "Duties and powers a law gives every city agency, or every agency of a kind.",
    "Borough Presidents": "Duties and powers laws give the five borough presidents.",
    "NYCC": "Duties and powers laws give the City Council and its Speaker."}


def fmt_money(n):
    if n is None:
        return "\u2014"
    sign, a = ("-" if n < 0 else ""), abs(n)
    if a >= 1e9:
        return sign + "$" + ("%.1f" % (a / 1e9)).removesuffix(".0") + "B"
    if a >= 1e6:
        return sign + "$" + ("%.1f" % (a / 1e6)).removesuffix(".0") + "M"
    if a >= 1e3:
        return sign + "$" + str(int(a / 1e3 + 0.5)) + "K"
    return sign + "$" + num(int(a + 0.5))


def agency_card(a):
    sector = a.get("sector") or OTHER_SECTOR
    tr = a.get("trackers") or {}
    duties, powers = tr.get("duties") or 0, tr.get("powers") or 0
    b = a["budget"][0]["adopted"] if a.get("budget") else 0
    desc = PUBLIC_BODY_DESC.get("NYCC" if a["id"] == "nycc" else a["name"])
    h = '<a class="agency-card%s" href="?agency=%s"><div class="ac-top"><span class="ac-name">%s</span></div>' % (
        " public-body" if a.get("public_body") else "", quote(a["id"], safe="-_.!~*'()"), esc(a["name"]))
    if a.get("public_body"):
        h += '<span class="public-body-pill">Public body, not a city agency</span>'
    if desc:
        h += '<span class="public-body-desc">%s</span>' % esc(desc)
    if a.get("head"):
        h += '<span class="ac-head">Led by %s %s</span>' % (esc(a["head"]["title"]), esc(a["head"]["name"]))
    if not a.get("public_body"):
        h += '<span class="sector-badge" style="background:%s;color:%s">%s</span>' % (
            SECTOR_LIGHT.get(sector, "#F2EBE1"), SECTOR_TEXT.get(sector, "#1A1208"), esc(sector))
    h += ('<div class="ac-nums"><div class="ac-num"><span class="ac-num-val">%d</span><span class="ac-num-label">%s</span></div>'
          '<div class="ac-num"><span class="ac-num-val">%d</span><span class="ac-num-label">%s</span></div>'
          '<div class="ac-num"><span class="ac-num-val">%s</span><span class="ac-num-label">budget</span></div></div></a>'
          % (duties, "duty" if duties == 1 else "duties", powers, "power" if powers == 1 else "powers",
             fmt_money(b) if b else "\u2014"))
    return h


def build_hub_agencies():
    d = load(HUB / "data" / "agencies.json")
    ags = d["agencies"]
    p = HUB / "agencies" / "index.html"
    duties = lambda a: (a.get("trackers") or {}).get("duties") or 0
    total_d = sum(duties(a) for a in ags)
    total_p = sum((a.get("trackers") or {}).get("powers") or 0 for a in ags)
    total_b = sum(a["budget"][0]["adopted"] if a.get("budget") else 0 for a in ags)
    cov = d.get("coverage") or {}
    note = ""
    if cov.get("obligations_no_agency") is not None:
        note = ("%s of %s duties and %s of %s powers in the trackers name no identifiable agency and are not counted here."
                % (cov["obligations_no_agency"], num(cov.get("obligation_total") or 0),
                   cov["powers_no_agency"], num(cov.get("power_total") or 0)))
    h = ('<div class="stat-pills">'
         '<div class="stat-pill"><span class="sp-num">%d</span><span class="sp-label">Agencies and public bodies</span></div>'
         '<div class="stat-pill"><span class="sp-num">%s</span><span class="sp-label">Duties across them</span></div>'
         '<div class="stat-pill"><span class="sp-num">%s</span><span class="sp-label">Powers</span></div>'
         '<div class="stat-pill"><span class="sp-num">%s</span><span class="sp-label">Combined adopted budget, latest fiscal year</span></div></div>'
         '<p class="section-note">%s</p>' % (len(ags), num(total_d), num(total_p), fmt_money(total_b), esc(note)))
    h += '<p class="result-count" id="resultCount">Showing <strong>%d</strong> of %d agencies</p>' % (TOP_N, len(ags))
    h += '<div class="agency-grid" id="agencyGrid">%s</div>' % "".join(
        agency_card(a) for a in sorted(ags, key=duties, reverse=True)[:TOP_N])
    put(p, "agencies-directory", h)


# ------------------------------------------------------- hub: council members
def party_class(p):
    p = (p or "").lower()
    return "dem" if p.startswith("dem") else "rep" if p.startswith("rep") else "oth"


def party_short(p):
    pl = (p or "").lower()
    return "D" if pl.startswith("dem") else "R" if pl.startswith("rep") else (p[:3] if p else "?")


def member_card(m):
    s = m["stats"]
    sess = m.get("sessions") or []
    span = (sess[0][:4] + "\u2013" + ("now" if m.get("current") else str(m.get("end_year") or ""))) if sess else ""
    return ('<a class="member-card" href="?member=%s"><div class="mc-top"><span class="mc-name">%s</span>'
            '<span class="party-badge %s">%s</span>%s</div><div class="mc-sub">District %s \u00b7 %s \u00b7 %s</div>'
            '<div class="mc-stats"><span class="mc-stat"><span class="n">%s</span><span class="l">tracked bills</span></span>'
            '<span class="mc-stat"><span class="n">%s</span><span class="l">obligations</span></span>'
            '<span class="mc-stat"><span class="n">%s</span><span class="l">net fiscal impact</span></span></div></a>'
            % (quote(str(m["id"]), safe="-_.!~*'()"), esc(m["full_name"]), party_class(m.get("party")),
               esc(party_short(m.get("party"))), '<span class="current-badge">Current</span>' if m.get("current") else "",
               m.get("district") or "\u2014", esc(m.get("borough") or ""), esc(span),
               s["legislation_total"], s["obligations_sum"], fmt_money(s["fiscal_net_sum"])))


def build_hub_members():
    ms = load(HUB / "data" / "members.json")["members"]
    p = HUB / "council-members" / "index.html"
    rows = sorted(ms, key=lambda m: (not m.get("current"), m.get("district") or 99, m["full_name"]))  # default: by district
    h = '<p class="result-count" id="resultCount">Showing <strong>%d</strong> of %d members</p>' % (TOP_N, len(ms))
    h += '<div class="member-grid" id="memberGrid">%s</div>' % "".join(member_card(m) for m in rows[:TOP_N])
    put(p, "members-browse", h)


def main():
    obl = load(HERE / "data" / "obligations.json")
    build_home(obl)
    build_workload(obl)
    build_timeline(obl)
    build_methodology()
    build_obligations_table(obl)
    pw = load(HERE / "data" / "powers.json")
    build_powers_table(pw)
    build_powers_home(pw)
    build_agency_powers(pw)
    build_hub_home(obl, pw)
    build_hub_agencies()
    build_hub_members()
    print("changed:" if changed else "no changes", *changed, sep="\n  ")


if __name__ == "__main__":
    main()
