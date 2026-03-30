"""Test the new segmentation prompt against real project data.

Runs the new prompt on actual transcripts, measures coverage,
and compares to the existing beats.json.

Usage:
    python test_prompt.py [project_id ...]
    python test_prompt.py 6c901929 42570241 d7e9e793
"""

import json
import sys
import time
from pathlib import Path

from videotool.llm import get_anthropic_client
from videotool.commands.llm_beats import (
    _build_beat_prompt,
    _compute_gaps,
    _format_transcript,
    _parse_beats_response,
    validate_beats,
    VALID_BEAT_TYPES,
    LLM_MODEL,
)

BASE = Path("~/.videotool/projects")


def test_project(project_id: str):
    """Run new prompt on a project and report results."""
    project_path = BASE / project_id
    meta = json.load(open(project_path / "meta.json"))
    transcript = json.load(open(project_path / "transcript_raw.json"))
    segments = transcript["segments"]
    duration = meta["duration_seconds"]

    # Load existing beats for comparison
    existing = json.load(open(project_path / "beats.json"))
    existing_gaps = _compute_gaps(existing, duration)
    existing_covered = duration - sum(g["end_s"] - g["start_s"] for g in existing_gaps)
    existing_pct = existing_covered / duration * 100

    print(f"\n{'='*60}")
    print(f"Project: {project_id}")
    print(f"Title: {meta.get('title', '?')[:70]}")
    print(f"Duration: {duration:.0f}s ({duration/60:.0f}min)")
    print(f"Segments: {len(segments)}")
    print(f"Existing coverage: {existing_pct:.1f}%")
    print(f"{'='*60}")

    # Build and send new prompt
    prompt = _build_beat_prompt(segments, duration)
    token_est = len(prompt) // 4
    print(f"Prompt tokens (est): ~{token_est}")
    print("Calling Claude...")

    client = get_anthropic_client()
    start_time = time.time()

    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=16384,
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}],
        timeout=300,
    )

    elapsed = time.time() - start_time
    response_text = response.content[0].text

    print(f"Response in {elapsed:.1f}s")
    print(f"Input tokens: {response.usage.input_tokens}")
    print(f"Output tokens: {response.usage.output_tokens}")

    # Parse and validate
    beats_data = _parse_beats_response(response_text)
    beats_data = validate_beats(beats_data, duration)

    # Compute coverage
    gaps = _compute_gaps(beats_data, duration)
    total_gap = sum(g["end_s"] - g["start_s"] for g in gaps)
    covered = duration - total_gap
    pct = covered / duration * 100

    n_topics = len(beats_data["beats"])
    n_beats = sum(len(t["beats"]) for t in beats_data["beats"])

    # Beat type distribution
    type_counts = {}
    for t in beats_data["beats"]:
        for b in t["beats"]:
            type_counts[b["type"]] = type_counts.get(b["type"], 0) + 1

    print(f"\n--- RESULTS ---")
    print(f"Topics: {n_topics}")
    print(f"Beats: {n_beats}")
    print(f"Coverage: {pct:.1f}% (was {existing_pct:.1f}%)")
    print(f"Gaps: {len(gaps)} totaling {total_gap:.0f}s")
    print(f"Beat types: {type_counts}")

    if gaps:
        print(f"\nGaps:")
        for g in gaps[:10]:
            print(f"  {g['start_s']:.0f}s - {g['end_s']:.0f}s ({(g['end_s']-g['start_s'])/60:.1f}min)")
        if len(gaps) > 10:
            print(f"  ... and {len(gaps) - 10} more")

    print(f"\nTopics:")
    for t in beats_data["beats"]:
        first = t["beats"][0]["start_s"]
        last = t["beats"][-1]["end_s"]
        types = [b["type"] for b in t["beats"]]
        print(f"  {t['topic_id']} [{first:.0f}s-{last:.0f}s] {t['topic_label']}")
        print(f"    beats: {' → '.join(types)}")

    # Save as beats.json (overwrite)
    out_path = project_path / "beats.json"
    json.dump(beats_data, open(out_path, "w"), indent=2)
    print(f"\nSaved to {out_path}")

    return pct


if __name__ == "__main__":
    projects = sys.argv[1:] if len(sys.argv) > 1 else ["6c901929", "42570241", "d7e9e793"]

    results = {}
    for pid in projects:
        try:
            pct = test_project(pid)
            results[pid] = pct
        except Exception as e:
            print(f"\nERROR on {pid}: {e}")
            import traceback
            traceback.print_exc()
            results[pid] = None

    print(f"\n{'='*60}")
    print("SUMMARY")
    for pid, pct in results.items():
        if pct is not None:
            print(f"  {pid}: {pct:.1f}%")
        else:
            print(f"  {pid}: FAILED")
