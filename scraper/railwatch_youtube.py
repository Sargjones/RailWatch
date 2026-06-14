"""
railwatch_youtube.py — RailWatch YouTube railfan channel scraper
Part of the Critical TO infrastructure intelligence family (criticalto.ca)

Pulls video metadata from configured railfan YouTube channels.
Extracts structured observation data from titles, descriptions, and tags
without downloading video content (YouTube Data API v3 only — no ToS issues).

Optionally: if ANTHROPIC_API_KEY is set and ENABLE_VISION=true, downloads
the video thumbnail and runs Claude vision to extract additional detail.

Outputs: railwatch_youtube_latest.json (appended to main data payload)

Author: Sarah Jones / Critical TO
"""

import os
import re
import json
import datetime
import requests

# ─── CONFIG ───────────────────────────────────────────────────────────────────
# Set these as GitHub Actions secrets / environment variables

YOUTUBE_API_KEY   = os.environ.get("YOUTUBE_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ENABLE_VISION     = os.environ.get("ENABLE_VISION", "false").lower() == "true"

# ── CHANNEL REGISTRY ──────────────────────────────────────────────────────────
# Add channels here as RailWatch partnerships grow.
# channel_id: view source on channel page, search "channelId" OR
#             use https://www.youtube.com/@handle → About → Share → Copy channel ID
#
# How to find it fast:
#   1. Open the YouTube channel
#   2. View Page Source (Cmd+U / Ctrl+U)
#   3. Search for: "channelId":"UC
#   4. Copy the UCxxxxxxx string

CHANNELS = [
    {
        "id":          "",                          # ← PASTE channel ID here
        "name":        "Trackside Ontario",
        "handle":      "@TracksideOntario",         # for reference
        "focus":       ["Bayview Junction", "CN Dundas Sub", "CN Oakville Sub"],
        "primary_location": "Bayview Junction, Hamilton ON",
        "active":      True,
    },
    {
        "id":          "UCyLxbrzjqNTMNL68la32UzQ",  # Trackside Tyson (confirmed)
        "name":        "Trackside Tyson",
        "handle":      "@tracksidetyson",
        "focus":       ["CN", "CPKC", "Ontario", "cross-Canada"],
        "primary_location": "Ontario, Canada",
        "active":      True,
    },
    {
        "id":          "UCojaEJ7WwqMvtlQlQdalEAA",  # Southern Ontario Railfan (confirmed)
        "name":        "Southern Ontario Railfan",
        "handle":      "@SouthernOntarioRailfan2026",
        "focus":       ["CN Dundas Sub", "CN Chatham Sub", "CPKC Windsor Sub"],
        "primary_location": "Strathroy / Windsor corridor",
        "active":      True,
    },
    {
        "id":          "",                          # ← Trackside Toronto (add ID)
        "name":        "Trackside Toronto",
        "handle":      "@tracksidetoronto",
        "focus":       ["VIA Rail", "GO Transit", "CN", "Toronto"],
        "primary_location": "Toronto / Kingston Sub",
        "active":      False,  # enable once ID confirmed
    },
]

# ── KEYWORD PATTERNS ──────────────────────────────────────────────────────────
# Used to extract structured data from video titles and descriptions.
# Titles like: "CN 3145 with loaded tank cars eastbound at Bayview Junction 2026-06-14"

LOCATION_KEYWORDS = {
    "Bayview Junction":    {"subdivision": "CN Oakville/Dundas Sub", "lat": 43.2870, "lon": -79.7760},
    "Aldershot":           {"subdivision": "CN Oakville Sub",         "lat": 43.3050, "lon": -79.7500},
    "Hamilton":            {"subdivision": "CN Dundas Sub",            "lat": 43.2700, "lon": -79.8100},
    "Burlington":          {"subdivision": "CN Oakville Sub",          "lat": 43.3200, "lon": -79.8000},
    "Oakville":            {"subdivision": "CN Oakville Sub",          "lat": 43.4472, "lon": -79.6877},
    "Mississauga":         {"subdivision": "CN Oakville Sub",          "lat": 43.5890, "lon": -79.6441},
    "Toronto":             {"subdivision": "CN Kingston/Oakville Sub", "lat": 43.6450, "lon": -79.3800},
    "Kingston":            {"subdivision": "CN Kingston Sub",          "lat": 44.2300, "lon": -76.4800},
    "Brockville":          {"subdivision": "CN Kingston Sub",          "lat": 44.5800, "lon": -75.7000},
    "Ottawa":              {"subdivision": "CN Smiths Falls Sub",      "lat": 45.4230, "lon": -75.6950},
    "London":              {"subdivision": "CN Dundas Sub",            "lat": 43.0080, "lon": -80.9960},
    "Windsor":             {"subdivision": "CN Dundas Sub",            "lat": 42.3149, "lon": -83.0364},
    "Sarnia":              {"subdivision": "CN Chatham Sub",           "lat": 42.9744, "lon": -82.4058},
    "Chatham":             {"subdivision": "CN Chatham Sub",           "lat": 42.4900, "lon": -82.1900},
    "Woodstock":           {"subdivision": "CN Dundas Sub",            "lat": 43.1300, "lon": -80.7500},
    "Barrie":              {"subdivision": "CN Bala Sub",              "lat": 44.3900, "lon": -79.6800},
    "Sudbury":             {"subdivision": "CN Bala Sub",              "lat": 46.4900, "lon": -80.9900},
}

COMMODITY_KEYWORDS = {
    "tank car":        {"type": "tank", "dg_likely": True},
    "tank cars":       {"type": "tank", "dg_likely": True},
    "tanker":          {"type": "tank", "dg_likely": True},
    "loaded":          {"type": "unknown", "dg_likely": True},
    "chemical":        {"type": "tank", "dg_likely": True},
    "crude":           {"type": "tank", "dg_likely": True, "un": "1267"},
    "propane":         {"type": "pressure_tank", "dg_likely": True, "un": "1978"},
    "ethanol":         {"type": "tank", "dg_likely": True, "un": "1170"},
    "acid":            {"type": "tank", "dg_likely": True},
    "hopper":          {"type": "hopper", "dg_likely": False},
    "grain":           {"type": "hopper", "dg_likely": False},
    "potash":          {"type": "hopper", "dg_likely": False},
    "coal":            {"type": "gondola", "dg_likely": False},
    "intermodal":      {"type": "intermodal", "dg_likely": False},
    "container":       {"type": "intermodal", "dg_likely": False},
    "manifest":        {"type": "mixed", "dg_likely": True},
    "auto rack":       {"type": "auto_rack", "dg_likely": False},
    "lumber":          {"type": "flatcar", "dg_likely": False},
}

DIRECTION_PATTERNS = [
    (r'\b(eastbound|east bound|EB|heading east|moving east)\b', 'East'),
    (r'\b(westbound|west bound|WB|heading west|moving west)\b', 'West'),
    (r'\b(northbound|north bound|NB)\b', 'North'),
    (r'\b(southbound|south bound|SB)\b', 'South'),
]

DATE_PATTERNS = [
    r'(\d{4}[-/]\d{2}[-/]\d{2})',          # 2026-06-14 or 2026/06/14
    r'(\w+ \d{1,2},?\s*\d{4})',            # June 14, 2026
    r'(\d{1,2}[-/]\d{1,2}[-/]\d{4})',      # 14/06/2026
    r'(\w+ \d{4})',                         # June 2026 (month-level fallback)
]

LOCO_PATTERN = re.compile(r'\bCN\s*(\d{3,5})\b|\bCP\s*(\d{3,5})\b|\bVIA\s*(\d{3,5})\b')
UN_PATTERN   = re.compile(r'\bUN\s*(\d{4})\b', re.IGNORECASE)

# ─── YOUTUBE API ──────────────────────────────────────────────────────────────

YT_BASE = "https://www.googleapis.com/youtube/v3"

def yt_get(endpoint, params):
    """Make a YouTube Data API v3 request."""
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY not set")
    params["key"] = YOUTUBE_API_KEY
    r = requests.get(f"{YT_BASE}/{endpoint}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def fetch_channel_videos(channel_id, max_results=50, published_after=None):
    """
    Fetch recent videos from a channel using the search endpoint.
    Returns list of video items with snippet data.
    """
    params = {
        "part":       "snippet",
        "channelId":  channel_id,
        "maxResults": min(max_results, 50),
        "order":      "date",
        "type":       "video",
    }
    if published_after:
        params["publishedAfter"] = published_after  # RFC 3339 e.g. "2026-01-01T00:00:00Z"

    try:
        data = yt_get("search", params)
        return data.get("items", [])
    except Exception as e:
        print(f"  YouTube API error for channel {channel_id}: {e}")
        return []

def fetch_video_details(video_ids):
    """
    Fetch full snippet + contentDetails for a list of video IDs.
    Returns dict keyed by video ID.
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
    """Try to parse a date from title or description text."""
    for pattern in DATE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            # Normalize to YYYY-MM-DD where possible
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%B %d, %Y", "%B %d %Y",
                        "%b %d, %Y", "%b %d %Y", "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    return datetime.datetime.strptime(raw, fmt).date().isoformat()
                except:
                    continue
            return raw  # return raw if can't parse fully
    return None

def extract_location(text):
    """Find the best location match in title/description."""
    text_lower = text.lower()
    for keyword, meta in LOCATION_KEYWORDS.items():
        if keyword.lower() in text_lower:
            return {"name": keyword, **meta}
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
    # Prefer DG hits
    dg_hits = [h for h in hits if h["dg_likely"]]
    return dg_hits[0] if dg_hits else hits[0]

def extract_locos(text):
    """Extract locomotive reporting marks and numbers."""
    locos = []
    for m in LOCO_PATTERN.finditer(text):
        road = "CN" if m.group(1) else ("CP" if m.group(2) else "VIA")
        num  = m.group(1) or m.group(2) or m.group(3)
        locos.append(f"{road} {num}")
    return locos or None

def extract_un(text):
    m = UN_PATTERN.search(text)
    return m.group(1) if m else None

def parse_video(item, detail, channel_meta):
    """
    Convert a YouTube video item into a RailWatch observation record.
    Confidence levels:
      high   — date + location + commodity all extracted
      medium — date + location only
      low    — date or location only
      meta   — title/description only, minimal extraction
    """
    snippet = detail.get("snippet", item.get("snippet", {}))
    vid_id  = detail.get("id") or item.get("id", {}).get("videoId", "")

    title       = snippet.get("title", "")
    description = snippet.get("description", "")
    tags        = snippet.get("tags", [])
    published   = snippet.get("publishedAt", "")
    full_text   = f"{title} {description} {' '.join(tags)}"

    # Extract fields
    obs_date   = extract_date(title) or extract_date(description) or published[:10]
    location   = extract_location(full_text)
    direction  = extract_direction(full_text)
    commodity  = extract_commodity(full_text)
    locos      = extract_locos(full_text)
    un_number  = extract_un(full_text)

    # Confidence scoring
    score = sum([bool(obs_date), bool(location), bool(commodity)])
    confidence = "high" if score == 3 else "medium" if score == 2 else "low" if score == 1 else "meta"

    return {
        "source":        "youtube",
        "channel":       channel_meta["name"],
        "channel_id":    channel_meta["id"],
        "video_id":      vid_id,
        "video_url":     f"https://www.youtube.com/watch?v={vid_id}",
        "title":         title,
        "published_at":  published,
        "date":          obs_date,
        "location":      location["name"] if location else None,
        "subdivision":   location["subdivision"] if location else None,
        "lat":           location.get("lat") if location else None,
        "lon":           location.get("lon") if location else None,
        "direction":     direction,
        "commodity_type":commodity["type"] if commodity else None,
        "dg_likely":     commodity["dg_likely"] if commodity else False,
        "un_number":     un_number,
        "locomotives":   locos,
        "confidence":    confidence,
        "raw_title":     title,
    }

# ─── VISION (optional) ────────────────────────────────────────────────────────

def analyse_thumbnail(video_id, title):
    """
    Download the video thumbnail and run Claude vision on it.
    Extracts any visible reporting marks, placard classes, or consist details.
    Only called if ENABLE_VISION=true and ANTHROPIC_API_KEY is set.
    """
    if not ANTHROPIC_API_KEY or not ENABLE_VISION:
        return None

    thumb_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
    try:
        img_resp = requests.get(thumb_url, timeout=15)
        img_resp.raise_for_status()
        import base64
        img_b64 = base64.b64encode(img_resp.content).decode()
        media_type = "image/jpeg"
    except Exception as e:
        print(f"    Thumbnail fetch failed for {video_id}: {e}")
        return None

    prompt = f"""You are analyzing a thumbnail from a Canadian railfan video titled: "{title}"

Extract any of the following that are visible:
1. Reporting marks and car numbers (e.g. AITX 38342, PROX 16662, CN 3145)
2. Hazmat placard class diamonds (the number on the diamond: 1-9)
3. UN number panels (orange panel with 4-digit number)
4. Train direction of travel if determinable
5. Location landmarks if recognizable (Bayview Junction footbridge, Royal Botanical Gardens, etc.)
6. Car types visible (tank cars, hoppers, flatcars, auto racks)

Respond ONLY with a JSON object, no markdown:
{{
  "reporting_marks": ["AITX 38342", "CN 3145"],
  "placard_classes": ["8", "3"],
  "un_numbers": ["1791"],
  "direction": "East",
  "location_clue": "Bayview Junction footbridge visible",
  "car_types": ["tank car", "covered hopper"],
  "confidence": "medium",
  "notes": "any other relevant observations"
}}
If nothing relevant is visible, return {{"confidence": "none"}}"""

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
                "max_tokens": 500,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_b64}},
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
        print(f"    Vision analysis failed for {video_id}: {e}")
        return None

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def run(days_back=7, output_file="railwatch_youtube_latest.json"):
    """
    Main entry point. Pulls last `days_back` days of videos from all
    active channels and writes structured observation JSON.
    """
    if not YOUTUBE_API_KEY:
        print("  YouTube: YOUTUBE_API_KEY not set — skipping")
        return {"status": "skipped", "reason": "no API key", "observations": []}

    since = (datetime.datetime.utcnow() - datetime.timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00Z")
    all_observations = []
    channel_summaries = []

    active_channels = [c for c in CHANNELS if c["active"] and c["id"]]
    if not active_channels:
        print("  YouTube: no channels with confirmed IDs — add channel IDs to CHANNELS config")
        return {"status": "no_channels", "observations": []}

    for channel in active_channels:
        print(f"  Fetching {channel['name']} ({channel['id']})...")
        items = fetch_channel_videos(channel["id"], max_results=50, published_after=since)
        if not items:
            print(f"    No videos found in last {days_back} days")
            channel_summaries.append({"channel": channel["name"], "videos": 0, "observations": 0})
            continue

        # Get full details for all videos in one API call (efficient)
        video_ids = [i.get("id", {}).get("videoId") for i in items if i.get("id", {}).get("videoId")]
        details   = fetch_video_details(video_ids)

        channel_obs = []
        for item in items:
            vid_id = item.get("id", {}).get("videoId")
            if not vid_id:
                continue
            detail = details.get(vid_id, item)
            obs = parse_video(item, detail, channel)

            # Optionally enhance with vision
            if ENABLE_VISION and obs["confidence"] in ("medium", "high", "low"):
                print(f"    Vision: {vid_id} — {obs['raw_title'][:50]}")
                vision = analyse_thumbnail(vid_id, obs["raw_title"])
                if vision and vision.get("confidence") != "none":
                    obs["vision"] = vision
                    # Merge vision data
                    if vision.get("un_numbers") and not obs["un_number"]:
                        obs["un_number"] = vision["un_numbers"][0]
                    if vision.get("placard_classes"):
                        obs["placard_classes_vision"] = vision["placard_classes"]
                    if vision.get("reporting_marks"):
                        obs["reporting_marks_vision"] = vision["reporting_marks"]
                    if vision.get("direction") and not obs["direction"]:
                        obs["direction"] = vision["direction"]
                    # Upgrade confidence if vision found useful data
                    if vision.get("reporting_marks") or vision.get("placard_classes"):
                        obs["confidence"] = "high"

            channel_obs.append(obs)
            print(f"    [{obs['confidence']:6}] {obs['date']} · {obs['location'] or '?'} · {obs['raw_title'][:50]}")

        all_observations.extend(channel_obs)
        channel_summaries.append({
            "channel":      channel["name"],
            "videos":       len(channel_obs),
            "high":         sum(1 for o in channel_obs if o["confidence"] == "high"),
            "medium":       sum(1 for o in channel_obs if o["confidence"] == "medium"),
            "low_meta":     sum(1 for o in channel_obs if o["confidence"] in ("low", "meta")),
            "dg_likely":    sum(1 for o in channel_obs if o["dg_likely"]),
        })

    payload = {
        "generated_at":  datetime.datetime.utcnow().isoformat() + "Z",
        "days_back":     days_back,
        "since":         since,
        "channels":      channel_summaries,
        "total":         len(all_observations),
        "high_confidence": sum(1 for o in all_observations if o["confidence"] == "high"),
        "dg_likely":     sum(1 for o in all_observations if o["dg_likely"]),
        "observations":  sorted(all_observations, key=lambda x: x.get("published_at",""), reverse=True),
    }

    with open(output_file, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\n  YouTube: {len(all_observations)} videos → {payload['high_confidence']} high-confidence observations → {output_file}")
    return payload

if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    run(days_back=days)
