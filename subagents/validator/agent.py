from pathlib import Path
from google.adk.agents import Agent
from tools.agent_tools import (
    save_markdown_file,
    save_json_file,
    gemini_models,
    read_researcher_output,
    exit_loop,
)

prompt = Path("./subagents/validator/validator_agent_prompt.md").read_text()
agent_name = "VALIDATOR"
validator_agent = Agent(
    name=agent_name,
    model=gemini_models.VALIDATOR,
    instruction=prompt,
    tools=[
        save_markdown_file,
        save_json_file,
        read_researcher_output,
        exit_loop,
    ],
)