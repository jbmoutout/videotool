"""Transcription command for vodtool."""

import logging
from pathlib import Path
from typing import Optional

from rich.console import Console

from vodtool.utils.file_utils import project_lock, safe_write_json
from vodtool.utils.validation import validate_project_path

console = Console()
logger = logging.getLogger("vodtool")

_last_error: Optional[str] = None


def get_last_error() -> Optional[str]:
    """Return the last error message set by transcribe_audio."""
    return _last_error


def transcribe_audio(
    project_path: Path,
    model_name: Optional[str] = None,
    force: bool = False,
    language: Optional[str] = None,
    provider: str = "groq",
) -> Optional[Path]:
    """
    Transcribe audio using the specified provider.

    Args:
        project_path: Path to the project directory
        model_name: Model override. Defaults: groq→whisper-large-v3-turbo, openai→whisper-1
        force: Force re-transcription even if transcript exists
        language: BCP-47 language code (e.g. "fr"). Auto-detect if None.
        provider: Transcription provider — "groq" (default, fast) or "openai"

    Returns:
        Path to transcript_raw.json, or None on failure
    """
    global _last_error
    _last_error = None

    error = validate_project_path(project_path)
    if error:
        _last_error = error
        console.print(f"[red]Error: {error}[/red]")
        return None

    audio_path = project_path / "audio.wav"
    if not audio_path.exists():
        _last_error = f"Audio file not found: {audio_path}"
        console.print(f"[red]Error: Audio file not found: {audio_path}[/red]")
        console.print("Run 'vodtool ingest' first to create a project with audio.")
        return None

    transcript_raw_path = project_path / "transcript_raw.json"
    transcript_txt_path = project_path / "transcript.txt"

    if transcript_raw_path.exists() and not force:
        console.print(f"[yellow]Transcript already exists: {transcript_raw_path}[/yellow]")
        console.print("Use --force to overwrite.")
        return transcript_raw_path

    try:
        if provider == "groq":
            from vodtool.transcription import GroqTranscriptionProvider
            transcription_provider = GroqTranscriptionProvider(
                model=model_name or "whisper-large-v3-turbo"
            )
        elif provider == "openai":
            from vodtool.transcription import OpenAITranscriptionProvider
            transcription_provider = OpenAITranscriptionProvider(
                model=model_name or "whisper-1"
            )
        else:
            _last_error = f"Unknown transcription provider: {provider!r}. Use 'groq' or 'openai'."
            console.print(f"[red]Error: {_last_error}[/red]")
            return None
    except (ValueError, ImportError) as e:
        _last_error = str(e)
        console.print(f"[red]Error: {e}[/red]")
        return None

    with project_lock(project_path):
        console.print(f"[cyan]Transcribing audio (provider: {provider})...[/cyan]")
        console.print(f"[dim]Audio file: {audio_path}[/dim]")
        if language:
            console.print(f"[dim]Language: {language}[/dim]")

        file_size_mb = audio_path.stat().st_size / (1024 * 1024)
        if file_size_mb > 25:
            console.print(
                f"[dim]File size: {file_size_mb:.0f}MB — chunking into 10-minute segments[/dim]"
            )

        try:
            result = transcription_provider.transcribe(audio_path, language=language)
            logger.info("Transcription complete")
        except FileNotFoundError as e:
            _last_error = str(e)
            console.print(f"[red]Error: {e}[/red]")
            return None
        except RuntimeError as e:
            _last_error = str(e)
            console.print(f"[red]Error during transcription: {e}[/red]")
            return None
        except Exception as e:
            _last_error = f"Unexpected error during transcription: {e}"
            console.print(f"[red]Unexpected error during transcription: {e}[/red]")
            return None

        if not safe_write_json(transcript_raw_path, result):
            _last_error = "Failed to write transcript_raw.json"
            return None
        logger.info(f"Saved transcript_raw.json: {transcript_raw_path}")

        try:
            with transcript_txt_path.open("w", encoding="utf-8") as f:
                for seg in result["segments"]:
                    f.write(seg["text"] + "\n")
        except OSError as e:
            logger.warning(f"Failed to save transcript.txt: {e}")

        segments = result["segments"]
        if segments:
            duration = segments[-1]["end"]
            console.print("\n[green]✓ Transcription complete![/green]")
            console.print(f"[bold]Provider:[/bold] {provider} ({result['model']})")
            console.print(f"[bold]Language:[/bold] {result['language']}")
            console.print(f"[bold]Segments:[/bold] {len(segments)}")
            console.print(f"[bold]Duration:[/bold] {duration:.1f}s ({duration / 60:.1f} min)")
            console.print(f"[bold]Transcript:[/bold] {transcript_raw_path}")
        else:
            console.print("[yellow]Warning: No segments found in transcription[/yellow]")

        return transcript_raw_path
