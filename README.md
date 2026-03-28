 █████   █████    ███████    ██████████      ███████████    ███████       ███████    █████
░░███   ░░███   ███░░░░░███ ░░███░░░░███    ░█░░░███░░░█  ███░░░░░███   ███░░░░░███ ░░███
 ░███    ░███  ███     ░░███ ░███   ░░███   ░   ░███  ░  ███     ░░███ ███     ░░███ ░███
 ░███    ░███ ░███      ░███ ░███    ░███       ░███    ░███      ░███░███      ░███ ░███
 ░░███   ███  ░███      ░███ ░███    ░███       ░███    ░███      ░███░███      ░███ ░███
  ░░░█████░   ░░███     ███  ░███    ███        ░███    ░░███     ███ ░░███     ███  ░███      █
    ░░███      ░░░███████░   ██████████         █████    ░░░███████░   ░░░███████░   ███████████
     ░░░         ░░░░░░░    ░░░░░░░░░░         ░░░░░       ░░░░░░░       ░░░░░░░    ░░░░░░░░░░░


# VodTool

Guided VOD editing — AI maps narrative beats (hook, build, peak, resolution) on your stream's timeline so you see the terrain before you cut.

## How It Works

VodTool runs a 3-step pipeline on any stream VOD:

```
ingest → transcribe → detect narrative beats
```

1. **Ingest** — downloads the video (Twitch URL or local file), extracts audio
2. **Transcribe** — sends audio to Groq Whisper (fast, free tier: ~2h/day)
3. **Detect beats** — sends the full transcript to Claude in a single call, gets back topics + narrative beats (hook/build/peak/resolution) with timestamps and confidence scores

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
vodtool beats path/to/video.mp4
vodtool beats https://twitch.tv/videos/<id>

# With language hint
vodtool beats path/to/video.mp4 --language fr

# JSON progress output (for Tauri IPC)
vodtool beats path/to/video.mp4 --json-progress
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
git clone https://github.com/jbmoutout/vodtool
cd vodtool
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Copy `.env.example` to `.env` and fill in your API keys.

## Beat Detection Output

The `beats.json` schema:

```json
{
  "beats": [
    {
      "topic_id": "topic_0001",
      "topic_label": "Rogue noir dans HP",
      "beats": [
        {
          "type": "hook",
          "start_s": 912,
          "end_s": 945,
          "confidence": 0.91,
          "label": "Hot take: casting Rogue noir"
        },
        {
          "type": "peak",
          "start_s": 945,
          "end_s": 1650,
          "confidence": 0.85,
          "label": "Main argument: racisme et adaptation"
        }
      ]
    }
  ]
}
```

**Beat types:**
- **hook** — the most attention-grabbing moment (where a YouTube video should start)
- **build** — context and setup that gives the hook meaning
- **peak** — the highest-value segment, the meat of the topic
- **resolution** — wind-down, conclusions, transition to next topic

Not every topic has all 4 types. A short tangent might only have a hook and peak.

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
vodtool pipeline path/to/video.mp4

# Individual steps
vodtool transcribe projects/<id>
vodtool chunks projects/<id>
vodtool embed projects/<id>
vodtool llm-topics projects/<id>
vodtool list-topics projects/<id>
vodtool show-topics projects/<id>
vodtool cutplan projects/<id> --topic topic_0001
vodtool export projects/<id>
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
