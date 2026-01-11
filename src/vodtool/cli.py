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
from vodtool.commands.explain_chunk import explain_chunk_command
from vodtool.commands.export import export_video
from vodtool.commands.ingest import ingest_video
from vodtool.commands.inspect_topic import inspect_topic_command
from vodtool.commands.label_topics import label_topics_command
from vodtool.commands.list_topics import list_topics_command
from vodtool.commands.llm_topics import llm_topics
from vodtool.commands.segment_topics import segment_topics
from vodtool.commands.show_topics import show_topics_command
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


@app.command(name="segment-topics")
def segment_topics_cmd(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    max_topics: int = typer.Option(4, "--max-topics", help="Maximum number of topic segments"),
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
    max_topics: int = typer.Option(4, "--max-topics", help="Maximum number of topics"),
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
    source: str = typer.Option(
        "auto",
        "--source",
        help="Topic map source: 'llm', 'labeled', 'basic', or 'auto' (default)",
    ),
):
    """
    Generate a cut plan for extracting a specific topic.

    Creates keep/drop spans for topic-focused editing (suggest-only).

    Source options:
      - auto: Use LLM > labeled > basic (first found)
      - llm: Use topic_map_llm.json (from llm-topics command)
      - labeled: Use topic_map_labeled.json (from label-topics command)
      - basic: Use topic_map.json (from topics command)
    """
    cutplan_path = generate_cutplan(project_path, topic, source)
    if cutplan_path is None:
        raise typer.Exit(code=1)


@app.command()
def diarize(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    num_main: int = typer.Option(2, "--num-main", help="Number of main speakers to identify"),
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


@app.command()
def pipeline(
    input_video_path: Path = typer.Argument(..., help="Path to input video file"),
    whisper_model: str = typer.Option("small", "--whisper-model", help="Whisper model size"),
    language: Optional[str] = typer.Option(
        None, "--language", help="Language code (auto-detect if not specified)",
    ),
    max_topics: int = typer.Option(4, "--max-topics", help="Maximum number of topics"),
    with_diarize: bool = typer.Option(False, "--diarize", help="Include speaker diarization"),
    num_main: int = typer.Option(2, "--num-main", help="Number of main speakers (if diarizing)"),
):
    """
    Run full pipeline: ingest → transcribe → chunks → embed → topics → label.

    One command to process a video from start to labeled topics.
    """
    ffmpeg_path = app.state.get("ffmpeg_path", "ffmpeg")

    # Step 1: Ingest
    console.print("\n[bold cyan]Step 1/8: Ingesting video...[/bold cyan]")
    project_dir = ingest_video(input_video_path, ffmpeg_path)
    if project_dir is None:
        raise typer.Exit(code=1)

    # Step 2: Transcribe
    console.print("\n[bold cyan]Step 2/8: Transcribing audio...[/bold cyan]")
    transcript_path = transcribe_audio(project_dir, whisper_model, False, language)
    if transcript_path is None:
        raise typer.Exit(code=1)

    # Step 3: Diarize (optional)
    if with_diarize:
        console.print("\n[bold cyan]Step 3/8: Diarizing speakers...[/bold cyan]")
        diarize_command(project_dir, num_main)
    else:
        console.print("\n[dim]Step 3/8: Skipping diarization (use --diarize to enable)[/dim]")

    # Step 4: Chunks
    console.print("\n[bold cyan]Step 4/8: Creating semantic chunks...[/bold cyan]")
    chunks_path = create_chunks(project_dir)
    if chunks_path is None:
        raise typer.Exit(code=1)

    # Step 5: Embed
    console.print("\n[bold cyan]Step 5/8: Generating embeddings...[/bold cyan]")
    db_path = embed_chunks(project_dir)
    if db_path is None:
        raise typer.Exit(code=1)

    # Step 6: Segment topics
    console.print("\n[bold cyan]Step 6/8: Detecting topic boundaries...[/bold cyan]")
    segments_path = segment_topics(project_dir, max_topics)
    if segments_path is None:
        raise typer.Exit(code=1)

    # Step 7: Cluster topics
    console.print("\n[bold cyan]Step 7/8: Clustering topics...[/bold cyan]")
    topic_map_path = cluster_topics(project_dir, max_topics)
    if topic_map_path is None:
        raise typer.Exit(code=1)

    # Step 8: Label topics
    console.print("\n[bold cyan]Step 8/8: Labeling topics...[/bold cyan]")
    labeled_path = label_topics_command(project_dir, force=True)
    if labeled_path is None:
        raise typer.Exit(code=1)

    # Summary
    console.print("\n[bold green]✓ Pipeline complete![/bold green]")
    console.print(f"[bold]Project:[/bold] {project_dir}")
    console.print("\n[bold]Next steps:[/bold]")
    console.print(f"  vodtool show-topics {project_dir}")
    console.print(f"  vodtool cutplan {project_dir} --topic topic_0000")
    console.print(f"  vodtool export {project_dir}")


@app.command(name="inspect-topic")
def inspect_topic(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    topic_id: str = typer.Argument(..., help="Topic ID to inspect (e.g., topic_0000)"),
):
    """
    Inspect and debug a specific topic.

    Shows duration, spans, and representative chunks for analysis.
    """
    inspect_topic_command(project_path, topic_id)


@app.command(name="show-topics")
def show_topics(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    include_misc: bool = typer.Option(
        False, "--include-misc", help="Include MISC bucket topics (short/singleton)",
    ),
):
    """
    Display chronological timeline of topic spans.

    Shows when topics appear and reappear (returns) throughout the video.
    """
    result = show_topics_command(project_path, include_misc)
    if result is None:
        raise typer.Exit(code=1)


@app.command(name="explain-chunk")
def explain_chunk(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    chunk_id: str = typer.Argument(..., help="Chunk ID to explain (e.g., chunk_0042)"),
):
    """
    Explain why a chunk belongs to its assigned topic.

    Shows chunk text, assigned topic, and top-3 nearest neighbors by similarity.
    """
    result = explain_chunk_command(project_path, chunk_id)
    if result is None:
        raise typer.Exit(code=1)


@app.command(name="llm-topics")
def llm_topics_cmd(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    max_topics: Optional[int] = typer.Option(
        None, "--max-topics", help="Maximum number of topics (optional)",
    ),
):
    """
    Use LLM to segment transcript into topics.

    Requires ANTHROPIC_API_KEY in .env file.
    Analyzes chunks directly with Claude and returns structured topic list.
    """
    result = llm_topics(project_path, max_topics)
    if result is None:
        raise typer.Exit(code=1)


@app.command(name="list-topics")
def list_topics(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    source: str = typer.Option(
        "auto",
        "--source",
        "-s",
        help="Topic map source: 'llm', 'labeled', 'basic', or 'auto' (default)",
    ),
):
    """
    List all topics with labels, durations, and summaries.

    Clean overview of detected topics. Auto-prefers LLM topics if available.
    """
    result = list_topics_command(project_path, source)
    if result is None:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
