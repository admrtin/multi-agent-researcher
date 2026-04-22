from pathlib import Path
from google.adk.agents import Agent
from tools.agent_tools import (
    save_markdown_file,
    save_json_file,
    load_json_file,
    get_latest_run_dir,
    gemini_models,
)

prompt = Path("./subagents/synthesizer/synthesizer_agent_prompt.md").read_text()
agent_name = "SYNTHESIZER"

synthesizer_agent = Agent(
    name=agent_name,
    model=gemini_models.SYNTHESIZER,
    instruction=prompt,
    tools=[
        save_markdown_file,
        save_json_file,
        load_json_file,
        get_latest_run_dir,
    ],
)
