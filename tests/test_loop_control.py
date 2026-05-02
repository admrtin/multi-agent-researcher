"""
Tests for researcher/validator loop-stopping behavior and researcher→synthesizer handoff.

Root-cause summary (verified against ADK 1.27.2 source):

  LoopAgent._run_async_impl only stops when event.actions.escalate is True.
  BaseAgent.run_async calls before_agent_callback ONCE before _run_async_impl —
  not between iterations.  So the state-flag approach (loop_done_N) cannot stop
  a loop that is already running; escalate is required.

  ParallelAgent and SequentialAgent do NOT check event.actions.escalate, so
  escalating inside a LoopAgent is safe: it stops only that loop and does not
  kill siblings or parent agents.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from google.genai import types

from tools.agent_tools import exit_loop
from subagents.researcher.agent import _make_loop_callback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_context(agent_name: str = "") -> SimpleNamespace:
    """Minimal ToolContext stand-in used to call exit_loop in tests."""
    ctx = SimpleNamespace()
    ctx.agent_name = agent_name
    ctx.state = {}
    ctx.actions = SimpleNamespace(escalate=None)
    return ctx


def _make_callback_context(state: dict | None = None) -> SimpleNamespace:
    """Minimal CallbackContext stand-in used to invoke the loop callback."""
    ctx = SimpleNamespace()
    ctx.state = state or {}
    return ctx


def _write_manifest(run_dir: Path, researchers: list[dict]) -> Path:
    manifest = {"researchers": researchers}
    path = run_dir / "planner_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# exit_loop — escalation
# ---------------------------------------------------------------------------

class TestExitLoopEscalation:
    """
    Verify that exit_loop correctly signals the LoopAgent to stop.

    The LoopAgent only stops its iteration when it sees event.actions.escalate=True
    in the event stream.  Setting state["loop_done_N"] is NOT sufficient because
    before_agent_callback is only called once (before the loop starts).
    """

    def test_exit_loop_sets_escalate_on_tool_context(self):
        """
        exit_loop must set tool_context.actions.escalate = True so the LoopAgent
        actually stops iterating after the validator calls this tool.
        """
        ctx = _make_tool_context("validator_1")
        exit_loop(ctx)
        assert ctx.actions.escalate is True, (
            "exit_loop did not set tool_context.actions.escalate = True. "
            "ADK's LoopAgent only exits when event.actions.escalate is True; "
            "the state flag alone cannot stop a running loop."
        )

    def test_exit_loop_still_sets_state_flag(self):
        """The state flag is kept as a secondary guard in before_agent_callback."""
        ctx = _make_tool_context("validator_2")
        exit_loop(ctx)
        assert ctx.state.get("loop_done_2") is True

    def test_exit_loop_escalates_for_unnumbered_agent(self):
        """Escalation must fire even when the agent name has no trailing number."""
        ctx = _make_tool_context("validator")
        exit_loop(ctx)
        assert ctx.actions.escalate is True

    def test_exit_loop_returns_loop_exited_status(self):
        ctx = _make_tool_context("validator_3")
        result = exit_loop(ctx)
        assert result["status"] == "loop_exited"


# ---------------------------------------------------------------------------
# _make_loop_callback — before_agent_callback logic
# ---------------------------------------------------------------------------

class TestMakeLoopCallback:
    """
    Unit tests for the before_agent_callback returned by _make_loop_callback.

    This callback fires ONCE before the LoopAgent starts (not per-iteration),
    so it is responsible for:
      - Skipping agents whose researcher_id is not in the manifest (unassigned slots)
      - Skipping loops that already completed (loop_done_N flag set by a prior run)
      - Skipping loops where validation already passed on disk
    """

    # --- should allow the loop to run (return None) ---

    def test_returns_none_when_assigned_and_not_done(self, tmp_path):
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir(parents=True)
        manifest_path = _write_manifest(run_dir, [{"id": "researcher_1"}])

        with patch("subagents.researcher.agent.get_latest_planner_manifest",
                   return_value=manifest_path.as_posix()):
            callback = _make_loop_callback("researcher_1", 1)
            result = callback(_make_callback_context())

        assert result is None, "Loop should run: researcher_1 is assigned and not done"

    # --- should stop the loop (return Content) ---

    def test_returns_content_when_loop_done_flag_is_set(self, tmp_path):
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir(parents=True)
        manifest_path = _write_manifest(run_dir, [{"id": "researcher_1"}])

        state = {"loop_done_1": True}
        with patch("subagents.researcher.agent.get_latest_planner_manifest",
                   return_value=manifest_path.as_posix()):
            callback = _make_loop_callback("researcher_1", 1)
            result = callback(_make_callback_context(state))

        assert result is not None, "Loop should stop: loop_done_1 flag is set"
        assert isinstance(result, types.Content)

    def test_returns_content_when_researcher_not_in_manifest(self, tmp_path):
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir(parents=True)
        # manifest lists researcher_2, not researcher_1
        manifest_path = _write_manifest(run_dir, [{"id": "researcher_2"}])

        with patch("subagents.researcher.agent.get_latest_planner_manifest",
                   return_value=manifest_path.as_posix()):
            callback = _make_loop_callback("researcher_1", 1)
            result = callback(_make_callback_context())

        assert result is not None, "Loop should skip: researcher_1 is not assigned"

    def test_returns_content_when_validation_already_passed(self, tmp_path):
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir(parents=True)
        manifest_path = _write_manifest(run_dir, [{"id": "researcher_1"}])

        val_dir = run_dir / "researchers" / "researcher_1" / "validator"
        val_dir.mkdir(parents=True)
        (val_dir / "validation_summary.md").write_text("Validation passed.", encoding="utf-8")

        with patch("subagents.researcher.agent.get_latest_planner_manifest",
                   return_value=manifest_path.as_posix()):
            callback = _make_loop_callback("researcher_1", 1)
            result = callback(_make_callback_context())

        assert result is not None, "Loop should stop: validation already passed on disk"

    def test_returns_content_when_no_manifest_found(self):
        with patch("subagents.researcher.agent.get_latest_planner_manifest",
                   side_effect=FileNotFoundError("no manifest")):
            callback = _make_loop_callback("researcher_1", 1)
            result = callback(_make_callback_context())

        assert result is not None, "Loop should skip: no manifest found"

    def test_does_not_stop_when_validation_summary_says_failed(self, tmp_path):
        """A failed validation summary should NOT stop the loop — retry is needed."""
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir(parents=True)
        manifest_path = _write_manifest(run_dir, [{"id": "researcher_1"}])

        val_dir = run_dir / "researchers" / "researcher_1" / "validator"
        val_dir.mkdir(parents=True)
        (val_dir / "validation_summary.md").write_text(
            "Validation failed. Missing citations.", encoding="utf-8"
        )

        with patch("subagents.researcher.agent.get_latest_planner_manifest",
                   return_value=manifest_path.as_posix()):
            callback = _make_loop_callback("researcher_1", 1)
            result = callback(_make_callback_context())

        assert result is None, "Loop should continue: validation failed, retry needed"

    def test_index_isolation_between_researchers(self, tmp_path):
        """loop_done_1 set for researcher_1 must not stop researcher_2's loop."""
        run_dir = tmp_path / "run_2026_01_01_120000"
        run_dir.mkdir(parents=True)
        manifest_path = _write_manifest(
            run_dir, [{"id": "researcher_1"}, {"id": "researcher_2"}]
        )

        # Only researcher_1 is done
        state = {"loop_done_1": True}
        with patch("subagents.researcher.agent.get_latest_planner_manifest",
                   return_value=manifest_path.as_posix()):
            callback_2 = _make_loop_callback("researcher_2", 2)
            result = callback_2(_make_callback_context(state))

        assert result is None, "researcher_2's loop should not be affected by loop_done_1"


# ---------------------------------------------------------------------------
# Researcher → Synthesizer handoff
# ---------------------------------------------------------------------------

class TestResearcherSynthesizerHandoff:
    """
    Verify that once researchers finish writing their summaries, those summaries
    are discoverable and readable by the synthesizer.

    The synthesizer uses get_latest_run_dir + read_researcher_output to collect
    all paper reviews.  These tests confirm the file-system contract is met after
    researchers complete.
    """

    from tools.agent_tools import get_latest_run_dir, read_researcher_output

    def _setup_run(self, base: Path, researcher_ids: list[str]) -> Path:
        """Create a run directory with summary.md for each researcher."""
        run_dir = base / "run_2026_01_01_120000"
        run_dir.mkdir(parents=True)
        for rid in researcher_ids:
            summary_path = run_dir / "researchers" / rid / "summary.md"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(f"# Summary for {rid}\nContent here.", encoding="utf-8")
        return run_dir

    def test_synthesizer_can_read_all_completed_summaries(self, tmp_path):
        from tools.agent_tools import get_latest_run_dir, read_researcher_output

        ids = ["researcher_1", "researcher_2", "researcher_3"]
        run_dir = self._setup_run(tmp_path, ids)

        latest = get_latest_run_dir(base_dir=tmp_path.as_posix())
        assert latest == run_dir.as_posix()

        for rid in ids:
            summary_path = Path(latest) / "researchers" / rid / "summary.md"
            result = json.loads(read_researcher_output(summary_path.as_posix()))
            assert result["status"] == "success"
            assert rid in result["content"]

    def test_synthesizer_gets_error_for_missing_summary(self, tmp_path):
        from tools.agent_tools import read_researcher_output

        missing = tmp_path / "run_x" / "researchers" / "researcher_5" / "summary.md"
        result = json.loads(read_researcher_output(missing.as_posix()))
        assert result["status"] == "error"

    def test_synthesis_proceeds_with_partial_completions(self, tmp_path):
        """Synthesizer should read available summaries even if some researchers failed."""
        from tools.agent_tools import get_latest_run_dir, read_researcher_output

        run_dir = self._setup_run(tmp_path, ["researcher_1", "researcher_2"])
        # researcher_3 never wrote a summary

        latest = get_latest_run_dir(base_dir=tmp_path.as_posix())
        results = {}
        for i in range(1, 4):
            rid = f"researcher_{i}"
            path = Path(latest) / "researchers" / rid / "summary.md"
            results[rid] = json.loads(read_researcher_output(path.as_posix()))

        assert results["researcher_1"]["status"] == "success"
        assert results["researcher_2"]["status"] == "success"
        assert results["researcher_3"]["status"] == "error"  # graceful — no crash

    def test_synthesizer_sees_latest_run_not_stale_run(self, tmp_path):
        from tools.agent_tools import get_latest_run_dir

        (tmp_path / "run_2026_01_01_090000").mkdir()
        (tmp_path / "run_2026_01_01_120000").mkdir()
        (tmp_path / "run_2026_01_01_150000").mkdir()

        latest = get_latest_run_dir(base_dir=tmp_path.as_posix())
        assert "run_2026_01_01_150000" in latest

    def test_validation_pass_file_is_readable_before_synthesis(self, tmp_path):
        """Synthesizer should be able to confirm which researchers passed validation."""
        from tools.agent_tools import read_researcher_output

        run_dir = tmp_path / "run_2026_01_01_120000"
        val_dir = run_dir / "researchers" / "researcher_1" / "validator"
        val_dir.mkdir(parents=True)
        (val_dir / "validation_summary.md").write_text("Validation passed.", encoding="utf-8")

        result = json.loads(
            read_researcher_output(
                (val_dir / "validation_summary.md").as_posix()
            )
        )
        assert result["status"] == "success"
        assert "Validation passed" in result["content"]
