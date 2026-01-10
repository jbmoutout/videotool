"""Topic labeling command for vodtool using TF-IDF keyword extraction."""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from rich.console import Console
from sklearn.feature_extraction.text import TfidfVectorizer

console = Console()
logger = logging.getLogger("vodtool")


def load_chunk_texts(db_path: Path, chunk_ids: list[str]) -> list[str]:
    """
    Load text for specific chunks from database.

    Args:
        db_path: Path to embeddings.sqlite
        chunk_ids: List of chunk IDs to load

    Returns:
        List of text strings in same order as chunk_ids
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Build query with placeholders
    placeholders = ",".join("?" * len(chunk_ids))
    query = f"""
        SELECT chunk_id, text
        FROM chunks
        WHERE chunk_id IN ({placeholders})
    """

    cursor.execute(query, chunk_ids)
    rows = cursor.fetchall()
    conn.close()

    # Build dict for ordered retrieval
    text_dict = {row[0]: row[1] for row in rows}

    # Return in same order as chunk_ids
    texts = [text_dict[cid] for cid in chunk_ids]

    return texts


def extract_tfidf_keywords(
    documents: list[str], n_keywords: int = 5
) -> list[list[str]]:
    """
    Extract top TF-IDF keywords for each document.

    Args:
        documents: List of text documents (one per topic)
        n_keywords: Number of top keywords to extract per document

    Returns:
        List of keyword lists (one list per document)
    """
    if not documents:
        return []

    # Create TF-IDF vectorizer
    vectorizer = TfidfVectorizer(
        max_features=1000,
        stop_words="english",
        ngram_range=(1, 2),  # Support unigrams and bigrams
        min_df=1,  # Allow rare terms (small corpus)
    )

    try:
        tfidf_matrix = vectorizer.fit_transform(documents)
    except ValueError as e:
        logger.warning(f"TF-IDF extraction failed: {e}")
        return [[] for _ in documents]

    feature_names = vectorizer.get_feature_names_out()

    # Extract top keywords for each document
    keywords_per_doc = []

    for doc_idx in range(len(documents)):
        # Get TF-IDF scores for this document
        doc_vector = tfidf_matrix[doc_idx].toarray()[0]

        # Get indices of top scores
        top_indices = doc_vector.argsort()[-n_keywords:][::-1]

        # Get corresponding keywords
        keywords = [feature_names[i] for i in top_indices if doc_vector[i] > 0]

        keywords_per_doc.append(keywords)

    return keywords_per_doc


def generate_label_from_keywords(keywords: list[str]) -> str:
    """
    Generate a readable label from keywords.

    Args:
        keywords: List of keywords

    Returns:
        Formatted label string
    """
    if not keywords:
        return "Unlabeled Topic"

    # Take top 3-6 keywords
    selected = keywords[:6]

    # Capitalize first letter of each word
    selected = [kw.title() for kw in selected]

    # Join with spaces
    label = " ".join(selected)

    # Truncate if too long
    if len(label) > 60:
        label = label[:57] + "..."

    return label


def label_topics_command(
    project_path: Path, force: bool = False
) -> Optional[Path]:
    """
    Generate human-readable labels for topics using TF-IDF.

    Args:
        project_path: Path to the project directory
        force: Force re-labeling even if labels exist

    Returns:
        Path to the topic_map_labeled.json file, or None if labeling failed
    """
    # Validate project directory
    if not project_path.exists():
        console.print(
            f"[red]Error: Project directory not found: {project_path}[/red]"
        )
        return None

    if not project_path.is_dir():
        console.print(f"[red]Error: Not a directory: {project_path}[/red]")
        return None

    # Check for topic_map.json
    topic_map_path = project_path / "topic_map.json"
    if not topic_map_path.exists():
        console.print(
            f"[red]Error: Topic map not found: {topic_map_path}[/red]"
        )
        console.print("Run 'vodtool topics' first to create topic map.")
        return None

    # Check for embeddings database (has chunk texts)
    db_path = project_path / "embeddings.sqlite"
    if not db_path.exists():
        console.print(
            f"[red]Error: Embeddings database not found: {db_path}[/red]"
        )
        return None

    # Load topic map
    console.print(f"[cyan]Loading topic map...[/cyan]")

    try:
        with open(topic_map_path, "r", encoding="utf-8") as f:
            topics = json.load(f)
    except Exception as e:
        console.print(f"[red]Error loading topic map: {e}[/red]")
        return None

    if not topics:
        console.print("[yellow]Warning: No topics found[/yellow]")
        return None

    logger.info(f"Loaded {len(topics)} topics")

    # Check if labeled version exists
    labeled_path = project_path / "topic_map_labeled.json"

    if labeled_path.exists() and not force:
        console.print(
            f"[yellow]Labeled topic map already exists: {labeled_path}[/yellow]"
        )
        console.print("Use --force to regenerate labels.")

        # Load existing labels to preserve manual edits
        try:
            with open(labeled_path, "r", encoding="utf-8") as f:
                existing_topics = json.load(f)

            # Merge: keep existing labels, add new topics
            existing_ids = {t["topic_id"] for t in existing_topics}

            for topic in topics:
                if topic["topic_id"] not in existing_ids:
                    console.print(
                        f"[cyan]Found new topic: {topic['topic_id']}[/cyan]"
                    )
                    existing_topics.append(topic)

            if len(existing_topics) == len(topics):
                console.print(
                    "[green]All topics already labeled. No changes needed.[/green]"
                )
                return labeled_path

            # Save merged version
            with open(labeled_path, "w", encoding="utf-8") as f:
                json.dump(existing_topics, f, indent=2, ensure_ascii=False)

            console.print(f"[green]Added labels for new topics[/green]")
            return labeled_path

        except Exception as e:
            console.print(
                f"[yellow]Warning: Could not load existing labels: {e}[/yellow]"
            )
            console.print("Regenerating all labels...")

    # Collect text for each topic
    console.print(f"[cyan]Loading topic texts...[/cyan]")

    topic_documents = []
    topic_ids = []

    for topic in topics:
        # Collect all chunk IDs for this topic
        chunk_ids = []
        for span in topic["spans"]:
            chunk_ids.extend(span["chunk_ids"])

        # Remove duplicates while preserving order
        seen = set()
        chunk_ids = [cid for cid in chunk_ids if not (cid in seen or seen.add(cid))]

        # Load texts
        try:
            texts = load_chunk_texts(db_path, chunk_ids)
            document = " ".join(texts)
            topic_documents.append(document)
            topic_ids.append(topic["topic_id"])
        except Exception as e:
            logger.warning(f"Could not load text for topic {topic['topic_id']}: {e}")
            topic_documents.append("")
            topic_ids.append(topic["topic_id"])

    logger.info(f"Loaded text for {len(topic_documents)} topics")

    # Extract keywords using TF-IDF
    console.print(f"[cyan]Extracting keywords with TF-IDF...[/cyan]")

    try:
        keywords_per_topic = extract_tfidf_keywords(topic_documents, n_keywords=6)
    except Exception as e:
        console.print(f"[red]Error extracting keywords: {e}[/red]")
        return None

    # Generate labels
    console.print(f"[cyan]Generating labels...[/cyan]")

    for topic, keywords in zip(topics, keywords_per_topic):
        label = generate_label_from_keywords(keywords)
        topic["label"] = label
        logger.info(f"{topic['topic_id']}: {label} (keywords: {keywords})")

    # Save labeled topic map
    try:
        with open(labeled_path, "w", encoding="utf-8") as f:
            json.dump(topics, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved topic_map_labeled.json: {labeled_path}")
    except Exception as e:
        console.print(f"[red]Error saving labeled topic map: {e}[/red]")
        return None

    # Print summary
    console.print(f"\n[green]✓ Topic labeling complete![/green]")
    console.print(f"[bold]Topics labeled:[/bold] {len(topics)}")
    console.print(f"[bold]Output:[/bold] {labeled_path}")
    console.print("\n[bold]Topic Labels:[/bold]")

    for topic in topics:
        console.print(f"  {topic['topic_id']}: {topic['label']}")

    return labeled_path
