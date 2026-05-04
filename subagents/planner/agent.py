from pathlib import Path
from google.adk.agents import Agent, SequentialAgent
from google.adk.tools.agent_tool import AgentTool
from tools.agent_tools import (
    create_run_output_dir,
    get_latest_run_dir,
    search_arxiv,
    save_json_file,
    save_markdown_file,
    bulk_download_arxiv_pdfs,
    gemini_models,
    stream_terminal_update,
)
from tools.stats_collector import make_token_callback, pipeline_start_callback

import os
from dotenv import load_dotenv

load_dotenv()
SEED_PAPER_COUNT = int(os.getenv("SEED_PAPER_COUNT", "3"))

prompt = Path("./subagents/planner/planner_agent_prompt.md").read_text()
prompt = prompt.replace("{SEED_PAPER_COUNT}", str(SEED_PAPER_COUNT))
agent_name = "PLANNER"

# Import here to avoid circular dependency (researcher/synthesizer don't import planner)
from subagents.researcher.agent import researcher_agent
from subagents.synthesizer.agent import synthesizer_agent

# PLANNER owns the research pipeline so it can invoke it directly after
# downloading papers — ROOT cannot re-invoke sub-agents after a turn ends.
research_pipeline = SequentialAgent(
    name="RESEARCH_PIPELINE",
    sub_agents=[researcher_agent, synthesizer_agent],
    description="Runs all paper researchers in parallel batches, then synthesizes the results.",
)

planner_agent = Agent(
    name=agent_name,
    model=gemini_models.PLANNER,
    instruction=prompt,
    tools=[
        create_run_output_dir,
        get_latest_run_dir,
        search_arxiv,
        save_json_file,
        save_markdown_file,
        bulk_download_arxiv_pdfs,
        stream_terminal_update,
        AgentTool(agent=research_pipeline),
    ],
    before_agent_callback=pipeline_start_callback,
    after_model_callback=make_token_callback("PLANNER"),
)
