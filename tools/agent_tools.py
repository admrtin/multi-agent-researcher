from __future__ import annotations

import json
import logging
import mimetypes
import os
from pathlib import Path
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET
from typing import Any, TYPE_CHECKING

from google.adk.tools import BaseTool
from google import genai
from google.genai import types
import requests
from dotenv import load_dotenv
from google.adk.tools.tool_context import ToolContext

if TYPE_CHECKING:
    from google.adk.models.llm_request import LlmRequest
    from google.adk.tools import ToolContext

load_dotenv()

_C_TOOL     = "\033[94m"   # bright blue   — tool operations
_C_WARN     = "\033[93m"   # bright yellow — warnings
_C_ERROR    = "\033[91m"   # bright red    — errors
_C_CALLBACK = "\033[90m"   # dark gray     — loop control signals
_RESET      = "\033[0m"

# TUI callback hook — registered by dashboard.py on startup.
# Signature: (prefix: str, message: str, content_type: str, agent_name: str) -> None
# When None (default), stream_terminal_update falls through to print() as normal.
_tui_callback = None


def _tool_print(label: str, message: str) -> None:
    if _tui_callback is not None:
        _tui_callback(f"  ▸ [{label}]", message, "step", "TOOL")
    else:
        print(f"{_C_TOOL}  ▸ [{label}] {message}{_RESET}", flush=True)

def _warn_print(label: str, message: str) -> None:
    if _tui_callback is not None:
        _tui_callback(f"  ⚠ [{label}]", message, "warning", "TOOL")
    else:
        print(f"{_C_WARN}  ⚠ [{label}] {message}{_RESET}", flush=True)

def _error_print(label: str, message: str) -> None:
    if _tui_callback is not None:
        _tui_callback(f"  ✗ [{label}]", message, "error", "TOOL")
    else:
        print(f"{_C_ERROR}  ✗ [{label}] {message}{_RESET}", file=sys.stderr, flush=True)

def _callback_print(agent_id: str, message: str) -> None:
    """Colorized status line for LoopAgent before_agent_callback."""
    if _tui_callback is not None:
        _tui_callback(f"  ↩ [loop:{agent_id}]", message, "info", agent_id)
    else:
        print(f"{_C_CALLBACK}  ↩ [loop:{agent_id}] {message}{_RESET}", flush=True)


def stream_terminal_update(
    message: str,
    content_type: str = "info",
    agent_name: str = "SYSTEM",
) -> str:
    """
    Prints a colorized, immediate progress message to terminal output.
    Useful when running `adk run .` so users can see streaming status updates.
    """
    color_map = {
        "info": "\033[96m",
        "step": "\033[94m",
        "success": "\033[92m",
        "warning": "\033[93m",
        "error": "\033[91m",
        "planner": "\033[95m",
        "researcher": "\033[36m",
        "validator": "\033[33m",
        "synthesizer": "\033[35m",
    }
    reset = "\033[0m"

    import re as _re
    _AGENT_TYPES = {"planner", "researcher", "validator", "synthesizer"}

    key = (content_type or "info").strip().lower()
    color = color_map.get(key, color_map["info"])
    name_upper = agent_name.upper()

    if key in _AGENT_TYPES:
        # "researcher_1" / "RESEARCHER_1" → "[RESEARCHER:1]"
        # "PLANNER" / "SYNTHESIZER"        → "[PLANNER]" / "[SYNTHESIZER]"
        m = _re.search(r"[_\s](\d+)$", name_upper)
        if m:
            base = _re.sub(r"[_\s]\d+$", "", name_upper)
            prefix = f"[{base}:{m.group(1)}]"
        else:
            prefix = f"[{name_upper}]"
    else:
        prefix = f"[{name_upper}:{key.upper()}]"
    rendered = f"{color}{prefix} {message}{reset}"

    if _tui_callback is not None:
        _tui_callback(prefix, message, content_type, agent_name)
    else:
        print(rendered, flush=True)

    return f"{prefix} {message}"


def exit_loop(tool_context: ToolContext) -> dict:
    """
    Signals the current researcher/validator LoopAgent to stop iterating.

    Two mechanisms are used together:
    - actions.escalate = True  → consumed by LoopAgent._run_async_impl; this is
      what actually stops the running loop.  In ADK 1.27, ParallelAgent and
      SequentialAgent do not react to escalate, so only the enclosing LoopAgent
      stops — sibling researchers are unaffected.
    - state["loop_done_N"] = True  → checked by before_agent_callback as a
      guard against re-entry (the callback fires once before the loop starts,
      not between iterations, so it cannot stop a running loop by itself).
    """
    import re

    agent_name = getattr(tool_context, "agent_name", "") or ""
    match = re.search(r"_(\d+)$", agent_name)

    if match:
        loop_index = match.group(1)
        tool_context.state[f"loop_done_{loop_index}"] = True

    # Actually stop the running LoopAgent.
    tool_context.actions.escalate = True

    return {
        "status": "loop_exited",
        "message": f"Loop terminated successfully for {agent_name}.",
    }


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
        _tool_print("save_md", f"Saved {len(content)} bytes → {path.as_posix()}")
        return f"Successfully saved {path.as_posix()} to disk."
    except Exception as e:
        _error_print("save_md", str(e))
        return f"Error saving file: {e}"

def find_researcher_summary(researcher_dir: str) -> str:
    """Returns the filename of the single .md summary in a researcher output directory.

    Searches only the top level of researcher_dir (not subdirectories such as
    validator/).  Returns JSON with {"status": "success", "filename": "<name>.md",
    "path": "<full_path>"} or {"status": "error", "message": "..."}.
    """
    try:
        directory = Path(researcher_dir)
        if not directory.is_dir():
            return json.dumps({"status": "error", "message": f"Directory not found: {researcher_dir}"})
        md_files = [f for f in directory.glob("*.md") if f.is_file()]
        if not md_files:
            return json.dumps({"status": "error", "message": f"No .md summary file found in {researcher_dir}"})
        found = md_files[0]
        _tool_print("find_summary", found.as_posix())
        return json.dumps({"status": "success", "filename": found.name, "path": found.as_posix()})
    except Exception as e:
        _error_print("find_summary", str(e))
        return json.dumps({"status": "error", "message": str(e)})

def read_researcher_output(researcher_output_path: str) -> str:
    """Reads a researcher output file and returns its content for validation."""
    try:
        path = Path(researcher_output_path)
        exists = path.exists()
        _tool_print("read_file", f"{path.as_posix()} (exists={exists})")
        if not exists:
            return json.dumps({"status": "error", "message": f"File not found: {researcher_output_path}"})
        content = path.read_text(encoding="utf-8")
        return json.dumps({"status": "success", "content": content})
    except Exception as e:
        _error_print("read_file", str(e))
        return json.dumps({"status": "error", "message": str(e)})

def load_json_file(filename: str) -> str:
    """
    Loads a JSON file from disk and returns it as a JSON string.
    """
    try:
        path = Path(filename)
        _tool_print("load_json", path.as_posix())
        if not path.exists():
             return json.dumps({"status": "error", "message": f"File not found: {filename}"})
        return path.read_text(encoding="utf-8")
    except Exception as e:
        _error_print("load_json", str(e))
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
                _warn_print("create_dir", f"Could not delete locked run folder: {old_dir}")
            except OSError as exc:
                _warn_print("create_dir", f"Could not delete {old_dir}: {exc}")

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
    _tool_print("arXiv search", f"query={query!r}")

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
                _warn_print("arXiv search", "rate limited — retrying in 10 s…")
                time.sleep(10)
                continue
            response.raise_for_status()
            xml_data = response.text
            break
        except Exception as e:
            if attempt == max_retries - 1:
                return json.dumps([{"error": f"Failed to retrieve papers: {e}"}], indent=2)
            _warn_print("arXiv search", f"request error: {e} — retrying in 5 s…")
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
    _tool_print("arXiv search", f"found {len(papers)} papers")
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
            _tool_print("download", f"{pdf_url} (attempt {attempt + 1})")
            response = requests.get(pdf_url, timeout=60, stream=True)

            if response.status_code == 429:
                if attempt == max_retries - 1:
                    return f"Failed to download {pdf_url}: HTTP 429 Too Many Requests after {max_retries} attempts."
                _warn_print("download", "rate limited — retrying in 10 s…")
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
            _warn_print("download", f"error: {e} — retrying in 5 s…")
            time.sleep(5)

    return f"Failed to download {pdf_url}: exhausted all retries."


def bulk_download_arxiv_pdfs(manifest_path: str) -> str:
    """
    Downloads all PDFs listed in a planner manifest in parallel.

    Reads the manifest JSON, extracts every researcher entry's pdf_link,
    and downloads them concurrently using a thread pool.  Each PDF is
    saved under ``<run_folder>/papers/<arxiv_id>.pdf``.

    Args:
        manifest_path: Path to the planner_manifest.json file.

    Returns:
        A JSON string summarising successes and failures, including a
        mapping from researcher_id to the local PDF path.
    """
    import re
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    path = Path(manifest_path)
    if not path.exists():
        return json.dumps({"status": "error", "message": f"Manifest not found: {manifest_path}"})

    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return json.dumps({"status": "error", "message": f"Could not parse manifest: {exc}"})

    researchers = manifest.get("researchers", [])
    if not researchers:
        return json.dumps({"status": "error", "message": "No researchers found in manifest."})

    run_folder = path.parent.as_posix()
    papers_dir = Path(run_folder) / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)

    def _download_one(entry: dict) -> dict:
        """Download a single PDF; returns a result dict."""
        researcher_id = entry.get("id", "unknown")
        pdf_url = entry.get("pdf_link", "")
        if not pdf_url:
            return {"id": researcher_id, "status": "skipped", "message": "No pdf_link"}

        # Derive filename from URL
        url_tail = pdf_url.rstrip("/").split("/")[-1]
        sanitized = re.sub(r"\.pdf$", "", url_tail, flags=re.IGNORECASE)
        sanitized = re.sub(r"[^\w.\-]", "_", sanitized)
        filename = f"{sanitized}.pdf"
        save_path = papers_dir / filename

        if save_path.exists():
            return {
                "id": researcher_id,
                "status": "already_exists",
                "path": save_path.as_posix(),
            }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                time.sleep(3.1)  # ArXiv rate-limit
                _tool_print("bulk download", f"{researcher_id} → {pdf_url} (attempt {attempt + 1})")
                resp = requests.get(pdf_url, timeout=60, stream=True)

                if resp.status_code == 429:
                    if attempt == max_retries - 1:
                        return {"id": researcher_id, "status": "error", "message": "HTTP 429 after retries"}
                    time.sleep(10)
                    continue

                resp.raise_for_status()
                with open(save_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)

                return {"id": researcher_id, "status": "success", "path": save_path.as_posix()}

            except Exception as exc:
                if attempt == max_retries - 1:
                    return {"id": researcher_id, "status": "error", "message": str(exc)}
                time.sleep(5)

        return {"id": researcher_id, "status": "error", "message": "Exhausted retries."}

    # Run downloads in parallel (cap at 4 to stay friendly to ArXiv)
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_download_one, entry): entry for entry in researchers}
        for future in as_completed(futures):
            results.append(future.result())

    # Sort results by researcher id for readability
    results.sort(key=lambda r: r.get("id", ""))

    successes = [r for r in results if r["status"] in ("success", "already_exists")]
    failures = [r for r in results if r["status"] not in ("success", "already_exists")]

    summary = {
        "status": "complete",
        "total": len(results),
        "downloaded": len(successes),
        "failed": len(failures),
        "results": results,
    }
    _tool_print("bulk download", f"done — {len(successes)} downloaded, {len(failures)} failed")
    return json.dumps(summary, indent=2)


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
            _tool_print("save_json", f"Saved → {path.as_posix()}")
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
        _tool_print("save_json", f"Saved → {path.as_posix()}")
        return f"Successfully saved {path.as_posix()} to disk."
    except Exception as e:
        _error_print("save_json", str(e))
        return f"Error saving JSON: {e}. Please ensure you are outputting a valid JSON string without single quotes for property names."


class UploadPdfFileTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="upload_pdf_file",
            description="Uploads a local PDF to Gemini Files API and returns reusable file URI."
        )

    def _get_declaration(self):
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "filename": types.Schema(
                        type=types.Type.STRING,
                        description="Local PDF path"
                    )
                },
                required=["filename"]
            )
        )

    async def run_async(self, *, args, tool_context):
        filename = args["filename"]
        path = Path(filename)

        if not path.exists():
            _error_print("upload_pdf_file", f"File not found: {filename}")
            return {"status": "error", "message": "File not found"}

        cache_file = path.parent / "file_cache.json"
        cache_data = {}

        if cache_file.exists():
            try:
                with open(cache_file, "r") as f:
                    cache_data = json.load(f)
            except json.JSONDecodeError:
                pass 

        if path.name in cache_data:
            _tool_print("upload_pdf_file", f"⚡ Cache hit! Reusing URI for {path.name}")
            return {
                "status": "success",
                "filename": filename,
                "file_uri": cache_data[path.name],
                "mime_type": "application/pdf"
            }

        _tool_print("upload_pdf_file", f"☁️ Uploading {path.name} to Gemini...")
        
        client = genai.Client(
            api_key=os.getenv("GOOGLE_API_KEY"),
            vertexai=False 
        )
        uploaded = client.files.upload(file=path)

        cache_data[path.name] = uploaded.uri

        with open(cache_file, "w") as f:
            json.dump(cache_data, f, indent=4)

        return {
            "status": "success",
            "filename": filename,
            "file_uri": uploaded.uri,
            "mime_type": "application/pdf"
        }

upload_pdf_file = UploadPdfFileTool()


class AnalyzePdfFromUriTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="analyze_pdf_from_uri",
            description="Sends a PDF (already uploaded via upload_pdf_file) to Gemini for analysis.",
        )

    def _get_declaration(self):
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "file_uri": types.Schema(
                        type=types.Type.STRING,
                        description="Gemini Files API URI returned by upload_pdf_file.",
                    ),
                    "prompt": types.Schema(
                        type=types.Type.STRING,
                        description="Analysis instruction or question to ask about the PDF.",
                    ),
                },
                required=["file_uri", "prompt"],
            ),
        )

    async def run_async(self, *, args, tool_context):
        file_uri = args["file_uri"]
        prompt = args["prompt"]
        _tool_print("analyze_pdf_from_uri", f"Analyzing PDF at {file_uri[:60]}...")
        try:
            client = genai.Client(
                api_key=os.getenv("GOOGLE_API_KEY"),
                vertexai=False,
            )
            response = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Part.from_uri(file_uri=file_uri, mime_type="application/pdf"),
                    types.Part.from_text(text=prompt),
                ],
            )
            return response.text
        except Exception as e:
            _error_print("analyze_pdf_from_uri", f"{type(e).__name__}: {e}")
            return f"Error analyzing PDF: {type(e).__name__}: {e}"


analyze_pdf_from_uri = AnalyzePdfFromUriTool()


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
