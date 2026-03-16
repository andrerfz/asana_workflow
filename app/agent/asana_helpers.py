"""Asana integration helpers for the agent — comments, subtasks, sections."""
import logging
import re as _re
import subprocess
from typing import Optional

from .state import add_log, load_agent_run, save_agent_run
from .claude_client import _run_claude_cli
from ..services.repo_manager import get_repo
from ..services.asana_client import (
    add_task_comment, delete_story, move_task_to_section, find_section_by_name,
    fetch_task_stories, fetch_subtasks, complete_subtask,
)

log = logging.getLogger(__name__)

_section_cache: dict[str, str | None] = {}


async def _move_task_section(task_gid: str, section_name: str):
    """Move task to a named section, caching section GID lookups."""
    try:
        if section_name not in _section_cache:
            _section_cache[section_name] = await find_section_by_name(section_name, create_if_missing=True)
        gid = _section_cache[section_name]
        if gid:
            await move_task_to_section(task_gid, gid)
            add_log(task_gid, f"Moved task to '{section_name}' in Asana")
        else:
            add_log(task_gid, f"Section '{section_name}' not found in Asana", "warning")
    except Exception as e:
        add_log(task_gid, f"Failed to move task to '{section_name}': {e}", "warning")


def _qa_verdict_is_pass(qa_text: str) -> bool:
    """Parse QA report to determine if verdict is PASS.

    Looks for explicit PASS/FAIL verdict markers. Defaults to FAIL (ask user)
    if ambiguous — better to ask than to auto-approve broken code.
    """
    text_lower = qa_text.lower()
    verdict_match = _re.search(r'verdict[:\s—\-\*]*\s*(pass|fail)', text_lower)
    if verdict_match:
        return verdict_match.group(1) == 'pass'
    if 'verdict: pass' in text_lower or '✅ pass' in text_lower or 'ready for delivery' in text_lower:
        return True
    return False


def _build_fix_instructions(qa_report: str, user_feedback: str = "") -> str:
    """Build fix-focused instructions from QA report + optional user feedback."""
    parts = []
    if user_feedback:
        parts.append(f"## User Instructions\n{user_feedback}")
    if qa_report:
        parts.append(f"## QA Issues to Fix\nThe following issues were found during QA review. Fix each one:\n\n{qa_report}")
    return "\n\n".join(parts) if parts else "Fix the issues found during QA review."


async def _post_asana_comment(task_gid: str, text: str, dedup_prefix: str = ""):
    """Post a comment on the Asana task (best-effort, never blocks agent).
    If dedup_prefix is set, delete any existing comment with that prefix before posting."""
    try:
        if dedup_prefix:
            stories = await fetch_task_stories(task_gid)
            if stories:
                for s in stories[-10:]:
                    existing = (s.get("text") or "").strip()
                    if existing.startswith(dedup_prefix):
                        story_gid = s.get("gid")
                        if story_gid:
                            await delete_story(story_gid)
                            add_log(task_gid, f"Deleted old Asana comment ({dedup_prefix[:30]}...)")
        await add_task_comment(task_gid, text)
    except Exception as e:
        add_log(task_gid, f"Failed to post Asana comment: {e}", "warning")


async def _auto_complete_subtasks(task_gid: str, run: dict):
    """After agent completes, ask Claude which subtasks were addressed and mark them done."""
    try:
        subtasks = await fetch_subtasks(task_gid)
        open_subtasks = [s for s in subtasks if not s.get("completed")]
        if not open_subtasks:
            return

        # Build a diff summary from all repos
        diff_summary = ""
        for repo_entry in run.get("repos", []):
            wt_path = repo_entry.get("worktree_path")
            if not wt_path:
                continue
            try:
                result = subprocess.run(
                    ["git", "log", "--oneline", "-20", f"origin/{repo_entry.get('default_branch', 'master')}..HEAD"],
                    cwd=wt_path, capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    diff_summary += f"\n### Commits in {repo_entry['id']}:\n{result.stdout.strip()}\n"
            except Exception:
                pass

        if not diff_summary:
            return

        # Ask Claude (quick, 1-turn) which subtasks were resolved
        subtask_list = "\n".join(
            f"- GID:{s['gid']} — {s.get('name', '?')}" for s in open_subtasks
        )
        prompt = (
            f"Given these commits:\n{diff_summary}\n\n"
            f"And these open subtasks:\n{subtask_list}\n\n"
            f"Which subtasks are FULLY resolved by the commits above? "
            f"Reply with ONLY the GIDs of resolved subtasks, one per line. "
            f"If none are resolved, reply NONE."
        )

        # Use first available worktree as cwd (Claude CLI requires cwd inside worktree sandbox)
        cli_cwd = next((r["worktree_path"] for r in run.get("repos", []) if r.get("worktree_path")), "/tmp")
        result = await _run_claude_cli(
            prompt=prompt,
            cwd=cli_cwd,
            max_turns=1,
            output_format="text",
        )

        response = result.get("text", "").strip()
        if not response or "NONE" in response.upper():
            add_log(task_gid, "No subtasks auto-completed (agent found none resolved)")
            return

        # Parse GIDs from response (exact word match to avoid substring false positives)
        completed = 0
        response_tokens = set(_re.findall(r'\b\d+\b', response))
        for st in open_subtasks:
            if st["gid"] in response_tokens:
                success = await complete_subtask(st["gid"])
                if success:
                    add_log(task_gid, f"Auto-completed subtask: {st.get('name', st['gid'])}")
                    completed += 1

        if completed:
            add_log(task_gid, f"Marked {completed} subtask(s) as complete in Asana")

    except Exception as e:
        log.warning("Failed to auto-complete subtasks for %s: %s", task_gid, e)
        add_log(task_gid, f"Subtask auto-complete failed: {e}", "warning")


async def _fetch_subtasks_context(task_gid: str) -> str:
    """Fetch subtasks from Asana, formatted for agent context."""
    try:
        subtasks = await fetch_subtasks(task_gid)
        if not subtasks:
            return ""
        lines = []
        for st in subtasks:
            status = "✓" if st.get("completed") else "○"
            name = st.get("name", "")
            assignee = st.get("assignee", {})
            assignee_name = assignee.get("name", "") if assignee else ""
            notes = st.get("notes", "").strip()
            line = f"- {status} {name}"
            if assignee_name:
                line += f" (assigned: {assignee_name})"
            if notes:
                line += f"\n  Details: {notes[:500]}"
            lines.append(line)
        if lines:
            return "\n\n## Subtasks\n" + "\n".join(lines)
    except Exception as e:
        log.warning("Failed to fetch subtasks for %s: %s", task_gid, e)
    return ""


def _get_branch_state(run: dict) -> str:
    """Get existing commits on the branch to show what work has already been done."""
    parts = []
    for r in run["repos"]:
        wt_path = r.get("worktree_path")
        if not wt_path:
            continue
        repo = get_repo(r["id"])
        default_branch = repo.get("default_branch", "master") if repo else "master"
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", f"origin/{default_branch}..HEAD"],
                cwd=wt_path, capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                commits = result.stdout.strip()
                parts.append(f"\n### Existing commits on branch ({r['id']}):\n```\n{commits}\n```")

            result2 = subprocess.run(
                ["git", "status", "--short"],
                cwd=wt_path, capture_output=True, text=True, timeout=10,
            )
            if result2.returncode == 0 and result2.stdout.strip():
                parts.append(f"\n### Uncommitted changes ({r['id']}):\n```\n{result2.stdout.strip()}\n```")
        except Exception as e:
            log.warning("Failed to get branch state for %s: %s", r["id"], e)

    if parts:
        return "\n\n## Existing Branch State\nThis branch already has prior work. Review it before making changes." + "".join(parts)
    return ""


async def _fetch_task_comments(task_gid: str) -> str:
    """Fetch human comments from Asana task, formatted for context."""
    try:
        stories = await fetch_task_stories(task_gid)
        if not stories:
            return ""
        lines = []
        for s in stories[-15:]:  # last 15 comments max
            author = s.get("created_by", {}).get("name", "Unknown")
            text = s.get("text", "").strip()
            if text:
                lines.append(f"- {author}: {text[:500]}")
        if lines:
            return "\n## Task Comments\n" + "\n".join(lines)
    except Exception as e:
        log.warning("Failed to fetch task comments for %s: %s", task_gid, e)
    return ""
