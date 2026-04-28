"""Context building helpers for agent prompts."""
import logging
import re
from pathlib import Path

from ..state import load_run_history
from ..memory import get_memory_context
from ...services.repo_manager import get_repo, list_repos

log = logging.getLogger(__name__)


def build_task_context(task: dict, run: dict) -> str:
    """Build rich context string for the agent from task data."""
    parts = [
        f"# Task: {task.get('name', 'Unknown')}",
        f"GID: {task.get('task_gid', '')}",
        f"Type: {task.get('tipo', 'N/A')}",
        f"Priority: {task.get('priority', 'N/A')}",
        f"Cluster: {task.get('cluster', {}).get('name', 'N/A')}",
        f"Area: {task.get('area', 'N/A')}",
    ]
    if task.get("notes"):
        parts.append(f"\n## Description\n{task['notes']}")
    if task.get("tags"):
        parts.append(f"\nTags: {', '.join(task['tags'])}")

    parts.append("\n## Repositories")
    for r in run["repos"]:
        repo = get_repo(r["id"])
        if repo:
            work_path = r.get("worktree_path") or repo["path"]
            parts.append(f"- {r['id']}: {work_path} (branch: {r.get('branch', 'N/A')})")
            if repo.get("language"):
                parts.append(f"  Language: {repo['language']}")
            if repo.get("context_files"):
                parts.append(f"  Context files: {', '.join(repo['context_files'])}")
            memory_ctx = get_memory_context(r["id"])
            if memory_ctx:
                parts.append(memory_ctx)

    history = load_run_history(run.get("task_gid", task.get("task_gid", "")))
    if history:
        parts.append("\n## Previous Agent Runs")
        parts.append("This task has been worked on before. Review what was done and what failed:")
        for i, prev in enumerate(history[:3]):
            status = prev.get("phase", "?")
            date = (prev.get("created_at") or "?")[:10]
            error = prev.get("error")
            commits = sum(r.get("commits", 0) for r in prev.get("repos", []))
            plan_summary = (prev.get("plan") or "")[:300]
            parts.append(f"\n### Run {i+1} ({date}, status: {status}, commits: {commits})")
            if plan_summary:
                parts.append(f"Plan: {plan_summary}...")
            if error:
                parts.append(f"Error: {error}")

    return "\n".join(parts)


def load_claude_md_guides(run: dict) -> str:
    """Load CLAUDE.md files from projects root and each configured repo."""
    from ...config import PROJECTS_DIR
    guides = []

    # Global CLAUDE.md at projects root
    if PROJECTS_DIR:
        global_md = Path(PROJECTS_DIR) / "CLAUDE.md"
        if global_md.exists():
            try:
                content = global_md.read_text()[:5000]
                guides.append(f"## Global Project Guide (CLAUDE.md)\n{content}")
            except OSError:
                pass

    # Per-repo CLAUDE.md files (including repos NOT assigned to this task)
    all_repos = list_repos()
    task_repo_ids = {r["id"] for r in run.get("repos", [])}
    for repo_entry in all_repos:
        repo_path = repo_entry.get("path", "")
        if not repo_path:
            continue
        repo_md = Path(repo_path) / "CLAUDE.md"
        if repo_md.exists():
            try:
                content = repo_md.read_text()[:3000]
                label = "assigned" if repo_entry["id"] in task_repo_ids else "related"
                guides.append(f"## {repo_entry['id']} CLAUDE.md ({label})\n{content}")
            except OSError:
                pass

    if guides:
        return "\n\n" + "\n\n".join(guides)
    return ""


def parse_additional_repos(investigation: str, run: dict) -> list[str]:
    """Parse ADDITIONAL_REPOS line from investigation report. Returns list of new repo IDs."""
    existing_ids = {r["id"] for r in run.get("repos", [])}
    try:
        all_repo_ids = {r["id"] for r in list_repos()}
    except Exception as e:
        log.error("Failed to list repos for additional repo parsing: %s", e)
        return []

    match = re.search(r"ADDITIONAL_REPOS:\s*(.+)", investigation)
    if not match:
        return []

    log.info("ADDITIONAL_REPOS line found: %s", match.group().strip())
    requested = [r.strip() for r in match.group(1).split(",") if r.strip()]
    valid = []
    for repo_id in requested:
        if repo_id in existing_ids:
            log.info("Additional repo %s already assigned — skipping", repo_id)
            continue
        if repo_id not in all_repo_ids:
            log.warning("Investigation requested unknown repo: %s (available: %s)", repo_id, all_repo_ids)
            continue
        valid.append(repo_id)
    return valid
