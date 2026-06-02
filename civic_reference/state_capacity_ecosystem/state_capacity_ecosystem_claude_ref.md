# State Capacity Ecosystem — Session Orientation

This file auto-loads at session start (per the project CLAUDE.md). It is a **pointer**, not the source of truth.

## Read this first

**`data_website/civic_reference/state_capacity_ecosystem/README.md`** is the comprehensive handoff doc. It contains:

- File layout, CSV schema, build pipeline
- Affinity-score formula and weight rationale
- Semantic-search index design
- Per-page behavior (Hub, Directory, Segments, Network, Methodology)
- Color palette (11 segments)
- Problem taxonomy (7 areas + 36 topics)
- GitHub push workflow
- Decisions to honor (do NOT silently reverse)
- Things to NOT change without thinking
- Parking lot of unbuilt improvements
- Cost guidance (when to use Sonnet vs Opus, when to `/compact`)
- Recent change log

**Always read that README before making changes to this tool.**

## High-signal facts (TL;DR)

- **Curator:** Henry Grunzweig (NOT "Henry Tolchard" — earlier sessions used the wrong name).
- **Visualization built by:** Tal Roded for NYCuriosity.
- **Live URL:** https://data.nycuriosity.com/civic_reference/state_capacity_ecosystem/
- **Current dataset:** 308 orgs, 1,653 affinity edges (refreshed 2026-06-01)
- **Affinity weights:** 0.40 description / 0.30 problem-topic / 0.15 funders / 0.15 segments. **No primary-segment boost.** Tuned to surface cross-segment surprise connections.
- **Schema (June 2026):** "Problem Area" has 7 buckets (Capacity removed); "Problem Topic" has 36 fine tags (was 37).
- **Semantic search:** TF-IDF index emitted by `build_affinity.py` as `search_index.json`. Client-side cosine similarity. No API.
- **GitHub remote URL** has the PAT baked in. PAT lives at `~/.claude/projects/.../memory/reference_github.md`.
- **Em dashes are banned** in NYCuriosity prose (per the global writing-style memory).
- **No links to Claude conversations** anywhere on the public site.

## Refresh workflow

```bash
# 1. Drop the new CSV in place of the canonical file
cp <new>.csv data_website/civic_reference/state_capacity_ecosystem/data/state_capacity_ecosystem.csv

# 2. Rebuild
cd data_website/civic_reference/state_capacity_ecosystem
python3 data/build_affinity.py

# 3. Push (remote URL already has PAT)
cd /Users/troded/Library/CloudStorage/OneDrive-Microsoft/Desktop/nycur/data_website
git add civic_reference/state_capacity_ecosystem/data/ ...
git commit -m "..."
git push
```

If hardcoded counts on the hub or methodology pages become stale, the README lists the exact lines to update.
