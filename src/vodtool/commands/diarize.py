"""Speaker diarization command using pyannote.audio."""

import json
import logging
import os
import warnings
from pathlib import Path

# Suppress noisy deprecation warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

# MUST patch torch BEFORE any torch operations or imports that use it
# Set environment variable to disable weights_only globally for PyTorch 2.6+
# This must be set before torch is imported anywhere
os.environ["TORCH_FORCE_WEIGHTS_ONLY_LOAD"] = "0"

import torch  # noqa: E402

# Double-check: Also patch torch.load directly as a fallback
# pyannote models were created before PyTorch 2.6 and are trusted sources
_original_torch_load = torch.load


def _patched_torch_load(*args, **kwargs):
    """Force weights_only=False for pyannote.audio compatibility with PyTorch 2.6+."""
    kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)


torch.load = _patched_torch_load

# Also patch the internal _load function used by torch.load
if hasattr(torch, "_load"):
    _original_internal_load = torch._load

    def _patched_internal_load(*args, **kwargs):
        kwargs["weights_only"] = False
        return _original_internal_load(*args, **kwargs)

    torch._load = _patched_internal_load

import typer  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.progress import Progress, SpinnerColumn, TextColumn  # noqa: E402

logger = logging.getLogger(__name__)
console = Console()

# Load environment variables from .env file
load_dotenv()


def diarize_command(
    project_path: Path = typer.Argument(..., help="Path to project folder"),
    num_main: int = typer.Option(2, help="Number of main speakers to identify"),
):
    """
    Perform speaker diarization on the project audio.

    Identifies speakers in the audio and maps the top N speakers
    (by speaking time) to MAIN_1, MAIN_2, etc. All other speakers
    are mapped to OTHER.

    Outputs:
    - diarization_segments.json: Raw diarization segments
    - speaker_map.json: Mapping of speaker IDs to roles (MAIN_1, MAIN_2, OTHER)
    """
    try:
        from pyannote.audio import Pipeline
    except ImportError as e:
        logger.error("pyannote.audio not installed. Install with: pip install pyannote.audio")
        raise typer.Exit(1) from e

    if not project_path.exists():
        logger.error(f"Project path does not exist: {project_path}")
        raise typer.Exit(1)

    # Check for required files
    meta_file = project_path / "meta.json"
    if not meta_file.exists():
        logger.error(f"meta.json not found in {project_path}")
        raise typer.Exit(1)

    with meta_file.open() as f:
        meta = json.load(f)

    audio_path = Path(meta["audio_path"])
    # Handle relative paths by resolving against project directory
    if not audio_path.is_absolute():
        audio_path = project_path / audio_path

    if not audio_path.exists():
        logger.error(f"Audio file not found: {audio_path}")
        raise typer.Exit(1)

    logger.info(f"Running speaker diarization on {audio_path}")

    # Get HuggingFace token from environment
    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        logger.error(
            "HF_TOKEN not found in environment or .env file.\n"
            "Please create a .env file with: HF_TOKEN=your_token_here\n"
            "Get your token from: https://huggingface.co/settings/tokens\n"
            "Accept model terms at: https://huggingface.co/pyannote/speaker-diarization-3.1",
        )
        raise typer.Exit(1)

    # Load pretrained pipeline
    console.print("[cyan]Loading diarization model...[/cyan]")
    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )
    except Exception as e:
        logger.error(
            f"Failed to load diarization model: {e}\n"
            "Note: You may need to accept pyannote model conditions on HuggingFace.\n"
            "Visit: https://huggingface.co/pyannote/speaker-diarization-3.1",
        )
        raise typer.Exit(1) from e

    # Run diarization with progress indicator
    console.print(
        f"[cyan]Running speaker diarization "
        f"(~{meta['duration_seconds']/60:.1f} min audio)...[/cyan]",
    )
    console.print("[dim]This may take several minutes...[/dim]")

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Analyzing audio...", total=None)
            diarization = pipeline(str(audio_path))
            progress.update(task, completed=True)
    except Exception as e:
        logger.error(f"Diarization failed: {e}")
        raise typer.Exit(1) from e

    # Convert to list of segments
    segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append(
            {"start": turn.start, "end": turn.end, "speaker_id": speaker},
        )

    # Sort by start time
    segments.sort(key=lambda s: s["start"])

    # Save raw diarization segments
    segments_file = project_path / "diarization_segments.json"
    with segments_file.open("w") as f:
        json.dump(segments, f, indent=2)
    logger.info(f"Saved {len(segments)} diarization segments to {segments_file}")

    # Compute speaking time per speaker
    speaker_times = {}
    for seg in segments:
        speaker_id = seg["speaker_id"]
        duration = seg["end"] - seg["start"]
        speaker_times[speaker_id] = speaker_times.get(speaker_id, 0.0) + duration

    # Sort speakers by speaking time (descending)
    sorted_speakers = sorted(speaker_times.items(), key=lambda x: x[1], reverse=True)

    # Map top num_main speakers to MAIN_1, MAIN_2, etc.
    main_speakers = []
    other_speakers = []

    for idx, (speaker_id, seconds) in enumerate(sorted_speakers):
        if idx < num_main:
            role = f"MAIN_{idx + 1}"
            main_speakers.append(
                {"role": role, "speaker_id": speaker_id, "seconds": round(seconds, 1)},
            )
        else:
            other_speakers.append({"speaker_id": speaker_id, "seconds": round(seconds, 1)})

    speaker_map = {
        "num_main": num_main,
        "main_speakers": main_speakers,
        "background_speakers": [],  # Empty initially, populated via diarize-review
        "other_speakers": other_speakers,
    }

    # Save speaker map
    map_file = project_path / "speaker_map.json"
    with map_file.open("w") as f:
        json.dump(speaker_map, f, indent=2)

    logger.info(f"Saved speaker map to {map_file}")
    logger.info(
        f"Identified {len(main_speakers)} main speaker(s) "
        f"and {len(other_speakers)} other(s)",
    )

    # Display results
    console.print("\n[green]✓ Diarization complete![/green]")
    console.print(f"[bold]Total segments:[/bold] {len(segments)}")
    console.print(f"[bold]Main speakers:[/bold] {len(main_speakers)}")

    for speaker in main_speakers:
        console.print(
            f"  • [bold]{speaker['role']}:[/bold] "
            f"{speaker['speaker_id']} ({speaker['seconds']}s)",
        )

    if other_speakers:
        console.print(f"[bold]Other speakers:[/bold] {len(other_speakers)}")
        for speaker in other_speakers[:3]:  # Show first 3
            console.print(
                f"  • {speaker['speaker_id']} ({speaker['seconds']}s)",
            )
        if len(other_speakers) > 3:
            console.print(f"  • ...and {len(other_speakers) - 3} more")

    console.print(
        f"\n[dim]Run 'vodtool diarize-review {project_path}' "
        "to classify background speakers[/dim]",
    )
