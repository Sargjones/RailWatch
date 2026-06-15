"""
railwatch_correlate.py — RailWatch consist correlation engine
Part of the Critical TO infrastructure intelligence family (criticalto.ca)

Cross-references train symbol sightings across multiple observer channels
to infer train movement, speed, and probable destination corridor.

Correlation tiers:
  TIER 1 — Cross-observer: different channels, same service symbol, plausible speed
            Strongest signal — two independent observers confirm the same train.

  TIER 2 — Single-observer transit (chasing): same channel, same symbol, multiple
            locations same day. One person tracked the train themselves. Speed
            is verifiable. Car count comparison possible — if counts differ, flag
            as a potential consist split (cars set off on a branch or at a yard).

  TIER 3 — Consist anomaly: any sighting where consist_anomaly is flagged in the
            observation (set-off, lift, cut). These are surfaced regardless of
            whether a cross-observer match exists.

Symbol filtering:
  Only service symbols are correlated — scheduled train numbers and letter-coded
  symbols (CN 368, VIA 61, Z148, Q107, X309 etc). Locomotive road numbers
  (CN 3950, CP 7603, IC 2719 etc) are excluded — they appear across multiple
  videos because they're the same physical unit, not the same train service.

  Service symbol criteria:
    - CN/VIA/CP + 1-3 digit number: CN 61, VIA 1, CN 368, CP 421
    - Letter + 3-5 digit number: Z148, Q107, X309, A414, M394, L570
  Excluded:
    - Any road number where the numeric part is 4+ digits: CN 3950, CP 7603

Author: SJonesG / Critical TO
"""

import json
import datetime
import math
import os
import re

# ── KNOWN STATION COORDINATES ─────────────────────────────────────────────────

STATIONS = {
    "Bayview Junction":  {"lat": 43.2870, "lon": -79.7760, "mile": 0,    "sub": "CN Oakville/Dundas Sub"},
    "Aldershot":         {"lat": 43.3050, "lon": -79.7500, "mile": 4,    "sub": "CN Oakville Sub"},
    "Burlington":        {"lat": 43.3200, "lon": -79.8000, "mile": 8,    "sub": "CN Oakville Sub"},
    "Oakville":          {"lat": 43.4472, "lon": -79.6877, "mile": 20,   "sub": "CN Oakville Sub"},
    "Toronto":           {"lat": 43.6450, "lon": -79.3800, "mile": 38,   "sub": "CN Oakville Sub"},
    "Pickering":         {"lat": 43.8354, "lon": -79.0893, "mile": 55,   "sub": "CN Kingston Sub"},
    "Oshawa":            {"lat": 43.8971, "lon": -78.8658, "mile": 67,   "sub": "CN Kingston Sub"},
    "Cobourg":           {"lat": 43.9600, "lon": -78.1700, "mile": 95,   "sub": "CN Kingston Sub"},
    "Trenton":           {"lat": 44.1000, "lon": -77.5800, "mile": 118,  "sub": "CN Kingston Sub"},
    "Belleville":        {"lat": 44.1600, "lon": -77.3800, "mile": 127,  "sub": "CN Kingston Sub"},
    "Kingston":          {"lat": 44.2300, "lon": -76.4800, "mile": 167,  "sub": "CN Kingston Sub"},
    "Brockville":        {"lat": 44.5800, "lon": -75.7000, "mile": 207,  "sub": "CN Kingston Sub"},
    "Silver Creek":      {"lat": 44.7500, "lon": -76.2500, "mile": 185,  "sub": "CN Smiths Falls Sub"},
    "Smiths Falls":      {"lat": 44.9000, "lon": -76.0200, "mile": 195,  "sub": "CN Smiths Falls Sub"},
    "Ottawa":            {"lat": 45.4230, "lon": -75.6950, "mile": 230,  "sub": "CN Smiths Falls Sub"},
    "Hamilton":          {"lat": 43.2700, "lon": -79.8100, "mile": -5,   "sub": "CN Dundas Sub"},
    "London":            {"lat": 43.0080, "lon": -80.9960, "mile": -85,  "sub": "CN Dundas Sub"},
    "Windsor":           {"lat": 42.3149, "lon": -83.0364, "mile": -190, "sub": "CN Dundas Sub"},
    "MacTier":           {"lat": 44.9500, "lon": -79.7300, "mile": 95,   "sub": "CPKC MacTier Sub"},
    "Brampton":          {"lat": 43.6833, "lon": -79.7667, "mile": 28,   "sub": "CN Halton Sub"},
    "Sarnia":            {"lat": 42.9744, "lon": -82.4058, "mile": -175, "sub": "CN Chatham Sub"},
}

# Speed ranges by consist type (km/h)
SPEED_PROFILES = {
    "intermodal":  {"min": 65, "max": 100, "label": "Intermodal unit train"},
    "manifest":    {"min": 40, "max": 75,  "label": "Manifest freight"},
    "mixed":       {"min": 40, "max": 75,  "label": "Mixed manifest freight"},
    "tank":        {"min": 35, "max": 65,  "label": "Tank car consist"},
    "auto_rack":   {"min": 55, "max": 85,  "label": "Automotive rack train"},
    "hopper":      {"min": 40, "max": 70,  "label": "Hopper/bulk train"},
    "passenger":   {"min": 80, "max": 160, "label": "Passenger train"},
    "unknown":     {"min": 35, "max": 100, "label": "Unknown consist type"},
}

# ── SYMBOL FILTERING ──────────────────────────────────────────────────────────

# Service symbols worth correlating
# CN/VIA/CP + 1-3 digits: CN 61, VIA 1, CN 368, CP 421
SERVICE_ROAD_PATTERN = re.compile(
    r'^(CN|VIA|CP|CPKC)\s*(\d{1,3})$', re.IGNORECASE
)
# Letter-coded CN symbols: Z148, Q107, X309, A414, M394, L570
# Single letter + 3-4 digits only — excludes two-letter foreign road prefixes
# like IC (Illinois Central) and foreign loco numbers
LETTER_SYMBOL_PATTERN = re.compile(
    r'^[A-Z]\d{3,4}$', re.IGNORECASE
)

def is_service_symbol(symbol):
    """
    Return True if symbol is a train service identifier, not a loco road number.
    CN 368 → True   (service)
    Z148   → True   (service)
    CN3950 → False  (loco road number, 4 digits)
    CP7603 → False  (loco road number, 4 digits)
    IC2719 → False  (foreign loco)
    """
    s = symbol.strip().upper().replace(" ", "")
    # Road + number: strip road prefix, check digit length
    m = re.match(r'^(CN|VIA|CP|CPKC)(\d+)$', s)
    if m:
        return len(m.group(2)) <= 3  # 1-3 digits = service number
    # Letter-coded symbol
    if LETTER_SYMBOL_PATTERN.match(s):
        return True
    return False

# ── TIME PARSING ──────────────────────────────────────────────────────────────

def parse_obs_time(obs):
    """
    Extract the best available datetime from an observation.
    Priority:
      1. observed_at — precise timestamp extracted from description (e.g. 08:20 EDT)
      2. published_at — YouTube upload timestamp (has time, may be hours after filming)
      3. date — date string only, falls back to midnight
    """
    # Priority 1: precise observed timestamp from description extractor
    observed_at = obs.get("observed_at", "")
    if observed_at:
        try:
            # Handle timezone offset formats: 2026-06-15T08:20-04:00
            return datetime.datetime.fromisoformat(observed_at).replace(tzinfo=None)
        except:
            pass

    # Priority 2: YouTube published_at (ISO 8601 with Z)
    pub = obs.get("published_at", "")
    if pub:
        try:
            return datetime.datetime.fromisoformat(
                pub.replace("Z", "+00:00")
            ).replace(tzinfo=None)
        except:
            pass

    # Priority 3: date string only — midnight
    date_str = obs.get("date", "")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(date_str, fmt)
        except:
            pass

    return None

def time_precision(obs):
    """Return how precise the timestamp is: 'observed', 'published', or 'date_only'."""
    if obs.get("observed_at"):
        return "observed"
    if obs.get("published_at"):
        return "published"
    return "date_only"

# ── GEOMETRY ──────────────────────────────────────────────────────────────────

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))

# ── CONSIST ANOMALY COLLECTOR ─────────────────────────────────────────────────

def collect_anomalies(observations):
    """
    Surface all observations with consist_anomaly flags, regardless of
    whether a cross-observer or chase correlation exists for them.
    These represent confirmed or suspected consist splits, set-offs, or lifts.
    """
    anomalies = []
    for obs in observations:
        if obs.get("anomaly_flag") or obs.get("consist_anomaly"):
            anomalies.append({
                "type":            "consist_anomaly",
                "channel":         obs.get("channel"),
                "date":            obs.get("date"),
                "location":        obs.get("location"),
                "train_symbols":   obs.get("train_symbols"),
                "anomaly_note":    obs.get("consist_anomaly", ""),
                "car_count":       obs.get("consist", {}).get("car_count") if obs.get("consist") else None,
                "car_count_note":  obs.get("consist", {}).get("car_count_note") if obs.get("consist") else None,
                "origin":          obs.get("origin"),
                "destination":     obs.get("destination"),
                "video_url":       obs.get("video_url"),
                "title":           obs.get("raw_title", "")[:80],
            })
    return anomalies

# ── MAIN CORRELATE ────────────────────────────────────────────────────────────

def correlate(youtube_data_path="railwatch_youtube_latest.json",
              output_path="railwatch_correlations.json"):

    if not os.path.exists(youtube_data_path):
        print(f"  Correlate: {youtube_data_path} not found")
        return []

    with open(youtube_data_path) as f:
        data = json.load(f)

    observations = data.get("observations", [])
    print(f"  Correlating {len(observations)} observations for train symbol matches...")

    # ── FILTER TO SERVICE SYMBOLS ONLY ────────────────────────────────────────
    # Index observations by service symbol, skipping loco road numbers
    by_symbol = {}
    skipped_loco = 0
    for obs in observations:
        symbols = obs.get("train_symbols") or []
        for sym in symbols:
            raw_symbol = sym["symbol"]
            if not is_service_symbol(raw_symbol):
                skipped_loco += 1
                continue
            key = raw_symbol.upper().replace(" ", "")
            if key not in by_symbol:
                by_symbol[key] = []
            by_symbol[key].append(obs)

    print(f"  Service symbols found: {len(by_symbol)} · Loco numbers excluded: {skipped_loco}")

    tier1 = []  # cross-observer
    tier2 = []  # same-observer chase

    for symbol, sightings in by_symbol.items():
        if len(sightings) < 2:
            continue

        # Sort by best available time
        dated = [(s, parse_obs_time(s)) for s in sightings]
        dated = [(s, t) for s, t in dated if t is not None]
        dated.sort(key=lambda x: x[1])

        for i in range(len(dated) - 1):
            obs_a, time_a = dated[i]
            obs_b, time_b = dated[i + 1]

            loc_a = obs_a.get("location")
            loc_b = obs_b.get("location")
            if not loc_a or not loc_b or loc_a == loc_b:
                continue

            sta_a = STATIONS.get(loc_a)
            sta_b = STATIONS.get(loc_b)
            if not sta_a or not sta_b:
                continue

            dist_km = haversine_km(
                sta_a["lat"], sta_a["lon"],
                sta_b["lat"], sta_b["lon"]
            )
            delta_h = (time_b - time_a).total_seconds() / 3600

            if delta_h <= 0 or delta_h > 72:
                continue

            speed_kmh = dist_km / delta_h

            commodity = obs_a.get("commodity_type") or obs_b.get("commodity_type") or "unknown"
            profile = SPEED_PROFILES.get(commodity, SPEED_PROFILES["unknown"])
            speed_plausible = profile["min"] <= speed_kmh <= profile["max"]

            mile_a = sta_a.get("mile", 0)
            mile_b = sta_b.get("mile", 0)
            inferred_direction = "East" if mile_b > mile_a else "West"

            dir_a = obs_a.get("direction")
            dir_b = obs_b.get("direction")
            direction_consistent = not (dir_a and dir_b and dir_a != dir_b)

            # Consist comparison for chase sightings
            consist_a = obs_a.get("consist") or {}
            consist_b = obs_b.get("consist") or {}
            car_count_a = consist_a.get("car_count")
            car_count_b = consist_b.get("car_count")
            car_count_delta = None
            split_suspected = False
            if car_count_a and car_count_b:
                car_count_delta = abs(car_count_b - car_count_a)
                # Flag if count drops by more than 5 cars — likely a set-off
                if car_count_b < car_count_a - 5:
                    split_suspected = True

            # Use precise observed times where available
            prec_a = time_precision(obs_a)
            prec_b = time_precision(obs_b)
            time_note = None
            if prec_a == "date_only" or prec_b == "date_only":
                time_note = "date-only timestamps — elapsed time is approximate"

            same_channel = obs_a.get("channel") == obs_b.get("channel")

            corr = {
                "symbol":       symbol,
                "tier":         "chase" if same_channel else "cross_observer",
                "sighting_a": {
                    "location":       loc_a,
                    "date":           obs_a.get("date"),
                    "observed_at":    obs_a.get("observed_at"),
                    "time_precision": prec_a,
                    "channel":        obs_a.get("channel"),
                    "direction":      dir_a,
                    "car_count":      car_count_a,
                    "origin":         obs_a.get("origin"),
                    "destination":    obs_a.get("destination"),
                    "video_url":      obs_a.get("video_url"),
                    "title":          obs_a.get("raw_title", "")[:60],
                },
                "sighting_b": {
                    "location":       loc_b,
                    "date":           obs_b.get("date"),
                    "observed_at":    obs_b.get("observed_at"),
                    "time_precision": prec_b,
                    "channel":        obs_b.get("channel"),
                    "direction":      dir_b,
                    "car_count":      car_count_b,
                    "origin":         obs_b.get("origin"),
                    "destination":    obs_b.get("destination"),
                    "video_url":      obs_b.get("video_url"),
                    "title":          obs_b.get("raw_title", "")[:60],
                },
                "transit": {
                    "distance_km":          round(dist_km, 1),
                    "elapsed_hours":        round(delta_h, 2),
                    "avg_speed_kmh":        round(speed_kmh, 1),
                    "speed_plausible":      speed_plausible,
                    "consist_profile":      profile["label"],
                    "inferred_direction":   inferred_direction,
                    "direction_consistent": direction_consistent,
                    "time_note":            time_note,
                },
                "consist_delta": {
                    "car_count_a":    car_count_a,
                    "car_count_b":    car_count_b,
                    "delta":          car_count_delta,
                    "split_suspected": split_suspected,
                } if (car_count_a or car_count_b) else None,
                "commodity":     commodity,
                "dg_likely":     obs_a.get("dg_likely") or obs_b.get("dg_likely"),
                "correlated_at": datetime.datetime.utcnow().isoformat() + "Z",
            }

            # Confidence scoring
            if same_channel:
                # Chase: speed plausibility is primary signal
                corr["confidence"] = "medium" if speed_plausible else "low"
                if split_suspected:
                    corr["split_suspected"] = True
                tier2.append(corr)
                tier_label = "CHASE"
            else:
                # Cross-observer: requires speed + direction both plausible
                corr["confidence"] = "high" if (speed_plausible and direction_consistent) else "medium"
                tier1.append(corr)
                tier_label = "CROSS "

            print(f"  {tier_label}: {symbol} · {loc_a} → {loc_b} · "
                  f"{dist_km:.0f}km in {delta_h:.1f}h · {speed_kmh:.0f}km/h · "
                  f"{'✓' if speed_plausible else '?'} speed"
                  f"{' ⚠ SPLIT?' if split_suspected else ''}")

    # ── TIER 3: CONSIST ANOMALIES ─────────────────────────────────────────────
    anomalies = collect_anomalies(observations)
    if anomalies:
        print(f"  Anomalies flagged: {len(anomalies)} (set-off / lift / split notes)")

    all_correlations = tier1 + tier2

    payload = {
        "generated_at":       datetime.datetime.utcnow().isoformat() + "Z",
        "total":              len(all_correlations),
        "cross_observer":     len(tier1),
        "chase":              len(tier2),
        "high":               sum(1 for c in all_correlations if c["confidence"] == "high"),
        "medium":             sum(1 for c in all_correlations if c["confidence"] == "medium"),
        "dg_correlations":    sum(1 for c in all_correlations if c["dg_likely"]),
        "splits_suspected":   sum(1 for c in all_correlations if c.get("split_suspected")),
        "anomalies":          anomalies,
        "correlations":       sorted(
            all_correlations,
            key=lambda x: (
                x["tier"] == "cross_observer",       # cross-observer first
                x["confidence"] == "high",            # high confidence first
                x.get("split_suspected", False),      # splits surfaced early
            ),
            reverse=True,
        ),
    }

    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"  Correlations: {len(tier1)} cross-observer · {len(tier2)} chase · "
          f"{payload['high']} high · {payload['dg_correlations']} DG-likely · "
          f"{payload['splits_suspected']} splits suspected")
    return all_correlations

if __name__ == "__main__":
    correlate()
