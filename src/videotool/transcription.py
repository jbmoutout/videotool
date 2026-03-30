"""Transcription provider abstraction for videotool.

Defines the TranscriptionProvider Protocol and two implementations:
- OpenAITranscriptionProvider: uses OpenAI Whisper API with chunking for >25MB files
- GroqTranscriptionProvider: uses Groq Whisper API (whisper-large-v3-turbo by default)
  — same chunking logic, ~10-20x faster than OpenAI for long files

Audio chunking strategy:
  Both APIs have a ~25MB file size limit. A 4-hour VOD produces 200-400MB
  of audio. Files exceeding the limit are split into CHUNK_DURATION_SECONDS segments,
  each transcribed independently, then stitched with timestamp offsets applied.

  CRITICAL: each chunk's timestamps are relative (start at 0s). When stitching,
  chunk N's timestamps must be offset by (N * chunk_duration) seconds so that a
  word at 2h30m appears at 9000s, not 0s.
"""

import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger("videotool")

MAX_CONCURRENT_TRANSCRIPTIONS = 4

WHISPER_MAX_BYTES = 25 * 1024 * 1024  # 25 MB
CHUNK_DURATION_SECONDS = 600  # 10 minutes per chunk


@runtime_checkable
class TranscriptionProvider(Protocol):
    """Protocol for transcription providers."""

    def transcribe(self, audio_path: Path, language: Optional[str] = None) -> dict:
        """
        Transcribe an audio file.

        Args:
            audio_path: Path to the audio file
            language: BCP-47 language code (e.g. "fr", "en"). Auto-detect if None.

        Returns:
            dict with keys:
              "language": str
              "model": str
              "segments": list of {"start": float, "end": float, "text": str}
        """
        ...


class _WhisperAPIBase:
    """Shared transcription logic for OpenAI-compatible Whisper APIs."""

    _client: object
    _model: str

    def transcribe(self, audio_path: Path, language: Optional[str] = None) -> dict:
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        if audio_path.stat().st_size <= WHISPER_MAX_BYTES:
            return self._transcribe_file(audio_path, language, offset_seconds=0.0)

        return self._transcribe_chunked(audio_path, language)

    def _transcribe_file(
        self, audio_path: Path, language: Optional[str], offset_seconds: float
    ) -> dict:
        kwargs: dict = {"model": self._model, "response_format": "verbose_json"}
        if language:
            kwargs["language"] = language

        with audio_path.open("rb") as f:
            response = self._client.audio.transcriptions.create(file=f, **kwargs)  # type: ignore[attr-defined]

        segments = [
            {
                "start": seg.start + offset_seconds,
                "end": seg.end + offset_seconds,
                "text": seg.text.strip(),
            }
            for seg in response.segments
        ]

        return {
            "language": response.language,
            "model": self._model,
            "segments": segments,
        }

    def _transcribe_chunked(self, audio_path: Path, language: Optional[str]) -> dict:
        total_duration = _probe_duration(audio_path)
        n_chunks = max(1, int(total_duration / CHUNK_DURATION_SECONDS) + 1)

        # Build list of (index, offset) for chunks that fall within duration
        chunk_specs = [
            (i, i * CHUNK_DURATION_SECONDS)
            for i in range(n_chunks)
            if i * CHUNK_DURATION_SECONDS < total_duration
        ]

        logger.info(
            f"Transcribing {len(chunk_specs)} chunks "
            f"({CHUNK_DURATION_SECONDS}s each, {MAX_CONCURRENT_TRANSCRIPTIONS} workers)"
        )

        detected_language: str = "unknown"

        with tempfile.TemporaryDirectory() as tmp_dir:

            def _process_chunk(spec: tuple[int, float]) -> tuple[int, dict]:
                idx, offset = spec
                chunk_path = Path(tmp_dir) / f"chunk_{idx:04d}.mp3"
                _extract_chunk(audio_path, chunk_path, start=offset, duration=CHUNK_DURATION_SECONDS)
                try:
                    result = self._transcribe_file(chunk_path, language, offset_seconds=offset)
                except Exception as e:
                    raise RuntimeError(
                        f"Transcription failed on chunk {idx + 1} of {len(chunk_specs)}: {e}"
                    ) from e
                return idx, result

            results: dict[int, dict] = {}
            with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TRANSCRIPTIONS) as executor:
                futures = {executor.submit(_process_chunk, spec): spec[0] for spec in chunk_specs}
                for future in as_completed(futures):
                    idx, result = future.result()
                    results[idx] = result
                    if detected_language == "unknown" and result["language"] != "unknown":
                        detected_language = result["language"]
                    logger.info(f"  chunk {idx + 1}/{len(chunk_specs)} done")

            # Reassemble segments in order
            all_segments: list[dict] = []
            for i in sorted(results):
                all_segments.extend(results[i]["segments"])

        return {
            "language": detected_language,
            "model": self._model,
            "segments": _deduplicate_boundary_segments(all_segments),
        }


class OpenAITranscriptionProvider(_WhisperAPIBase):
    """Transcribes audio using the OpenAI Whisper API (whisper-1).

    Automatically chunks files larger than 25MB and stitches results with
    correct timestamp offsets.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "whisper-1"):
        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")
        try:
            import openai
        except ImportError:
            raise ImportError("openai package not installed. Run: pip install openai")
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model


class GroqTranscriptionProvider(_WhisperAPIBase):
    """Transcribes audio using the Groq Whisper API.

    Uses the OpenAI-compatible Groq endpoint — ~10-20x faster than OpenAI
    thanks to Groq's LPU hardware. Runs whisper-large-v3-turbo by default,
    which is also more accurate than OpenAI's whisper-1 (medium-based).

    Available models:
      whisper-large-v3-turbo       — default, fast + accurate
      whisper-large-v3             — max accuracy, slightly slower
      distil-whisper-large-v3-en   — English only, fastest

    Requires GROQ_API_KEY or VITE_API_PROXY_URL. Get a key at console.groq.com.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "whisper-large-v3-turbo"):
        api_key = api_key or os.environ.get("GROQ_API_KEY")
        proxy_url = os.environ.get("VITE_API_PROXY_URL")
        if not api_key and not proxy_url:
            raise ValueError(
                "GROQ_API_KEY not set and no proxy configured. "
                "Set GROQ_API_KEY or VITE_API_PROXY_URL in .env"
            )
        try:
            import openai
        except ImportError:
            raise ImportError("openai package not installed. Run: pip install openai")
        extra_headers = {}
        if api_key:
            base_url = "https://api.groq.com/openai/v1"
        else:
            base_url = f"{proxy_url.rstrip('/')}/groq"
            logger.info("Using proxy for Groq transcription")
            auth_token = os.environ.get("PROXY_AUTH_TOKEN")
            if auth_token:
                extra_headers["X-Proxy-Token"] = auth_token
        self._client = openai.OpenAI(
            api_key=api_key or "proxy",
            base_url=base_url,
            default_headers=extra_headers or None,
        )
        self._model = model


def _probe_duration(audio_path: Path) -> float:
    """Return audio duration in seconds using ffprobe."""
    import subprocess

    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")
    return float(result.stdout.strip())


def _extract_chunk(audio_path: Path, output_path: Path, start: float, duration: float) -> None:
    """Extract a time slice from audio_path into output_path as MP3."""
    import subprocess

    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-t", str(duration),
            "-i", str(audio_path),
            "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k",
            str(output_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg chunk extraction failed: {result.stderr.strip()}")


def _deduplicate_boundary_segments(segments: list[dict]) -> list[dict]:
    """Remove duplicate segments that appear at chunk boundaries.

    Whisper occasionally re-emits the last sentence of a chunk at the start of
    the next chunk. We drop any segment whose text duplicates the immediately
    preceding segment's text (case-insensitive, stripped).
    """
    if not segments:
        return segments

    deduped: list[dict] = [segments[0]]
    for seg in segments[1:]:
        if seg["text"].strip().lower() != deduped[-1]["text"].strip().lower():
            deduped.append(seg)
    return deduped
