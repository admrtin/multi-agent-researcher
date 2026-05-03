#!/usr/bin/env python
"""
dashboard.py — Textual TUI for the Multi-Agent Researcher.
Run: python dashboard.py  (from the multi_agent_researcher/ directory)
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Optional

# Must be set before any agent module is imported (suppresses the greeting thread).
os.environ["ADK_TUI_MODE"] = "1"

sys.path.insert(0, str(Path(__file__).parent))

if not Path("agent.py").exists():
    sys.exit(
        "Error: dashboard.py must be run from the multi_agent_researcher/ directory.\n"
        "  cd /path/to/multi_agent_researcher && python dashboard.py"
    )

try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Footer, Header, Input, Label, RichLog, Static
    from textual import on, work
    from rich.text import Text
    from rich.rule import Rule
except ImportError:
    sys.exit(
        "Error: 'textual' is not installed.\n"
        "  pip install 'textual>=0.89.0'"
    )

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STATUS_ICONS = {
    "idle":     "○",
    "running":  "●",
    "complete": "✓",
    "error":    "✗",
    "skipped":  "–",
}
_STATUS_STYLES = {
    "idle":     "dim",
    "running":  "bold yellow",
    "complete": "bold green",
    "error":    "bold red",
    "skipped":  "dim",
}
_CONTENT_COLORS = {
    "info":        "cyan",
    "step":        "blue",
    "success":     "green",
    "warning":     "yellow",
    "error":       "red",
    "planner":     "magenta",
    "researcher":  "dark_cyan",
    "validator":   "orange3",
    "synthesizer": "medium_purple",
}
_APPROVAL_KEYWORDS = frozenset(
    ["approved", "approve", "yes", "proceed", "continue", "remove", "confirm"]
)


# ---------------------------------------------------------------------------
# AgentStatusPanel
# ---------------------------------------------------------------------------

class AgentStatusPanel(Static):
    """Left panel: per-agent status grid."""

    DEFAULT_CSS = """
    AgentStatusPanel {
        width: 30;
        height: 1fr;
        border: solid $primary;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def __init__(self, seed_count: int = 3, **kwargs):
        super().__init__(**kwargs)
        self._seed_count = seed_count
        self._statuses: dict[str, str] = {}  # agent_key → status
        self._order: list[str] = []
        self._build_initial()

    def _build_initial(self) -> None:
        keys = ["PLANNER"]
        for i in range(1, self._seed_count + 1):
            keys.append(f"RESEARCHER:{i}")
            keys.append(f"VALIDATOR:{i}")
        keys.append("SYNTHESIZER")
        self._order = keys
        for k in keys:
            self._statuses[k] = "idle"

    def render(self) -> Text:
        t = Text()
        t.append("Pipeline Status\n", style="bold underline")
        for key in self._order:
            status = self._statuses.get(key, "idle")
            icon = _STATUS_ICONS.get(status, "○")
            style = _STATUS_STYLES.get(status, "")
            t.append(f" {icon} ", style=style)
            t.append(f"{key:<20}", style=style)
            t.append(f"{status.capitalize()}\n", style=style)
        return t

    def update_status(self, agent_key: str, status: str) -> None:
        if agent_key not in self._statuses:
            self._order.append(agent_key)
        self._statuses[agent_key] = status
        self.refresh()

    def reset_all(self) -> None:
        for k in self._order:
            self._statuses[k] = "idle"
        self.refresh()


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

class ResearcherApp(App):
    TITLE = "Multi-Agent Researcher"
    CSS = """
    Screen { layout: vertical; }

    #main-pane {
        height: 1fr;
    }

    #log-panel {
        width: 1fr;
        height: 1fr;
        border: solid $accent;
        padding: 0 1;
    }

    #input-bar {
        height: 3;
        border: solid $primary;
        padding: 0 1;
    }

    #input-label {
        width: 3;
        content-align: left middle;
    }

    #user-input {
        width: 1fr;
        background: $boost;
        color: $text;
        border: none;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("ctrl+l", "clear_log", "Clear Log"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._seed_count: int = int(os.getenv("SEED_PAPER_COUNT", "3"))
        self._runner = None
        self._session_id: Optional[str] = None
        self._user_id = "tui_user"
        self._app_name = "researcher"
        self._genai_types = None
        self._chat_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        self._runner_ready = False
        self._status_panel: Optional[AgentStatusPanel] = None
        # Per-turn flags set synchronously in _on_stream_update
        self._manifest_saved_this_turn: bool = False
        self._pipeline_activity_this_turn: bool = False
        self._auto_continue_attempts: int = 0

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        self._status_panel = AgentStatusPanel(
            seed_count=self._seed_count, id="status-panel"
        )
        with Horizontal(id="main-pane"):
            yield self._status_panel
            yield RichLog(id="log-panel", markup=True, highlight=False, wrap=True)
        with Horizontal(id="input-bar"):
            yield Label("> ", id="input-label")
            yield Input(
                placeholder="Enter research topic or message...",
                id="user-input",
                disabled=True,
            )
        yield Footer()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self._log("[bold cyan]Initializing — loading agent modules...[/bold cyan]")
        self._initialize_runner()

    # ------------------------------------------------------------------
    # Initialization worker
    # ------------------------------------------------------------------

    @work(exclusive=True, group="init")
    async def _initialize_runner(self) -> None:
        try:
            import tools.agent_tools as _at
            _at._tui_callback = self._on_stream_update

            from agent import root_agent  # noqa: PLC0415
            from google.adk.runners import Runner
            from google.adk.sessions import InMemorySessionService
            from google.genai import types as _types

            self._genai_types = _types

            session_svc = InMemorySessionService()
            session = await session_svc.create_session(
                app_name=self._app_name, user_id=self._user_id
            )
            self._session_id = session.id
            self._runner = Runner(
                agent=root_agent,
                app_name=self._app_name,
                session_service=session_svc,
            )
            self._runner_ready = True
            self._log("[bold green]Ready. Enter a research topic below.[/bold green]")

            user_input = self.query_one("#user-input", Input)
            user_input.disabled = False
            user_input.focus()

            self._conversation_loop()

        except Exception as exc:
            self._log(f"[bold red]Initialization failed: {exc}[/bold red]")
            raise

    # ------------------------------------------------------------------
    # Stream callback (called synchronously from stream_terminal_update
    # which runs in the asyncio event loop thread inside a @work task)
    # ------------------------------------------------------------------

    def _on_stream_update(
        self, prefix: str, message: str, content_type: str, agent_name: str
    ) -> None:
        # Update pipeline-tracking flags synchronously before yielding control.
        if "saving manifest" in message.lower():
            self._manifest_saved_this_turn = True
        if content_type in ("researcher", "validator", "synthesizer"):
            self._pipeline_activity_this_turn = True

        # stream_terminal_update is a sync function called from within the ADK
        # async task, which runs on the same event loop thread as Textual.
        # call_from_thread() requires a *different* thread, so we use call_soon()
        # to schedule the UI update for the next event loop iteration instead.
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon(
                self._apply_stream_update, prefix, message, content_type, agent_name
            )
        except RuntimeError:
            # No running loop (shouldn't happen, but safe fallback)
            self._apply_stream_update(prefix, message, content_type, agent_name)

    def _apply_stream_update(
        self, prefix: str, message: str, content_type: str, agent_name: str
    ) -> None:
        color = _CONTENT_COLORS.get(content_type, "cyan")
        log = self.query_one("#log-panel", RichLog)
        # Build Text directly — prefix/message may contain "[label]" strings
        # (e.g. "▸ [arXiv search]") that would be mis-parsed as Rich markup tags.
        t = Text()
        t.append(f"{prefix} {message}", style=color)
        log.write(t)

        if self._status_panel is not None:
            self._update_agent_status(content_type, agent_name, message)

    def _update_agent_status(
        self, content_type: str, agent_name: str, message: str
    ) -> None:
        name_upper = agent_name.upper()
        m = re.search(r"[_\s](\d+)$", name_upper)
        if m:
            base = re.sub(r"[_\s]\d+$", "", name_upper)
            agent_key = f"{base}:{m.group(1)}"
            idx = m.group(1)
        else:
            agent_key = name_upper
            idx = None

        if content_type == "error":
            new_status = "error"
        elif content_type == "success":
            new_status = "complete"
        else:
            new_status = "running"

        self._status_panel.update_status(agent_key, new_status)

        # When a validator passes, also mark its paired researcher complete.
        if new_status == "complete" and "VALIDATOR" in agent_key and idx:
            self._status_panel.update_status(f"RESEARCHER:{idx}", "complete")

        # When planner reports pipeline done, sweep everything to complete
        # and show the synthesis report path.
        msg_lower = message.lower()
        if "PLANNER" in name_upper and (
            "pipeline complete" in msg_lower or "synthesis saved" in msg_lower
        ):
            for key in list(self._status_panel._order):
                self._status_panel.update_status(key, "complete")
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon(self._show_synthesis_path)
            except RuntimeError:
                self._show_synthesis_path()

    def _show_synthesis_path(self) -> None:
        try:
            from tools.agent_tools import get_latest_run_dir
            run_dir = get_latest_run_dir("outputs")
            synthesis_path = f"{run_dir}/synthesis/synthesis_report.md"
            log = self.query_one("#log-panel", RichLog)
            log.write("")
            banner = Text()
            banner.append("✓ Pipeline complete.  ", style="bold green")
            banner.append("Synthesis report → ", style="green")
            banner.append(synthesis_path, style="bold white")
            log.write(banner)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Conversation loop worker
    # ------------------------------------------------------------------

    @work(exclusive=True, group="conversation")
    async def _conversation_loop(self) -> None:
        log = self.query_one("#log-panel", RichLog)
        user_input = self.query_one("#user-input", Input)

        while True:
            user_text = await self._chat_queue.get()
            if user_text is None:
                break

            log.write(Text.from_markup(f"[bold white]▶ {user_text}[/bold white]"))

            is_approval = any(kw in user_text.lower() for kw in _APPROVAL_KEYWORDS)
            if not is_approval and self._status_panel is not None:
                self._status_panel.reset_all()

            # Reset per-turn pipeline tracking
            self._manifest_saved_this_turn = False
            self._pipeline_activity_this_turn = False

            user_input.disabled = True
            had_exception = False

            try:
                async for event in self._runner.run_async(
                    user_id=self._user_id,
                    session_id=self._session_id,
                    new_message=self._genai_types.Content(
                        role="user",
                        parts=[self._genai_types.Part(text=user_text)],
                    ),
                ):
                    if (
                        event.is_final_response()
                        and event.content
                        and event.content.parts
                    ):
                        text = "".join(
                            getattr(p, "text", "") or ""
                            for p in event.content.parts
                        ).strip()
                        if text:
                            author = getattr(event, "author", "AGENT")
                            # Blank line + author header before each response
                            log.write("")
                            header = Text()
                            header.append(f"── [{author}] " + "─" * 20, style="bold cyan")
                            log.write(header)
                            # Custom renderer: converts **bold** and --- rules
                            # without Rich's Markdown underline/heading styles.
                            for line in text.splitlines():
                                if line.strip() == "---":
                                    log.write(Rule(style="dim cyan"))
                                else:
                                    t = Text()
                                    parts = re.split(r"\*\*(.*?)\*\*", line)
                                    for i, part in enumerate(parts):
                                        t.append(part, style="bold" if i % 2 == 1 else "")
                                    log.write(t)

            except Exception as exc:
                had_exception = True
                log.write(
                    Text.from_markup(f"[bold red]Pipeline error: {exc}[/bold red]")
                )

            # If the manifest was saved but researchers never started, the planner
            # skipped the RESEARCH_PIPELINE tool call. Use ROOT's continuation flow
            # (get_latest_planner_manifest → PLANNER skips phases 1-4 → calls
            # RESEARCH_PIPELINE directly). Cap at 3 attempts to avoid infinite loops.
            if (
                not had_exception
                and self._manifest_saved_this_turn
                and not self._pipeline_activity_this_turn
                and self._auto_continue_attempts < 3
            ):
                self._auto_continue_attempts += 1
                log.write(Text.from_markup(
                    "[dim yellow]Manifest saved but pipeline not started — "
                    f"auto-continuing (attempt {self._auto_continue_attempts}/3)...[/dim yellow]"
                ))
                await asyncio.sleep(0.5)
                self._chat_queue.put_nowait("Continue from the latest planner run")
            else:
                if self._pipeline_activity_this_turn:
                    self._auto_continue_attempts = 0
                user_input.disabled = False
                user_input.focus()

    # ------------------------------------------------------------------
    # Input handler
    # ------------------------------------------------------------------

    @on(Input.Submitted, "#user-input")
    def on_user_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        if not self._runner_ready:
            self._log("[yellow]Still initializing — please wait...[/yellow]")
            return
        self._chat_queue.put_nowait(text)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_clear_log(self) -> None:
        self.query_one("#log-panel", RichLog).clear()

    def action_quit(self) -> None:
        self._chat_queue.put_nowait(None)
        try:
            import tools.agent_tools as _at
            _at._tui_callback = None
        except Exception:
            pass
        self.exit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, markup: str) -> None:
        try:
            self.query_one("#log-panel", RichLog).write(Text.from_markup(markup))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ResearcherApp().run()
