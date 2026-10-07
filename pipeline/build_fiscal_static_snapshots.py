#!/usr/bin/env python3
"""
Pre-render the Fiscal Impacts Tracker's JS-built content as static HTML, so
crawlers that do not run JavaScript (most AI crawlers) read real numbers:

  overview/  stat pills, the four chart titles, the four bar/column charts
  hub        the "Showing N of N bills" line and the 10 most recent bills

Each block mirrors the page's own JS (same markup, labels and title templates,
ported from overview/index.html render() and index.html renderRow()) and sits
inside the element the JS fills, so the JS replaces it on load. Top-10 rows at
most; the trackers offer no downloads. Run after the data refresh:

    python3 pipeline/build_fiscal_static_snapshots.py      # from data_website/

refresh_fiscal_data.yml runs it after validate_fiscal_impacts.py.
"""

import json
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "seo"))
from static_snapshot import inject  # noqa: E402

TRACKER = ROOT / "civic_reference" / "nyc_council_fiscal_impacts_tracker"


def esc(s):
    return escape(str(s), quote=True)


def fmt(v):
    """overview fmt(): $1.2B / $3.4M / $56K."""
    if v is None:
        return "—"
    a, sign = abs(v), "−" if v < 0 else ""
    if a >= 1e9:
        return f"{sign}${a / 1e9:.1f}B"
    if a >= 1e6:
        return f"{sign}${a / 1e6:.1f}M"
    if a >= 1e3:
        return f"{sign}${a / 1e3:.0f}K"
    return f"{sign}${a:.0f}"


def short_money(v):
    a = abs(v)
    if a >= 1e9:
        return f"${a / 1e9:.0f}B" if a >= 1e10 else f"${a / 1e9:.1f}B"
    if a >= 1e6:
        return f"${round(a / 1e6)}M"
    if a >= 1e3:
        return f"${round(a / 1e3)}K"
    return f"${round(a)}"


def fmt_curr(v):
    """hub fmtCurr()."""
    if v is None:
        return None
    a = abs(v)
    if a == 0:
        return "$0"
    if a >= 1e9:
        return f"${v / 1e9:.2f}B"
    if a >= 1e6:
        return f"${v / 1e6:.1f}M"
    if a >= 1e3:
        return f"${v / 1e3:.0f}K"
    return f"${a:.0f}"


def cost(r):
    return (r.get("total_expenditure") or 0) + (r.get("total_capital") or 0)


def hbars(pairs, money):
    if not pairs:
        return '<p class="loading-note">No data.</p>'
    mx = max(abs(p[1]) for p in pairs) or 0
    out = []
    for p in pairs:
        w = abs(p[1]) / mx * 100 if mx else 0
        label = p[2] if len(p) > 2 and p[2] else p[0]
        val = fmt(p[1]) if money else f"{p[1]:,}"
        out.append(f'<div class="c-bar-row"><span class="c-bar-label" title="{esc(label)}">{esc(p[0])}</span>'
                   f'<div class="c-bar-track"><div class="c-bar-fill" data-w="{w:g}" style="width:{w:.1f}%"></div></div>'
                   f'<span class="c-bar-value">{val}</span></div>')
    return "".join(out)


def columns(pairs, raw):
    if not pairs:
        return '<p class="loading-note">No data.</p>'
    mx = max(p[1] for p in raw) or 0
    top = max(range(len(raw)), key=lambda i: raw[i][1])
    out = ['<div class="col-chart">']
    for i, p in enumerate(pairs):
        h = raw[i][1] / mx * 100 if mx else 0
        cls = "col-num" + (" col-num-alt" if i % 2 == 1 else "") + (" col-num-top" if i == top else "")
        out.append(f'<div class="col-item"><span class="{cls}">{short_money(raw[i][1])}</span>'
                   f'<div class="col-bar" data-h="{h:g}" style="height:{max(2, h):.1f}%"></div>'
                   f'<span class="col-label">{esc(p[0])}</span></div>')
    out.append("</div>")
    return "".join(out)


def overview(records):
    page = TRACKER / "overview" / "index.html"
    total = len(records)
    total_cost = sum(cost(r) for r in records)
    total_rev = sum(r.get("total_revenue") or 0 for r in records)
    rev_bills = sum(1 for r in records if (r.get("net_fiscal_impact") or 0) > 0)
    blocks = {"sp-bills": f"{total:,}", "sp-cost": fmt(total_cost), "sp-revenue": fmt(total_rev),
              "sp-rev-bills": f"{rev_bills:,}"}

    by_agency, full = {}, {}
    for r in records:
        for i, a in enumerate(r.get("agencies_abbrev") or []):
            if not a:
                continue
            by_agency[a] = by_agency.get(a, 0) + cost(r)
            fulls = r.get("agencies_full") or []
            f = fulls[i] if i < len(fulls) else None
            if f and a not in full:
                full[a] = f
    agency = sorted(([k, v, full.get(k, k)] for k, v in by_agency.items()), key=lambda p: -p[1])
    # The live chart shows 12 agencies plus "All other agencies"; the static copy stops at 10.
    blocks["chart-agency"] = hbars(agency[:10], True)
    if agency:
        blocks["title-agency"] = esc(f"{agency[0][2]} is attached to {fmt(agency[0][1])} in annual costs, "
                                     f"more than any other agency")

    by_sponsor = {}
    for r in records:
        if r.get("prime_sponsor"):
            by_sponsor[r["prime_sponsor"]] = by_sponsor.get(r["prime_sponsor"], 0) + cost(r)
    sponsor = sorted(([k, v] for k, v in by_sponsor.items()), key=lambda p: -p[1])[:10]
    blocks["chart-sponsor"] = hbars(sponsor, True)
    if sponsor:
        blocks["title-sponsor"] = esc(f"{sponsor[0][0]} sponsored bills with the largest combined annual cost: "
                                      f"{fmt(sponsor[0][1])}")

    by_year = {}
    for r in records:
        if r.get("intro_year"):
            by_year[r["intro_year"]] = by_year.get(r["intro_year"], 0) + cost(r)
    years = sorted(([k, v] for k, v in by_year.items()), key=lambda p: int(p[0]))
    blocks["chart-year"] = columns([["'" + str(p[0])[2:], p[1]] for p in years], years)
    if years:
        ty = max(years, key=lambda p: p[1])
        blocks["title-year"] = esc(f"Bills from {ty[0]} carry the largest combined annual cost: {fmt(ty[1])}")

    with_net = [r for r in records if r.get("net_fiscal_impact") is not None]
    cost_b = sum(1 for r in with_net if r["net_fiscal_impact"] < 0)
    rev_b = sum(1 for r in with_net if r["net_fiscal_impact"] > 0)
    zero_b = sum(1 for r in with_net if r["net_fiscal_impact"] == 0)
    pairs = [["Cost the city", cost_b], ["Raise revenue", rev_b]] + ([["Net zero", zero_b]] if zero_b else [])
    blocks["chart-cost-rev"] = hbars(pairs, False)
    blocks["title-cost-rev"] = esc(f"{cost_b:,} of {len(with_net):,} bills cost the city money; {rev_b:,} raise revenue")

    changed = [bid for bid, html in blocks.items() if inject(page, bid, html)]
    return page, changed


def type_badge(t):
    if not t:
        return '<span class="type-badge other">?</span>'
    if "Pre-Considered" in t:
        return '<span class="type-badge res">Pre-Consid.</span>'
    if t == "Introduction":
        return '<span class="type-badge intro">Int.</span>'
    if t == "Resolution":
        return '<span class="type-badge res">Res.</span>'
    return f'<span class="type-badge other">{esc(t[:6])}</span>'


def net_label(r):
    if not r.get("cost_estimable"):
        return "net-unk", "unestimable"
    n = r.get("net_fiscal_impact")
    if r.get("package_note") and n is None:
        return "net-unk", "see package"
    if n is None:
        return "net-unk", "—"
    if n == 0:
        return "net-zero", "$0"
    if n < 0:
        return "net-cost", "−" + fmt_curr(abs(n))
    return "net-rev", "+" + fmt_curr(n)


def row(r):
    cls, txt = net_label(r)
    amt = lambda k: fmt_curr(r[k]) if r.get(k) is not None else "—"  # noqa: E731
    ag = r.get("agencies_abbrev") or []
    tags = "".join(f'<span class="agency-tag">{esc(a)}</span>' for a in ag[:4])
    if len(ag) > 4:
        tags += f'<span class="agency-tag">+{len(ag) - 4}</span>'
    label = esc(r.get("legistar_file") or r.get("file_number") or "No number")
    bill = (f'<a href="{esc(r["legistar_url"])}" target="_blank" rel="noopener">{label}</a>' if r.get("legistar_url")
            else f'<span title="No Legistar page could be matched to this historical record">{label}</span>')
    return (f'<tr class="data-row" data-id="{esc(r.get("matter_id", ""))}"><td class="file-cell">{bill}</td>'
            f'<td class="type-cell">{type_badge(r.get("legislation_type"))}</td>'
            f'<td class="title-cell"><div class="title-text">{esc(r.get("title") or "")}</div></td>'
            f'<td>{esc(r.get("committee") or "—")}</td><td>{esc(r.get("prime_sponsor") or "—")}</td>'
            f'<td><div class="agency-tags">{tags or "—"}</div></td>'
            f'<td style="white-space:nowrap;color:var(--text-faint);font-size:0.75rem">{esc(r.get("date_prepared") or "")}</td>'
            f'<td class="amount-cell {cls}">{txt}</td><td class="amount-cell">{amt("total_expenditure")}</td>'
            f'<td class="amount-cell">{amt("total_capital")}</td><td class="amount-cell">{amt("total_revenue")}</td>'
            f'<td style="text-align:center"><span class="expand-icon">›</span></td></tr>')


def hub(records):
    page = TRACKER / "index.html"
    # Default view: date_prepared descending, undated bills last (index.html sort).
    recent = sorted(records, key=lambda r: r.get("date_prepared") or "", reverse=True)[:10]
    blocks = {
        "results-count": f"Showing <strong>{len(records)}</strong> of <strong>{len(records)}</strong> bills",
        "bill-rows": "\n".join(row(r) for r in recent),
    }
    changed = [bid for bid, html in blocks.items() if inject(page, bid, html)]
    return page, changed


def main():
    data = json.loads((TRACKER / "agency-fiscal-impact" / "data.json").read_text(encoding="utf-8"))
    hub_records = json.loads((TRACKER / "data" / "fiscal_impacts.json").read_text(encoding="utf-8"))["records"]
    for page, changed in (overview(data["records"]), hub(hub_records)):
        rel = page.relative_to(ROOT)
        print(f"{'updated' if changed else 'unchanged'} {rel}" + (f": {', '.join(changed)}" if changed else ""))


if __name__ == "__main__":
    main()
