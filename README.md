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

### Basic Workflow

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

## Commands

### Core Pipeline
- `ingest` - Import video and extract audio
- `transcribe` - Generate timestamped transcript using Whisper (supports `--language` for specific language codes)
- `chunks` - Split transcript into semantic chunks
- `embed` - Compute embeddings for chunks
- `segment-topics` - Detect topic boundaries
- `topics` - Cluster segments into topics
- `label-topics` - Generate topic labels (with duration and talk-time metrics)
- `cutplan` - Create editing plan for a topic
- `export` - Generate final video with preview

### Speaker Diarization (Optional)
- `diarize` - Identify speakers and rank by speaking time (use `--num-main` to set number of main speakers)
- `diarize-review` - Review speaker statistics and mark background speakers

When diarization is used, topic analysis automatically filters to main speakers only, excluding background audio and other speakers.

### Debug & Inspection
- `show-topics` - Display chronological timeline of topic spans, showing when topics appear and return
- `explain-chunk` - Explain why a chunk belongs to its topic (shows nearest neighbors by similarity)
- `inspect-topic` - Deep inspection of a specific topic with statistics and representative chunks

```bash
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
