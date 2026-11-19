"""Merge all member-tracker sources into data/boards.json + data/members.json.

Inputs (produced by the sibling scripts; extracted/ inputs are optional and
the merge degrades gracefully when they are missing):
  cache/cau_boards.json                CAU dataset: chair, DM, contacts (59 boards)
  cache/bronx_roster.json              Bronx BP roster with term_expires
  extracted/rosters/<cd>.json          per-board site extraction (ROSTER_SCHEMA.md)
  extracted/block_party_activity.json  Manhattan resolution activity
  extracted/chair_links.json           chair LinkedIn/news enrichment

Term-limit rules encoded here (2018 charter amendment to §2800, approved
Nov 6 2018): two-year terms run Apr 1 - Mar 31 with half of each board
appointed each year; max four consecutive terms for terms beginning on or
after Apr 1 2019; members whose term began Apr 1 2020 may serve five
consecutive terms (staggering the turnover waves). First forced wave
2027-03-31, second 2030-03-31. Per-member clocks are CONFIRMED only where
a BP publishes term data (Bronx); elsewhere the waves are structural.

Run from the member-tracker folder: python3 pipeline/build_tracker_data.py
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
EXTRACTED = HERE / "extracted"
DATA = HERE.parent / "data"

TERM_RULES = {
    "term_years": 2,
    "term_runs": "April 1 to March 31",
    "max_consecutive_terms": 4,
    "exception": "terms that began April 1, 2020 may run five consecutive terms",
    "clock_start": "2019-04-01",
    "first_forced_wave": "2027-03-31",
    "second_forced_wave": "2030-03-31",
    "authority": "NYC Charter §2800, amended by ballot Question 3 (Nov 2018)",
}

SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def norm_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^\w\s]", " ", s.lower())
    parts = [p for p in s.split() if p not in SUFFIXES]
    if len(parts) >= 3 and len(parts[1]) == 1:  # drop middle initial
        parts = [parts[0]] + parts[2:]
    return " ".join(parts)


def same_person(a: str, b: str) -> bool:
    """True when two name strings plausibly refer to the same person.

    Handles honorifics, 'Last, First' ordering, and small spelling variants
    ('Mohammed/Mohammad', 'DiBenedett/DiBenedetto') so a typo never reads as
    a leadership change.
    """
    from difflib import SequenceMatcher

    na, nb = norm_name(strip_honorific(a)), norm_name(strip_honorific(b))
    if not na or not nb:
        return False
    if na == nb or set(na.split()) == set(nb.split()):
        return True
    return SequenceMatcher(None, na, nb).ratio() >= 0.85


def strip_honorific(name: str) -> str:
    return re.sub(
        r"^(hon\.?|ms\.?|mr\.?|mrs\.?|dr\.?|rev\.?)\s+", "", (name or "").strip(),
        flags=re.I,
    ).replace(",", " ")


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text())
    return default


def fuzzy_key(entries: dict, key: str) -> str | None:
    """An existing key that plausibly names the same person, else None."""
    from difflib import SequenceMatcher

    for k in entries:
        if set(k.split()) == set(key.split()) or SequenceMatcher(None, k, key).ratio() >= 0.9:
            return k
    return None


def committee_base(name: str) -> str:
    """Committee name with exactly one trailing 'Committee' unless it is a
    task force / work group / other self-labeled body."""
    n = (name or "").strip()
    if re.search(r"(committee|task force|work group|caucus|board)s?$", n, re.I):
        return n
    return n + " Committee"


def dedupe_roles(roles: list[str]) -> list[str]:
    out: list[str] = []
    seen = set()
    for r in roles:
        r = re.sub(r"\s+", " ", r).replace("Committee Committee", "Committee").strip()
        k = r.lower()
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def main() -> None:
    boards_src = json.loads((CACHE / "cau_boards.json").read_text())
    bronx_rows = load_json(CACHE / "bronx_roster.json", [])
    bp_activity = load_json(EXTRACTED / "block_party_activity.json", {"boards": {}})
    chair_links = {
        c["cd"]: c for c in load_json(EXTRACTED / "chair_links.json", [])
    }

    # Bronx: the latest roster year is the current membership snapshot;
    # older vintages would inflate boards with since-departed members
    bronx_latest_year = max((r["roster_year"] or 0 for r in bronx_rows), default=None)
    bronx: dict[int, dict[str, dict]] = {}
    for r in bronx_rows:
        if r["roster_year"] != bronx_latest_year:
            continue
        cd = r["boro_cd"]
        full = f"{r['first_name']} {r['last_name']}".strip()
        key = norm_name(full)
        if not key:
            continue
        bronx.setdefault(cd, {})[key] = {**r, "full_name": full}

    out_boards = []
    out_members = []

    overrides = load_json(HERE / "chair_overrides.json", {})

    for b in boards_src:
        cd = b["boro_cd"]
        roster = load_json(EXTRACTED / "rosters" / f"{cd}.json", None)
        link = chair_links.get(cd)

        # Chair precedence: manual override > the board site's own "Chair"
        # officer > the CAU dataset (which lags board elections by months).
        cau_chair = (link or {}).get("canonical_name") or b["chair"]
        site_chair = None
        for o in (roster or {}).get("officers", []):
            if re.match(r"^(board |b'board )?chair(person|man|woman)?$", (o.get("role") or "").strip(), re.I):
                site_chair = o["name"]
                break
        override = overrides.get(str(cd))
        chair_name = (override or {}).get("name") or site_chair or cau_chair
        note = (override or {}).get("note")
        if (
            not note
            and cau_chair
            and chair_name
            and not same_person(chair_name, cau_chair)
        ):
            note = (
                f"Chair per the board's own website; the citywide CAU dataset "
                f"still lists {cau_chair}."
            )
        link_matches = bool(
            link and chair_name
            and same_person(link.get("canonical_name") or link.get("name") or "", chair_name)
        )
        if chair_name:
            chair_name = strip_honorific(chair_name).strip()
            if "," in (site_chair or "") and chair_name == strip_honorific(site_chair).strip():
                last, _, first = site_chair.partition(",")
                chair_name = f"{first.strip()} {last.strip()}"
            if chair_name.isupper():
                chair_name = chair_name.title()
            chair_name = re.sub(r"\s+", " ", chair_name)
        chair = {
            "name": chair_name,
            "linkedin": link.get("linkedin") if link_matches else None,
            "news": link.get("news", []) if link_matches else [],
            "status_note": note or ((link or {}).get("status_note") if link_matches else None),
        }

        committees = []
        officers = []
        site_members: dict[str, dict] = {}
        roster_as_of = None
        roster_sources = []
        if roster:
            roster_as_of = roster.get("as_of")
            roster_sources = roster.get("sources", [])
            officers = roster.get("officers", [])
            for c in roster.get("committees", []):
                chair_name = c.get("chair")
                if not chair_name and c.get("co_chairs"):
                    chair_name = " & ".join(c["co_chairs"])
                committees.append(
                    {
                        "name": c["name"],
                        "chair": chair_name,
                        "members_listed": bool(c.get("members")),
                    }
                )
            for m in roster.get("members", []):
                key = norm_name(m["name"])
                if key:
                    site_members[key] = {"name": m["name"], "roles": m.get("roles", [])}
            # committee membership -> roles on the member record. When the
            # board publishes a real roster, committee lists only ANNOTATE
            # known members — creating new entries from them would promote
            # committee public members onto the board.
            has_roster = len(roster.get("members", [])) >= 15
            for c in roster.get("committees", []):
                for name in c.get("members") or []:
                    key = norm_name(name)
                    if key not in site_members:
                        if has_roster or c.get("includes_public_members"):
                            continue
                        site_members[key] = {"name": name, "roles": []}
                    entry = site_members[key]
                    role = committee_base(c["name"])
                    if role not in entry["roles"] and not any(
                        r.startswith(c["name"]) for r in entry["roles"]
                    ):
                        entry["roles"].append(role)

        # merge Bronx BP roster (authoritative for membership + term dates)
        bx = bronx.get(cd, {})
        merged: dict[str, dict] = {}
        for key, m in bx.items():
            merged[key] = {
                "name": m["full_name"],
                "roles": [],
                "term_expires": m["term_expires"],
                "recommending_official": m["recommending_official"],
                "roster_year": m["roster_year"],
                "source": "bronx_bp",
            }
        for key, m in site_members.items():
            if key in merged:
                merged[key]["roles"] = m["roles"]
                merged[key]["source"] = "bronx_bp+board_site"
            elif bx:
                # the BP roster is the authoritative membership snapshot;
                # site-only names on Bronx boards are likely departed members
                # on a stale page. Attach roles to a fuzzy-matched BP member
                # ("Last, First" pages), otherwise drop the name.
                fuzzy = fuzzy_key(merged, key)
                if fuzzy:
                    merged[fuzzy]["roles"] = merged[fuzzy]["roles"] + m["roles"]
                    merged[fuzzy]["source"] = "bronx_bp+board_site"
                continue
            else:
                merged[key] = {
                    "name": m["name"],
                    "roles": m["roles"],
                    "term_expires": None,
                    "recommending_official": None,
                    "roster_year": None,
                    "source": "board_site",
                }

        # officers and the CAU chair are board members even when no roster page exists
        def add_role(name: str, role: str):
            key = norm_name(name)
            if not key:
                return
            entry = merged.setdefault(
                key,
                {
                    "name": name,
                    "roles": [],
                    "term_expires": None,
                    "recommending_official": None,
                    "roster_year": None,
                    "source": "cau" if role == "Chair" else "board_site",
                },
            )
            if role not in entry["roles"]:
                entry["roles"].insert(0, role)

        for o in officers:
            add_role(o["name"], o["role"])
        if chair["name"]:
            add_role(chair["name"], "Chair")
        for c in committees:
            for cc_name in re.split(r"\s*[;&]\s*", c["chair"] or ""):
                if cc_name.strip():
                    add_role(cc_name.strip(), committee_base(c["name"]) + " Chair")

        # fuzzy-merge near-duplicate names (site typos like Kathryn/Kathyrn)
        from difflib import SequenceMatcher

        keys = sorted(merged, key=lambda k: (merged[k]["source"] == "board_site", k))
        for i, k1 in enumerate(keys):
            if k1 not in merged:
                continue
            for k2 in keys[i + 1:]:
                if k2 not in merged or k1 == k2:
                    continue
                if (
                    set(k1.split()) == set(k2.split())  # "Last First" vs "First Last"
                    or SequenceMatcher(None, k1, k2).ratio() >= 0.9
                ):
                    keep, dup = merged[k1], merged.pop(k2)
                    keep["roles"] = keep["roles"] + dup["roles"]
                    keep["term_expires"] = keep["term_expires"] or dup["term_expires"]
                    keep["recommending_official"] = (
                        keep["recommending_official"] or dup["recommending_official"]
                    )

        for m in merged.values():
            m["roles"] = dedupe_roles(m["roles"])
        members = sorted(merged.values(), key=lambda m: m["name"].split()[-1].lower())
        has_full_roster = bool(site_members) and len(site_members) >= 15 or bool(bx)
        coverage_roster = (
            "full" if has_full_roster else ("partial" if members else "none")
        )
        if roster and roster.get("committees"):
            if any(c["members_listed"] for c in committees):
                coverage_committees = "assignments"
            elif any(c["chair"] for c in committees):
                coverage_committees = "chairs"
            else:
                coverage_committees = "list"
        else:
            coverage_committees = "none"

        confirmed = {}
        projected = {}
        today = date.today().isoformat()
        for m in bx.values():
            exp = m["term_expires"]
            if m["roster_year"] != bronx_latest_year or not exp:
                continue
            confirmed[exp] = confirmed.get(exp, 0) + 1
            # roll a stale date forward by two-year terms to the seat's next
            # expiration, assuming reappointment: the board's turnover classes
            nxt = exp
            while nxt < today:
                nxt = f"{int(nxt[:4]) + 2}{nxt[4:]}"
            projected[nxt] = projected.get(nxt, 0) + 1

        out_boards.append(
            {
                "cd": cd,
                "borough": b["borough"],
                "number": b["board_number"],
                "name": f"{b['borough']} CB {b['board_number']}",
                "neighborhoods": b["neighborhoods"],
                "website": b["website"],
                "office_email": b["office_email"],
                "office_phone": b["office_phone"],
                "board_meeting": b["board_meeting"],
                "chair": chair,
                "district_manager": b["district_manager"],
                "officers": officers,
                "committees": committees,
                "member_count": len([m for m in members if m["source"] != "cau"])
                or None,
                "coverage": {
                    "roster": coverage_roster,
                    "committees": coverage_committees,
                    "terms": "confirmed" if confirmed else "modeled",
                },
                "roster_as_of": roster_as_of,
                "roster_sources": roster_sources,
                "term_clock": {
                    "confirmed_expirations": confirmed or None,
                    "projected_expirations": projected or None,
                    "bronx_roster_year": bronx_latest_year if confirmed else None,
                },
                "block_party": bp_activity["boards"].get(str(cd)),
            }
        )

        for m in members:
            out_members.append({"cd": cd, **m})

    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "boards.json").write_text(
        json.dumps(
            {
                "generated": date.today().isoformat(),
                "term_rules": TERM_RULES,
                "boards": out_boards,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
    )
    (DATA / "members.json").write_text(
        json.dumps(
            {"generated": date.today().isoformat(), "members": out_members},
            separators=(",", ":"),
            ensure_ascii=False,
        )
    )

    n_full = sum(1 for x in out_boards if x["coverage"]["roster"] == "full")
    n_comm = sum(1 for x in out_boards if x["coverage"]["committees"] != "none")
    print(
        f"boards.json: {len(out_boards)} boards ({n_full} full rosters, "
        f"{n_comm} with committee data) | members.json: {len(out_members)} rows"
    )


if __name__ == "__main__":
    main()
