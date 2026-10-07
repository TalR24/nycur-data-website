"""Signed-law texts for one session: HTML (2017 on) or plain text, cached, then converted by text_markup to cache/text_marked/.
fetch_bills.py --session already caches the active text of every signed bill it lists; this script converts those and fetches
(one request each) any signed bill whose text is missing. Resumable: bills with a marked text are skipped.
Usage: python3 fetch_signed_texts.py --session 2017 [--limit N]"""
import argparse, json, os, time
import openleg, text_markup

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
DATA = os.path.join(HERE, "..", "data")
HTML_FROM = 2017      # the API serves underline markup only for the 2017-2018 session on


def signed_bills(session):
    """[(base_print_no)] of every SIGNED_BY_GOV bill of the session, from the full cache or the committed index."""
    out = []
    jl = os.path.join(CACHE, "bills_full", "%d.jsonl" % session)
    if os.path.exists(jl):
        for ln in open(jl):
            r = json.loads(ln)
            if r.get("signed") and (r.get("status") or {}).get("type") == "SIGNED_BY_GOV":
                out.append(r["base_print_no"])
        return out
    sg = os.path.join(DATA, "signed", "%d.json" % session)
    if os.path.exists(sg):
        return [l["print_no"] for l in json.load(open(sg))]
    idx = os.path.join(DATA, "bills", "%d.json" % session)
    d = json.load(open(idx))
    c = d["cols"]
    return [r[c.index("base_print_no")] for r in d["rows"] if r[c.index("status")] == "SIGNED_BY_GOV"]


def need_fetch(session, key):
    has_html = os.path.exists(os.path.join(CACHE, "html", key + ".html"))
    has_text = os.path.exists(os.path.join(CACHE, "text", key + ".txt"))
    return not (has_html if session >= HTML_FROM else has_text)


def fetch_one(session, base):
    key = "%d-%s" % (session, base)
    d = openleg.get("/api/3/bills/%d/%s" % (session, base), {"fullTextFormat": ["HTML", "PLAIN"]})
    if not d:
        return False
    r = d["result"]
    a = (r.get("amendments") or {}).get("items", {}).get(r.get("activeVersion") or "") or {}
    for sub, ext, field in (("html", ".html", "fullTextHtml"), ("text", ".txt", "fullText")):
        if a.get(field):
            os.makedirs(os.path.join(CACHE, sub), exist_ok=True)
            open(os.path.join(CACHE, sub, key + ext), "w").write(a[field])
    if a.get("memo") and base.startswith("S"):
        os.makedirs(os.path.join(CACHE, "memo"), exist_ok=True)
        open(os.path.join(CACHE, "memo", key + ".txt"), "w").write(a["memo"])
    return True


def run(session, limit=None):
    bills = signed_bills(session)
    if limit:
        bills = bills[:limit]
    os.makedirs(os.path.join(CACHE, "text_marked"), exist_ok=True)
    stats = {"signed": len(bills), "skipped_done": 0, "fetched": 0, "from_listing_cache": 0, "converted": 0, "no_text": 0}
    t0, r0 = time.time(), openleg.STATS["requests"]
    for base in bills:
        key = "%d-%s" % (session, base)
        out = os.path.join(CACHE, "text_marked", key + ".txt")
        if os.path.exists(out):
            stats["skipped_done"] += 1
            continue
        if need_fetch(session, key):
            if not fetch_one(session, base):
                stats["no_text"] += 1
                continue
            stats["fetched"] += 1
        else:
            stats["from_listing_cache"] += 1
        try:
            txt, src = text_markup.convert(key, HERE)
        except FileNotFoundError:
            stats["no_text"] += 1
            continue
        open(out, "w").write(txt)
        stats["converted"] += 1
    stats["requests"] = openleg.STATS["requests"] - r0
    stats["seconds"] = round(time.time() - t0)
    print("session %d:" % session, json.dumps(stats))
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", type=int, required=True)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    run(a.session, a.limit)
