 █████   █████    ███████    ██████████      ███████████    ███████       ███████    █████      
░░███   ░░███   ███░░░░░███ ░░███░░░░███    ░█░░░███░░░█  ███░░░░░███   ███░░░░░███ ░░███       
 ░███    ░███  ███     ░░███ ░███   ░░███   ░   ░███  ░  ███     ░░███ ███     ░░███ ░███       
 ░███    ░███ ░███      ░███ ░███    ░███       ░███    ░███      ░███░███      ░███ ░███       
 ░░███   ███  ░███      ░███ ░███    ░███       ░███    ░███      ░███░███      ░███ ░███       
  ░░░█████░   ░░███     ███  ░███    ███        ░███    ░░███     ███ ░░███     ███  ░███      █
    ░░███      ░░░███████░   ██████████         █████    ░░░███████░   ░░░███████░   ███████████
     ░░░         ░░░░░░░    ░░░░░░░░░░         ░░░░░       ░░░░░░░       ░░░░░░░    ░░░░░░░░░░░ 
                                                                                                
                                                                

# VodTool

A local, transcript-first CLI tool for content creators to extract coherent topic-focused videos from long multi-topic streams.

## Overview

VodTool helps talking-heavy streamers who talk for hours across many subjects turn one stream into focused, coherent videos. The tool:

- Transcribes audio using OpenAI Whisper
- Identifies speakers through diarization (optional)
- Identifies topics through semantic analysis
- Generates cut plans to isolate specific topic threads
- Exports topic-focused videos with minimal manual editing

## Key Features

- **Transcript-first**: Works best with talking-heavy content
- **Speaker-aware**: Optional speaker diarization to focus on main speakers (great for react/commentary content)
- **Local & Private**: All processing happens on your machine
- **Suggest-only**: Never auto-deletes; generates reversible cut plans
- **Topic detection**: Automatically finds topic boundaries using semantic embeddings

## Installation

1. Clone the repository
2. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Install the package in development mode:

```bash
pip install -e .
```

4. For zsh users, to make `vodtool` available in new shells, add the venv activation to your profile:

```bash
# Replace /path/to/vodtool with your actual vodtool directory path
echo 'source /Users/YOUR_USERNAME/code/vodtool/.venv/bin/activate' >> ~/.zshrc && source ~/.zshrc
```

Or manually activate the venv each time: `source .venv/bin/activate`

5. Install system dependencies:

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
apt-get install ffmpeg

# Other systems: install ffmpeg from https://ffmpeg.org/
```

## Usage

### Quick Start (One Command)

```bash
# Run full pipeline: ingest → transcribe → chunks → embed → topics → label
vodtool pipeline path/to/video.mp4

# With options
vodtool pipeline path/to/video.mp4 --language fr --max-topics 10
vodtool pipeline path/to/video.mp4 --diarize --num-main 2
```

### Step-by-Step Workflow

```bash
# Show help
vodtool --help

# 1. Ingest a video file
vodtool ingest path/to/video.mp4

# 2. Transcribe audio (auto-detect language)
vodtool transcribe projects/<project-id>

# 3. (Optional) Speaker diarization - identify and filter speakers
vodtool diarize projects/<project-id>
vodtool diarize-review projects/<project-id>  # Review and mark background speakers

# 4. Create semantic chunks
vodtool chunks projects/<project-id>

# 5. Generate embeddings
vodtool embed projects/<project-id>

# 6. Detect topic segments
vodtool segment-topics projects/<project-id>

# 7. Cluster into topics
vodtool topics projects/<project-id>

# 8. Label topics with keywords
vodtool label-topics projects/<project-id>

# 9. Create cut plan for a topic
vodtool cutplan projects/<project-id> --topic topic_0000

# 10. Export final video
vodtool export projects/<project-id>
```

### Speaker Diarization (Optional)

For multi-speaker content (podcasts, co-streams, react videos):

```bash
# Identify speakers automatically
vodtool diarize projects/<project-id> --num-main 2

# Review speaker statistics and mark background audio
vodtool diarize-review projects/<project-id>

# Re-run chunks to apply speaker labels
vodtool chunks projects/<project-id>
```

Speaker diarization helps when:
- You have multiple hosts and want to focus on main speakers
- React/commentary content has background video audio that should be excluded
- You want topics to only include specific speakers' content

### Language Options

```bash
# Auto-detect language (default)
vodtool transcribe projects/<project-id>

# Specify language code
vodtool transcribe projects/<project-id> --language en
vodtool transcribe projects/<project-id> --language es
```

### Topic Count

Control the maximum number of topics detected:

```bash
# Default: 4 topics
vodtool segment-topics projects/<project-id>
vodtool topics projects/<project-id>

# Custom topic count
vodtool segment-topics projects/<project-id> --max-topics 12
vodtool topics projects/<project-id> --max-topics 12

# Or via pipeline
vodtool pipeline path/to/video.mp4 --max-topics 12
```

Lower values create broader topic groupings; higher values create more granular topics.

### LLM-Based Topics (Recommended)

vodtool supports both local LLM (Ollama) and API-based (Claude) topic generation.

#### Local LLM (Ollama) - Free & Private

Cost-free, offline topic extraction running entirely on your machine:

```bash
# 1. Install Ollama (one-time setup)
curl -fsSL https://ollama.com/install.sh | sh

# 2. Pull recommended model (one-time, ~2GB download)
ollama pull qwen2.5:3b

# 3. Generate topics with local LLM
vodtool llm-topics projects/<project-id>
vodtool llm-topics projects/<project-id> --max-topics 8

# Force local LLM (error if unavailable)
vodtool llm-topics projects/<project-id> --provider ollama

# Try different models
vodtool llm-topics projects/<project-id> --provider ollama --model llama3.2:3b
```

**Recommended Models:**
- **qwen2.5:3b** (default) - Best structured output, ~2GB
- **llama3.2:3b** - Good all-around, ~2GB
- **gemma2:2b** - Lightest, ~1.6GB (lower quality)

**Performance:** Local inference takes 10-30 seconds per stream (vs 2-5s with API).

**Hardware Requirements:**
- **Minimum:** 16GB RAM recommended for reliable inference
- **8GB RAM:** May experience crashes with large transcripts (>100 chunks)
- If local LLM crashes, use `--provider anthropic` or rely on auto-fallback

#### Anthropic API (Claude) - Best Quality

For highest quality results using Claude API:

```bash
# Requires ANTHROPIC_API_KEY in .env file
vodtool llm-topics projects/<project-id> --provider anthropic
vodtool llm-topics projects/<project-id> --provider anthropic --max-topics 8
```

#### Auto Mode (Default)

By default, vodtool tries Ollama first and falls back to Anthropic if unavailable:

```bash
# Automatic provider selection
vodtool llm-topics projects/<project-id>  # tries ollama → anthropic

# Note: Requires ANTHROPIC_API_KEY in .env for fallback to work
```

**Important:** The auto-fallback requires `ANTHROPIC_API_KEY` in your `.env` file. Without it, the command will fail if Ollama is unavailable.

#### Compare Both Providers

Generate topics with both Claude and Ollama, then see a side-by-side comparison:

```bash
vodtool compare-llm projects/<project-id>
vodtool compare-llm projects/<project-id> --max-topics 8 --ollama-model qwen2.5:3b
```

This shows:
- Performance comparison (time, topic count)
- Side-by-side topic labels
- Cost analysis

Topic labels are automatically generated in the transcript's language.

### Creating a Cut Plan

```bash
# Auto-detect best topic map (prefers LLM > labeled > basic)
vodtool cutplan projects/<project-id> --topic topic_0001

# Explicitly use LLM-generated topics
vodtool cutplan projects/<project-id> --topic topic_0001 --source llm

# Use embedding-based topics
vodtool cutplan projects/<project-id> --topic topic_0001 --source labeled
vodtool cutplan projects/<project-id> --topic topic_0001 --source basic
```

Source options:
- `auto` (default): Uses first available: LLM → labeled → basic
- `llm`: Use `topic_map_llm.json` (best labels, from `llm-topics`)
- `labeled`: Use `topic_map_labeled.json` (with quotes, from `label-topics`)
- `basic`: Use `topic_map.json` (from `topics`)

## Commands

### Full Pipeline
- `pipeline` - Run all steps in one command (ingest → transcribe → chunks → embed → topics → label)

### Core Pipeline (Individual Steps)
- `ingest` - Import video and extract audio
- `transcribe` - Generate timestamped transcript using Whisper (supports `--language` for specific language codes)
- `chunks` - Split transcript into semantic chunks
- `embed` - Compute embeddings for chunks
- `segment-topics` - Detect topic boundaries
- `topics` - Cluster segments into topics
- `label-topics` - Generate topic labels (with duration and talk-time metrics)
- `llm-topics` - Use LLM to identify topics (local Ollama or Anthropic API)
- `compare-llm` - Compare Claude and Ollama topic generation side-by-side
- `cutplan` - Create editing plan for a topic (use `--source llm|labeled|basic|auto`)
- `export` - Generate final video with preview

### Speaker Diarization (Optional)
- `diarize` - Identify speakers and rank by speaking time (use `--num-main` to set number of main speakers)
- `diarize-review` - Review speaker statistics and mark background speakers

When diarization is used, topic analysis automatically filters to main speakers only, excluding background audio and other speakers.

### Debug & Inspection
- `list-topics` - List all topics with labels, durations, and summaries (use `--source llm|labeled|basic|auto`)
- `show-topics` - Display chronological timeline of topic spans, showing when topics appear and return
- `explain-chunk` - Explain why a chunk belongs to its topic (shows nearest neighbors by similarity)
- `inspect-topic` - Deep inspection of a specific topic with statistics and representative chunks

```bash
# List topics with labels and summaries (auto-prefers LLM topics)
vodtool list-topics projects/<project-id>
vodtool list-topics projects/<project-id> --source labeled

# View topic timeline (MISC topics hidden by default)
vodtool show-topics projects/<project-id>
vodtool show-topics projects/<project-id> --include-misc

# Understand why a chunk was assigned to its topic
vodtool explain-chunk projects/<project-id> chunk_0042

# Deep dive into a specific topic
vodtool inspect-topic projects/<project-id> topic_0000
```

### MISC Topics

Short or singleton topics (< 90s duration or < 3 chunks) are automatically categorized as MISC and hidden by default. This keeps the output focused on substantial topics. Use `--include-misc` with `show-topics` to view them.

## Requirements

- Python 3.9+
- ffmpeg (for video/audio processing)

## License

MIT
