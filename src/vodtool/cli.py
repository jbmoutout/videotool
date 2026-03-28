"""Main CLI interface for VodTool."""

import logging
from pathlib import Path
from typing import Optional

import typer

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass
from rich.console import Console

from vodtool import __version__
from vodtool.commands.chunks import create_chunks
from vodtool.commands.chunks import get_last_error as get_chunks_error
from vodtool.commands.cutplan import generate_cutplan
from vodtool.commands.diarize import diarize_command
from vodtool.commands.diarize_review import diarize_review_command
from vodtool.commands.embed import embed_chunks
from vodtool.commands.embed import get_last_error as get_embed_error
from vodtool.commands.explain_chunk import explain_chunk_command
from vodtool.commands.export import export_video
from vodtool.commands.ingest import get_last_error as get_ingest_error
from vodtool.commands.ingest import ingest_video
from vodtool.commands.inspect_topic import inspect_topic_command
from vodtool.commands.label_topics import label_topics_command
from vodtool.commands.list_topics import list_topics_command
from vodtool.commands.llm_beats import detect_beats
from vodtool.commands.llm_beats import get_last_error as get_beats_error
from vodtool.commands.llm_topics import get_last_error as get_llm_error
from vodtool.commands.llm_topics import llm_topics
from vodtool.commands.merge_topics import merge_topics_command
from vodtool.commands.segment_topics import segment_topics
from vodtool.commands.show_topics import show_topics_command
from vodtool.commands.topics import cluster_topics
from vodtool.commands.transcribe import get_last_error as get_transcribe_error
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
    input_video_path: str = typer.Argument(..., help="Path to video file or Twitch VOD URL"),
    quality: str = typer.Option(
        "worst",
        "--quality",
        help="Video quality for Twitch downloads (default: 'worst', use 'best' for export quality)",
    ),
):
    """
    Ingest a video file or Twitch VOD URL and create a new project.

    Creates a project folder with extracted audio and metadata.
    Accepts a local file path or a Twitch URL (https://twitch.tv/videos/<id>).
    """
    ffmpeg_path = app.state.get("ffmpeg_path", "ffmpeg")
    project_dir = ingest_video(input_video_path, ffmpeg_path, quality=quality)
    if project_dir is None:
        raise typer.Exit(code=1)


@app.command()
def transcribe(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    provider: str = typer.Option(
        "groq",
        "--provider",
        help="Transcription provider: 'groq' (default, fast) or 'openai'",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Model override (e.g. 'whisper-large-v3' for Groq, 'whisper-1' for OpenAI)",
    ),
    language: Optional[str] = typer.Option(
        None,
        "--language",
        help="Language code (e.g., 'en', 'fr', 'es'). Auto-detect if not specified.",
    ),
    force: bool = typer.Option(False, "--force", help="Force re-transcription"),
):
    """
    Transcribe audio using Groq or OpenAI Whisper API.

    Generates timestamped transcript from project audio.
    Default provider is Groq (whisper-large-v3-turbo) — ~10-20x faster than OpenAI.
    """
    transcript_path = transcribe_audio(project_path, model, force, language, provider)
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
    provider: str = typer.Option(
        "openai",
        "--provider",
        help="Embedding provider: 'openai' (default) or 'local' (sentence-transformers)",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Model override (e.g., 'text-embedding-3-large' for OpenAI)",
    ),
):
    """
    Generate embeddings for transcript chunks.

    Uses OpenAI text-embedding-3-small by default (requires OPENAI_API_KEY).
    Use --provider local for offline sentence-transformers.
    """
    db_path = embed_chunks(project_path, provider, model)
    if db_path is None:
        raise typer.Exit(code=1)


@app.command(name="segment-topics")
def segment_topics_cmd(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    max_topics: int = typer.Option(6, "--max-topics", help="Maximum number of topic segments"),
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
    max_topics: int = typer.Option(6, "--max-topics", help="Maximum number of topics"),
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


def _run_ingest_and_transcribe(
    input_video_path: str,
    json_progress: bool,
    total_steps: int,
    quality: str = "worst",
    transcription_provider: str = "groq",
    whisper_model: Optional[str] = None,
    language: Optional[str] = None,
):
    """
    Shared helper: run ingest + transcribe (steps 1–2 of any pipeline).

    Returns (project_dir, progress_fn, fail_fn) or exits on error.
    """
    import json as _json
    import sys

    ffmpeg_path = app.state.get("ffmpeg_path", "ffmpeg")

    def progress(step: int, msg: str):
        if json_progress:
            sys.stdout.write(
                _json.dumps({
                    "step": step,
                    "total": total_steps,
                    "pct": round(step / total_steps, 3),
                    "msg": msg,
                })
                + "\n"
            )
            sys.stdout.flush()
        else:
            console.print(f"\n[bold cyan]Step {step}/{total_steps}: {msg}[/bold cyan]")

    def fail(step: int, msg: str):
        if json_progress:
            sys.stdout.write(_json.dumps({"error": msg, "step": step}) + "\n")
            sys.stdout.flush()
        raise typer.Exit(code=1)

    # Step 1: Ingest (with download progress for Twitch URLs)
    progress(1, "Ingesting video...")

    def _download_progress(pct: float):
        if json_progress:
            sys.stdout.write(
                _json.dumps({
                    "step": 1,
                    "total": total_steps,
                    "pct": round(pct / total_steps, 3),
                    "msg": f"Downloading: {int(pct * 100)}%",
                    "download_pct": round(pct * 100),
                })
                + "\n"
            )
            sys.stdout.flush()

    project_dir = ingest_video(
        input_video_path, ffmpeg_path, quality=quality,
        download_progress_callback=_download_progress if json_progress else None,
    )
    if project_dir is None:
        fail(1, get_ingest_error() or "Ingest failed")

    # Step 2: Transcribe
    progress(2, "Transcribing audio...")
    transcript_path = transcribe_audio(
        project_dir, whisper_model, False, language, transcription_provider
    )
    if transcript_path is None:
        fail(2, get_transcribe_error() or "Transcription failed")

    return project_dir, progress, fail


@app.command()
def beats(
    input_video_path: str = typer.Argument(..., help="Path to video file or Twitch VOD URL"),
    quality: str = typer.Option(
        "worst",
        "--quality",
        help="Video quality for Twitch downloads (default: 'worst', use 'best' for export quality)",
    ),
    transcription_provider: str = typer.Option(
        "groq",
        "--transcription-provider",
        help="Transcription provider: 'groq' (default, fast) or 'openai'",
    ),
    whisper_model: Optional[str] = typer.Option(
        None,
        "--whisper-model",
        help="Transcription model override (default: whisper-large-v3-turbo for groq, whisper-1 for openai)",
    ),
    language: Optional[str] = typer.Option(
        None,
        "--language",
        help="Language code (auto-detect if not specified)",
    ),
    json_progress: bool = typer.Option(
        False, "--json-progress", help="Emit JSON progress lines (for Tauri IPC)"
    ),
):
    """
    Run beat detection pipeline: ingest → transcribe → llm-beats.

    Simplified 3-step pipeline. The LLM identifies topics AND narrative beats
    (hook/build/peak/resolution) in a single call from the full transcript.
    With --json-progress, emits lines like: {"step":1,"total":3,"pct":0.333,"msg":"..."}
    """
    import json as _json
    import sys

    total = 3

    project_dir, progress, fail = _run_ingest_and_transcribe(
        input_video_path, json_progress, total,
        quality=quality,
        transcription_provider=transcription_provider,
        whisper_model=whisper_model,
        language=language,
    )

    # Step 3: LLM beat detection
    progress(3, "Analyzing narrative structure...")
    beats_path = detect_beats(project_dir, json_progress=json_progress)
    if beats_path is None:
        fail(3, get_beats_error() or "Beat detection failed")

    if json_progress:
        try:
            beats_data = _json.loads(beats_path.read_text())
            beat_count = sum(len(t["beats"]) for t in beats_data.get("beats", []))
            topic_count = len(beats_data.get("beats", []))
        except Exception:
            beat_count = 0
            topic_count = 0
        sys.stdout.write(
            _json.dumps({
                "done": True,
                "project_dir": str(project_dir),
                "topic_count": topic_count,
                "beat_count": beat_count,
            })
            + "\n"
        )
        sys.stdout.flush()
    else:
        console.print("\n[bold green]✓ Beat detection complete![/bold green]")
        console.print(f"[bold]Project:[/bold] {project_dir}")


@app.command()
def pipeline(
    input_video_path: str = typer.Argument(..., help="Path to video file or Twitch VOD URL"),
    quality: str = typer.Option(
        "worst",
        "--quality",
        help="Video quality for Twitch downloads (default: 'worst', use 'best' for export quality)",
    ),
    transcription_provider: str = typer.Option(
        "groq",
        "--transcription-provider",
        help="Transcription provider: 'groq' (default, fast) or 'openai'",
    ),
    whisper_model: Optional[str] = typer.Option(
        None,
        "--whisper-model",
        help="Transcription model override (default: whisper-large-v3-turbo for groq, whisper-1 for openai)",
    ),
    language: Optional[str] = typer.Option(
        None,
        "--language",
        help="Language code (auto-detect if not specified)",
    ),
    max_topics: Optional[int] = typer.Option(
        None,
        "--max-topics",
        help="Cap on topics (default: LLM decides naturally)",
    ),
    provider: str = typer.Option(
        "anthropic",
        "--provider",
        help="LLM provider: 'anthropic' or 'ollama'",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Model override (e.g. 'qwen2.5:3b' for Ollama)",
    ),
    json_progress: bool = typer.Option(
        False, "--json-progress", help="Emit JSON progress lines (for Tauri IPC)"
    ),
):
    """
    Run full pipeline: ingest → transcribe → chunks → embed → llm-topics.

    One command to process a video from start to labeled topics.
    With --json-progress, emits lines like: {"step":1,"total":5,"pct":0.2,"msg":"..."}
    """
    import json as _json
    import sys

    total = 5

    project_dir, progress, fail = _run_ingest_and_transcribe(
        input_video_path, json_progress, total,
        quality=quality,
        transcription_provider=transcription_provider,
        whisper_model=whisper_model,
        language=language,
    )

    # Step 3: Chunks
    progress(3, "Creating semantic chunks...")
    chunks_path = create_chunks(project_dir)
    if chunks_path is None:
        fail(3, get_chunks_error() or "Chunking failed")

    # Step 4: Embed
    progress(4, "Generating embeddings...")
    db_path = embed_chunks(project_dir)
    if db_path is None:
        fail(4, get_embed_error() or "Embedding failed")

    # Step 5: LLM topic detection (replaces segment-topics + topics + label-topics)
    progress(5, "Detecting topics...")
    topic_map_path = llm_topics(project_dir, max_topics, provider, model)
    if topic_map_path is None:
        fail(5, get_llm_error() or "LLM topic detection failed")

    if json_progress:
        try:
            topic_map = _json.loads(topic_map_path.read_text())
            topic_count = len(topic_map)
        except Exception:
            topic_count = 0
        sys.stdout.write(
            _json.dumps({"done": True, "project_dir": str(project_dir), "topic_count": topic_count})
            + "\n"
        )
        sys.stdout.flush()
    else:
        console.print("\n[bold green]✓ Pipeline complete![/bold green]")
        console.print(f"[bold]Project:[/bold] {project_dir}")
        console.print("\n[bold]Next steps:[/bold]")
        console.print(f"  vodtool show-topics {project_dir}")
        console.print(f"  vodtool cutplan {project_dir} --topic topic_0000")
        console.print(f"  vodtool export {project_dir}")


@app.command(name="llm-beats")
def llm_beats_cmd(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
):
    """
    Detect narrative beats from an existing transcript.

    Runs only the LLM beat detection step (no ingest, no transcribe).
    Requires transcript_raw.json in the project directory.
    """
    result = detect_beats(project_path)
    if result is None:
        raise typer.Exit(code=1)


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
        False,
        "--include-misc",
        help="Include MISC bucket topics (short/singleton)",
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
        None,
        "--max-topics",
        help="Maximum number of topics (optional)",
    ),
    provider: str = typer.Option(
        "auto",
        "--provider",
        help="LLM provider: 'anthropic' (API), 'ollama' (local), or 'auto' (try ollama first)",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Model override (e.g., 'qwen2.5:3b' for Ollama)",
    ),
):
    """
    Use LLM to segment transcript into topics.

    Supports both Anthropic API (Claude) and local Ollama models.

    Provider options:
      - auto: Try Ollama first, fall back to Anthropic (default)
      - anthropic: Force Anthropic API (requires ANTHROPIC_API_KEY)
      - ollama: Force local Ollama (requires Ollama running)

    Analyzes chunks directly with LLM and returns structured topic list.
    """
    result = llm_topics(project_path, max_topics, provider, model)
    if result is None:
        raise typer.Exit(code=1)


@app.command(name="compare-llm")
def compare_llm_cmd(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    max_topics: Optional[int] = typer.Option(
        None,
        "--max-topics",
        help="Maximum number of topics (optional)",
    ),
    ollama_model: str = typer.Option(
        "qwen2.5:3b",
        "--ollama-model",
        help="Ollama model to use for comparison",
    ),
):
    """
    Compare Claude and Ollama topic generation side-by-side.

    Generates topics with both providers and displays:
      - Performance comparison (time, topic count)
      - Side-by-side topic labels
      - Quality insights

    Saves results to topic_map_claude.json and topic_map_ollama.json.
    Requires both ANTHROPIC_API_KEY and Ollama installed.
    """
    from vodtool.commands.compare_llm import compare_llm_topics

    compare_llm_topics(project_path, max_topics, ollama_model)


@app.command(name="merge-topics")
def merge_topics(
    project_path: Path = typer.Argument(..., help="Path to project directory"),
    topic_a: str = typer.Argument(..., help="Topic to keep (e.g. topic_0002)"),
    topic_b: str = typer.Argument(..., help="Topic to absorb into topic_a"),
    source: str = typer.Option(
        "auto",
        "--source",
        "-s",
        help="Topic map source: 'llm', 'labeled', 'basic', or 'auto' (default)",
    ),
):
    """
    Merge two topics into one.

    Combines topic_b into topic_a (keeps topic_a's label), then renumbers all topics.
    Edits the topic map file in place.
    """
    result = merge_topics_command(project_path, topic_a, topic_b, source)
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
