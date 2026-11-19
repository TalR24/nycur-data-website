"""Build the compact public export (data/site/) the five NYS pages read. The pages never load the working files.
Usage: python3 pipeline/build_site_data.py [--out DIR]. No network, no model calls."""
import datetime, glob, gzip, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")

# extraction provenance per session, for the methodology note (Tal/Nov 12 2026 orders)
EXTRACTION_NOTES = {"2025": "Extracted Nov 12 2026 through the API credit (Sonnet).",
                    "default": "Extracted on the Claude Max plan (subagent packets)."}

def load(p, default=None):
    try:
        with open(p) as f: return json.load(f)
    except FileNotFoundError:
        return default

def compact(r, kind_key, eff):
    """Short-key record: only what a table row, filter or evidence view needs."""
    o = {"i": r["obligation_id"], "l": r["matter_id"], "k": "d" if kind_key == "obligations" else "p",
         "a": r.get("agency"), "s": r.get("action_summary"), "q": r.get("quote"), "c": r.get("citation")}
    for key, val in (("au", r.get("agency_unit")), ("j", r.get("jurisdiction")),
                     ("dk", r.get("deadline_kind") if r.get("deadline_kind") != "none" else None),
                     ("dd", r.get("deadline_date")), ("rc", r.get("recurrence")),
                     ("ef", r.get("effective_date") or eff), ("hn", r.get("holder_note"))):
        if val not in (None, ""): o[key] = val
    if r.get("actor_raw") and (r["actor_raw"] or "").strip().lower() != (r.get("agency") or "").strip().lower():
        o["ar"] = r["actor_raw"]
    if r.get("extends_existing"): o["x"] = 1
    if r.get("multi_state"): o["ms"] = 1
    return o

def norm(n): return " ".join((n or "").lower().replace(".", "").split())

def build(data=DATA, out=None, today=None):
    out = out or os.path.join(data, "site")
    today = today or datetime.date.today().isoformat()
    cross = load(os.path.join(data, "agency_crosswalk_nys.json"), {"agencies": []})
    cag = {a["canonical"]: a for a in cross["agencies"]}
    members = load(os.path.join(data, "members.json"), [])
    by_name = {}
    for m in members: by_name.setdefault(norm(m["full_name"]), []).append(m)
    signed = {}
    for p in glob.glob(os.path.join(data, "signed", "*.json")):
        for l in load(p, []): signed[l["key"]] = l
    effs = {}
    for p in glob.glob(os.path.join(data, "effective_dates", "*.json")): effs.update(load(p, {}))
    sessions = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(data, "duties", "*.json")))
    os.makedirs(out, exist_ok=True)
    recs, laws, agencies, legs = {}, {}, {}, {}
    per_session = {}
    for y in sessions:
        rows = []
        for kk, d in (("obligations", "duties"), ("powers", "powers")):
            for r in (load(os.path.join(data, d, y + ".json"), {}) or {}).get(kk, []):
                key = r["matter_id"]; e = effs.get(key) or {}
                rows.append(compact(r, kk, e.get("effective_date")))
                L = laws.setdefault(key, {"key": key, "session": r["session"], "chapter": r["chapter"],
                    "chapter_year": r["chapter_year"], "law_number_display": r["law_number_display"],
                    "title": r["law_title"], "prime_sponsor": r.get("prime_sponsor") or (signed.get(key) or {}).get("sponsor"),
                    "signed": (signed.get(key) or {}).get("signed_date") or r.get("enactment_date"),
                    "effective_date": r.get("effective_date") or e.get("effective_date"),
                    "expires_date": r.get("law_expires_date") or e.get("expires_date"),
                    "openleg_url": r.get("openleg_url"), "duties": 0, "powers": 0})
                L["duties" if kk == "obligations" else "powers"] += 1
                A = agencies.setdefault(r["agency"], {"name": r["agency"], "full_name": r.get("agency_full") or r["agency"],
                    "org_type": (cag.get(r["agency"]) or {}).get("org_type") or r.get("agency_org_type"),
                    "duties": {}, "powers": {}, "laws": set(), "dl": []})
                A["duties" if kk == "obligations" else "powers"][y] = A["duties" if kk == "obligations" else "powers"].get(y, 0) + 1
                A["laws"].add(key)
                if r.get("multi_state"): A["multi_state"] = True
                if kk == "obligations" and r.get("deadline_date") and r["deadline_date"] >= today:
                    A["dl"].append({"date": r["deadline_date"], "law": key, "id": r["obligation_id"], "summary": r["action_summary"]})
        per_session[y] = {"duties": sum(1 for x in rows if x["k"] == "d"), "powers": sum(1 for x in rows if x["k"] == "p")}
        recs[y] = rows
    for y, rows in recs.items():
        with open(os.path.join(out, "records_%s.json" % y), "w") as f: json.dump(rows, f, separators=(",", ":"))
    law_list = sorted(laws.values(), key=lambda l: (l["session"], l["chapter_year"], l["chapter"]))
    for A in agencies.values():
        A["laws"] = len(A["laws"]); A["next_deadlines"] = sorted(A.pop("dl"), key=lambda x: x["date"])[:5]
    ag_list = sorted(agencies.values(), key=lambda a: -(sum(a["duties"].values()) + sum(a["powers"].values())))
    # legislators: prime sponsor of each law that creates records; chamber from the bill prefix
    for l in law_list:
        sp = l["prime_sponsor"]
        if not sp: continue
        pn = (signed.get(l["key"]) or {}).get("print_no") or l["key"].split("-", 1)[1]
        ch = "Senate" if pn[:1] == "S" else "Assembly"
        g = legs.setdefault((norm(sp), ch), {"name": sp, "chamber": ch, "districts": set(), "member_id": None,
                                             "laws": 0, "duties": 0, "powers": 0, "sessions": set()})
        g["laws"] += 1; g["duties"] += l["duties"]; g["powers"] += l["powers"]; g["sessions"].add(l["session"])
        for m in by_name.get(norm(sp), []):
            if m["chamber"] == ch and m["session"] == l["session"]:
                g["member_id"] = m["member_id"]
                if m.get("district"): g["districts"].add(m["district"])
    leg_list = []
    for g in sorted(legs.values(), key=lambda g: -(g["duties"] + g["powers"])):
        g["districts"] = sorted(g["districts"]); g["sessions"] = sorted(g["sessions"])
        g["matched"] = g["member_id"] is not None
        leg_list.append(g)
    tot_d = sum(v["duties"] for v in per_session.values()); tot_p = sum(v["powers"] for v in per_session.values())
    summary = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds"), "duties": tot_d, "powers": tot_p,
               "records": tot_d + tot_p, "laws": len(law_list), "agencies": len(ag_list), "legislators": len(leg_list),
               "sessions": [{"session": int(y), **per_session[y], "extraction_note": EXTRACTION_NOTES.get(y, EXTRACTION_NOTES["default"])} for y in sessions]}
    for name, obj in (("laws", law_list), ("agencies", ag_list), ("legislators", leg_list), ("summary", summary)):
        with open(os.path.join(out, name + ".json"), "w") as f: json.dump(obj, f, separators=(",", ":"))
    return summary

if __name__ == "__main__":
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    s = build(out=out)
    od = out or os.path.join(DATA, "site")
    print("totals: duties %d powers %d laws %d agencies %d legislators %d" % (s["duties"], s["powers"], s["laws"], s["agencies"], s["legislators"]))
    for p in sorted(glob.glob(os.path.join(od, "*.json"))):
        raw = os.path.getsize(p); gz = len(gzip.compress(open(p, "rb").read()))
        print("%-22s raw %7.2f MB  gzip %6.2f MB" % (os.path.basename(p), raw / 1e6, gz / 1e6))
