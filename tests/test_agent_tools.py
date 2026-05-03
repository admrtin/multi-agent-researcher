from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tools.agent_tools import (
    bulk_download_arxiv_pdfs,
    create_run_output_dir,
    exit_loop,
    get_latest_planner_manifest,
    get_latest_run_dir,
    load_json_file,
    read_researcher_output,
    save_json_file,
    save_markdown_file,
    search_arxiv,
    stream_terminal_update,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_context(agent_name: str = "") -> SimpleNamespace:
    ctx = SimpleNamespace()
    ctx.agent_name = agent_name
    ctx.state = {}
    ctx.actions = SimpleNamespace(escalate=None)
    return ctx


ARXIV_XML_ONE_ENTRY = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Attention Is All You Need</title>
    <published>2017-06-12T00:00:00Z</published>
    <link title="pdf" href="http://arxiv.org/pdf/1706.03762v5"/>
    <summary>We propose a new simple network architecture, the Transformer, based solely on attention mechanisms.</summary>
  </entry>
</feed>"""

ARXIV_XML_NO_ENTRIES = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
</feed>"""


# ---------------------------------------------------------------------------
# save_json_file
# ---------------------------------------------------------------------------

class TestSaveJsonFile:
    def test_saves_dict_directly(self, tmp_path):
        dest = tmp_path / "out.json"
        result = save_json_file(dest.as_posix(), {"key": "value"})
        assert "Successfully saved" in result
        assert json.loads(dest.read_text()) == {"key": "value"}

    def test_saves_list_directly(self, tmp_path):
        dest = tmp_path / "out.json"
        save_json_file(dest.as_posix(), [1, 2, 3])
        assert json.loads(dest.read_text()) == [1, 2, 3]

    def test_saves_json_string(self, tmp_path):
        dest = tmp_path / "out.json"
        save_json_file(dest.as_posix(), '{"foo": "bar"}')
        assert json.loads(dest.read_text()) == {"foo": "bar"}

    def test_strips_markdown_json_fence(self, tmp_path):
        dest = tmp_path / "out.json"
        wrapped = '```json\n{"a": 1}\n```'
        save_json_file(dest.as_posix(), wrapped)
        assert json.loads(dest.read_text()) == {"a": 1}

    def test_strips_plain_code_fence(self, tmp_path):
        dest = tmp_path / "out.json"
        wrapped = '```\n{"a": 1}\n```'
        save_json_file(dest.as_posix(), wrapped)
        assert json.loads(dest.read_text()) == {"a": 1}

    def test_adds_json_extension(self, tmp_path):
        dest = tmp_path / "out"
        save_json_file(dest.as_posix(), {"x": 1})
        assert (tmp_path / "out.json").exists()

    def test_creates_parent_dirs(self, tmp_path):
        dest = tmp_path / "deep" / "nested" / "out.json"
        save_json_file(dest.as_posix(), {})
        assert dest.exists()

    def test_returns_error_on_invalid_json_string(self, tmp_path):
        dest = tmp_path / "bad.json"
        result = save_json_file(dest.as_posix(), "not valid json {{{{")
        assert "Error" in result


# ---------------------------------------------------------------------------
# load_json_file
# ---------------------------------------------------------------------------

class TestLoadJsonFile:
    def test_returns_raw_file_contents(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('{"hello": "world"}', encoding="utf-8")
        result = load_json_file(f.as_posix())
        assert result == '{"hello": "world"}'

    def test_returns_error_json_if_file_missing(self, tmp_path):
        result = load_json_file((tmp_path / "nope.json").as_posix())
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "not found" in parsed["message"].lower() or "File not found" in parsed["message"]


# ---------------------------------------------------------------------------
# save_markdown_file
# ---------------------------------------------------------------------------

class TestSaveMarkdownFile:
    def test_saves_content(self, tmp_path):
        dest = tmp_path / "report.md"
        result = save_markdown_file(dest.as_posix(), "# Hello\nWorld")
        assert "Successfully saved" in result
        assert dest.read_text() == "# Hello\nWorld"

    def test_adds_md_extension(self, tmp_path):
        dest = tmp_path / "report"
        save_markdown_file(dest.as_posix(), "content")
        assert (tmp_path / "report.md").exists()

    def test_creates_parent_dirs(self, tmp_path):
        dest = tmp_path / "a" / "b" / "c.md"
        save_markdown_file(dest.as_posix(), "text")
        assert dest.exists()


# ---------------------------------------------------------------------------
# read_researcher_output
# ---------------------------------------------------------------------------

class TestReadResearcherOutput:
    def test_returns_content_on_success(self, tmp_path):
        f = tmp_path / "summary.md"
        f.write_text("# Summary\nGreat paper.", encoding="utf-8")
        result = json.loads(read_researcher_output(f.as_posix()))
        assert result["status"] == "success"
        assert "Great paper." in result["content"]

    def test_returns_error_when_file_missing(self, tmp_path):
        result = json.loads(read_researcher_output((tmp_path / "missing.md").as_posix()))
        assert result["status"] == "error"
        assert "not found" in result["message"].lower() or "File not found" in result["message"]


# ---------------------------------------------------------------------------
# create_run_output_dir
# ---------------------------------------------------------------------------

class TestCreateRunOutputDir:
    def test_creates_dir_with_run_prefix(self, tmp_path):
        path = create_run_output_dir(base_dir=tmp_path.as_posix(), keep_last=3)
        assert Path(path).exists()
        assert Path(path).name.startswith("run_")

    def test_keeps_only_last_n_runs(self, tmp_path):
        for i in range(4):
            (tmp_path / f"run_2026_01_01_1000{i}").mkdir()
        create_run_output_dir(base_dir=tmp_path.as_posix(), keep_last=3)
        remaining = sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("run_"))
        assert len(remaining) == 3
        assert "run_2026_01_01_10000" not in remaining

    def test_returns_path_as_string(self, tmp_path):
        result = create_run_output_dir(base_dir=tmp_path.as_posix())
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# get_latest_run_dir
# ---------------------------------------------------------------------------

class TestGetLatestRunDir:
    def test_returns_most_recent_run(self, tmp_path):
        (tmp_path / "run_2026_01_01_120000").mkdir()
        (tmp_path / "run_2026_01_02_090000").mkdir()
        result = get_latest_run_dir(base_dir=tmp_path.as_posix())
        assert "run_2026_01_02_090000" in result

    def test_raises_when_no_runs(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            get_latest_run_dir(base_dir=tmp_path.as_posix())


# ---------------------------------------------------------------------------
# get_latest_planner_manifest
# ---------------------------------------------------------------------------

class TestGetLatestPlannerManifest:
    def test_returns_path_to_manifest(self, tmp_path):
        run = tmp_path / "run_2026_01_01_120000"
        run.mkdir()
        manifest = run / "planner_manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        result = get_latest_planner_manifest(base_dir=tmp_path.as_posix())
        assert result == manifest.as_posix()

    def test_prefers_latest_run_with_manifest(self, tmp_path):
        old = tmp_path / "run_2026_01_01_120000"
        old.mkdir()
        (old / "planner_manifest.json").write_text('{"run": "old"}', encoding="utf-8")
        new = tmp_path / "run_2026_01_02_090000"
        new.mkdir()
        (new / "planner_manifest.json").write_text('{"run": "new"}', encoding="utf-8")
        result = get_latest_planner_manifest(base_dir=tmp_path.as_posix())
        assert "run_2026_01_02_090000" in result

    def test_skips_run_dir_without_manifest(self, tmp_path):
        empty_run = tmp_path / "run_2026_01_02_090000"
        empty_run.mkdir()
        old_run = tmp_path / "run_2026_01_01_120000"
        old_run.mkdir()
        (old_run / "planner_manifest.json").write_text("{}", encoding="utf-8")
        result = get_latest_planner_manifest(base_dir=tmp_path.as_posix())
        assert "run_2026_01_01_120000" in result

    def test_raises_when_no_runs(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            get_latest_planner_manifest(base_dir=tmp_path.as_posix())

    def test_raises_when_no_manifest_in_any_run(self, tmp_path):
        (tmp_path / "run_2026_01_01_120000").mkdir()
        with pytest.raises(FileNotFoundError):
            get_latest_planner_manifest(base_dir=tmp_path.as_posix())

    def test_raises_when_base_dir_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            get_latest_planner_manifest(base_dir=(tmp_path / "nonexistent").as_posix())


# ---------------------------------------------------------------------------
# stream_terminal_update
# ---------------------------------------------------------------------------

class TestStreamTerminalUpdate:
    def test_numbered_researcher_prefix(self):
        result = stream_terminal_update("doing work", content_type="researcher", agent_name="researcher_3")
        assert result.startswith("[RESEARCHER:3]")
        assert "doing work" in result

    def test_plain_agent_prefix(self):
        result = stream_terminal_update("planning", content_type="planner", agent_name="PLANNER")
        assert result.startswith("[PLANNER]")

    def test_non_agent_type_uses_name_and_type(self):
        result = stream_terminal_update("msg", content_type="info", agent_name="SYSTEM")
        assert result.startswith("[SYSTEM:INFO]")

    def test_unknown_content_type_falls_back_to_info_color(self):
        result = stream_terminal_update("msg", content_type="unknown_type", agent_name="BOT")
        assert "msg" in result

    def test_returns_string_without_ansi_codes(self):
        result = stream_terminal_update("hello", content_type="info", agent_name="A")
        assert "\033[" not in result


# ---------------------------------------------------------------------------
# exit_loop
# ---------------------------------------------------------------------------

class TestExitLoop:
    def test_sets_loop_done_flag_for_numbered_agent(self):
        ctx = _make_tool_context("validator_2")
        result = exit_loop(ctx)
        assert ctx.state.get("loop_done_2") is True
        assert result["status"] == "loop_exited"

    def test_sets_flag_for_researcher_agent(self):
        ctx = _make_tool_context("researcher_5")
        exit_loop(ctx)
        assert ctx.state.get("loop_done_5") is True

    def test_no_flag_set_for_unnumbered_agent(self):
        ctx = _make_tool_context("validator")
        exit_loop(ctx)
        assert ctx.state == {}

    def test_return_message_contains_agent_name(self):
        ctx = _make_tool_context("validator_1")
        result = exit_loop(ctx)
        assert "validator_1" in result["message"]


# ---------------------------------------------------------------------------
# search_arxiv (mocked HTTP)
# ---------------------------------------------------------------------------

class TestSearchArxiv:
    @patch("tools.agent_tools.requests.get")
    @patch("time.sleep", return_value=None)
    def test_parses_single_entry(self, _sleep, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ARXIV_XML_ONE_ENTRY
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = json.loads(search_arxiv("transformers", max_results=1))

        assert len(result) == 1
        assert result[0]["title"] == "Attention Is All You Need"
        assert result[0]["year"] == "2017"
        assert "1706.03762" in result[0]["pdf_link"]
        assert "Transformer" in result[0]["abstract"]

    @patch("tools.agent_tools.requests.get")
    @patch("time.sleep", return_value=None)
    def test_returns_empty_list_for_no_entries(self, _sleep, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ARXIV_XML_NO_ENTRIES
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = json.loads(search_arxiv("zzznonexistent"))
        assert result == []

    @patch("tools.agent_tools.requests.get")
    @patch("time.sleep", return_value=None)
    def test_returns_error_on_network_exception(self, _sleep, mock_get):
        mock_get.side_effect = Exception("connection refused")

        result = json.loads(search_arxiv("query"))
        assert len(result) == 1
        assert "error" in result[0]

    @patch("tools.agent_tools.requests.get")
    @patch("time.sleep", return_value=None)
    def test_returns_error_on_429_after_retries(self, _sleep, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_get.return_value = mock_resp

        result = json.loads(search_arxiv("query"))
        assert any("429" in str(r) for r in result)


# ---------------------------------------------------------------------------
# bulk_download_arxiv_pdfs (mocked HTTP)
# ---------------------------------------------------------------------------

class TestBulkDownloadArxivPdfs:
    def _write_manifest(self, path: Path, researchers: list[dict]) -> Path:
        manifest_path = path / "planner_manifest.json"
        manifest_path.write_text(json.dumps({"researchers": researchers}), encoding="utf-8")
        return manifest_path

    def test_returns_error_for_missing_manifest(self, tmp_path):
        result = json.loads(bulk_download_arxiv_pdfs((tmp_path / "none.json").as_posix()))
        assert result["status"] == "error"
        assert "not found" in result["message"].lower() or "Manifest not found" in result["message"]

    def test_returns_error_when_no_researchers(self, tmp_path):
        p = self._write_manifest(tmp_path, [])
        result = json.loads(bulk_download_arxiv_pdfs(p.as_posix()))
        assert result["status"] == "error"

    def test_skips_entry_with_no_pdf_link(self, tmp_path):
        p = self._write_manifest(tmp_path, [{"id": "researcher_1", "pdf_link": ""}])
        result = json.loads(bulk_download_arxiv_pdfs(p.as_posix()))
        assert result["results"][0]["status"] == "skipped"

    @patch("tools.agent_tools.requests.get")
    @patch("time.sleep", return_value=None)
    def test_downloads_pdf_and_reports_success(self, _sleep, mock_get, tmp_path):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_content = MagicMock(return_value=[b"%PDF-1.4 fake"])
        mock_get.return_value = mock_resp

        p = self._write_manifest(
            tmp_path,
            [{"id": "researcher_1", "pdf_link": "http://arxiv.org/pdf/2401.00001v1"}],
        )
        result = json.loads(bulk_download_arxiv_pdfs(p.as_posix()))
        assert result["status"] == "complete"
        assert result["downloaded"] == 1
        assert result["failed"] == 0

    @patch("tools.agent_tools.requests.get")
    @patch("time.sleep", return_value=None)
    def test_reports_already_exists_when_pdf_present(self, _sleep, mock_get, tmp_path):
        papers_dir = tmp_path / "papers"
        papers_dir.mkdir()
        (papers_dir / "2401.00001v1.pdf").write_bytes(b"%PDF")

        p = self._write_manifest(
            tmp_path,
            [{"id": "researcher_1", "pdf_link": "http://arxiv.org/pdf/2401.00001v1"}],
        )
        result = json.loads(bulk_download_arxiv_pdfs(p.as_posix()))
        assert result["results"][0]["status"] == "already_exists"
        mock_get.assert_not_called()
