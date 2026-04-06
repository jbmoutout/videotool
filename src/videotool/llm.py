"""LLM client module for videotool."""

import json
import logging
import os
import time
from typing import Optional
from rich.console import Console

logger = logging.getLogger("videotool")
console = Console()

# API timeout settings
ANTHROPIC_TIMEOUT = 60  # seconds
OLLAMA_TIMEOUT = 120  # seconds (local models are slower)
MAX_RETRIES = 2  # retry once on transient failures


def get_anthropic_client():
    """Get Anthropic client, falling back to proxy if no local API key."""
    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise ImportError(
            "anthropic package not installed. Run: pip install anthropic",
        ) from e

    api_key = os.getenv("ANTHROPIC_API_KEY")
    proxy_url = os.getenv("VITE_API_PROXY_URL")

    if api_key:
        return Anthropic(api_key=api_key)

    if proxy_url:
        logger.info("Using proxy for Anthropic API")
        headers = {}
        auth_token = os.getenv("PROXY_AUTH_TOKEN")
        if not auth_token:
            raise ValueError(
                "PROXY_AUTH_TOKEN not set for proxy mode. "
                "Set PROXY_AUTH_TOKEN in .env alongside VITE_API_PROXY_URL"
            )
        headers["X-Proxy-Token"] = auth_token
        return Anthropic(
            api_key="proxy",
            base_url=f"{proxy_url.rstrip('/')}/anthropic",
            default_headers=headers,
        )

    raise ValueError(
        "ANTHROPIC_API_KEY not set and no proxy configured. "
        "Set ANTHROPIC_API_KEY or VITE_API_PROXY_URL in .env"
    )


def get_ollama_client(model: str = "qwen2.5:3b"):
    """
    Get OpenAI client configured for local Ollama server.

    Args:
        model: Ollama model name (default: qwen2.5:3b)

    Returns:
        OpenAI client configured for localhost:11434

    Raises:
        ImportError: If openai package not installed
        ConnectionError: If Ollama server not running or model not found
    """
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ImportError(
            "openai package not installed. Run: pip install 'videotool[llm]'",
        ) from e

    client = OpenAI(
        base_url="http://localhost:11434/v1",
        api_key="ollama",  # Dummy key required by OpenAI SDK
    )

    # Verify Ollama is running and model exists
    try:
        client.models.retrieve(model)
    except Exception as e:
        raise ConnectionError(
            f"Ollama not running or model '{model}' not found.\n"
            f"Install Ollama: https://ollama.ai\n"
            f"Pull model: ollama pull {model}",
        ) from e

    return client


def _build_topic_extraction_prompt(
    chunks: list[dict],
    max_topics: Optional[int] = None,
    chat_context: Optional[str] = None,
) -> str:
    """
    Build the prompt for topic extraction (shared between providers).

    Args:
        chunks: List of chunks with id, start, end, text
        max_topics: Optional maximum number of topics to create
        chat_context: Optional formatted Twitch chat replay string

    Returns:
        Formatted prompt string
    """
    # Format chunks for the prompt
    chunks_text = "\n".join(
        [f"[{c['id']}] ({c['start']:.1f}s - {c['end']:.1f}s): {c['text']}" for c in chunks],
    )

    if max_topics:
        max_topics_instruction = f"\n- Create at most {max_topics} topics"
    else:
        max_topics_instruction = (
            "\n- Create as many topics as the content naturally has"
            " — don't merge distinct subjects just to reduce count"
        )

    chat_section = ""
    if chat_context:
        chat_section = f"""
TWITCH CHAT REPLAY (sampled — use as signal for audience reactions and topic shifts):
{chat_context}

"""

    prompt = f"""Analyze this video transcript and identify the distinct topics discussed.
{chat_section}
TRANSCRIPT (with chunk IDs and timestamps):
{chunks_text}

Return a JSON array of topics. Each topic should have:
- "label": A short, punchy label (3-6 words) in the host's voice/slang
- "chunk_ids": Array of chunk IDs that belong to this topic (e.g., ["chunk_0000", "chunk_0001"])
# - "summary": A FACTUAL one-sentence description using the host's vocabulary and energy

Rules:
- Topics should be coherent subjects/themes, not arbitrary splits
- A topic can have non-contiguous chunks (if speaker returns to a subject)
- Every chunk ID must belong to exactly one topic
- Prefer fewer, broader topics over many small ones
- Don't split mid-conversation just because vocabulary changes
- CRITICAL: A discussion that evolves naturally is ONE topic — only create a new topic when the conversation clearly moves to a NEW unrelated subject
- Ask yourself: "could a YouTube viewer reasonably watch these chunks in the same video?"
  If yes, they belong to the same topic
- Generate the "label" in the same language as the transcript
- Use the host's slang, expressions, and vocabulary from the transcript
- If chat replay is provided, use audience reactions to confirm topic boundaries

# CRITICAL for summaries - FACTUAL but with the host's voice:
# - Describe WHAT the topic contains, not what the host does
# - NEVER use first person (I, we, my, our, etc. in any language)
# - NEVER describe host actions (watches, shows, reacts, talks about, discovers, etc.)
# - BUT keep the host's tone, slang, and energy in the wording{max_topics_instruction}

Return ONLY the JSON array, no other text or markdown formatting."""

    return prompt  # noqa: RET504


def _parse_topic_response(response_text: str) -> list[dict]:
    """
    Parse LLM response and extract topic JSON (shared between providers).

    Args:
        response_text: Raw response text from LLM

    Returns:
        List of topic dicts with label, chunk_ids, summary

    Raises:
        ValueError: If response is not valid JSON
    """
    response_text = response_text.strip()

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
        raise ValueError(f"LLM returned invalid JSON: {e}") from e

    return topics


def segment_topics_with_llm(
    client,
    chunks: list[dict],
    max_topics: Optional[int] = None,
    chat_context: Optional[str] = None,
) -> list[dict]:
    """
    Have Claude analyze chunks and return topic structure.

    Args:
        client: Anthropic client
        chunks: List of chunks with id, start, end, text
        max_topics: Optional maximum number of topics to create
        chat_context: Optional Twitch chat replay string for context

    Returns:
        List of topic dicts with label, chunk_ids, summary

    Raises:
        ConnectionError: If API call fails after retries
        ValueError: If API returns invalid JSON
    """
    # Build prompt using shared logic
    prompt = _build_topic_extraction_prompt(chunks, max_topics, chat_context)

    logger.info(f"Sending {len(chunks)} chunks to Claude for topic segmentation")

    # Retry logic for transient network errors
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt}],
                timeout=ANTHROPIC_TIMEOUT,
            )

            response_text = response.content[0].text

            # Parse using shared logic
            topics = _parse_topic_response(response_text)

            logger.info(f"Claude identified {len(topics)} topics")
            return topics

        except Exception as e:
            last_error = e
            error_type = type(e).__name__

            # Check if it's a retryable error (network/timeout)
            is_retryable = "timeout" in error_type.lower() or "connection" in error_type.lower()
            if is_retryable and attempt < MAX_RETRIES:
                wait_time = 2**attempt  # Exponential backoff: 1s, 2s
                logger.warning(f"API call failed ({error_type}), retrying in {wait_time}s...")
                console.print(f"[yellow]Network error, retrying in {wait_time}s...[/yellow]")
                time.sleep(wait_time)
                continue

            # Exhausted retries or non-retryable error
            if is_retryable:
                msg = f"Claude API failed after {MAX_RETRIES + 1} attempts"
                console.print(f"[red]Error: {msg}[/red]")
                console.print(f"[dim]{error_type}: {e}[/dim]")
                raise ConnectionError(f"Claude API timeout/network error: {e}") from e

            # Non-retryable error (auth, invalid request, etc.)
            console.print("[red]Error: Claude API call failed[/red]")
            console.print(f"[dim]{error_type}: {e}[/dim]")
            raise

    # Should not reach here, but just in case
    raise ConnectionError(f"Claude API failed: {last_error}") from last_error


def _estimate_token_count(text: str) -> int:
    """
    Rough estimate of token count (1 token ≈ 4 characters).

    Args:
        text: Text to estimate

    Returns:
        Estimated token count
    """
    return len(text) // 4


def segment_topics_with_local_llm(
    chunks: list[dict],
    model: str = "qwen2.5:3b",
    max_topics: Optional[int] = None,
    chat_context: Optional[str] = None,
) -> list[dict]:
    """
    Use local LLM (via Ollama) to analyze chunks and return topic structure.

    Automatically handles large inputs by batching chunks to stay within
    the model's context window (3000 tokens per batch for safety margin).

    Args:
        chunks: List of chunks with id, start, end, text
        model: Ollama model name (default: qwen2.5:3b)
        max_topics: Optional maximum number of topics to create
        chat_context: Optional Twitch chat replay string for context

    Returns:
        List of topic dicts with label, chunk_ids, summary

    Raises:
        ImportError: If openai package not installed
        ConnectionError: If Ollama not running or model not found
    """
    client = get_ollama_client(model)

    # Check if we need to batch the input
    full_prompt = _build_topic_extraction_prompt(chunks, max_topics, chat_context)
    estimated_tokens = _estimate_token_count(full_prompt)

    # Context window limit (extremely conservative for small models on limited RAM)
    # llama3.2:1b has 4096 context but crashes on M2 8GB - use very small batches
    MAX_INPUT_TOKENS = 1000

    if estimated_tokens <= MAX_INPUT_TOKENS:
        # Input fits in one batch - use normal processing
        logger.info(f"Sending {len(chunks)} chunks to local LLM ({model}) for topic segmentation")

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": full_prompt}],
                temperature=0.3,
                max_tokens=4096,
                response_format={"type": "json_object"},
                timeout=OLLAMA_TIMEOUT,
            )

            response_text = response.choices[0].message.content
            topics = _parse_topic_response(response_text)

            logger.info(f"Local LLM identified {len(topics)} topics")
            return topics

        except Exception as e:
            error_type = type(e).__name__
            console.print(f"[red]Error: Local LLM ({model}) call failed[/red]")
            console.print(f"[dim]{error_type}: {e}[/dim]")
            if "timeout" in str(e).lower():
                console.print(
                    "[yellow]Tip: Try a smaller model (llama3.2:1b) or fewer chunks[/yellow]"
                )
            raise

    # Input is too large - batch processing
    logger.info(
        f"Input too large ({estimated_tokens} tokens estimated), "
        f"splitting {len(chunks)} chunks into batches"
    )

    # Calculate batch size based on average chunk token count
    avg_chunk_tokens = estimated_tokens // len(chunks)
    # Reserve ~500 tokens for prompt template
    batch_size = max(1, (MAX_INPUT_TOKENS - 500) // avg_chunk_tokens)

    logger.info(f"Processing in batches of ~{batch_size} chunks")

    # Process chunks in batches
    all_topics = []
    for i in range(0, len(chunks), batch_size):
        batch_chunks = chunks[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(chunks) + batch_size - 1) // batch_size

        logger.info(
            f"Processing batch {batch_num}/{total_batches} "
            f"({len(batch_chunks)} chunks)"
        )

        batch_prompt = _build_topic_extraction_prompt(batch_chunks, max_topics)

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": batch_prompt}],
                temperature=0.3,
                max_tokens=4096,
                response_format={"type": "json_object"},
                timeout=OLLAMA_TIMEOUT,
            )

            response_text = response.choices[0].message.content
            batch_topics = _parse_topic_response(response_text)

            all_topics.extend(batch_topics)

        except Exception as e:
            error_type = type(e).__name__
            msg = f"Error: Local LLM batch {batch_num}/{total_batches} failed"
            console.print(f"[red]{msg}[/red]")
            console.print(f"[dim]{error_type}: {e}[/dim]")
            raise

    logger.info(
        f"Local LLM identified {len(all_topics)} topics across "
        f"{total_batches} batches"
    )

    return all_topics
