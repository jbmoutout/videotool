"""Pipeline dependency and file requirement helpers for vodtool."""

from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()

# Pipeline stage dependencies and their outputs
PIPELINE_STAGES = {
    "ingest": {
        "output_files": ["audio.wav", "meta.json"],
        "command": "vodtool ingest",
        "description": "ingest a video file",
    },
    "transcribe": {
        "output_files": ["transcript_raw.json"],
        "command": "vodtool transcribe",
        "description": "transcribe the audio",
        "requires": ["ingest"],
    },
    "chunks": {
        "output_files": ["chunks.json"],
        "command": "vodtool chunks",
        "description": "create semantic chunks",
        "requires": ["transcribe"],
    },
    "embed": {
        "output_files": ["embeddings.sqlite"],
        "command": "vodtool embed",
        "description": "generate embeddings",
        "requires": ["chunks"],
    },
}


def require_file(
    project_path: Path,
    filename: str,
    *,
    stage_name: Optional[str] = None,
) -> Optional[Path]:
    """
    Check that a required file exists in the project directory.

    Args:
        project_path: Path to the project directory
        filename: Name of the required file
        stage_name: Optional pipeline stage that produces this file

    Returns:
        Path to the file if it exists, None otherwise (with error printed)
    """
    file_path = project_path / filename
    if not file_path.exists():
        console.print(f"[red]Error: {filename} not found: {file_path}[/red]")

        # If we know which stage produces this file, suggest running it
        if stage_name and stage_name in PIPELINE_STAGES:
            stage = PIPELINE_STAGES[stage_name]
            console.print(f"Run '{stage['command']}' first to {stage['description']}.")
        else:
            # Try to find which stage produces this file
            for stage_key, stage_info in PIPELINE_STAGES.items():
                if filename in stage_info["output_files"]:
                    console.print(
                        f"Run '{stage_info['command']}' first to {stage_info['description']}.",
                    )
                    break

        return None

    return file_path


def require_pipeline_stage(project_path: Path, stage_name: str) -> bool:
    """
    Check that a pipeline stage has been completed.

    Verifies that all output files from the specified stage exist.

    Args:
        project_path: Path to the project directory
        stage_name: Name of the pipeline stage (e.g., 'ingest', 'transcribe')

    Returns:
        True if all required files exist, False otherwise (with error printed)
    """
    if stage_name not in PIPELINE_STAGES:
        console.print(f"[red]Error: Unknown pipeline stage: {stage_name}[/red]")
        return False

    stage = PIPELINE_STAGES[stage_name]
    missing_files = []

    for filename in stage["output_files"]:
        file_path = project_path / filename
        if not file_path.exists():
            missing_files.append(filename)

    if missing_files:
        console.print(
            f"[red]Error: Pipeline stage '{stage_name}' has not been completed[/red]",
        )
        console.print(f"Missing files: {', '.join(missing_files)}")
        console.print(f"Run '{stage['command']}' first to {stage['description']}.")
        return False

    return True


def check_pipeline_dependencies(project_path: Path, stage_name: str) -> bool:
    """
    Check that all dependencies for a pipeline stage are satisfied.

    Args:
        project_path: Path to the project directory
        stage_name: Name of the pipeline stage to check

    Returns:
        True if all dependencies are satisfied, False otherwise
    """
    if stage_name not in PIPELINE_STAGES:
        console.print(f"[red]Error: Unknown pipeline stage: {stage_name}[/red]")
        return False

    stage = PIPELINE_STAGES[stage_name]
    required_stages = stage.get("requires", [])

    for required_stage in required_stages:
        if not require_pipeline_stage(project_path, required_stage):
            return False

    return True
