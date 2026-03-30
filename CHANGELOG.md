# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.7] - 2026-03-30

### Fixed
- Fix proxy URL not forwarded to Python CLI in release builds (filter empty strings)
- Add diagnostic logging for proxy config to aid debugging
- Harden Windows CI: retry Chocolatey installs (3 attempts, 10s backoff), drop unused yt-dlp

## [0.1.6] - 2026-03-30

### Fixed
- CI release verification now locates target-specific macOS bundles and inspects Windows installers for embedded CLI binaries

## [0.1.5] - 2026-03-30

### Added
- Bundle ffmpeg/ffprobe inside the app so the pipeline runs fully standalone

### Changed
- Twitch VOD downloads now use the Streamlink Python API (no external CLI dependency)
- CLI command imports are lazy-loaded to avoid PyInstaller crashes on missing ML deps
- Release workflow now bundles ffmpeg/ffprobe on macOS and Windows

### Fixed
- App now passes bundled ffmpeg path to the CLI at runtime for reliable media processing
- Local builds now load `.env` values when no proxy or API keys are set in the environment

## [0.1.4] - 2026-03-30

### Added
- Debug-only log of the resolved CLI path to simplify release spawn troubleshooting

### Changed
- Release setup docs now call out the `hdiutil` sandbox limitation during DMG bundling

### Fixed
- Tauri release builds now locate the bundled `videotool` binary across resource locations and target-suffixed names, and fail fast if missing
- Viewer [home] button now navigates back to the Tauri app in release builds (tauri:// origin)

## [0.1.3] - 2026-03-30

### Changed
- Slimmed release bundle from 141 to 43 Python packages — removed unused ML deps (torch, whisper, pyannote, scikit-learn) since the Tauri app uses API providers
- Fixed CI release workflow: use matrix target triple for cross-compilation binary naming
- Synced all version numbers across Cargo.toml, package.json, tauri.conf.json, pyproject.toml, and __init__.py

## [0.1.2] - 2026-03-26

### Added
- File locking (`project_lock()`) to prevent concurrent modifications across commands
- Safe JSON utilities with atomic writes (write to temp file, then rename)
- Input validation utilities for project paths, video files, and disk space checks
- Pipeline dependency management system for tracking stage requirements
- LLM retry logic with exponential backoff and configurable timeouts (60s Anthropic, 120s Ollama)
- Timeout protection for ffprobe calls (30s) to prevent hanging on corrupted files

### Changed
- Refactored all commands to use centralized validation, file locking, and safe JSON operations
- Projects now stored in `~/.videotool/projects` instead of `./projects`
- Error messages now include helpful suggestions for missing pipeline dependencies
- Improved error handling with specific exception types instead of broad `Exception` catches

### Fixed
- Line-too-long linter errors in llm_topics.py
- Redundant IOError exception (Python 3 alias) in transcribe.py
- Added cleanup on ingest failure (removes partial project directory)

## [0.1.1] - 2026-03-26

### Added
- TODOS.md with comprehensive implementation roadmap from engineering review
  - TODO #1: Harden Python CLI before Tauri wrapper (17 critical tests, branch cleanup)
  - TODO #2: Add Ollama support for free/local LLM processing
  - TODO #3: Add visual timeline with video preview (YouTube chapters style)
  - TODO #4: Add batch processing queue for multiple VODs
  - TODO #5: Expand test coverage to 100% (47 total tests)

### Changed
- Updated .gitignore to exclude gstack and Claude Code user-specific files

## [0.1.0] - 2026-03-25

### Added
- Initial release of VideoTool CLI
- Whisper-based transcription with automatic language detection
- Speaker diarization support for multi-person streams
- Semantic topic detection using embeddings
- LLM-based topic labeling (Anthropic Claude API)
- Local LLM support via Ollama (qwen2.5:3b, llama3.2:3b, gemma2:2b)
- Topic comparison between Claude and Ollama (`compare-llm` command)
- Video export with topic-focused cutting
- Full pipeline command for end-to-end processing
- Debug commands: list-topics, show-topics, explain-chunk, inspect-topic
