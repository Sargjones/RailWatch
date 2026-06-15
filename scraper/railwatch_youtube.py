"""
railwatch_youtube.py — RailWatch YouTube railfan channel scraper
Part of the Critical TO infrastructure intelligence family (criticalto.ca)

Improvements v2:
  1. Channel default locations — applied when title/description extraction fails
  2. Subdivision name pattern matching — "Dundas Sub", "Oakville Sub" etc in text
  3. Full description fetching — details API returns complete description text
  4. Vision analysis — Claude reads thumbnails for reporting marks, placards, location

Author: Sarah Jones / Critical TO
"""

import os
import re
import json
import base64
import datetime
import requests
from railwatch_dedup import load_seen, save_seen, filter_new, mark_seen, stats as dedup_stats

# ─── CONFIG ───────────────────────────────────────────────────────────────────

YOUTUBE_API_KEY   = os.environ.get("YOUTUBE_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ENABLE_VISION     = os.environ.get("ENABLE_VISION", "false").lower() == "true"

# ── CHANNEL REGISTRY ──────────────────────────────────────────────────────────
# default_location: applied when extraction finds nothing in title/description
# default_subdivision: same
# province_filter: if True, flag videos with no Ontario location hit as out-of-province

CHANNELS = [
    {
        "id":               "UCLZtQIlW2g6tOFh5EBkypdw",
        "name":             "Trackside Ontario",
        "handle":           "@TracksideOntario",
        "focus":            ["Bayview Junction", "CN Dundas Sub", "CN Oakville Sub"],
        "default_location": "Bayview Junction",
        "default_subdivision": "CN Oakville/Dundas Sub",
        "default_lat":      43.2870,
        "default_lon":      -79.7760,
        "province_filter":  True,   # almost always Ontario
        "active":           True,
    },
    {
        "id":               "UC_uOfTPvNmHJdUNKeaoZ-aA",
        "name":             "Trackside Tyson",
        "handle":           "@tracksidetyson",
        "focus":            ["CN", "CPKC", "Ontario", "cross-Canada"],
        "default_location": None,   # ranges nationally — no single default
        "default_subdivision": None,
        "province_filter":  False,  # cross-Canada content expected
        "active":           True,
    },
    {
        "id":               "UCojaEJ7WwqMvtlQlQdalEAA",
        "name":             "Southern Ontario Railfan",
        "handle":           "@SouthernOntarioRailfan2026",
        "focus":            ["CN Dundas Sub", "CN Chatham Sub", "CPKC Windsor Sub"],
        "default_location": "CN Dundas Sub",
        "default_subdivision": "CN Dundas Sub",
        "default_lat":      43.1000,
        "default_lon":      -80.5000,
        "province_filter":  True,
        "active":           True,
    },
    {
        "id":               "UCTqv9O8m0vdSlGIXSHUKQbQ",
        "name":             "Trackside Toronto",
        "handle":           "@tracksidetoronto",
        "focus":            ["VIA Rail", "GO Transit", "CN", "Toronto"],
        "default_location": "Toronto",
        "default_subdivision": "CN Kingston/Oakville Sub",
        "default_lat":      43.6450,
        "default_lon":      -79.3800,
        "province_filter":  True,
        "active":           False,
    },
    {
        "id":               "UCJzmiVZMfXiOm8dKP_Ntj7w",
        "name":             "Trackside Tristan",
        "handle":           "@TracksideTristan",
        "focus":            ["CPKC MacTier Sub", "CN Ontario", "intermodal"],
        "default_location": "MacTier",
        "default_subdivision": "CPKC MacTier Sub",
        "default_lat":      44.9500,
        "default_lon":      -79.7300,
        "province_filter":  True,
        "active":           True,
    },
    {
        "id":               "UCWK8y_tzwbtVknVsPSKremw",
        "name":             "Track Side Mike",
        "handle":           "@TrackSideMike",
        "focus":            ["CN Smiths Falls Sub", "CN Kingston Sub"],
        "default_location": "Smiths Falls",
        "default_subdivision": "CN Smiths Falls Sub",
        "default_lat":      44.8990,
        "default_lon":      -76.0220,
        "province_filter":  True,
        "active":           True,
    },
    # ── PENDING CHANNEL IDs — verify and set active: True ──────────────────
    {
        "id":               "UCQUUHzkvfoCqcTKIn6cI9yw",  # Scott's Rails / Chasing The Money Shot (verified 2026-06-15)
        "name":             "Scott Rails (Chasing The Money Shot)",
        "handle":           "@ScottRails",
        "focus":            ["Bayview Junction", "CN Oakville Sub", "CN Dundas Sub"],
        "default_location": "Bayview Junction",
        "default_subdivision": "CN Oakville/Dundas Sub",
        "default_lat":      43.2870,
        "default_lon":      -79.7760,
        "province_filter":  True,
        "active":           True,
    },
    {
        "id":               "UCJzzfzG95FxDCgeUO26FvCw",  # Rail Fans Canada (verified 2026-06-15)
        "name":             "Rail Fans Canada",
        "handle":           "@RailFansCanada",
        "focus":            ["Ottawa O-Train", "GO Transit", "Ontario transit"],
        "default_location": "Ottawa",
        "default_subdivision": "CN Smiths Falls Sub",
        "default_lat":      45.4230,
        "default_lon":      -75.6950,
        "province_filter":  True,
        "active":           True,
    },
    {
        "id":               "UCdBR6gWk5pSjXxoG7EoNMEA",  # Brockville RailFan (verified 2026-06-15)
        "name":             "Brockville RailFan",
        "handle":           "@BrockvilleRailFan",
        "focus":            ["CN Kingston Sub", "VIA Rail", "Brockville"],
        "default_location": "Brockville",
        "default_subdivision": "CN Kingston Sub",
        "default_lat":      44.5800,
        "default_lon":      -75.7000,
        "province_filter":  True,
        "active":           True,
    },
    {
        "id":               "",   # ← Ontario Northland Railfan — find ID
        "name":             "Ontario.Northland.Railfan",
        "handle":           "@OntarioNorthlandRailfan",
        "focus":            ["Ontario Northland Railway", "Kirkland Lake", "Northern ON"],
        "default_location": "Kirkland Lake",
        "default_subdivision": "Ontario Northland Railway",
        "default_lat":      48.1500,
        "default_lon":      -80.0400,
        "province_filter":  True,
        "active":           False,
    },
    {
        "id":               "UC-mYzr9LGSK7paIDZ2yWcUQ",  # Planes Trains Boats Online (verified 2026-06-15)
        "name":             "PTBO Railfanning",
        "handle":           "@PlanesTrainsBoatsOnline",
        "focus":            ["CN Chatham Sub", "Sarnia", "CPKC Windsor Sub", "Great Lakes shipping"],
        "default_location": "Sarnia",
        "default_subdivision": "CN Chatham Sub",
        "default_lat":      42.9744,
        "default_lon":      -82.4058,
        "province_filter":  True,
        "active":           True,
    },
    {
        "id":               "UCO2SFDeaIvjPycVTLQNvinw",  # MJM Productions (verified 2026-06-15)
        "name":             "MJM Productions",
        "handle":           "@MJMProductions",
        "focus":            ["CN Kingston Sub", "Toronto east end", "Cedarbrae"],
        "default_location": "Toronto",
        "default_subdivision": "CN Kingston Sub",
        "default_lat":      43.7500,
        "default_lon":      -79.2500,
        "province_filter":  True,
        "active":           True,
    },
    {
        "id":               "",   # ← Ontario Railfan (Oliver) — find ID
        "name":             "Ontario Railfan",
        "handle":           "@OntarioRailfan",
        "focus":            ["Southern Ontario", "CN", "CPKC"],
        "default_location": None,
        "default_subdivision": None,
        "province_filter":  True,
        "active":           False,
    },
    {
        "id":               "",   # ← Chris Wilson Sudbury — find ID
        "name":             "Chris Wilson Sudbury Trains",
        "handle":           "@ChrisWilsonSudbury",
        "focus":            ["CN Bala Sub", "Sudbury", "Northern Ontario"],
        "default_location": "Sudbury",
        "default_subdivision": "CN Bala Sub",
        "default_lat":      46.4900,
        "default_lon":      -80.9900,
        "province_filter":  True,
        "active":           False,
    },
]

# ── LOCATION KEYWORDS ─────────────────────────────────────────────────────────

LOCATION_KEYWORDS = {
    # Junctions and yards — most specific, check first
    "Bayview Junction":    {"subdivision": "CN Oakville/Dundas Sub", "lat": 43.2870, "lon": -79.7760},
    "Bayview":             {"subdivision": "CN Oakville/Dundas Sub", "lat": 43.2870, "lon": -79.7760},
    "MacMillan Yard":      {"subdivision": "CN Bala Sub",            "lat": 43.7800, "lon": -79.5300},
    "Aldershot":           {"subdivision": "CN Oakville Sub",        "lat": 43.3050, "lon": -79.7500},
    "Silver Creek":        {"subdivision": "CN Smiths Falls Sub",    "lat": 44.7500, "lon": -76.2500},
    "Sharbot Lake":        {"subdivision": "CN Smiths Falls Sub",    "lat": 44.7700, "lon": -76.6900},
    "Smiths Falls":        {"subdivision": "CN Smiths Falls Sub",    "lat": 44.8990, "lon": -76.0220},
    # Cities
    "Hamilton":            {"subdivision": "CN Dundas Sub",          "lat": 43.2700, "lon": -79.8100},
    "Burlington":          {"subdivision": "CN Oakville Sub",        "lat": 43.3200, "lon": -79.8000},
    "Oakville":            {"subdivision": "CN Oakville Sub",        "lat": 43.4472, "lon": -79.6877},
    "Mississauga":         {"subdivision": "CN Oakville Sub",        "lat": 43.5890, "lon": -79.6441},
    "Brampton":            {"subdivision": "CN Halton Sub",          "lat": 43.6833, "lon": -79.7667},
    "Georgetown":          {"subdivision": "CN Halton Sub",          "lat": 43.6529, "lon": -79.9170},
    "Toronto":             {"subdivision": "CN Kingston/Oakville Sub","lat": 43.6450, "lon": -79.3800},
    "Pickering":           {"subdivision": "CN Kingston Sub",        "lat": 43.8354, "lon": -79.0893},
    "Ajax":                {"subdivision": "CN Kingston Sub",        "lat": 43.8509, "lon": -79.0205},
    "Whitby":              {"subdivision": "CN Kingston Sub",        "lat": 43.8975, "lon": -78.9429},
    "Oshawa":              {"subdivision": "CN Kingston Sub",        "lat": 43.8971, "lon": -78.8658},
    "Cobourg":             {"subdivision": "CN Kingston Sub",        "lat": 43.9600, "lon": -78.1700},
    "Port Hope":           {"subdivision": "CN Kingston Sub",        "lat": 43.9500, "lon": -78.2900},
    "Trenton":             {"subdivision": "CN Kingston Sub",        "lat": 44.1000, "lon": -77.5800},
    "Belleville":          {"subdivision": "CN Kingston Sub",        "lat": 44.1600, "lon": -77.3800},
    "Napanee":             {"subdivision": "CN Kingston Sub",        "lat": 44.2500, "lon": -76.9500},
    "Kingston":            {"subdivision": "CN Kingston Sub",        "lat": 44.2300, "lon": -76.4800},
    "Gananoque":           {"subdivision": "CN Kingston Sub",        "lat": 44.3300, "lon": -76.1600},
    "Brockville":          {"subdivision": "CN Kingston Sub",        "lat": 44.5800, "lon": -75.7000},
    "Prescott":            {"subdivision": "CN Kingston Sub",        "lat": 44.7100, "lon": -75.5200},
    "Ottawa":              {"subdivision": "CN Smiths Falls Sub",    "lat": 45.4230, "lon": -75.6950},
    "Guelph":              {"subdivision": "CPKC Galt Sub",          "lat": 43.5448, "lon": -80.2482},
    "Kitchener":           {"subdivision": "CPKC Galt Sub",          "lat": 43.4516, "lon": -80.4925},
    "Stratford":           {"subdivision": "CN Goderich Sub",        "lat": 43.3700, "lon": -80.9820},
    "Woodstock":           {"subdivision": "CN Dundas Sub",          "lat": 43.1300, "lon": -80.7500},
    "Ingersoll":           {"subdivision": "CN Dundas Sub",          "lat": 43.0376, "lon": -80.8837},
    "London":              {"subdivision": "CN Dundas Sub",          "lat": 43.0080, "lon": -80.9960},
    "St. Thomas":          {"subdivision": "CN Dundas Sub",          "lat": 42.7751, "lon": -81.1990},
    "Chatham":             {"subdivision": "CN Chatham Sub",         "lat": 42.4900, "lon": -82.1900},
    "Sarnia":              {"subdivision": "CN Chatham Sub",         "lat": 42.9744, "lon": -82.4058},
    "Windsor":             {"subdivision": "CN Dundas Sub",          "lat": 42.3149, "lon": -83.0364},
    "Barrie":              {"subdivision": "CN Bala Sub",            "lat": 44.3900, "lon": -79.6800},
    "Sudbury":             {"subdivision": "CN Bala Sub",            "lat": 46.4900, "lon": -80.9900},
    "Parry Sound":         {"subdivision": "CN Bala Sub",            "lat": 45.3500, "lon": -80.0400},
    "MacTier":             {"subdivision": "CPKC MacTier Sub",        "lat": 44.9500, "lon": -79.7300},
    "Washago":             {"subdivision": "CN Bala Sub",             "lat": 44.7500, "lon": -79.3300},
    "Gravenhurst":         {"subdivision": "CN Bala Sub",             "lat": 44.9200, "lon": -79.3700},
    "Huntsville":          {"subdivision": "CN Bala Sub",             "lat": 45.3300, "lon": -79.2200},
    "Capreol":             {"subdivision": "CN Bala Sub",             "lat": 46.7100, "lon": -80.9300},
    "Schreiber":           {"subdivision": "CN Ruel Sub",             "lat": 48.8100, "lon": -87.2700},
    "White River":         {"subdivision": "CN Ruel Sub",             "lat": 48.5900, "lon": -85.2800},
    "Cartier":             {"subdivision": "CN Ruel Sub",             "lat": 46.6900, "lon": -81.5600},
}

# ── SUBDIVISION NAME PATTERNS (Priority 2) ────────────────────────────────────
# Matches "Dundas Sub", "Oakville Sub", "CN Dundas" etc in titles/descriptions

SUBDIVISION_PATTERNS = [
    (r'\b(dundas\s+sub(?:division)?)\b',        {"subdivision": "CN Dundas Sub",          "name": "CN Dundas Sub",          "lat": 43.1000, "lon": -80.5000}),
    (r'\b(oakville\s+sub(?:division)?)\b',       {"subdivision": "CN Oakville Sub",        "name": "CN Oakville Sub",        "lat": 43.3500, "lon": -79.6500}),
    (r'\b(kingston\s+sub(?:division)?)\b',       {"subdivision": "CN Kingston Sub",        "name": "CN Kingston Sub",        "lat": 44.0000, "lon": -77.5000}),
    (r'\b(smiths?\s+falls?\s+sub(?:division)?)\b',{"subdivision": "CN Smiths Falls Sub",  "name": "CN Smiths Falls Sub",    "lat": 44.8990, "lon": -76.0220}),
    (r'\b(halton\s+sub(?:division)?)\b',         {"subdivision": "CN Halton Sub",          "name": "CN Halton Sub",          "lat": 43.6000, "lon": -79.8000}),
    (r'\b(bala\s+sub(?:division)?)\b',           {"subdivision": "CN Bala Sub",            "name": "CN Bala Sub",            "lat": 44.5000, "lon": -79.8000}),
    (r'\b(chatham\s+sub(?:division)?)\b',        {"subdivision": "CN Chatham Sub",         "name": "CN Chatham Sub",         "lat": 42.7000, "lon": -82.3000}),
    (r'\b(galt\s+sub(?:division)?)\b',           {"subdivision": "CPKC Galt Sub",          "name": "CPKC Galt Sub",          "lat": 43.4000, "lon": -80.5000}),
    (r'\b(grimsby\s+sub(?:division)?)\b',        {"subdivision": "CN Grimsby Sub",         "name": "CN Grimsby Sub",         "lat": 43.2000, "lon": -79.5000}),
    (r'\b(southend\s+sub(?:division)?)\b',       {"subdivision": "CN Smiths Falls Sub",    "name": "Southend Sub",           "lat": 44.8000, "lon": -76.1000}),
    (r'\b(strathroy\s+sub(?:division)?)\b',      {"subdivision": "CN Strathroy Sub",       "name": "CN Strathroy Sub",       "lat": 42.9600, "lon": -81.6200}),
    (r'\b(goderich\s+sub(?:division)?)\b',       {"subdivision": "CN Goderich Sub",        "name": "CN Goderich Sub",        "lat": 43.5000, "lon": -81.0000}),
    (r'\b(newmarket\s+sub(?:division)?)\b',      {"subdivision": "CN Newmarket Sub",       "name": "CN Newmarket Sub",       "lat": 44.0500, "lon": -79.4600}),
    (r'@?silvercreeksub\b',               {"subdivision": "CN Smiths Falls Sub",    "name": "Silver Creek Sub",       "lat": 44.7500, "lon": -76.2500}),
    (r'\b(silver\s+creek\s+sub(?:division)?)\b', {"subdivision": "CN Smiths Falls Sub", "name": "Silver Creek Sub",       "lat": 44.7500, "lon": -76.2500}),
    (r'\b(mactier\s+sub(?:division)?)\b',         {"subdivision": "CPKC MacTier Sub",       "name": "CPKC MacTier Sub",       "lat": 44.9500, "lon": -79.7300}),
    (r'\b(parry\s+sound\s+sub(?:division)?)\b',  {"subdivision": "CN Bala Sub",            "name": "CN Bala Sub (Parry Sound)","lat": 45.3500, "lon": -80.0400}),
    (r'\b(ruel\s+sub(?:division)?)\b',            {"subdivision": "CN Ruel Sub",            "name": "CN Ruel Sub",            "lat": 48.0000, "lon": -85.0000}),
    (r'\b(superior\s+sub(?:division)?)\b',        {"subdivision": "CN Superior Sub",        "name": "CN Superior Sub",        "lat": 48.5000, "lon": -87.0000}),
]

# ── COMMODITY KEYWORDS ────────────────────────────────────────────────────────

COMMODITY_KEYWORDS = {
    "tank car":     {"type": "tank",          "dg_likely": True},
    "tank cars":    {"type": "tank",          "dg_likely": True},
    "tanker":       {"type": "tank",          "dg_likely": True},
    "loaded":       {"type": "unknown",       "dg_likely": True},
    "chemical":     {"type": "tank",          "dg_likely": True},
    "crude":        {"type": "tank",          "dg_likely": True,  "un": "1267"},
    "propane":      {"type": "pressure_tank", "dg_likely": True,  "un": "1978"},
    "ethanol":      {"type": "tank",          "dg_likely": True,  "un": "1170"},
    "acid":         {"type": "tank",          "dg_likely": True},
    "chlorine":     {"type": "pressure_tank", "dg_likely": True,  "un": "1017"},
    "ammonia":      {"type": "pressure_tank", "dg_likely": True,  "un": "1005"},
    "sulphur":      {"type": "gondola",       "dg_likely": True,  "un": "2448"},
    "sulfur":       {"type": "gondola",       "dg_likely": True,  "un": "2448"},
    "potash":       {"type": "hopper",        "dg_likely": False},
    "grain":        {"type": "hopper",        "dg_likely": False},
    "hopper":       {"type": "hopper",        "dg_likely": False},
    "coal":         {"type": "gondola",       "dg_likely": False},
    "intermodal":   {"type": "intermodal",    "dg_likely": False},
    "container":    {"type": "intermodal",    "dg_likely": False},
    "manifest":     {"type": "mixed",         "dg_likely": True},
    "mixed freight":{"type": "mixed",         "dg_likely": True},
    "auto rack":    {"type": "auto_rack",     "dg_likely": False},
    "autorack":     {"type": "auto_rack",     "dg_likely": False},
    "lumber":       {"type": "flatcar",       "dg_likely": False},
    "potash":       {"type": "hopper",        "dg_likely": False},
    "unit train":   {"type": "unit",          "dg_likely": True},
}

OUT_OF_SCOPE_KEYWORDS = [
    "british columbia", " bc ", "thompson canyon", "alberta", "saskatchewan",
    "manitoba", "nova scotia", "new brunswick", "fraser", "rockies",
    "tunnel mountain", "rogers pass", "spiral tunnel", "field bc",
    "kamloops", "revelstoke", "jasper", "banff", "calgary", "edmonton",
    "vancouver", "surrey", "winnipeg", "regina", "saskatoon",
]

DIRECTION_PATTERNS = [
    (r'\b(eastbound|east[\s-]?bound|heading east|moving east|\bEB\b)\b', 'East'),
    (r'\b(westbound|west[\s-]?bound|heading west|moving west|\bWB\b)\b', 'West'),
    (r'\b(northbound|north[\s-]?bound|\bNB\b)\b', 'North'),
    (r'\b(southbound|south[\s-]?bound|\bSB\b)\b', 'South'),
]

DATE_PATTERNS = [
    r'(\d{4}[-/]\d{2}[-/]\d{2})',
    r'(\w+ \d{1,2},?\s*\d{4})',
    r'(\d{1,2}[-/]\d{1,2}[-/]\d{4})',
    r'(\w+ \d{4})',
]

LOCO_PATTERN = re.compile(r'\b(CN|CP|CPKC|VIA)\s*(\d{3,5})\b', re.IGNORECASE)
UN_PATTERN   = re.compile(r'\bUN\s*[#-]?(\d{4})\b', re.IGNORECASE)

# Train symbol patterns — e.g. "CN Train 368", "VIA 61", "Q10831", "A41451 18"
# CN symbols: letter(s) + digits, e.g. Q108, A414, M394, L522, X500
# VIA symbols: train number only, e.g. VIA 61, VIA 1
TRAIN_SYMBOL_PATTERN = re.compile(
    r'\b(?:'
    r'(?:CN|CP|CPKC|VIA)\s+(?:Train\s+)?(\d{2,4})'   # CN/VIA + number: "CN Train 368", "VIA 61"
    r'|\b([A-Z]{1,2}\d{3,5}(?:\s+\d{2})?)\b'         # Symbol format: Q108, A41451, M39431 18
    r')', re.IGNORECASE
)

# ─── YOUTUBE API ──────────────────────────────────────────────────────────────

YT_BASE = "https://www.googleapis.com/youtube/v3"

def yt_get(endpoint, params):
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY not set")
    params["key"] = YOUTUBE_API_KEY
    r = requests.get(f"{YT_BASE}/{endpoint}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def fetch_channel_videos(channel_id, max_results=50, published_after=None):
    """Search API — returns video IDs and basic snippet. Descriptions are truncated here."""
    params = {
        "part":       "snippet",
        "channelId":  channel_id,
        "maxResults": min(max_results, 50),
        "order":      "date",
        "type":       "video",
    }
    if published_after:
        params["publishedAfter"] = published_after
    try:
        data = yt_get("search", params)
        return data.get("items", [])
    except Exception as e:
        print(f"  YouTube API error for channel {channel_id}: {e}")
        return []

def fetch_video_details(video_ids):
    """
    Videos API — returns FULL descriptions, tags, and content details.
    This is the key fix for Priority 3: descriptions from the search API
    are truncated to ~150 chars. The videos endpoint returns the complete text.
    """
    if not video_ids:
        return {}
    params = {
        "part": "snippet,contentDetails,statistics",
        "id":   ",".join(video_ids[:50]),
    }
    try:
        data = yt_get("videos", params)
        return {item["id"]: item for item in data.get("items", [])}
    except Exception as e:
        print(f"  YouTube video details error: {e}")
        return {}

# ─── EXTRACTION ───────────────────────────────────────────────────────────────

def extract_date(text):
    for pattern in DATE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%B %d, %Y", "%B %d %Y",
                        "%b %d, %Y", "%b %d %Y", "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    return datetime.datetime.strptime(raw, fmt).date().isoformat()
                except:
                    continue
            return raw
    return None

def extract_location(text):
    """
    Priority 1: exact city/place name match
    Priority 2: subdivision pattern match (e.g. 'Dundas Sub', 'Southend Sub')
    """
    text_lower = text.lower()

    # Priority 1 — named places
    for keyword, meta in LOCATION_KEYWORDS.items():
        if keyword.lower() in text_lower:
            return {"name": keyword, **meta}

    # Priority 2 — subdivision name patterns
    for pattern, meta in SUBDIVISION_PATTERNS:
        if re.search(pattern, text_lower):
            return meta

    return None

def extract_direction(text):
    for pattern, direction in DIRECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return direction
    return None

def extract_commodity(text):
    text_lower = text.lower()
    hits = []
    for keyword, meta in COMMODITY_KEYWORDS.items():
        if keyword in text_lower:
            hits.append({**meta, "keyword": keyword})
    if not hits:
        return None
    dg_hits = [h for h in hits if h["dg_likely"]]
    return dg_hits[0] if dg_hits else hits[0]

def extract_locos(text):
    locos = []
    for m in LOCO_PATTERN.finditer(text):
        locos.append(f"{m.group(1).upper()} {m.group(2)}")
    return list(dict.fromkeys(locos)) or None  # deduplicate, preserve order

def extract_un(text):
    m = UN_PATTERN.search(text)
    return m.group(1) if m else None

def extract_train_symbols(text):
    """
    Extract train symbols and numbers from title/description.
    Returns list of dicts: {road, number, symbol, raw}
    e.g. "CN Train 368 Eastbound" → [{road:'CN', number:'368', symbol:'CN 368'}]
    """
    results = []
    seen = set()
    for m in TRAIN_SYMBOL_PATTERN.finditer(text):
        raw = m.group(0).strip()
        # Determine road from context
        ctx = text[max(0,m.start()-10):m.start()].upper()
        if m.group(1):  # CN/VIA + number format
            number = m.group(1)
            if 'VIA' in ctx:
                road, symbol = 'VIA', f'VIA {number}'
            elif 'CPKC' in ctx or 'CP' in ctx:
                road, symbol = 'CPKC', f'CP {number}'
            else:
                road, symbol = 'CN', f'CN {number}'
        else:           # Symbol format (Q108, A414 etc)
            raw_sym = m.group(2).strip()
            road, symbol = 'CN', raw_sym.upper()  # CN uses letter-based symbols
        key = symbol.upper().replace(' ','')
        if key not in seen and len(key) >= 4:
            seen.add(key)
            results.append({'road': road, 'symbol': symbol, 'raw': raw})
    return results or None

def apply_channel_defaults(obs, channel_meta):
    """
    Priority 1 improvement: if extraction found nothing, apply channel-level defaults.
    Trackside Ontario is almost always at Bayview Junction.
    Track Side Mike is almost always on CN Smiths Falls Sub.
    Mark these as 'default' so the dashboard can display them differently if needed.
    """
    if not obs["location"] and channel_meta.get("default_location"):
        obs["location"]          = channel_meta["default_location"]
        obs["subdivision"]       = channel_meta.get("default_subdivision")
        obs["lat"]               = channel_meta.get("default_lat")
        obs["lon"]               = channel_meta.get("default_lon")
        obs["location_source"]   = "channel_default"
    else:
        obs["location_source"]   = "extracted" if obs["location"] else "none"
    return obs

def parse_video(item, detail, channel_meta):
    """
    Convert a YouTube video item into a RailWatch observation record.
    Uses full description from details API (not truncated search snippet).
    """
    # Use detail snippet if available — it has the FULL description
    snippet     = detail.get("snippet", item.get("snippet", {}))
    vid_id      = detail.get("id") or item.get("id", {}).get("videoId", "")

    title       = snippet.get("title", "")
    description = snippet.get("description", "")  # FULL text from details API
    tags        = snippet.get("tags", [])
    published   = snippet.get("publishedAt", "")

    # Combine all text sources for extraction
    full_text = f"{title}\n{description}\n{' '.join(tags)}"

    # Run extractors against full combined text
    obs_date  = extract_date(title) or extract_date(description) or published[:10]
    location  = extract_location(full_text)
    direction = extract_direction(full_text)
    commodity = extract_commodity(full_text)
    locos        = extract_locos(full_text)
    un_number    = extract_un(full_text)
    train_syms   = extract_train_symbols(full_text)

    # Geographic scope
    text_lower = full_text.lower()
    out_of_scope = any(kw in text_lower for kw in OUT_OF_SCOPE_KEYWORDS)
    geographic_scope = "out-of-province" if (out_of_scope and not location) else "ontario"

    # Confidence scoring — location now counts even if from subdivision pattern
    score = sum([bool(obs_date), bool(location), bool(commodity)])
    confidence = "high" if score == 3 else "medium" if score == 2 else "low" if score == 1 else "meta"

    obs = {
        "source":           "youtube",
        "geographic_scope": geographic_scope,
        "channel":          channel_meta["name"],
        "channel_id":       channel_meta["id"],
        "video_id":         vid_id,
        "video_url":        f"https://www.youtube.com/watch?v={vid_id}",
        "title":            title,
        "published_at":     published,
        "date":             obs_date,
        "location":         location["name"] if location else None,
        "subdivision":      location["subdivision"] if location else None,
        "lat":              location.get("lat") if location else None,
        "lon":              location.get("lon") if location else None,
        "direction":        direction,
        "commodity_type":   commodity["type"] if commodity else None,
        "dg_likely":        commodity["dg_likely"] if commodity else False,
        "un_number":        un_number,
        "locomotives":      locos,
        "train_symbols":    train_syms,
        "confidence":       confidence,
        "raw_title":        title,
        "description_chars": len(description),  # diagnostic: confirms full desc received
    }

    # If train symbol found with location, upgrade confidence
    if train_syms and obs.get('location'):
        obs['dg_candidate'] = True  # flag for future consist correlation

    # Apply channel defaults if extraction found no location
    obs = apply_channel_defaults(obs, channel_meta)

    # Re-score confidence after defaults applied
    score = sum([bool(obs["date"]), bool(obs["location"]), bool(obs["commodity_type"])])
    obs["confidence"] = "high" if score == 3 else "medium" if score == 2 else "low" if score == 1 else "meta"

    return obs

# ─── VISION ───────────────────────────────────────────────────────────────────

def analyse_thumbnail(video_id, title, description=""):
    """
    Priority 4: Download thumbnail and run Claude vision.
    Extracts reporting marks, placard classes, UN numbers, location clues.
    Only called when ENABLE_VISION=true and ANTHROPIC_API_KEY is set.
    """
    if not ANTHROPIC_API_KEY or not ENABLE_VISION:
        return None

    # Try maxres first, fall back to hq
    for quality in ("maxresdefault", "hqdefault"):
        thumb_url = f"https://img.youtube.com/vi/{video_id}/{quality}.jpg"
        try:
            img_resp = requests.get(thumb_url, timeout=15)
            img_resp.raise_for_status()
            # Skip placeholder thumbnails (very small)
            if len(img_resp.content) < 5000:
                continue
            img_b64 = base64.b64encode(img_resp.content).decode()
            break
        except:
            continue
    else:
        return None

    context = f'Title: "{title}"'
    if description:
        context += f'\nDescription preview: "{description[:300]}"'

    prompt = f"""You are analyzing a thumbnail from a Canadian railfan YouTube video.
{context}

Extract ONLY what is clearly visible. Do not guess. Return ONLY a JSON object:
{{
  "reporting_marks": ["AITX 38342", "CN 3145"],
  "placard_classes": ["8", "3"],
  "un_numbers": ["1791"],
  "direction": "East",
  "location_clue": "Bayview Junction RBG footbridge visible",
  "car_types": ["tank car", "covered hopper"],
  "confidence": "high",
  "notes": "any other relevant observations"
}}

Rules:
- reporting_marks: only if alphanumeric text on car side is readable
- placard_classes: only if diamond placard number is visible (1-9)
- un_numbers: only if orange UN panel with 4 digits is visible
- direction: only if train movement direction is clear from image context
- confidence: "high" if 2+ fields found, "medium" if 1, "low" if none, "none" if no rail content
- If no useful rail content visible, return {{"confidence": "none"}}
"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-sonnet-4-6",
                "max_tokens": 400,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64",
                         "media_type": "image/jpeg", "data": img_b64}},
                        {"type": "text", "text": prompt},
                    ]
                }]
            },
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"].strip()
        raw = re.sub(r'^```json\s*|```\s*$', '', raw).strip()
        return json.loads(raw)
    except Exception as e:
        print(f"    Vision error for {video_id}: {e}")
        return None

def merge_vision(obs, vision):
    """Merge vision results into observation, upgrading confidence where warranted."""
    if not vision or vision.get("confidence") == "none":
        return obs
    obs["vision"] = vision
    if vision.get("un_numbers") and not obs["un_number"]:
        obs["un_number"] = vision["un_numbers"][0]
    if vision.get("placard_classes"):
        obs["placard_classes_vision"] = vision["placard_classes"]
        obs["dg_likely"] = True
    if vision.get("reporting_marks"):
        obs["reporting_marks_vision"] = vision["reporting_marks"]
    if vision.get("direction") and not obs["direction"]:
        obs["direction"] = vision["direction"]
    if vision.get("location_clue") and not obs["location"]:
        obs["location"] = vision["location_clue"]
        obs["location_source"] = "vision"
    # Upgrade confidence if vision found hard data
    if vision.get("reporting_marks") or vision.get("placard_classes") or vision.get("un_numbers"):
        if obs["confidence"] in ("low", "meta"):
            obs["confidence"] = "medium"
        elif obs["confidence"] == "medium":
            obs["confidence"] = "high"
    return obs

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def run(days_back=7, output_file="railwatch_youtube_latest.json"):
    if not YOUTUBE_API_KEY:
        print("  YouTube: YOUTUBE_API_KEY not set — skipping")
        return {"status": "skipped", "reason": "no API key", "observations": []}

    since = (datetime.datetime.utcnow() - datetime.timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00Z")
    all_observations = []
    channel_summaries = []

    active_channels = [c for c in CHANNELS if c["active"] and c["id"]]
    if not active_channels:
        print("  YouTube: no active channels with confirmed IDs")
        return {"status": "no_channels", "observations": []}

    # When days_back >= 30, treat as a full re-scrape:
    # clear the dedup registry so every video in the window is reprocessed
    # and wipe the output file so we rebuild from scratch cleanly.
    if days_back >= 30:
        print(f"  Full re-scrape mode (days_back={days_back}): clearing dedup registry and output file")
        save_seen({})
        if os.path.exists(output_file):
            os.remove(output_file)

    # Load dedup registry — skip already-processed videos
    seen = load_seen()
    print(f"  Dedup registry: {len(seen)} videos already processed")

    for channel in active_channels:
        print(f"  Fetching {channel['name']} ({channel['id']})...")
        # Look back further to catch any missed videos — dedup prevents reprocessing
        items = fetch_channel_videos(channel["id"], max_results=50, published_after=since)
        if not items:
            print(f"    No videos in last {days_back} days")
            channel_summaries.append({"channel": channel["name"], "videos": 0, "skipped": 0})
            continue

        # Filter out already-seen videos — only process new ones
        new_items, skipped = filter_new(items, seen)
        print(f"    {len(new_items)} new, {skipped} already processed")

        if not new_items:
            channel_summaries.append({
                "channel": channel["name"], "videos": 0, "skipped": skipped
            })
            continue

        # Fetch FULL details for new videos only
        video_ids = [i.get("id", {}).get("videoId") for i in new_items if i.get("id", {}).get("videoId")]
        details   = fetch_video_details(video_ids)

        channel_obs = []
        for item in new_items:
            vid_id = item.get("id", {}).get("videoId")
            if not vid_id:
                continue

            detail = details.get(vid_id, item)
            obs    = parse_video(item, detail, channel)

            # Vision enhancement — only on new videos (dedup ensures this runs once per video)
            if ENABLE_VISION:
                desc_preview = detail.get("snippet", {}).get("description", "")[:300]
                vision = analyse_thumbnail(vid_id, obs["raw_title"], desc_preview)
                obs = merge_vision(obs, vision)

            # Mark as processed in dedup registry
            seen = mark_seen(vid_id, channel["name"], obs["raw_title"],
                           obs["confidence"], seen)

            channel_obs.append(obs)

            loc_src  = obs.get("location_source", "")
            loc_tag  = f" [{loc_src}]" if loc_src != "extracted" else ""
            desc_len = obs.get("description_chars", 0)
            syms     = obs.get("train_symbols")
            sym_tag  = f" · {syms[0]['symbol']}" if syms else ""
            print(f"    [{obs['confidence']:6}] {obs['date']} · "
                  f"{(obs['location'] or '?') + loc_tag:<30}"
                  f"{sym_tag:<12} · desc={desc_len}c · {obs['raw_title'][:35]}")

        all_observations.extend(channel_obs)
        channel_summaries.append({
            "channel":   channel["name"],
            "videos":    len(channel_obs),
            "skipped":   skipped,
            "high":      sum(1 for o in channel_obs if o["confidence"] == "high"),
            "medium":    sum(1 for o in channel_obs if o["confidence"] == "medium"),
            "low_meta":  sum(1 for o in channel_obs if o["confidence"] in ("low","meta")),
            "dg_likely": sum(1 for o in channel_obs if o["dg_likely"]),
            "defaulted": sum(1 for o in channel_obs if o.get("location_source") == "channel_default"),
        })

    # Save updated dedup registry
    save_seen(seen)
    dedup_summary = dedup_stats(seen)
    print(f"  Dedup registry saved: {dedup_summary['total']} total videos across all runs")

    # ── ACCUMULATION: load existing, merge, never shrink ──────────────────────
    # Rule: the observations file may only grow. If a run produces fewer
    # records than currently on disk, the write is aborted and an error is
    # raised so the problem is visible in the Actions log.
    existing_obs = []
    existing_channels = {}
    if os.path.exists(output_file):
        try:
            with open(output_file) as f_existing:
                existing_data = json.load(f_existing)
                existing_obs = existing_data.get("observations", [])
                # Preserve channel summaries from last run that had data
                for ch in existing_data.get("channels", []):
                    if ch.get("videos", 0) > 0:
                        existing_channels[ch["channel"]] = ch
            print(f"  Loaded {len(existing_obs)} existing observations from {output_file}")
        except Exception as e:
            print(f"  Warning: could not load existing data: {e}")

    # Merge: existing + new, deduplicated by video_id
    existing_ids = {o.get("video_id") for o in existing_obs if o.get("video_id")}
    new_unique = [o for o in all_observations if o.get("video_id") not in existing_ids]
    merged = existing_obs + new_unique
    merged_sorted = sorted(merged, key=lambda x: x.get("published_at", ""), reverse=True)

    # ── SAFETY GATE: refuse to shrink the dataset ─────────────────────────────
    if len(merged_sorted) < len(existing_obs):
        msg = (
            f"  ABORT: merged set ({len(merged_sorted)}) is smaller than existing "
            f"({len(existing_obs)}). Refusing to write — data would be lost."
        )
        print(msg)
        raise RuntimeError(msg)

    # Merge channel summaries — use this run's counts but preserve history
    merged_channels = []
    seen_channel_names = set()
    for ch in channel_summaries:
        merged_channels.append(ch)
        seen_channel_names.add(ch["channel"])
    # Add channels from previous runs not in this run's summary
    for name, ch in existing_channels.items():
        if name not in seen_channel_names:
            ch["from_cache"] = True
            merged_channels.append(ch)

    print(f"  Accumulated: {len(merged_sorted)} total observations "
          f"({len(new_unique)} new, {len(existing_obs)} existing)")

    payload = {
        "generated_at":    datetime.datetime.utcnow().isoformat() + "Z",
        "dedup_registry":  dedup_summary,
        "days_back":       days_back,
        "since":           since,
        "channels":        merged_channels,
        "total":           len(merged_sorted),
        "new_this_run":    len(new_unique),
        "high_confidence": sum(1 for o in merged_sorted if o["confidence"] == "high"),
        "dg_likely":       sum(1 for o in merged_sorted if o["dg_likely"]),
        "observations":    merged_sorted,
    }

    with open(output_file, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"\n  YouTube: {len(all_observations)} videos processed this run · "
          f"{len(merged_sorted)} total accumulated · "
          f"{payload['high_confidence']} HIGH · "
          f"vision={'on' if ENABLE_VISION else 'off'}")
    return payload

if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    run(days_back=days)
