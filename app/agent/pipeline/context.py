"""Context building helpers for agent prompts."""
import logging
import re
from pathlib import Path

from ..state import load_run_history
from ..memory import get_memory_context
from ...services.repo_manager import get_repo, list_repos, load_repos, AREA_REPO_MAP

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
        notes = task["notes"][:8000]
        parts.append(f"\n## Description\n{notes}")
        if len(task["notes"]) > 8000:
            parts.append(f"[...notes truncated, {len(task['notes'])} chars total]")
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
                content = global_md.read_text()[:4000]
                guides.append(f"## Global Project Guide (CLAUDE.md)\n{content}")
            except OSError:
                pass

    # Per-repo CLAUDE.md — only load for repos assigned to this task
    # Unassigned/related repos are skipped to reduce context size
    task_repo_ids = {r["id"] for r in run.get("repos", [])}
    all_repos = list_repos()
    for repo_entry in all_repos:
        if repo_entry["id"] not in task_repo_ids:
            continue  # skip unassigned repos — saves ~3000 chars each
        repo_path = repo_entry.get("path", "")
        if not repo_path:
            continue
        repo_md = Path(repo_path) / "CLAUDE.md"
        if repo_md.exists():
            try:
                content = repo_md.read_text()[:2500]
                guides.append(f"## {repo_entry['id']} CLAUDE.md\n{content}")
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

    # Tolerate near-misses: exact repo id, case-insensitive id, or an area name
    # (e.g. "backend_proveedor") that maps to one or more repos.
    ci_ids = {rid.lower(): rid for rid in all_repo_ids}
    area_map = load_repos().get("area_repo_map", AREA_REPO_MAP)

    def _resolve(token: str) -> list[str]:
        if token in all_repo_ids:
            return [token]
        if token.lower() in ci_ids:
            return [ci_ids[token.lower()]]
        if token in area_map:  # an area name → its repo ids
            return [rid for rid in area_map[token] if rid in all_repo_ids]
        return []

    valid = []
    for token in requested:
        resolved = _resolve(token)
        if not resolved:
            log.warning("Investigation requested unknown repo: %s (available: %s)", token, all_repo_ids)
            continue
        for repo_id in resolved:
            if repo_id in existing_ids:
                log.info("Additional repo %s already assigned — skipping", repo_id)
                continue
            if repo_id in valid:
                continue
            valid.append(repo_id)
    return valid
