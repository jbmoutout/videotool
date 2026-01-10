"""Speaker diarization command using pyannote.audio."""

import json
import logging
from pathlib import Path

import typer

logger = logging.getLogger(__name__)


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
    except ImportError:
        logger.error("pyannote.audio not installed. Install with: pip install pyannote.audio")
        raise typer.Exit(1)

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
    if not audio_path.exists():
        logger.error(f"Audio file not found: {audio_path}")
        raise typer.Exit(1)

    logger.info(f"Running speaker diarization on {audio_path}")

    # Load pretrained pipeline
    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=None,  # May require HuggingFace token for first download
        )
    except Exception as e:
        logger.error(
            f"Failed to load diarization model: {e}\n"
            "Note: You may need to accept pyannote model conditions on HuggingFace "
            "and set HF_TOKEN environment variable."
        )
        raise typer.Exit(1)

    # Run diarization
    try:
        diarization = pipeline(str(audio_path))
    except Exception as e:
        logger.error(f"Diarization failed: {e}")
        raise typer.Exit(1)

    # Convert to list of segments
    segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append(
            {"start": turn.start, "end": turn.end, "speaker_id": speaker}
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
                {"role": role, "speaker_id": speaker_id, "seconds": round(seconds, 1)}
            )
        else:
            other_speakers.append({"speaker_id": speaker_id, "seconds": round(seconds, 1)})

    speaker_map = {
        "num_main": num_main,
        "main_speakers": main_speakers,
        "other_speakers": other_speakers,
    }

    # Save speaker map
    map_file = project_path / "speaker_map.json"
    with map_file.open("w") as f:
        json.dump(speaker_map, f, indent=2)

    logger.info(f"Saved speaker map to {map_file}")
    logger.info(f"Identified {len(main_speakers)} main speaker(s) and {len(other_speakers)} other(s)")

    for speaker in main_speakers:
        logger.info(
            f"  {speaker['role']}: {speaker['speaker_id']} ({speaker['seconds']}s)"
        )

    typer.echo(f"✓ Diarization complete. Main speakers: {len(main_speakers)}")
