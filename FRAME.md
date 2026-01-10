 █████   █████    ███████    ██████████      ███████████    ███████       ███████    █████      
░░███   ░░███   ███░░░░░███ ░░███░░░░███    ░█░░░███░░░█  ███░░░░░███   ███░░░░░███ ░░███       
 ░███    ░███  ███     ░░███ ░███   ░░███   ░   ░███  ░  ███     ░░███ ███     ░░███ ░███       
 ░███    ░███ ░███      ░███ ░███    ░███       ░███    ░███      ░███░███      ░███ ░███       
 ░░███   ███  ░███      ░███ ░███    ░███       ░███    ░███      ░███░███      ░███ ░███       
  ░░░█████░   ░░███     ███  ░███    ███        ░███    ░░███     ███ ░░███     ███  ░███      █
    ░░███      ░░░███████░   ██████████         █████    ░░░███████░   ░░░███████░   ███████████
     ░░░         ░░░░░░░    ░░░░░░░░░░         ░░░░░       ░░░░░░░       ░░░░░░░    ░░░░░░░░░░░ 
                                                                                                
                                                                                                
                                                                                                

I have 10 high-level tickets to build an MVP from scratch. Please work through them sequentially, completing each one fully before moving to the next.

Requirements:
1. Use the TodoWrite tool to track all tickets and subtasks
2. Create a single 'mvp-development' branch for this work (or let me know if you want separate branches per ticket)
3. For each ticket:
   - Create a GitHub issue with the ticket description
   - Update the issue with progress every 30 minutes
   - When blocked on a decision, add a comment with your question and label it 'blocked'
   - I'll check GitHub periodically and respond to unblock you
   - After completing a ticket, close the issue and move to the next
4. After completing each significant task, create a git commit with a message explaining WHAT changed and WHY
5. When you make a major architectural decision (tech stack, database choice, auth approach, API structure, etc.), stop and notify me via GitHub issue comment - I'll decide if it needs documentation in ARCHITECTURE.md
6. Don't create any .md files unless I explicitly ask
7. Ask me clarifying questions in GitHub issue comments if any ticket is ambiguous or has multiple valid approaches
8. Run tests after implementing each ticket (if applicable)
9. You can challenge assumptions and technical choices made in the tickets regarding feasibility and best practices.

Here are the 10 tickets:

1.
Create a Python repo skeleton for a CLI tool named `vodtool` using Typer.

Requirements:
- Use `src/` layout.
- Provide `pyproject.toml` using setuptools (or hatch) so `pip install -e .` installs `vodtool`.
- Add `src/vodtool/cli.py` with a Typer app exposing subcommands: ingest, transcribe, topics, cutplan, export (they can be stubs).
- Add `src/vodtool/__init__.py`.
- Add `README.md` with how to run: `vodtool --help`.
- Add `Makefile` or simple `scripts/dev.sh` to run locally (optional).
- Add minimal logging setup.

Acceptance:
- After `pip install -e .`, `vodtool --help` runs.
- `vodtool ingest --help` etc. exist.

2.
Implement `vodtool ingest <input_video_path>`.

Behavior:
- Create a project folder under `./projects/<project_id>/` where project_id is a short uuid.
- Copy (or symlink) original video into project as `source.mp4` (preserve extension if not mp4).
- Extract audio to `audio.wav` (mono, 16kHz) using ffmpeg via subprocess.
- Write `meta.json` containing: project_id, created_at (iso), source_filename, source_path (original), duration_seconds (best effort), and audio_path.
- Print the project path on success.

Files to add/update:
- `src/vodtool/commands/ingest.py` (or similar)
- Wire into Typer in `cli.py`.

Acceptance:
- Running `vodtool ingest samples/test.mp4` creates the folder with `source.*`, `audio.wav`, `meta.json`.
- `audio.wav` exists and is non-empty.
- Command is idempotent only per run (new project each time is fine).
- If ffmpeg missing, show a clear error message.


3.
Implement `vodtool transcribe <project_path> [--model small]`.

Behavior:
- Load `audio.wav` from project.
- Run OpenAI Whisper (python package) locally to produce timestamped segments.
- Save `transcript_raw.json` with at least: language, model, segments (each segment has start, end, text).
- Also save `transcript.txt` as plain text (segments concatenated with newlines).
- Do not rerun if transcript_raw.json already exists unless `--force`.

Files:
- `src/vodtool/commands/transcribe.py`
- Update CLI wiring.

Acceptance:
- On a small sample audio, files are created.
- JSON is valid and includes timestamps.
- `--force` overwrites.
- If whisper not installed or model download needed, surface a helpful message.

4. 
Implement `vodtool chunks <project_path>` to create `chunks.json`.

Behavior:
- Read `transcript_raw.json`.
- Produce chunks with fields: id (stable), start, end, text.
- Chunking rule (simple v0):
  - Start from whisper segments, then split into sentences if possible (basic punctuation-based split ok).
  - Ensure chunk durations are roughly 5–25 seconds; merge adjacent small chunks.
- Save `chunks.json` as a list sorted by start time.

Acceptance:
- Every chunk has non-empty text.
- Time ordering is increasing.
- Total coverage approximately matches transcript end time.
- Output deterministic for same input.

5. 
Implement `vodtool embed <project_path> [--model sentence-transformers/all-MiniLM-L6-v2]`.

Behavior:
- Read `chunks.json`.
- Compute embeddings for each chunk text using sentence-transformers (local).
- Store embeddings in `embeddings.sqlite` with tables:
  - chunks(chunk_id TEXT PRIMARY KEY, text TEXT, start REAL, end REAL)
  - embeddings(chunk_id TEXT, model TEXT, vector BLOB, PRIMARY KEY(chunk_id, model))
- On rerun, skip chunks already embedded for that model.
- Provide a small helper to serialize vectors (e.g., float32) into blob.

Acceptance:
- After run, sqlite exists and contains embeddings rows == number of chunks.
- Rerun does not recompute (log “skipped N, computed M”).
- Deterministic ordering, stable chunk ids.

6. 
Implement `vodtool segment-topics <project_path> [--max-topics 8]` to create `topic_segments.json`.

Behavior:
- Load embeddings from sqlite for chosen model (default same as embedding step).
- Compute a similarity signal between consecutive chunks.
- Create change points where similarity drops below a threshold (heuristic ok).
- Group into contiguous segments with: segment_id, start, end, chunk_ids.
- Ensure you don’t create more than --max-topics contiguous segments; if too many, merge smallest/closest.

Acceptance:
- Every chunk_id appears exactly once across segments.
- Segments are contiguous and time-ordered.
- Number of segments <= max-topics.
- Output file is valid JSON and deterministic.

7. 
Implement `vodtool topics <project_path> [--max-topics 8]` to create `topic_map.json`.

Behavior:
- Load `topic_segments.json` and embeddings.
- Compute a centroid embedding for each segment.
- Cluster segments into topics (k <= max-topics) using agglomerative clustering or k-means (your choice, but deterministic).
- Create topic objects:
  - topic_id
  - label_stub (empty string for now)
  - spans: list of {start, end, chunk_ids, segment_ids}
- A topic may have multiple spans (non-contiguous). Preserve original ordering of spans by time.

Acceptance:
- No chunk appears in two topics.
- At least one topic can have multiple spans if segments cluster that way.
- Total coverage matches all chunks.
- Deterministic results (set random seeds if needed).

8. 
Implement `vodtool label-topics <project_path>` to create `topic_map_labeled.json`.

Behavior:
- Load `topic_map.json` and chunks text.
- Generate labels using a heuristic baseline (no external APIs):
  - For each topic, concatenate a sample of its text and compute keywords (TF-IDF) then pick 3-6 words; make a short label string.
- Save same structure but with `label` field (and keep `label_stub` if you want).
- Add support for an optional LLM labeling later via env var, but keep it OFF by default.

Acceptance:
- Works offline.
- Produces human-readable non-empty labels.
- Does not overwrite if user edited label in an existing labeled file unless `--force`.

9. 
Implement `vodtool cutplan <project_path> --topic <topic_id>` to create `cutplan.json`.

Behavior:
- Load `topic_map_labeled.json` (or topic_map.json if labeled missing).
- For selected topic, keep_spans = its spans (merge adjacent spans separated by < 15s gap).
- drop_spans = complement across the full stream duration, with reason = "other_topic:<id>" where possible (based on which topic owns those chunks).
- Save: selected_topic_id, keep_spans, drop_spans, total_keep_seconds.
- Never delete anything; just produce the plan.

Acceptance:
- keep_spans have no overlaps and are time-ordered.
- drop_spans cover everything else (within transcript time range).
- Sum(keep)+Sum(drop) approx equals total duration.

10. 
Implement `vodtool export <project_path>` to produce `export.mp4` and `export_index.json`.

Behavior:
- Requires `cutplan.json` and original `source.*`.
- Use ffmpeg to cut keep_spans and concatenate into a single mp4.
- Write `export_index.json` mapping:
  - original_time -> export_time (piecewise mapping by span)
  - and chunk_id -> export_time_start (approx) using chunks.
- Provide a minimal HTML preview page `preview.html` in the project folder with:
  - a <video> tag for export.mp4
  - a simple list of kept spans with links that seek the video
  - (no frameworks; minimal JS ok)

Acceptance:
- export.mp4 exists and plays.
- preview.html opens locally and seeks when clicking span links.
- If ffmpeg fails, print stderr and exit non-zero.


Project context: 
This MVP is a local, transcript-first tool for talking-heavy streamers who talk for hours across many subjects and later struggle to turn one stream into one coherent video.
The tool extracts topics from a long stream, lets the creator pick one thread, and produces a reversible cut plan to isolate that thread.
Constraints: suggest-only (no auto-delete), transcript-first, local/privacy-respecting, talking-heavy only (no gameplay or highlights).

Please start by:
1. Initializing the git repository if needed
2. Creating GitHub issues for all 10 tickets
3. Breaking down the first ticket into subtasks
4. Beginning work on the first ticket
