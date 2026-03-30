"""Embedding generation command for videotool."""

import logging
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np
from rich.console import Console

from videotool.embeddings import EmbeddingProvider, get_embedding_provider
from typing import Optional
from videotool.utils.file_utils import safe_read_json
from videotool.utils.pipeline import require_file
from videotool.utils.validation import validate_project_path

console = Console()
logger = logging.getLogger("videotool")

_last_error: Optional[str] = None


def get_last_error() -> Optional[str]:
    """Return the last error message set by embed_chunks."""
    return _last_error


def serialize_vector(vector: list[float]) -> bytes:
    return np.array(vector, dtype=np.float32).tobytes()


def deserialize_vector(blob: bytes, dtype=np.float32) -> np.ndarray:
    return np.frombuffer(blob, dtype=dtype)


def init_embeddings_db(db_path: Path, model_name: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            start REAL NOT NULL,
            end REAL NOT NULL,
            speaker TEXT
        )
        """
    )
    cursor.execute("PRAGMA table_info(chunks)")
    columns = [col[1] for col in cursor.fetchall()]
    if "speaker" not in columns:
        cursor.execute("ALTER TABLE chunks ADD COLUMN speaker TEXT")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS embeddings (
            chunk_id TEXT NOT NULL,
            model TEXT NOT NULL,
            vector BLOB NOT NULL,
            PRIMARY KEY (chunk_id, model),
            FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(model)"
    )
    conn.commit()
    return conn


def get_existing_embeddings(conn: sqlite3.Connection, model_name: str) -> set[str]:
    cursor = conn.cursor()
    cursor.execute("SELECT chunk_id FROM embeddings WHERE model = ?", (model_name,))
    return {row[0] for row in cursor.fetchall()}


def embed_chunks(
    project_path: Path,
    provider: str = "openai",
    model_name: Optional[str] = None,
) -> Optional[Path]:
    """
    Generate embeddings for transcript chunks.

    Args:
        project_path: Path to the project directory
        provider: Embedding provider — "openai" (default) or "local"
        model_name: Optional model override

    Returns:
        Path to embeddings.sqlite, or None on failure
    """
    global _last_error
    _last_error = None

    error = validate_project_path(project_path)
    if error:
        _last_error = error
        console.print(f"[red]Error: {error}[/red]")
        return None

    chunks_path = require_file(project_path, "chunks.json", stage_name="chunks")
    if chunks_path is None:
        _last_error = "chunks.json not found — run 'videotool chunks' first"
        return None

    chunks = safe_read_json(chunks_path)
    if not chunks:
        _last_error = "No chunks found in chunks.json"
        console.print("[yellow]Warning: No chunks found[/yellow]")
        return None

    logger.info(f"Loaded {len(chunks)} chunks")

    try:
        embedding_provider: EmbeddingProvider = get_embedding_provider(provider, model_name)
    except (ValueError, ImportError) as e:
        _last_error = str(e)
        console.print(f"[red]Error: {e}[/red]")
        return None

    effective_model = embedding_provider.model_name
    db_path = project_path / "embeddings.sqlite"

    try:
        conn = init_embeddings_db(db_path, effective_model)
    except Exception as e:
        _last_error = f"Error initializing embeddings database: {e}"
        console.print(f"[red]Error initializing database: {e}[/red]")
        return None

    existing_chunk_ids = get_existing_embeddings(conn, effective_model)
    chunks_to_embed = [c for c in chunks if c["id"] not in existing_chunk_ids]

    if not chunks_to_embed:
        console.print("[green]All chunks already have embeddings for this model[/green]")
        console.print(f"[bold]Database:[/bold] {db_path}")
        conn.close()
        return db_path

    console.print(f"[cyan]Computing embeddings for {len(chunks_to_embed)} chunks...[/cyan]")
    console.print(f"[dim]Provider: {provider} / Model: {effective_model}[/dim]")
    console.print(f"[dim]Skipping {len(existing_chunk_ids)} existing embeddings[/dim]")

    try:
        texts = [c["text"] for c in chunks_to_embed]
        vectors = embedding_provider.embed(texts)
        logger.info(f"Generated {len(vectors)} embeddings")
    except Exception as e:
        _last_error = f"Error generating embeddings: {e}"
        console.print(f"[red]Error generating embeddings: {e}[/red]")
        conn.close()
        return None

    cursor = conn.cursor()
    try:
        for chunk in chunks_to_embed:
            cursor.execute(
                "INSERT OR IGNORE INTO chunks (chunk_id, text, start, end, speaker) VALUES (?, ?, ?, ?, ?)",
                (chunk["id"], chunk["text"], chunk["start"], chunk["end"], chunk.get("speaker", "UNKNOWN")),
            )
        for chunk, vector in zip(chunks_to_embed, vectors):
            cursor.execute(
                "INSERT OR REPLACE INTO embeddings (chunk_id, model, vector) VALUES (?, ?, ?)",
                (chunk["id"], effective_model, serialize_vector(vector)),
            )
        conn.commit()
    except Exception as e:
        _last_error = f"Error storing embeddings: {e}"
        console.print(f"[red]Error storing embeddings: {e}[/red]")
        conn.rollback()
        conn.close()
        return None

    conn.close()

    total = len(existing_chunk_ids) + len(chunks_to_embed)
    embedding_dim = len(vectors[0]) if vectors else 0
    console.print("\n[green]✓ Embedding complete![/green]")
    console.print(f"[bold]Total chunks:[/bold] {len(chunks)}")
    console.print(f"[bold]New embeddings:[/bold] {len(chunks_to_embed)}")
    console.print(f"[bold]Existing embeddings:[/bold] {len(existing_chunk_ids)}")
    console.print(f"[bold]Total embeddings:[/bold] {total}")
    console.print(f"[bold]Embedding dimension:[/bold] {embedding_dim}")
    console.print(f"[bold]Model:[/bold] {effective_model}")
    console.print(f"[bold]Database:[/bold] {db_path}")

    return db_path
