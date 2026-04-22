from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from google.adk.tools.tool_context import ToolContext

load_dotenv()

SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY")



def exit_loop(tool_context: ToolContext) -> dict:
    """
    Signals the enclosing LoopAgent to stop iterating immediately.

    Call this tool once validation has passed (or when the task is
    confirmed complete) to prevent the LoopAgent from running further
    researcher → validator cycles unnecessarily.
    """
    tool_context.actions.escalate = True
    return {"status": "loop_exited", "message": "Loop terminated successfully."}


def save_markdown_file(filename: str, content: str) -> str:
    """
    Saves markdown content to disk. Creates parent directories if needed.
    """
    try:
        path = Path(filename)
        if path.suffix.lower() != ".md":
            path = path.with_suffix(".md")
        
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        msg = f"[TOOL] save_markdown_file: Saved {len(content)} bytes to {path.as_posix()}"
        print(msg, flush=True)
        return f"Successfully saved {path.as_posix()} to disk."
    except Exception as e:
        msg = f"[TOOL ERROR] save_markdown_file: {e}"
        print(msg, file=sys.stderr, flush=True)
        return f"Error saving file: {e}"

def read_researcher_output(researcher_output_path: str) -> str:
    """Reads a researcher output file and returns its content for validation."""
    try:
        path = Path(researcher_output_path)
        exists = path.exists()
        msg = f"[TOOL] read_researcher_output: Reading {path.as_posix()} (exists={exists})"
        print(msg, flush=True)
        if not exists:
            return json.dumps({"status": "error", "message": f"File not found: {researcher_output_path}"})
        content = path.read_text(encoding="utf-8")
        return json.dumps({"status": "success", "content": content})
    except Exception as e:
        msg = f"[TOOL ERROR] read_researcher_output: {e}"
        print(msg, file=sys.stderr, flush=True)
        return json.dumps({"status": "error", "message": str(e)})

def load_json_file(filename: str) -> str:
    """
    Loads a JSON file from disk and returns it as a JSON string.
    """
    try:
        path = Path(filename)
        msg = f"[TOOL] load_json_file: Reading {path.as_posix()}"
        print(msg, flush=True)
        if not path.exists():
             return json.dumps({"status": "error", "message": f"File not found: {filename}"})
        return path.read_text(encoding="utf-8")
    except Exception as e:
        msg = f"[TOOL ERROR] load_json_file: {e}"
        print(msg, file=sys.stderr, flush=True)
        return json.dumps({"status": "error", "message": str(e)})


def create_run_output_dir(base_dir: str = "outputs", keep_last: int = 3) -> str:
    """
    Creates a timestamped run folder inside the outputs directory and
    automatically deletes older run folders, keeping only the newest N runs.

    Example:
        outputs/run_2026_04_04_1530

    Args:
        base_dir: The parent directory where run folders should be created.
        keep_last: Number of most recent runs to keep.

    Returns:
        The path to the created run directory as a string.
    """
    base_path = Path(base_dir)
    base_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("run_%Y_%m_%d_%H%M%S")
    run_dir = base_path / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    run_dirs = sorted(
        [path for path in base_path.iterdir() if path.is_dir() and path.name.startswith("run_")],
        key=lambda path: path.name,
    )

    if len(run_dirs) > keep_last:
        to_delete = run_dirs[:-keep_last]
        for old_dir in to_delete:
            try:
                shutil.rmtree(old_dir)
            except PermissionError:
                print(f"Warning: Could not delete locked run folder: {old_dir}")
            except OSError as exc:
                print(f"Warning: Could not delete {old_dir}: {exc}")

    return run_dir.as_posix()


def _semantic_scholar_headers() -> dict[str, str]:
    """
    Build request headers for Semantic Scholar. If an API key is available
    in the environment, include it. Otherwise return empty headers so the
    app can still work without authentication.
    """
    headers: dict[str, str] = {}
    if SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_API_KEY
    return headers


def scrape_research_articles(
    topic: str,
    max_results: int = 10,
    max_references_per_paper: int = 5,
) -> str:
    """
    Search for research papers related to a topic and return abstracts plus references.
    """
    print(f"[TOOL] scrape_research_articles: Searching for '{topic}'", flush=True)
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
        response = requests.get(
            url,
            params=params,
            headers=_semantic_scholar_headers(),
            timeout=30,
        )
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
                "abstract": (paper.get("abstract") or "No abstract available.")[:500] + "...",
                "reference_count": paper.get("referenceCount", 0),
                "references": references[:3],
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


def research_single_paper(
    paper_title: str,
    max_references: int = 5,
    max_citations: int = 5,
) -> str:
    """
    Retrieve metadata for a single paper from Semantic Scholar, including
    abstract, references, and citations when available.
    """
    url = "https://api.semanticscholar.org/graph/v1/paper/search"

    params = {
        "query": paper_title,
        "limit": 1,
        "fields": ",".join(
            [
                "title",
                "year",
                "abstract",
                "url",
                "venue",
                "authors",
                "citationCount",
                "referenceCount",
                "references.title",
                "references.year",
                "references.url",
                "citations.title",
                "citations.year",
                "citations.url",
            ]
        ),
    }

    try:
        response = requests.get(
            url,
            params=params,
            headers=_semantic_scholar_headers(),
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        return json.dumps(
            {
                "paper_title": paper_title,
                "status": "error",
                "message": f"Failed to retrieve paper: {exc}",
            },
            indent=2,
        )

    data = payload.get("data", [])
    if not data:
        return json.dumps(
            {
                "paper_title": paper_title,
                "status": "error",
                "message": "No paper found for the given title.",
            },
            indent=2,
        )

    paper = data[0]

    author_list = paper.get("authors") or []
    authors = [author.get("name", "Unknown Author") for author in author_list[:10]]

    raw_references = paper.get("references") or []
    references = [
        {
            "title": ref.get("title", "Unknown Title"),
            "year": ref.get("year"),
            "url": ref.get("url"),
        }
        for ref in raw_references[:max_references]
    ]

    raw_citations = paper.get("citations") or []
    citations = [
        {
            "title": cite.get("title", "Unknown Title"),
            "year": cite.get("year"),
            "url": cite.get("url"),
        }
        for cite in raw_citations[:max_citations]
    ]

    return json.dumps(
        {
            "status": "success",
            "paper": {
                "title": paper.get("title", "Unknown Title"),
                "year": paper.get("year"),
                "venue": paper.get("venue"),
                "url": paper.get("url"),
                "authors": authors,
                "abstract": paper.get("abstract") or "No abstract available.",
                "citation_count": paper.get("citationCount", 0),
                "reference_count": paper.get("referenceCount", 0),
                "references": references,
                "citations": citations,
            },
        },
        indent=2,
    )


def save_json_file(filename: str, data) -> str:
    """
    Saves JSON content to disk.

    ``data`` can be either:
    - A JSON-encoded string (e.g. '{"key": "value"}')
    - A pre-parsed Python dict/list (passed directly by an LLM agent)
    """
    path = Path(filename)

    if path.suffix.lower() != ".json":
        path = path.with_suffix(".json")

    path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(data, (dict, list)):
        parsed = data
    else:
        # data is expected to be a JSON string
        parsed = json.loads(data)

    path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")

    return f"Successfully saved {path.as_posix()} to disk."





def get_latest_planner_manifest(base_dir: str = "outputs") -> str:
    """
    Returns the path to the most recent planner_manifest.json file
    inside the planner outputs directory.

    Args:
        base_dir: Base directory containing planner run folders.

    Returns:
        The path to the latest planner_manifest.json file as a string.

    Raises:
        FileNotFoundError: If no planner manifest files are found.
    """
    base_path = Path(base_dir)
    if not base_path.exists():
        raise FileNotFoundError(f"Planner output directory does not exist: {base_dir}")

    run_dirs = sorted(
        [path for path in base_path.iterdir() if path.is_dir() and path.name.startswith("run_")],
        key=lambda path: path.name,
    )

    if not run_dirs:
        raise FileNotFoundError(f"No planner run folders found in: {base_dir}")

    for run_dir in reversed(run_dirs):
        manifest_path = run_dir / "planner_manifest.json"
        if manifest_path.exists():
            return manifest_path.as_posix()

    raise FileNotFoundError(f"No planner_manifest.json found in any run folder under: {base_dir}")

def list_researcher_outputs(base_dir: str = "outputs") -> str:
    """Lists all researcher output files available for validation."""
    path = Path(base_dir)
    files = list(path.rglob("*.json")) + list(path.rglob("*.md"))
    return json.dumps([f.as_posix() for f in files], indent=2)



def get_latest_run_dir(base_dir: str = "outputs") -> str:
    """Returns the most recent run directory path."""
    base_path = Path(base_dir)
    run_dirs = sorted(base_path.glob("run_*"), key=lambda p: p.name)
    if not run_dirs:
        raise FileNotFoundError("No run directories found.")
    return run_dirs[-1].as_posix()

@dataclass(frozen=True)
class GeminiModel:
    ROOT: str = "gemini-2.5-flash"
    PLANNER: str = "gemini-2.5-flash"
    RESEARCHER: str = "gemini-2.5-flash"
    VALIDATOR: str = "gemini-2.5-flash"
    SYNTHESIZER: str = "gemini-2.5-flash"

# Instance for easy import
gemini_models = GeminiModel()