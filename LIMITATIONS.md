# VideoTool Limitations

This document tracks known limitations of the current implementation. Items marked **[Planned]** are scheduled for future releases (see TODOS.md for details).

---

## Workflow Limitations

### No Manual Topic Editing
- **What:** Cannot manually adjust topic boundaries after LLM segmentation
- **Workaround:** Re-run topic detection with different settings (`--max-topics`, `--provider`)
- **Status:** By design for MVP (keeps workflow simple)

### No Project Save/Reload
- **What:** Stateless workflow - no persistence of intermediate results between commands
- **Impact:** Must keep terminal session open during multi-step workflow
- **Workaround:** Use `videotool pipeline` for end-to-end processing in one command
- **Status:** By design for MVP

### No Checkpoint/Resume on Failure
- **What:** If processing fails mid-pipeline, user must restart from scratch
- **Impact:** Long videos (>2 hours) lose progress if transcription/diarization fails
- **Workaround:** Process smaller segments, or use stable internet for LLM calls
- **Status:** [Planned] - TODO #1 includes retry/resume logic

### Single-File Processing Only
- **What:** No batch queue for processing multiple VODs
- **Impact:** Editors processing 5-10 streams/day must run command for each file
- **Workaround:** Shell script with loop: `for f in *.mp4; do videotool pipeline "$f"; done`
- **Status:** [Planned] - TODO #4

---

## Feature Limitations

### No Visual Timeline
- **What:** No video preview with clickable timeline (YouTube chapters style)
- **Impact:** Cannot preview topics before export
- **Workaround:** Review topic labels and durations in terminal output
- **Status:** [Planned] - TODO #3

### No Segment Editing in Exported Videos
- **What:** Exported videos are exactly the identified topic spans - no manual trimming
- **Impact:** May include brief off-topic moments at segment boundaries
- **Workaround:** Re-run with adjusted settings, or manually edit exported video
- **Status:** By design for MVP

---

## LLM Limitations

### Ollama Not Bundled
- **What:** Local LLM (Ollama) requires separate installation and model download
- **Impact:** ~500MB download on first run, manual setup steps
- **Workaround:** Use Anthropic API (requires ANTHROPIC_API_KEY in .env)
- **Status:** [Planned] - TODO #2 improves Ollama setup flow

### No LLM Result Caching
- **What:** Re-running topic detection on same chunks calls LLM again (costs API credits)
- **Impact:** Iterating on topic settings costs ~$0.50 per run (Anthropic) or 30s (Ollama)
- **Workaround:** Use Ollama for iteration, then Anthropic for final quality pass
- **Status:** Future enhancement (not currently planned)

---

## Platform Limitations

### macOS Primary Platform
- **What:** Developed and tested primarily on macOS (M1/M2 and Intel)
- **Impact:** Linux/Windows may have edge cases (path handling, ffmpeg, file locking)
- **Known issues:**
  - Windows: File locking uses `fcntl` (POSIX only) - needs `msvcrt.locking` fallback
  - Linux: Tested on Ubuntu 22.04, but not extensively validated
- **Status:** Community contributions welcome for platform-specific fixes

### No Windows Native Support
- **What:** File locking (`fcntl`) and signal handling (`SIGALRM`) are POSIX-only
- **Impact:** May not work on Windows without WSL
- **Workaround:** Use WSL2 on Windows, or contribute Windows-compatible locking
- **Status:** [Planned] - Cross-platform file locking after MVP validation

---

## Performance Limitations

### Large Files (>50GB)
- **What:** Warning threshold at 50GB, but tool processes any size
- **Impact:** Very large files (4K streams >3 hours) may exhaust disk space or RAM
- **Known issues:**
  - Whisper transcription loads entire audio into RAM (~10GB for 3hr 1080p stream)
  - Diarization (pyannote) peaks at ~8GB RAM during analysis
- **Workaround:** Process on machine with 16GB+ RAM, ensure 2x file size free disk space
- **Status:** Documented limitation (out of scope for MVP)

### Concurrent Processing Not Supported
- **What:** File locking prevents multiple `videotool` processes on same project
- **Impact:** Cannot run `videotool transcribe` and `videotool diarize` simultaneously
- **Workaround:** Run commands sequentially (or process different projects in parallel)
- **Status:** By design (prevents race conditions)

---

## Test Coverage

### No Automated Tests Yet
- **What:** Core commands lack unit/integration tests
- **Impact:** Regressions possible during development
- **Status:** **[In Progress]** - 17 critical tests being added now (Phase 4 of hardening)

### No E2E Tests
- **What:** No full pipeline tests (ingest → transcribe → chunks → topics → export)
- **Impact:** Integration failures between stages may not be caught before release
- **Status:** [Planned] - TODO #5 includes E2E test suite

---

## Distribution Limitations

### No Pre-built Binaries
- **What:** Must install from source with Python virtual environment
- **Impact:** Non-technical users cannot easily install/run
- **Workaround:** Follow installation steps in README (requires Python 3.9+)
- **Status:** [Planned] - Tauri desktop app (post-hardening) will bundle everything

### Dependencies Not Pinned
- **What:** `pyproject.toml` uses version ranges (e.g., `>=0.9.0`) not exact pins
- **Impact:** `pip install` may pull newer dependency versions with breaking changes
- **Workaround:** Use `pip freeze` to lock dependencies after first install
- **Status:** Will pin before v1.0 release

---

## Known Bugs

None currently tracked. Report issues at: https://github.com/jbmoutout/videotool/issues

---

**Last updated:** 2026-03-26 (v0.1.2)
