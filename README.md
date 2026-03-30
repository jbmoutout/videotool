
# VideoTool

Guided VOD editing — AI maps every second of your stream into topics and beats (highlight, core, context, chat, transition, break) so you see the terrain before you cut.

## How It Works

VideoTool runs a 3-step pipeline on any stream VOD:

```
ingest → transcribe → detect narrative beats
```

1. **Ingest** — downloads the video (Twitch URL or local file), extracts audio
2. **Transcribe** — sends audio to Groq Whisper (fast, free tier: ~2h/day)
3. **Detect beats** — sends the full transcript to Claude in a single call, gets back topics + beats (highlight/core/context/chat/transition/break) with timestamps and confidence scores, tiling the entire stream

The output is a `beats.json` file that maps the narrative structure of your stream.

## Two Ways to Use It

### Desktop App (Tauri)

Paste a Twitch VOD link or drop a video file. The app runs the pipeline and shows an interactive beat timeline with click-to-seek video playback.

```bash
# Build and run the desktop app
cd src-tauri && cargo tauri dev
```

### CLI

```bash
# Full beat detection pipeline — one command
videotool beats path/to/video.mp4
videotool beats https://twitch.tv/videos/<id>

# With language hint
videotool beats path/to/video.mp4 --language fr

# Re-run beat detection only (skip ingest + transcribe)
videotool llm-beats projects/<id>

# JSON progress output (for Tauri IPC)
videotool beats path/to/video.mp4 --json-progress
```

### Standalone Beat Viewer (HTML)

For paywalled VODs or local OBS recordings — no install required:

1. Open `tools/beat-viewer.html` in any browser
2. Load your video file + paste the `beats.json` output
3. Click beats to seek, hover for details

## Requirements

- Python 3.9+
- `ffmpeg` installed and in PATH
- `yt-dlp` installed and in PATH (for Twitch VOD downloads)
- `GROQ_API_KEY` — for transcription ([free at console.groq.com](https://console.groq.com))
- `ANTHROPIC_API_KEY` — for beat detection (Claude Sonnet)

## Installation

```bash
git clone https://github.com/jbmoutout/videotool
cd videotool
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Copy `.env.example` to `.env` and fill in your API keys.

## Beat Detection Output

The `beats.json` schema:

```json
{
  "topic_id": "coupe_cheveux",
  "topic_label": "Les 4 phases d'une coupe",
  "beats": [
    {
      "type": "context",
      "start_s": 1068.5,
      "end_s": 1185.2,
      "confidence": 0.75,
      "label": "Ça fait trois semaines, là c'est le pire stade de la repousse"
    },
    {
      "type": "core",
      "start_s": 1406.8,
      "end_s": 1767.3,
      "confidence": 0.90,
      "label": "Théorie des 4 phases d'une coupe de cheveux"
    },
    {
      "type": "transition",
      "start_s": 2066.4,
      "end_s": 2869.8,
      "confidence": 0.78,
      "label": "Débat sur les coupes longues, buzz cut et couvre-chefs de darons"
    }
  ]
}
```

**Beat types:**
- **highlight** — the most attention-grabbing moment (where a YouTube video should start)
- **core** — the meat of the topic, the highest-value segment
- **context** — setup and background that gives the core meaning
- **chat** — chat interaction, audience engagement
- **transition** — wind-down, pivot to the next topic
- **break** — off-topic pause, BRB, dead air

Not every topic has all 6 types. A short tangent might only have a highlight and core.

## API Proxy (for zero-friction distribution)

A Cloudflare Worker proxy (`cloudflare-worker/`) lets you distribute the app without requiring users to configure API keys. The proxy adds your keys and forwards requests.

```bash
cd cloudflare-worker

# Set up local dev
echo "GROQ_API_KEY=your-key" > .dev.vars
echo "ANTHROPIC_API_KEY=your-key" >> .dev.vars

# Run locally at http://localhost:8787
npx wrangler dev

# Deploy to production
npx wrangler deploy
wrangler secret put GROQ_API_KEY
wrangler secret put ANTHROPIC_API_KEY
```

## Old Pipeline (topic detection only)

The original topic detection pipeline is still available for power users:

```bash
# 5-step pipeline: ingest → transcribe → chunks → embed → llm-topics
videotool pipeline path/to/video.mp4

# Individual steps
videotool transcribe projects/<id>
videotool chunks projects/<id>
videotool embed projects/<id>
videotool llm-topics projects/<id>
videotool list-topics projects/<id>
videotool show-topics projects/<id>
videotool cutplan projects/<id> --topic topic_0001
videotool export projects/<id>
```

## Cost

| VOD length | Transcription (Groq) | Beat detection (Claude) | Total |
|---|---|---|---|
| 1 hour | Free | ~$0.05-0.10 | ~$0.10 |
| 4 hours | Free | ~$0.30-0.60 | ~$0.60 |
| 6 hours | Free | ~$0.50-1.00 | ~$1.00 |

Groq Whisper free tier covers ~2 hours of audio per day.

## License

MIT
