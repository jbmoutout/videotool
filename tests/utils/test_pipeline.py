"""Tests for vodtool.utils.pipeline module."""

import pytest

from vodtool.utils.pipeline import (
    PIPELINE_STAGES,
    check_pipeline_dependencies,
    require_file,
    require_pipeline_stage,
)


class TestRequireFile:
    """Tests for require_file()."""

    def test_returns_path_when_file_exists(self, mock_project_dir):
        """Returns file path when file exists."""
        # meta.json exists in mock_project_dir
        result = require_file(mock_project_dir, "meta.json")
        assert result is not None
        assert result.name == "meta.json"
        assert result.exists()

    def test_returns_none_when_file_missing(self, mock_project_dir):
        """Returns None when file doesn't exist."""
        result = require_file(mock_project_dir, "missing.json")
        assert result is None

    def test_suggests_command_for_known_stage(self, mock_project_dir, capsys):
        """Prints helpful command suggestion for known pipeline stage."""
        require_file(mock_project_dir, "chunks.json", stage_name="chunks")
        captured = capsys.readouterr()
        assert "vodtool chunks" in captured.out
        assert "create semantic chunks" in captured.out

    def test_finds_stage_without_explicit_name(self, mock_project_dir, capsys):
        """Finds stage by output filename even without stage_name parameter."""
        require_file(mock_project_dir, "transcript_raw.json")
        captured = capsys.readouterr()
        assert "vodtool transcribe" in captured.out


class TestRequirePipelineStage:
    """Tests for require_pipeline_stage()."""

    def test_returns_true_when_all_outputs_exist(self, mock_project_dir):
        """Returns True when all stage output files exist."""
        # Create required files for 'transcribe' stage
        (mock_project_dir / "transcript_raw.json").write_text("{}")

        result = require_pipeline_stage(mock_project_dir, "transcribe")
        assert result is True

    def test_returns_false_when_outputs_missing(self, mock_project_dir):
        """Returns False when any output file is missing."""
        # 'transcribe' requires transcript_raw.json (not present)
        result = require_pipeline_stage(mock_project_dir, "transcribe")
        assert result is False

    def test_returns_false_for_unknown_stage(self, mock_project_dir, capsys):
        """Returns False for unknown stage name."""
        result = require_pipeline_stage(mock_project_dir, "invalid_stage")
        assert result is False
        captured = capsys.readouterr()
        assert "unknown" in captured.out.lower()

    def test_checks_multiple_output_files(self, mock_project_dir):
        """Checks all output files for stages with multiple outputs."""
        # 'ingest' requires both audio.wav and meta.json
        (mock_project_dir / "audio.wav").write_bytes(b"fake audio")
        # meta.json already exists from fixture

        result = require_pipeline_stage(mock_project_dir, "ingest")
        assert result is True

    def test_fails_if_any_output_missing(self, mock_project_dir):
        """Fails if any output file is missing (multi-output stage)."""
        # Create only meta.json, not audio.wav
        result = require_pipeline_stage(mock_project_dir, "ingest")
        assert result is False


class TestCheckPipelineDependencies:
    """Tests for check_pipeline_dependencies()."""

    def test_returns_true_when_dependencies_satisfied(self, mock_project_dir):
        """Returns True when all dependency stages are complete."""
        # 'ingest' has no dependencies
        result = check_pipeline_dependencies(mock_project_dir, "ingest")
        assert result is True

    def test_returns_false_when_dependencies_missing(self, mock_project_dir):
        """Returns False when dependency stages are incomplete."""
        # 'transcribe' requires 'ingest' (audio.wav missing)
        result = check_pipeline_dependencies(mock_project_dir, "transcribe")
        assert result is False

    def test_checks_transitive_dependencies(self, mock_project_dir):
        """Checks all transitive dependencies."""
        # 'chunks' requires 'transcribe' requires 'ingest'
        # None are satisfied yet
        result = check_pipeline_dependencies(mock_project_dir, "chunks")
        assert result is False

        # Satisfy 'ingest'
        (mock_project_dir / "audio.wav").write_bytes(b"fake audio")
        result = check_pipeline_dependencies(mock_project_dir, "chunks")
        assert result is False  # Still need transcribe

        # Satisfy 'transcribe'
        (mock_project_dir / "transcript_raw.json").write_text("{}")
        result = check_pipeline_dependencies(mock_project_dir, "chunks")
        assert result is True  # All dependencies satisfied

    def test_returns_false_for_unknown_stage(self, mock_project_dir):
        """Returns False for unknown stage name."""
        result = check_pipeline_dependencies(mock_project_dir, "invalid_stage")
        assert result is False


class TestPipelineStagesDefinition:
    """Tests for PIPELINE_STAGES constant."""

    def test_all_stages_have_required_fields(self):
        """All pipeline stages have required fields."""
        required_fields = {"output_files", "command", "description"}

        for stage_name, stage_info in PIPELINE_STAGES.items():
            assert all(field in stage_info for field in required_fields), (
                f"Stage '{stage_name}' missing required fields"
            )

    def test_output_files_are_lists(self):
        """All output_files are lists."""
        for stage_name, stage_info in PIPELINE_STAGES.items():
            assert isinstance(stage_info["output_files"], list), (
                f"Stage '{stage_name}' output_files should be a list"
            )

    def test_dependencies_reference_existing_stages(self):
        """All 'requires' dependencies reference valid stages."""
        stage_names = set(PIPELINE_STAGES.keys())

        for stage_name, stage_info in PIPELINE_STAGES.items():
            if "requires" in stage_info:
                for dep in stage_info["requires"]:
                    assert dep in stage_names, (
                        f"Stage '{stage_name}' depends on unknown stage '{dep}'"
                    )

    def test_no_circular_dependencies(self):
        """No circular dependencies in pipeline stages."""

        def has_cycle(stage, visited, stack):
            visited.add(stage)
            stack.add(stage)

            dependencies = PIPELINE_STAGES[stage].get("requires", [])
            for dep in dependencies:
                if dep not in visited:
                    if has_cycle(dep, visited, stack):
                        return True
                elif dep in stack:
                    return True  # Circular dependency found

            stack.remove(stage)
            return False

        for stage in PIPELINE_STAGES:
            assert not has_cycle(stage, set(), set()), (
                f"Circular dependency detected involving stage '{stage}'"
            )
