2026-01-11
# Product Roadmap

## Goal
Help talking-heavy streamers turn a long, digressive stream into **one coherent video** by identifying topics, selecting a single thread, and generating a **reversible cut plan**.

---

## Phase 1 — WOW (Discovery)
- Generate topic map from transcript
- Human-readable topic labels + durations
- Fast, confident presentation

**Magical:** topic discovery, naming, semantic grouping
**Signal:** "This understands my stream."

---

## Phase 2 — TRUST (Inspection)
- Click topic → quotes + timestamps
- Show non-contiguous topic spans
- Explicit topic ↔ chunk ↔ time mapping
- Manual topic renaming

**Boring-but-safe:** timestamps, provenance, determinism
**Signal:** "These groupings make sense."

---

## Phase 3 — CONTROL (Action)
- Pick one topic as the target thread
- Generate reversible cut plan (keep/drop)
- Explain every decision
- Minimal video preview before export

**Boring-but-safe:** cuts, export, no auto-delete
**Signal:** "This is the video."

---

## Local LLM — Topic Boundary Detection
- Local LLM proposes topic boundaries and returns
- No cloud dependency; no training on user data
- Rules enforce caps, merges, and determinism
- LLM suggests; system guarantees safety

---

## Invariants
- Suggest, don't assume
- Transcript-first
- Fully reversible
- Errors embarrassing on YouTube must be deterministic
