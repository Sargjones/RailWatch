"""
railwatch_backfill.py — RailWatch historical backfill scraper
Part of the Critical TO infrastructure intelligence family (criticalto.ca)

Fetches one channel's historical videos in 90-day windows, stepping backward
in time from today. Writes to railwatch_backfill.json — completely separate
from the live railwatch_youtube_latest.json. Never touches live data.

Cursor state is tracked in backfill_state.json, committed to the repo after
each run so the next run knows where to pick up.

Usage:
  python scraper/railwatch_backfill.py --channel "Track Side Mike"
  python scraper/railwatch_backfill.py --channel "PTBO Railfanning"

Controlled via BACKFILL_CHANNEL env var in scrape.yml:
  BACKFILL_CHANNEL: "Track Side Mike"

Backfill order (bottom-up by volume):
  1. Track Side Mike         ~200 videos  Jun 16
  2. PTBO Railfanning        ~25  videos  Jun 17
  3. Ontario Northland Railfan unknown   Jun 18
  4. Ontario Railman          unknown    Jun 19
  5. Rail Fans Canada         ~100 videos Jun 20
  6. Trackside Tristan        ~200 videos Jun 21
  7. Scott Rails              ~150 videos Jun 22-23
  8. Trackside Tyson          ~400 videos Jun 24-25
  9. Trackside Ontario        ~300 videos Jun 26-27
  10. Southern Ontario Railfan ~200 videos Jun 28-29
  11. MJM Productions         ~500 videos Jun 30-Jul 3
  12. Brockville RailFan      ~600 videos Jul 4-10
  13. PROMOTE all validated   —           Jul 11

Author: SJonesG / Critical TO
"""

import os
import re
import json
import base64
import time
import datetime
import argparse
import requests

# ── Import shared extraction logic from main scraper ──────────────────────────
# We reuse all the same extractors — no duplication
import sys
sys.path.insert(0, os.path.dirname(__file__))
from railwatch_youtube import (
    CHANNELS,
    fetch_channel_videos,
    fetch_video_details,
    parse_video,
    YOUTUBE_API_KEY,
)

# ── CONFIG ────────────────────────────────────────────────────────────────────

BACKFILL_STATE_FILE  = "backfill_state.json"
BACKFILL_OUTPUT_FILE = "railwatch_backfill.json"
WINDOW_DAYS          = 90    # fetch 90 days per run per channel
INTER_REQUEST_DELAY  = 1.5   # seconds between channel API calls — avoids 429

# ── STATE MANAGEMENT ──────────────────────────────────────────────────────────

def load_state():
    """Load backfill cursor state. Returns dict keyed by channel name."""
    if not os.path.exists(BACKFILL_STATE_FILE):
        return {}
    try:
        with open(BACKFILL_STATE_FILE) as f:
            return json.load(f)
    except Exception as e:
        print(f"  Backfill: could not load state: {e}")
        return {}

def save_state(state):
    """Persist cursor state to disk."""
    with open(BACKFILL_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    print(f"  Backfill state saved: {BACKFILL_STATE_FILE}")

def get_channel_state(state, channel_name):
    """
    Get or initialise state for a channel.
    'fetch_before' is the upper bound of the next window to fetch.
    Starts at today and steps backward by WINDOW_DAYS each run.
    'backfill_until' is the target end date (one year ago).
    """
    if channel_name not in state:
        today = datetime.date.today()
        one_year_ago = today - datetime.timedelta(days=365)
        state[channel_name] = {
            "channel":        channel_name,
            "fetch_before":   today.isoformat(),           # start from today
            "backfill_until": one_year_ago.isoformat(),    # target: 1 year back
            "windows_fetched": 0,
            "total_videos":   0,
            "status":         "not_started",
            "started_at":     datetime.datetime.utcnow().isoformat() + "Z",
            "last_run":       None,
            "completed_at":   None,
        }
    return state[channel_name]

# ── OUTPUT MANAGEMENT ─────────────────────────────────────────────────────────

def load_backfill_output():
    """Load existing backfill output. Returns the full payload dict."""
    if not os.path.exists(BACKFILL_OUTPUT_FILE):
        return {
            "generated_at":  datetime.datetime.utcnow().isoformat() + "Z",
            "description":   "RailWatch historical backfill — separate from live data",
            "channels":      {},
            "total_videos":  0,
            "observations":  [],
        }
    try:
        with open(BACKFILL_OUTPUT_FILE) as f:
            return json.load(f)
    except Exception as e:
        print(f"  Backfill: could not load output: {e}")
        return {
            "generated_at":  datetime.datetime.utcnow().isoformat() + "Z",
            "description":   "RailWatch historical backfill — separate from live data",
            "channels":      {},
            "total_videos":  0,
            "observations":  [],
        }

def save_backfill_output(payload):
    """Write backfill output. Never touches live data files."""
    # Safety check — refuse to write to live data file
    if BACKFILL_OUTPUT_FILE == "railwatch_youtube_latest.json":
        raise RuntimeError("ABORT: backfill would overwrite live data")
    with open(BACKFILL_OUTPUT_FILE, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"  Backfill output saved: {BACKFILL_OUTPUT_FILE}")

# ── MAIN ──────────────────────────────────────────────────────────────────────

def run_backfill(channel_name):
    """
    Fetch one 90-day window of historical videos for the named channel.
    Merges into backfill output. Updates cursor state.
    """
    if not YOUTUBE_API_KEY:
        print("  Backfill: YOUTUBE_API_KEY not set — skipping")
        return

    # Find channel config
    channel_meta = next(
        (c for c in CHANNELS if c["name"] == channel_name and c.get("id")),
        None
    )
    if not channel_meta:
        print(f"  Backfill: channel '{channel_name}' not found or has no ID")
        return

    # Load state and output
    state   = load_state()
    ch_state = get_channel_state(state, channel_name)
    output  = load_backfill_output()

    # Check if already complete
    if ch_state["status"] == "complete":
        print(f"  Backfill: {channel_name} already complete — nothing to do")
        return

    # Calculate this run's date window
    fetch_before = datetime.date.fromisoformat(ch_state["fetch_before"])
    fetch_after  = fetch_before - datetime.timedelta(days=WINDOW_DAYS)
    backfill_until = datetime.date.fromisoformat(ch_state["backfill_until"])

    # Don't go past the target
    if fetch_after < backfill_until:
        fetch_after = backfill_until

    print(f"  Backfill: {channel_name}")
    print(f"    Window: {fetch_after} → {fetch_before}")
    print(f"    Target: {backfill_until} ({(fetch_before - backfill_until).days} days remaining)")

    # Fetch videos in this window
    published_after  = fetch_after.strftime("%Y-%m-%dT00:00:00Z")
    published_before = fetch_before.strftime("%Y-%m-%dT23:59:59Z")

    time.sleep(INTER_REQUEST_DELAY)  # be polite to the API

    items = fetch_channel_videos_windowed(
        channel_meta["id"],
        published_after=published_after,
        published_before=published_before,
        max_results=50,
    )

    print(f"    Fetched: {len(items)} videos")

    if items:
        time.sleep(INTER_REQUEST_DELAY)
        video_ids = [i.get("id", {}).get("videoId") for i in items if i.get("id", {}).get("videoId")]
        details   = fetch_video_details(video_ids)

        new_observations = []
        for item in items:
            vid_id = item.get("id", {}).get("videoId")
            if not vid_id:
                continue
            detail = details.get(vid_id, item)
            obs    = parse_video(item, detail, channel_meta)
            obs["backfill"] = True  # tag so dashboard can distinguish
            new_observations.append(obs)

        # Merge into output — deduplicate by video_id
        existing_ids = {o.get("video_id") for o in output["observations"]}
        new_unique   = [o for o in new_observations if o.get("video_id") not in existing_ids]

        output["observations"].extend(new_unique)
        output["observations"].sort(
            key=lambda x: x.get("published_at", ""), reverse=True
        )

        # Update channel summary in output
        if channel_name not in output["channels"]:
            output["channels"][channel_name] = {"total": 0, "windows": []}
        output["channels"][channel_name]["total"] += len(new_unique)
        output["channels"][channel_name]["windows"].append({
            "from":   fetch_after.isoformat(),
            "to":     fetch_before.isoformat(),
            "videos": len(new_unique),
        })

        output["total_videos"]  = len(output["observations"])
        output["generated_at"]  = datetime.datetime.utcnow().isoformat() + "Z"

        print(f"    Added: {len(new_unique)} new observations "
              f"({len(items) - len(new_unique)} duplicates skipped)")
    else:
        print(f"    No videos found in this window")

    # Update cursor state
    ch_state["fetch_before"]    = fetch_after.isoformat()  # next run starts here
    ch_state["windows_fetched"] += 1
    ch_state["total_videos"]    += len(items)
    ch_state["last_run"]        = datetime.datetime.utcnow().isoformat() + "Z"
    ch_state["status"]          = "in_progress"

    # Mark complete if we've reached the target
    if fetch_after <= backfill_until:
        ch_state["status"]       = "complete"
        ch_state["completed_at"] = datetime.datetime.utcnow().isoformat() + "Z"
        print(f"  ✓ Backfill COMPLETE for {channel_name} — "
              f"{ch_state['windows_fetched']} windows, "
              f"{ch_state['total_videos']} total videos fetched")
    else:
        remaining = (fetch_after - backfill_until).days
        print(f"    Remaining: ~{remaining} days to backfill "
              f"(~{remaining // WINDOW_DAYS + 1} more runs)")

    state[channel_name] = ch_state
    save_state(state)
    save_backfill_output(output)


def fetch_channel_videos_windowed(channel_id, published_after, published_before,
                                   max_results=50):
    """
    Fetch videos from a channel within a specific date window.
    Uses both publishedAfter AND publishedBefore — standard scraper only
    uses publishedAfter.
    """
    if not YOUTUBE_API_KEY:
        return []
    params = {
        "part":           "snippet",
        "channelId":      channel_id,
        "maxResults":     min(max_results, 50),
        "order":          "date",
        "type":           "video",
        "publishedAfter":  published_after,
        "publishedBefore": published_before,
        "key":             YOUTUBE_API_KEY,
    }
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params=params, timeout=20
        )
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as e:
        print(f"  YouTube API error (backfill): {e}")
        return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RailWatch backfill scraper")
    parser.add_argument(
        "--channel",
        default=os.environ.get("BACKFILL_CHANNEL", ""),
        help="Channel name to backfill (must match CHANNELS registry exactly)"
    )
    args = parser.parse_args()

    if not args.channel:
        print("Usage: python railwatch_backfill.py --channel 'Track Side Mike'")
        print("Or set BACKFILL_CHANNEL environment variable")
        sys.exit(1)

    run_backfill(args.channel)
