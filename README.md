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
- `OPENAI_API_KEY` environment variable (for transcription and embeddings)

## Installation

```bash
git clone https://github.com/jbmoutout/vodtool
cd vodtool
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

To activate automatically in new shells:

```bash
echo 'source /path/to/vodtool/.venv/bin/activate' >> ~/.zshrc
```

## Quick Start

```bash
# Full pipeline — one command
vodtool pipeline path/to/video.mp4

# With language hint and topic count
vodtool pipeline path/to/video.mp4 --language fr --max-topics 8
```

The pipeline runs 7 steps: ingest → transcribe → chunks → embed → segment-topics → topics → label-topics.

## Step-by-Step

```bash
# 1. Import video and extract audio
vodtool ingest path/to/video.mp4

# 2. Transcribe (OpenAI Whisper, auto-detects language)
vodtool transcribe projects/<id>
vodtool transcribe projects/<id> --language fr

# 3. Split transcript into semantic chunks
vodtool chunks projects/<id>

# 4. Generate embeddings
vodtool embed projects/<id>
vodtool embed projects/<id> --provider local   # offline, uses sentence-transformers

# 5. Detect topic boundaries
vodtool segment-topics projects/<id> --max-topics 8

# 6. Cluster into topics
vodtool topics projects/<id> --max-topics 8

# 7. Label topics
vodtool label-topics projects/<id>
```

## LLM Topics (Better Labels)

For richer topic labels, use an LLM instead of the embedding-only approach:

```bash
# Tries Ollama first, falls back to Anthropic (requires ANTHROPIC_API_KEY)
vodtool llm-topics projects/<id>

# Force a specific provider
vodtool llm-topics projects/<id> --provider anthropic
vodtool llm-topics projects/<id> --provider ollama --model qwen2.5:3b

# Compare both side-by-side
vodtool compare-llm projects/<id>
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

# Why is this chunk in its topic?
vodtool explain-chunk projects/<id> chunk_0042
```

Source options for `list-topics` and `cutplan`: `--source auto|llm|labeled|basic` (auto prefers LLM > labeled > basic).

## Export

```bash
# Generate a cut plan for a topic
vodtool cutplan projects/<id> --topic topic_0001

# Export the video
vodtool export projects/<id>
```

## License

MIT
