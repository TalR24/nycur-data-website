# Roster extraction schema

One JSON file per board at `pipeline/extracted/rosters/<boro_cd>.json` (59 files). `pipeline/extract_rosters.py` writes them from the pages cached by `fetch_board_pages.py` (`pipeline/cache/pages/<boro_cd>/`, indexed in `pipeline/cache/pages_index.json`). The script sends each board's page text to Claude (default model `claude-haiku-4-5-20251001`, secret `ANTHROPIC_API_KEY`) with a JSON schema that forbids extra keys. It skips a board whose page hashes match the stored `page_hashes`, unless `--force` is passed. `build_tracker_data.py` reads these files.

Extraction rules:
- Every person name must appear verbatim in the source page text (whitespace collapsed, case-insensitive). The script drops names that fail, sets a committee chair that fails to `null`, and keeps the previous file when a call errors.
- `members` holds appointed voting members only. Committee public members, staff (district manager, community associates) and elected officials are excluded.
- Officers (Chair, First Vice Chair, Secretary, Treasurer, and so on) go in `officers` and also stay in `members` when the page lists a full roster.
- `as_of` is a "last updated" date printed on a page (YYYY-MM-DD), else `null`.

```json
{
  "cd": 103,
  "sources": ["https://..."],
  "page_hashes": ["sha256 prefix of each cached page, sorted"],
  "as_of": "2026-04-09 or null",
  "officers": [{"role": "Chair", "name": "..."}],
  "members": [{"name": "...", "roles": ["Chair", "Land Use Committee Chair"]}],
  "committees": [
    {"name": "Land Use", "chair": "... or null", "members": ["..."]}
  ],
  "notes": "one short sentence on gaps (roster missing, PDF-only, ...)"
}
```

`cd` and `sources` and `page_hashes` come from the script; the other five keys come from the model.

`members` empty with `committees` present is a valid result, since many boards list committees but not rosters. The fields `members_listed` and `coverage` are computed downstream by `build_tracker_data.py` (`members_listed` is true when a committee has a `members` list) and are not stored here. `build_tracker_data.py` also reads an optional `includes_public_members` flag on a committee to stop that committee's list from adding new board members; the extractor does not produce it, so set it by hand on a roster file when needed.
