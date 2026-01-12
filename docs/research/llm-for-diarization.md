# LLM for Speaker Diarization

**Status**: Research only - no implementation planned
**Date**: 2026-01-11

## Question
Can LLMs replace or enhance acoustic diarization?

## Answer: No for Core Diarization

**Current system** ([diarize.py](../../src/vodtool/commands/diarize.py)): pyannote.audio 3.1
- Acoustic deep learning on audio waveforms
- Millisecond-precision speaker boundaries
- Voice biometrics (pitch, timbre, accent)

**Why LLMs don't work**:
- Operate on text transcripts only
- No access to voice characteristics
- Cannot provide precise timing
- Cannot handle overlapping speech

## Comparison Table

| Capability | Acoustic (pyannote) | LLM (transcript) |
|------------|---------------------|------------------|
| Voice distinction | ✅ Timbre, pitch | ❌ No audio access |
| Precise timing | ✅ Millisecond boundaries | ❌ Word-level at best |
| Overlapping speech | ✅ Detectable | ❌ Very difficult |
| Speaker identity | ✅ Same voice = same ID | ❌ Can't verify |
| Speed | ⏱️ Minutes | ⚡ Seconds |

## Where LLMs Could Help

### 1. Auto-Classify Background Speakers (HIGH VALUE)
**Current**: Manual `diarize-review` to mark background audio
**LLM enhancement**: Auto-detect videos being watched, music, ads

**Benefit**: Automates tedious manual work

### 2. Semantic Boundary Refinement (MODERATE)
Adjust speaker change points to natural sentence breaks

### 3. Speaker Role Naming (LOW)
Infer "host", "guest", "caller" instead of "SPEAKER_00"

## Data Flow (Current)

```
Audio → pyannote → diarization_segments.json
                ↓
         speaker_map.json (MAIN/OTHER)
                ↓
         chunks.json (speaker labels)
                ↓
         Topic analysis (MAIN speakers only)
```

**Integration points**:
- [chunks.py](../../src/vodtool/commands/chunks.py#L131-L181) - Speaker assignment
- [segment_topics.py](../../src/vodtool/commands/segment_topics.py#L54-L65) - MAIN filter

## Recommendation

**Keep pyannote** - it's the right tool for voice-based speaker detection.

**Consider later**: LLM-based background audio detection if manual review becomes a bottleneck.

## Related
- [local-llm-for-topics.md](local-llm-for-topics.md) - LLMs work great for topic segmentation (different task)
