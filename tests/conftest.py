"""Shared test fixtures for VideoTool test suite."""

import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_project_dir(temp_dir):
    """Create a mock videotool project directory with meta.json."""
    project_dir = temp_dir / "test_project"
    project_dir.mkdir()

    # Create meta.json
    meta = {
        "project_id": "testproj",
        "audio_path": "audio.wav",
        "duration_seconds": 120.0,
    }
    with (project_dir / "meta.json").open("w") as f:
        json.dump(meta, f)

    return project_dir


@pytest.fixture
def mock_video_file(temp_dir):
    """Create a mock video file for testing."""
    video_path = temp_dir / "test_video.mp4"
    # Create a small file (not actual video, but enough for validation)
    video_path.write_bytes(b"fake video content for testing")
    return video_path


@pytest.fixture
def mock_json_file(temp_dir):
    """Create a valid JSON file for testing."""
    json_path = temp_dir / "test.json"
    data = {"test": "data", "numbers": [1, 2, 3]}
    with json_path.open("w") as f:
        json.dump(data, f)
    return json_path


@pytest.fixture
def corrupted_json_file(temp_dir):
    """Create a corrupted JSON file for testing."""
    json_path = temp_dir / "corrupted.json"
    json_path.write_text("{invalid json")
    return json_path
