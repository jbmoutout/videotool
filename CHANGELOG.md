# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- Initial release of VodTool CLI
- Whisper-based transcription with automatic language detection
- Speaker diarization support for multi-person streams
- Semantic topic detection using embeddings
- LLM-based topic labeling (Anthropic Claude API)
- Local LLM support via Ollama (qwen2.5:3b, llama3.2:3b, gemma2:2b)
- Topic comparison between Claude and Ollama (`compare-llm` command)
- Video export with topic-focused cutting
- Full pipeline command for end-to-end processing
- Debug commands: list-topics, show-topics, explain-chunk, inspect-topic
