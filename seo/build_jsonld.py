#!/usr/bin/env python3
"""
Write schema.org JSON-LD into the <head> of the pages that benefit from it,
so search engines and AI answer engines can tell who publishes the site and
which pages are datasets. Built only from what the page and profile_facts.json
already say (title, meta description, canonical URL, public identity), so it
adds no new claims.

    python3 seo/build_jsonld.py --site data            # report what would change
    python3 seo/build_jsonld.py --site data --apply    # write it
    python3 seo/build_jsonld.py --all --apply

What gets a block:
    homepage, data      WebSite, published by Tal Roded
    homepage, personal  Person (identity and links from profile_facts.json)
    homepage, sce       Organization
    tool and hub pages  Dataset: data-site civic_reference/<tool>/, cb-tools/<tool>/
                        and nycuriosity_substack_posts/<post>/ (minus NOT_DATASETS);
                        SCE directory pages (SCE_DATASETS)
Everything else gets nothing. The block sits between <!-- jsonld:start --> and
<!-- jsonld:end --> before </head>; reruns replace it. build_sitemap.py runs
this in --apply mode, so a page copied from another one gets its own URL.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SITES, WORKSPACE, load_pages, repo_path  # noqa: E402

START, END = "<!-- jsonld:start -->", "<!-- jsonld:end -->"
BLOCK_RE = re.compile(re.escape(START) + r".*?" + re.escape(END) + r"\n?", re.S)
SUFFIX_RE = re.compile(r"\s+[—|]\s+(NYCuriosity|State Capacity Ecosystem|Tal Roded).*$")
# Standing decision (Tal, Aug 24 2026): no search attention on these until the post is out.
HOLD = ("/nycuriosity_substack_posts/medicaid_provider_spending/",)
DATASET_PREFIXES = {
    "data": ("civic_reference", "cb-tools", "nycuriosity_substack_posts"),
    "personal": (),
}
# Pages under those prefixes that are tools, demos or decks rather than data.
NOT_DATASETS = {
    "data": ("/cb-tools/roberts-rules-helper/", "/cb-tools/meeting-review/", "/cb-tools/school-of-data-2026/",
             "/cb-tools/block_party_july2026/", "/civic_reference/cb_member_guide/"),
}
# SCE: the directory pages only.
SCE_DATASETS = ("/ecosystem/", "/ecosystem/organizations/", "/ecosystem/connect/")


def profile():
    path = WORKSPACE / "personal_website" / "profile_facts.json"
    if not path.exists():
        path = repo_path("personal") / "profile_facts.json"
    ident = json.loads(path.read_text(encoding="utf-8"))["identity"]
    sites = ident.get("sites", {})
    return {
        "@type": "Person", "name": ident["name"], "url": sites.get("personal"),
        "sameAs": [u for k, u in sites.items() if k != "personal" and u],
        "address": {"@type": "PostalAddress", "addressLocality": "New York", "addressRegion": "NY"},
    }


def clean(t):
    return SUFFIX_RE.sub("", (t or "").strip())


def graph_for(key, page, person):
    url, head = page["abs"], page["head"]
    name, desc = clean(head.title), (head.meta.get("description") or "").strip()
    path = page["url"]
    if path == "/":
        if key == "data":
            return {"@context": "https://schema.org", "@type": "WebSite", "name": name, "url": url,
                    "description": desc, "inLanguage": "en-US",
                    "publisher": {k: v for k, v in person.items() if k in ("@type", "name", "url")}}
        if key == "personal":
            return {"@context": "https://schema.org", **person, "description": desc}
        if key == "sce":
            return {"@context": "https://schema.org", "@type": "Organization", "name": name, "url": url,
                    "description": desc, "logo": SITES["sce"]["base"] + SITES["sce"]["og_image"],
                    "sameAs": ["https://substack.statecapacityecosystem.com/"]}
    segs = [s for s in path.strip("/").split("/") if s]
    is_dataset = (path in SCE_DATASETS if key == "sce" else
                  len(segs) == 2 and segs[0] in DATASET_PREFIXES[key] and path.endswith("/")
                  and path not in NOT_DATASETS.get(key, ()))
    if is_dataset and not path.startswith(HOLD) and len(desc) >= 50:
        creator = ({k: v for k, v in person.items() if k in ("@type", "name", "url")} if key == "data" else
                   {"@type": "Organization", "name": "State Capacity Ecosystem", "url": SITES["sce"]["base"] + "/"})
        return {"@context": "https://schema.org", "@type": "Dataset", "name": name, "description": desc,
                "url": url, "creator": creator, "isAccessibleForFree": True, "inLanguage": "en-US",
                "spatialCoverage": {"@type": "Place", "name": "New York City"} if key == "data" else None}
    return None


def render(graph):
    graph = {k: v for k, v in graph.items() if v is not None}
    body = json.dumps(graph, ensure_ascii=False, indent=1)
    return f'{START}\n<script type="application/ld+json">\n{body}\n</script>\n{END}\n'


def apply_page(path, block):
    text = path.read_text(encoding="utf-8")
    if block is None:
        new = BLOCK_RE.sub("", text)
    elif BLOCK_RE.search(text):
        new = BLOCK_RE.sub(lambda _m: block, text, count=1)
    else:
        i = text.lower().find("</head>")
        if i < 0:
            return False
        new = text[:i] + block + text[i:]
    if new != text:
        path.write_text(new, encoding="utf-8")
        return True
    return False


def run(key, apply=False, repo=None):
    person = profile()
    root = repo_path(key, repo)
    changed = []
    for p in load_pages(key, repo):
        if p["kind"] != "live":
            continue
        graph = graph_for(key, p, person)
        block = render(graph) if graph else None
        path = root / p["rel"]
        has = bool(BLOCK_RE.search(p["html"]))
        if block is None and not has:
            continue
        current = BLOCK_RE.search(p["html"]).group(0) if has else None
        if current == block:
            continue
        changed.append((p["rel"], graph["@type"] if graph else "removed"))
        if apply:
            apply_page(path, block)
    return changed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", choices=sorted(SITES))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--repo")
    args = ap.parse_args()
    keys = sorted(SITES) if args.all else [args.site]
    if not keys or keys == [None]:
        ap.error("--site or --all")
    for key in keys:
        changed = run(key, args.apply, args.repo)
        verb = "updated" if args.apply else "would update"
        print(f"{key}: {verb} {len(changed)} page(s)")
        for rel, t in changed:
            print(f"  {t:13} {rel}")


if __name__ == "__main__":
    main()
