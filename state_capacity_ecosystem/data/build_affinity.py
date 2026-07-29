"""
Build affinity graph + directory data + semantic-search index for the
State Capacity Ecosystem tool.

Affinity score (composite, 0–1) — rebalanced May 2026 to surface surprise
connections instead of obvious same-segment pairings:

  composite = 0.40 * description_TFIDF_cosine
            + 0.30 * problem_statement_jaccard
            + 0.15 * named_funder_jaccard
            + 0.15 * segment_overlap_jaccard

The segment signal is intentionally de-weighted (and the primary-segment
boost dropped) so the network surfaces cross-segment affinities. Problem
statements — Henry Grunzweig's tags, present on every org — replace the
old same-segment dominance with shared-problem dominance.

The script also writes a separate affinity_search.json containing a term
vocabulary and per-org sparse TF-IDF vectors so the front-end can do
ranked semantic search at query time without an external embedding API.
"""

import csv, json, re, math
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CSV  = ROOT / "directory.csv"
OUT  = ROOT

# Known funders likely to appear in Funding Detail. Extracted lazily and used
# for named-funder overlap. Keep names as they typically appear; matching is
# case-insensitive and tolerant of minor spelling variants.
KNOWN_FUNDERS = [
    "Schmidt Futures", "Schmidt Sciences", "Open Philanthropy", "Omidyar Network",
    "Omidyar", "Ford Foundation", "Hewlett Foundation", "MacArthur Foundation",
    "Knight Foundation", "Bloomberg Philanthropies", "Gates Foundation",
    "Walton Family Foundation", "Walton Foundation", "Rockefeller Foundation",
    "Robert Wood Johnson Foundation", "RWJF", "Carnegie Corporation",
    "Kresge Foundation", "Surdna Foundation", "Sloan Foundation",
    "Heising-Simons Foundation", "Heising-Simons", "Patrick J. McGovern Foundation",
    "McGovern Foundation", "Doris Duke", "Arnold Ventures", "Laura and John Arnold",
    "Pew Charitable Trusts", "Pew", "Public Interest Tech Fund", "Public Interest Technology",
    "Skoll Foundation", "Skoll", "Mozilla Foundation", "Mozilla",
    "Democracy Fund", "Luminate", "Hopewell Fund", "Tides Foundation",
    "New Venture Fund", "Arabella Advisors", "Borealis Philanthropy",
    "Lever for Change", "Emerson Collective",
    "Schwartz Reisman", "Mellon Foundation", "Joyce Foundation",
    "8VC", "a16z", "Andreessen Horowitz", "Govtech Fund", "Govtech Ventures",
    "Commonweal Ventures", "Commonweal", "Kapor Capital", "Socium Ventures",
    "True Ventures", "First Round", "USDS",
    "DARPA", "NSF", "National Science Foundation",
    "Federal Government", "State Government",
]
# Sort by length so we match longer names first (e.g. "Open Philanthropy" before "Omidyar").
KNOWN_FUNDERS = sorted(set(KNOWN_FUNDERS), key=len, reverse=True)

STOPWORDS = set("""
a an the and or but if then so of in on at to for from with by about into over
through across under above between among against during before after up down out
off on as is are was were be been being have has had do does did doing this that
these those there here it its their our your his her my we they them us i you he
she who whom what which whose when where why how all any both each few more most
other some such no nor not only own same than too very can will just dont don't
also like across around within towards toward whether including include includes
focused focus orgs org organization organizations including help helps support
supports work works working primarily aimed via using used use makes make built
based across nation country wide range provide provides build building grow growing
new york nyc states programs program program's
""".split())

WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z\-]+")


def normalize(text: str) -> str:
    return (text or "").strip()


def tokens(text: str):
    return [t.lower() for t in WORD_RE.findall(text or "") if t.lower() not in STOPWORDS and len(t) > 2]


def parse_segments(primary: str, secondary: str):
    primary = normalize(primary)
    sec_list = [s.strip() for s in (secondary or "").split(",") if s.strip()]
    all_segs = [primary] + sec_list if primary else sec_list
    return primary, set(all_segs)


def parse_focus(focus: str):
    return [s.strip() for s in (focus or "").split(",") if s.strip()]


def parse_problem_statements(value: str):
    return [s.strip() for s in (value or "").split(",") if s.strip()]


def extract_funders(detail: str):
    detail = (detail or "")
    found = set()
    low = detail.lower()
    for name in KNOWN_FUNDERS:
        if name.lower() in low:
            # Canonicalize a couple of common aliases.
            canon = name
            if canon == "RWJF": canon = "Robert Wood Johnson Foundation"
            if canon == "Schmidt Sciences": canon = "Schmidt Futures"
            if canon == "Omidyar": canon = "Omidyar Network"
            if canon == "Skoll": canon = "Skoll Foundation"
            if canon == "Mozilla": canon = "Mozilla Foundation"
            if canon == "Pew": canon = "Pew Charitable Trusts"
            if canon == "Walton Foundation": canon = "Walton Family Foundation"
            if canon == "Public Interest Technology": canon = "Public Interest Tech Fund"
            if canon == "McGovern Foundation": canon = "Patrick J. McGovern Foundation"
            if canon == "Heising-Simons": canon = "Heising-Simons Foundation"
            if canon == "Laura and John Arnold": canon = "Arnold Ventures"
            if canon == "Andreessen Horowitz": canon = "a16z"
            if canon == "Commonweal": canon = "Commonweal Ventures"
            if canon == "National Science Foundation": canon = "NSF"
            found.add(canon)
    return found


# ── Load ─────────────────────────────────────────────────────────────────────
with open(CSV, encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

orgs = []
for r in rows:
    name = normalize(r["Org Name"])
    if not name:
        continue
    primary_seg, all_segs = parse_segments(r["Primary Segment"], r["Secondary Segments"])
    funders = extract_funders(r["Funding Detail"])
    desc = normalize(r["Description"])
    orgs.append({
        "id": len(orgs),
        "name": name,
        "primary_segment": primary_seg,
        "segments": sorted(all_segs),
        "focus": parse_focus(r["Focus"]),
        "description": desc,
        "funding_model": normalize(r["Funding Model"]),
        "funding_detail": normalize(r["Funding Detail"]),
        "named_funders": sorted(funders),
        "website": normalize(r["Website"]),
        # Schema May 2026: the old "Problem Statements" column was split into
        # "Problem Area" (7 coarse buckets) and "Problem Topic" (36 fine tags).
        # We map Topic → problem_statements (same granularity as before, so the
        # existing UI + Jaccard signal carry over) and capture Area separately.
        "problem_statements": parse_problem_statements(
            r.get("Problem Topic") or r.get("Problem Statements", "")
        ),
        "problem_areas": parse_problem_statements(r.get("Problem Area", "")),
        # Token bag used for TF-IDF — folds in problem topics + areas + segments
        # so a free-text query like "procurement" can hit orgs whose description
        # never says the word but whose tags do.
        "_tokens": tokens(
            desc + " "
            + r.get("Funding Detail", "") + " "
            + (r.get("Problem Topic") or r.get("Problem Statements", "")).replace(",", " ") + " "
            + r.get("Problem Area", "").replace(",", " ") + " "
            + r.get("Primary Segment", "") + " "
            + r.get("Secondary Segments", "").replace(",", " ")
        ),
    })

n = len(orgs)
print(f"Loaded {n} orgs.")

# ── TF-IDF on descriptions ───────────────────────────────────────────────────
df = Counter()
for o in orgs:
    df.update(set(o["_tokens"]))
N = n
idf = {term: math.log((1 + N) / (1 + d)) + 1 for term, d in df.items()}

vecs = []
for o in orgs:
    tf = Counter(o["_tokens"])
    if not tf:
        vecs.append({})
        continue
    vec = {term: f * idf.get(term, 0) for term, f in tf.items()}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    vecs.append({k: v / norm for k, v in vec.items()})

def cosine(a, b):
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0) for k, v in a.items())


# ── Pairwise similarity ──────────────────────────────────────────────────────
def segment_sim(a, b):
    # Plain Jaccard, no primary-segment boost — we deliberately want the
    # graph to NOT collapse into same-segment cliques.
    sa, sb = set(a["segments"]), set(b["segments"])
    union = sa | sb
    if not union:
        return 0.0
    return len(sa & sb) / len(union)


def problem_sim(a, b):
    pa, pb = set(a["problem_statements"]), set(b["problem_statements"])
    if not pa or not pb:
        return 0.0
    return len(pa & pb) / len(pa | pb)


def funder_sim(a, b):
    fa, fb = set(a["named_funders"]), set(b["named_funders"])
    if not fa or not fb:
        # Fall back to funding-model match as a weak signal so orgs with no
        # extractable named funders aren't permanently isolated.
        if a["funding_model"] and a["funding_model"] == b["funding_model"]:
            return 0.15
        return 0.0
    inter = fa & fb
    if not inter:
        return 0.0
    return len(inter) / len(fa | fb)


# Weights — sum to 1.0. See module docstring for rationale.
W_DESC, W_PROB, W_FUND, W_SEG = 0.40, 0.30, 0.15, 0.15

edges_raw = []
for i in range(n):
    for j in range(i + 1, n):
        ds = cosine(vecs[i], vecs[j])
        ps = problem_sim(orgs[i], orgs[j])
        fs = funder_sim(orgs[i], orgs[j])
        ss = segment_sim(orgs[i], orgs[j])
        composite = W_DESC*ds + W_PROB*ps + W_FUND*fs + W_SEG*ss
        if composite < 0.05:
            continue
        edges_raw.append({
            "source": i, "target": j,
            "weight": round(composite, 4),
            "desc": round(ds, 4),
            "prob": round(ps, 4),
            "fund": round(fs, 4),
            "seg":  round(ss, 4),
        })

edges_raw.sort(key=lambda e: -e["weight"])
print(f"Computed {len(edges_raw)} candidate edges (composite ≥ 0.05).")
print(f"Score distribution: max={edges_raw[0]['weight']:.3f}  median≈{edges_raw[len(edges_raw)//2]['weight']:.3f}  min={edges_raw[-1]['weight']:.3f}")


# ── Edge thresholding: keep up to N strongest edges per node, plus a global cap.
# Henry observed that an unfiltered graph becomes a hairball, so we limit each
# node's degree. This preserves the strongest cross-segment bridges without
# letting any single hub dominate.
MAX_DEG = 8     # per-node cap on outgoing edges in the kept set
MIN_W   = 0.10  # absolute floor

degree = Counter()
edges = []
for e in edges_raw:
    if e["weight"] < MIN_W:
        break
    if degree[e["source"]] >= MAX_DEG and degree[e["target"]] >= MAX_DEG:
        continue
    edges.append(e)
    degree[e["source"]] += 1
    degree[e["target"]] += 1

print(f"Kept {len(edges)} edges after thresholding (cap deg={MAX_DEG}, w≥{MIN_W}).")


# ── Node degrees ─────────────────────────────────────────────────────────────
final_deg = Counter()
for e in edges:
    final_deg[e["source"]] += 1
    final_deg[e["target"]] += 1


# ── Emit ─────────────────────────────────────────────────────────────────────
nodes_out = [{
    "id": o["id"],
    "name": o["name"],
    "primary_segment": o["primary_segment"],
    "segments": o["segments"],
    "focus": o["focus"],
    "description": o["description"],
    "funding_model": o["funding_model"],
    "funding_detail": o["funding_detail"],
    "named_funders": o["named_funders"],
    "website": o["website"],
    "problem_statements": o["problem_statements"],
    "problem_areas": o["problem_areas"],
    "degree": final_deg.get(o["id"], 0),
} for o in orgs]

(OUT / "affinity.json").write_text(json.dumps({
    "nodes": nodes_out,
    "edges": edges,
    "stats": {
        "org_count": n,
        "edge_count": len(edges),
        "max_weight": edges_raw[0]["weight"] if edges_raw else 0,
        "median_weight": edges_raw[len(edges_raw)//2]["weight"] if edges_raw else 0,
        "last_updated": date.today().isoformat(),
    },
}, indent=None, separators=(",", ":")))

# Directory file: same node list without the graph metadata so the directory
# subpage can ship its own bundle.
(OUT / "directory.json").write_text(json.dumps(nodes_out, indent=None, separators=(",", ":")))

# ── Semantic-search index ────────────────────────────────────────────────────
# Ship a vocab + per-org sparse TF-IDF vectors so the front-end can rank orgs
# against an arbitrary natural-language query without round-tripping to an
# embedding API. Cost at query time: O(num_query_terms × num_orgs).
vocab_list = sorted(idf.keys())
vocab_idx  = {t: i for i, t in enumerate(vocab_list)}
idf_list   = [round(idf[t], 4) for t in vocab_list]

search_vectors = []
for v in vecs:
    # {term_idx: weight} — only non-zero entries
    sparse = {vocab_idx[t]: round(w, 4) for t, w in v.items() if t in vocab_idx}
    search_vectors.append(sparse)

(OUT / "affinity_search.json").write_text(json.dumps({
    "vocab": vocab_list,
    "idf":   idf_list,
    "vectors": search_vectors,
    "stats": {
        "vocab_size": len(vocab_list),
        "avg_terms_per_org": round(sum(len(v) for v in search_vectors) / max(1, n), 1),
    },
}, indent=None, separators=(",", ":")))

print(f"Wrote {OUT/'affinity.json'}")
print(f"Wrote {OUT/'directory.json'}")
print(f"Wrote {OUT/'affinity_search.json'}  (vocab={len(vocab_list)}, avg terms/org={sum(len(v) for v in search_vectors)/max(1,n):.1f})")
