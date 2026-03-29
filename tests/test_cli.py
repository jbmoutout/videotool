"""Tests for vodtool.cli module."""

import json
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


class TestPipelineJsonProgress:
    """Tests for vodtool pipeline --json-progress flag."""

    def test_json_progress_emits_json_lines(self, tmp_path):
        """--json-progress flag produces parseable JSON lines on stdout."""
        import json

        with mock.patch("vodtool.cli.ingest_video") as mock_ingest, \
             mock.patch("vodtool.cli.transcribe_audio") as mock_transcribe, \
             mock.patch("vodtool.cli.create_chunks") as mock_chunks, \
             mock.patch("vodtool.cli.embed_chunks") as mock_embed, \
             mock.patch("vodtool.cli.llm_topics") as mock_llm:
            project = tmp_path / "project"
            project.mkdir()
            topic_file = project / "topic_map_llm.json"
            topic_file.write_text('[{"topic_id":"t1"}]')
            mock_ingest.return_value = project
            mock_transcribe.return_value = project / "transcript_raw.json"
            mock_chunks.return_value = project / "chunks.json"
            mock_embed.return_value = project / "embeddings.sqlite"
            mock_llm.return_value = topic_file

            result = runner.invoke(app, ["pipeline", "--json-progress", str(tmp_path / "video.mp4")])

        assert result.exit_code == 0
        lines = [l for l in result.output.strip().splitlines() if l.strip()]
        parsed = [json.loads(l) for l in lines]
        # 5 progress lines + 1 done line = 6
        progress_lines = [p for p in parsed if "step" in p and "error" not in p]
        done_lines = [p for p in parsed if p.get("done")]
        assert len(progress_lines) == 5
        for i, obj in enumerate(progress_lines, start=1):
            assert obj["step"] == i
            assert obj["total"] == 5
            assert "pct" in obj
            assert "msg" in obj
        assert len(done_lines) == 1

    def test_json_progress_step_failure_emits_error(self, tmp_path):
        """When a step fails with --json-progress, stdout contains an error object."""
        import json

        with mock.patch("vodtool.cli.ingest_video") as mock_ingest, \
             mock.patch("vodtool.cli.transcribe_audio") as mock_transcribe:
            mock_ingest.return_value = tmp_path / "project"
            mock_transcribe.return_value = None  # step 2 fails

            result = runner.invoke(app, ["pipeline", "--json-progress", str(tmp_path / "video.mp4")])

        assert result.exit_code == 1
        lines = [l for l in result.output.strip().splitlines() if l.strip()]
        parsed = [json.loads(l) for l in lines]
        error_lines = [p for p in parsed if "error" in p]
        assert len(error_lines) == 1
        assert error_lines[0]["step"] == 2

    def test_no_json_progress_uses_rich_output(self, tmp_path):
        """Without --json-progress, output uses Rich text format (no JSON)."""
        import json

        with mock.patch("vodtool.cli.ingest_video") as mock_ingest, \
             mock.patch("vodtool.cli.transcribe_audio") as mock_transcribe, \
             mock.patch("vodtool.cli.create_chunks") as mock_chunks, \
             mock.patch("vodtool.cli.embed_chunks") as mock_embed, \
             mock.patch("vodtool.cli.llm_topics") as mock_llm:
            project = tmp_path / "project"
            project.mkdir()
            topic_file = project / "topic_map_llm.json"
            topic_file.write_text('[{"topic_id":"t1"}]')
            mock_ingest.return_value = project
            mock_transcribe.return_value = project / "transcript_raw.json"
            mock_chunks.return_value = project / "chunks.json"
            mock_embed.return_value = project / "embeddings.sqlite"
            mock_llm.return_value = topic_file

            result = runner.invoke(app, ["pipeline", str(tmp_path / "video.mp4")])

        assert result.exit_code == 0
        # No JSON lines in output
        for line in result.output.splitlines():
            if line.strip():
                try:
                    json.loads(line)
                    assert False, f"Unexpected JSON line in non-json-progress output: {line}"
                except (json.JSONDecodeError, ValueError):
                    pass  # expected — plain text output


class TestPipelineIpc:
    """Tests for pipeline --json-progress IPC protocol (Tauri integration)."""

    def _mock_successful_pipeline(self, tmp_path, mock_ingest, mock_transcribe,
                                   mock_chunks, mock_embed, mock_llm):
        """Set up all pipeline step mocks for a successful run."""
        project = tmp_path / "project"
        project.mkdir()
        topic_map = project / "topic_map_llm.json"
        topic_map.write_text('[{"topic_id":"topic_0000"},{"topic_id":"topic_0001"},{"topic_id":"topic_0002"}]')
        mock_ingest.return_value = project
        mock_transcribe.return_value = project / "transcript_raw.json"
        mock_chunks.return_value = project / "chunks.json"
        mock_embed.return_value = project / "embeddings.sqlite"
        mock_llm.return_value = topic_map

    def test_progress_lines_have_correct_schema(self, tmp_path):
        """Each progress line is valid JSON with step/total/pct/msg fields."""
        import json

        with mock.patch("vodtool.cli.ingest_video") as mi, \
             mock.patch("vodtool.cli.transcribe_audio") as mt, \
             mock.patch("vodtool.cli.create_chunks") as mc, \
             mock.patch("vodtool.cli.embed_chunks") as me, \
             mock.patch("vodtool.cli.llm_topics") as ml:
            self._mock_successful_pipeline(tmp_path, mi, mt, mc, me, ml)
            result = runner.invoke(app, ["pipeline", "--json-progress", str(tmp_path / "video.mp4")])

        assert result.exit_code == 0
        progress_lines = []
        for line in result.output.splitlines():
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if "step" in obj and "done" not in obj:
                progress_lines.append(obj)

        assert len(progress_lines) == 5  # one per pipeline step
        for obj in progress_lines:
            assert "step" in obj
            assert "total" in obj
            assert "pct" in obj
            assert "msg" in obj
            assert obj["total"] == 5
            assert 0.0 <= obj["pct"] <= 1.0

    def test_done_message_emitted_on_success(self, tmp_path):
        """On success, last JSON line is {done:true, project_dir:..., topic_count:N}."""
        import json

        with mock.patch("vodtool.cli.ingest_video") as mi, \
             mock.patch("vodtool.cli.transcribe_audio") as mt, \
             mock.patch("vodtool.cli.create_chunks") as mc, \
             mock.patch("vodtool.cli.embed_chunks") as me, \
             mock.patch("vodtool.cli.llm_topics") as ml:
            self._mock_successful_pipeline(tmp_path, mi, mt, mc, me, ml)
            result = runner.invoke(app, ["pipeline", "--json-progress", str(tmp_path / "video.mp4")])

        assert result.exit_code == 0
        json_lines = [json.loads(l) for l in result.output.splitlines() if l.strip()]
        done_lines = [obj for obj in json_lines if obj.get("done") is True]

        assert len(done_lines) == 1
        done = done_lines[0]
        assert done["done"] is True
        assert "project_dir" in done
        assert isinstance(done["topic_count"], int)

    def test_done_topic_count_matches_topic_map(self, tmp_path):
        """done.topic_count equals the number of topics in topic_map_llm.json."""
        import json

        with mock.patch("vodtool.cli.ingest_video") as mi, \
             mock.patch("vodtool.cli.transcribe_audio") as mt, \
             mock.patch("vodtool.cli.create_chunks") as mc, \
             mock.patch("vodtool.cli.embed_chunks") as me, \
             mock.patch("vodtool.cli.llm_topics") as ml:
            self._mock_successful_pipeline(tmp_path, mi, mt, mc, me, ml)
            result = runner.invoke(app, ["pipeline", "--json-progress", str(tmp_path / "video.mp4")])

        assert result.exit_code == 0
        json_lines = [json.loads(l) for l in result.output.splitlines() if l.strip()]
        done = next(obj for obj in json_lines if obj.get("done") is True)

        # _mock_successful_pipeline writes 3 topics
        assert done["topic_count"] == 3

    def test_error_line_emitted_on_step_failure(self, tmp_path):
        """When a step fails, stdout contains {error:..., step:N} and exit code is 1."""
        import json

        with mock.patch("vodtool.cli.ingest_video") as mi, \
             mock.patch("vodtool.cli.transcribe_audio") as mt:
            mi.return_value = tmp_path / "project"
            mt.return_value = None  # step 2 fails

            result = runner.invoke(app, ["pipeline", "--json-progress", str(tmp_path / "video.mp4")])

        assert result.exit_code == 1
        json_lines = [json.loads(l) for l in result.output.splitlines() if l.strip()]
        error_lines = [obj for obj in json_lines if "error" in obj]

        assert len(error_lines) == 1
        assert error_lines[0]["step"] == 2
        assert isinstance(error_lines[0]["error"], str)
        # No done message on failure
        assert not any(obj.get("done") is True for obj in json_lines)


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


class TestBeatsJsonProgress:
    """Tests for vodtool beats --json-progress output."""

    def _mock_successful_beats(self, tmp_path, mock_ingest, mock_transcribe,
                                mock_detect):
        """Set up all beats step mocks for a successful run."""
        project = tmp_path / "project"
        project.mkdir()
        beats_file = project / "beats.json"
        beats_file.write_text(json.dumps({
            "beats": [
                {
                    "topic": "Intro",
                    "beats": [
                        {"type": "hook", "start_s": 0, "end_s": 60},
                        {"type": "build", "start_s": 60, "end_s": 120},
                    ],
                },
                {
                    "topic": "Main",
                    "beats": [
                        {"type": "peak", "start_s": 120, "end_s": 180},
                    ],
                },
            ]
        }))
        mock_ingest.return_value = project
        mock_transcribe.return_value = project / "transcript_raw.json"
        mock_detect.return_value = beats_file

    def test_no_beats_ready_event(self, tmp_path):
        """beats_ready is no longer emitted — only done."""
        with mock.patch("vodtool.cli.ingest_video") as mi, \
             mock.patch("vodtool.cli.transcribe_audio") as mt, \
             mock.patch("vodtool.cli.detect_beats") as md:
            self._mock_successful_beats(tmp_path, mi, mt, md)
            result = runner.invoke(
                app, ["beats", "--json-progress", str(tmp_path / "video.mp4")]
            )

        assert result.exit_code == 0
        lines = [json.loads(l) for l in result.output.splitlines() if l.strip()]
        assert not any(obj.get("beats_ready") for obj in lines)
        assert not any(obj.get("video_ready") for obj in lines)

    def test_done_event_emitted(self, tmp_path):
        """On success, done event with beat_count and topic_count is emitted."""
        with mock.patch("vodtool.cli.ingest_video") as mi, \
             mock.patch("vodtool.cli.transcribe_audio") as mt, \
             mock.patch("vodtool.cli.detect_beats") as md:
            self._mock_successful_beats(tmp_path, mi, mt, md)
            result = runner.invoke(
                app, ["beats", "--json-progress", str(tmp_path / "video.mp4")]
            )

        assert result.exit_code == 0
        lines = [json.loads(l) for l in result.output.splitlines() if l.strip()]
        done_lines = [obj for obj in lines if obj.get("done") is True]
        assert len(done_lines) == 1
        done = done_lines[0]
        assert done["topic_count"] == 2
        assert done["beat_count"] == 3
        assert "project_dir" in done

    def test_three_progress_steps(self, tmp_path):
        """Beats pipeline emits 3 step progress events."""
        with mock.patch("vodtool.cli.ingest_video") as mi, \
             mock.patch("vodtool.cli.transcribe_audio") as mt, \
             mock.patch("vodtool.cli.detect_beats") as md:
            self._mock_successful_beats(tmp_path, mi, mt, md)
            result = runner.invoke(
                app, ["beats", "--json-progress", str(tmp_path / "video.mp4")]
            )

        assert result.exit_code == 0
        lines = [json.loads(l) for l in result.output.splitlines() if l.strip()]
        progress_lines = [
            obj for obj in lines
            if "step" in obj and "done" not in obj and "error" not in obj
        ]
        assert len(progress_lines) == 3
        for obj in progress_lines:
            assert obj["total"] == 3

    def test_step1_msg_says_downloading_video(self, tmp_path):
        """Step 1 sub-events say 'Downloading video' not 'Downloading audio'."""
        download_msgs = []

        def fake_ingest(path, ffmpeg="ffmpeg", quality="worst",
                        download_progress_callback=None, status_callback=None):
            # Simulate download progress callback
            if download_progress_callback:
                download_progress_callback(0.5)
            project = tmp_path / "project"
            project.mkdir(exist_ok=True)
            return project

        project = tmp_path / "project"
        project.mkdir(exist_ok=True)

        with mock.patch("vodtool.cli.ingest_video", side_effect=fake_ingest), \
             mock.patch("vodtool.cli.transcribe_audio") as mt, \
             mock.patch("vodtool.cli.detect_beats") as md:
            mt.return_value = project / "transcript_raw.json"
            beats_file = project / "beats.json"
            beats_file.write_text('{"beats":[]}')
            md.return_value = beats_file
            result = runner.invoke(
                app, ["beats", "--json-progress", str(tmp_path / "video.mp4")]
            )

        lines = [json.loads(l) for l in result.output.splitlines() if l.strip()]
        download_events = [
            obj for obj in lines if obj.get("download_pct") is not None
        ]
        for evt in download_events:
            assert "Downloading video" in evt["msg"]
            assert "audio" not in evt["msg"].lower()

    def test_error_on_beat_detection_failure(self, tmp_path):
        """When beat detection fails, error event is emitted."""
        with mock.patch("vodtool.cli.ingest_video") as mi, \
             mock.patch("vodtool.cli.transcribe_audio") as mt, \
             mock.patch("vodtool.cli.detect_beats") as md:
            project = tmp_path / "project"
            project.mkdir()
            mi.return_value = project
            mt.return_value = project / "transcript_raw.json"
            md.return_value = None  # Beat detection fails

            result = runner.invoke(
                app, ["beats", "--json-progress", str(tmp_path / "video.mp4")]
            )

        assert result.exit_code == 1
        lines = [json.loads(l) for l in result.output.splitlines() if l.strip()]
        error_lines = [obj for obj in lines if "error" in obj]
        assert len(error_lines) == 1
        assert error_lines[0]["step"] == 3


class TestProgressContract:
    """Verify the JSON progress contract between Python CLI and Tauri frontend."""

    def _run_beats_pipeline(self, tmp_path):
        """Run a mocked beats pipeline and return all JSON lines."""
        with mock.patch("vodtool.cli.ingest_video") as mi, \
             mock.patch("vodtool.cli.transcribe_audio") as mt, \
             mock.patch("vodtool.cli.detect_beats") as md:
            project = tmp_path / "project"
            project.mkdir()
            beats_file = project / "beats.json"
            beats_file.write_text('{"beats":[{"topic":"T","beats":[{"type":"hook","start_s":0,"end_s":60}]}]}')
            mi.return_value = project
            mt.return_value = project / "transcript_raw.json"
            md.return_value = beats_file

            result = runner.invoke(
                app, ["beats", "--json-progress", str(tmp_path / "video.mp4")]
            )

        assert result.exit_code == 0
        return [json.loads(l) for l in result.output.splitlines() if l.strip()]

    def test_all_lines_are_valid_json(self, tmp_path):
        """Every line emitted with --json-progress is parseable JSON."""
        with mock.patch("vodtool.cli.ingest_video") as mi, \
             mock.patch("vodtool.cli.transcribe_audio") as mt, \
             mock.patch("vodtool.cli.detect_beats") as md:
            project = tmp_path / "project"
            project.mkdir()
            beats_file = project / "beats.json"
            beats_file.write_text('{"beats":[]}')
            mi.return_value = project
            mt.return_value = project / "transcript_raw.json"
            md.return_value = beats_file

            result = runner.invoke(
                app, ["beats", "--json-progress", str(tmp_path / "video.mp4")]
            )

        for line in result.output.splitlines():
            if line.strip():
                json.loads(line)  # Should not raise

    def test_step_field_range(self, tmp_path):
        """step is always 1 <= step <= total."""
        lines = self._run_beats_pipeline(tmp_path)
        for obj in lines:
            if "step" in obj:
                assert 1 <= obj["step"] <= obj["total"]

    def test_pct_range(self, tmp_path):
        """pct is always 0.0 <= pct <= 1.0."""
        lines = self._run_beats_pipeline(tmp_path)
        for obj in lines:
            if "pct" in obj:
                assert 0.0 <= obj["pct"] <= 1.0

    def test_download_pct_range(self, tmp_path):
        """download_pct, when present, is 0 <= download_pct <= 100."""
        project = tmp_path / "project"
        project.mkdir()

        def fake_ingest(path, ffmpeg="ffmpeg", quality="worst",
                        download_progress_callback=None, status_callback=None):
            if download_progress_callback:
                for pct in [0.0, 0.25, 0.5, 0.75, 1.0]:
                    download_progress_callback(pct)
            return project

        beats_file = project / "beats.json"
        beats_file.write_text('{"beats":[]}')

        with mock.patch("vodtool.cli.ingest_video", side_effect=fake_ingest), \
             mock.patch("vodtool.cli.transcribe_audio") as mt, \
             mock.patch("vodtool.cli.detect_beats") as md:
            mt.return_value = project / "transcript_raw.json"
            md.return_value = beats_file

            result = runner.invoke(
                app, ["beats", "--json-progress", str(tmp_path / "video.mp4")]
            )

        lines = [json.loads(l) for l in result.output.splitlines() if l.strip()]
        for obj in lines:
            if "download_pct" in obj and obj["download_pct"] is not None:
                assert 0 <= obj["download_pct"] <= 100

    def test_terminal_event_always_emitted(self, tmp_path):
        """Pipeline always emits exactly one terminal event: done OR error."""
        lines = self._run_beats_pipeline(tmp_path)
        done_count = sum(1 for obj in lines if obj.get("done") is True)
        error_count = sum(1 for obj in lines if "error" in obj and "step" in obj)
        assert done_count + error_count == 1
        assert done_count == 1  # success case

    def test_done_event_has_required_fields(self, tmp_path):
        """done event has: done=true, project_dir, topic_count, beat_count."""
        lines = self._run_beats_pipeline(tmp_path)
        done = next(obj for obj in lines if obj.get("done") is True)
        assert done["done"] is True
        assert isinstance(done["project_dir"], str)
        assert isinstance(done["topic_count"], int)
        assert isinstance(done["beat_count"], int)

    def test_error_event_has_required_fields(self, tmp_path):
        """error event has: error (string), step (int)."""
        with mock.patch("vodtool.cli.ingest_video") as mi, \
             mock.patch("vodtool.cli.transcribe_audio") as mt:
            mi.return_value = tmp_path
            mt.return_value = None  # step 2 fails

            result = runner.invoke(
                app, ["beats", "--json-progress", str(tmp_path / "video.mp4")]
            )

        assert result.exit_code == 1
        lines = [json.loads(l) for l in result.output.splitlines() if l.strip()]
        error = next(obj for obj in lines if "error" in obj)
        assert isinstance(error["error"], str)
        assert isinstance(error["step"], int)
        assert len(error["error"]) > 0
