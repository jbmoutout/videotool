# VodTool

A local, transcript-first CLI tool for content creators to extract coherent topic-focused videos from long multi-topic streams.

## Overview

VodTool helps talking-heavy streamers who talk for hours across many subjects turn one stream into focused, coherent videos. The tool:

- Transcribes audio using OpenAI Whisper
- Identifies topics through semantic analysis
- Generates cut plans to isolate specific topic threads
- Exports topic-focused videos with minimal manual editing

## Key Features

- **Transcript-first**: Works best with talking-heavy content
- **Local & Private**: All processing happens on your machine
- **Suggest-only**: Never auto-deletes; generates reversible cut plans
- **Topic detection**: Automatically finds topic boundaries using semantic embeddings

## Installation

1. Clone the repository
2. Install the package in development mode:

```bash
pip install -e .
```

3. Install system dependencies:

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
apt-get install ffmpeg

# Other systems: install ffmpeg from https://ffmpeg.org/
```

## Usage

```bash
# Show help
vodtool --help

# Ingest a video file
vodtool ingest path/to/video.mp4

# Transcribe audio
vodtool transcribe projects/<project-id>

# Create semantic chunks
vodtool chunks projects/<project-id>

# Generate embeddings
vodtool embed projects/<project-id>

# Detect topic segments
vodtool segment-topics projects/<project-id>

# Cluster into topics
vodtool topics projects/<project-id>

# Label topics with keywords
vodtool label-topics projects/<project-id>

# Create cut plan for a topic
vodtool cutplan projects/<project-id> --topic topic_0000

# Export final video
vodtool export projects/<project-id>
```

## Commands

- `ingest` - Import video and extract audio
- `transcribe` - Generate timestamped transcript using Whisper
- `chunks` - Split transcript into semantic chunks
- `embed` - Compute embeddings for chunks
- `segment-topics` - Detect topic boundaries
- `topics` - Cluster segments into topics
- `label-topics` - Generate topic labels
- `cutplan` - Create editing plan for a topic
- `export` - Generate final video with preview

## Requirements

- Python 3.9+
- ffmpeg (for video/audio processing)

## License

MIT
