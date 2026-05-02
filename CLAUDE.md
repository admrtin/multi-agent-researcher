# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then edit .env
```

**Auth (Vertex AI, recommended):**
```bash
gcloud auth application-default login
gcloud config set project <your-project-id>
gcloud services enable aiplatform.googleapis.com
```

Required `.env` for Vertex AI: `GOOGLE_GENAI_USE_VERTEXAI=true`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`. Alternatively set `GOOGLE_API_KEY` for direct API key mode.

## Running

```bash
# Must be run from multi_agent_researcher/ directory
adk run .
```

No test runner is currently configured (`tests/` is empty).

## Architecture

This is a **Google ADK multi-agent system** where all agents are defined using `google.adk.agents.Agent` and all tools are plain Python functions (or `BaseTool` subclasses) registered via the `tools=` list.

### Agent hierarchy

```
Root (agent.py)
  └── Planner (subagents/planner/agent.py)
        ├── Researcher (subagents/researcher/agent.py)  ← spawned as AgentTool
        └── Synthesizer (subagents/synthesizer/agent.py) ← spawned as AgentTool
```

- **Root** — intake coordinator; routes planning requests to Planner, or paper-analysis requests directly to Researcher; loads `planner_manifest.json` for continuation flows.
- **Planner** — searches arXiv → Semantic Scholar → OpenAlex for seed papers; generates `planner_manifest.json` and a planning overview markdown; spawns Researcher sub-agents for each paper then invokes Synthesizer.
- **Researcher** — analyzes one paper; tries arXiv PDF download first, falls back to web search; writes `paper_review.md` + `paper_review.json` and registers output in `shared_state.json`.
- **Synthesizer** — reads all registered researcher outputs from `shared_state.json`; writes `final_literature_review.md` + `synthesis_summary.json`; runs a validation pass.
- **Validator** (`subagents/validator/`) — defined as a standalone agent but **not wired as a sub-agent** in any `sub_agents=` list. Validation is instead performed deterministically by calling `validate_researcher_artifacts()` / `validate_synthesis_artifacts()` directly as tools inside Researcher and Synthesizer.

### All tools live in `tools/agent_tools.py`

This single file contains every tool function shared across all agents. Notable internals:

- **`GeminiModel` dataclass** — at import time, probes the configured Vertex AI project to resolve which Gemini model variant is actually available (`gemini_models.ROOT`, `.PLANNER`, etc.). This fires real API calls on startup.
- **`execute_planner_pipeline()`** — large deterministic function that bypasses prompt-only orchestration; handles the full planner flow (search → aspect assignment → manifest creation → shared-state initialization → pre-registration of assignments).
- **`build_synthesis_artifacts()`** — similarly deterministic; constructs the final synthesis from registered researcher outputs without needing further model calls.
- **`_discover_and_download_paper_assets()`** — arXiv-first discovery; falls back to DuckDuckGo web search for PDF links.
- **Output identity functions** (`build_planner_output_identity`, `build_researcher_output_identity`, `build_synthesis_output_identity`) — produce stable slugs + SHA-1 digests used in folder and file names.

### Inter-agent communication

Agents share state through JSON files on disk:

- `outputs/shared_runs/run_.../shared_state.json` — central registry tracking planner assignments, researcher completions, validator decisions, and synthesizer outputs.
- `outputs/planner_outputs/run_.../planner_manifest.json` — planner → researcher handoff.
- `outputs/researcher_outputs/run_.../paper_review.json` — researcher → synthesizer handoff.

Run folders use `run_<identity>_<timestamp>` naming. Retention limits: 3 planner/shared runs, 50 researcher runs, 20 synthesizer runs (high limits prevent parallel researchers from deleting each other's outputs).

### Prompts

Each agent reads its system prompt from a `.md` file at init time (e.g., `root_agent_prompt.md`, `subagents/planner/planner_agent_prompt.md`). Editing the `.md` file changes agent behavior without touching Python.

### Adding a new tool

1. Add the function to `tools/agent_tools.py`.
2. Import it in the relevant `subagents/<name>/agent.py` and add it to the agent's `tools=` list.
