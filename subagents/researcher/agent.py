from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from google.adk.agents import Agent, ParallelAgent, LoopAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.genai import types
from dotenv import load_dotenv

from subagents.validator.agent import prompt as validator_prompt
from tools.agent_tools import (
    save_markdown_file,
    save_json_file,
    download_arxiv_pdf,
    load_json_file,
    gemini_models,
    get_latest_planner_manifest,
    read_researcher_output,
    exit_loop,
)

load_dotenv()

prompt = Path("./subagents/researcher/researcher_agent_prompt.md").read_text()
agent_name = "RESEARCHER"

# Pool size matches SEED_PAPER_COUNT. If the user removes papers during
# approval, unassigned slots are skipped via before_agent_callback.
MAX_RESEARCHER_POOL = int(os.getenv("SEED_PAPER_COUNT", "10"))


def _make_skip_callback(researcher_id: str):
    """
    Returns a before_agent_callback that reads the planner manifest at
    *runtime* (not at import time) and skips this LoopAgent pair entirely
    if researcher_id is not listed in the manifest.

    This prevents unassigned agents from wasting API calls when the planner
    assigns fewer researchers than MAX_RESEARCHER_POOL.
    """
    def _callback(callback_context: CallbackContext) -> Optional[types.Content]:
        # Locate the latest manifest at invocation time.
        try:
            manifest_path = get_latest_planner_manifest(base_dir="outputs")
        except FileNotFoundError:
            # No manifest yet — skip this agent to be safe.
            return types.Content(
                role="model",
                parts=[types.Part(text=f"No manifest found, skipping {researcher_id}.")],
            )

        try:
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        except Exception as exc:
            return types.Content(
                role="model",
                parts=[types.Part(text=f"Could not read manifest ({exc}), skipping {researcher_id}.")],
            )

        assigned_ids = {r["id"] for r in manifest.get("researchers", [])}
        if researcher_id not in assigned_ids:
            # Return a Content object to skip this agent entirely.
            return types.Content(
                role="model",
                parts=[types.Part(text=f"No task assigned for {researcher_id}.")],
            )

        # Return None to let the agent run normally.
        return None

    return _callback


# ─── Build the researcher+validator pool ───────────────────────────────
# NOTE: The manifest_path is NOT baked into agent instructions at import time.
# The manifest is created by the Planner Agent AFTER this module is loaded.
# Each researcher resolves the manifest path at runtime via the
# `get_latest_planner_manifest` tool, guaranteeing it always uses the
# freshest manifest regardless of when the module was first imported.

sub_agents = []

for i in range(1, MAX_RESEARCHER_POOL + 1):
    researcher_id = f"researcher_{i}"

    researcher = Agent(
        name=f"RESEARCHER_{i}",
        model=gemini_models.RESEARCHER,
        instruction=(
            f"Your <YOUR_ID> is {researcher_id}.\n"
            f"Use the `get_latest_planner_manifest` tool to locate the current manifest.\n\n"
            + prompt
        ),
        tools=[
            download_arxiv_pdf,
            save_markdown_file,
            load_json_file,
            get_latest_planner_manifest,
            read_researcher_output,
            exit_loop,
        ],
    )

    validator = Agent(
        name=f"VALIDATOR_{i}",
        model=gemini_models.VALIDATOR,
        instruction=(
            f"You are validating {researcher_id}.\n"
            f"Use the `get_latest_planner_manifest` tool to locate the current manifest if needed.\n\n"
            + validator_prompt
        ),
        tools=[save_markdown_file, save_json_file, get_latest_planner_manifest, read_researcher_output, exit_loop],
    )

    pair = LoopAgent(
        name=f"RESEARCH_AND_VALIDATE_{i}",
        sub_agents=[researcher, validator],
        max_iterations=3,
        before_agent_callback=_make_skip_callback(researcher_id),
    )
    sub_agents.append(pair)

# ─── Chunk into parallel groups ────────────────────────────────────────
# Keep chunk size small to avoid hitting Gemini API rate limits
# (1M input tokens/minute on the free/paid tier).
CHUNK_SIZE = 2
chunked_agents = []
for i in range(0, len(sub_agents), CHUNK_SIZE):
    chunk = sub_agents[i:i + CHUNK_SIZE]
    chunk_agent = ParallelAgent(
        name=f"RESEARCHER_CHUNK_{i // CHUNK_SIZE + 1}",
        sub_agents=chunk,
    )
    chunked_agents.append(chunk_agent)

# ─── Export the top-level researcher agent ─────────────────────────────
# SequentialAgent is a workflow-only orchestrator: no model, no instruction,
# no tools.  It just runs the chunks in order.
researcher_agent = SequentialAgent(
    name=agent_name,
    sub_agents=chunked_agents,
    description="Orchestrates parallel paper research and validation.",
)