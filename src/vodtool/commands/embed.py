"""Embedding generation command for vodtool using sentence-transformers."""

import logging
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np
from rich.console import Console

from vodtool.utils.file_utils import safe_read_json
from vodtool.utils.pipeline import require_file
from vodtool.utils.validation import validate_project_path

console = Console()
logger = logging.getLogger("vodtool")


def serialize_vector(vector: np.ndarray) -> bytes:
    """
    Serialize numpy vector to bytes for SQLite storage.

    Args:
        vector: Numpy array to serialize

    Returns:
        Serialized bytes
    """
    return vector.tobytes()


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


def check_sentence_transformers_available() -> bool:
    """Check if sentence-transformers is installed and accessible."""
    try:
        import sentence_transformers  # noqa: F401

        return True
    except ImportError:
        return False


def init_embeddings_db(db_path: Path, model_name: str) -> sqlite3.Connection:
    """
    Initialize embeddings database with schema.

    Args:
        db_path: Path to SQLite database file
        model_name: Name of the embedding model (for metadata)

    Returns:
        SQLite connection
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create chunks table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            start REAL NOT NULL,
            end REAL NOT NULL,
            speaker TEXT
        )
    """,
    )

    # Check if speaker column exists, add it if not (for backwards compatibility)
    cursor.execute("PRAGMA table_info(chunks)")
    columns = [col[1] for col in cursor.fetchall()]
    if "speaker" not in columns:
        cursor.execute("ALTER TABLE chunks ADD COLUMN speaker TEXT")

    # Create embeddings table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS embeddings (
            chunk_id TEXT NOT NULL,
            model TEXT NOT NULL,
            vector BLOB NOT NULL,
            PRIMARY KEY (chunk_id, model),
            FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id)
        )
    """,
    )

    # Create index for faster lookups
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_embeddings_model
        ON embeddings(model)
    """,
    )

    conn.commit()
    return conn


def get_existing_embeddings(conn: sqlite3.Connection, model_name: str) -> set[str]:
    """
    Get set of chunk IDs that already have embeddings for this model.

    Args:
        conn: SQLite connection
        model_name: Name of the embedding model

    Returns:
        Set of chunk IDs with existing embeddings
    """
    cursor = conn.cursor()
    cursor.execute("SELECT chunk_id FROM embeddings WHERE model = ?", (model_name,))
    return {row[0] for row in cursor.fetchall()}


def embed_chunks(
    project_path: Path,
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
) -> Optional[Path]:
    """
    Generate embeddings for transcript chunks using sentence-transformers.

    Args:
        project_path: Path to the project directory
        model_name: Sentence transformer model to use

    Returns:
        Path to the embeddings.sqlite file, or None if embedding failed
    """
    # Check sentence-transformers availability
    if not check_sentence_transformers_available():
        console.print("[red]Error: sentence-transformers is not installed[/red]")
        console.print("\nPlease install sentence-transformers:")
        console.print("  pip install -U sentence-transformers")
        return None

    # Validate project directory
    error = validate_project_path(project_path)
    if error:
        console.print(f"[red]Error: {error}[/red]")
        return None

    # Check for chunks.json
    chunks_path = require_file(project_path, "chunks.json", stage_name="chunks")
    if chunks_path is None:
        return None

    # Load chunks
    console.print("[cyan]Loading chunks...[/cyan]")
    chunks = safe_read_json(chunks_path)
    if chunks is None:
        return None

    if not chunks:
        console.print("[yellow]Warning: No chunks found[/yellow]")
        return None

    logger.info(f"Loaded {len(chunks)} chunks")

    # Initialize database
    db_path = project_path / "embeddings.sqlite"
    console.print("[cyan]Initializing embeddings database...[/cyan]")

    try:
        conn = init_embeddings_db(db_path, model_name)
    except Exception as e:
        console.print(f"[red]Error initializing database: {e}[/red]")
        return None

    # Get existing embeddings to skip
    existing_chunk_ids = get_existing_embeddings(conn, model_name)
    logger.info(f"Found {len(existing_chunk_ids)} existing embeddings for model {model_name}")

    # Filter chunks that need embedding
    chunks_to_embed = [c for c in chunks if c["id"] not in existing_chunk_ids]

    if not chunks_to_embed:
        console.print("[green]All chunks already have embeddings for this model[/green]")
        console.print(f"[bold]Database:[/bold] {db_path}")
        conn.close()
        return db_path

    console.print(f"[cyan]Computing embeddings for {len(chunks_to_embed)} chunks...[/cyan]")
    console.print(f"[dim]Model: {model_name}[/dim]")
    console.print(f"[dim]Skipping {len(existing_chunk_ids)} existing embeddings[/dim]")

    # Import sentence-transformers here (after checking it's available)
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        console.print(f"[red]Error importing sentence-transformers: {e}[/red]")
        conn.close()
        return None

    # Load model
    console.print("[cyan]Loading sentence transformer model...[/cyan]")
    console.print("[dim]Note: First run will download the model (this may take a while)[/dim]")

    try:
        model = SentenceTransformer(model_name)
        logger.info(f"Loaded model: {model_name}")
    except Exception as e:
        console.print(f"[red]Error loading model: {e}[/red]")
        conn.close()
        return None

    # Generate embeddings
    try:
        texts = [c["text"] for c in chunks_to_embed]
        embeddings = model.encode(texts, show_progress_bar=True)
        logger.info(f"Generated {len(embeddings)} embeddings")
    except Exception as e:
        console.print(f"[red]Error generating embeddings: {e}[/red]")
        conn.close()
        return None

    # Store in database
    console.print("[cyan]Storing embeddings in database...[/cyan]")

    cursor = conn.cursor()

    try:
        # Insert chunks (insert or ignore if already exists)
        for chunk in chunks_to_embed:
            speaker = chunk.get("speaker", "UNKNOWN")
            cursor.execute(
                """
                INSERT OR IGNORE INTO chunks (chunk_id, text, start, end, speaker)
                VALUES (?, ?, ?, ?, ?)
                """,
                (chunk["id"], chunk["text"], chunk["start"], chunk["end"], speaker),
            )

        # Insert embeddings
        for chunk, embedding in zip(chunks_to_embed, embeddings):
            vector_blob = serialize_vector(embedding)
            cursor.execute(
                """
                INSERT OR REPLACE INTO embeddings (chunk_id, model, vector)
                VALUES (?, ?, ?)
                """,
                (chunk["id"], model_name, vector_blob),
            )

        conn.commit()
        logger.info("Stored embeddings in database")
    except Exception as e:
        console.print(f"[red]Error storing embeddings: {e}[/red]")
        conn.rollback()
        conn.close()
        return None

    conn.close()

    # Print summary
    total_embeddings = len(existing_chunk_ids) + len(chunks_to_embed)
    embedding_dim = embeddings[0].shape[0]

    console.print("\n[green]✓ Embedding complete![/green]")
    console.print(f"[bold]Total chunks:[/bold] {len(chunks)}")
    console.print(f"[bold]New embeddings:[/bold] {len(chunks_to_embed)}")
    console.print(f"[bold]Existing embeddings:[/bold] {len(existing_chunk_ids)}")
    console.print(f"[bold]Total embeddings:[/bold] {total_embeddings}")
    console.print(f"[bold]Embedding dimension:[/bold] {embedding_dim}")
    console.print(f"[bold]Model:[/bold] {model_name}")
    console.print(f"[bold]Database:[/bold] {db_path}")

    return db_path
