from pathlib import Path
from google.adk.agents import Agent
from tools.agent_tools import (
    create_run_output_dir,
    search_arxiv,
    save_json_file,
    save_markdown_file,
    bulk_download_arxiv_pdfs,
    gemini_models,
)

import os
from dotenv import load_dotenv

load_dotenv()
SEED_PAPER_COUNT = int(os.getenv("SEED_PAPER_COUNT", "10"))

prompt = Path("./subagents/planner/planner_agent_prompt.md").read_text()
prompt = prompt.replace("{SEED_PAPER_COUNT}", str(SEED_PAPER_COUNT))
agent_name = "PLANNER"

planner_agent = Agent(
    name=agent_name,
    model=gemini_models.PLANNER,
    instruction=prompt,
    tools=[
        create_run_output_dir,
        search_arxiv,
        save_json_file,
        save_markdown_file,
        bulk_download_arxiv_pdfs,
    ],
)