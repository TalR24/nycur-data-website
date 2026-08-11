#!/usr/bin/env python3
"""
NYC Legislation Implementation Tracker — Step 1: fetch enacted local laws.

Enumerates all NYC Council Introductions with final status "Enacted" for the
given years via the Legistar advanced search (no API token needed), fetches
each law's detail page, and saves:

  - data/laws.json          — one metadata record per enacted law (committed)
  - cache/text/{id}.txt     — full enacted legislation text (gitignored)
  - cache/laws/{id}.json    — per-law raw parse checkpoint (gitignored)

The full text is the input to Step 2 (extract_obligations.py). Detail pages
render the latest (enacted) version of the bill text by default.

Usage:
    python3 pipeline/fetch_enacted_laws.py                 # years 2024-2026
    python3 pipeline/fetch_enacted_laws.py --years 2024 2025
    python3 pipeline/fetch_enacted_laws.py --incremental   # skip cached laws

Scraping approach (search form postbacks, RadGrid pagination) is adapted from
the NYC Council Fiscal Impacts Tracker pipeline.
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
CACHE = HERE / "cache"
TEXT_CACHE = CACHE / "text"
LAW_CACHE = CACHE / "laws"
LAWS_JSON = DATA / "laws.json"

BASE_URL = "https://legistar.council.nyc.gov"
# Full tracker coverage. The Jul 2026 expansion to 2014 was run with an explicit
# --years list while this default still said 2024-2026; the Aug 2026 monthly Action
# then regenerated laws.json from the stale default and truncated the dataset.
# Keep this spanning 2014 -> current year so CI refreshes never shrink coverage.
DEFAULT_YEARS = [str(y) for y in range(2014, datetime.now().year + 1)]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fetch_enacted_laws")


def create_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    return s


def _viewstate(html: str) -> tuple[str, str]:
    vs = re.search(r'id="__VIEWSTATE"\s+value="([^"]+)"', html)
    vsg = re.search(r'id="__VIEWSTATEGENERATOR"\s+value="([^"]+)"', html)
    return (vs.group(1) if vs else "", vsg.group(1) if vsg else "")


def _combo_state(value: str) -> str:
    """
    ClientState JSON for a Telerik RadComboBox selection. The 'logEntries'
    format is required — the fiscal tracker's 'validationText' variant works
    for the year combo but is silently ignored for lstType/lstStatus.
    """
    return json.dumps({
        "logEntries": [],
        "value": value,
        "text": value,
        "enabled": True,
        "checkedIndices": [],
        "checkedItemsTextOverflows": False,
    })


def search_enacted_intros(session: requests.Session, year: str,
                          max_retries: int = 2) -> list[tuple[str, str]]:
    """
    Advanced search: Type=Introduction, Status=Enacted, for one year.
    Returns deduplicated (matter_id, guid) tuples across all result pages.
    """
    log.info(f"Searching enacted Introductions for {year} ...")

    search_fields = {
        "ctl00$ContentPlaceHolder1$lstYearsAdvanced": year,
        "ctl00_ContentPlaceHolder1_lstYearsAdvanced_ClientState": _combo_state(year),
        "ctl00$ContentPlaceHolder1$lstType": "Introduction",
        "ctl00_ContentPlaceHolder1_lstType_ClientState": _combo_state("Introduction"),
        "ctl00$ContentPlaceHolder1$lstStatus": "Enacted",
        "ctl00_ContentPlaceHolder1_lstStatus_ClientState": _combo_state("Enacted"),
        "ctl00$ContentPlaceHolder1$lstMax": "1000",
        "ctl00_ContentPlaceHolder1_lstMax_ClientState": _combo_state("1000"),
    }

    for attempt in range(max_retries + 1):
        try:
            r = session.get(f"{BASE_URL}/Legislation.aspx", timeout=20)
            r.raise_for_status()
            vs, vsg = _viewstate(r.text)

            # Switch to advanced search mode
            r2 = session.post(f"{BASE_URL}/Legislation.aspx", data={
                "__VIEWSTATE": vs, "__VIEWSTATEGENERATOR": vsg,
                "ctl00$ContentPlaceHolder1$btnSwitch": "Advanced search >>>",
                "ctl00$ContentPlaceHolder1$lstYears": "This Year",
                "ctl00$ContentPlaceHolder1$lstTypeBasic": "All Types",
            }, timeout=20)
            r2.raise_for_status()
            vs2, vsg2 = _viewstate(r2.text)

            r3 = session.post(f"{BASE_URL}/Legislation.aspx", data={
                "__VIEWSTATE": vs2, "__VIEWSTATEGENERATOR": vsg2,
                "ctl00$ContentPlaceHolder1$btnSearch": "Search Legislation",
                **search_fields,
            }, timeout=90)
            r3.raise_for_status()

            seen: set[str] = set()
            unique: list[tuple[str, str]] = []

            def _extract(page_html: str) -> None:
                for mid, guid in re.findall(
                    r"LegislationDetail\.aspx\?ID=(\d+)&(?:amp;)?GUID=([A-F0-9\-]+)",
                    page_html,
                ):
                    if mid not in seen:
                        seen.add(mid)
                        unique.append((mid, guid))

            _extract(r3.text)
            log.info(f"  {year} page 1: {len(unique)} matters")

            current_html = r3.text
            page_num = 1
            while True:
                next_page = page_num + 1
                m = re.search(
                    r"doPostBack\(&#39;([^&]+)&#39;,&#39;&#39;\)"
                    r"[^<]*<span>" + str(next_page) + r"</span>",
                    current_html,
                )
                if not m:
                    break
                vs_p, vsg_p = _viewstate(current_html)
                rn = session.post(f"{BASE_URL}/Legislation.aspx", data={
                    "__VIEWSTATE": vs_p, "__VIEWSTATEGENERATOR": vsg_p,
                    "__EVENTTARGET": m.group(1), "__EVENTARGUMENT": "",
                    **search_fields,
                }, timeout=60)
                rn.raise_for_status()
                before = len(unique)
                _extract(rn.text)
                log.info(f"  {year} page {next_page}: {len(unique) - before} new "
                         f"(total: {len(unique)})")
                current_html = rn.text
                page_num = next_page
                time.sleep(1.5)

            log.info(f"  {year}: {len(unique)} enacted Introductions")
            return unique

        except requests.exceptions.Timeout:
            if attempt < max_retries:
                wait = 30 * (attempt + 1)
                log.warning(f"  Timeout for {year} (attempt {attempt+1}); retry in {wait}s")
                time.sleep(wait)
            else:
                log.error(f"  Timeout for {year} after {max_retries+1} attempts")
                return []
        except Exception as e:
            log.error(f"  Error searching {year}: {e}")
            return []
    return []


# ── Detail page parsing ───────────────────────────────────────────────────────

def _span(html: str, label_id: str) -> str:
    m = re.search(
        r'id="ctl00_ContentPlaceHolder1_' + label_id + r'"[^>]*>(.*?)</span>',
        html, re.S,
    )
    if not m:
        return ""
    return htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()


# Legistar renders an amended section in full, marking NEW matter with an
# underline and DELETED matter with square brackets. Stripping tags threw the
# underline away, so a reprinted pre-existing duty looked identical to a newly
# enacted one — the single largest defect class in the Aug 2026 audits. Keep
# the distinction as inline markers the extraction prompt can act on.
_TAG = re.compile(r"<(/?)([a-zA-Z][\w:-]*)([^>]*)>")
_UNDERLINE_STYLE = re.compile(r"text-decoration\s*:\s*underline", re.I)
_VOID_TAGS = {"br", "img", "hr", "input", "meta", "link"}


def _mark_new_matter(fragment: str) -> str:
    """Wrap Legistar's underlined runs in {{...}} so new matter survives tag
    stripping.

    Tracks underline state with a tag stack: an element counts as underlined if
    it is <u> or carries text-decoration: underline, and the state persists
    through nested elements until that element closes.
    """
    out, pos, stack, depth = [], 0, [], 0
    for m in _TAG.finditer(fragment):
        text = fragment[pos:m.start()]
        if text:
            out.append("{{" + text + "}}" if depth else text)
        pos = m.end()
        closing, name, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == name:
                    if stack[i][1]:
                        depth -= 1
                    del stack[i:]
                    break
        elif name not in _VOID_TAGS and not attrs.rstrip().endswith("/"):
            underlined = name == "u" or bool(_UNDERLINE_STYLE.search(attrs))
            stack.append((name, underlined))
            if underlined:
                depth += 1
        out.append(m.group(0))
    tail = fragment[pos:]
    if tail:
        out.append("{{" + tail + "}}" if depth else tail)
    return "".join(out)


def _strip_text_html(fragment: str) -> str:
    """Convert the divText HTML fragment to readable plain text.

    New matter (underlined in Legistar) is preserved as {{...}}; deleted
    matter keeps the source's own [square brackets].
    """
    t = _mark_new_matter(fragment)
    t = re.sub(r"<(p|div|br|tr|li|h\d)[^>]*>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\}\}(\s*)\{\{", r"\1", t)      # merge runs split by markup
    t = re.sub(r"\{\{(\s*)\}\}", r"\1", t)      # drop empty markers
    t = htmllib.unescape(t)
    t = t.replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" ?\n ?", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = t.strip()
    # Drop trailing page-tab artifacts ("Legislation Text", "Legislation
    # Details", "Legislation Details (With Text)") left by the divText markup
    lines = t.split("\n")
    artifacts = {"", "Legislation Text", "Legislation Details",
                 "Legislation Details (With Text)"}
    while lines and lines[-1].strip() in artifacts:
        lines.pop()
    return "\n".join(lines)


def _merge_name_suffixes(sponsors: list[str]) -> list[str]:
    """
    Re-attach name suffixes severed by the comma split ("Rafael Salamanca,
    Jr." arrives as two entries).
    """
    merged: list[str] = []
    for s in sponsors:
        if re.fullmatch(r"(Jr|Sr|II|III|IV)\.?", s) and merged:
            merged[-1] = merged[-1] + ", " + s
        else:
            merged.append(s)
    return merged


def _normalize_record(rec: dict) -> dict:
    """
    Repair a previously saved record in place: records cached before the
    suffix re-merge fix carry "Jr."-style fragments as separate sponsor
    entries, and --incremental would otherwise preserve them forever.
    """
    merged = _merge_name_suffixes(rec.get("sponsors", []))
    if merged != rec.get("sponsors"):
        rec["sponsors"] = merged
        rec["prime_sponsor"] = merged[0] if merged else ""
        rec["sponsor_count"] = len(merged)
    return rec



# A law that repeals itself on a date ("expires and is deemed repealed on
# December 31, 2024") stops imposing its duties then. Without this, a sunset
# law's recurring obligations read as permanent standing duties forever.
SUNSET_CLAUSE = re.compile(
    r"(shall expire and (?:be|is) deemed repealed|expires? and is deemed repealed|"
    r"shall be deemed repealed on|this local law expires)[^.]{0,220}", re.I)
_SUNSET_DATE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{1,2}),\s*(\d{4})")
_SUNSET_REL = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+(year|month)s?\s+"
    r"after\s+(?:it becomes law|the effective date|its effective date|such effective date)", re.I)
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"])}
_NUMWORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def parse_sunset(text: str, enactment_date: str | None) -> tuple[str | None, str | None]:
    """Return (clause_text, sunset_date) for a self-repealing law.

    Only clauses that resolve to a calendar date produce a date; sunsets tied
    to an event ("upon submission of the report") keep the clause with no date,
    exactly as the tracker handles event-anchored deadlines.
    """
    flat = re.sub(r"\s+", " ", text or "")
    m = SUNSET_CLAUSE.search(flat)
    if not m:
        return None, None
    clause = m.group(0).strip()
    dm = _SUNSET_DATE.search(clause)
    if dm:
        try:
            return clause, date(int(dm.group(3)), _MONTHS[dm.group(1)],
                                int(dm.group(2))).isoformat()
        except ValueError:
            return clause, None
    rm = _SUNSET_REL.search(clause)
    if rm and enactment_date:
        n = _NUMWORDS.get(rm.group(1).lower())
        if n is None:
            n = int(rm.group(1))
        days = n * 365 if rm.group(2).lower() == "year" else n * 30
        try:
            y, mo, dd = (int(x) for x in enactment_date[:10].split("-"))
            return clause, (date(y, mo, dd) + timedelta(days=days)).isoformat()
        except ValueError:
            return clause, None
    return clause, None


def parse_detail_page(html: str, matter_id: str, guid: str) -> dict:
    committee = ""
    c = re.search(r'id="ctl00_ContentPlaceHolder1_hypInControlOf[^"]*"[^>]*>([^<]+)<',
                  html)
    if c:
        committee = htmllib.unescape(c.group(1)).strip()

    sponsors_raw = _span(html, "lblSponsors2")
    sponsors = [s.strip() for s in sponsors_raw.split(",") if s.strip()]
    # Drop trailing "(in conjunction with the Mayor)" style suffixes from list
    sponsors = [s for s in sponsors if not s.startswith("(")]
    sponsors = _merge_name_suffixes(sponsors)

    indexes_raw = _span(html, "lblIndexes2")
    indexes = [i.strip() for i in indexes_raw.split(",") if i.strip()]

    law_number = _span(html, "lblEnactmentNumber2")  # e.g. "2026/061"
    law_display = ""
    m = re.match(r"(\d{4})/(\d+)", law_number)
    if m:
        law_display = f"Local Law {int(m.group(2))} of {m.group(1)}"

    text = ""
    tm = re.search(
        r'id="ctl00_ContentPlaceHolder1_divText"[^>]*>(.*)</div>\s*'
        r'(?:<div|<!--|</td)', html, re.S,
    )
    if tm:
        text = _strip_text_html(tm.group(1))

    enact_raw = _span(html, "lblEnactmentDate2")
    enactment_date = ""
    if enact_raw:
        try:
            enactment_date = datetime.strptime(enact_raw, "%m/%d/%Y").strftime("%Y-%m-%d")
        except ValueError:
            enactment_date = enact_raw

    return {
        "matter_id": matter_id,
        "legistar_guid": guid,
        "legistar_url": f"{BASE_URL}/LegislationDetail.aspx?ID={matter_id}&GUID={guid}",
        "file_number": _span(html, "lblFile2"),          # "Int 1391-2025"
        "law_number": law_number,                        # "2026/061"
        "law_number_display": law_display,               # "Local Law 61 of 2026"
        "status": _span(html, "lblStatus2"),
        "matter_type": _span(html, "lblType2"),
        "title": _span(html, "lblTitle2"),
        "summary": _span(html, "lblSummary2"),
        "committee": committee,
        "sponsors": sponsors,
        "prime_sponsor": sponsors[0] if sponsors else "",
        "sponsor_count": len(sponsors),
        "enactment_date": enactment_date,
        "legistar_indexes": indexes,                     # e.g. "Report Required"
        "sunset_clause": parse_sunset(text, enactment_date)[0],
        "sunset_date": parse_sunset(text, enactment_date)[1],
        "text_chars": len(text),
        "text_sha1": hashlib.sha1(text.encode()).hexdigest() if text else "",
        "_text": text,  # stripped before writing laws.json
        "_html": html,  # ditto; needed only for the attachment fallback
    }


def fetch_law(session: requests.Session, matter_id: str, guid: str,
              max_retries: int = 2) -> dict | None:
    url = f"{BASE_URL}/LegislationDetail.aspx?ID={matter_id}&GUID={guid}&Options=&Search="
    for attempt in range(max_retries + 1):
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            return parse_detail_page(r.text, matter_id, guid)
        except Exception as e:
            if attempt < max_retries:
                time.sleep(10 * (attempt + 1))
            else:
                log.error(f"  Failed to fetch matter {matter_id}: {e}")
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", default=DEFAULT_YEARS)
    ap.add_argument("--incremental", action="store_true",
                    help="Reuse records already in data/laws.json (or cache/laws/) "
                         "and only fetch newly enacted matters")
    args = ap.parse_args()

    for d in (DATA, TEXT_CACHE, LAW_CACHE):
        d.mkdir(parents=True, exist_ok=True)

    # Prior records let --incremental work in CI, where cache/ doesn't exist
    prior: dict[str, dict] = {}
    if args.incremental and LAWS_JSON.exists():
        for rec in json.loads(LAWS_JSON.read_text()).get("laws", []):
            prior[rec["matter_id"]] = _normalize_record(rec)

    session = create_session()

    matters: list[tuple[str, str]] = []
    seen: set[str] = set()
    for year in args.years:
        for mid, guid in search_enacted_intros(session, year):
            if mid not in seen:
                seen.add(mid)
                matters.append((mid, guid))
        time.sleep(2)
    log.info(f"Total unique enacted Introductions: {len(matters)}")

    records = []
    for i, (mid, guid) in enumerate(matters, 1):
        cache_file = LAW_CACHE / f"{mid}.json"
        if args.incremental and mid in prior:
            records.append(prior[mid])
            continue
        if args.incremental and cache_file.exists():
            records.append(_normalize_record(json.loads(cache_file.read_text())))
            continue

        rec = fetch_law(session, mid, guid)
        if rec is None:
            continue
        if rec["status"] != "Enacted" or rec["matter_type"] != "Introduction":
            log.info(f"  [{i}] skip {rec['file_number']}: "
                     f"{rec['matter_type']}/{rec['status']}")
            continue
        # Some laws publish only a pointer ("A COPY OF INT. NO. ... CAN BE FOUND
        # UNDER ATTACHMENTS") and keep the enacted text in an attachment. The
        # re-extraction path already knew how to read those; the primary path
        # did not, so such a law cached an 86-character stub and every duty in
        # it was invisible. Fall back to the attachment here, at the point the
        # text is first cached, so no later stage has to compensate.
        if not rec["_text"] or "Be it enacted" not in rec["_text"]:
            recovered = None
            try:
                from reextract_queued import attachment_text
                recovered = attachment_text(rec.get("_html") or "")
            except Exception as e:                      # noqa: BLE001
                log.warning(f"  [{i}] attachment fallback failed: {e}")
            if recovered and len(recovered) > len(rec["_text"] or ""):
                log.info(f"  [{i}] {rec['file_number']}: recovered "
                         f"{len(recovered)} chars from an attachment")
                rec["_text"] = recovered
                rec["text_chars"] = len(recovered)
                rec["text_sha1"] = hashlib.sha1(recovered.encode()).hexdigest()
            else:
                log.warning(f"  [{i}] {rec['file_number']}: no enacted text found "
                            f"({rec['text_chars']} chars)")

        (TEXT_CACHE / f"{mid}.txt").write_text(rec["_text"])
        meta = {k: v for k, v in rec.items() if not k.startswith("_")}
        cache_file.write_text(json.dumps(meta, indent=1))
        records.append(meta)
        log.info(f"  [{i}/{len(matters)}] {rec['file_number']} "
                 f"{rec['law_number_display']} ({rec['text_chars']} chars)")
        time.sleep(1)

    records.sort(key=lambda r: (r.get("enactment_date") or "", r["file_number"]),
                 reverse=True)
    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "years": args.years,
        "count": len(records),
        "laws": records,
    }
    LAWS_JSON.write_text(json.dumps(out, indent=1))
    log.info(f"Wrote {LAWS_JSON}: {len(records)} laws")


if __name__ == "__main__":
    main()
