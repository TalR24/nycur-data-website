#!/usr/bin/env python3
"""
Pull Google Search Console data for the NYCuriosity properties and write a
monthly report (Markdown + JSON snapshot). Search Console is the source of
truth for what search actually sends; this script turns it into the short list
of pages worth rewriting.

    python3 seo/gsc_pull.py                      # last 28 days, report to stdout + files
    python3 seo/gsc_pull.py --days 90 --out ~/Desktop
    python3 seo/gsc_pull.py --email              # also email the report (Gmail SMTP secrets)

Credentials: a Google Cloud service account that has been added as a user on
each Search Console property. Provide the key as the GSC_SERVICE_ACCOUNT_JSON
env var (the JSON text, used by the GitHub Action) or as a file at
~/.config/gsc/service_account.json (local sessions). Never commit the key.

Properties (domain properties cover every subdomain, so nycuriosity.com covers
the Substack site, data.nycuriosity.com and talroded.nycuriosity.com):
    sc-domain:nycuriosity.com
    sc-domain:statecapacityecosystem.com

Requires: pip3 install --user google-auth requests

Report sections, per host:
  totals (clicks / impressions / CTR / position) vs the previous period
  top pages and top queries
  REWRITE CANDIDATES: pages with real impressions but a weak CTR for their
      position, i.e. the title/description are not earning the click
  DROPS: pages whose clicks fell by half or more
  NOT SEEN: sitemap URLs with zero impressions (indexing or discovery problem)
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SITES, WORKSPACE, send_email, sitemap_locs  # noqa: E402

PROPERTIES = ["sc-domain:nycuriosity.com", "sc-domain:statecapacityecosystem.com"]
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
API = "https://www.googleapis.com/webmasters/v3/sites/{prop}/searchAnalytics/query"
DATA_LAG_DAYS = 3  # Search Console finalizes data about three days late

# Expected CTR by position, a conservative curve; a page well under it is a
# rewrite candidate. Positions past 20 are ignored (nobody sees them).
EXPECTED_CTR = {1: .25, 2: .14, 3: .10, 4: .07, 5: .055, 6: .045, 7: .035, 8: .03,
                9: .025, 10: .022, 11: .015, 12: .013, 13: .012, 14: .011, 15: .010,
                16: .009, 17: .008, 18: .007, 19: .006, 20: .005}
MIN_IMPRESSIONS = 100  # below this the CTR is noise

HOST_LABELS = {
    "data.nycuriosity.com": "Data website",
    "talroded.nycuriosity.com": "Personal site",
    "statecapacityecosystem.com": "State Capacity Ecosystem",
    "www.statecapacityecosystem.com": "State Capacity Ecosystem",
}


def substack_host(host):
    return host in ("nycuriosity.com", "www.nycuriosity.com", "nycuriosity.substack.com")


def host_label(host):
    if substack_host(host):
        return "Substack (nycuriosity.com)"
    return HOST_LABELS.get(host, host)


# ------------------------------------------------------------------ auth ---

def credentials(key_path=None):
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
    except ImportError:
        raise SystemExit("google-auth is not installed: pip3 install --user google-auth requests")
    raw = os.environ.get("GSC_SERVICE_ACCOUNT_JSON")
    if raw:
        info = json.loads(raw)
        creds = service_account.Credentials.from_service_account_info(info, scopes=[SCOPE])
    else:
        path = Path(key_path or "~/.config/gsc/service_account.json").expanduser()
        if not path.exists():
            raise SystemExit(f"no Search Console key: set GSC_SERVICE_ACCOUNT_JSON or save the service "
                             f"account JSON at {path}")
        creds = service_account.Credentials.from_service_account_file(str(path), scopes=[SCOPE])
    creds.refresh(Request())
    return creds


def query(session, token, prop, start, end, dimensions, row_limit=25000):
    import requests
    body = {"startDate": start.isoformat(), "endDate": end.isoformat(),
            "dimensions": dimensions, "rowLimit": row_limit, "dataState": "final"}
    rows, start_row = [], 0
    while True:
        body["startRow"] = start_row
        r = session.post(API.format(prop=quote(prop, safe="")), json=body,
                         headers={"Authorization": f"Bearer {token}"}, timeout=60)
        if r.status_code == 403:
            raise SystemExit(f"403 for {prop}: add the service account email as a user on this property "
                             f"in Search Console (Settings > Users and permissions)")
        r.raise_for_status()
        batch = r.json().get("rows", [])
        rows.extend(batch)
        if len(batch) < row_limit:
            return rows
        start_row += row_limit


# ------------------------------------------------------------- analysis ---

def totals(rows):
    clicks = sum(r["clicks"] for r in rows)
    imps = sum(r["impressions"] for r in rows)
    pos = (sum(r["position"] * r["impressions"] for r in rows) / imps) if imps else 0
    return {"clicks": clicks, "impressions": imps, "ctr": (clicks / imps) if imps else 0, "position": pos}


def by_host(rows):
    out = {}
    for r in rows:
        host = urlsplit(r["keys"][0]).netloc
        out.setdefault(host, []).append(r)
    return out


def pct(cur, prev):
    if not prev:
        return "new" if cur else "0"
    return f"{(cur - prev) / prev * 100:+.0f}%"


def rewrite_candidates(page_rows):
    out = []
    for r in page_rows:
        if r["impressions"] < MIN_IMPRESSIONS or r["position"] > 20:
            continue
        expected = EXPECTED_CTR.get(max(1, round(r["position"])), .005)
        if r["ctr"] < expected * 0.6:
            out.append({**r, "expected_ctr": expected,
                        "missed_clicks": round((expected - r["ctr"]) * r["impressions"])})
    return sorted(out, key=lambda r: -r["missed_clicks"])[:12]


def drops(cur_rows, prev_rows):
    prev = {r["keys"][0]: r for r in prev_rows}
    out = []
    for r in cur_rows:
        p = prev.get(r["keys"][0])
        if p and p["clicks"] >= 10 and r["clicks"] <= p["clicks"] * 0.5:
            out.append({"page": r["keys"][0], "clicks": r["clicks"], "prev_clicks": p["clicks"],
                        "position": r["position"], "prev_position": p["position"]})
    # pages that vanished entirely
    cur = {r["keys"][0] for r in cur_rows}
    for url, p in prev.items():
        if url not in cur and p["clicks"] >= 10:
            out.append({"page": url, "clicks": 0, "prev_clicks": p["clicks"],
                        "position": None, "prev_position": p["position"]})
    return sorted(out, key=lambda d: d["prev_clicks"] - d["clicks"], reverse=True)[:12]


def unseen_sitemap_urls(session, base, page_rows):
    try:
        r = session.get(base + "/sitemap.xml", timeout=30)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        return None, f"sitemap fetch failed: {e}"
    seen = {r_["keys"][0].rstrip("/") for r_ in page_rows}
    return [u for u in sitemap_locs(r.text) if u.rstrip("/") not in seen], None


# --------------------------------------------------------------- report ---

def fmt_row(r, label_key="keys"):
    key = r[label_key][0] if label_key == "keys" else r[label_key]
    return f"{r['clicks']:>6} clicks  {r['impressions']:>8} imp  {r['ctr']*100:5.1f}% CTR  pos {r['position']:5.1f}  {key}"


def render(period, prev_period, sections):
    out = [f"# NYCuriosity search report, {period[0]} to {period[1]}",
           f"Compared with {prev_period[0]} to {prev_period[1]}. Source: Google Search Console.", ""]
    for s in sections:
        t, p = s["totals"], s["prev_totals"]
        out.append(f"## {s['label']}")
        out.append(f"Clicks {t['clicks']} ({pct(t['clicks'], p['clicks'])})  "
                   f"Impressions {t['impressions']} ({pct(t['impressions'], p['impressions'])})  "
                   f"CTR {t['ctr']*100:.1f}%  Avg position {t['position']:.1f} (was {p['position']:.1f})")
        out.append("")
        if s["top_pages"]:
            out.append("Top pages")
            out.extend("  " + fmt_row(r) for r in s["top_pages"])
            out.append("")
        if s["top_queries"]:
            out.append("Top queries")
            out.extend("  " + fmt_row(r) for r in s["top_queries"])
            out.append("")
        out.append("REWRITE CANDIDATES (impressions but a weak CTR for the position; fix title + description)")
        if s["rewrite"]:
            for r in s["rewrite"]:
                out.append(f"  ~{r['missed_clicks']:>4} clicks missed  {r['impressions']:>7} imp  "
                           f"{r['ctr']*100:4.1f}% vs {r['expected_ctr']*100:.1f}% expected  pos {r['position']:4.1f}  {r['keys'][0]}")
        else:
            out.append("  none this period")
        out.append("")
        out.append("DROPS (clicks fell by half or more)")
        if s["drops"]:
            for d in s["drops"]:
                pos = f"pos {d['position']:.1f} (was {d['prev_position']:.1f})" if d["position"] else "no longer appearing"
                out.append(f"  {d['clicks']:>5} clicks (was {d['prev_clicks']})  {pos}  {d['page']}")
        else:
            out.append("  none")
        out.append("")
        if s.get("unseen") is not None:
            out.append(f"NOT SEEN: {len(s['unseen'])} sitemap URLs with zero impressions")
            out.extend("  " + u for u in s["unseen"][:40])
            if len(s["unseen"]) > 40:
                out.append(f"  ... and {len(s['unseen']) - 40} more")
            out.append("")
        elif s.get("unseen_error"):
            out.append(f"NOT SEEN: {s['unseen_error']}")
            out.append("")
    return "\n".join(out) + "\n"


def main():
    import requests
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--properties", nargs="*", default=PROPERTIES)
    ap.add_argument("--key", help="service account JSON path (default ~/.config/gsc/service_account.json)")
    ap.add_argument("--out", help="folder for the report files (default: nycur-data-premium/seo_reports/ "
                                  "if present, else ./seo_reports/)")
    ap.add_argument("--email", action="store_true")
    ap.add_argument("--end", help="period end date YYYY-MM-DD (default: today minus data lag)")
    args = ap.parse_args()

    end = date.fromisoformat(args.end) if args.end else date.today() - timedelta(days=DATA_LAG_DAYS)
    start = end - timedelta(days=args.days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=args.days - 1)

    creds = credentials(args.key)
    session = requests.Session()
    sections, snapshot = [], {"period": [start.isoformat(), end.isoformat()],
                              "previous": [prev_start.isoformat(), prev_end.isoformat()], "hosts": {}}
    for prop in args.properties:
        cur_pages = query(session, creds.token, prop, start, end, ["page"])
        prev_pages = query(session, creds.token, prop, prev_start, prev_end, ["page"])
        cur_queries = query(session, creds.token, prop, start, end, ["page", "query"])
        hosts_cur, hosts_prev, hosts_q = by_host(cur_pages), by_host(prev_pages), by_host(cur_queries)
        for host in sorted(set(hosts_cur) | set(hosts_prev), key=lambda h: -totals(hosts_cur.get(h, []))["clicks"]):
            rows, prev_rows = hosts_cur.get(host, []), hosts_prev.get(host, [])
            queries = {}
            for r in hosts_q.get(host, []):
                q = queries.setdefault(r["keys"][1], {"keys": [r["keys"][1]], "clicks": 0, "impressions": 0, "pos_w": 0})
                q["clicks"] += r["clicks"]
                q["impressions"] += r["impressions"]
                q["pos_w"] += r["position"] * r["impressions"]
            qrows = []
            for q in queries.values():
                q["ctr"] = q["clicks"] / q["impressions"] if q["impressions"] else 0
                q["position"] = q.pop("pos_w") / q["impressions"] if q["impressions"] else 0
                qrows.append(q)
            section = {
                "host": host, "label": host_label(host),
                "totals": totals(rows), "prev_totals": totals(prev_rows),
                "top_pages": sorted(rows, key=lambda r: -r["clicks"])[:15],
                "top_queries": sorted(qrows, key=lambda r: -r["clicks"])[:15],
                "rewrite": rewrite_candidates(rows),
                "drops": drops(rows, prev_rows),
            }
            base = next((c["base"] for c in SITES.values() if c["gsc_host"] == host), None)
            if base:
                unseen, err = unseen_sitemap_urls(session, base, rows)
                section["unseen"], section["unseen_error"] = unseen, err
            sections.append(section)
            snapshot["hosts"][host] = {"pages": rows, "prev_pages": prev_rows, "queries": qrows}

    report = render((start, end), (prev_start, prev_end), sections)
    sys.stdout.write(report)

    out_dir = Path(args.out) if args.out else (
        WORKSPACE / "nycur-data-premium" / "seo_reports" if (WORKSPACE / "nycur-data-premium").exists()
        else Path("seo_reports"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / end.strftime("%Y-%m")
    stem.with_suffix(".md").write_text(report, encoding="utf-8")
    stem.with_suffix(".json").write_text(json.dumps(snapshot, indent=1), encoding="utf-8")
    print(f"\nwrote {stem}.md and {stem}.json", file=sys.stderr)

    if args.email:
        send_email(f"NYCuriosity SEO report, {end.strftime('%B %Y')}", report)


if __name__ == "__main__":
    main()
