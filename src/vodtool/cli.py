"""Main CLI interface for VodTool."""

import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from vodtool import __version__
from vodtool.commands.chunks import create_chunks
from vodtool.commands.cutplan import generate_cutplan
from vodtool.commands.diarize import diarize_command
from vodtool.commands.diarize_review import diarize_review_command
from vodtool.commands.embed import embed_chunks
from vodtool.commands.export import export_video
from vodtool.commands.ingest import ingest_video
from vodtool.commands.label_topics import label_topics_command
from vodtool.commands.segment_topics import segment_topics
from vodtool.commands.topics import cluster_topics
from vodtool.commands.transcribe import transcribe_audio

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
        None,
        "--version",
        "-v",
        callback=version_callback,
        help="Show version and exit",
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logging"),
    ffmpeg_path: Optional[str] = typer.Option(
        None,
        "--ffmpeg-path",
        help="Path to ffmpeg binary (default: 'ffmpeg' in PATH)",
        envvar="VODTOOL_FFMPEG_PATH",
    ),
):
    """VodTool: Extract topic-focused videos from long multi-topic streams."""
    if verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled")

    # Store ffmpeg_path in app context for commands to access
    app.state = {"ffmpeg_path": ffmpeg_path or "ffmpeg"}


@app.command()
def ingest(
    input_video_path: Path = typer.Argument(..., help="Path to input video file"),
):
    """
    Ingest a video file and create a new project.

    Creates a project folder with extracted audio and metadata.
    """
    ffmpeg_path = app.state.get("ffmpeg_path", "ffmpeg")
    project_dir = ingest_video(input_video_path, ffmpeg_path)
    if project_dir is None:
        raise typer.Exit(code=1)


@app.command()
def transcribe(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    model: str = typer.Option("small", "--model", help="Whisper model size"),
    language: Optional[str] = typer.Option(
        None,
        "--language",
        help="Language code (e.g., 'en', 'fr', 'es'). Auto-detect if not specified.",
    ),
    force: bool = typer.Option(False, "--force", help="Force re-transcription"),
):
    """
    Transcribe audio using OpenAI Whisper.

    Generates timestamped transcript from project audio.
    """
    transcript_path = transcribe_audio(project_path, model, force, language)
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
    topic_map_path = cluster_topics(project_path, max_topics)
    if topic_map_path is None:
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
    labeled_path = label_topics_command(project_path, force)
    if labeled_path is None:
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
    cutplan_path = generate_cutplan(project_path, topic)
    if cutplan_path is None:
        raise typer.Exit(code=1)


@app.command()
def diarize(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    num_main: int = typer.Option(
        2, "--num-main", help="Number of main speakers to identify"
    ),
):
    """
    Perform speaker diarization on project audio.

    Identifies speakers and maps top N speakers to MAIN_1, MAIN_2, etc.
    """
    diarize_command(project_path, num_main)


@app.command(name="diarize-review")
def diarize_review(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
):
    """
    Review and reclassify speakers after diarization.

    Displays speaker statistics and allows marking speakers as BACKGROUND.
    """
    diarize_review_command(project_path)


@app.command()
def export(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
):
    """
    Export video based on cut plan.

    Generates final topic-focused video with preview.
    """
    ffmpeg_path = app.state.get("ffmpeg_path", "ffmpeg")
    export_path = export_video(project_path, ffmpeg_path)
    if export_path is None:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
