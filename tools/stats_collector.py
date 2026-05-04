"""
Pipeline statistics collector: per-agent token usage and end-to-end timing.

Usage pattern:
  - call record_tokens(agent_name, usage_metadata) from after_model_callback on each agent
  - call mark_pipeline_start() from before_agent_callback on planner
  - call mark_pipeline_end() + write_stats(run_dir) from after_agent_callback on synthesizer
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse

_lock = threading.Lock()

_token_totals: dict[str, dict[str, int]] = defaultdict(
    lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0}
)
_pipeline_start: Optional[float] = None
_pipeline_end: Optional[float] = None


def mark_pipeline_start() -> None:
    global _pipeline_start
    with _lock:
        if _pipeline_start is None:
            _pipeline_start = time.time()


def mark_pipeline_end() -> None:
    global _pipeline_end
    with _lock:
        _pipeline_end = time.time()


def record_tokens(agent_name: str, usage_metadata) -> None:
    if usage_metadata is None:
        return
    prompt_tokens = getattr(usage_metadata, "prompt_token_count", 0) or 0
    candidate_tokens = getattr(usage_metadata, "candidates_token_count", 0) or 0
    total_tokens = getattr(usage_metadata, "total_token_count", 0) or (
        prompt_tokens + candidate_tokens
    )
    with _lock:
        rec = _token_totals[agent_name]
        rec["input_tokens"] += prompt_tokens
        rec["output_tokens"] += candidate_tokens
        rec["total_tokens"] += total_tokens
        rec["calls"] += 1


def get_stats() -> dict:
    with _lock:
        elapsed = None
        if _pipeline_start is not None and _pipeline_end is not None:
            elapsed = round(_pipeline_end - _pipeline_start, 2)
        per_agent = {}
        for name, rec in _token_totals.items():
            calls = rec["calls"] or 1
            per_agent[name] = {
                "total_calls": rec["calls"],
                "avg_input_tokens": round(rec["input_tokens"] / calls),
                "avg_output_tokens": round(rec["output_tokens"] / calls),
                "avg_total_tokens": round(rec["total_tokens"] / calls),
                "cumulative_input_tokens": rec["input_tokens"],
                "cumulative_output_tokens": rec["output_tokens"],
                "cumulative_total_tokens": rec["total_tokens"],
            }
        return {
            "pipeline_elapsed_seconds": elapsed,
            "agents": per_agent,
        }


def write_stats(run_dir: str | Path) -> None:
    stats = get_stats()
    path = Path(run_dir) / "pipeline_stats.json"
    path.write_text(json.dumps(stats, indent=2))
    print(f"[STATS] Written to {path}")
    _print_summary(stats)


def _print_summary(stats: dict) -> None:
    elapsed = stats.get("pipeline_elapsed_seconds")
    elapsed_str = f"{elapsed}s" if elapsed is not None else "N/A"
    print(f"\n[STATS] Pipeline duration: {elapsed_str}")
    print(f"[STATS] {'Agent':<20} {'Calls':>6}  {'Avg Input':>10}  {'Avg Output':>11}  {'Avg Total':>10}")
    print(f"[STATS] {'-'*20}  {'-'*6}  {'-'*10}  {'-'*11}  {'-'*10}")
    for name, a in stats["agents"].items():
        print(
            f"[STATS] {name:<20} {a['total_calls']:>6}  "
            f"{a['avg_input_tokens']:>10,}  {a['avg_output_tokens']:>11,}  "
            f"{a['avg_total_tokens']:>10,}"
        )


# --- ADK callback helpers ---

def make_token_callback(agent_name: str):
    """Returns an after_model_callback that records token usage for agent_name."""
    def _cb(callback_context: CallbackContext, llm_response: LlmResponse) -> Optional[LlmResponse]:
        record_tokens(agent_name, llm_response.usage_metadata)
        return None
    _cb.__name__ = f"_token_cb_{agent_name}"
    return _cb


def pipeline_start_callback(callback_context: CallbackContext):
    """before_agent_callback: marks pipeline start time."""
    mark_pipeline_start()
    return None


def pipeline_end_callback(callback_context: CallbackContext):
    """after_agent_callback: marks pipeline end and writes stats."""
    mark_pipeline_end()
    try:
        from tools.agent_tools import get_latest_run_dir
        run_dir = get_latest_run_dir()
    except Exception:
        run_dir = None
    if run_dir:
        write_stats(run_dir)
    else:
        _print_summary(get_stats())
    return None
