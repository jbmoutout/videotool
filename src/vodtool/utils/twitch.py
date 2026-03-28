"""Twitch VOD and chat downloader utilities."""

import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("vodtool")

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
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


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
    result = subprocess.run(
        ["streamlink", url, quality, "--output", str(output_path)],
        text=True,
    )
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
        stderr=subprocess.DEVNULL,
    )

    # Estimate expected file size from quality:
    # worst (~400kbps) = ~180MB/hr, 720p (~2.5Mbps) = ~1.1GB/hr, best (~6Mbps) = ~2.7GB/hr
    # We don't know the duration, so we estimate from file growth rate.
    # After 10s of download, extrapolate total size from growth rate.
    estimated_total = 0
    last_size = 0

    while proc.poll() is None:
        time.sleep(2)
        if output_path.exists():
            current_size = output_path.stat().st_size
            if estimated_total == 0 and current_size > 1_000_000:
                # After first MB, read streamlink stderr for any duration hints
                # Otherwise estimate: assume file grows ~linearly, estimate
                # total from growth rate over the first 10s
                pass

            if estimated_total == 0 and current_size > 1_000_000:
                # After 5MB, estimate total from growth rate
                # Assume we're ~10s in, typical VOD is 1-4 hours
                # Use a rough heuristic: multiply current rate by expected duration
                # For now, just use a reasonable estimate: 500MB for worst, 2GB for 720p
                if "worst" in quality:
                    estimated_total = 500_000_000  # ~500MB
                elif "best" in quality:
                    estimated_total = 3_000_000_000  # ~3GB
                else:
                    estimated_total = 1_500_000_000  # ~1.5GB

            if estimated_total > 0 and progress_callback:
                pct = min(current_size / estimated_total, 0.95)
                progress_callback(pct)

            last_size = current_size

    if proc.returncode != 0:
        logger.error("streamlink failed")
        return False

    if progress_callback:
        progress_callback(1.0)

    return output_path.exists() and output_path.stat().st_size > 0


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
