"""Every member per session -> data/members.json. Usage: python3 fetch_members.py"""
import json, os
import openleg

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")


def main():
    out = []
    for y in range(2009, 2026, 2):
        n = 0
        for m in openleg.paginate("/api/3/members/%d" % y, {"full": "true"}, page=1000):
            # sessionShortNameMap holds the district for the requested session; top-level fields are the latest session
            sm = (m.get("sessionShortNameMap") or {}).get(str(y)) or [{}]
            e = sm[0]
            p = m.get("person") or {}
            out.append({"member_id": m.get("memberId"), "session": y, "chamber": (m.get("chamber") or "").title(),
                        "full_name": m.get("fullName"), "short_name": e.get("shortName") or m.get("shortName"),
                        "district": e.get("districtCode", m.get("districtCode")), "session_member_id": e.get("sessionMemberId"),
                        "alternate": e.get("alternate"), "incumbent": m.get("incumbent"),
                        "first_name": p.get("firstName"), "last_name": p.get("lastName"), "party": None})
            n += 1
        print(y, n, flush=True)
    json.dump(out, open(os.path.join(DATA, "members.json"), "w"), indent=1)
    print("members rows", len(out), openleg.STATS)


if __name__ == "__main__":
    main()
