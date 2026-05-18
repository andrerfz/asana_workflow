"""Pipeline modules — per-phase implementations for the agent executor.

Modules:
  timer       — work-time budget tracker
  context     — task context and CLAUDE.md guide builders
  investigate — codebase exploration phase
  plan        — implementation plan generation
  code        — coding phase with guide support
  rebase      — git rebase onto default branch
  test        — test execution with auto-fix retries
  qa          — QA review and quality checks
"""

from .timer import AgentTimer, agent_timers, check_timeout
from .context import build_task_context, load_claude_md_guides, parse_additional_repos
from .investigate import agent_investigate
from .plan import agent_plan
from .code import agent_code, auto_commit_if_dirty
from .rebase import rebase_from_default
from .test import agent_test, run_test_with_progress, select_test_cmd, has_migration_files, has_backend_files
from .qa import agent_qa_review, quality_checks, _QARateLimitError
from .finalize import agent_finalize

__all__ = [
    "AgentTimer", "agent_timers", "check_timeout",
    "build_task_context", "load_claude_md_guides", "parse_additional_repos",
    "agent_investigate",
    "agent_plan",
    "agent_code", "auto_commit_if_dirty",
    "rebase_from_default",
    "agent_test", "run_test_with_progress", "select_test_cmd", "has_migration_files", "has_backend_files",
    "agent_qa_review", "quality_checks",
    "agent_finalize",
]
