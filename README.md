 █████   █████    ███████    ██████████      ███████████    ███████       ███████    █████
░░███   ░░███   ███░░░░░███ ░░███░░░░███    ░█░░░███░░░█  ███░░░░░███   ███░░░░░███ ░░███
 ░███    ░███  ███     ░░███ ░███   ░░███   ░   ░███  ░  ███     ░░███ ███     ░░███ ░███
 ░███    ░███ ░███      ░███ ░███    ░███       ░███    ░███      ░███░███      ░███ ░███
 ░░███   ███  ░███      ░███ ░███    ░███       ░███    ░███      ░███░███      ░███ ░███
  ░░░█████░   ░░███     ███  ░███    ███        ░███    ░░███     ███ ░░███     ███  ░███      █
    ░░███      ░░░███████░   ██████████         █████    ░░░███████░   ░░░███████░   ███████████
     ░░░         ░░░░░░░    ░░░░░░░░░░         ░░░░░       ░░░░░░░       ░░░░░░░    ░░░░░░░░░░░


# VodTool

A transcript-first CLI tool for content creators. Takes a long stream, finds the topics, generates cut plans to export focused videos.

## Requirements

- Python 3.9+
- `ffmpeg` installed and in PATH
- `OPENAI_API_KEY` — for transcription (Whisper) and embeddings
- `ANTHROPIC_API_KEY` — for LLM topic detection (optional if using Ollama)

## Installation

```bash
git clone https://github.com/jbmoutout/vodtool
cd vodtool
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Copy `.env.example` to `.env` and fill in your API keys.

## Quick Start

```bash
# Full pipeline — one command (uses Anthropic by default, falls back to Ollama)
vodtool pipeline path/to/video.mp4

# Twitch VOD
vodtool pipeline https://twitch.tv/videos/<id>

# With language hint
vodtool pipeline path/to/video.mp4 --language fr

# Force a specific LLM provider
vodtool pipeline path/to/video.mp4 --provider anthropic
vodtool pipeline path/to/video.mp4 --provider ollama --model qwen2.5:3b
```

The pipeline runs 5 steps: **ingest → transcribe → chunks → embed → llm-topics**.
The LLM decides the number of topics naturally — no preset needed.

## Step-by-Step

```bash
# 1. Import video (or Twitch URL) and extract audio
vodtool ingest path/to/video.mp4
vodtool ingest https://twitch.tv/videos/<id>

# 2. Transcribe (OpenAI Whisper, auto-detects language)
vodtool transcribe projects/<id>
vodtool transcribe projects/<id> --language fr

# 3. Split transcript into semantic chunks
vodtool chunks projects/<id>

# 4. Generate embeddings
vodtool embed projects/<id>

# 5. Detect topics with LLM (tries Ollama first, falls back to Anthropic)
vodtool llm-topics projects/<id>
vodtool llm-topics projects/<id> --provider anthropic
vodtool llm-topics projects/<id> --provider ollama --model qwen2.5:3b
vodtool llm-topics projects/<id> --max-topics 5   # cap if needed
```

For Ollama: `ollama pull qwen2.5:3b` (one-time, ~2GB).

## Inspecting Results

```bash
# List all topics with labels and durations
vodtool list-topics projects/<id>

# Chronological topic timeline
vodtool show-topics projects/<id>

# Deep dive into a topic
vodtool inspect-topic projects/<id> topic_0001

# Compare Anthropic vs Ollama side-by-side
vodtool compare-llm projects/<id>
```

Source options for `list-topics` and `cutplan`: `--source auto|llm|labeled|basic` (auto prefers LLM topics).

## Export

```bash
# Generate a cut plan for a topic
vodtool cutplan projects/<id> --topic topic_0001

# Export the video
vodtool export projects/<id>
```

## License

MIT
