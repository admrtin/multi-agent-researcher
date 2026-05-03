"""
Tests for the Planner → Research Pipeline handoff.

The approval flow spans two conversation turns:
  Turn 1: Planner searches, creates run dir, presents papers, STOPS
  Turn 2: User says "approved" → Root re-routes to Planner → Planner runs
          Phase 3 (save tasking + manifest) then Phase 4 (download + RESEARCH_PIPELINE)

Failure modes under test:
  - Manifest JSON does not match the structure researchers expect
  - Tasking file paths are wrong (wrong run folder)
  - Researchers cannot find their manifest after Phase 3
  - Research pipeline gets wrong manifest when run dirs pile up
  - Planner calls create_run_output_dir a second time (Phase 3 turn), creating
    a new empty dir — tests that get_latest_run_dir still resolves to the
    correct populated dir
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.agent_tools import (
    get_latest_planner_manifest,
    get_latest_run_dir,
    read_researcher_output,
    save_json_file,
    save_markdown_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_PAPERS = [
    {
        "id": "researcher_1",
        "title": "Symplectic Adjoint Method for Exact Gradient of Neural ODE",
        "year": "2021",
        "pdf_link": "http://arxiv.org/pdf/2111.02118v1",
        "abstract": "A neural network model of a differential equation...",
        "summary": "summary.md",
    },
    {
        "id": "researcher_2",
        "title": "Adaptive Checkpoint Adjoint Method for Gradient Estimation",
        "year": "2020",
        "pdf_link": "http://arxiv.org/pdf/2006.02493v1",
        "abstract": "Neural ordinary differential equations (NODEs)...",
        "summary": "summary.md",
    },
    {
        "id": "researcher_3",
        "title": "Evolutionary algorithms as an alternative to backpropagation",
        "year": "2023",
        "pdf_link": "http://arxiv.org/pdf/2301.00000v1",
        "abstract": "Training networks consisting of biophysically accurate...",
        "summary": "summary.md",
    },
]


def _write_manifest(run_dir: Path, papers: list[dict] | None = None) -> Path:
    """Write a planner_manifest.json in `run_dir` and return its path."""
    manifest = {
        "timestamp": "2026-01-01_120000",
        "planner_topic": "Efficient backpropagation for Neural ODEs",
        "researchers": papers if papers is not None else SAMPLE_PAPERS,
    }
    manifest_path = run_dir / "planner_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def _write_tasking(run_dir: Path, paper: dict) -> Path:
    """Write a tasking.md for one paper and return its path."""
    rid = paper["id"]
    tasking_dir = run_dir / "researchers" / rid
    tasking_dir.mkdir(parents=True, exist_ok=True)
    content = (
        f"# Tasking: {paper['title']}\n\n"
        f"## Research Topic\nEfficient backpropagation for Neural ODEs\n\n"
        f"## Paper Metadata\n"
        f"- **Title**: {paper['title']}\n"
        f"- **Year**: {paper['year']}\n"
        f"- **PDF Link**: {paper['pdf_link']}\n\n"
        f"## Abstract\n{paper['abstract']}\n\n"
        f"## Instructions\n"
        f"Download the paper using the PDF link above, read it, and produce a detailed summary.\n"
    )
    path = tasking_dir / "tasking.md"
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Manifest structure
# ---------------------------------------------------------------------------

class TestManifestStructure:
    """
    The manifest must contain all fields the researcher reads at runtime.
    A missing key here means researchers silently get no assignment.
    """

    def test_manifest_has_required_top_level_fields(self, tmp_path):
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir()
        manifest_path = _write_manifest(run_dir)

        manifest = json.loads(manifest_path.read_text())
        assert "timestamp" in manifest
        assert "planner_topic" in manifest
        assert "researchers" in manifest

    def test_each_researcher_entry_has_required_fields(self, tmp_path):
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir()
        manifest_path = _write_manifest(run_dir)

        manifest = json.loads(manifest_path.read_text())
        for entry in manifest["researchers"]:
            assert "id" in entry, f"Missing 'id' in {entry}"
            assert "title" in entry
            assert "year" in entry
            assert "pdf_link" in entry
            assert "abstract" in entry

    def test_researcher_ids_are_sequential(self, tmp_path):
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir()
        manifest_path = _write_manifest(run_dir)

        manifest = json.loads(manifest_path.read_text())
        ids = [r["id"] for r in manifest["researchers"]]
        expected = [f"researcher_{i}" for i in range(1, len(ids) + 1)]
        assert ids == expected, f"IDs {ids} are not sequential {expected}"

    def test_pdf_links_are_non_empty(self, tmp_path):
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir()
        manifest_path = _write_manifest(run_dir)

        manifest = json.loads(manifest_path.read_text())
        for entry in manifest["researchers"]:
            assert entry["pdf_link"], f"Empty pdf_link for {entry['id']}"

    def test_save_json_file_roundtrip_preserves_manifest(self, tmp_path):
        """save_json_file must not corrupt the manifest on write."""
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir()
        manifest = {
            "timestamp": "2026-01-01_120000",
            "planner_topic": "Neural ODEs",
            "researchers": SAMPLE_PAPERS,
        }
        dest = run_dir / "planner_manifest.json"
        save_json_file(dest.as_posix(), manifest)

        loaded = json.loads(dest.read_text())
        assert loaded["researchers"] == SAMPLE_PAPERS
        assert loaded["planner_topic"] == "Neural ODEs"


# ---------------------------------------------------------------------------
# Phase 3 file creation
# ---------------------------------------------------------------------------

class TestPhase3FileCreation:
    """
    Verify that the files Phase 3 is supposed to create are written correctly
    and in the right locations.
    """

    def test_tasking_file_contains_paper_metadata(self, tmp_path):
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir()
        paper = SAMPLE_PAPERS[0]
        path = _write_tasking(run_dir, paper)

        content = path.read_text()
        assert paper["title"] in content
        assert paper["year"] in content
        assert paper["pdf_link"] in content
        assert paper["abstract"] in content

    def test_tasking_files_created_for_all_papers(self, tmp_path):
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir()
        for paper in SAMPLE_PAPERS:
            _write_tasking(run_dir, paper)

        for paper in SAMPLE_PAPERS:
            expected = run_dir / "researchers" / paper["id"] / "tasking.md"
            assert expected.exists(), f"Missing tasking for {paper['id']}"

    def test_save_markdown_file_creates_tasking(self, tmp_path):
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir()
        paper = SAMPLE_PAPERS[0]
        dest = run_dir / "researchers" / paper["id"] / "tasking.md"

        result = save_markdown_file(dest.as_posix(), f"# Tasking: {paper['title']}")
        assert "Successfully saved" in result
        assert dest.exists()

    def test_manifest_saved_alongside_tasking_files(self, tmp_path):
        """Manifest and tasking files must share the same run folder root."""
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir()
        manifest_path = _write_manifest(run_dir)
        for paper in SAMPLE_PAPERS:
            _write_tasking(run_dir, paper)

        assert manifest_path.parent == run_dir
        for paper in SAMPLE_PAPERS:
            tasking = run_dir / "researchers" / paper["id"] / "tasking.md"
            assert tasking.parent.parent.parent == run_dir


# ---------------------------------------------------------------------------
# get_latest_planner_manifest — cross-turn recovery
# ---------------------------------------------------------------------------

class TestCrossTurnManifestRecovery:
    """
    Phase 3 runs in a new conversation turn and must recover the run folder.
    get_latest_planner_manifest is the recovery mechanism.

    If the Planner calls create_run_output_dir a second time (without writing
    a manifest first), get_latest_planner_manifest must still return the
    manifest from the FIRST run, not the empty second one.
    """

    def test_finds_manifest_after_phase_3(self, tmp_path):
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir()
        _write_manifest(run_dir)

        result = get_latest_planner_manifest(base_dir=tmp_path.as_posix())
        assert result == (run_dir / "planner_manifest.json").as_posix()

    def test_skips_empty_run_dir_created_in_second_turn(self, tmp_path):
        """
        Scenario: Planner creates run_A in turn 1, saves manifest there.
        In turn 2, Planner mistakenly calls create_run_output_dir again,
        creating run_B (empty).  get_latest_planner_manifest must still
        return run_A's manifest, not fail with 'no manifest found'.
        """
        run_a = tmp_path / "run_2026_01_01_120000"
        run_a.mkdir()
        _write_manifest(run_a)

        # Simulate a second create_run_output_dir call (empty dir, no manifest)
        run_b = tmp_path / "run_2026_01_01_130000"
        run_b.mkdir()

        result = get_latest_planner_manifest(base_dir=tmp_path.as_posix())
        assert "run_2026_01_01_120000" in result, (
            "get_latest_planner_manifest should fall back to the most recent "
            "run that CONTAINS a manifest, not the empty newer run."
        )

    def test_manifest_readable_via_load_json(self, tmp_path):
        from tools.agent_tools import load_json_file

        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir()
        _write_manifest(run_dir)

        manifest_path = get_latest_planner_manifest(base_dir=tmp_path.as_posix())
        raw = load_json_file(manifest_path)
        parsed = json.loads(raw)
        assert "researchers" in parsed


# ---------------------------------------------------------------------------
# Researcher assignment lookup
# ---------------------------------------------------------------------------

class TestResearcherAssignmentLookup:
    """
    Researchers read the manifest to find their assignment.
    The manifest structure must let a researcher correctly determine:
    - Was it assigned? (id in researchers list)
    - What paper should it read? (pdf_link)
    - Where is the PDF? (derived from pdf_link + run folder)
    """

    def test_researcher_finds_its_own_entry(self, tmp_path):
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir()
        manifest_path = _write_manifest(run_dir)

        manifest = json.loads(manifest_path.read_text())
        assigned_ids = {r["id"] for r in manifest["researchers"]}

        assert "researcher_1" in assigned_ids
        assert "researcher_2" in assigned_ids
        assert "researcher_3" in assigned_ids

    def test_unassigned_researcher_not_in_manifest(self, tmp_path):
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir()
        # Only 2 papers approved
        manifest_path = _write_manifest(run_dir, papers=SAMPLE_PAPERS[:2])

        manifest = json.loads(manifest_path.read_text())
        assigned_ids = {r["id"] for r in manifest["researchers"]}

        assert "researcher_1" in assigned_ids
        assert "researcher_2" in assigned_ids
        assert "researcher_3" not in assigned_ids

    def test_pdf_path_derivable_from_manifest(self, tmp_path):
        """
        Researchers derive the local PDF path from pdf_link.
        arxiv.org/pdf/2111.02118v1 → papers/2111.02118v1.pdf
        """
        import re

        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir()
        manifest_path = _write_manifest(run_dir)

        manifest = json.loads(manifest_path.read_text())
        for entry in manifest["researchers"]:
            pdf_link = entry["pdf_link"]
            url_tail = pdf_link.rstrip("/").split("/")[-1]
            sanitized = re.sub(r"\.pdf$", "", url_tail, flags=re.IGNORECASE)
            sanitized = re.sub(r"[^\w.\-]", "_", sanitized)
            expected_filename = f"{sanitized}.pdf"
            assert expected_filename.endswith(".pdf")
            assert len(expected_filename) > 4

    def test_tasking_file_readable_by_researcher(self, tmp_path):
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir()
        paper = SAMPLE_PAPERS[0]
        _write_tasking(run_dir, paper)

        tasking_path = run_dir / "researchers" / paper["id"] / "tasking.md"
        result = json.loads(read_researcher_output(tasking_path.as_posix()))
        assert result["status"] == "success"
        assert paper["title"] in result["content"]
        assert paper["pdf_link"] in result["content"]


# ---------------------------------------------------------------------------
# Root prompt routing assertions
# ---------------------------------------------------------------------------

class TestRootPromptRouting:
    """
    Verify that root_agent_prompt.md contains the instructions needed to
    re-route 'approved' back to the Planner.  These tests catch accidental
    deletion or weakening of the routing rules.
    """

    PROMPT_PATH = Path("root_agent_prompt.md")

    def _load_prompt(self) -> str:
        return self.PROMPT_PATH.read_text(encoding="utf-8")

    def test_prompt_classifies_paper_approval(self):
        prompt = self._load_prompt()
        assert "Paper Approval" in prompt, (
            "root_agent_prompt.md must contain the 'Paper Approval' routing category"
        )

    def test_prompt_mentions_approved_keyword(self):
        prompt = self._load_prompt()
        assert "approved" in prompt.lower(), (
            "root_agent_prompt.md must mention 'approved' in the routing rules "
            "so the LLM knows to classify it as Paper Approval"
        )

    def test_prompt_routes_approval_to_planner(self):
        prompt = self._load_prompt()
        assert "Planner" in prompt or "PLANNER" in prompt
        # Check that approval is followed by re-route to planner
        lines = prompt.lower().splitlines()
        approval_lines = [l for l in lines if "paper approval" in l or "approved" in l]
        assert any("planner" in l for l in approval_lines), (
            "The Paper Approval routing rule must mention the Planner Agent"
        )

    def test_prompt_has_passing_your_response_sentence(self):
        """The exact sentence Root is supposed to say before re-routing."""
        prompt = self._load_prompt()
        assert "Passing your response to the Planner" in prompt, (
            "root_agent_prompt.md should instruct Root to say "
            "'Passing your response to the Planner to continue the pipeline.' "
            "before re-routing so the user sees feedback"
        )


# ---------------------------------------------------------------------------
# Planner prompt tool availability
# ---------------------------------------------------------------------------

class TestPlannerPromptToolAvailability:
    """
    The Planner prompt must reference all tools required by the Phase 3/4
    workflow so the LLM knows to use them.  If a tool is called in the
    workflow instructions but never mentioned anywhere in the prompt, the
    LLM may silently skip it.
    """

    PROMPT_PATH = Path("subagents/planner/planner_agent_prompt.md")

    def _load_prompt(self) -> str:
        return self.PROMPT_PATH.read_text(encoding="utf-8")

    def test_prompt_mentions_create_run_output_dir(self):
        prompt = self._load_prompt()
        assert "create_run_output_dir" in prompt

    def test_prompt_mentions_save_json_file(self):
        prompt = self._load_prompt()
        assert "save_json_file" in prompt

    def test_prompt_mentions_save_markdown_file(self):
        prompt = self._load_prompt()
        assert "save_markdown_file" in prompt

    def test_prompt_mentions_bulk_download(self):
        prompt = self._load_prompt()
        assert "bulk_download_arxiv_pdfs" in prompt

    def test_prompt_mentions_research_pipeline_tool(self):
        prompt = self._load_prompt()
        assert "RESEARCH_PIPELINE" in prompt

    def test_available_tools_section_lists_all_tools(self):
        """
        The 'Available tools' section at the top of the prompt should list
        every tool the Planner needs, not just stream_terminal_update.
        A missing tool here means the LLM may not invoke it in Phase 3/4.
        """
        prompt = self._load_prompt()
        available_section_start = prompt.find("## Available tools")
        available_section_end = prompt.find("\n##", available_section_start + 1)
        available_section = prompt[available_section_start:available_section_end]

        required_tools = [
            "create_run_output_dir",
            "get_latest_run_dir",
            "search_arxiv",
            "save_json_file",
            "save_markdown_file",
            "bulk_download_arxiv_pdfs",
            "RESEARCH_PIPELINE",
        ]
        missing = [t for t in required_tools if t not in available_section]
        assert not missing, (
            f"The 'Available tools' section in planner_agent_prompt.md is missing: "
            f"{missing}. The LLM only reliably calls tools that appear in this section."
        )
