"""Transcription command for vodtool using OpenAI Whisper."""

import logging
from pathlib import Path
from typing import Optional

from rich.console import Console

from vodtool.utils.file_utils import project_lock, safe_write_json
from vodtool.utils.validation import validate_project_path

console = Console()
logger = logging.getLogger("vodtool")


def check_whisper_available() -> bool:
    """Check if Whisper is installed and accessible."""
    try:
        import whisper  # noqa: F401

        return True
    except ImportError:
        return False


def transcribe_audio(
    project_path: Path,
    model_name: str = "small",
    force: bool = False,
    language: Optional[str] = None,
) -> Optional[Path]:
    """
    Transcribe audio using OpenAI Whisper.

    Args:
        project_path: Path to the project directory
        model_name: Whisper model size (tiny, base, small, medium, large)
        force: Force re-transcription even if transcript exists
        language: Language code (e.g., 'en', 'fr', 'es'). Auto-detect if None.

    Returns:
        Path to the transcript_raw.json file, or None if transcription failed
    """
    # Check whisper availability
    if not check_whisper_available():
        console.print("[red]Error: OpenAI Whisper is not installed[/red]")
        console.print("\nPlease install whisper:")
        console.print("  pip install -U openai-whisper")
        console.print("\nNote: Whisper also requires ffmpeg to be installed.")
        console.print("  macOS: brew install ffmpeg")
        console.print("  Ubuntu/Debian: sudo apt-get install ffmpeg")
        return None

    # Validate project directory
    error = validate_project_path(project_path)
    if error:
        console.print(f"[red]Error: {error}[/red]")
        return None

    # Check for audio file
    audio_path = project_path / "audio.wav"
    if not audio_path.exists():
        console.print(f"[red]Error: Audio file not found: {audio_path}[/red]")
        console.print("Run 'vodtool ingest' first to create a project with audio.")
        return None

    # Check if transcript already exists
    transcript_raw_path = project_path / "transcript_raw.json"
    transcript_txt_path = project_path / "transcript.txt"

    if transcript_raw_path.exists() and not force:
        console.print(f"[yellow]Transcript already exists: {transcript_raw_path}[/yellow]")
        console.print("Use --force to overwrite.")
        return transcript_raw_path

    # Import whisper here (after checking it's available)
    try:
        import whisper
    except ImportError as e:
        console.print(f"[red]Error importing whisper: {e}[/red]")
        return None

    # Load Whisper model
    console.print(f"[cyan]Loading Whisper model '{model_name}'...[/cyan]")
    console.print("[dim]Note: First run will download the model (this may take a while)[/dim]")

    try:
        model = whisper.load_model(model_name)
        logger.info(f"Loaded Whisper model: {model_name}")
    except Exception as e:
        console.print(f"[red]Error loading Whisper model: {e}[/red]")
        console.print("\nValid model names: tiny, base, small, medium, large")
        return None

    # Acquire project lock to prevent concurrent modifications
    with project_lock(project_path):
        # Transcribe audio
        console.print("[cyan]Transcribing audio...[/cyan]")
        console.print(f"[dim]Audio file: {audio_path}[/dim]")
        if language:
            console.print(f"[dim]Language: {language}[/dim]")

        try:
            transcribe_kwargs = {"verbose": False}
            if language:
                transcribe_kwargs["language"] = language
            result = model.transcribe(str(audio_path), **transcribe_kwargs)
            logger.info("Transcription complete")
        except Exception as e:
            console.print(f"[red]Error during transcription: {e}[/red]")
            return None

        # Extract relevant data
        transcript_data = {
            "language": result.get("language", "unknown"),
            "model": model_name,
            "segments": [
                {
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"].strip(),
                }
                for seg in result.get("segments", [])
            ],
        }

        # Save transcript_raw.json
        console.print("[cyan]Saving transcript...[/cyan]")

        if not safe_write_json(transcript_raw_path, transcript_data):
            return None

        logger.info(f"Saved transcript_raw.json: {transcript_raw_path}")

        # Save transcript.txt (plain text)
        try:
            with transcript_txt_path.open("w", encoding="utf-8") as f:
                for seg in transcript_data["segments"]:
                    f.write(seg["text"] + "\n")
            logger.info(f"Saved transcript.txt: {transcript_txt_path}")
        except OSError as e:
            console.print(f"[red]Error saving transcript text: {e}[/red]")
            # Not fatal, JSON is more important
            logger.warning(f"Failed to save transcript.txt: {e}")

        # Print summary
        num_segments = len(transcript_data["segments"])
        if num_segments > 0:
            duration = transcript_data["segments"][-1]["end"]
            console.print("\n[green]✓ Transcription complete![/green]")
            console.print(f"[bold]Language:[/bold] {transcript_data['language']}")
            console.print(f"[bold]Segments:[/bold] {num_segments}")
            console.print(f"[bold]Duration:[/bold] {duration:.1f}s ({duration/60:.1f} min)")
            console.print(f"[bold]Transcript:[/bold] {transcript_raw_path}")
        else:
            console.print("[yellow]Warning: No segments found in transcription[/yellow]")

        return transcript_raw_path
