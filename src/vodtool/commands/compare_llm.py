"""Compare LLM providers for topic segmentation."""

import json
import logging
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from vodtool.utils.file_utils import safe_read_json
from vodtool.utils.validation import validate_project_path

console = Console()
logger = logging.getLogger("vodtool")


def compare_llm_topics(
    project_path: Path,
    max_topics: Optional[int] = None,
    ollama_model: str = "qwen2.5:3b",
) -> None:
    """
    Generate topics with both Claude and local LLM, then compare results.

    Args:
        project_path: Path to the project directory
        max_topics: Optional maximum number of topics
        ollama_model: Ollama model to use for comparison
    """
    from vodtool.commands.llm_topics import build_topic_map

    # Validate project directory
    error = validate_project_path(project_path)
    if error:
        console.print(f"[red]Error: {error}[/red]")
        return

    # Check for chunks.json
    chunks_path = project_path / "chunks.json"
    if not chunks_path.exists():
        console.print(f"[red]Error: chunks.json not found: {chunks_path}[/red]")
        console.print("Run 'vodtool chunks' first to create chunks.")
        return

    # Load chunks
    console.print("[cyan]Loading chunks...[/cyan]")
    chunks = safe_read_json(chunks_path)
    if chunks is None:
        return

    console.print(f"[cyan]Loaded {len(chunks)} chunks[/cyan]\n")

    # Results storage
    results = {}

    # Generate topics with Claude (Anthropic)
    console.print(Panel("[bold cyan]Generating topics with Claude (Anthropic API)[/bold cyan]"))
    try:
        from vodtool.llm import get_anthropic_client, segment_topics_with_llm

        client = get_anthropic_client()

        start_time = time.time()
        claude_result = segment_topics_with_llm(client, chunks, max_topics=max_topics)
        claude_time = time.time() - start_time

        claude_topic_map = build_topic_map(claude_result, chunks)

        # Save Claude results
        claude_path = project_path / "topic_map_claude.json"
        with claude_path.open("w", encoding="utf-8") as f:
            json.dump(claude_topic_map, f, indent=2, ensure_ascii=False)

        results["claude"] = {
            "success": True,
            "topic_map": claude_topic_map,
            "time": claude_time,
            "path": claude_path,
        }
        console.print(f"[green]✓ Claude generated {len(claude_topic_map)} topics in {claude_time:.1f}s[/green]")
        console.print(f"[dim]Saved to: {claude_path}[/dim]\n")

    except Exception as e:
        console.print(f"[red]✗ Claude failed: {e}[/red]\n")
        results["claude"] = {"success": False, "error": str(e)}

    # Generate topics with Ollama (local LLM)
    console.print(Panel(f"[bold cyan]Generating topics with Ollama ({ollama_model})[/bold cyan]"))
    try:
        from vodtool.llm import segment_topics_with_local_llm

        start_time = time.time()
        ollama_result = segment_topics_with_local_llm(
            chunks,
            model=ollama_model,
            max_topics=max_topics,
        )
        ollama_time = time.time() - start_time

        ollama_topic_map = build_topic_map(ollama_result, chunks)

        # Save Ollama results
        ollama_path = project_path / "topic_map_ollama.json"
        with ollama_path.open("w", encoding="utf-8") as f:
            json.dump(ollama_topic_map, f, indent=2, ensure_ascii=False)

        results["ollama"] = {
            "success": True,
            "topic_map": ollama_topic_map,
            "time": ollama_time,
            "path": ollama_path,
        }
        console.print(f"[green]✓ Ollama generated {len(ollama_topic_map)} topics in {ollama_time:.1f}s[/green]")
        console.print(f"[dim]Saved to: {ollama_path}[/dim]\n")

    except Exception as e:
        console.print(f"[red]✗ Ollama failed: {e}[/red]\n")
        results["ollama"] = {"success": False, "error": str(e)}

    # Compare results
    if results.get("claude", {}).get("success") and results.get("ollama", {}).get("success"):
        console.print(Panel("[bold yellow]Comparison Results[/bold yellow]"))

        # Performance comparison
        perf_table = Table(title="Performance Metrics")
        perf_table.add_column("Provider", style="cyan")
        perf_table.add_column("Time", style="yellow")
        perf_table.add_column("Topics", style="green")
        perf_table.add_column("Speed", style="blue")

        claude_time = results["claude"]["time"]
        ollama_time = results["ollama"]["time"]
        speedup = ollama_time / claude_time if claude_time > 0 else 0

        perf_table.add_row(
            "Claude (API)",
            f"{claude_time:.1f}s",
            str(len(results["claude"]["topic_map"])),
            "1.0x",
        )
        perf_table.add_row(
            f"Ollama ({ollama_model})",
            f"{ollama_time:.1f}s",
            str(len(results["ollama"]["topic_map"])),
            f"{speedup:.1f}x",
        )

        console.print(perf_table)
        console.print()

        # Side-by-side topic comparison
        comparison_table = Table(title="Side-by-Side Topic Comparison")
        comparison_table.add_column("Claude Label", style="cyan", width=40)
        comparison_table.add_column("Ollama Label", style="green", width=40)
        comparison_table.add_column("Duration", style="yellow")

        claude_topics = results["claude"]["topic_map"]
        ollama_topics = results["ollama"]["topic_map"]

        max_topics_count = max(len(claude_topics), len(ollama_topics))

        for i in range(max_topics_count):
            claude_label = claude_topics[i]["label"] if i < len(claude_topics) else "-"
            claude_duration = claude_topics[i]["duration_label"] if i < len(claude_topics) else "-"

            ollama_label = ollama_topics[i]["label"] if i < len(ollama_topics) else "-"
            ollama_duration = ollama_topics[i]["duration_label"] if i < len(ollama_topics) else "-"

            duration = f"C: {claude_duration} / O: {ollama_duration}"

            comparison_table.add_row(claude_label, ollama_label, duration)

        console.print(comparison_table)
        console.print()

        # Summary insights
        console.print(Panel("[bold]Summary Insights[/bold]"))

        # Topic count difference
        topic_diff = abs(len(claude_topics) - len(ollama_topics))
        if topic_diff == 0:
            console.print("[green]✓ Both providers identified the same number of topics[/green]")
        else:
            console.print(f"[yellow]⚠ Topic count differs by {topic_diff}[/yellow]")

        # Speed comparison
        if speedup < 1.5:
            console.print(f"[green]✓ Ollama is only {speedup:.1f}x slower (acceptable)[/green]")
        elif speedup < 3:
            console.print(f"[yellow]⚠ Ollama is {speedup:.1f}x slower (noticeable)[/yellow]")
        else:
            console.print(f"[red]⚠ Ollama is {speedup:.1f}x slower (significant)[/red]")

        # Cost comparison
        claude_cost = len(chunks) * 0.00002  # Rough estimate
        console.print(f"\n[dim]Estimated Claude API cost: ${claude_cost:.4f}[/dim]")
        console.print("[dim]Ollama cost: $0.00 (local)[/dim]")

    elif not results.get("claude", {}).get("success"):
        console.print("[yellow]⚠ Claude comparison unavailable (see error above)[/yellow]")
    elif not results.get("ollama", {}).get("success"):
        console.print("[yellow]⚠ Ollama comparison unavailable (see error above)[/yellow]")
