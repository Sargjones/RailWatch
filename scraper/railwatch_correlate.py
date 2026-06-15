"""
railwatch_correlate.py — RailWatch consist correlation engine
Part of the Critical TO infrastructure intelligence family (criticalto.ca)

Cross-references train symbol sightings across multiple observer channels
to infer train movement, speed, and probable destination corridor.

Example:
  Bayview Junction (Hamilton): CN 368 observed eastbound 08:15
  Brockville: CN 368 observed eastbound 10:47
  → Same consist, 2h32m transit, ~175km, ~69km/h → consistent with CN manifest freight
  → Destination: Montreal or east of Brockville on Kingston Sub

Author: SJonesG / Critical TO
"""

import json
import datetime
import math
import os

# ── KNOWN STATION COORDINATES ────────────────────────────────────────────────
# Used to calculate distance and transit time between sightings

STATIONS = {
    "Bayview Junction":  {"lat": 43.2870, "lon": -79.7760, "mile": 0,   "sub": "CN Oakville/Dundas Sub"},
    "Aldershot":         {"lat": 43.3050, "lon": -79.7500, "mile": 4,   "sub": "CN Oakville Sub"},
    "Burlington":        {"lat": 43.3200, "lon": -79.8000, "mile": 8,   "sub": "CN Oakville Sub"},
    "Oakville":          {"lat": 43.4472, "lon": -79.6877, "mile": 20,  "sub": "CN Oakville Sub"},
    "Toronto":           {"lat": 43.6450, "lon": -79.3800, "mile": 38,  "sub": "CN Oakville Sub"},
    "Pickering":         {"lat": 43.8354, "lon": -79.0893, "mile": 55,  "sub": "CN Kingston Sub"},
    "Oshawa":            {"lat": 43.8971, "lon": -78.8658, "mile": 67,  "sub": "CN Kingston Sub"},
    "Cobourg":           {"lat": 43.9600, "lon": -78.1700, "mile": 95,  "sub": "CN Kingston Sub"},
    "Trenton":           {"lat": 44.1000, "lon": -77.5800, "mile": 118, "sub": "CN Kingston Sub"},
    "Belleville":        {"lat": 44.1600, "lon": -77.3800, "mile": 127, "sub": "CN Kingston Sub"},
    "Kingston":          {"lat": 44.2300, "lon": -76.4800, "mile": 167, "sub": "CN Kingston Sub"},
    "Brockville":        {"lat": 44.5800, "lon": -75.7000, "mile": 207, "sub": "CN Kingston Sub"},
    "Silver Creek":      {"lat": 44.7500, "lon": -76.2500, "mile": 185, "sub": "CN Smiths Falls Sub"},
    "Smiths Falls":      {"lat": 44.9000, "lon": -76.0200, "mile": 195, "sub": "CN Smiths Falls Sub"},
    "Ottawa":            {"lat": 45.4230, "lon": -75.6950, "mile": 230, "sub": "CN Smiths Falls Sub"},
    "Hamilton":          {"lat": 43.2700, "lon": -79.8100, "mile": -5,  "sub": "CN Dundas Sub"},
    "London":            {"lat": 43.0080, "lon": -80.9960, "mile": -85, "sub": "CN Dundas Sub"},
    "Windsor":           {"lat": 42.3149, "lon": -83.0364, "mile": -190,"sub": "CN Dundas Sub"},
    "MacTier":           {"lat": 44.9500, "lon": -79.7300, "mile": 95,  "sub": "CPKC MacTier Sub"},
}

# Typical speed ranges for CN consist types (km/h)
SPEED_PROFILES = {
    "intermodal":  {"min": 65, "max": 100, "label": "Intermodal unit train"},
    "manifest":    {"min": 40, "max": 75,  "label": "Manifest freight"},
    "tank":        {"min": 35, "max": 65,  "label": "Tank car consist"},
    "auto_rack":   {"min": 55, "max": 85,  "label": "Automotive rack train"},
    "hopper":      {"min": 40, "max": 70,  "label": "Hopper/bulk train"},
    "unknown":     {"min": 35, "max": 100, "label": "Unknown consist type"},
}

def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate great-circle distance between two points in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))

def parse_obs_time(obs):
    """Try to extract a datetime from an observation record."""
    date_str = obs.get("date", "")
    pub = obs.get("published_at", "")
    # Try exact date first
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(date_str, fmt)
        except:
            pass
    # Fall back to published_at
    try:
        return datetime.datetime.fromisoformat(pub.replace("Z", "+00:00"))
    except:
        return None

def correlate(youtube_data_path="railwatch_youtube_latest.json",
              output_path="railwatch_correlations.json"):
    """
    Load all observations and find matching train symbols across channels.
    Returns list of correlated sighting pairs with inferred movement data.
    """
    if not os.path.exists(youtube_data_path):
        print(f"  Correlate: {youtube_data_path} not found")
        return []

    with open(youtube_data_path) as f:
        data = json.load(f)

    observations = data.get("observations", [])

    # Index observations by train symbol
    by_symbol = {}
    for obs in observations:
        symbols = obs.get("train_symbols") or []
        for sym in symbols:
            key = sym["symbol"].upper().replace(" ", "")
            if key not in by_symbol:
                by_symbol[key] = []
            by_symbol[key].append(obs)

    correlations = []
    for symbol, sightings in by_symbol.items():
        if len(sightings) < 2:
            continue  # Need at least 2 sightings to correlate

        # Sort by date
        dated = [(s, parse_obs_time(s)) for s in sightings]
        dated = [(s, t) for s, t in dated if t is not None]
        dated.sort(key=lambda x: x[1])

        # Compare each pair
        for i in range(len(dated) - 1):
            obs_a, time_a = dated[i]
            obs_b, time_b = dated[i + 1]

            loc_a = obs_a.get("location")
            loc_b = obs_b.get("location")
            if not loc_a or not loc_b or loc_a == loc_b:
                continue

            # Get station coordinates
            sta_a = STATIONS.get(loc_a)
            sta_b = STATIONS.get(loc_b)
            if not sta_a or not sta_b:
                continue

            # Calculate distance and time delta
            dist_km = haversine_km(
                sta_a["lat"], sta_a["lon"],
                sta_b["lat"], sta_b["lon"]
            )
            delta_h = (time_b - time_a).total_seconds() / 3600

            if delta_h <= 0 or delta_h > 48:
                continue  # Same time or too far apart

            speed_kmh = dist_km / delta_h

            # Classify speed against consist profile
            commodity = obs_a.get("commodity_type") or obs_b.get("commodity_type") or "unknown"
            profile = SPEED_PROFILES.get(commodity, SPEED_PROFILES["unknown"])
            speed_plausible = profile["min"] <= speed_kmh <= profile["max"]

            # Infer direction from mile markers if available
            mile_a = sta_a.get("mile", 0)
            mile_b = sta_b.get("mile", 0)
            inferred_direction = "East" if mile_b > mile_a else "West"

            # Direction consistency check
            dir_a = obs_a.get("direction")
            dir_b = obs_b.get("direction")
            direction_consistent = True
            if dir_a and dir_b and dir_a != dir_b:
                direction_consistent = False

            corr = {
                "symbol":        symbol,
                "sighting_a": {
                    "location":  loc_a,
                    "date":      obs_a.get("date"),
                    "channel":   obs_a.get("channel"),
                    "direction": dir_a,
                    "video_url": obs_a.get("video_url"),
                    "title":     obs_a.get("raw_title", "")[:60],
                },
                "sighting_b": {
                    "location":  loc_b,
                    "date":      obs_b.get("date"),
                    "channel":   obs_b.get("channel"),
                    "direction": dir_b,
                    "video_url": obs_b.get("video_url"),
                    "title":     obs_b.get("raw_title", "")[:60],
                },
                "transit": {
                    "distance_km":         round(dist_km, 1),
                    "elapsed_hours":       round(delta_h, 2),
                    "avg_speed_kmh":       round(speed_kmh, 1),
                    "speed_plausible":     speed_plausible,
                    "consist_profile":     profile["label"],
                    "inferred_direction":  inferred_direction,
                    "direction_consistent":direction_consistent,
                },
                "commodity":    commodity,
                "dg_likely":    obs_a.get("dg_likely") or obs_b.get("dg_likely"),
                "confidence":   "high" if speed_plausible and direction_consistent else "low",
                "correlated_at":datetime.datetime.utcnow().isoformat() + "Z",
            }
            correlations.append(corr)
            print(f"  CORRELATION: {symbol} · {loc_a} → {loc_b} · "
                  f"{dist_km:.0f}km in {delta_h:.1f}h · {speed_kmh:.0f}km/h · "
                  f"{'✓' if speed_plausible else '?'} speed")

    payload = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "total":        len(correlations),
        "high":         sum(1 for c in correlations if c["confidence"] == "high"),
        "dg_correlations": sum(1 for c in correlations if c["dg_likely"]),
        "correlations": sorted(correlations,
                               key=lambda x: x["confidence"] == "high",
                               reverse=True),
    }

    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"  Correlations: {len(correlations)} total · "
          f"{payload['high']} high confidence · "
          f"{payload['dg_correlations']} involve DG-likely consists")
    return correlations

if __name__ == "__main__":
    correlate()
