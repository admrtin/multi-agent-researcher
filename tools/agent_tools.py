from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


def save_markdown_file(filename: str, content: str) -> str:
    """
    Saves markdown content to disk. Creates parent directories if needed.
    """
    path = Path(filename)

    if path.suffix.lower() != ".md":
        path = path.with_suffix(".md")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    return f"Successfully saved {path.as_posix()} to disk."


def create_run_output_dir(base_dir: str = "outputs") -> str:
    """
    Creates a timestamped run folder inside the outputs directory.

    Example:
        outputs/run_2026_04_04_1530

    Args:
        base_dir: The parent directory where run folders should be created.

    Returns:
        The path to the created run directory as a string.
    """
    timestamp = datetime.now().strftime("run_%Y_%m_%d_%H%M%S")
    run_dir = Path(base_dir) / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir.as_posix()


def cleanup_old_runs(base_dir: str = "outputs", keep_last: int = 3) -> str:
    """
    Deletes older run folders in the outputs directory, keeping only the newest N runs.

    Args:
        base_dir: The directory containing timestamped run folders.
        keep_last: Number of most recent runs to keep.

    Returns:
        A status message describing what was deleted or if no cleanup was needed.
    """
    base_path = Path(base_dir)
    base_path.mkdir(parents=True, exist_ok=True)

    run_dirs = sorted(
        [path for path in base_path.iterdir() if path.is_dir() and path.name.startswith("run_")],
        key=lambda path: path.name,
    )

    if len(run_dirs) <= keep_last:
        return f"No cleanup needed. Found {len(run_dirs)} run folder(s) in {base_path.as_posix()}."

    to_delete = run_dirs[:-keep_last]
    deleted = []

    for old_dir in to_delete:
        shutil.rmtree(old_dir, ignore_errors=True)
        deleted.append(old_dir.as_posix())

    return (
        f"Deleted {len(deleted)} old run folder(s). "
        f"Kept the most recent {keep_last} run(s). "
        f"Deleted: {deleted}"
    )


def scrape_research_articles(
    topic: str,
    max_results: int = 10,
    max_references_per_paper: int = 5,
) -> str:
    """
    Search for research papers related to a topic and return abstracts plus references.
    """
    url = "https://api.semanticscholar.org/graph/v1/paper/search"

    params = {
        "query": topic,
        "limit": max_results,
        "fields": ",".join(
            [
                "title",
                "year",
                "abstract",
                "url",
                "venue",
                "authors",
                "referenceCount",
                "references.title",
                "references.year",
                "references.url",
            ]
        ),
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        return json.dumps(
            {
                "topic": topic,
                "status": "error",
                "message": f"Failed to retrieve papers: {exc}",
                "papers": [],
            },
            indent=2,
        )

    papers: list[dict[str, Any]] = []

    for paper in payload.get("data", []):
        author_list = paper.get("authors") or []
        authors = [
            author.get("name", "Unknown Author")
            for author in author_list[:5]
        ]

        raw_references = paper.get("references") or []
        references = []
        for ref in raw_references[:max_references_per_paper]:
            references.append(
                {
                    "title": ref.get("title", "Unknown Title"),
                    "year": ref.get("year"),
                    "url": ref.get("url"),
                }
            )

        papers.append(
            {
                "title": paper.get("title", "Unknown Title"),
                "year": paper.get("year"),
                "venue": paper.get("venue"),
                "url": paper.get("url"),
                "authors": authors,
                "abstract": paper.get("abstract") or "No abstract available.",
                "reference_count": paper.get("referenceCount", 0),
                "references": references,
            }
        )

    return json.dumps(
        {
            "topic": topic,
            "status": "success",
            "paper_count": len(papers),
            "papers": papers,
        },
        indent=2,
    )


@dataclass(frozen=True)
class GeminiModel:
    ROOT: str = "gemini-3-flash-preview"
    PLANNER: str = "gemini-3-flash-preview"
    RESEARCHER: str = "gemini-3-flash-preview"
    SYNTHESIZER: str = "gemini-3-flash-preview"

# Instance for easy import
gemini_models = GeminiModel()