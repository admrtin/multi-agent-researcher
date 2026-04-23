from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import requests
from dotenv import load_dotenv
from google.adk.tools.tool_context import ToolContext

load_dotenv()



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


def search_arxiv(query: str, max_results: int = 10) -> str:
    """
    Search the ArXiv database using a query and return a list of papers.
    Returns a JSON string containing a list of dictionaries with title, year, and pdf_link.
    """


    url = "http://export.arxiv.org/api/query"
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results
    }
    print(f"Making request to ArXiv with query: {query}")
    
    import time
    max_retries = 3
    xml_data = None
    for attempt in range(max_retries):
        try:
            # Respect ArXiv's rate limit of 1 request / 3 seconds.
            time.sleep(3.1)
            response = requests.get(url, params=params, timeout=30)
            if response.status_code == 429:
                if attempt == max_retries - 1:
                    return json.dumps([{"error": "Failed to retrieve papers: HTTP 429 Too Many Requests"}], indent=2)
                print(f"Rate limited by ArXiv. Retrying in 10 seconds...")
                time.sleep(10)
                continue
            response.raise_for_status()
            xml_data = response.text
            break
        except Exception as e:
            if attempt == max_retries - 1:
                return json.dumps([{"error": f"Failed to retrieve papers: {e}"}], indent=2)
            print(f"Error accessing ArXiv: {e}. Retrying in 5 seconds...")
            time.sleep(5)

    if not xml_data:
        return json.dumps([{"error": "Failed to retrieve papers: XML data is empty"}], indent=2)

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        return json.dumps([{"error": f"Failed to parse XML response: {e}"}], indent=2)
        
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    
    papers = []
    for entry in root.findall('atom:entry', ns):
        title_element = entry.find('atom:title', ns)
        title = title_element.text.replace('\n', ' ').strip() if title_element is not None and title_element.text else "Unknown Title"
        
        published_element = entry.find('atom:published', ns)
        year = published_element.text[:4] if published_element is not None and published_element.text else "Unknown Year"
        
        pdf_link = ""
        for link in entry.findall('atom:link', ns):
            if link.attrib.get('title') == 'pdf':
                pdf_link = link.attrib.get('href', '')
                break
        
        if not pdf_link:
            for link in entry.findall('atom:link', ns):
                if 'pdf' in link.attrib.get('href', ''):
                    pdf_link = link.attrib.get('href', '')
                    break
        
        summary_element = entry.find('atom:summary', ns)
        abstract = summary_element.text.strip().replace('\n', ' ') if summary_element is not None and summary_element.text else "No abstract available"
                    
        papers.append({
            "title": title,
            "year": year,
            "pdf_link": pdf_link,
            "abstract": abstract
        })
    print(f"Found {len(papers)} papers on ArXiv.")
    return json.dumps(papers, indent=2)



def download_arxiv_pdf(pdf_url: str, save_dir: str, filename: str = "") -> str:
    """
    Downloads a PDF from an ArXiv PDF URL and saves it to disk.

    Args:
        pdf_url: The ArXiv PDF URL (e.g. http://arxiv.org/pdf/2301.12345v1).
        save_dir: The run output directory. PDFs are saved under save_dir/papers/.
        filename: Optional custom filename. If empty, auto-generated from the URL.

    Returns:
        A status message indicating success or failure, with the saved file path.
    """
    import re
    import time

    papers_dir = Path(save_dir) / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)

    if not filename:
        # Extract arxiv ID from URL and use as filename
        # e.g. http://arxiv.org/pdf/2301.12345v1 -> 2301.12345v1.pdf
        url_path = pdf_url.rstrip("/").split("/")[-1]
        # Remove any existing .pdf extension, then add it back
        sanitized = re.sub(r"\.pdf$", "", url_path, flags=re.IGNORECASE)
        sanitized = re.sub(r"[^\w.\-]", "_", sanitized)
        filename = f"{sanitized}.pdf"

    save_path = papers_dir / filename

    max_retries = 3
    for attempt in range(max_retries):
        try:
            time.sleep(3.1)  # Respect ArXiv rate limit
            print(f"Downloading PDF from {pdf_url} (attempt {attempt + 1})...")
            response = requests.get(pdf_url, timeout=60, stream=True)

            if response.status_code == 429:
                if attempt == max_retries - 1:
                    return f"Failed to download {pdf_url}: HTTP 429 Too Many Requests after {max_retries} attempts."
                print("Rate limited. Retrying in 10 seconds...")
                time.sleep(10)
                continue

            response.raise_for_status()

            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return f"Successfully downloaded: {save_path.as_posix()}"

        except Exception as e:
            if attempt == max_retries - 1:
                return f"Failed to download {pdf_url} after {max_retries} attempts: {e}"
            print(f"Download error: {e}. Retrying in 5 seconds...")
            time.sleep(5)

    return f"Failed to download {pdf_url}: exhausted all retries."


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

    try:
        # If data is already a dict or list, write it directly
        if isinstance(data, (dict, list)):
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            msg = f"[TOOL] save_json_file: Saved to {path.as_posix()}"
            print(msg, flush=True)
            return f"Successfully saved {path.as_posix()} to disk."

        # Otherwise treat as a string that may need cleaning
        clean_data = data.strip()
        # Sometimes LLMs wrap json in markdown blocks
        if clean_data.startswith("```json"):
            clean_data = clean_data[7:]
        if clean_data.startswith("```"):
            clean_data = clean_data[3:]
        if clean_data.endswith("```"):
            clean_data = clean_data[:-3]
        clean_data = clean_data.strip()

        import ast
        try:
            parsed = json.loads(clean_data)
        except json.JSONDecodeError:
            # Fall back to ast.literal_eval for single-quoted dict strings
            parsed = ast.literal_eval(clean_data)

        path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
        msg = f"[TOOL] save_json_file: Saved to {path.as_posix()}"
        print(msg, flush=True)
        return f"Successfully saved {path.as_posix()} to disk."
    except Exception as e:
        msg = f"[TOOL ERROR] save_json_file: {e}"
        print(msg, file=sys.stderr, flush=True)
        return f"Error saving JSON: {e}. Please ensure you are outputting a valid JSON string without single quotes for property names."



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