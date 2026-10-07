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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="pilot.json")
    ap.add_argument("--out", default=os.path.join(DATA, "bills.json"))
    a = ap.parse_args()
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
