from pathlib import Path
from google.adk.agents import Agent
from tools.agent_tools import (
    save_markdown_file,
    create_run_output_dir,
    cleanup_old_runs,
    scrape_research_articles,
    gemini_models,
)

prompt = Path("./subagents/planner/planner_agent_prompt.md").read_text()
agent_name = "PLANNER"

planner_agent = Agent(
    name=agent_name,
    model=gemini_models.PLANNER,
    instruction=prompt,
    tools=[
        save_markdown_file,
        create_run_output_dir,
        cleanup_old_runs,
        scrape_research_articles,
    ],
)

# TODO: (DONE) We need to implement the research article abstract/reference scraper as a tool for the planner
# TODO: (DONE) Once above TODO is done we need to update the planner prompt to reflect