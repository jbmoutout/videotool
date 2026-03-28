"""Topic clustering command for vodtool using agglomerative clustering."""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np
from rich.console import Console

from vodtool.utils.file_utils import safe_read_json
from vodtool.utils.validation import validate_project_path
from sklearn.cluster import AgglomerativeClustering

console = Console()
logger = logging.getLogger("vodtool")


def deserialize_vector(blob: bytes, dtype=np.float32) -> np.ndarray:
    """
    Deserialize bytes back to numpy vector.

    Args:
        blob: Serialized bytes from SQLite
        dtype: Data type of the array

    Returns:
        Numpy array
    """
    return np.frombuffer(blob, dtype=dtype)


def load_embeddings_for_chunks(db_path: Path, chunk_ids: list[str], model_name: str) -> np.ndarray:
    """
    Load embeddings for specific chunks from database.

    Args:
        db_path: Path to embeddings.sqlite
        chunk_ids: List of chunk IDs to load
        model_name: Name of the model

    Returns:
        Numpy array of embeddings
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Build query with placeholders
    placeholders = ",".join("?" * len(chunk_ids))
    query = f"""
        SELECT chunk_id, vector
        FROM embeddings
        WHERE chunk_id IN ({placeholders}) AND model = ?
    """

    cursor.execute(query, chunk_ids + [model_name])
    rows = cursor.fetchall()
    conn.close()

    # Build dict for ordered retrieval
    embeddings_dict = {row[0]: deserialize_vector(row[1]) for row in rows}

    # Return in same order as chunk_ids
    return np.array([embeddings_dict[cid] for cid in chunk_ids])


def compute_segment_centroids(segments: list[dict], db_path: Path, model_name: str) -> np.ndarray:
    """
    Compute centroid embeddings for each segment.

    Args:
        segments: List of segments with chunk_ids
        db_path: Path to embeddings database
        model_name: Model name for embeddings

    Returns:
        Matrix of centroid embeddings (n_segments, embedding_dim)
    """
    centroids = []

    for seg in segments:
        chunk_ids = seg["chunk_ids"]

        # Load embeddings for this segment's chunks
        embeddings = load_embeddings_for_chunks(db_path, chunk_ids, model_name)

        # Compute mean (centroid)
        centroid = np.mean(embeddings, axis=0)

        # L2 normalize for cosine space
        centroid = centroid / np.linalg.norm(centroid)

        centroids.append(centroid)

    return np.array(centroids)


def cluster_segments(centroids: np.ndarray, max_topics: int, random_state: int = 42) -> np.ndarray:
    """
    Cluster segment centroids using agglomerative clustering.

    Args:
        centroids: Matrix of centroid embeddings
        max_topics: Maximum number of clusters
        random_state: Random seed for reproducibility

    Returns:
        Cluster labels for each segment
    """
    n_segments = len(centroids)
    n_clusters = min(max_topics, n_segments)

    logger.info(f"Clustering {n_segments} segments into {n_clusters} topics")

    clustering = AgglomerativeClustering(
        n_clusters=n_clusters,
        metric="cosine",
        linkage="average",
    )

    return clustering.fit_predict(centroids)


def build_topic_map(segments: list[dict], labels: np.ndarray, db_path: Path) -> list[dict]:
    """
    Build topic map from cluster labels.

    Args:
        segments: List of segments with metadata
        labels: Cluster label for each segment
        db_path: Path to embeddings database for chunk metadata

    Returns:
        List of topics with spans
    """
    # Group segments by cluster
    topics_dict = {}

    for seg, label in zip(segments, labels):
        label = int(label)  # Convert numpy int to Python int

        if label not in topics_dict:
            topics_dict[label] = []

        topics_dict[label].append(seg)

    # Build output structure
    topics = []

    for topic_idx, (_label, topic_segments) in enumerate(sorted(topics_dict.items())):
        # Sort segments within topic by time
        topic_segments = sorted(topic_segments, key=lambda s: s["start"])

        # Build spans (each segment becomes a span)
        spans = []
        for seg in topic_segments:
            spans.append(
                {
                    "start": seg["start"],
                    "end": seg["end"],
                    "chunk_ids": seg["chunk_ids"],
                    "segment_ids": [seg["segment_id"]],
                },
            )

        topics.append(
            {
                "topic_id": f"topic_{topic_idx:04d}",
                "label_stub": "",  # To be filled by label-topics command
                "spans": spans,
            },
        )

    return topics


def cluster_topics(project_path: Path, max_topics: int = 8) -> Optional[Path]:
    """
    Cluster segments into topics using agglomerative clustering.

    Args:
        project_path: Path to the project directory
        max_topics: Maximum number of topics

    Returns:
        Path to the topic_map.json file, or None if clustering failed
    """
    # Validate project directory
    error = validate_project_path(project_path)
    if error:
        console.print(f"[red]Error: {error}[/red]")
        return None

    # Check for topic_segments.json
    segments_path = project_path / "topic_segments.json"
    if not segments_path.exists():
        console.print(f"[red]Error: Topic segments not found: {segments_path}[/red]")
        console.print("Run 'vodtool segment-topics' first to create segments.")
        return None

    # Check for embeddings database
    db_path = project_path / "embeddings.sqlite"
    if not db_path.exists():
        console.print(f"[red]Error: Embeddings database not found: {db_path}[/red]")
        return None

    # Load segments
    console.print("[cyan]Loading topic segments...[/cyan]")

    segments = safe_read_json(segments_path)
    if segments is None:
        return None

    if not segments:
        console.print("[yellow]Warning: No segments found[/yellow]")
        return None

    logger.info(f"Loaded {len(segments)} segments")

    # Determine model name
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT model FROM embeddings LIMIT 1")
    result = cursor.fetchone()
    conn.close()

    if not result:
        console.print("[red]Error: No embeddings found in database[/red]")
        return None

    model_name = result[0]
    logger.info(f"Using embeddings from model: {model_name}")

    # Compute segment centroids
    console.print("[cyan]Computing segment centroids...[/cyan]")

    try:
        centroids = compute_segment_centroids(segments, db_path, model_name)
        logger.info(f"Computed {len(centroids)} centroids")
    except Exception as e:
        console.print(f"[red]Error computing centroids: {e}[/red]")
        return None

    # Cluster segments
    console.print(f"[cyan]Clustering segments into topics (max {max_topics})...[/cyan]")

    try:
        labels = cluster_segments(centroids, max_topics)
        logger.info("Clustering complete")
    except Exception as e:
        console.print(f"[red]Error clustering segments: {e}[/red]")
        return None

    # Build topic map
    console.print("[cyan]Building topic map...[/cyan]")

    try:
        topics = build_topic_map(segments, labels, db_path)
        logger.info(f"Created {len(topics)} topics")
    except Exception as e:
        console.print(f"[red]Error building topic map: {e}[/red]")
        return None

    # Save topic_map.json
    output_path = project_path / "topic_map.json"

    try:
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(topics, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved topic_map.json: {output_path}")
    except Exception as e:
        console.print(f"[red]Error saving topic map: {e}[/red]")
        return None

    # Validation: ensure all chunks covered exactly once
    all_chunks = set()
    for topic in topics:
        for span in topic["spans"]:
            all_chunks.update(span["chunk_ids"])

    # Count total chunks from segments
    total_chunks = sum(len(seg["chunk_ids"]) for seg in segments)

    if len(all_chunks) != total_chunks:
        console.print("[yellow]Warning: Not all chunks covered in topic map[/yellow]")
        logger.warning(f"Chunks in topics: {len(all_chunks)}, Total chunks: {total_chunks}")

    # Print summary
    total_spans = sum(len(t["spans"]) for t in topics)
    avg_spans_per_topic = total_spans / len(topics)

    console.print("\n[green]✓ Topic clustering complete![/green]")
    console.print(f"[bold]Topics:[/bold] {len(topics)}")
    console.print(f"[bold]Total spans:[/bold] {total_spans}")
    console.print(f"[bold]Average spans per topic:[/bold] {avg_spans_per_topic:.1f}")
    console.print(f"[bold]Output:[/bold] {output_path}")

    return output_path
