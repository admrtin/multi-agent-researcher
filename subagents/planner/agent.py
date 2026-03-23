from pathlib import Path
from google.adk.agents import Agent
from tools.agent_tools import save_markdown_file, gemini_models

prompt = Path("./subagents/planner/planner_agent_prompt.md").read_text()
agent_name = "PLANNER"

planner_agent = Agent(
    name=agent_name,
    model=gemini_models.PLANNER, # Fixed model version
    instruction=prompt, # The agent's context prompt
    tools=[save_markdown_file], # Give it the ability to write
)

# TODO: We need to implement the research article abstract/reference scraper as a tool for the planner
# TODO: Once above TODO is done we need to update the planner prompt to reflect