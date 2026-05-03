# The root agent.
# Acts as the interface to planner and research pipeline agents.
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="google.adk")

from pathlib import Path
from google.adk.agents import Agent

from subagents.planner.agent import planner_agent
from tools.agent_tools import gemini_models, load_json_file, get_latest_planner_manifest, get_latest_run_dir, stream_terminal_update

prompt = Path("root_agent_prompt.md").read_text()
agent_name = "ROOT"

root_agent = Agent(
    name=agent_name,
    model=gemini_models.ROOT,
    instruction=prompt,
    tools=[
        load_json_file,
        get_latest_planner_manifest,
        get_latest_run_dir,
        stream_terminal_update,
    ],
    sub_agents=[
        planner_agent,
    ],
)

# Immediate greeting for CLI users.
# We use a small delay and a background thread to ensure it appears after
# the initial ADK log setup and experimental warnings.
def _delayed_greeting():
    import os, time

    if os.getenv("ADK_TUI_MODE"):
        return
    time.sleep(0.5)
    _BOLD_CYAN = "\033[1;96m"
    _RESET     = "\033[0m"
    bar = "═" * 60
    print(f"\n{_BOLD_CYAN}{bar}{_RESET}")
    print(f"{_BOLD_CYAN}  ROOT  ·  Research Intake Coordinator{_RESET}")
    print(f"{_BOLD_CYAN}{bar}{_RESET}")
    print( "  I can help you plan a literature review, analyze a")
    print( "  specific paper, or continue from a previous run.")
    print( "  What would you like to start with?")
    print(f"{_BOLD_CYAN}{bar}{_RESET}\n")


import threading

threading.Thread(target=_delayed_greeting, daemon=True).start()
