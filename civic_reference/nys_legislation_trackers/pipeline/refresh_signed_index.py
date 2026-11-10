#!/usr/bin/env python3
"""Keep data/signed/{session}.json current from the daily bill index. No model calls, no Anthropic key.

data/bills/{session}.json is refreshed daily from the Open Legislation change feed, but data/signed/{session}.json (the law
list the duty extraction reads) was only written by fetch_bills.py --session, so newly signed laws never reached extraction.
This script finds every row of the bill index that is SIGNED_BY_GOV with a chapter number and is missing from the signed
index, fetches just those bills (view=no_fulltext, needs NYS_OPENLEG_KEY) and appends their law records. Texts are fetched
later by fetch_signed_texts.py when extraction needs them.

  python3 refresh_signed_index.py                 refresh every session that has a signed index
  python3 refresh_signed_index.py --session 2025
  python3 refresh_signed_index.py --dry-run       list what is missing, fetch and write nothing (no key needed)
  python3 refresh_signed_index.py --check         exit 1 if a signed index is stale against its bill index (no key needed)

Staleness (STALE_DAYS = 10): a law the bill index shows as signed more than 10 days before the index date but absent from
the signed index, or a recorded refresh date more than 10 days older than the bill index date. Where the local packet cache
exists, --check also flags signed laws older than 10 days with no packet and no answer (next_packet_batch.gap_problems).
Writes data/signed_state.json {"refreshed": {"2025": "2026-11-10"}} so the refresh date is visible."""
import argparse, datetime as dt, json, os, sys
import fetch_bills

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
STATE = os.path.join(DATA, "signed_state.json")
STALE_DAYS = 10


def load_index(data, session):
    p = os.path.join(data, "bills", "%d.json" % session)
    return json.load(open(p)) if os.path.exists(p) else None


def signed_rows(doc):
    """[(base_print_no, chapter_number, status_date)] of every signed-with-chapter row of a bill index document."""
    c = doc["cols"]
    ib, iS, iC, iD = (c.index(k) for k in ("base_print_no", "status", "chapter", "status_date"))
    return [(r[ib], r[iC], r[iD]) for r in doc["rows"] if r[iS] == "SIGNED_BY_GOV" and r[iC] is not None]


def load_signed(data, session):
    p = os.path.join(data, "signed", "%d.json" % session)
    return json.load(open(p)) if os.path.exists(p) else None


def missing_laws(data, session):
    """Signed bills in the bill index that the signed index does not list yet: [(base_print_no, chapter, status_date)]."""
    doc, laws = load_index(data, session), load_signed(data, session)
    if doc is None or laws is None:
        return []
    have = {l["print_no"] for l in laws}
    return [t for t in signed_rows(doc) if t[0] not in have]


def stale_problems(data, today=None):
    """Human-readable problems, empty when every signed index is fresh against its bill index."""
    out = []
    state = json.load(open(os.path.join(data, "signed_state.json"))) if os.path.exists(os.path.join(data, "signed_state.json")) else {}
    for fn in sorted(os.listdir(os.path.join(data, "signed"))):
        session = int(fn.split(".")[0])
        doc = load_index(data, session)
        if doc is None:
            continue
        gen = dt.date.fromisoformat(doc["generated"])
        cutoff = (gen - dt.timedelta(days=STALE_DAYS)).isoformat()
        old = [t for t in missing_laws(data, session) if (t[2] or "9999") <= cutoff]
        if old:
            out.append("session %d: %d signed laws in the bill index (generated %s) are missing from the signed index and were signed on or before %s"
                       % (session, len(old), gen, cutoff))
        ref = (state.get("refreshed") or {}).get(str(session))
        if ref and (gen - dt.date.fromisoformat(ref)).days > STALE_DAYS:
            out.append("session %d: signed index last refreshed %s, %d days before the bill index (%s)" % (session, ref, (gen - dt.date.fromisoformat(ref)).days, gen))
    return out


def refresh_session(data, session, fetch=None, write=True):
    """Appends the missing laws to the signed index. fetch(session, print_no) returns a normalized bill record (default: the API).
    Returns the list of added keys."""
    miss = missing_laws(data, session)
    if not miss:
        return []
    if fetch is None:
        import openleg
        def fetch(sess, pn):
            d = openleg.get("/api/3/bills/%d/%s" % (sess, pn), {"view": "no_fulltext"})
            return fetch_bills.normalize(d["result"]) if d else None
    laws = load_signed(data, session)
    added = []
    for pn, chapter, _ in miss:
        rec = fetch(session, pn)
        if not rec or not rec.get("chapter") or (rec.get("status") or {}).get("type") != "SIGNED_BY_GOV":
            print("skipped %d-%s: the API does not show a signed chapter yet" % (session, pn))
            continue
        laws.append(fetch_bills.law_record(rec))
        added.append(laws[-1]["key"])
    if write and added:
        json.dump(laws, open(os.path.join(data, "signed", "%d.json" % session), "w"), separators=(",", ":"), ensure_ascii=False)
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        probs = stale_problems(DATA)
        import next_packet_batch
        probs += next_packet_batch.gap_problems()           # skipped cleanly where cache/packets is absent (CI)
        for p in probs:
            print("STALE:", p)
        print("signed index stale: %d problem(s)" % len(probs) if probs else "signed index fresh")
        sys.exit(1 if probs else 0)
    sessions = [a.session] if a.session else sorted(int(f.split(".")[0]) for f in os.listdir(os.path.join(DATA, "signed")))
    state = json.load(open(STATE)) if os.path.exists(STATE) else {"refreshed": {}}
    total = 0
    for s in sessions:
        if a.dry_run:
            m = missing_laws(DATA, s)
            print("session %d: %d signed laws missing from the signed index" % (s, len(m)))
            total += len(m)
            continue
        added = refresh_session(DATA, s)
        total += len(added)
        print("session %d: added %d laws" % (s, len(added)))
        if load_index(DATA, s) is not None:
            state.setdefault("refreshed", {})[str(s)] = dt.date.today().isoformat()
    if not a.dry_run:
        json.dump(state, open(STATE, "w"), indent=1)
    print("total %s: %d" % ("missing" if a.dry_run else "added", total))


if __name__ == "__main__":
    main()
