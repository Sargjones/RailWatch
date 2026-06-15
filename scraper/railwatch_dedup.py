"""
railwatch_dedup.py — RailWatch video deduplication cache
Part of the Critical TO infrastructure intelligence family (criticalto.ca)

Maintains seen_videos.json — a persistent registry of all processed video IDs.
The YouTube scraper checks this before processing any video, skipping known IDs
and only running vision/extraction on genuinely new content.

This means:
  - Vision API costs are incurred once per video, not on every run
  - Historical observations accumulate rather than rolling 7-day window
  - Duplicate observations never enter the dataset

Author: SJonesG / Critical TO
"""

import json
import os
import datetime

SEEN_FILE = "seen_videos.json"

def load_seen() -> dict:
    """
    Load the seen video registry.
    Returns dict: {video_id: {channel, title, processed_at, confidence}}
    """
    if not os.path.exists(SEEN_FILE):
        return {}
    try:
        with open(SEEN_FILE, "r") as f:
            data = json.load(f)
            return data.get("videos", {})
    except Exception:
        return {}

def save_seen(seen: dict) -> None:
    """Write the seen registry back to disk."""
    payload = {
        "meta": {
            "description": "RailWatch processed video registry",
            "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "total_videos": len(seen),
        },
        "videos": seen,
    }
    with open(SEEN_FILE, "w") as f:
        json.dump(payload, f, indent=2)

def is_seen(video_id: str, seen: dict) -> bool:
    return video_id in seen

def mark_seen(video_id: str, channel: str, title: str,
              confidence: str, seen: dict) -> dict:
    """Record a video as processed."""
    seen[video_id] = {
        "channel":      channel,
        "title":        title[:80],
        "confidence":   confidence,
        "processed_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    return seen

def filter_new(items: list, seen: dict) -> tuple:
    """
    Split a list of YouTube items into new and already-seen.
    Returns (new_items, skipped_count)
    """
    new, skipped = [], 0
    for item in items:
        vid_id = item.get("id", {}).get("videoId", "")
        if vid_id and is_seen(vid_id, seen):
            skipped += 1
        else:
            new.append(item)
    return new, skipped

def stats(seen: dict) -> dict:
    """Return summary statistics on the seen registry."""
    by_channel = {}
    by_confidence = {"high": 0, "medium": 0, "low": 0, "meta": 0}
    for vid_id, meta in seen.items():
        ch = meta.get("channel", "unknown")
        by_channel[ch] = by_channel.get(ch, 0) + 1
        conf = meta.get("confidence", "meta")
        by_confidence[conf] = by_confidence.get(conf, 0) + 1
    return {
        "total": len(seen),
        "by_channel": by_channel,
        "by_confidence": by_confidence,
    }
