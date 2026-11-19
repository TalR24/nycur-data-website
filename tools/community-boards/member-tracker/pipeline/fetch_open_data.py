"""Fetch the two NYC Open Data sources for the CB member tracker.

Sources:
  ruf7-3wgc  NYC Community Boards (Mayor's Community Affairs Unit)
             -> chair, district manager, office contacts, meeting schedule,
                website URL for all 59 boards
  wbau-xy7g  Bronx Community Boards (Bronx BP)
             -> full member roster with term_expires and recommending official

Writes pipeline/cache/cau_boards.json and pipeline/cache/bronx_roster.json.
Run from the member-tracker folder: python3 pipeline/fetch_open_data.py
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

CACHE = Path(__file__).resolve().parent / "cache"

BOROUGH_PREFIX = {
    "manhattan": 1,
    "bronx": 2,
    "brooklyn": 3,
    "queens": 4,
    "staten island": 5,
}


def fetch_json(url: str) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "nycuriosity-cb-tracker"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def boro_cd(borough: str, board_number: int) -> int:
    return BOROUGH_PREFIX[borough.strip().lower()] * 100 + board_number


def fetch_cau() -> list[dict]:
    rows = fetch_json(
        "https://data.cityofnewyork.us/resource/ruf7-3wgc.json?$limit=100"
    )
    boards = []
    for r in rows:
        m = re.search(r"(\d+)", r.get("community_board", ""))
        if not m or "borough" not in r:
            continue
        website = r.get("cb_website")
        boards.append(
            {
                "boro_cd": boro_cd(r["borough"], int(m.group(1))),
                "borough": r["borough"].strip(),
                "board_number": int(m.group(1)),
                "neighborhoods": r.get("neighborhoods"),
                "chair": (r.get("cb_chair") or "").strip() or None,
                "district_manager": (r.get("cb_district_manager") or "").strip() or None,
                "office_address": r.get("cb_office_address"),
                "office_phone": r.get("cb_office_phone"),
                "office_email": r.get("cb_office_email"),
                "website": website.get("url") if isinstance(website, dict) else website,
                "board_meeting": r.get("cb_board_meeting"),
            }
        )
    boards.sort(key=lambda b: b["boro_cd"])
    return boards


def fetch_bronx() -> list[dict]:
    rows = fetch_json(
        "https://data.cityofnewyork.us/resource/wbau-xy7g.json?$limit=2000"
    )
    members = []
    for r in rows:
        try:
            board_number = int(r["community_board"])
        except (KeyError, ValueError):
            continue
        members.append(
            {
                "boro_cd": 200 + board_number,
                "roster_year": int(r["year"]) if r.get("year") else None,
                "first_name": (r.get("first_name") or "").strip(),
                "last_name": (r.get("last_name") or "").strip(),
                "zip_code": r.get("zip_code"),
                "recommending_official": r.get("recommending_official"),
                "term_expires": (r.get("term_expires") or "")[:10] or None,
            }
        )
    return members


def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)

    boards = fetch_cau()
    if len(boards) != 59:
        sys.exit(f"expected 59 boards from CAU dataset, got {len(boards)}")
    (CACHE / "cau_boards.json").write_text(
        json.dumps(boards, indent=1, ensure_ascii=False)
    )
    print(f"cau_boards.json: {len(boards)} boards")

    bronx = fetch_bronx()
    if len(bronx) < 500:
        sys.exit(f"Bronx roster suspiciously small: {len(bronx)} rows")
    (CACHE / "bronx_roster.json").write_text(
        json.dumps(bronx, indent=1, ensure_ascii=False)
    )
    years = sorted({m["roster_year"] for m in bronx if m["roster_year"]})
    print(f"bronx_roster.json: {len(bronx)} rows, roster years {years}")


if __name__ == "__main__":
    main()
