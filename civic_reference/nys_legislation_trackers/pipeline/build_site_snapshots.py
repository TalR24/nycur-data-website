#!/usr/bin/env python3
"""Pre-render the static blocks of the NYS duties/, powers/, agencies/ and legislators/ pages (hero line, result count, first 25 rows,
methodology note) from data/site/ and quality/gold_score.json, so crawlers that skip JavaScript see real content.
Mirrors the markup and labels the pages' own JS builds; the JS replaces the blocks on load.

    python3 civic_reference/nys_legislation_trackers/pipeline/build_site_snapshots.py

No network, no model calls, idempotent. Uses the same marker helper as the NYC builder
(civic_reference/legislation_implementation_tracker/pipeline/build_static_snapshots.py, via seo/static_snapshot.py)."""
import json
import sys
from html import escape
from urllib.parse import quote
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent            # nys_legislation_trackers/
REPO = HERE.parent.parent                                  # data_website/
sys.path.insert(0, str(REPO / "seo"))
from static_snapshot import inject  # noqa: E402

SITE = HERE / "data" / "site"
PAGE_SIZE = 25
MS_NOTE = "Multi-state compact body in which New York takes part"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
changed = []


def esc(s):
    return escape("" if s is None else str(s), quote=True)


def num(n):
    return f"{n:,}"


def put(path, block_id, html):
    if inject(path, block_id, html):
        changed.append(f"{Path(path).relative_to(REPO)}:{block_id}")


def fmt_date(iso):
    y, m, d = iso.split("-")
    return f"{MONTHS[int(m) - 1]} {int(d)}, {y}"


def kind_label(v):
    s = str(v).replace("_", " ")
    return s[:1].upper() + s[1:]


def row(r, laws, ag, has_deadline):
    law = laws.get(r["l"], {})
    full = (ag.get(r["a"]) or {}).get("full_name") or r["a"]
    year = str(law.get("session") or r["i"][:4])
    cell = ('<td class="agency-cell" title="%s">%s%s%s%s</td>' % (
        esc(r["a"] + " · " + full if full != r["a"] else r["a"]), esc(full),
        '<span class="agency-unit">%s</span>' % esc(r["au"]) if r.get("au") else "",
        '<span class="agency-unit note">%s</span>' % esc(r["hn"]) if r.get("hn") else "",
        '<span class="agency-unit note">%s</span>' % esc(MS_NOTE) if r.get("ms") else ""))
    dl = ""
    if has_deadline:
        text = fmt_date(r["dd"]) if r.get("dd") else (kind_label(r["dk"]) if r.get("dk") else "—")
        dl = '<td class="deadline-cell">%s%s</td>' % (esc(text), '<span class="recur-sub">%s</span>' % esc(r["rc"]) if r.get("rc") else "")
    file_no = "-".join(r["l"].split("-")[1:])
    return ('<tr class="data-row" data-id="%s">%s<td class="action-cell">%s</td>%s'
            '<td class="law-cell">%s<span class="file-no">%s</span></td><td class="meta-cell">%s</td></tr>'
            % (esc(r["i"]), cell, esc(r["s"]), dl, esc(law.get("law_number_display") or r["l"]), esc(file_no), esc(year)))


def method_note(summary, gold):
    pr = gold["precision_real"]["rate"] * 100
    rc = gold["recall"]["rate"] * 100
    return ('Claude read the marked text of each signed law and listed the duties and powers it creates or widens, and the pipeline '
            'then drops reprinted text, conditions, definitions and duties of private parties before resolving each actor to a '
            'canonical agency. Two auditors check a blind sample of new records every night against a hand-verified set of %s laws, '
            'where %.1f%% of stored records are real duties or powers and %.1f%% of the provisions in those laws are found. '
            'The 2025 session was extracted on November 12, 2026 and has had one audit so far, so its records carry more uncertainty '
            'than earlier sessions until the nightly audits reach it.'
            % (num(gold["gold_laws"]), pr, rc))


def enc(s):
    """Same escaping as the pages' encodeURIComponent."""
    return quote(s, safe="!'()*")


def agency_row(a):
    d, p = sum(a["duties"].values()), sum(a["powers"].values())
    nd = a["next_deadlines"][0]["date"] if a["next_deadlines"] else None
    full = a.get("full_name") or a["name"]
    return ('<tr class="data-row"><td class="agency-cell name-cell" title="%s"><a href="?agency=%s">%s</a>%s</td>'
            '<td class="num-cell">%s</td><td class="num-cell">%s</td><td class="num-cell">%s</td><td class="deadline-cell">%s</td></tr>'
            % (esc(a["name"]), esc(enc(a["name"])), esc(full), '<span class="agency-unit">%s</span>' % esc(a["name"]) if full != a["name"] else "",
               num(d), num(p), num(a["laws"]), esc(fmt_date(nd)) if nd else "—"))


def legislator_row(g, dup):
    href = "?name=" + enc(g["name"]) + ("&chamber=" + enc(g["chamber"]) if g["name"] in dup else "")
    return ('<tr class="data-row"><td class="agency-cell name-cell"><a href="%s">%s</a></td><td class="meta-cell">%s</td>'
            '<td class="num-cell">%s</td><td class="num-cell">%s</td><td class="num-cell">%s</td></tr>'
            % (esc(href), esc(g["name"]), esc(g["chamber"]), num(g["laws"]), num(g["duties"]), num(g["powers"])))


def directory_pages(summary):
    """Agencies and legislators: hero line, result count and first PAGE_SIZE rows in the pages' default sort
    (duties plus powers, descending; ties by name), the same order the JS paints."""
    ags = json.load(open(SITE / "agencies.json"))
    ags.sort(key=lambda a: (-(sum(a["duties"].values()) + sum(a["powers"].values())), a["name"]))
    path = HERE / "agencies" / "index.html"
    put(path, "nys-ag-hero", "%s state and local bodies carry duties or powers from New York laws signed since 2009." % num(summary["agencies"]))
    put(path, "nys-ag-count", "Showing <strong>1–%d</strong> of %s matching agencies" % (PAGE_SIZE, num(len(ags))))
    put(path, "nys-ag-rows", "".join(agency_row(a) for a in ags[:PAGE_SIZE]))
    lgs = json.load(open(SITE / "legislators.json"))
    seen, dup = set(), set()
    for g in lgs:
        (dup if g["name"] in seen else seen).add(g["name"])
    lgs.sort(key=lambda g: (-(g["duties"] + g["powers"]), g["name"]))
    path = HERE / "legislators" / "index.html"
    put(path, "nys-lg-hero", "%s prime sponsors carried the signed laws behind these duties and powers." % num(summary["legislators"]))
    put(path, "nys-lg-count", "Showing <strong>1–%d</strong> of %s matching legislators" % (PAGE_SIZE, num(len(lgs))))
    put(path, "nys-lg-rows", "".join(legislator_row(g, dup) for g in lgs[:PAGE_SIZE]))


def main():
    summary = json.load(open(SITE / "summary.json"))
    gold = json.load(open(HERE / "quality" / "gold_score.json"))
    laws = {l["key"]: l for l in json.load(open(SITE / "laws.json"))}
    ag = {a["name"]: a for a in json.load(open(SITE / "agencies.json"))}
    recs = []
    for s in summary["sessions"]:
        recs += json.load(open(SITE / ("records_%d.json" % s["session"])))
    for page, kind, key, noun, hero, has_dl in (
            ("duties", "d", "duties", "duties", "New York laws signed since 2009 gave state and local governments %s duties to carry out.", True),
            ("powers", "p", "powers", "powers", "New York laws signed since 2009 granted or extended %s powers that state and local governments may use.", False)):
        path = HERE / page / "index.html"
        rows = [r for r in recs if r["k"] == kind]
        for r in rows:                                    # default sort of the JS: law signed date descending, then record id
            r["_sd"] = laws.get(r["l"], {}).get("signed") or ""
        rows.sort(key=lambda r: (_neg(r["_sd"]), r["i"]))
        total = summary[key]
        assert len(rows) == total, (page, len(rows), total)
        put(path, "nys-hero", hero % num(total))
        put(path, "nys-count", "Showing <strong>1–%d</strong> of %s matching %s" % (PAGE_SIZE, num(total), noun))
        put(path, "nys-rows", "".join(row(r, laws, ag, has_dl) for r in rows[:PAGE_SIZE]))
        put(path, "nys-method", method_note(summary, gold))
    directory_pages(summary)
    print("changed:", changed or "nothing")


def _neg(s):
    """Sort key that reverses ISO date strings (descending) without a second pass."""
    return tuple(-ord(c) for c in s)


if __name__ == "__main__":
    main()
