"""Topic segmentation command for vodtool using embedding similarity."""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np
from rich.console import Console
from sklearn.metrics.pairwise import cosine_similarity
from vodtool.utils.validation import validate_project_path

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


def load_embeddings_from_db(
    db_path: Path, model_name: str, filter_main_speakers: bool = True,
) -> tuple[list[str], np.ndarray]:
    """
    Load embeddings from SQLite database.

    Args:
        db_path: Path to embeddings.sqlite
        model_name: Name of the model to load embeddings for
        filter_main_speakers: If True, only load chunks from MAIN speakers (default: True)

    Returns:
        Tuple of (chunk_ids, embeddings_matrix)
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if speaker column exists in chunks table
    cursor.execute("PRAGMA table_info(chunks)")
    columns = [col[1] for col in cursor.fetchall()]
    has_speaker = "speaker" in columns

    if filter_main_speakers and has_speaker:
        # Load embeddings for MAIN speakers only (exclude OTHER and BACKGROUND)
        cursor.execute(
            """
            SELECT e.chunk_id, e.vector
            FROM embeddings e
            JOIN chunks c ON e.chunk_id = c.chunk_id
            WHERE e.model = ?
              AND c.speaker NOT IN ('OTHER', 'BACKGROUND')
            ORDER BY c.start
            """,
            (model_name,),
        )
    else:
        # Load all embeddings, ordered by start time
        cursor.execute(
            """
            SELECT e.chunk_id, e.vector
            FROM embeddings e
            JOIN chunks c ON e.chunk_id = c.chunk_id
            WHERE e.model = ?
            ORDER BY c.start
            """,
            (model_name,),
        )

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return [], np.array([])

    chunk_ids = [row[0] for row in rows]
    embeddings = np.array([deserialize_vector(row[1]) for row in rows])

    return chunk_ids, embeddings


def detect_topic_boundaries(embeddings: np.ndarray, percentile: float = 25.0) -> list[int]:
    """
    Detect topic boundaries using cosine similarity drops.

    Args:
        embeddings: Matrix of embeddings (n_chunks, embedding_dim)
        percentile: Percentile threshold for similarity drops (lower = more boundaries)

    Returns:
        List of boundary indices (chunk positions where new segments start)
    """
    if len(embeddings) < 2:
        return [0]

    # Compute cosine similarity between consecutive chunks
    similarities = []
    for i in range(len(embeddings) - 1):
        sim = cosine_similarity(embeddings[i : i + 1], embeddings[i + 1 : i + 2])[0][0]
        similarities.append(sim)

    similarities = np.array(similarities)

    # Find threshold using percentile
    threshold = np.percentile(similarities, percentile)
    logger.info(f"Similarity threshold ({percentile}th percentile): {threshold:.4f}")

    # Boundaries where similarity drops below threshold
    boundaries = [0]  # Always start with first chunk
    for i, sim in enumerate(similarities):
        if sim < threshold:
            boundaries.append(i + 1)

    logger.info(f"Detected {len(boundaries)} initial boundaries")

    return boundaries


def merge_segments_to_max(segments: list[dict], max_segments: int) -> list[dict]:
    """
    Merge segments until count <= max_segments.

    Merges adjacent segments with highest similarity first.

    Args:
        segments: List of segments with chunk_ids, embeddings
        max_segments: Maximum number of segments to keep

    Returns:
        Merged segments list
    """
    if len(segments) <= max_segments:
        return segments

    logger.info(f"Merging {len(segments)} segments down to {max_segments} max")

    # Create working copy
    working_segments = [seg.copy() for seg in segments]

    while len(working_segments) > max_segments:
        # Compute similarities between adjacent segments
        similarities = []
        for i in range(len(working_segments) - 1):
            # Compute centroid similarity
            emb1 = working_segments[i]["embeddings"]
            emb2 = working_segments[i + 1]["embeddings"]

            centroid1 = np.mean(emb1, axis=0, keepdims=True)
            centroid2 = np.mean(emb2, axis=0, keepdims=True)

            sim = cosine_similarity(centroid1, centroid2)[0][0]
            similarities.append(sim)

        # Find most similar adjacent pair
        max_sim_idx = np.argmax(similarities)

        # Merge the pair
        seg1 = working_segments[max_sim_idx]
        seg2 = working_segments[max_sim_idx + 1]

        merged = {
            "chunk_ids": seg1["chunk_ids"] + seg2["chunk_ids"],
            "embeddings": np.vstack([seg1["embeddings"], seg2["embeddings"]]),
        }

        # Replace with merged segment
        working_segments = (
            working_segments[:max_sim_idx] + [merged] + working_segments[max_sim_idx + 2 :]
        )

    logger.info(f"Final segment count: {len(working_segments)}")

    return working_segments


def create_segment_metadata(
    segments: list[dict],
    chunk_ids_all: list[str],
    db_path: Path,
) -> list[dict]:
    """
    Create segment metadata with start/end times.

    Args:
        segments: List of segments with chunk_ids
        chunk_ids_all: All chunk IDs in order
        db_path: Path to embeddings database

    Returns:
        List of segment dicts with id, start, end, chunk_ids
    """
    # Load chunk times from database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT chunk_id, start, end FROM chunks ORDER BY start")
    chunk_times = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
    conn.close()

    # Build segment metadata
    output_segments = []

    for i, seg in enumerate(segments):
        chunk_ids = seg["chunk_ids"]

        # Get time range
        start_time = chunk_times[chunk_ids[0]][0]
        end_time = chunk_times[chunk_ids[-1]][1]

        output_segments.append(
            {
                "segment_id": f"seg_{i:04d}",
                "start": start_time,
                "end": end_time,
                "chunk_ids": chunk_ids,
            },
        )

    return output_segments


def segment_topics(project_path: Path, max_topics: int = 8) -> Optional[Path]:
    """
    Detect topic boundaries using embedding similarity.

    Args:
        project_path: Path to the project directory
        max_topics: Maximum number of topic segments

    Returns:
        Path to the topic_segments.json file, or None if segmentation failed
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
        console.print("Run 'vodtool embed' first to generate embeddings.")
        return None

    # Determine model name (use first available)
    console.print("[cyan]Loading embeddings...[/cyan]")

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

    # Load embeddings (filter to MAIN speakers by default)
    chunk_ids, embeddings = load_embeddings_from_db(db_path, model_name, filter_main_speakers=True)

    if len(chunk_ids) == 0:
        console.print("[yellow]Warning: No embeddings found[/yellow]")
        return None

    logger.info(f"Loaded {len(chunk_ids)} embeddings (MAIN speakers only)")
    console.print(f"[cyan]Loaded {len(chunk_ids)} chunks from MAIN speakers[/cyan]")

    # Detect boundaries
    console.print(f"[cyan]Detecting topic boundaries (max {max_topics} segments)...[/cyan]")

    boundaries = detect_topic_boundaries(embeddings, percentile=25.0)

    # Create initial segments
    segments = []
    for i, boundary_idx in enumerate(boundaries):
        # Determine end of this segment
        end_idx = boundaries[i + 1] if i + 1 < len(boundaries) else len(chunk_ids)

        segments.append(
            {
                "chunk_ids": chunk_ids[boundary_idx:end_idx],
                "embeddings": embeddings[boundary_idx:end_idx],
            },
        )

    logger.info(f"Initial segments: {len(segments)}")

    # Merge if necessary
    if len(segments) > max_topics:
        segments = merge_segments_to_max(segments, max_topics)

    # Create output metadata
    console.print("[cyan]Creating segment metadata...[/cyan]")
    output_segments = create_segment_metadata(segments, chunk_ids, db_path)

    # Save topic_segments.json
    output_path = project_path / "topic_segments.json"

    try:
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(output_segments, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved topic_segments.json: {output_path}")
    except Exception as e:
        console.print(f"[red]Error saving segments: {e}[/red]")
        return None

    # Validation
    all_chunks_in_segments = set()
    for seg in output_segments:
        all_chunks_in_segments.update(seg["chunk_ids"])

    if len(all_chunks_in_segments) != len(chunk_ids):
        console.print("[yellow]Warning: Not all chunks covered by segments[/yellow]")
        logger.warning(
            f"Chunks in segments: {len(all_chunks_in_segments)}, Total chunks: {len(chunk_ids)}",
        )

    # Print summary
    total_duration = output_segments[-1]["end"] - output_segments[0]["start"]
    avg_duration = total_duration / len(output_segments)

    console.print("\n[green]✓ Segmentation complete![/green]")
    console.print(f"[bold]Segments:[/bold] {len(output_segments)}")
    console.print(
        f"[bold]Total duration:[/bold] {total_duration:.1f}s ({total_duration/60:.1f} min)",
    )
    console.print(f"[bold]Average segment:[/bold] {avg_duration:.1f}s")
    console.print(f"[bold]Output:[/bold] {output_path}")

    return output_path
