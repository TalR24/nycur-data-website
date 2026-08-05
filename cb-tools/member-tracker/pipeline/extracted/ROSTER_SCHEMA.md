# Roster extraction schema

One JSON file per board at `pipeline/extracted/rosters/<boro_cd>.json`,
produced from the cached pages in `pipeline/cache/pages/<boro_cd>/`
(initial pass: Claude in-session; refreshes: `extract_rosters.py` on boards
whose page hashes changed).

Extraction rules:
- Every person name must appear verbatim in the source page text (same
  guard as the Block Party tally rule). No inference, no filling gaps.
- Public/non-voting committee members are excluded from `members` but a
  committee may note `"includes_public_members": true`.
- Staff (district manager, community associates) never go in `members`.
- If a page is stale-dated, keep extracting and record `as_of`.

```json
{
  "cd": 103,
  "sources": ["https://..."],
  "as_of": "2026-04-09 or null (a 'last updated' date printed on the page)",
  "officers": [{"role": "Chair", "name": "..."}],
  "members": [{"name": "...", "roles": ["Chair", "Land Use Committee Chair"]}],
  "committees": [
    {"name": "Land Use", "chair": "... or null",
     "members_listed": true, "members": ["..."]}
  ],
  "notes": "anything a maintainer should know (roster missing, PDF-only, ...)"
}
```

`members` empty + `committees` present is a valid result (many boards list
committees but not rosters). `coverage` is computed downstream by
`build_tracker_data.py`, not stored here.
- `page_hashes`: sorted page sha256 list, written by extract_rosters.py for its unchanged-skip.
