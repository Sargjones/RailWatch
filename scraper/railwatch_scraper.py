"""
railwatch_scraper.py — RailWatch Canada data collector
Part of the Critical TO infrastructure intelligence family (criticalto.ca)

Runs on GitHub Actions (cron: daily). Writes JSON to:
  - railwatch_data_latest.json      (always current)
  - railwatch_data_YYYYMMDD.json    (daily archive)
  - railwatch_tdg.json              (TDG lookup table, refreshed weekly)

Data sources (all public / open):
  - TSB Rail Occurrence Database (1983–present)
  - Transport Canada Weekly Freight Rail Service & Performance
  - Transport Canada TDG Schedule 1 (UN number / class / ERAP lookup)
  - OpenStreetMap Overpass API (corridor geometry)
  - Community observation feed (GitHub Issues as structured input)

Author: Sarah Jones / Critical TO
"""

import json
import re
import csv
import time
import datetime
import hashlib
import requests
from io import StringIO

# ─── CONFIG ───────────────────────────────────────────────────────────────────

OUTPUT_LATEST   = "railwatch_data_latest.json"
OUTPUT_ARCHIVE  = f"railwatch_data_{datetime.date.today().strftime('%Y%m%d')}.json"
OUTPUT_TDG      = "railwatch_tdg.json"

CORRIDORS = {
    "dundas_sub": {
        "name": "CN Dundas Subdivision",
        "description": "Toronto–Hamilton–London–Windsor corridor",
        "operator": "CN",
        "communities": ["Toronto", "Mississauga", "Oakville", "Burlington", "Hamilton",
                        "Dundas", "Woodstock", "Ingersoll", "London",
                        "Tillsonburg", "St. Thomas", "Windsor"],
        "osm_relation": 7410819,
        "tsb_subdivision": "Dundas",
    },
    "chatham_sub": {
        "name": "CN Chatham Subdivision",
        "description": "Windsor–Sarnia cross-border industrial corridor",
        "operator": "CN",
        "communities": ["Windsor", "Chatham", "Sarnia"],
        "osm_relation": None,
        "tsb_subdivision": "Chatham",
    },
    "cpkc_windsor": {
        "name": "CPKC Windsor Subdivision",
        "description": "Toronto–Guelph–London–Windsor via CPKC",
        "operator": "CPKC",
        "communities": ["Toronto", "Brampton", "Guelph", "Kitchener", "London", "Windsor"],
        "osm_relation": None,
        "tsb_subdivision": "Windsor",
    },
}

# Aldershot area coordinates (CN Dundas/Oakville Sub junction area)
BRANTFORD_LAT = 43.1394
BRANTFORD_LON = -80.2644

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _ok(key, value, source, unit=None, note=None):
    return {
        "key": key,
        "value": value,
        "source": source,
        "unit": unit,
        "note": note,
        "status": "ok",
        "fetched_at": datetime.datetime.utcnow().isoformat() + "Z",
    }

def _err(key, source, error):
    return {
        "key": key,
        "value": None,
        "source": source,
        "status": "error",
        "error": str(error),
        "fetched_at": datetime.datetime.utcnow().isoformat() + "Z",
    }

def _manual(key, value, source, unit=None, note=None):
    r = _ok(key, value, source, unit, note)
    r["status"] = "manual"
    return r

def safe_get(url, timeout=20, headers=None):
    """GET with timeout and basic error handling."""
    try:
        h = {"User-Agent": "RailWatch-Canada/1.0 (criticalto.ca; contact@criticalto.ca)"}
        if headers:
            h.update(headers)
        r = requests.get(url, timeout=timeout, headers=h)
        r.raise_for_status()
        return r
    except Exception as e:
        raise RuntimeError(f"GET {url} failed: {e}")

# ─── TDG SCHEDULE 1 LOOKUP TABLE ──────────────────────────────────────────────
# Seeded from Transport Canada Schedule 1 (SOR/2001-286).
# Full CSV: https://opendatatc.tc.canada.ca/TDGR_SCHEDULE1_ENG.csv
# This seed covers the most commonly rail-transported dangerous goods in Canada.
# Refresh strategy: fetch TC CSV weekly in GitHub Actions; fall back to seed.

TDG_SEED = [
    # UN#,  Shipping name,                              Class,   PG,  ERAP, Notes
    ("1005", "AMMONIA, ANHYDROUS",                       "2.3",  None, True,  "Toxic gas; common in agriculture and refrigeration"),
    ("1017", "CHLORINE",                                 "2.3",  None, True,  "Toxic gas; water treatment and chemical manufacturing"),
    ("1023", "COAL GAS",                                 "2.3",  None, False, "Flammable toxic gas"),
    ("1040", "ETHYLENE OXIDE",                           "2.3",  None, True,  "Toxic flammable gas; sterilization and chemical precursor"),
    ("1053", "HYDROGEN SULPHIDE",                        "2.3",  None, True,  "Highly toxic flammable gas; oil and gas byproduct"),
    ("1062", "METHYL BROMIDE",                           "2.3",  None, True,  "Toxic gas; fumigant"),
    ("1067", "DINITROGEN TETROXIDE",                     "2.3",  None, True,  "Toxic oxidizing gas"),
    ("1075", "PETROLEUM GASES, LIQUEFIED",               "2.1",  None, False, "Flammable gas; includes propane, butane — common rail cargo"),
    ("1079", "SULPHUR DIOXIDE",                          "2.3",  None, True,  "Toxic gas; pulp/paper and mining byproduct"),
    ("1086", "VINYL CHLORIDE",                           "2.1",  None, True,  "Flammable gas; PVC precursor"),
    ("1202", "GAS OIL",                                  "3",    "III",False, "Flammable liquid; diesel fuel class"),
    ("1203", "GASOLINE",                                 "3",    "II", False, "Flammable liquid; major rail commodity"),
    ("1223", "KEROSENE",                                 "3",    "III",False, "Flammable liquid"),
    ("1230", "METHANOL",                                 "3",    "II", False, "Flammable toxic liquid"),
    ("1267", "PETROLEUM CRUDE OIL",                      "3",    "I",  True,  "Flammable liquid; high-volume rail cargo post-Lac-Mégantic"),
    ("1294", "TOLUENE",                                  "3",    "II", False, "Flammable liquid; industrial solvent"),
    ("1301", "VINYL ACETATE",                            "3",    "II", False, "Flammable liquid; polymer precursor"),
    ("1547", "ANILINE",                                  "6.1",  "II", False, "Toxic liquid; dye and rubber manufacturing"),
    ("1589", "CYANOGEN CHLORIDE",                        "2.3",  None, True,  "Extremely toxic gas; chemical precursor"),
    ("1591", "O-DICHLOROBENZENE",                        "6.1",  "III",False, "Toxic liquid; solvent and precursor"),
    ("1648", "ACETONITRILE",                             "3",    "II", False, "Flammable liquid; solvent"),
    ("1689", "SODIUM CYANIDE, SOLID",                    "6.1",  "I",  True,  "Highly toxic solid; mining gold extraction"),
    ("1719", "CAUSTIC ALKALI LIQUID",                    "8",    "II", False, "Corrosive liquid; includes sodium hydroxide solutions"),
    ("1745", "BROMINE PENTAFLUORIDE",                    "5.1",  "I",  True,  "Oxidizer and corrosive; very reactive"),
    ("1760", "CORROSIVE LIQUID",                         "8",    "II", False, "Generic corrosive liquid classification"),
    ("1779", "FORMIC ACID",                              "8",    "II", False, "Corrosive liquid; textile and leather processing"),
    ("1789", "HYDROCHLORIC ACID",                        "8",    "II", False, "Corrosive liquid; industrial acid"),
    ("1791", "HYPOCHLORITE SOLUTION",                    "8",    "III",False, "Corrosive liquid; water treatment (sodium hypochlorite)"),
    ("1793", "ISOPROPYL ACID PHOSPHATE",                 "8",    "III",False, "Corrosive liquid"),
    ("1805", "PHOSPHORIC ACID",                          "8",    "III",False, "Corrosive liquid; fertilizer manufacturing"),
    ("1823", "SODIUM HYDROXIDE, SOLID",                  "8",    "II", False, "Caustic soda; paper and aluminium processing"),
    ("1824", "SODIUM HYDROXIDE SOLUTION",                "8",    "II", False, "Caustic soda solution; very common rail cargo"),
    ("1830", "SULPHURIC ACID",                           "8",    "II", True,  "Corrosive liquid; largest volume chemical shipped by rail"),
    ("1849", "SODIUM SULPHIDE",                          "8",    "II", False, "Corrosive solid; pulp and paper"),
    ("1906", "SLUDGE ACID",                              "8",    "II", False, "Corrosive liquid; refinery waste"),
    ("1942", "AMMONIUM NITRATE",                         "5.1",  "III",True,  "Oxidizer; fertilizer — requires ERAP; detonation risk"),
    ("1950", "AEROSOLS",                                 "2.1",  None, False, "Flammable aerosol"),
    ("1977", "NITROGEN, REFRIGERATED LIQUID",            "2.2",  None, False, "Cryogenic non-flammable gas"),
    ("2014", "HYDROGEN PEROXIDE SOLUTION",               "5.1",  "II", False, "Oxidizer; bleaching and chemical manufacturing"),
    ("2031", "NITRIC ACID",                              "8",    "I",  True,  "Corrosive oxidizing liquid; chemical manufacturing"),
    ("2046", "CYMENES",                                  "3",    "III",False, "Flammable liquid; industrial solvent"),
    ("2056", "TETRAHYDROFURAN",                          "3",    "II", False, "Flammable liquid; solvent"),
    ("2209", "FORMALDEHYDE SOLUTION",                    "8",    "III",False, "Corrosive toxic liquid; resin manufacturing"),
    ("2211", "POLYMERIC BEADS",                          "9",    "III",False, "Miscellaneous; polystyrene precursor"),
    ("2448", "SULPHUR, MOLTEN",                          "4.1",  "III",False, "Flammable solid; petroleum refining byproduct — common in W. Canada"),
    ("2570", "CADMIUM COMPOUND",                         "6.1",  "II", False, "Toxic solid; mining byproduct"),
    ("2672", "AMMONIA SOLUTION",                         "8",    "III",False, "Corrosive liquid; cleaning and fertilizer"),
    ("2789", "ACETIC ACID, GLACIAL",                     "8",    "II", False, "Corrosive flammable liquid; chemical manufacturing"),
    ("2794", "BATTERIES, WET, FILLED WITH ACID",         "8",    None, False, "Corrosive; lead-acid batteries"),
    ("2809", "MERCURY",                                  "8",    "III",True,  "Corrosive heavy metal; mining and instrument manufacturing"),
    ("2924", "FLAMMABLE LIQUID, CORROSIVE",              "3",    "II", False, "Flammable corrosive liquid"),
    ("3077", "ENVIRONMENTALLY HAZARDOUS SUBSTANCE SOLID","9",    "III",False, "Misc. hazardous; catch-all for ecotoxic solids"),
    ("3082", "ENVIRONMENTALLY HAZARDOUS SUBSTANCE LIQUID","9",   "III",False, "Misc. hazardous; catch-all for ecotoxic liquids"),
    ("3256", "ELEVATED TEMPERATURE LIQUID, FLAMMABLE",   "3",    "III",False, "Hot flammable liquid; asphalt and tar"),
    ("3257", "ELEVATED TEMPERATURE LIQUID",              "9",    None, False, "Hot non-flammable liquid; molten materials"),
    ("3264", "CORROSIVE LIQUID, ACIDIC, INORGANIC",      "8",    "II", False, "Acidic corrosive"),
    ("3265", "CORROSIVE LIQUID, ACIDIC, ORGANIC",        "8",    "III",False, "Organic acid corrosive"),
]

TDG_CLASS_LABELS = {
    "1":   "Explosive",
    "1.1": "Explosive — mass explosion hazard",
    "1.2": "Explosive — projection hazard",
    "1.3": "Explosive — fire hazard",
    "1.4": "Explosive — minor hazard",
    "2.1": "Flammable gas",
    "2.2": "Non-flammable, non-toxic gas",
    "2.3": "Toxic gas",
    "3":   "Flammable liquid",
    "4.1": "Flammable solid",
    "4.2": "Spontaneously combustible",
    "4.3": "Dangerous when wet",
    "5.1": "Oxidizer",
    "5.2": "Organic peroxide",
    "6.1": "Toxic",
    "6.2": "Infectious substance",
    "7":   "Radioactive",
    "8":   "Corrosive",
    "9":   "Miscellaneous dangerous goods",
}

def fetch_tdg_lookup():
    """
    Build the TDG lookup table.
    Primary: fetch TC open CSV (https://opendatatc.tc.canada.ca/TDGR_SCHEDULE1_ENG.csv)
    Fallback: use seed data above.
    Returns list of dicts.
    """
    TC_TDG_CSV = "https://opendatatc.tc.canada.ca/TDGR_SCHEDULE1_ENG.csv"
    records = []
    try:
        r = safe_get(TC_TDG_CSV, timeout=30)
        reader = csv.DictReader(StringIO(r.text))
        for row in reader:
            un = row.get("UN_NUMBER","").strip().lstrip("UN").lstrip("0")
            name = row.get("SHIPPING_NAME","").strip()
            cls  = row.get("CLASS","").strip()
            pg   = row.get("PACKING_GROUP","").strip() or None
            erap = bool(row.get("ERAP_INDEX","").strip())
            if un and name:
                records.append({
                    "un": un,
                    "name": name,
                    "class": cls,
                    "class_label": TDG_CLASS_LABELS.get(cls, cls),
                    "packing_group": pg,
                    "erap_required": erap,
                    "notes": None,
                    "source": "Transport Canada Schedule 1 CSV",
                })
        print(f"  TDG: loaded {len(records)} records from TC CSV")
    except Exception as e:
        print(f"  TDG: TC CSV unavailable ({e}), using seed data ({len(TDG_SEED)} entries)")
        for un, name, cls, pg, erap, notes in TDG_SEED:
            records.append({
                "un": un,
                "name": name,
                "class": cls,
                "class_label": TDG_CLASS_LABELS.get(cls, cls),
                "packing_group": pg,
                "erap_required": erap,
                "notes": notes,
                "source": "RailWatch seed (TC Schedule 1)",
            })
    return records

# ─── TSB OCCURRENCE DATA ───────────────────────────────────────────────────────

def fetch_tsb_occurrences():
    """
    Fetch TSB rail occurrence data.
    Dataset: https://www.tsb-bst.gc.ca/eng/stats/rail/data-5.html
    The TSB publishes downloadable CSV via the Open Government Portal.
    We query for the Dundas Subdivision filter as the pilot corridor.
    """
    # TSB Open Gov dataset ID for rail occurrences
    TSB_DATASET = "https://open.canada.ca/data/en/dataset/9705e1b3-6523-4490-9a97-4484a2f2a3cc"
    TSB_CSV_URL = "https://www.bst-tsb.gc.ca/eng/stats/rail/datasets/rail_occurrence_data.csv"

    results = []
    try:
        r = safe_get(TSB_CSV_URL, timeout=45)
        reader = csv.DictReader(StringIO(r.text))
        for row in reader:
            subdivision = row.get("Subdivision","").strip()
            if not subdivision:
                continue
            year = row.get("Year","").strip()
            dg   = row.get("Dangerous_Goods_Indicator","").strip().upper()
            occ_type = row.get("Occurrence_Type","").strip()
            results.append({
                "year": year,
                "subdivision": subdivision,
                "occurrence_type": occ_type,
                "dangerous_goods": dg in ("Y","YES","1","TRUE"),
                "fatalities": _int(row.get("Fatalities","0")),
                "injuries":   _int(row.get("Injuries","0")),
                "cars_derailed": _int(row.get("Cars_Derailed","0")),
            })
        dundas = [r for r in results if "dundas" in r["subdivision"].lower()]
        return _ok(
            "tsb_occurrences",
            {
                "total_records": len(results),
                "dundas_sub_total": len(dundas),
                "dundas_sub_with_dg": sum(1 for r in dundas if r["dangerous_goods"]),
                "dundas_sub_records": dundas[-50:],  # last 50 for dashboard
            },
            source="TSB Rail Occurrence Database",
            note="All rail occurrences 1983–present; Dundas Sub filtered for pilot",
        )
    except Exception as e:
        # Graceful fallback — seed with known incidents from public TSB reports
        known = [
            {"year":"2008","subdivision":"Dundas","occurrence_type":"Derailment",
             "dangerous_goods":False,"fatalities":0,"injuries":0,"cars_derailed":0,
             "note":"TSB R08T0029 — Bayview Junction Mile 0.6; wheel failure at curve where Dundas and Oakville Subs join. No DG release."},
            {"year":"1995","subdivision":"Dundas","occurrence_type":"Derailment",
             "dangerous_goods":True,"fatalities":0,"injuries":0,"cars_derailed":3,
             "note":"TSB R95T0262 — Brantford Yard; 3 butane tank cars (UN 1075) derailed; precautionary evacuations in adjacent residential area."},
        ]
        notable = [
            {"year":"2013","location":"Lac-Mégantic, QC","subdivision":"Sherbrooke Sub (MMA)",
             "dangerous_goods":True,"fatalities":47,"cars_derailed":63,
             "note":"TSB R13D0054 — Deadliest freight rail disaster in Canadian history. 72 tank cars UN 1267 crude oil; 6 million litres spilled; 47 killed; runaway train reached 104 km/h. Eliminated DOT-111 tank cars; mandatory 2-person crews."},
            {"year":"2019","location":"St-Lazare, MB","subdivision":"CN Rivers Sub",
             "dangerous_goods":True,"fatalities":0,"cars_derailed":37,
             "note":"TSB R19W0050 — Largest crude oil release by volume. 37 TC/DOT-117R tank cars derailed; 815,000 litres UN 1267 crude oil released from 17 breached cars. Failed rail joint."},
            {"year":"2024","location":"Longueuil, QC","subdivision":"CN St-Hyacinthe Sub",
             "dangerous_goods":True,"fatalities":0,"cars_derailed":8,
             "note":"TSB R24D0080 — 8 cars derailed at Southwark Yard. DG release; safety perimeter; TC remedial measures specialists deployed."},
        ]
        return _ok(
            "tsb_occurrences",
            {
                "total_records": len(known),
                "dundas_sub_total": len(known),
                "dundas_sub_with_dg": sum(1 for r in known if r["dangerous_goods"]),
                "dundas_sub_records": known,
                "notable_canadian_incidents": notable,
                "fallback": True,
            },
            source="TSB (seed — live CSV unavailable)",
            note=str(e),
        )

def _int(v):
    try:
        return int(str(v).strip())
    except:
        return 0

# ─── TC WEEKLY FREIGHT PERFORMANCE ────────────────────────────────────────────

def fetch_tc_weekly_freight():
    """
    Transport Canada Weekly Freight Rail Service & Performance data.
    Published at: https://tdih-cdit.tc.canada.ca/en
    Data endpoint: https://tc.canada.ca/en/corporate-services/transparency/
                   briefing-documents/rail-service-data (weekly JSON/CSV)
    """
    TC_FREIGHT_URL = ("https://tc.canada.ca/sites/default/files/2024-01/"
                      "weekly-freight-rail-service-performance-data.csv")
    try:
        r = safe_get(TC_FREIGHT_URL, timeout=30)
        reader = csv.DictReader(StringIO(r.text))
        rows = list(reader)
        if not rows:
            raise ValueError("empty response")
        latest = rows[-1]
        return _ok(
            "tc_weekly_freight",
            {
                "week_ending": latest.get("Week_Ending") or latest.get("week_ending",""),
                "cn_cars_on_line": _int(latest.get("CN_Cars_On_Line",0)),
                "cp_cars_on_line": _int(latest.get("CP_Cars_On_Line",0)),
                "cn_velocity_mph": latest.get("CN_Train_Speed",""),
                "cp_velocity_mph": latest.get("CP_Train_Speed",""),
                "cn_dwell_hours":  latest.get("CN_Dwell_Hours",""),
                "cp_dwell_hours":  latest.get("CP_Train_Speed",""),
                "total_weeks": len(rows),
            },
            source="Transport Canada Weekly Freight Rail Service & Performance",
        )
    except Exception as e:
        return _err("tc_weekly_freight", "Transport Canada", e)

# ─── COMMUNITY OBSERVATION FEED ───────────────────────────────────────────────

def fetch_community_observations():
    """
    Read structured community rail observations submitted as GitHub Issues
    on the railwatch-observations repo (label: observation).

    Issue format (markdown body):
      **Date:** 2026-06-12
      **Location:** CN Dundas Sub — Hamilton corridor (eastbound)
      **Placard class:** 8
      **UN number:** 1791
      **Cars observed:** 4
      **Direction:** East
      **Notes:** Observed approx 19:00 eastbound

    Falls back to example seed if repo is private or unavailable.
    """
    GITHUB_ISSUES_URL = ("https://api.github.com/repos/Sargjones/railwatch-observations"
                         "/issues?labels=observation&state=open&per_page=50")
    try:
        r = safe_get(GITHUB_ISSUES_URL, timeout=20)
        issues = r.json()
        observations = []
        for issue in issues:
            body = issue.get("body","") or ""
            obs = _parse_observation_body(body)
            obs["submitted_at"] = issue.get("created_at","")
            obs["issue_number"] = issue.get("number")
            observations.append(obs)
        return _ok(
            "community_observations",
            {"count": len(observations), "observations": observations},
            source="GitHub Issues / railwatch-observations",
        )
    except Exception as e:
        # Seed with the observation that started this platform
        seed_obs = [
            {
                "date": "2026-06-12",
                "location": "CN Dundas Sub — Hamilton corridor",
                "subdivision": "CN Dundas Sub",
                "direction": "East",
                "placard_class": "8",
                "un_number": "1791",
                "name": "HYPOCHLORITE SOLUTION (sodium hypochlorite)",
                "cars_observed": "multiple",
                "notes": "Observed eastbound through CN Dundas Sub approx 19:00",
                "submitted_at": "2026-06-13T00:00:00Z",
                "seed": True,
            }
        ]
        return _ok(
            "community_observations",
            {"count": len(seed_obs), "observations": seed_obs, "fallback": True},
            source="Seed observation",
            note=str(e),
        )

def _parse_observation_body(body):
    """Extract structured fields from GitHub Issue markdown body."""
    fields = {
        "date": "", "location": "", "subdivision": "", "direction": "",
        "placard_class": "", "un_number": "", "cars_observed": "", "notes": "",
    }
    patterns = {
        "date":          r"\*\*Date:\*\*\s*(.+)",
        "location":      r"\*\*Location:\*\*\s*(.+)",
        "placard_class": r"\*\*Placard class:\*\*\s*(.+)",
        "un_number":     r"\*\*UN number:\*\*\s*(.+)",
        "cars_observed": r"\*\*Cars observed:\*\*\s*(.+)",
        "direction":     r"\*\*Direction:\*\*\s*(.+)",
        "notes":         r"\*\*Notes:\*\*\s*(.+)",
    }
    for field, pattern in patterns.items():
        m = re.search(pattern, body, re.IGNORECASE)
        if m:
            fields[field] = m.group(1).strip()
    return fields

# ─── OSM CORRIDOR GEOMETRY ─────────────────────────────────────────────────────

def fetch_osm_corridor(osm_relation_id):
    """
    Fetch rail corridor geometry from OpenStreetMap Overpass API.
    Returns a simplified linestring as list of [lat, lon] pairs.
    """
    OVERPASS = "https://overpass-api.de/api/interpreter"
    query = f"""
    [out:json][timeout:30];
    relation({osm_relation_id});
    way(r);
    node(w);
    out skel;
    """
    try:
        r = requests.post(OVERPASS, data={"data": query}, timeout=35,
                          headers={"User-Agent":"RailWatch-Canada/1.0"})
        r.raise_for_status()
        elements = r.json().get("elements", [])
        nodes = {e["id"]: [e["lat"], e["lon"]] for e in elements if e["type"]=="node"}
        # Return first 200 node points as simplified corridor
        pts = list(nodes.values())[:200]
        return _ok("osm_corridor", {"relation_id": osm_relation_id, "points": pts,
                                     "point_count": len(pts)},
                   source="OpenStreetMap Overpass API")
    except Exception as e:
        return _err("osm_corridor", "OpenStreetMap", e)

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def run():
    print(f"RailWatch scraper starting — {datetime.datetime.utcnow().isoformat()}Z")
    run_date = datetime.date.today().isoformat()

    # 1. TDG lookup table (write separately)
    print("Fetching TDG Schedule 1 lookup table...")
    tdg_records = fetch_tdg_lookup()
    tdg_payload = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "record_count": len(tdg_records),
        "class_labels": TDG_CLASS_LABELS,
        "records": tdg_records,
    }
    with open(OUTPUT_TDG, "w") as f:
        json.dump(tdg_payload, f, indent=2)
    print(f"  Written: {OUTPUT_TDG} ({len(tdg_records)} TDG records)")

    # 2. Core data fetches
    print("Fetching TSB occurrences...")
    tsb = fetch_tsb_occurrences()

    print("Fetching TC weekly freight performance...")
    freight = fetch_tc_weekly_freight()

    print("Fetching community observations...")
    observations = fetch_community_observations()

    print("Fetching OSM corridor geometry (Dundas Sub)...")
    osm = fetch_osm_corridor(CORRIDORS["dundas_sub"]["osm_relation"])

    # 3. Assemble payload
    payload = {
        "meta": {
            "platform": "RailWatch Canada",
            "parent": "Critical TO (criticalto.ca)",
            "version": "1.0.0",
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "run_date": run_date,
            "pilot_corridor": CORRIDORS["dundas_sub"],
        },
        "indicators": [tsb, freight, observations],
        "corridor_geometry": osm,
        "corridors": CORRIDORS,
    }

    for path in [OUTPUT_LATEST, OUTPUT_ARCHIVE]:
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"  Written: {path}")

    # Summary
    ok_count  = sum(1 for i in payload["indicators"] if i["status"] == "ok")
    err_count = sum(1 for i in payload["indicators"] if i["status"] == "error")
    print(f"\nDone — {ok_count} ok, {err_count} errors")

if __name__ == "__main__":
    run()
