"""
railwatch_cameras_ab.py — RailWatch 511 Alberta webcam scraper
Part of the Critical TO infrastructure intelligence family (criticalto.ca)

Fetches all Alberta 511 traffic cameras from the 511.alberta.ca public API,
filters for cameras within 2.5km of defined Alberta rail corridor alignments,
and writes railwatch_cameras_ab.json for the dashboard map layer.

Data source: 511 Alberta Developer API (public, no key required)
  https://511.alberta.ca/api/v2/get/cameras
  Throttling is enabled — keep call frequency modest.

Mirrors railwatch_cameras.py (Ontario). Kept as a separate file rather than
merged/parameterized, since the two provinces' corridor sets, throttle
behaviour, and camera mix (Banff townsite cams, WOOD highway cams, Calgary
intersection cams) are different enough to be worth maintaining independently
for now. Field-handling logic (camelCase/PascalCase fallbacks) is identical
to the Ontario script since both provinces use the same underlying 511/IBI
camera API schema.

Author: SJonesG / Critical TO
"""

import json
import math
import datetime
import requests

# ── CONFIG ────────────────────────────────────────────────────────────────────

CAMERAS_URL   = "https://511.alberta.ca/api/v2/get/cameras"
OUTPUT_FILE   = "railwatch_cameras_ab.json"
CORRIDOR_RADIUS_KM = 2.5   # cameras within this distance of corridor are included

# ── CORRIDOR WAYPOINTS ────────────────────────────────────────────────────────
# Simplified corridor centrelines — cameras within CORRIDOR_RADIUS_KM of any
# segment between consecutive waypoints are included.
# Matches the polylines added to index.html (national expansion, 2026-06-17).

CORRIDORS = {
    "CN Mainline (Manitoba-Alberta)": [
        (49.8951,-97.1384),  # Winnipeg
        (49.9700,-97.8000),  # Portage la Prairie
        (50.0300,-99.0000),
        (50.0300,-100.2400), # Rivers Sub
        (50.4000,-102.5000),
        (50.4500,-104.6178), # Regina area
        (50.8000,-107.0000),
        (52.8400,-110.8600), # Wainwright Sub
    ],
    "CN Edson Sub": [
        (53.5461,-113.4938), # Edmonton
        (53.5800,-114.8000),
        (53.5800,-116.4300), # Edson Sub
        (53.2000,-117.7000),
        (52.8734,-118.0814), # Jasper
    ],
    "CPKC Laggan / Mountain Sub": [
        (51.0447,-114.0719), # Calgary
        (51.0800,-114.8000),
        (51.1700,-115.5700), # Canmore / Banff
        (51.1700,-116.2000), # Laggan Sub (Lake Louise area)
        (51.1700,-116.9700),
        (51.1700,-117.6800), # Field, BC
        (51.1700,-117.9400), # Mountain Sub
    ],
    "CPKC Shuswap Sub": [
        (50.9981,-118.1957), # Revelstoke
        (50.9500,-119.0000),
        (50.9000,-119.2000), # Shuswap Sub
        (50.8000,-119.8000),
        (50.6745,-120.3273), # Kamloops
    ],
    "CPKC Red Deer Sub": [
        (51.0447,-114.0719), # Calgary
        (51.6000,-113.9500),
        (52.2681,-113.8112), # Red Deer Sub
        (53.0000,-113.7000),
        (53.5461,-113.4938), # Edmonton
    ],
    "CPKC Brooks Sub": [
        (51.0447,-114.0719), # Calgary
        (50.8000,-113.0000),
        (50.5640,-111.8980), # Brooks Sub
        (50.0420,-110.6770), # Medicine Hat
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
    """Fetch all Alberta 511 cameras. Returns list of camera dicts."""
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
        print(f"  511 Alberta API error: {e}")
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
        source    = cam.get("Source") or cam.get("source", "")
        # Status is inside Views array, not on camera object
        views = cam.get("Views") or cam.get("views") or []
        enabled_views = []
        if isinstance(views, list):
            for v in views:
                v_status = v.get("Status") or v.get("status", "")
                if v_status.lower() == "enabled":
                    enabled_views.append({
                        "url":         v.get("Url") or v.get("url", ""),
                        "description": v.get("Description") or v.get("description", ""),
                    })

        view_url = enabled_views[0]["url"] if enabled_views else f"https://511.alberta.ca/map/Cctv/{cam_id}"
        view_desc = enabled_views[0]["description"] if enabled_views else ""

        results.append({
            "id":           cam_id,
            "name":         name,
            "roadway":      roadway,
            "source_group": source,  # e.g. "Banff", "Calgary", "WOOD", "Parks"
            "lat":          lat,
            "lon":          lon,
            "view_url":     view_url,
            "view_desc":    view_desc,
            "view_count":   len(enabled_views),
            "corridor":     corridor,
            "dist_km":      round(dist_km, 2),
            "enabled":      len(enabled_views) > 0,
        })

    # Sort by corridor then distance
    results.sort(key=lambda x: (x["corridor"], x["dist_km"]))
    return results

# ── MAIN ─────────────────────────────────────────────────────────────────────

def run(output_file=OUTPUT_FILE):
    print(f"  Fetching 511 Alberta cameras...")
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
        "source":         "511 Alberta Developer API (511.alberta.ca)",
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
