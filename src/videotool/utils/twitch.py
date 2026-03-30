"""Twitch VOD and chat downloader utilities."""

import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("videotool")

# Public client ID used by the Twitch web player
_TWITCH_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
_TWITCH_GQL_URL = "https://gql.twitch.tv/gql"


def parse_twitch_video_id(url: str) -> Optional[str]:
    """Extract video ID from a twitch.tv/videos/<id> URL."""
    match = re.search(r"twitch\.tv/videos/(\d+)", url)
    return match.group(1) if match else None


def is_twitch_url(value: str) -> bool:
    """Return True if value looks like a Twitch VOD URL."""
    return bool(re.search(r"twitch\.tv/videos/\d+", value))


def check_streamlink() -> bool:
    """Return True if streamlink is available."""
    try:
        result = subprocess.run(
            ["streamlink", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


# Ordered list of video qualities from lowest to highest resolution.
# Used for fallback when a requested quality is unavailable.
_QUALITY_LADDER = ["160p", "360p", "480p", "480p60", "720p", "720p60", "1080p", "1080p60"]


def get_available_streams(url: str) -> Optional[list[str]]:
    """Query streamlink for the list of available stream names.

    Returns a list of stream names (e.g. ['audio', '480p', '720p60', 'best'])
    or None if the query fails. Stderr is suppressed to avoid blocking.
    """
    try:
        result = subprocess.run(
            ["streamlink", url, "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("streamlink --json returned non-zero exit code")
            return None
        data = json.loads(result.stdout)
        return list(data.get("streams", {}).keys())
    except subprocess.TimeoutExpired:
        logger.warning("streamlink --json timed out after 30s")
        return None
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Failed to query available streams: {e}")
        return None


def resolve_quality(requested: str, available: list[str]) -> str:
    """
    Pick the best available quality from a requested comma-separated list.

    If none of the requested qualities exist, fall back to the nearest
    lower resolution on the quality ladder, then nearest higher, then 'best'.
    """
    candidates = [q.strip() for q in requested.split(",")]

    # Direct match
    for q in candidates:
        if q in available:
            logger.info(f"Quality '{q}' is available")
            return q

    # Find the best candidate on the quality ladder for fallback
    # Use the first candidate that's on the ladder as the target
    target_idx = None
    for q in candidates:
        if q in _QUALITY_LADDER:
            target_idx = _QUALITY_LADDER.index(q)
            break

    if target_idx is not None:
        available_on_ladder = [q for q in available if q in _QUALITY_LADDER]
        if available_on_ladder:
            # Sort by distance from target, preferring lower resolution
            def sort_key(q):
                idx = _QUALITY_LADDER.index(q)
                distance = abs(idx - target_idx)
                prefer_lower = 0 if idx <= target_idx else 1
                return (distance, prefer_lower)

            best = min(available_on_ladder, key=sort_key)
            logger.info(
                f"Requested quality '{requested}' unavailable, "
                f"falling back to '{best}'"
            )
            return best

    # Nothing on the ladder matched — use 'best' if available
    if "best" in available:
        logger.info(f"Requested quality '{requested}' unavailable, falling back to 'best'")
        return "best"

    # Last resort: return original and let streamlink handle it
    return candidates[0]


def download_vod(url: str, output_path: Path, quality: str = "worst") -> bool:
    """
    Download a Twitch VOD to output_path using streamlink.

    Args:
        url: Twitch VOD URL (https://twitch.tv/videos/<id>)
        output_path: Destination file path (e.g. /tmp/vod.mp4)
        quality: streamlink quality selector. Comma-separated fallback list.
                 Default: "720p,720p60,best" — prefers 720p, falls back to best.

    Returns:
        True on success, False on failure
    """
    logger.info(f"Downloading VOD: {url} (quality: {quality})")
    try:
        result = subprocess.run(
            ["streamlink", url, quality, "--output", str(output_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=21600,  # 6 hours — long VODs at low quality are legitimate
        )
    except subprocess.TimeoutExpired:
        logger.error("streamlink timed out after 2 hours")
        return False
    if result.returncode != 0:
        logger.error("streamlink failed")
        return False
    return output_path.exists() and output_path.stat().st_size > 0


def download_vod_with_progress(
    url: str,
    output_path: Path,
    quality: str = "worst",
    progress_callback=None,
) -> bool:
    """
    Download a Twitch VOD with progress tracking via file size growth.

    Spawns streamlink as a background process and polls the output file
    size to estimate download progress.

    Args:
        url: Twitch VOD URL
        output_path: Destination file path
        quality: streamlink quality selector
        progress_callback: Optional callable(pct: float) called with 0.0-1.0

    Returns:
        True on success, False on failure
    """
    logger.info(f"Downloading VOD: {url} (quality: {quality})")

    proc = subprocess.Popen(
        ["streamlink", url, quality, "--output", str(output_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,  # MUST be DEVNULL — PIPE deadlocks (see 35320f7)
    )

    # Track download progress via file size growth.
    # We measure the download rate over the first few seconds, then use
    # an asymptotic curve so progress always moves forward but never
    # overshoots. This works regardless of final file size.
    start_time = time.monotonic()
    rate = 0.0  # bytes/sec, measured from actual growth
    last_pct = 0.0

    while proc.poll() is None:
        time.sleep(2)
        elapsed = time.monotonic() - start_time

        if not output_path.exists():
            # File not created yet — show we're alive
            if progress_callback and elapsed < 10:
                progress_callback(min(elapsed / 200, 0.04))
            continue

        current_size = output_path.stat().st_size

        # Update rate estimate (exponential moving average for stability)
        if elapsed > 4 and current_size > 0:
            instant_rate = current_size / elapsed
            rate = instant_rate if rate == 0 else rate * 0.7 + instant_rate * 0.3

        # Progress: logarithmic curve that always advances.
        # pct = log(1 + elapsed/30) / log(1 + expected_total/30)
        # We assume the download takes at most 10 minutes (600s).
        # This gives smooth progress: ~30% at 60s, ~60% at 180s, ~80% at 360s.
        # At completion, process exits and we emit 1.0.
        import math as _math
        if rate > 0 and current_size > 100_000:
            # Scale expected total based on rate — faster rate = shorter expected
            # Audio (~3MB/s) typically finishes in 1-4 min.
            # Video (~1MB/s) might take 10-30 min.
            expected_total = max(300, 60 + elapsed * 0.5)
            pct = min(_math.log(1 + elapsed / 30) / _math.log(1 + expected_total / 30), 0.95)
        elif current_size > 0:
            # No rate yet — slow ramp
            pct = min(elapsed / 300, 0.10)
        else:
            pct = min(elapsed / 600, 0.03)

        # Never go backwards
        pct = max(pct, last_pct)
        last_pct = pct

        if progress_callback:
            progress_callback(pct)

    if proc.returncode != 0:
        logger.error(f"streamlink failed (exit code {proc.returncode})")
        return False

    if progress_callback:
        progress_callback(1.0)

    return output_path.exists() and output_path.stat().st_size > 0


def fetch_vod_metadata(video_id: str) -> Optional[dict]:
    """
    Fetch metadata (title, language) for a Twitch VOD via the GQL API.

    Args:
        video_id: Numeric Twitch video ID

    Returns:
        Dict with "title" and "language" keys, or None on failure.
        Language is a BCP-47 code (e.g. "fr", "en", "es").
    """
    try:
        import requests
    except ImportError:
        logger.warning("requests not installed — cannot fetch VOD metadata")
        return None

    query = {
        "query": f'{{ video(id: "{video_id}") {{ title language owner {{ displayName }} }} }}',
    }

    try:
        resp = requests.post(
            _TWITCH_GQL_URL,
            json=query,
            headers={"Client-ID": _TWITCH_CLIENT_ID},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        video = data["data"]["video"]
        owner = video.get("owner") or {}
        return {
            "title": video["title"],
            "language": video.get("language"),
            "channel": owner.get("displayName"),
        }
    except Exception as e:
        logger.warning(f"Failed to fetch VOD metadata: {e}")
        return None


def download_chat(video_id: str, output_path: Path) -> bool:
    """
    Download chat replay for a Twitch VOD via the GQL API.

    Paginates through all messages and saves to output_path as JSON:
    [{"offset": 12.3, "user": "nick", "text": "message"}, ...]

    Args:
        video_id: Numeric Twitch video ID
        output_path: Destination .json file

    Returns:
        True on success (even if 0 messages), False on network/API failure
    """
    try:
        import requests
    except ImportError:
        logger.warning("requests not installed — skipping chat download")
        return False

    messages = []
    cursor = None
    page = 0

    logger.info(f"Downloading chat for video {video_id}")

    while True:
        query = [
            {
                "operationName": "VideoCommentsByOffsetOrCursor",
                "variables": {
                    "videoID": video_id,
                    **({"cursor": cursor} if cursor else {"contentOffsetSeconds": 0}),
                },
                "extensions": {
                    "persistedQuery": {
                        "version": 1,
                        "sha256Hash": "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a",
                    }
                },
            }
        ]

        try:
            resp = requests.post(
                _TWITCH_GQL_URL,
                json=query,
                headers={"Client-ID": _TWITCH_CLIENT_ID},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Chat API request failed: {e}")
            return False

        try:
            comments_data = data[0]["data"]["video"]["comments"]
            if comments_data is None:
                logger.warning("No chat data available for this VOD")
                break
            edges = comments_data.get("edges", [])
        except (KeyError, IndexError, TypeError, AttributeError):
            logger.error("Unexpected chat API response shape")
            return False

        for edge in edges:
            node = edge.get("node", {})
            commenter = node.get("commenter") or {}
            message = node.get("message") or {}
            fragments = message.get("fragments") or []
            text = "".join(f.get("text", "") for f in fragments)
            offset = node.get("contentOffsetSeconds", 0)
            messages.append({
                "offset": offset,
                "user": commenter.get("displayName", ""),
                "text": text,
            })

        page_info = comments_data.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break

        cursor = edges[-1]["cursor"] if edges else None
        if not cursor:
            break

        page += 1
        if page % 10 == 0:
            logger.info(f"  downloaded {len(messages)} messages so far...")
            time.sleep(0.1)  # be polite

    output_path.write_text(json.dumps(messages, ensure_ascii=False, indent=2))
    logger.info(f"Saved {len(messages)} chat messages to {output_path}")
    return True


def summarize_chat_for_prompt(chat_path: Path, max_messages: int = 300) -> Optional[str]:
    """
    Load chat.json and return a compact string for LLM context.

    Samples evenly across the full chat so the LLM sees coverage of the
    whole stream, not just the first N minutes.

    Returns None if chat file doesn't exist or is empty.
    """
    if not chat_path.exists():
        return None

    try:
        messages = json.loads(chat_path.read_text())
    except Exception:
        return None

    if not messages:
        return None

    # Even sample across the full chat
    if len(messages) > max_messages:
        step = len(messages) / max_messages
        messages = [messages[int(i * step)] for i in range(max_messages)]

    lines = []
    for m in messages:
        offset = m.get("offset", 0)
        mins = int(offset // 60)
        secs = int(offset % 60)
        lines.append(f"[{mins:02d}:{secs:02d}] {m.get('user', '?')}: {m.get('text', '')}")

    return "\n".join(lines)
