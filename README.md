# CSCI 576 Multi-Agent Researcher — Group 6

A multi-agent literature research assistant built with Google ADK. Given a research topic, it searches ArXiv, presents papers for approval, runs parallel paper analysis, validates each summary, and produces a final synthesized literature review.

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .\.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then fill in your keys
```

### Required `.env` keys

| Variable | Required | Notes |
|---|---|---|
| `GOOGLE_API_KEY` | Yes | Gemini API access |
| `SEED_PAPER_COUNT` | No | Number of papers to research (default: 3) |
| `SEMANTIC_SCHOLAR_API_KEY` | No | Reduces throttling on paper lookups |

---

## Running

### TUI Dashboard (recommended)

```bash
cd multi_agent_researcher
python dashboard.py
```

Launches a Textual TUI with:
- **Left panel** — live per-agent status (Planner, Researchers, Validators, Synthesizer)
- **Right panel** — scrollable activity log with full tool-level output
- **Input bar** — multi-turn conversation with the agent pipeline
- `Ctrl+L` to clear the log, `Ctrl+C` to quit

### Plain CLI (original)

```bash
cd multi_agent_researcher
adk run .
```

---

## Workflow

1. **Enter a research topic** — Root refines it and asks for a green light
2. **Green light** — Planner searches ArXiv and presents papers
3. **Approve papers** — type `approved` or remove papers by number
4. **Pipeline runs automatically** — researchers analyze each paper in parallel, validators check each summary, synthesizer produces the final report
5. **Output path shown** — synthesis report location printed on completion

### Continuing a previous run

```text
Continue from the latest planner run
```

Root loads the existing manifest and skips straight to the research pipeline.

---

## Output structure

```
outputs/
  run_<timestamp>/
    planner_manifest.json
    papers/
      <arxiv_id>.pdf
      file_cache.json
    researchers/
      researcher_1/
        summary.md
        validator/
          validation_criteria.json
          validation_summary.md
      researcher_2/ ...
      researcher_3/ ...
    synthesis/
      synthesis_report.md
      synthesis_summary.json
```

Only the 3 most recent runs are kept (configurable via `keep_last` in `create_run_output_dir`).

---

## Agent hierarchy

```
Root
└── Planner
    └── Research Pipeline (SequentialAgent)
        ├── Researcher Pool (parallel LoopAgents)
        │   ├── Researcher_1 + Validator_1
        │   ├── Researcher_2 + Validator_2
        │   └── Researcher_N + Validator_N
        └── Synthesizer
```

All tools are defined in `tools/agent_tools.py`. Agent prompts live in `<subagent>/agent_prompt.md`.
