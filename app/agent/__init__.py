"""Agent package — AI agent for autonomous coding via Claude Code CLI.

Modules:
  phases         — AgentPhase enum, workflow graph
  state          — run persistence, logging, broadcasting, settings
  claude_client  — Claude Code CLI wrapper
  asana_helpers  — Asana integration helpers
  executor       — main execution engine (start/stop/plan/code/test/QA)
  queue          — concurrent execution queue
  memory         — per-repo knowledge base
  stream_parser  — CLI output parsing
  ws_manager     — WebSocket broadcasting
"""

from .phases import AgentPhase, WORKFLOW_GRAPH, get_workflow_graph as _get_workflow_graph_raw
from .state import (
    AGENT_RUNS_DIR,
    load_agent_run, save_agent_run, create_agent_run,
    add_log, update_phase, clear_agent_run,
    get_agent_status, list_active_agents, get_worktree_diff,
    load_run_history, load_agent_settings, save_agent_settings,
    register_event_callback,
)
from .claude_client import check_claude_code_status
from .executor import (
    start_agent, stop_agent, answer_question, guide_agent,
    resume_agent, trigger_manual_qa, run_manual_tests,
)
from .queue import agent_queue
from .memory import (
    load_memory, clear_memory, get_all_memory_repos,
    get_memory_context, update_memory_after_run,
)
from .stream_parser import recover_stale_runs
from .ws_manager import ws_manager


def get_workflow_graph() -> dict:
    """Load settings and return workflow graph with section names injected."""
    settings = load_agent_settings()
    return _get_workflow_graph_raw(settings)
