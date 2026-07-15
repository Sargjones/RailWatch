"""
railwatch_firewatch.py — RailWatch Fire Watch module
Part of the Critical TO infrastructure intelligence family (criticalto.ca)

Correlates active wildfire data against Ontario rail corridor geometry to
surface TDG-relevant exposure: trains on subdivisions where fire activity
is at or near the right-of-way, especially where dangerous-goods movement
is likely and public notice is otherwise limited to social media virality
rather than structured disclosure.

Pipeline (planned):

  1. FETCH   — pull active fire hotspots/perimeters from CWFIS (NRCan) and
               the Ontario active fire list. Both are public but not
               formally structured as an API for CWFIS hotspots (KML/shapefile
               exports) — this stage will need a small parser, not just a
               JSON GET.
  2. BUFFER  — build a buffer polygon (default 5 km, configurable per tier)
               around each active fire perimeter/hotspot.
  3. INTERSECT — test buffer polygons against subdivision geometry loaded
               from cn_track_filtered.geojson and ontario_northland_track.geojson
               (see railwatch_corridors_on.json for the subdivision registry
               this module now watches — expanded province-wide 2026-07-15,
               was previously limited to the 3-corridor pilot).
  4. FLAG    — any subdivision with an intersecting buffer becomes a
               candidate incident. Tier 3 subdivisions (remote, transcon
               main lines through unorganized territory — see
               railwatch_corridors_on.json) are the priority watch list,
               since they combine long single-track exposure with the
               least redundant public reporting.
  5. ENRICH  — cross-reference against CN/CPKC/ONT service alerts and
               OPP/community evacuation notices where available. This stage
               is manual/event-driven for now (see incidents[].sources in
               railwatch_firewatch.json) until a reliable structured feed
               is identified.
  6. WRITE   — append/update entries in railwatch_firewatch.json following
               the incident schema below. Existing incidents are updated
               in place by id; new detections get a new FW-YYYY-NNN id.

This module does not yet run automatically. It was seeded manually
(FW-2026-001, Armstrong ON / Allanwater Sub, 15 Jul 2026) following a
viral wildfire video. Wiring steps 1-3 into the daily GitHub Actions run
(scrape.yml) is the next step — flagged as a follow-up, not done here.

Incident schema — see railwatch_firewatch.json for the authoritative
example (FW-2026-001). Required fields: id, status, headline, date_reported,
location (lat/lon), corridor (operator/subdivision), sources.

Author: SJonesG / Critical TO
"""

import json
import datetime
import os

# ── PATHS ──────────────────────────────────────────────────────────────────

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORRIDORS_PATH = os.path.join(REPO_ROOT, "railwatch_corridors_on.json")
FIREWATCH_PATH = os.path.join(REPO_ROOT, "railwatch_firewatch.json")
CN_GEOJSON_PATH = os.path.join(REPO_ROOT, "cn_track_filtered.geojson")
ONT_GEOJSON_PATH = os.path.join(REPO_ROOT, "ontario_northland_track.geojson")

# Buffer distance (km) by corridor tier — tighter for dense Tier 1 corridors
# where any nearby fire is already newsworthy through other channels;
# wider for Tier 3 remote corridors where fire and rail are often the only
# two things happening in the area and correlation is the main signal.
BUFFER_KM_BY_TIER = {
    1: 3,
    2: 5,
    3: 8,
}


# ── STAGE 1: FETCH (stub) ────────────────────────────────────────────────

def fetch_active_fires():
    """
    Placeholder. Planned sources:
      - CWFIS hotspots (NRCan): https://cwfis.cfs.nrcan.gc.ca/datamart
        (KML/shapefile, not a clean JSON API — needs a small parser)
      - Ontario active fire list: https://www.ontario.ca/page/forest-fires
        (HTML table, would need scraping like railwatch_scraper.py does
        for other sources)
    Not implemented — network access to these domains isn't available from
    this environment. Returns an empty list so the rest of the pipeline is
    at least testable end-to-end against manually seeded data.
    """
    return []


# ── STAGE 2/3: BUFFER + INTERSECT (stub) ────────────────────────────────

def load_corridor_registry():
    with open(CORRIDORS_PATH, "r") as f:
        return json.load(f)


def load_subdivision_geometry():
    """Load and index subdivision features from both CN and ONT geojson."""
    index = {}
    for path, operator in [(CN_GEOJSON_PATH, "CN"), (ONT_GEOJSON_PATH, "ONT")]:
        if not os.path.exists(path):
            continue
        with open(path, "r") as f:
            data = json.load(f)
        for feature in data.get("features", []):
            sub = feature.get("properties", {}).get("subdivision")
            if not sub:
                continue
            key = (operator, sub)
            index.setdefault(key, []).append(feature)
    return index


def intersect_fires_with_corridors(fires, corridor_geometry):
    """
    Placeholder for the actual buffer/intersect geometry logic (would use
    shapely in the real implementation — matches the dependency pattern
    already in requirements.txt if geopandas/shapely get added).
    Returns a list of (fire, operator, subdivision, tier) matches.
    """
    matches = []
    # Not implemented pending fetch_active_fires() returning real data.
    return matches


# ── STAGE 6: WRITE ────────────────────────────────────────────────────────

def load_firewatch_data():
    with open(FIREWATCH_PATH, "r") as f:
        return json.load(f)


def save_firewatch_data(data):
    data["meta"]["generated_at"] = datetime.datetime.utcnow().strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    with open(FIREWATCH_PATH, "w") as f:
        json.dump(data, f, indent=2)


def next_incident_id(data, year=None):
    year = year or datetime.datetime.utcnow().year
    existing = [
        inc["id"] for inc in data.get("incidents", [])
        if inc["id"].startswith(f"FW-{year}-")
    ]
    n = len(existing) + 1
    return f"FW-{year}-{n:03d}"


def upsert_incident(data, incident):
    """Update an existing incident by id, or append a new one."""
    for i, existing in enumerate(data["incidents"]):
        if existing["id"] == incident["id"]:
            data["incidents"][i] = incident
            return data
    data["incidents"].append(incident)
    return data


# ── MAIN ──────────────────────────────────────────────────────────────────

def run():
    corridors = load_corridor_registry()
    geometry = load_subdivision_geometry()
    fires = fetch_active_fires()
    matches = intersect_fires_with_corridors(fires, geometry)

    if not matches:
        print(
            "railwatch_firewatch: no automated fire/corridor intersections "
            "this run (fetch_active_fires is a stub — see module docstring). "
            f"{len(corridors.get('operators', {}))} operators / "
            f"{sum(len(v.get('subdivisions', {})) for v in corridors.get('operators', {}).values())} "
            "subdivisions loaded from railwatch_corridors_on.json."
        )
        return

    data = load_firewatch_data()
    for match in matches:
        # incident construction from match would go here once
        # fetch_active_fires() and intersect_fires_with_corridors() are real
        pass
    save_firewatch_data(data)


if __name__ == "__main__":
    run()
