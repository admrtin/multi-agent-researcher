# The root agent.
# Acts as the interface to planner agent.
from pathlib import Path
from google.adk.agents import Agent
from subagents.planner.agent import planner_agent
from tools.agent_tools import gemini_models

prompt = Path("root_agent_prompt.md").read_text()
agent_name = "ROOT"
root_agent = Agent(
    name=agent_name,
    model=gemini_models.ROOT,
    instruction=prompt,
    sub_agents=[planner_agent],
)