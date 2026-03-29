"""Topic inspection command for vodtool - debug and analyze topics."""

import logging
import sqlite3
from pathlib import Path

import numpy as np
from rich.console import Console
from rich.table import Table
from vodtool.utils.file_utils import safe_read_json
from vodtool.utils.validation import validate_project_path

console = Console()
logger = logging.getLogger("vodtool")


def format_duration(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def load_chunk_data(db_path: Path, chunk_ids: list[str]) -> list[dict]:
    """
    Load full chunk data from database.

    Args:
        db_path: Path to embeddings.sqlite
        chunk_ids: List of chunk IDs to load

    Returns:
        List of chunk dicts with id, text, start, end, duration
    """
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

    # Build dict for ordered retrieval
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

    # Return in same order as chunk_ids
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


def find_most_central_chunks(
    chunk_ids: list[str], embeddings: dict[str, np.ndarray], n: int = 5,
) -> list[str]:
    """
    Find the most central chunks based on average cosine similarity to all others.

    Args:
        chunk_ids: List of chunk IDs
        embeddings: Dict of chunk_id to embedding vector
        n: Number of central chunks to return

    Returns:
        List of most central chunk IDs
    """
    if len(chunk_ids) <= n:
        return chunk_ids

    # Compute centrality score for each chunk (average similarity to all others)
    centrality_scores = []

    for chunk_id in chunk_ids:
        if chunk_id not in embeddings:
            centrality_scores.append((chunk_id, 0.0))
            continue

        vec = embeddings[chunk_id]
        similarities = []

        for other_id in chunk_ids:
            if other_id != chunk_id and other_id in embeddings:
                other_vec = embeddings[other_id]
                # Cosine similarity
                sim = np.dot(vec, other_vec) / (np.linalg.norm(vec) * np.linalg.norm(other_vec))
                similarities.append(sim)

        avg_similarity = np.mean(similarities) if similarities else 0.0
        centrality_scores.append((chunk_id, avg_similarity))

    # Sort by centrality score (descending)
    centrality_scores.sort(key=lambda x: x[1], reverse=True)

    return [chunk_id for chunk_id, _ in centrality_scores[:n]]


def inspect_topic_command(project_path: Path, topic_id: str) -> None:
    """
    Inspect a topic and display detailed information.

    Args:
        project_path: Path to project directory
        topic_id: Topic ID to inspect (e.g., 'topic_0000')
    """
    # Validate project directory
    error = validate_project_path(project_path)
    if error:
        console.print(f"[red]Error: {error}[/red]")
        return

    # Check for topic_map.json (try labeled first, then unlabeled)
    labeled_path = project_path / "topic_map_labeled.json"
    unlabeled_path = project_path / "topic_map.json"

    if labeled_path.exists():
        topic_map_path = labeled_path
    elif unlabeled_path.exists():
        topic_map_path = unlabeled_path
    else:
        console.print(f"[red]Error: Topic map not found in {project_path}[/red]")
        console.print("Run 'vodtool topics' first to create topic map.")
        return

    # Check for embeddings database
    db_path = project_path / "embeddings.sqlite"
    if not db_path.exists():
        console.print(f"[red]Error: Embeddings database not found: {db_path}[/red]")
        return

    # Load topic map
    console.print(f"[cyan]Loading topic map from {topic_map_path.name}...[/cyan]\n")

    topics = safe_read_json(topic_map_path)
    if topics is None:
        return

    # Find the requested topic
    topic = None
    for t in topics:
        if t["topic_id"] == topic_id:
            topic = t
            break

    if topic is None:
        console.print(f"[red]Error: Topic '{topic_id}' not found[/red]")
        console.print("\nAvailable topics:")
        for t in topics:
            label = t.get("label", "Unlabeled")
            console.print(f"  - {t['topic_id']}: {label}")
        return

    # Collect all chunk IDs for this topic
    all_chunk_ids = []
    for span in topic["spans"]:
        all_chunk_ids.extend(span["chunk_ids"])

    # Remove duplicates while preserving order
    seen = set()
    unique_chunk_ids = [cid for cid in all_chunk_ids if not (cid in seen or seen.add(cid))]

    # Load chunk data
    chunks = load_chunk_data(db_path, unique_chunk_ids)

    if not chunks:
        console.print(f"[red]Error: No chunks found for topic {topic_id}[/red]")
        return

    # Calculate total duration
    total_duration = sum(chunk["duration"] for chunk in chunks)

    # Load embeddings for centrality calculation
    embeddings = load_embeddings(db_path, unique_chunk_ids)

    # Find most central chunks
    central_chunk_ids = find_most_central_chunks(unique_chunk_ids, embeddings, n=5)
    central_chunks = [c for c in chunks if c["chunk_id"] in central_chunk_ids]

    # Find longest chunks
    sorted_by_duration = sorted(chunks, key=lambda c: c["duration"], reverse=True)
    longest_chunks = sorted_by_duration[:5]

    # Display topic information
    console.print(f"[bold cyan]Topic: {topic_id}[/bold cyan]")

    label = topic.get("label", "Unlabeled")
    console.print(f"[bold]Label:[/bold] {label}")

    console.print("\n[bold]Statistics:[/bold]")
    console.print(f"  Total chunks: {len(chunks)}")
    console.print(f"  Total duration: {format_duration(total_duration)} ({total_duration:.1f}s)")
    console.print(f"  Number of spans: {len(topic['spans'])}")
    console.print(f"  Average chunk duration: {format_duration(total_duration / len(chunks))}")

    # Display spans
    console.print("\n[bold]Spans:[/bold]")
    spans_table = Table(show_header=True, header_style="bold magenta")
    spans_table.add_column("#", style="dim", width=3)
    spans_table.add_column("Start", justify="right")
    spans_table.add_column("End", justify="right")
    spans_table.add_column("Duration", justify="right")
    spans_table.add_column("Chunks", justify="right")

    for idx, span in enumerate(topic["spans"]):
        duration = span["end"] - span["start"]
        spans_table.add_row(
            str(idx + 1),
            format_duration(span["start"]),
            format_duration(span["end"]),
            format_duration(duration),
            str(len(span["chunk_ids"])),
        )

    console.print(spans_table)

    # Display 5 most central chunks
    console.print("\n[bold]5 Most Central Chunks (semantically representative):[/bold]")
    for idx, chunk in enumerate(central_chunks, 1):
        time_range = (
            f"{format_duration(chunk['start'])} - "
            f"{format_duration(chunk['end'])} ({chunk['duration']:.1f}s)"
        )
        console.print(f"\n[cyan]{idx}. [{chunk['chunk_id']}] {time_range}[/cyan]")
        console.print(f"   {chunk['text'][:200]}{'...' if len(chunk['text']) > 200 else ''}")

    # Display 5 longest chunks
    console.print("\n[bold]5 Longest Chunks:[/bold]")
    for idx, chunk in enumerate(longest_chunks, 1):
        time_range = (
            f"{format_duration(chunk['start'])} - "
            f"{format_duration(chunk['end'])} ({chunk['duration']:.1f}s)"
        )
        console.print(f"\n[cyan]{idx}. [{chunk['chunk_id']}] {time_range}[/cyan]")
        console.print(f"   {chunk['text'][:200]}{'...' if len(chunk['text']) > 200 else ''}")

    console.print("\n[green]✓ Topic inspection complete![/green]")
