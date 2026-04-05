from pathlib import Path
from google.adk.agents import Agent
from tools.agent_tools import (
    save_markdown_file,
    create_run_output_dir,
    research_single_paper,
    save_json_file,
    gemini_models,
)

prompt = Path("./subagents/researcher/researcher_agent_prompt.md").read_text()
agent_name = "RESEARCHER"

researcher_agent = Agent(
    name=agent_name,
    model=gemini_models.RESEARCHER,
    instruction=prompt,
    tools=[
        create_run_output_dir,
        research_single_paper,
        save_markdown_file,
        save_json_file,
    ],
)