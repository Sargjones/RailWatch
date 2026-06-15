"""
railwatch_cameras.py — RailWatch 511on.ca webcam scraper
Part of the Critical TO infrastructure intelligence family (criticalto.ca)

Fetches all Ontario MTO traffic cameras from the 511on.ca public API,
filters for cameras within 2km of defined rail corridor alignments,
and writes railwatch_cameras.json for the dashboard map layer.

Data source: Ontario 511 Developer API (public, no key required)
  https://511on.ca/api/v2/get/cameras?format=json&lang=en
  Throttle: 10 calls per 60 seconds

Author: SJonesG / Critical TO
"""

import json
import math
import datetime
import requests

# ── CONFIG ────────────────────────────────────────────────────────────────────

CAMERAS_URL   = "https://511on.ca/api/v2/get/cameras?format=json&lang=en"
OUTPUT_FILE   = "railwatch_cameras.json"
CORRIDOR_RADIUS_KM = 2.5   # cameras within this distance of corridor are included

# ── CORRIDOR WAYPOINTS ────────────────────────────────────────────────────────
# Simplified corridor centrelines — cameras within CORRIDOR_RADIUS_KM of any
# segment between consecutive waypoints are included.

CORRIDORS = {
    "CN Dundas / Oakville Sub": [
        (42.3149,-83.0364), # Windsor
        (42.5800,-82.3500), # Chatham area
        (43.0080,-80.9960), # London
        (43.0900,-80.6500), # Woodstock
        (43.1700,-80.2500), # mid-Dundas Sub
        (43.2700,-79.8100), # Hamilton
        (43.2870,-79.7760), # Bayview Junction
        (43.3050,-79.7500), # Aldershot
        (43.4200,-79.4200), # Oakville
        (43.5200,-79.3500), # Port Credit
        (43.6450,-79.3800), # Toronto Union
    ],
    "CN Kingston Sub": [
        (43.6450,-79.3800), # Toronto Union
        (43.8354,-79.0893), # Pickering
        (43.8971,-78.8658), # Oshawa
        (43.9600,-78.1700), # Cobourg
        (44.1600,-77.3800), # Belleville
        (44.2300,-76.4800), # Kingston
        (44.5800,-75.7000), # Brockville
    ],
    "CN Smiths Falls Sub": [
        (45.4230,-75.6950), # Ottawa
        (44.9000,-76.0200), # Smiths Falls
        (44.2500,-76.9500), # Napanee
    ],
    "CN Chatham Sub": [
        (42.3149,-83.0364), # Windsor
        (42.4900,-82.5500), # Chatham
        (42.9744,-82.4058), # Sarnia
    ],
    "CN Halton Sub": [
        (43.6450,-79.3800), # Toronto
        (43.6700,-79.6300), # Brampton
        (43.6500,-79.8500), # Georgetown
        (43.3100,-79.8000), # Burlington
    ],
    "CN Bala Sub": [
        (43.6450,-79.3800), # Toronto
        (43.9500,-79.4500), # Richmond Hill
        (44.3900,-79.6800), # Barrie
        (45.0500,-79.9000), # Parry Sound
        (46.4900,-80.9900), # Sudbury
    ],
}

# ── GEOMETRY ─────────────────────────────────────────────────────────────────

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))

def point_to_segment_km(px, py, ax, ay, bx, by):
    """Minimum distance from point P to line segment AB in km."""
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return haversine_km(px, py, ax, ay)
    t = max(0, min(1, ((px-ax)*dx + (py-ay)*dy) / (dx*dx + dy*dy)))
    return haversine_km(px, py, ax + t*dx, ay + t*dy)

def nearest_corridor(lat, lon):
    """
    Find the nearest corridor to a camera and the distance to it.
    Returns (corridor_name, distance_km) or (None, inf)
    """
    best_name, best_dist = None, float('inf')
    for name, waypoints in CORRIDORS.items():
        for i in range(len(waypoints) - 1):
            a, b = waypoints[i], waypoints[i+1]
            d = point_to_segment_km(lat, lon, a[0], a[1], b[0], b[1])
            if d < best_dist:
                best_dist = d
                best_name = name
    return best_name, best_dist

# ── FETCH ─────────────────────────────────────────────────────────────────────

def fetch_cameras():
    """Fetch all Ontario 511 cameras. Returns list of camera dicts."""
    try:
        r = requests.get(
            CAMERAS_URL,
            timeout=30,
            headers={"User-Agent": "RailWatch-Canada/1.0 (criticalto.ca; contact@criticalto.ca)"}
        )
        r.raise_for_status()
        data = r.json()
        # API returns list directly or wrapped — handle both
        if isinstance(data, list):
            return data
        return data.get("cameras", data.get("Cameras", []))
    except Exception as e:
        print(f"  511on API error: {e}")
        return []

def process_cameras(raw_cameras):
    """
    Filter cameras to those within CORRIDOR_RADIUS_KM of a rail corridor.
    Returns list of enriched camera dicts.
    """
    results = []
    for cam in raw_cameras:
        # Handle both camelCase and PascalCase field names
        lat = cam.get("Latitude") or cam.get("latitude")
        lon = cam.get("Longitude") or cam.get("longitude")
        if not lat or not lon:
            continue
        lat, lon = float(lat), float(lon)

        corridor, dist_km = nearest_corridor(lat, lon)
        if dist_km > CORRIDOR_RADIUS_KM:
            continue

        cam_id    = cam.get("Id") or cam.get("id", "")
        name      = cam.get("Name") or cam.get("Location") or cam.get("name", "")
        roadway   = cam.get("Roadway") or cam.get("RoadwayName") or cam.get("roadway", "")
        status    = cam.get("Status") or cam.get("status", "Unknown")

        # Build view URL
        views = cam.get("Views") or cam.get("views") or []
        if isinstance(views, list) and views:
            view_url = (views[0].get("Url") or views[0].get("url") or
                       f"https://511on.ca/map/Cctv/{cam_id}")
        else:
            view_url = f"https://511on.ca/map/Cctv/{cam_id}"

        results.append({
            "id":          cam_id,
            "name":        name,
            "roadway":     roadway,
            "lat":         lat,
            "lon":         lon,
            "status":      status,
            "view_url":    view_url,
            "corridor":    corridor,
            "dist_km":     round(dist_km, 2),
            "enabled":     status.lower() == "enabled",
        })

    # Sort by corridor then distance
    results.sort(key=lambda x: (x["corridor"], x["dist_km"]))
    return results

# ── MAIN ─────────────────────────────────────────────────────────────────────

def run(output_file=OUTPUT_FILE):
    print(f"  Fetching 511on cameras...")
    raw = fetch_cameras()

    if not raw:
        print("  No cameras returned — using empty dataset")
        cameras = []
    else:
        print(f"  {len(raw)} total cameras fetched, filtering to {CORRIDOR_RADIUS_KM}km of corridors...")
        cameras = process_cameras(raw)

    # Summary by corridor
    by_corridor = {}
    for cam in cameras:
        c = cam["corridor"]
        if c not in by_corridor:
            by_corridor[c] = {"total": 0, "enabled": 0}
        by_corridor[c]["total"] += 1
        if cam["enabled"]:
            by_corridor[c]["enabled"] += 1

    for corridor, stats in by_corridor.items():
        print(f"    {corridor}: {stats['enabled']} enabled / {stats['total']} total")

    payload = {
        "generated_at":   datetime.datetime.utcnow().isoformat() + "Z",
        "source":         "Ontario 511 Developer API (511on.ca)",
        "total_cameras":  len(cameras),
        "enabled_cameras":sum(1 for c in cameras if c["enabled"]),
        "radius_km":      CORRIDOR_RADIUS_KM,
        "by_corridor":    by_corridor,
        "cameras":        cameras,
    }

    with open(output_file, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"  Cameras: {payload['enabled_cameras']} enabled near corridors → {output_file}")
    return payload

if __name__ == "__main__":
    run()
