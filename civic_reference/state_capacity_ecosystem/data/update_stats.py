#!/usr/bin/env python3
"""
Patch hardcoded stat strings after a CSV rebuild.
Run from civic_reference/state_capacity_ecosystem/ (not from data/).
Called by the GitHub Actions refresh workflow after build_affinity.py and build_people.py.
"""
import json
import re
from pathlib import Path

aff  = json.loads(Path("data/affinity.json").read_text())
dirs = json.loads(Path("data/directory.json").read_text())

s          = aff["stats"]
org_count  = s["org_count"]
edge_count = s["edge_count"]
max_w      = round(s["max_weight"], 2)
median_w   = round(s["median_weight"], 2)
topics     = {t for o in dirs for t in o.get("problem_statements", [])}
funded     = sum(1 for o in dirs if o.get("named_funders"))


def sub(text, pattern, replacement, label, flags=re.DOTALL):
    result, n = re.subn(pattern, replacement, text, flags=flags)
    if n == 0:
        raise ValueError(f"Pattern not found in {label!r}:\n  {pattern!r}")
    print(f"  {label}: {n} match(es) replaced")
    return result


# ── 1. data_website/index.html (homepage card-stat) ──
p = Path("../../index.html")
html = p.read_text()
html = sub(
    html,
    r"\d+ orgs · 11 segments · \d+ problem topics",
    f"{org_count} orgs · 11 segments · {len(topics)} problem topics",
    "data_website/index.html",
)
p.write_text(html)

# ── 2. data_website/README.md (file-tree row count) ──
p = Path("../../README.md")
md = p.read_text()
md = sub(
    md,
    r"state_capacity_ecosystem\.csv(\s+)→ Canonical org source \(\d+ rows\)",
    lambda m: f"state_capacity_ecosystem.csv{m.group(1)}→ Canonical org source ({org_count} rows)",
    "data_website/README.md",
)
p.write_text(md)

# ── 3. methodology/index.html ──
p = Path("methodology/index.html")
html = p.read_text()
html = sub(
    html,
    r"Approximately \d+ of \d+ orgs have at least one named funder detected",
    f"Approximately {funded} of {org_count} orgs have at least one named funder detected",
    "methodology/index.html (funder callout)",
)
html = sub(
    html,
    r"<strong>\d+ nodes and [\d,]+ edges</strong>, with a maximum edge score of \d+\.\d+ and a median of \d+\.\d+",
    f"<strong>{org_count} nodes and {edge_count:,} edges</strong>, "
    f"with a maximum edge score of {max_w:.2f} and a median of {median_w:.2f}",
    "methodology/index.html (dataset stats line)",
)
p.write_text(html)

# ── 4. README.md (project README — three stat locations) ──
p = Path("README.md")
md = p.read_text()
md = sub(
    md,
    r"- \d+ orgs, [\d,]+ kept edges",
    f"- {org_count} orgs, {edge_count:,} kept edges",
    "project README.md (current dataset stats)",
)
md = sub(
    md,
    r"- Funder coverage: \d+/\d+ orgs",
    f"- Funder coverage: {funded}/{org_count} orgs",
    "project README.md (funder coverage)",
)
md = sub(
    md,
    r"For \d+ orgs with rich curator-assigned tags",
    f"For {org_count} orgs with rich curator-assigned tags",
    "project README.md (TF-IDF trade-off note)",
)
p.write_text(md)

print(
    f"\nAll stats updated: {org_count} orgs · {edge_count:,} edges · "
    f"{len(topics)} topics · {funded}/{org_count} funded"
)
