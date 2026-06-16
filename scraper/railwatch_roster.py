"""
railwatch_roster.py — RailWatch locomotive roster builder
Part of the Critical TO infrastructure intelligence family (criticalto.ca)

Scans all accumulated observations and builds a roster of every locomotive
and rolling stock unit seen 2+ times. Produces railwatch_roster.json for
the Roster tab on the dashboard.

Sources per observation:
  - locomotives field: road numbers extracted from title/description text
  - consist.engines + consist.dpu: structured engine lists from descriptions

Priority sort:
  1. CN units (most common on Ontario corridors)
  2. VIA units
  3. CPKC/CP units
  4. Foreign/other (KCS, IC, etc.)

Author: SJonesG / Critical TO
"""

import json
import os
import re
import datetime

YOUTUBE_DATA    = "railwatch_youtube_latest.json"
BACKFILL_DATA   = "railwatch_backfill.json"
OUTPUT_FILE     = "railwatch_roster.json"
MIN_SIGHTINGS   = 2   # minimum sightings before a unit gets a card

# Road priority for display ordering
ROAD_PRIORITY = {
    "CN":    1,
    "VIA":   2,
    "CP":    3,
    "CPKC":  4,
    "KCS":   5,
    "IC":    6,
    "BNSF":  7,
    "UP":    8,
    "CSX":   9,
    "NS":    10,
    "GO":    11,
    "ONR":   12,
}

def road_sort_key(unit):
    """Sort by road priority then sighting count descending then number."""
    road = unit.get("road", "ZZZ").upper()
    priority = ROAD_PRIORITY.get(road, 99)
    return (priority, -unit.get("sighting_count", 0), unit.get("number", ""))

def extract_road_number(loco_string):
    """
    Parse a loco string into (road, number).
    Handles formats: "CN 3922", "CN3922", "CP 7603", "VIA 6439"
    Returns (road, number) or (None, None) if unparseable.
    """
    if not loco_string:
        return None, None
    s = str(loco_string).strip().upper()
    # Road + space + number
    m = re.match(r'^([A-Z]{2,5})\s+(\d{3,5})$', s)
    if m:
        return m.group(1), m.group(2)
    # Road + number no space
    m = re.match(r'^([A-Z]{2,5})(\d{3,5})$', s)
    if m:
        return m.group(1), m.group(2)
    return None, None

def is_loco_number(road, number):
    """
    Distinguish locomotive road numbers from train service symbols.
    Locos: 3-5 digit numbers (CN 3922, CP 7603)
    Service symbols: 1-3 digit numbers (CN 368, VIA 61) or letter-coded (Z148)
    """
    if not number:
        return False
    return len(number) >= 4  # 4+ digits = almost certainly a loco road number

def collect_locos_from_obs(obs):
    """
    Extract all locomotive road numbers from a single observation.
    Returns list of dicts: {road, number, role, train_symbol, ...}
    """
    locos = []
    train_symbols = obs.get("train_symbols") or []
    # Get the primary service symbol for this observation
    service_sym = next(
        (s["symbol"] for s in train_symbols
         if re.match(r'^(CN|VIA|CP|CPKC)\s*\d{1,3}$', s["symbol"], re.IGNORECASE)
         or re.match(r'^[A-Z]\d{3,4}$', s["symbol"], re.IGNORECASE)),
        None
    )

    # Source 1: locomotives field (extracted from text)
    for loco in (obs.get("locomotives") or []):
        road, number = extract_road_number(loco)
        if road and number and is_loco_number(road, number):
            locos.append({
                "road":         road,
                "number":       number,
                "role":         "unknown",
                "train_symbol": service_sym,
                "source":       "text_extraction",
            })

    # Source 2: consist.engines (structured from Brockville descriptions)
    consist = obs.get("consist") or {}
    for eng in (consist.get("engines") or []):
        road, number = extract_road_number(eng)
        if road and number:
            locos.append({
                "road":         road,
                "number":       number,
                "role":         "lead",
                "train_symbol": service_sym,
                "source":       "description_structured",
            })

    # Source 3: consist.dpu
    for dpu in (consist.get("dpu") or []):
        road, number = extract_road_number(dpu)
        if road and number:
            locos.append({
                "road":         road,
                "number":       number,
                "role":         "dpu",
                "train_symbol": service_sym,
                "source":       "description_structured",
                "dpu":          True,
            })

    # Source 4: train_symbols that are actually loco numbers
    # (scraper sometimes extracts these as symbols)
    for sym in train_symbols:
        road, number = extract_road_number(sym["symbol"])
        if road and number and is_loco_number(road, number):
            # Only add if not already captured above
            already = any(
                l["road"] == road and l["number"] == number
                for l in locos
            )
            if not already:
                locos.append({
                    "road":         road,
                    "number":       number,
                    "role":         "unknown",
                    "train_symbol": service_sym,
                    "source":       "symbol_extraction",
                })

    return locos

def build_roster(observations):
    """
    Build unit registry from all observations.
    Returns dict keyed by "{road}_{number}".
    """
    registry = {}

    for obs in observations:
        locos = collect_locos_from_obs(obs)
        for loco in locos:
            key = f"{loco['road']}_{loco['number']}"
            if key not in registry:
                registry[key] = {
                    "road":           loco["road"],
                    "number":         loco["number"],
                    "display":        f"{loco['road']} {loco['number']}",
                    "sighting_count": 0,
                    "first_seen":     obs.get("date", ""),
                    "last_seen":      obs.get("date", ""),
                    "corridors":      [],
                    "trains_led":     [],
                    "dpu_confirmed":  False,
                    "roles_seen":     [],
                    "sightings":      [],
                }

            unit = registry[key]
            unit["sighting_count"] += 1

            # Update date range
            obs_date = obs.get("date", "")
            if obs_date:
                if not unit["first_seen"] or obs_date < unit["first_seen"]:
                    unit["first_seen"] = obs_date
                if not unit["last_seen"] or obs_date > unit["last_seen"]:
                    unit["last_seen"] = obs_date

            # Corridor
            sub = obs.get("subdivision")
            if sub and sub not in unit["corridors"]:
                unit["corridors"].append(sub)

            # Trains led
            if loco.get("train_symbol") and loco["train_symbol"] not in unit["trains_led"]:
                unit["trains_led"].append(loco["train_symbol"])

            # DPU flag
            if loco.get("dpu"):
                unit["dpu_confirmed"] = True

            # Role
            role = loco.get("role", "unknown")
            if role not in unit["roles_seen"]:
                unit["roles_seen"].append(role)

            # Sighting record
            unit["sightings"].append({
                "date":         obs_date,
                "location":     obs.get("location"),
                "subdivision":  obs.get("subdivision"),
                "channel":      obs.get("channel"),
                "train_symbol": loco.get("train_symbol"),
                "direction":    obs.get("direction"),
                "role":         role,
                "dpu":          loco.get("dpu", False),
                "video_url":    obs.get("video_url"),
                "title":        obs.get("raw_title", "")[:60],
                "source":       loco.get("source"),
            })

    return registry

def run(youtube_path=YOUTUBE_DATA, backfill_path=BACKFILL_DATA,
        output_path=OUTPUT_FILE):

    # Load all observations
    all_observations = []

    if os.path.exists(youtube_path):
        with open(youtube_path) as f:
            data = json.load(f)
            obs = data.get("observations", [])
            all_observations.extend(obs)
            print(f"  Roster: loaded {len(obs)} observations from {youtube_path}")
    else:
        print(f"  Roster: {youtube_path} not found")

    if os.path.exists(backfill_path):
        with open(backfill_path) as f:
            data = json.load(f)
            obs = data.get("observations", [])
            all_observations.extend(obs)
            if obs:
                print(f"  Roster: loaded {len(obs)} backfill observations")

    if not all_observations:
        print("  Roster: no observations to process")
        return

    print(f"  Roster: processing {len(all_observations)} total observations...")

    # Build registry
    registry = build_roster(all_observations)

    # Filter to units seen MIN_SIGHTINGS+ times
    qualified = {
        k: v for k, v in registry.items()
        if v["sighting_count"] >= MIN_SIGHTINGS
    }

    # Sort sightings within each unit by date descending
    for unit in qualified.values():
        unit["sightings"].sort(
            key=lambda s: s.get("date", ""), reverse=True
        )

    # Sort units by priority
    sorted_units = sorted(qualified.values(), key=road_sort_key)

    # Summary stats
    by_road = {}
    for unit in sorted_units:
        road = unit["road"]
        by_road[road] = by_road.get(road, 0) + 1

    print(f"  Roster: {len(sorted_units)} units with {MIN_SIGHTINGS}+ sightings")
    for road, count in sorted(by_road.items(),
                               key=lambda x: ROAD_PRIORITY.get(x[0], 99)):
        print(f"    {road}: {count} units")

    payload = {
        "generated_at":  datetime.datetime.utcnow().isoformat() + "Z",
        "total_units":   len(sorted_units),
        "min_sightings": MIN_SIGHTINGS,
        "by_road":       by_road,
        "units":         sorted_units,
    }

    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"  Roster written: {output_path}")
    return payload

if __name__ == "__main__":
    run()
