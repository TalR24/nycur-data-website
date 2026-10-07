"""Fetch bills from OpenLeg and write normalized records.
Usage: python3 fetch_bills.py --ids ../data/pilot.json   (pilot)
Signed bills also get their active text and (Senate) sponsor memo cached under pipeline/cache/."""
import argparse, json, os, re, time
import openleg

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
CACHE = os.path.join(HERE, "cache")

CHAP_RE = re.compile(r"SIGNED\s+CHAP(?:TER)?\s*\.?\s*(\d+)", re.I)
STATUS_TYPES = {  # OpenLeg statusType -> tracker stage
    "INTRODUCED": "introduced", "IN_SENATE_COMM": "in_committee", "IN_ASSEMBLY_COMM": "in_committee",
    "SENATE_FLOOR": "on_floor", "ASSEMBLY_FLOOR": "on_floor", "PASSED_SENATE": "passed_one_house",
    "PASSED_ASSEMBLY": "passed_one_house", "DELIVERED_TO_GOV": "delivered_to_governor",
    "SIGNED_BY_GOV": "signed", "VETOED": "vetoed", "STRICKEN": "stricken", "LOST": "lost",
    "SUBSTITUTED": "substituted", "ADOPTED": "adopted", "SIGNED_BY_GOV_CHAPTERED": "signed",
}


def parse_chapter(text):
    """Chapter number from an action like 'SIGNED CHAP.151', else None."""
    m = CHAP_RE.search(text or "")
    return int(m.group(1)) if m else None


def chamber_from_print_no(print_no):
    c = (print_no or "").strip().upper()[:1]
    return {"S": "Senate", "A": "Assembly"}.get(c)


def map_status(status_type):
    return STATUS_TYPES.get(status_type, "other")


def _member(m):
    if not m:
        return None
    return {"member_id": m.get("memberId"), "full_name": m.get("fullName"), "short_name": m.get("shortName"),
            "district": m.get("districtCode"), "chamber": (m.get("chamber") or "").title() or None}


def _members(block):
    return [_member(m) for m in ((block or {}).get("items") or [])]


def _refs(block):
    return [{"print_no": r.get("printNo"), "session": r.get("session")} for r in ((block or {}).get("items") or [])]


def _rules_sponsor(sponsor):
    """Rules Committee bills carry no member: sponsor.rules is true (2009-A42007)."""
    if sponsor.get("rules"):
        return {"member_id": None, "full_name": "Rules Committee", "short_name": "RULES", "district": None, "chamber": None, "rules": True}
    return None


def normalize(r):
    av = r.get("activeVersion") or ""
    amend = (r.get("amendments") or {}).get("items", {}).get(av) or {}
    st = r.get("status") or {}
    actions = [{"date": x.get("date"), "text": x.get("text"), "chamber": (x.get("chamber") or "").title() or None}
               for x in ((r.get("actions") or {}).get("items") or [])]
    chapter = None
    for x in actions:
        n = parse_chapter(x["text"])
        if n is not None:
            chapter = {"number": n, "year": int(x["date"][:4]), "signed_date": x["date"]}
    veto_items = (r.get("vetoMessages") or {}).get("items") or []
    vetoed = bool(r.get("vetoed"))
    sponsor = r.get("sponsor") or {}
    sub = r.get("substitutedBy")
    bt = r.get("billType") or {}
    sess = r["session"]
    return {
        "session": sess, "print_no": r.get("printNo"), "base_print_no": r.get("basePrintNo"),
        "chamber": (bt.get("chamber") or "").title() or chamber_from_print_no(r.get("basePrintNo")),
        "is_resolution": bool(bt.get("resolution")),
        "title": r.get("title"), "summary": r.get("summary"),
        "sponsor": _member(sponsor.get("member")) or _rules_sponsor(sponsor),
        "cosponsors": _members(amend.get("coSponsors")), "multisponsors": _members(amend.get("multiSponsors")),
        "committee": st.get("committeeName"),
        "status": {"type": st.get("statusType"), "desc": st.get("statusDesc"), "date": st.get("actionDate"),
                   "stage": map_status(st.get("statusType"))},
        "milestones": [{"type": m.get("statusType"), "desc": m.get("statusDesc"), "date": m.get("actionDate"),
                        "committee": m.get("committeeName")} for m in ((r.get("milestones") or {}).get("items") or [])],
        "actions": actions,
        "signed": bool(r.get("signed")), "chapter": chapter,
        "vetoed": vetoed,
        "veto": [{"number": v.get("vetoNumber"), "year": v.get("year"), "type": v.get("type"), "date": v.get("signedDate") or v.get("date")} for v in veto_items] if vetoed or veto_items else None,
        "same_as": _refs(amend.get("sameAs")),
        "substituted_by": ({"print_no": sub.get("printNo"), "session": sub.get("session")} if isinstance(sub, dict) else sub),
        "budget": bool(sponsor.get("budget")), "program_info": r.get("programInfo"),
        "law_section": amend.get("lawSection"), "law_code": amend.get("lawCode"), "act_clause": amend.get("actClause"),
        "active_version": av, "published_at": r.get("publishedDateTime"),
        "openleg_url": "https://www.nysenate.gov/legislation/bills/%s/%s" % (sess, r.get("basePrintNo")),
    }


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(text)


def fetch_one(session, print_no, signed_hint=False):
    """Returns the normalized record. Signed bills are fetched in the default view (one call) so the
    active text and memo can be cached; others use no_fulltext."""
    base = "/api/3/bills/%s/%s" % (session, print_no)
    d = openleg.get(base, {"view": "no_fulltext"})
    if d is None:
        return None
    r = d["result"]
    rec = normalize(r)
    if rec["signed"]:
        full = openleg.get(base, {"fullTextFormat": "PLAIN"})["result"]
        av = full.get("activeVersion") or ""
        a = (full.get("amendments") or {}).get("items", {}).get(av) or {}
        key = "%s-%s" % (session, rec["base_print_no"])
        _write(os.path.join(CACHE, "text", key + ".txt"), a.get("fullText") or "")
        rec["text_cached"] = bool(a.get("fullText"))
        if rec["chamber"] == "Senate" and a.get("memo"):
            _write(os.path.join(CACHE, "memo", key + ".txt"), a["memo"])
            rec["memo_cached"] = True
        else:
            rec["memo_cached"] = False
    return rec


# ── Full-session mode (phase 3a) ────────────────────────────────────────────────────────────────────────────────────
# The listing endpoint with full=true returns every field the tracker needs for 1,000 bills per request (about 36 KB a bill
# with both text formats, 7 s a page); per-bill calls would be one request per bill at 3.7 requests a second.
COLS = ["session", "print_no", "base_print_no", "chamber", "is_resolution", "title", "sponsor_id", "sponsor", "cosponsors",
        "committee", "status", "status_date", "signed", "chapter", "chapter_year", "vetoed", "same_as", "law_section", "published"]
PAGE = 1000
FULL = os.path.join(CACHE, "bills_full")
INDEX_DIR = os.path.join(DATA, "bills")


def index_row(rec):
    """One compact index row (list, in COLS order) from a normalized bill record."""
    sp = rec.get("sponsor") or {}
    ch = rec.get("chapter") or {}
    st = rec.get("status") or {}
    return [rec["session"], rec["print_no"], rec["base_print_no"], rec["chamber"], bool(rec["is_resolution"]),
            (rec.get("title") or "")[:300], sp.get("member_id"), sp.get("short_name"),
            len(rec.get("cosponsors") or []), rec.get("committee"), st.get("type"), st.get("date"), bool(rec.get("signed")),
            ch.get("number"), ch.get("year"), bool(rec.get("vetoed")),
            ",".join(r["print_no"] for r in (rec.get("same_as") or []) if r.get("print_no")),
            rec.get("law_section"), (rec.get("published_at") or "")[:10]]


def cache_signed_text(item, rec):
    """Signed bills: keep the active version's text (HTML where the API has it, plain otherwise) and the Senate memo."""
    if not rec["signed"]:
        return False
    av = item.get("activeVersion") or ""
    a = (item.get("amendments") or {}).get("items", {}).get(av) or {}
    key = "%s-%s" % (rec["session"], rec["base_print_no"])
    got = False
    if a.get("fullTextHtml"):
        _write(os.path.join(CACHE, "html", key + ".html"), a["fullTextHtml"]); got = True
    if a.get("fullText"):
        _write(os.path.join(CACHE, "text", key + ".txt"), a["fullText"]); got = True
    if rec["chamber"] == "Senate" and a.get("memo"):
        _write(os.path.join(CACHE, "memo", key + ".txt"), a["memo"])
    return got


def law_record(b):
    """The per-law dict the extractor needs (chapter, signing date, act clause, law section) from a normalized signed bill."""
    key = "%s-%s" % (b["session"], b["base_print_no"])
    return {"matter_id": key, "key": key, "session": b["session"], "print_no": b["base_print_no"],
            "chapter_number": b["chapter"]["number"], "chapter_year": b["chapter"]["year"],
            "signed_date": b["chapter"]["signed_date"], "enactment_date": b["chapter"]["signed_date"],
            "title": b["title"], "act_clause": b.get("act_clause"), "law_section": b.get("law_section"),
            "sponsor": (b.get("sponsor") or {}).get("full_name"), "openleg_url": b.get("openleg_url"),
            "law_number_display": "Chapter %d of %d" % (b["chapter"]["number"], b["chapter"]["year"])}


def run_session(session, resume=False, limit=None):
    os.makedirs(FULL, exist_ok=True)
    os.makedirs(INDEX_DIR, exist_ok=True)
    part = os.path.join(FULL, "%d.jsonl" % session)
    done = 0
    if resume and os.path.exists(part):
        with open(part) as f:
            done = sum(1 for _ in f)
    elif os.path.exists(part):
        os.remove(part)
    t0, nbytes, calls = time.time(), 0, 0
    total = None
    while True:
        want = PAGE if limit is None else min(PAGE, limit - done)
        if want <= 0:
            break
        raw = openleg.get("/api/3/bills/%d" % session, {"limit": want, "offset": done + 1, "full": "true",
                                                         "fullTextFormat": ["HTML", "PLAIN"]}, raw=True)
        calls += 1
        nbytes += len(raw)
        d = json.loads(raw)
        total = d.get("total", total)
        items = ((d.get("result") or {}).get("items")) or []
        if not items:
            break
        lines = []
        for it in items:
            item = it.get("result", it)
            rec = normalize(item)
            rec["text_cached"] = cache_signed_text(item, rec)
            lines.append(json.dumps(rec, separators=(",", ":")))
        with open(part, "a") as f:                      # the checkpoint: one append per page of 1,000 bills
            f.write("\n".join(lines) + "\n")
        done += len(items)
        print("session %d: %d of %s bills, %d requests, %.0f s, %.1f MB" % (session, done, total, calls, time.time() - t0, nbytes / 1e6), flush=True)
        if total is not None and done >= total:
            break
    rows, laws = [], []
    with open(part) as f:
        for ln in f:
            rec = json.loads(ln)
            rows.append(index_row(rec))
            if rec.get("chapter") and rec["status"]["type"] == "SIGNED_BY_GOV":
                laws.append(law_record(rec))
    os.makedirs(os.path.join(DATA, "signed"), exist_ok=True)
    json.dump(laws, open(os.path.join(DATA, "signed", "%d.json" % session), "w"), separators=(",", ":"), ensure_ascii=False)
    out = os.path.join(INDEX_DIR, "%d.json" % session)
    json.dump({"session": session, "generated": time.strftime("%Y-%m-%d", time.gmtime()), "total_in_api": total, "cols": COLS, "rows": rows},
              open(out, "w"), separators=(",", ":"), ensure_ascii=False)
    size = os.path.getsize(out)
    print("index %s: %d rows, %.2f MB; %d requests (+%d retries), %.0f s, %.1f MB downloaded" % (out, len(rows), size / 1e6, calls, openleg.STATS["retries"], time.time() - t0, nbytes / 1e6))
    return {"rows": len(rows), "bytes": size, "requests": calls, "seconds": time.time() - t0, "download_bytes": nbytes}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="pilot.json")
    ap.add_argument("--session", type=int, help="fetch a whole session through the listing endpoint")
    ap.add_argument("--resume", action="store_true", help="continue from the cached checkpoint")
    ap.add_argument("--limit", type=int, help="stop after this many bills")
    ap.add_argument("--out", default=os.path.join(DATA, "bills.json"))
    a = ap.parse_args()
    if a.session:
        run_session(a.session, a.resume, a.limit)
        return
    ids = json.load(open(a.ids))["bills"]
    t0 = time.time()
    recs, missing = [], []
    for i, b in enumerate(ids):
        rec = fetch_one(b["session"], b["print_no"])
        if rec is None:
            missing.append(b)
            continue
        rec["pilot_stratum"] = b.get("stratum")
        recs.append(rec)
        if (i + 1) % 50 == 0:
            print(i + 1, "fetched", flush=True)
    json.dump(recs, open(a.out, "w"), indent=1)
    print("records", len(recs), "missing", missing, "seconds", round(time.time() - t0), openleg.STATS)


if __name__ == "__main__":
    main()
