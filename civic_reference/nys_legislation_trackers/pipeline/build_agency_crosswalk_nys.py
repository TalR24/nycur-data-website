#!/usr/bin/env python3
"""Build data/agency_crosswalk_nys.json: NYS duty-holders, same shape as the Council crosswalk
({source, agencies:[{canonical, full_name, display_name, org_type, jurisdiction, variants}], lookup:{norm: canonical}}) so
extract_obligations.match_agency works on it unchanged.

Sources (fetched live, Open Data pages with $limit/$offset until an empty page):
  * https://data.ny.gov/resource/kjw8-pupa.json  "Agency Contacts" (Office of the Governor): 79 distinct agency names
  * https://data.ny.gov/resource/xzfr-sv3m.json  "Directory of State Authorities" (Authorities Budget Office): 45 State authorities
plus a curated table (the constitutional officers, courts, the Legislature, local-government groups, and the actors that
appear in the 52 pilot laws). Private parties are never duty-holders.
Usage: python3 build_agency_crosswalk_nys.py
"""
import json, os, re, sys, urllib.parse, urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
OUT = os.path.join(DATA, "agency_crosswalk_nys.json")
SNAP = os.path.join(HERE, "cache", "agency_sources")
SOURCES = [("kjw8-pupa", "agency"), ("xzfr-sv3m", None)]
ORG_TYPES = ["executive agency", "department", "division", "office", "board/commission", "public authority",
             "statewide elected official", "judiciary", "legislature", "local government group"]


def norm(s):  # must match extract_obligations.norm_lookup_key
    s = s.lower().strip().replace("&", "and")
    s = re.sub(r"[.,'’]", "", s)
    return re.sub(r"\s+", " ", s)


def skel(s):
    """Looser key for merging the official lists into curated entries (drops 'New York State', hyphens, articles)."""
    s = norm(s).replace("-", " ")
    s = re.sub(r"^(the )?(new york state |nys |state of new york )", "", s)
    return re.sub(r"\s+", " ", s).strip()


def pull(ds, select=None):
    out, off = [], 0
    while True:
        q = {"$limit": 1000, "$offset": off, "$order": ":id"}
        if select:
            q["$select"] = select
        d = json.load(urllib.request.urlopen("https://data.ny.gov/resource/%s.json?%s" % (ds, urllib.parse.urlencode(q))))
        if not d:
            return out
        out += d
        off += 1000


def org_type_for(name):
    n = name.lower()
    if re.search(r"authority|corporation|trust|district|fund|port of|bridge|university|power|racing", n):
        return "public authority"
    if re.search(r"board|commission|council|justice center", n):
        return "board/commission"
    if n.startswith("division"):
        return "division"
    if n.startswith("department") or "department of" in n:
        return "department"
    if n.startswith("office") or n.startswith("empire state development"):
        return "office"
    return "executive agency"


# (canonical, full name, org_type, extra variants). Variants are matched after norm(); "department of X" and
# "new york state ..." forms are generated below.
CURATED = [
    ("Governor", "Governor of the State of New York", "statewide elected official", ["governor", "the governor", "executive chamber", "office of the governor"]),
    ("State Comptroller", "Office of the State Comptroller", "statewide elected official",
     ["state comptroller", "comptroller", "the comptroller", "comptroller of the state of new york", "office of the state comptroller", "department of audit and control", "state department of audit and control", "osc"]),
    ("Attorney General", "Office of the Attorney General", "statewide elected official", ["attorney general", "attorney-general", "office of the attorney general", "oag"]),
    ("Lieutenant Governor", "Lieutenant Governor", "statewide elected official", ["lieutenant governor"]),
    ("DOB", "Division of the Budget", "division", ["director of the budget", "division of the budget", "budget director", "state division of the budget", "director of the division of the budget"]),
    ("Board of Regents", "Board of Regents of the University of the State of New York", "board/commission", ["board of regents", "regents", "the regents", "university of the state of new york"]),
    ("SED", "State Education Department", "executive agency", ["state education department", "education department", "department of education of the state of new york", "commissioner of education", "commissioner of the state education department", "new york state education department", "nysed", "sed", "state department of education"]),
    ("Unified Court System", "Unified Court System / Office of Court Administration", "judiciary",
     ["chief administrator of the courts", "office of court administration", "unified court system", "chief judge", "chief judge of the state of new york", "court of appeals", "supreme court", "court", "the court", "family court", "surrogates court", "appellate division", "judicial conference", "oca"]),
    ("Legislature", "New York State Legislature", "legislature", ["legislature", "the legislature", "state legislature", "senate", "state senate", "assembly", "state assembly", "temporary president of the senate", "speaker of the assembly", "legislative bill drafting commission", "legislative commission"]),
    ("DOH", "Department of Health", "department", ["department of health", "commissioner of health", "health commissioner", "state department of health", "doh", "health department", "state health commissioner", "commissioner of the department of health", "state commissioner of health"]),
    ("DOCCS", "Department of Corrections and Community Supervision", "department", ["department of corrections and community supervision", "doccs", "commissioner of corrections and community supervision", "commissioner of correctional services", "department of correctional services"]),
    ("DTF", "Department of Taxation and Finance", "department", ["department of taxation and finance", "commissioner of taxation and finance", "tax commissioner", "state tax commission", "tax department", "dtf", "department of tax and finance"]),
    ("DFS", "Department of Financial Services", "department", ["department of financial services", "superintendent of financial services", "superintendent of insurance", "superintendent of banks", "insurance department", "department of financial service", "dfs"]),
    ("DEC", "Department of Environmental Conservation", "department", ["department of environmental conservation", "commissioner of environmental conservation", "dec"]),
    ("DOL", "Department of Labor", "department", ["department of labor", "commissioner of labor", "labor commissioner", "dol"]),
    ("DOS", "Department of State", "department", ["department of state", "secretary of state", "dos"]),
    ("DMV", "Department of Motor Vehicles", "department", ["department of motor vehicles", "commissioner of motor vehicles", "dmv"]),
    ("NYSDOT", "Department of Transportation", "department", ["department of transportation", "commissioner of transportation", "state department of transportation", "nys dot", "nysdot", "new york state department of transportation (dot)"]),
    ("DCS", "Department of Civil Service", "department", ["department of civil service", "civil service commission", "president of the civil service commission", "state civil service commission"]),
    ("DAM", "Department of Agriculture and Markets", "department", ["department of agriculture and markets", "commissioner of agriculture and markets", "dam"]),
    ("DPS", "Department of Public Service", "department", ["department of public service", "dps"]),
    ("PSC", "Public Service Commission", "board/commission", ["public service commission", "psc", "chair of the public service commission"]),
    ("OMH", "Office of Mental Health", "office", ["office of mental health", "commissioner of mental health", "omh", "department of mental hygiene", "commissioner of mental hygiene", "commissioner of the office of mental health"]),
    ("OASAS", "Office of Addiction Services and Supports", "office", ["office of addiction services and supports", "commissioner of addiction services and supports", "oasas", "office of alcoholism and substance abuse services", "commissioner of alcoholism and substance abuse services"]),
    ("OPWDD", "Office for People with Developmental Disabilities", "office", ["office for people with developmental disabilities", "commissioner of developmental disabilities", "opwdd", "commissioner of the office for people with developmental disabilities"]),
    ("OCFS", "Office of Children and Family Services", "office", ["office of children and family services", "commissioner of children and family services", "ocfs", "commissioner of the office of children and family services"]),
    ("OTDA", "Office of Temporary and Disability Assistance", "office", ["office of temporary and disability assistance", "commissioner of temporary and disability assistance", "otda", "department of family assistance", "state commissioner of temporary and disability assistance", "state commissioner of temporary and disability"]),
    ("OMIG", "Office of the Medicaid Inspector General", "office", ["office of the medicaid inspector general", "medicaid inspector general", "omig", "office of medicaid inspector general"]),
    ("OGS", "Office of General Services", "office", ["office of general services", "commissioner of general services", "ogs"]),
    ("ITS", "Office of Information Technology Services", "office", ["office of information technology services", "its", "chief information officer", "state chief information officer"]),
    ("HESC", "Higher Education Services Corporation", "public authority", ["higher education services corporation", "hesc", "office of nys higher education services corporation"]),
    ("SUNY", "State University of New York", "public authority", ["state university of new york", "suny", "board of trustees of the state university of new york", "state university trustees", "state university"]),
    ("CUNY", "City University of New York", "public authority", ["city university of new york", "cuny", "board of trustees of the city university of new york"]),
    ("DASNY", "Dormitory Authority of the State of New York", "public authority", ["dormitory authority of the state of new york", "dormitory authority state of ny", "dormitory authority", "dasny"]),
    ("DHSES", "Division of Homeland Security and Emergency Services", "division", ["division of homeland security and emergency services", "dhses", "commissioner of homeland security and emergency services"]),
    ("DCJS", "Division of Criminal Justice Services", "division", ["division of criminal justice services", "dcjs", "commissioner of criminal justice services"]),
    ("State Police", "Division of State Police", "division", ["division of state police", "state police", "new york state police", "superintendent of state police", "superintendent of the division of state police", "nys police"]),
    ("DHR", "Division of Human Rights", "division", ["division of human rights", "state division of human rights", "dhr"]),
    ("HCR", "Homes and Community Renewal", "executive agency", ["homes and community renewal", "division of housing and community renewal", "hcr", "commissioner of housing and community renewal", "state homes and community renewal"]),
    ("OPRHP", "Office of Parks, Recreation and Historic Preservation", "office", ["office of parks recreation and historic preservation", "office of parks recreation and historic preservations", "oprhp", "commissioner of parks recreation and historic preservation", "state parks"]),
    ("Board of Elections", "State Board of Elections", "board/commission", ["state board of elections", "board of elections", "nys board of elections", "boe", "nys board of elections (boe)"]),
    ("Gaming Commission", "New York State Gaming Commission", "board/commission", ["gaming commission", "state gaming commission", "new york state gaming commission", "racing and wagering board", "state racing and wagering board"]),
    ("PERB", "Public Employment Relations Board", "board/commission", ["public employment relations board", "perb"]),
    ("WCB", "Workers' Compensation Board", "board/commission", ["workers compensation board", "workers’ compensation board", "worker’s compensation board", "wcb", "chair of the workers compensation board"]),
    ("Industrial Board of Appeals", "Industrial Board of Appeals", "board/commission", ["industrial board of appeals"]),
    ("ESD", "Empire State Development", "public authority", ["empire state development", "esd", "empire state development corporation", "urban development corporation", "new york state urban development corporation"]),
    ("NYPA", "New York Power Authority", "public authority", ["power authority of the state of new york", "new york power authority", "nypa"]),
    ("MTA", "Metropolitan Transportation Authority", "public authority", ["metropolitan transportation authority", "mta"]),
    ("Charter School Board", "State Charter Schools Advisory Board", "board/commission", ["state charter advisory board", "charter school advisory board"]),
    ("NYSCA", "New York State Council on the Arts", "board/commission", ["council on the arts", "state council on the arts", "new york state council on the arts", "nysca"]),
    ("TBTA", "Triborough Bridge and Tunnel Authority", "public authority", ["triborough bridge and tunnel authority", "tbta", "mta bridges and tunnels", "triborough bridge and tunnel authority (mta bridges and tunnels)"]),
    ("Fire Prevention and Building Code Council", "State Fire Prevention and Building Code Council", "board/commission", ["state fire prevention and building code council", "fire prevention and building code council", "new york state fire prevention and building code council", "code council"]),
    ("Fire districts", "Fire districts", "local government group", ["fire district", "fire districts", "board of fire commissioners", "fire commissioners", "each fire district"]),
    ("Special districts", "Special districts", "local government group", ["special district", "special districts", "improvement district", "improvement districts", "district corporation"]),
    ("Assessors (local)", "Assessors (local)", "local government group", ["assessor", "assessors", "board of assessors", "local assessor", "the assessor"]),
    ("Local veterans' service agencies", "Local veterans' service agencies", "local government group", ["veterans service agency", "veterans service agencies", "veterans' service agency", "veterans' service agencies", "county veterans service agency", "local veterans service agency"]),
    ("Public schools (all)", "Public schools (all)", "local government group", ["public schools", "public school", "each public school", "all public schools", "every public school", "every public school including charter schools", "public schools including charter schools"]),
    ("RJSCB", "Rochester Joint Schools Construction Board", "board/commission", ["rjscb", "rochester joint schools construction board"]),
    ("MCFFA", "New York State Medical Care Facilities Finance Agency", "public authority", ["medical care facilities finance agency", "new york state medical care facilities finance agency", "mcffa"]),
    ("Municipalities (all)", "Municipalities (all)", "local government group", ["municipality", "municipalities", "any municipality", "each municipality", "political subdivision", "political subdivisions", "local government", "local governments", "local governmental entity", "public corporation", "public corporations", "governmental entity", "local agency"]),
    ("Counties", "Counties", "local government group", ["county", "counties", "each county", "any county", "county legislature", "board of supervisors", "county executive", "county board of elections", "local social services districts", "local social services district", "social services district"]),
    ("Cities", "Cities", "local government group", ["city", "cities", "each city", "any city", "city council", "common council", "city manager", "city comptroller"]),
    ("Towns", "Towns", "local government group", ["town", "towns", "each town", "any town", "town board", "town supervisor", "town clerk"]),
    ("Villages", "Villages", "local government group", ["village", "villages", "each village", "any village", "village board", "village board of trustees", "village board of trustees of the village"]),
    ("School districts", "School districts", "local government group", ["school district", "school districts", "board of education", "boards of education", "board of cooperative educational services", "boces", "central school district", "union free school district", "trustees of the school district", "superintendent of schools", "school board"]),
    ("New York City", "New York City", "local government group", ["new york city", "city of new york", "the city of new york", "nyc", "mayor of the city of new york", "city of new york (nyc)"]),
]


def acronym_and_name(raw):
    """'Department of Health (DOH)' -> ('DOH', 'Department of Health'); drops footnote junk."""
    s = re.sub(r"\*.*$", "", raw).strip()
    m = re.match(r"^(.*?)\s*\(([^)]+)\)\s*(.*)$", s)
    if m:
        return m.group(2).split("/")[0].strip(), (m.group(1) + " " + m.group(3)).strip()
    return None, s


def main():
    os.makedirs(SNAP, exist_ok=True)
    raw = {}
    for ds, sel in SOURCES:
        rows = pull(ds, sel)
        raw[ds] = rows
        json.dump(rows, open(os.path.join(SNAP, ds + ".json"), "w"))
    names = sorted({r["agency"] for r in raw["kjw8-pupa"] if r.get("agency") and "NOT A STATE AGENCY" not in r["agency"]})
    auths = sorted({r["public_authority_name"] for r in raw["xzfr-sv3m"] if r.get("public_authority_name")})
    agencies, by_canon = [], {}

    def add(canon, full, otype, variants, source):
        if canon in by_canon:
            a = by_canon[canon]
            a["variants"] = sorted(set(a["variants"]) | set(variants))
            a["sources"] = sorted(set(a["sources"]) | {source})
            return
        a = {"canonical": canon, "full_name": full, "display_name": full, "org_type": otype, "jurisdiction": "state",
             "variants": sorted(set(variants) | {full}), "sources": [source]}
        by_canon[canon] = a
        agencies.append(a)

    for canon, full, otype, extra in CURATED:
        add(canon, full, otype, extra, "curated")
        if otype == "local government group":
            by_canon[canon]["jurisdiction"] = "nyc" if canon == "New York City" else "local"
    # official lists: attach as variants to a curated entry when any name already resolves, else add a new entry
    lookup_probe = {}
    for a in agencies:
        for v in a["variants"]:
            lookup_probe[norm(v)] = a["canonical"]
            lookup_probe[skel(v)] = a["canonical"]
    for raw_name in names + auths:
        src = "data.ny.gov kjw8-pupa (Agency Contacts)" if raw_name in names else "data.ny.gov xzfr-sv3m (Directory of State Authorities)"
        acr, full = acronym_and_name(raw_name)
        full = full.replace("Worker’s", "Workers’")
        forms = {full, raw_name.replace("*NOT A STATE AGENCY", "")}
        if acr:
            forms |= {acr}
        parts = [p.strip() for p in re.split(r"\s+/\s+", full)] if "/" in full else [full]
        for p in parts:
            hit = next((lookup_probe[k] for f in forms | {p} for k in (norm(f), skel(f)) if k in lookup_probe), None)
            hit = hit or (lookup_probe.get(norm(acr)) if acr else None)
            if hit:
                add(hit, by_canon[hit]["full_name"], by_canon[hit]["org_type"], list(forms | {p}), src)
            else:
                pa = re.sub(r"\s*\([^)]*\)", "", p).strip()
                canon = acr if acr and len(parts) == 1 else pa
                add(canon, pa, org_type_for(pa), list(forms | {p, pa}), src)
                for f in forms | {pa}:
                    lookup_probe[norm(f)] = canon
                    lookup_probe[skel(f)] = canon
    # generated variants
    for a in agencies:
        if a["jurisdiction"] != "state":
            continue
        vs = set(a["variants"])
        for v in list(vs):
            m = re.match(r"^(?:the )?department of (.+)$", v, re.I)
            if m:
                vs |= {m.group(1) + " department", "dept of " + m.group(1), "new york state department of " + m.group(1), "state department of " + m.group(1), "nys department of " + m.group(1)}
            m = re.match(r"^(?:the )?office of (.+)$", v, re.I)
            if m:
                vs |= {"new york state office of " + m.group(1), "state office of " + m.group(1)}
        full = a["full_name"]
        if not full.lower().startswith(("new york", "nys", "state")):
            vs |= {"new york state " + full, "nys " + full}
        a["variants"] = sorted(vs)
    lookup, clash = {}, []
    rank = {"curated": 0}
    for a in agencies:           # curated entries come first and win a clash
        for v in a["variants"] + [a["canonical"], a["full_name"]]:
            k = norm(v)
            if k in lookup and lookup[k] != a["canonical"]:
                clash.append((k, lookup[k], a["canonical"]))
                continue
            lookup[k] = a["canonical"]
    out = {"source": "data.ny.gov kjw8-pupa (Agency Contacts, Office of the Governor, %d distinct names) and xzfr-sv3m (Directory of State Authorities, %d State authorities), fetched %s via the Socrata API; plus a curated table of constitutional officers, courts, the Legislature, local-government groups and the actors in the pilot laws" % (len(names), len(auths), date.today().isoformat()),
           "source_urls": ["https://data.ny.gov/resource/kjw8-pupa.json", "https://data.ny.gov/resource/xzfr-sv3m.json"],
           "fetched": date.today().isoformat(), "org_types": ORG_TYPES, "agencies": agencies, "lookup": lookup}
    json.dump(out, open(OUT, "w"), indent=1, ensure_ascii=False)
    from collections import Counter
    print("agencies", len(agencies), "lookup keys", len(lookup), dict(Counter(a["org_type"] for a in agencies)), "clashes", len(clash))
    for c in clash[:15]:
        print("  clash", c)


if __name__ == "__main__":
    main()
