from pathlib import Path
from google.adk.agents import Agent
from tools.agent_tools import (
    save_markdown_file,
    save_json_file,
    load_json_file,
    get_latest_run_dir,
    read_researcher_output,
    gemini_models,
    stream_terminal_update,
)
from tools.stats_collector import make_token_callback, pipeline_end_callback

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
        read_researcher_output,
        stream_terminal_update,
    ],
    include_contents="none",
    after_model_callback=make_token_callback("SYNTHESIZER"),
    after_agent_callback=pipeline_end_callback,
)