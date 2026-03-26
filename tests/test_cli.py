"""Tests for vodtool.cli module."""

from pathlib import Path
from unittest import mock

import pytest
from typer.testing import CliRunner

from vodtool.cli import app, version_callback


runner = CliRunner()


class TestVersionCallback:
    """Tests for version_callback()."""

    def test_prints_version_and_exits(self, capsys):
        """Prints version and raises Exit when value is True."""
        from typer import Exit

        with pytest.raises(Exit):
            version_callback(True)

        captured = capsys.readouterr()
        assert "vodtool version" in captured.out

    def test_does_nothing_when_false(self):
        """Does nothing when value is False."""
        # Should not raise
        version_callback(False)


class TestMainCallback:
    """Tests for main callback (global options)."""

    def test_version_flag_shows_version(self):
        """--version flag displays version and exits."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "vodtool version" in result.stdout

    def test_help_flag_shows_help(self):
        """--help flag displays help text."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "vodtool" in result.stdout
        assert "transcript-first tool" in result.stdout

    def test_ffmpeg_path_option_sets_state(self):
        """--ffmpeg-path option sets app state."""
        # Test requires invoking a command to access app.state
        # We'll use ingest and mock it to check the ffmpeg_path
        with mock.patch("vodtool.cli.ingest_video") as mock_ingest:
            mock_ingest.return_value = Path("/tmp/project")

            result = runner.invoke(
                app,
                ["--ffmpeg-path", "/custom/ffmpeg", "ingest", "test.mp4"],
            )

            # Check that ingest_video was called with custom ffmpeg path
            assert mock_ingest.call_count == 1
            args, kwargs = mock_ingest.call_args
            assert args[1] == "/custom/ffmpeg"  # ffmpeg_path parameter


class TestCommandRegistration:
    """Tests for command registration (smoke tests)."""

    def test_ingest_command_exists(self):
        """Ingest command is registered."""
        result = runner.invoke(app, ["ingest", "--help"])
        assert result.exit_code == 0
        assert "Ingest a video file" in result.stdout

    def test_transcribe_command_exists(self):
        """Transcribe command is registered."""
        result = runner.invoke(app, ["transcribe", "--help"])
        assert result.exit_code == 0
        assert "Transcribe audio" in result.stdout

    def test_chunks_command_exists(self):
        """Chunks command is registered."""
        result = runner.invoke(app, ["chunks", "--help"])
        assert result.exit_code == 0

    def test_topics_command_exists(self):
        """Topics command is registered."""
        result = runner.invoke(app, ["topics", "--help"])
        assert result.exit_code == 0

    def test_export_command_exists(self):
        """Export command is registered."""
        result = runner.invoke(app, ["export", "--help"])
        assert result.exit_code == 0

    def test_cutplan_command_exists(self):
        """Cutplan command is registered."""
        result = runner.invoke(app, ["cutplan", "--help"])
        assert result.exit_code == 0

    def test_llm_topics_command_exists(self):
        """LLM topics command is registered."""
        result = runner.invoke(app, ["llm-topics", "--help"])
        assert result.exit_code == 0


class TestIngestCommand:
    """Tests for ingest command."""

    def test_exits_with_error_when_ingest_fails(self):
        """CLI exits with code 1 when ingest_video returns None."""
        with mock.patch("vodtool.cli.ingest_video") as mock_ingest:
            mock_ingest.return_value = None  # Failure

            result = runner.invoke(app, ["ingest", "test.mp4"])

            assert result.exit_code == 1

    def test_succeeds_when_ingest_returns_project_dir(self):
        """CLI exits with code 0 when ingest_video succeeds."""
        with mock.patch("vodtool.cli.ingest_video") as mock_ingest:
            mock_ingest.return_value = Path("/tmp/project")

            result = runner.invoke(app, ["ingest", "test.mp4"])

            assert result.exit_code == 0


class TestTranscribeCommand:
    """Tests for transcribe command."""

    def test_passes_model_option_to_transcribe_audio(self):
        """--model option is passed to transcribe_audio."""
        with mock.patch("vodtool.cli.transcribe_audio") as mock_transcribe:
            result = runner.invoke(
                app,
                ["transcribe", "/tmp/project", "--model", "large"],
            )

            mock_transcribe.assert_called_once()
            args, kwargs = mock_transcribe.call_args
            assert args[1] == "large"  # model parameter

    def test_passes_language_option_to_transcribe_audio(self):
        """--language option is passed to transcribe_audio."""
        with mock.patch("vodtool.cli.transcribe_audio") as mock_transcribe:
            result = runner.invoke(
                app,
                ["transcribe", "/tmp/project", "--language", "fr"],
            )

            mock_transcribe.assert_called_once()
            args, kwargs = mock_transcribe.call_args
            # Parameter order: project_path, model, force, language
            assert args[3] == "fr"  # language parameter (4th arg)

    def test_passes_force_option_to_transcribe_audio(self):
        """--force option is passed to transcribe_audio."""
        with mock.patch("vodtool.cli.transcribe_audio") as mock_transcribe:
            result = runner.invoke(
                app,
                ["transcribe", "/tmp/project", "--force"],
            )

            mock_transcribe.assert_called_once()
            args, kwargs = mock_transcribe.call_args
            # Parameter order: project_path, model, force, language
            assert args[2] is True  # force parameter (3rd arg)


class TestExportCommand:
    """Tests for export command."""

    def test_calls_export_video_with_project_path(self):
        """Export command calls export_video with project path and ffmpeg path."""
        with mock.patch("vodtool.cli.export_video") as mock_export:
            mock_export.return_value = Path("/tmp/output.mp4")

            result = runner.invoke(
                app,
                ["export", "/tmp/project"],
            )

            mock_export.assert_called_once()
            args, kwargs = mock_export.call_args
            assert args[0] == Path("/tmp/project")  # project_path
            assert args[1] == "ffmpeg"  # ffmpeg_path (default)

    def test_exits_with_error_when_export_fails(self):
        """CLI exits with code 1 when export_video returns None."""
        with mock.patch("vodtool.cli.export_video") as mock_export:
            mock_export.return_value = None  # Failure

            result = runner.invoke(app, ["export", "/tmp/project"])

            assert result.exit_code == 1
