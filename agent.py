# The root agent.
# Acts as the interface to planner and research pipeline agents.
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="google.adk")

from pathlib import Path
from google.adk.agents import Agent, SequentialAgent

from subagents.planner.agent import planner_agent
from subagents.researcher.agent import researcher_agent
from subagents.synthesizer.agent import synthesizer_agent
from tools.agent_tools import gemini_models, load_json_file, get_latest_planner_manifest

prompt = Path("root_agent_prompt.md").read_text()
agent_name = "ROOT"

research_pipeline = SequentialAgent(
    name="RESEARCH_PIPELINE",
    sub_agents=[
        researcher_agent,
        synthesizer_agent,
    ],
)

root_agent = Agent(
    name=agent_name,
    model=gemini_models.ROOT,
    instruction=prompt,
    tools=[
        load_json_file,
        get_latest_planner_manifest,
    ],
    sub_agents=[
        planner_agent,
        research_pipeline,
    ],
)

# Immediate greeting for CLI users.
# We use a small delay and a background thread to ensure it appears after
# the initial ADK log setup and experimental warnings.
def _delayed_greeting():
    import time

    time.sleep(0.5)
    print("\n" + "═" * 70)
    print("  [ROOT]: Hello! I am the Research Intake Coordinator.")
    print("  I can help you plan a literature review, analyze a specific paper,")
    print("  or continue from a previous research run.")
    print("  What would you like to start with?")
    print("═" * 70 + "\n")


import threading

threading.Thread(target=_delayed_greeting, daemon=True).start()