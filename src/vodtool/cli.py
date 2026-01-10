"""Main CLI interface for VodTool."""

import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from vodtool import __version__
from vodtool.commands.ingest import ingest_video
from vodtool.commands.transcribe import transcribe_audio
from vodtool.commands.chunks import create_chunks
from vodtool.commands.embed import embed_chunks
from vodtool.commands.segment_topics import segment_topics

app = typer.Typer(
    name="vodtool",
    help="A transcript-first tool for extracting topic-focused videos from streams",
    add_completion=False,
)
console = Console()
logger = logging.getLogger("vodtool")


def version_callback(value: bool):
    """Print version and exit."""
    if value:
        console.print(f"vodtool version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", callback=version_callback, help="Show version and exit"
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logging"),
):
    """VodTool: Extract topic-focused videos from long multi-topic streams."""
    if verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled")


@app.command()
def ingest(
    input_video_path: Path = typer.Argument(..., help="Path to input video file"),
):
    """
    Ingest a video file and create a new project.

    Creates a project folder with extracted audio and metadata.
    """
    project_dir = ingest_video(input_video_path)
    if project_dir is None:
        raise typer.Exit(code=1)


@app.command()
def transcribe(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    model: str = typer.Option("small", "--model", help="Whisper model size"),
    force: bool = typer.Option(False, "--force", help="Force re-transcription"),
):
    """
    Transcribe audio using OpenAI Whisper.

    Generates timestamped transcript from project audio.
    """
    transcript_path = transcribe_audio(project_path, model, force)
    if transcript_path is None:
        raise typer.Exit(code=1)


@app.command()
def chunks(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
):
    """
    Split transcript into semantic chunks.

    Creates 5-25 second chunks for embedding.
    """
    chunks_path = create_chunks(project_path)
    if chunks_path is None:
        raise typer.Exit(code=1)


@app.command()
def embed(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    model: str = typer.Option(
        "sentence-transformers/all-MiniLM-L6-v2",
        "--model",
        help="Sentence transformer model",
    ),
):
    """
    Generate embeddings for transcript chunks.

    Computes semantic embeddings using sentence-transformers.
    """
    db_path = embed_chunks(project_path, model)
    if db_path is None:
        raise typer.Exit(code=1)


@app.command()
def segment_topics_cmd(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    max_topics: int = typer.Option(8, "--max-topics", help="Maximum number of topic segments"),
):
    """
    Detect topic boundaries using embedding similarity.

    Creates contiguous segments where topic changes occur.
    """
    segments_path = segment_topics(project_path, max_topics)
    if segments_path is None:
        raise typer.Exit(code=1)


@app.command()
def topics(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    max_topics: int = typer.Option(8, "--max-topics", help="Maximum number of topics"),
):
    """
    Cluster segments into topics.

    Groups similar segments across the entire stream.
    """
    console.print("[yellow]Not implemented yet: topics command[/yellow]")
    console.print(f"Would cluster topics for: {project_path}")
    raise typer.Exit(code=1)


@app.command()
def label_topics(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    force: bool = typer.Option(False, "--force", help="Force re-labeling"),
):
    """
    Generate human-readable labels for topics.

    Uses TF-IDF keyword extraction to create topic labels.
    """
    console.print("[yellow]Not implemented yet: label-topics command[/yellow]")
    console.print(f"Would label topics for: {project_path}")
    raise typer.Exit(code=1)


@app.command()
def cutplan(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    topic: str = typer.Option(..., "--topic", help="Topic ID to extract"),
):
    """
    Generate a cut plan for extracting a specific topic.

    Creates keep/drop spans for topic-focused editing (suggest-only).
    """
    console.print("[yellow]Not implemented yet: cutplan command[/yellow]")
    console.print(f"Would create cutplan for: {project_path}, topic: {topic}")
    raise typer.Exit(code=1)


@app.command()
def export(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
):
    """
    Export video based on cut plan.

    Generates final topic-focused video with preview.
    """
    console.print("[yellow]Not implemented yet: export command[/yellow]")
    console.print(f"Would export video for: {project_path}")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
