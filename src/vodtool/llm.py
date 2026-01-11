"""LLM client module for vodtool."""

import json
import logging
import os
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger("vodtool")

# Load environment variables from .env
load_dotenv()


def get_anthropic_client():
    """Get Anthropic client, raising clear error if API key missing."""
    try:
        from anthropic import Anthropic
    except ImportError:
        raise ImportError(
            "anthropic package not installed. Run: pip install anthropic"
        )

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY not set. Add to .env file or set environment variable."
        )

    return Anthropic(api_key=api_key)


def segment_topics_with_llm(
    client,
    chunks: list[dict],
    max_topics: Optional[int] = None,
) -> list[dict]:
    """
    Have Claude analyze chunks and return topic structure.

    Args:
        client: Anthropic client
        chunks: List of chunks with id, start, end, text
        max_topics: Optional maximum number of topics to create

    Returns:
        List of topic dicts with label, chunk_ids, summary
    """
    # Format chunks for the prompt
    chunks_text = "\n".join(
        [
            f"[{c['id']}] ({c['start']:.1f}s - {c['end']:.1f}s): {c['text']}"
            for c in chunks
        ]
    )

    max_topics_instruction = ""
    if max_topics:
        max_topics_instruction = f"\n- Create at most {max_topics} topics"

    prompt = f"""Analyze this video transcript and identify the distinct topics discussed.

TRANSCRIPT (with chunk IDs and timestamps):
{chunks_text}

Return a JSON array of topics. Each topic should have:
- "label": A short descriptive label (3-6 words)
- "chunk_ids": Array of chunk IDs that belong to this topic (e.g., ["chunk_0000", "chunk_0001"])
- "summary": One sentence describing what's discussed

Rules:
- Topics should be coherent subjects/themes, not arbitrary splits
- A topic can have non-contiguous chunks (if speaker returns to a subject)
- Every chunk ID must belong to exactly one topic
- Prefer fewer, broader topics over many small ones
- Don't split mid-conversation just because vocabulary changes{max_topics_instruction}

Return ONLY the JSON array, no other text or markdown formatting."""

    logger.info(f"Sending {len(chunks)} chunks to LLM for topic segmentation")

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = response.content[0].text.strip()

    # Handle potential markdown code blocks
    if response_text.startswith("```"):
        # Remove markdown code block
        lines = response_text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        response_text = "\n".join(lines[1:-1])

    try:
        topics = json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        logger.error(f"Response was: {response_text[:500]}...")
        raise ValueError(f"LLM returned invalid JSON: {e}")

    logger.info(f"LLM identified {len(topics)} topics")

    return topics
