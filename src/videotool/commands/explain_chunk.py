"""Explain chunk command for videotool - show why a chunk belongs to its topic."""

import logging
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np
from rich.console import Console
from rich.table import Table
from videotool.utils.file_utils import safe_read_json
from videotool.utils.validation import validate_project_path

console = Console()
logger = logging.getLogger("videotool")


def format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(np.dot(vec1, vec2) / (norm1 * norm2))


def load_all_embeddings(db_path: Path) -> dict[str, tuple[np.ndarray, dict]]:
    """
    Load all embeddings and chunk metadata from database.

    Args:
        db_path: Path to embeddings.sqlite

    Returns:
        Dict mapping chunk_id to (embedding, metadata)
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    query = """
        SELECT c.chunk_id, c.text, c.start, c.end, c.speaker, e.vector
        FROM chunks c
        JOIN embeddings e ON c.chunk_id = e.chunk_id
    """

    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()

    result = {}
    for chunk_id, text, start, end, speaker, vector_bytes in rows:
        embedding = np.frombuffer(vector_bytes, dtype=np.float32)
        metadata = {
            "chunk_id": chunk_id,
            "text": text,
            "start": start,
            "end": end,
            "speaker": speaker,
        }
        result[chunk_id] = (embedding, metadata)

    return result


def find_chunk_topic(topics: list[dict], chunk_id: str) -> Optional[dict]:
    """
    Find which topic a chunk belongs to.

    Args:
        topics: List of topic dicts
        chunk_id: Chunk ID to find

    Returns:
        Topic dict or None if not found
    """
    for topic in topics:
        for span in topic["spans"]:
            if chunk_id in span["chunk_ids"]:
                return topic
    return None


def compute_topic_centroid(
    topic: dict, embeddings: dict[str, tuple[np.ndarray, dict]],
) -> Optional[np.ndarray]:
    """
    Compute the centroid embedding for a topic.

    Args:
        topic: Topic dict with spans
        embeddings: All embeddings

    Returns:
        Centroid embedding or None
    """
    chunk_ids = []
    for span in topic["spans"]:
        chunk_ids.extend(span["chunk_ids"])

    vectors = []
    for cid in chunk_ids:
        if cid in embeddings:
            vectors.append(embeddings[cid][0])

    if not vectors:
        return None

    centroid = np.mean(vectors, axis=0)
    # L2 normalize for cosine similarity
    norm = np.linalg.norm(centroid)
    if norm > 0:
        centroid = centroid / norm

    return centroid


def explain_chunk_command(
    project_path: Path, chunk_id: str, top_n: int = 3,
) -> Optional[dict]:
    """
    Explain why a chunk belongs to its assigned topic.

    Shows the chunk text, its assigned topic, and the top-N most similar
    chunks/topics by cosine similarity.

    Args:
        project_path: Path to the project directory
        chunk_id: Chunk ID to explain (e.g., 'chunk_0042')
        top_n: Number of nearest neighbors to show

    Returns:
        Explanation dict or None if failed
    """
    # Validate project directory
    error = validate_project_path(project_path)
    if error:
        console.print(f"[red]Error: {error}[/red]")
        return None

    # Check for embeddings database
    db_path = project_path / "embeddings.sqlite"
    if not db_path.exists():
        console.print(f"[red]Error: Embeddings database not found: {db_path}[/red]")
        return None

    # Check for topic_map.json (try labeled first, then unlabeled)
    labeled_path = project_path / "topic_map_labeled.json"
    unlabeled_path = project_path / "topic_map.json"

    if labeled_path.exists():
        topic_map_path = labeled_path
    elif unlabeled_path.exists():
        topic_map_path = unlabeled_path
    else:
        console.print(f"[red]Error: Topic map not found in {project_path}[/red]")
        console.print("Run 'videotool topics' first to create topic map.")
        return None

    # Load all embeddings
    console.print("[cyan]Loading embeddings...[/cyan]")
    all_embeddings = load_all_embeddings(db_path)

    if chunk_id not in all_embeddings:
        console.print(f"[red]Error: Chunk '{chunk_id}' not found[/red]")
        # Show available chunk IDs
        chunk_ids = sorted(all_embeddings.keys())
        console.print(f"\nAvailable chunks: {chunk_ids[0]} ... {chunk_ids[-1]}")
        console.print(f"Total: {len(chunk_ids)} chunks")
        return None

    # Load topic map
    topics = safe_read_json(topic_map_path)
    if topics is None:
        return None

    # Get target chunk info
    target_embedding, target_meta = all_embeddings[chunk_id]

    # Find assigned topic
    assigned_topic = find_chunk_topic(topics, chunk_id)

    # Compute similarities to all other chunks
    chunk_similarities = []
    for other_id, (other_embedding, other_meta) in all_embeddings.items():
        if other_id != chunk_id:
            sim = cosine_similarity(target_embedding, other_embedding)
            chunk_similarities.append((other_id, sim, other_meta))

    # Sort by similarity (descending)
    chunk_similarities.sort(key=lambda x: x[1], reverse=True)
    top_chunks = chunk_similarities[:top_n]

    # Compute similarities to all topic centroids
    topic_similarities = []
    for topic in topics:
        centroid = compute_topic_centroid(topic, all_embeddings)
        if centroid is not None:
            sim = cosine_similarity(target_embedding, centroid)
            topic_similarities.append((topic, sim))

    # Sort by similarity (descending)
    topic_similarities.sort(key=lambda x: x[1], reverse=True)
    top_topics = topic_similarities[:top_n]

    # Display results
    console.print(f"\n[bold cyan]Chunk: {chunk_id}[/bold cyan]")
    console.print(
        f"[dim]Time: {format_timestamp(target_meta['start'])} – "
        f"{format_timestamp(target_meta['end'])}[/dim]",
    )
    if target_meta.get("speaker"):
        console.print(f"[dim]Speaker: {target_meta['speaker']}[/dim]")

    console.print("\n[bold]Text:[/bold]")
    console.print(f"  \"{target_meta['text']}\"")

    # Assigned topic
    console.print("\n[bold]Assigned Topic:[/bold]")
    if assigned_topic:
        topic_label = assigned_topic.get("label", assigned_topic["topic_id"])
        # Find similarity to assigned topic
        assigned_centroid = compute_topic_centroid(assigned_topic, all_embeddings)
        if assigned_centroid is not None:
            assigned_sim = cosine_similarity(target_embedding, assigned_centroid)
            console.print(
                f"  {assigned_topic['topic_id']} ({topic_label}) — "
                f"similarity: {assigned_sim:.3f}",
            )
        else:
            console.print(f"  {assigned_topic['topic_id']} ({topic_label})")
    else:
        console.print("  [yellow]Not assigned to any topic[/yellow]")

    # Top-N nearest chunks
    console.print(f"\n[bold]Top {top_n} Nearest Chunks (by cosine similarity):[/bold]")
    chunk_table = Table(show_header=True, header_style="bold magenta")
    chunk_table.add_column("Chunk", width=12)
    chunk_table.add_column("Similarity", justify="right", width=10)
    chunk_table.add_column("Topic", width=12)
    chunk_table.add_column("Time", width=15)
    chunk_table.add_column("Text Preview", width=50)

    for other_id, sim, other_meta in top_chunks:
        other_topic = find_chunk_topic(topics, other_id)
        topic_str = other_topic["topic_id"] if other_topic else "—"

        # Highlight if same topic
        if assigned_topic and other_topic and other_topic["topic_id"] == assigned_topic["topic_id"]:
            topic_str = f"[green]{topic_str}[/green]"

        time_str = (
            f"{format_timestamp(other_meta['start'])}–{format_timestamp(other_meta['end'])}"
        )
        text_preview = (
            other_meta["text"][:47] + "..."
            if len(other_meta["text"]) > 50
            else other_meta["text"]
        )

        chunk_table.add_row(other_id, f"{sim:.3f}", topic_str, time_str, text_preview)

    console.print(chunk_table)

    # Top-N nearest topics
    console.print(f"\n[bold]Top {top_n} Nearest Topics (by centroid similarity):[/bold]")
    topic_table = Table(show_header=True, header_style="bold magenta")
    topic_table.add_column("Topic", width=12)
    topic_table.add_column("Similarity", justify="right", width=10)
    topic_table.add_column("Label", width=20)
    topic_table.add_column("Match", width=8)

    for topic, sim in top_topics:
        topic_label = topic.get("label", "—")
        is_assigned = (
            assigned_topic and topic["topic_id"] == assigned_topic["topic_id"]
        )
        match_str = "[green]✓[/green]" if is_assigned else ""

        topic_table.add_row(topic["topic_id"], f"{sim:.3f}", topic_label, match_str)

    console.print(topic_table)

    # Analysis
    console.print("\n[bold]Analysis:[/bold]")

    if assigned_topic:
        # Check if assigned topic is the most similar
        if top_topics and top_topics[0][0]["topic_id"] == assigned_topic["topic_id"]:
            console.print(
                "  [green]✓ Chunk is assigned to its most similar topic[/green]",
            )
        else:
            # Find rank of assigned topic
            for rank, (topic, _sim) in enumerate(topic_similarities):
                if topic["topic_id"] == assigned_topic["topic_id"]:
                    console.print(
                        f"  [yellow]Assigned topic ranks #{rank + 1} by similarity[/yellow]",
                    )
                    if top_topics:
                        console.print(
                            f"  [dim]Most similar topic: {top_topics[0][0]['topic_id']} "
                            f"(sim: {top_topics[0][1]:.3f})[/dim]",
                        )
                    break

        # Check how many nearest chunks share the same topic
        same_topic_count = sum(
            1
            for other_id, _, _ in top_chunks
            if find_chunk_topic(topics, other_id)
            and find_chunk_topic(topics, other_id)["topic_id"]
            == assigned_topic["topic_id"]
        )
        console.print(
            f"  {same_topic_count}/{top_n} nearest chunks share the same topic",
        )

    console.print()

    return {
        "chunk_id": chunk_id,
        "chunk_meta": target_meta,
        "assigned_topic": assigned_topic["topic_id"] if assigned_topic else None,
        "top_chunks": [(cid, sim) for cid, sim, _ in top_chunks],
        "top_topics": [(t["topic_id"], sim) for t, sim in top_topics],
    }
