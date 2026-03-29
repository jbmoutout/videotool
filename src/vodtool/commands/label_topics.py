"""Topic labeling command for vodtool using representative quotes."""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np
from rich.console import Console

from vodtool.utils.file_utils import safe_read_json
from vodtool.utils.validation import validate_project_path

console = Console()
logger = logging.getLogger("vodtool")


def format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    minutes = int(seconds // 60)
    if minutes >= 60:
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}h {mins}min" if mins else f"{hours}h"
    return f"{minutes} min"


def load_chunk_data(db_path: Path, chunk_ids: list[str]) -> list[dict]:
    """
    Load chunk data from database.

    Args:
        db_path: Path to embeddings.sqlite
        chunk_ids: List of chunk IDs to load

    Returns:
        List of chunk dicts with id, text, start, end, duration
    """
    if not chunk_ids:
        return []

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    placeholders = ",".join("?" * len(chunk_ids))
    query = f"""
        SELECT chunk_id, text, start, end
        FROM chunks
        WHERE chunk_id IN ({placeholders})
    """

    cursor.execute(query, chunk_ids)
    rows = cursor.fetchall()
    conn.close()

    chunk_dict = {
        row[0]: {
            "chunk_id": row[0],
            "text": row[1],
            "start": row[2],
            "end": row[3],
            "duration": row[3] - row[2],
        }
        for row in rows
    }

    return [chunk_dict[cid] for cid in chunk_ids if cid in chunk_dict]


def load_embeddings(db_path: Path, chunk_ids: list[str]) -> dict[str, np.ndarray]:
    """
    Load embeddings for chunks.

    Args:
        db_path: Path to embeddings.sqlite
        chunk_ids: List of chunk IDs

    Returns:
        Dict mapping chunk_id to embedding vector
    """
    if not chunk_ids:
        return {}

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    placeholders = ",".join("?" * len(chunk_ids))
    query = f"""
        SELECT chunk_id, vector
        FROM embeddings
        WHERE chunk_id IN ({placeholders})
    """

    cursor.execute(query, chunk_ids)
    rows = cursor.fetchall()
    conn.close()

    embeddings = {}
    for chunk_id, vector_bytes in rows:
        embeddings[chunk_id] = np.frombuffer(vector_bytes, dtype=np.float32)

    return embeddings


def find_representative_chunks(
    chunks: list[dict],
    embeddings: dict[str, np.ndarray],
    n: int = 3,
) -> list[dict]:
    """
    Find the most representative chunks based on centrality.

    Args:
        chunks: List of chunk dicts
        embeddings: Dict of chunk_id to embedding vector
        n: Number of representative chunks to return

    Returns:
        List of most representative chunk dicts
    """
    if len(chunks) <= n:
        return chunks

    # Compute centrality score for each chunk (average similarity to all others)
    centrality_scores = []

    for chunk in chunks:
        chunk_id = chunk["chunk_id"]
        if chunk_id not in embeddings:
            centrality_scores.append((chunk, 0.0))
            continue

        vec = embeddings[chunk_id]
        similarities = []

        for other_chunk in chunks:
            other_id = other_chunk["chunk_id"]
            if other_id != chunk_id and other_id in embeddings:
                other_vec = embeddings[other_id]
                norm_product = np.linalg.norm(vec) * np.linalg.norm(other_vec)
                if norm_product > 0:
                    sim = np.dot(vec, other_vec) / norm_product
                    similarities.append(sim)

        avg_similarity = np.mean(similarities) if similarities else 0.0
        centrality_scores.append((chunk, avg_similarity))

    # Sort by centrality score (descending)
    centrality_scores.sort(key=lambda x: x[1], reverse=True)

    return [chunk for chunk, _ in centrality_scores[:n]]


def extract_quote(text: str, min_length: int = 40, max_length: int = 120) -> str:
    """
    Extract the best sentence or phrase from chunk text.

    Strategy:
    1. Split text into sentences
    2. Find the first complete sentence that's long enough
    3. If no good sentence, take the first meaningful phrase

    Args:
        text: Raw chunk text
        min_length: Minimum length for a good quote
        max_length: Maximum length before truncating

    Returns:
        Cleaned quote string
    """
    import re

    # Clean up the text - normalize whitespace
    text = " ".join(text.split())

    if not text:
        return ""

    # If text is already short enough, return it
    if len(text) <= max_length:
        return text

    # Split into sentences using common sentence boundaries
    # Handle French and English punctuation patterns
    sentences = re.split(r'(?<=[.!?])\s+', text)

    # Find the first sentence that's meaningful (> min_length)
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) >= min_length:
            if len(sentence) <= max_length:
                return sentence
            # Sentence too long - try to find a natural break
            break

    # No good complete sentence found - extract first meaningful portion
    # Look for natural phrase boundaries (comma, dash, etc.)
    phrase_breaks = [", ", " - ", " – ", ": ", "; "]

    for break_char in phrase_breaks:
        idx = text.find(break_char, min_length)
        if min_length < idx < max_length:
            return text[:idx + len(break_char) - 1]

    # Last resort: find word boundary near max_length
    if len(text) > max_length:
        # Look for last space before max_length
        idx = text[:max_length].rfind(" ")
        if idx > min_length:
            return text[:idx] + "..."

    return text[:max_length] + "..."


def label_topics_command(project_path: Path, force: bool = False) -> Optional[Path]:
    """
    Generate topic labels with duration and representative quotes.

    Args:
        project_path: Path to the project directory
        force: Force re-labeling even if labels exist

    Returns:
        Path to the topic_map_labeled.json file, or None if labeling failed
    """
    # Validate project directory
    error = validate_project_path(project_path)
    if error:
        console.print(f"[red]Error: {error}[/red]")
        return None

    # Check for topic_map.json
    topic_map_path = project_path / "topic_map.json"
    if not topic_map_path.exists():
        console.print(f"[red]Error: Topic map not found: {topic_map_path}[/red]")
        console.print("Run 'vodtool topics' first to create topic map.")
        return None

    # Check for embeddings database
    db_path = project_path / "embeddings.sqlite"
    if not db_path.exists():
        console.print(f"[red]Error: Embeddings database not found: {db_path}[/red]")
        return None

    # Load topic map
    console.print("[cyan]Loading topic map...[/cyan]")
    topics = safe_read_json(topic_map_path)
    if topics is None:
        return None

    if not topics:
        console.print("[yellow]Warning: No topics found[/yellow]")
        return None

    logger.info(f"Loaded {len(topics)} topics")

    # Check if labeled version exists
    labeled_path = project_path / "topic_map_labeled.json"

    if labeled_path.exists() and not force:
        console.print(f"[yellow]Labeled topic map already exists: {labeled_path}[/yellow]")
        console.print("Use --force to regenerate labels.")
        return labeled_path

    # Process each topic
    console.print("[cyan]Extracting representative quotes...[/cyan]")

    for topic in topics:
        # Collect all chunk IDs for this topic
        chunk_ids = []
        for span in topic["spans"]:
            chunk_ids.extend(span["chunk_ids"])

        # Remove duplicates while preserving order
        seen = set()
        chunk_ids = [cid for cid in chunk_ids if not (cid in seen or seen.add(cid))]

        # Load chunk data and embeddings
        chunks = load_chunk_data(db_path, chunk_ids)
        embeddings = load_embeddings(db_path, chunk_ids)

        # Calculate durations:
        # - span_duration: sum of span durations (user expectation for "topic length")
        # - talk_time: sum of individual chunk durations (actual content time)
        span_duration = sum(span["end"] - span["start"] for span in topic["spans"])
        talk_time = sum(chunk["duration"] for chunk in chunks)

        topic["duration_seconds"] = span_duration
        topic["duration_label"] = format_duration(span_duration)
        topic["talk_time_seconds"] = talk_time
        topic["talk_time_label"] = format_duration(talk_time)

        # Find representative chunks
        representative = find_representative_chunks(chunks, embeddings, n=3)

        # Extract quotes
        quotes = [extract_quote(chunk["text"]) for chunk in representative]
        topic["quotes"] = quotes

        # Create a simple label (Topic N - Duration)
        topic_num = int(topic["topic_id"].split("_")[1]) + 1
        topic["label"] = f"Topic {topic_num}"

        # Mark as MISC if duration < 90s OR chunks < 3
        total_chunks = len(chunk_ids)
        topic["is_misc"] = span_duration < 90 or total_chunks < 3
        topic["chunk_count"] = total_chunks

        logger.info(
            f"{topic['topic_id']}: {topic['duration_label']}, "
            f"{len(quotes)} quotes, misc={topic['is_misc']}",
        )

    # Save labeled topic map
    try:
        with labeled_path.open("w", encoding="utf-8") as f:
            json.dump(topics, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved topic_map_labeled.json: {labeled_path}")
    except Exception as e:
        console.print(f"[red]Error saving labeled topic map: {e}[/red]")
        return None

    # Print summary with new format
    console.print("\n[green]✓ Topic labeling complete![/green]")
    console.print(f"[bold]Output:[/bold] {labeled_path}\n")

    # Separate MISC and regular topics
    regular_topics = [t for t in topics if not t.get("is_misc", False)]
    misc_topics = [t for t in topics if t.get("is_misc", False)]

    for topic in regular_topics:
        talk_time = topic.get("talk_time_label", "")
        duration_info = f"[bold]{topic['duration_label']}[/bold]"
        if talk_time and talk_time != topic["duration_label"]:
            duration_info += f" [dim](talk-time: {talk_time})[/dim]"

        console.print(f"[bold cyan]{topic['label']}[/bold cyan] — {duration_info}")
        for quote in topic.get("quotes", []):
            console.print(f'  [dim]•[/dim] "{quote}"')
        console.print()

    if misc_topics:
        console.print(
            f"[dim]+ {len(misc_topics)} MISC topic(s) hidden (< 90s or < 3 chunks)[/dim]",
        )
        console.print("[dim]  Use 'vodtool show-topics --include-misc' to view[/dim]\n")

    return labeled_path
