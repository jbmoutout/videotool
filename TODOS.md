# VodTool TODOs

Generated from /plan-eng-review on 2026-03-26

---

## 1. Harden Python CLI Before Tauri Wrapper + Branch Cleanup

**What:** Audit and refactor the existing Python CLI to fix brittle branch logic, add error handling, extract DRY violations, and reorganize git branches (merge useful ones, delete dead branches).

**Why:** The current CLI is a "brittle PoC with messy branch logic." Wrapping it in a polished Tauri desktop app creates a façade of quality — beta testers will hit crashes and edge cases, producing misleading feedback ("the UI is nice but it doesn't work"). We won't know if the concept is bad or the implementation is broken.

**Pros:**
- Beta feedback is about the product, not bugs
- Clean foundation for iteration
- Respects "well-tested code is non-negotiable" preference
- Prevents wasted Tauri build effort

**Cons:**
- Adds 1-2 days before Tauri work starts
- But this is a lake worth boiling — with CC+gstack, hardening costs days, not weeks

**Context:**
- Design doc assumes CLI is "production-ready" but user confirmed it's a brittle PoC
- Messy branch logic usually means: inconsistent error handling, edge cases not handled, brittle state assumptions, hard-coded paths
- During hardening:
  - Add error handling for common failure modes (file not found, invalid format, disk space, interrupted processing)
  - Extract common logic (error handling, file validation, path resolution) into shared utilities
  - Ensure `vodtool pipeline` composes individual steps cleanly (no copy-paste)
  - Add **17 critical tests** (15 baseline + 2 promoted from TODO #5):
    - **PROMOTED #1:** Non-UTF8 stdout handling — Rust parser must handle gracefully when Python outputs binary data, not crash (prevents silent progress freeze)
    - **PROMOTED #2:** JSON parse error handling — Tauri must show error when Python outputs malformed JSON, not render blank Results screen (prevents user confusion at final step)
    - See TODO #5 for remaining 30 deferred tests
  - Document known limitations in LIMITATIONS.md
  - Clean up git branches: merge useful work, delete dead experiments

**Depends on:** None (blocking work for Tauri wrapper)

**Effort:** human ~3-5 days / CC+gstack ~1-2 days

---

## 2. Add Ollama Support for Free/Local LLM Processing

**What:** Add local LLM option (Ollama) alongside Anthropic API. Users can choose between free/private/slower (Ollama) or fast/paid (Anthropic).

**Why:** MVP ships with Anthropic-only to simplify distribution and speed up beta validation. But the original vision was "local-first for privacy + cost" — free tier may be critical for price-sensitive users like @ouaiseddy (DIY streamer without editor budget).

**Pros:**
- Enables free tier (0 cost per VOD vs ~$0.50 with Anthropic)
- Privacy-first (no data sent to cloud)
- Differentiates from cloud-only tools like AutoCut
- Unlocks users who can't/won't pay for API

**Cons:**
- Adds distribution complexity (Ollama setup flow, model download)
- Slower processing (local inference 10-30 sec vs API 2-5 sec)
- First-run UX friction (400MB Ollama download + model pull)
- May crash on low-RAM machines (<16GB)

**Context:**
- Ollama was dropped from MVP (Architecture Issue #3) to simplify distribution
- Hybrid approach was designed: bundle Python+FFmpeg (~150MB), guide user through Ollama setup on first run
- Recommended models: qwen2.5:3b (default, best structured output), llama3.2:3b, gemma2:2b
- Auto-fallback: try Ollama → fall back to Anthropic if unavailable (requires ANTHROPIC_API_KEY in .env)
- Documentation preserved for this post-MVP work

**Depends on:** CLI hardening (TODO #1) completed, MVP validated with beta testers

**Blocked by:** Wait for user demand signal — if beta testers don't ask for "free tier," this may not be needed

**Effort:** human ~1 day / CC+gstack ~3 hours

---

## 3. Add Visual Timeline with Video Preview (YouTube Chapters Style)

**What:** Build a visual timeline component (like YouTube chapters) with:
- Horizontal bar representing full video duration
- Colored segments for each topic (8-color palette)
- Multi-segment topics shown with same color, multiple blocks
- Click segment → preview video at that timestamp

**Why:** Deferred from MVP to save 4-6 hours build time. Topic cards list (title, duration, span info, Export button) is sufficient for demand validation. But visual timeline is a polish feature that improves UX post-validation.

**Pros:**
- Professional UX (matches YouTube pattern users know)
- Easier to judge topic quality visually
- Helps users understand multi-segment topics (crypto discussed in 3 separate parts)
- Preview before export (click segment → see if it's actually about that topic)

**Cons:**
- Complex to implement well (HTML5 video player + custom Canvas/SVG timeline + click handlers + seek logic)
- Not needed for core validation (users can still see topics and export without preview)
- May introduce cross-browser/platform bugs (video playback differences)

**Context:**
- Wireframe already designed: `/tmp/gstack-sketch-1743048000.html`
- User specifically asked about this feature ("should it also show the segments on a video preview?")
- Design doc originally included it, then deferred to V2 during architecture review
- Implementation: HTML5 `<video>` element + Canvas or SVG for timeline + React/Vue state management

**Depends on:** MVP shipped and validated

**Effort:** human ~2 days / CC+gstack ~4-6 hours

---

## 4. Add Batch Processing Queue for Multiple VODs

**What:** Allow users to add multiple VOD files to a processing queue. Process them sequentially (or parallel if resources allow). Show queue UI with status for each file.

**Why:** MVP is single-file only (V1 scope limit). But professional editors like @lethar process multiple streams per day. Batch processing is a productivity multiplier.

**Pros:**
- Productivity win for B2B use case (editors processing 5-10 streams/day)
- Set-and-forget workflow (queue 5 files, come back in 2 hours, all done)
- Justifies higher pricing tier (batch = professional feature)

**Cons:**
- More complex UX (queue management, reordering, cancel individual items)
- Resource contention (processing 3 VODs simultaneously may crash on 16GB RAM)
- Edge cases: what if one file fails mid-queue? Skip and continue or stop entire queue?

**Context:**
- Design doc V1 scope limit: "Single-file processing only (no batch queue)"
- Rationale: MVP validates demand with one file at a time. Batch is a productivity feature for post-validation.
- If @lethar (professional editor) gives feedback: "I need to process 10 VODs per day, clicking 10 times is painful" → prioritize this TODO
- Implementation: queue state management + sequential subprocess spawning + UI for queue list

**Depends on:** MVP validated, B2B use case confirmed (editors, not DIY streamers)

**Blocked by:** Wait for user feedback — if beta testers don't ask for batch, may not be needed

**Effort:** human ~3 days / CC+gstack ~6 hours

---

## 5. Expand Test Coverage to 100% (47 Total Tests)

**What:** Add 30 more tests to reach 100% coverage (currently 17 critical tests = 75% coverage). Cover all edge cases, minor error paths, and platform-specific behaviors.

**Why:** MVP ships with 17 critical tests (15 baseline + 2 promoted from failure modes analysis) to balance speed vs quality. But the Completeness Principle says: with AI-assisted coding, the marginal cost of full coverage is near-zero. The delta between 17 tests and 47 tests is ~2 hours with CC+gstack — not worth skipping.

**Note:** 2 tests were promoted to MVP critical tests (non-UTF8 stdout, JSON parse errors) after failure modes analysis revealed they cause user-visible blocking failures. See TODO #1 for details.

**Pros:**
- Confidence in edge case handling (file >50GB, non-UTF8 output, race conditions)
- Regression safety (changes don't break obscure paths)
- Professional engineering discipline
- Cheap to do with AI (human ~1 week / CC+gstack ~2 hours)

**Cons:**
- Not strictly needed for MVP (70% coverage catches most bugs)
- May find bugs in edge cases that don't affect beta users (diminishing returns)

**Context:**
- Current plan: 17 critical tests covering happy path, error recovery, integration points, and 2 blocking user-visible failures
- Remaining 30 tests include:
  - Edge cases: file >50GB warning, non-ASCII filenames, close app during processing
  - Platform-specific: Mac M1/M2 vs Windows behavior differences
  - Minor error paths: buffer deadlock, subprocess already finished when canceled
- Test breakdown:
  - Python CLI: 19 total paths, 10 critical tests → 9 more tests
  - Tauri wrapper: 16 total paths, 5 critical tests (3 baseline + 2 promoted) → 11 more tests
  - Frontend: 12 total paths, 0 tests → 12 more tests (can defer frontend tests if not using TDD)
  - E2E: 4 total flows, 2 critical tests → 2 more tests

**Depends on:** 17 critical tests written and passing (part of CLI hardening, TODO #1)

**Effort:** human ~1 week / CC+gstack ~2 hours (boil the lake — completeness is cheap with AI)

---

## 6. Audio Chunk Timestamp Stitching Utility (P0)

**What:** Implement `stitch_transcripts(chunks: list[TranscriptChunk]) -> Transcript` that merges per-chunk Whisper API results into a single transcript with correct absolute timestamps.

**Why:** OpenAI Whisper API has a 25MB file size limit. A 4-hour VOD produces 200-400MB of audio — must be chunked into ~10-minute segments. Each chunk's timestamps are relative (start at 0s), but must be offset by the chunk's start time to produce correct absolute timestamps. Without this, a topic that starts at 2h30m would appear at 0m30s in the stitched result. This breaks all downstream topic boundary calculations.

**Critical correctness requirements:**
- Chunk N starts at `N * chunk_duration` seconds → all its word timestamps must be offset by that value
- Words at chunk boundaries must appear in exactly one chunk (no duplicates, no drops)
- API failure on chunk N of M must raise with which chunk failed (not a silent partial result)

**Pros:**
- Required for any VOD longer than ~30 minutes (25MB ≈ 30 min @ 128kbps MP3)
- Correctness is non-negotiable — wrong timestamps = wrong topic boundaries = wrong exports
- Enables future accuracy improvements (Groq, AssemblyAI) with same stitching logic

**Cons:**
- Adds complexity to transcribe pipeline
- Boundary handling requires careful off-by-one attention

**Context:**
- Identified during /plan-eng-review Architecture Review (Issue #4)
- `TranscriptionProvider` abstraction (`src/vodtool/transcribe.py`) is prerequisite — provider returns per-chunk results, stitcher merges them
- Tests required: `tests/test_transcribe.py` (7 tests covering: ≤25MB direct call, >25MB chunking, timestamp offset correctness, boundary deduplication, chunk failure error, missing API key, file not found)
- The CRITICAL test: chunk 2 starts at 600s → its timestamps must be offset by 600s in stitched output

**Depends on:** `TranscriptionProvider` abstraction implemented in `src/vodtool/transcribe.py`

**Effort:** human ~1 day / CC+gstack ~30 min

---

## 7. GitHub Actions Release Workflow for Tauri DMG (P0)

**What:** Create `.github/workflows/release.yml` using `tauri-apps/tauri-action` to build and publish the Tauri desktop app as a Mac DMG (and eventually Windows installer) on every version tag push.

**Why:** Code without distribution is code nobody can use. The Tauri app has no value if users can't install it. A manual build process is not acceptable for beta — we need automated artifact generation so @lethar and @ouaiseddy can download and install without compiling from source.

**Required:**
- Trigger: `push` to tags matching `v*` (e.g., `v0.1.0`)
- Matrix: `macos-latest` (Mac DMG first, Windows later)
- Action: `tauri-apps/tauri-action@v0` with `tagName`, `releaseName`, `releaseBody`, `releaseDraft: true`
- Secrets: `TAURI_PRIVATE_KEY`, `TAURI_KEY_PASSWORD` for code signing
- Output: GitHub Release with `.dmg` attached (draft until manual review)

**Pros:**
- One-command release: `git tag v0.1.0 && git push origin v0.1.0` → DMG ready in 5 min
- Mac code signing prevents "unidentified developer" warning on first launch
- Draft releases allow QA before public announcement

**Cons:**
- Mac code signing requires Apple Developer Program ($99/year) or ad-hoc signing (warning shown)
- Windows build requires separate `windows-latest` runner (add in follow-up)

**Context:**
- Identified during /plan-eng-review Architecture Review (Distribution Issue)
- Tauri v2 release workflow documented at: https://tauri.app/distribute/
- The Tauri app lives in `src-tauri/` (to be created)
- Note: For MVP beta, ad-hoc signing (no cert) is acceptable — users right-click → Open to bypass Gatekeeper

**Depends on:** `src-tauri/` directory created with `tauri.conf.json`

**Effort:** human ~4 hours / CC+gstack ~15 min

---

## 8. React Stream Content Mode (`--content-type react`) (P1)

**What:** Add `--content-type react|talk|gaming` flag to `vodtool pipeline` and `vodtool llm-topics`. In `react` mode, the LLM topic extraction prompt is specialized for react stream structure — producing topic labels like `"Réaction: clip Gotaga"`, `"Tangente chat"`, `"Intro/Outro"` instead of generic subject labels.

**Why:** @ouaiseddy and @lethar work exclusively with react streams — a streamer reacts to YouTube videos live. The transcript is a mixed-down signal (streamer mic + YouTube desktop audio) with no clean source separation possible (OBS multi-track not used). However, topic boundaries in react streams are linguistically identifiable (`"okay on regarde..."`, `"attends attends"`). The LLM just needs a prompt that understands react content structure.

**What was ruled out for v0:**
- Video frame sampling to detect YouTube player → streamer speaks WITH the react layout visible simultaneously, so frames give no separation signal
- OBS multi-track recording (Track 1: mic, Track 2: desktop) → streamers won't have this configured
- Audio source separation (demucs/spleeter) → designed for music, not concurrent speech streams
- `pyannote.audio` local diarization → heavy local ML dep, dropped from v0 cloud-first pivot

**The v1 path (acoustic diarization IS feasible):**
Streamer mic (close, direct, clean) and YouTube desktop audio (compressed, re-encoded) are acoustically very distinguishable. AssemblyAI Universal-2 returns transcript + speaker labels in a single API call — no separate diarization step needed. `[Speaker A]` = streamer, `[Speaker B]` = YouTube video. This makes react topic segmentation clean and reliable.

When implementing: `AssemblyAITranscriptionProvider` slots into the existing `TranscriptionProvider` interface — `Transcript` model gets an optional `speaker_labels` field.

**Architecture notes:**
- `TranscriptionProvider` interface: `transcribe(audio_path: Path) -> Transcript`
- v0: `OpenAITranscriptionProvider` — no speaker labels
- v1: `AssemblyAITranscriptionProvider` — transcript + speaker labels in one call
- React mode prompt uses speaker labels when present, falls back to linguistic detection when absent
- No pipeline changes between v0 and v1 — just provider swap + prompt specialization

**Depends on:** MVP validated with @ouaiseddy — confirm react content is the primary use case

**Effort:** human ~2 hours / CC+gstack ~15 min

---

## NOT in scope (explicitly deferred)

- **Segment editing** — No manual adjustment of topic boundaries. Users re-run with different settings if topics are wrong.
- **Project save/reload** — Stateless workflow. No persistence of intermediate results.
- **Full checkpointing/resume** — If processing fails, user restarts from scratch. Cancellation + retry guidance is sufficient for MVP.
