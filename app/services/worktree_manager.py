"""Git worktree lifecycle manager for agent workers."""
import logging
import os
import subprocess
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

from ..config import PROJECTS_DIR
from .repo_manager import get_repo

log = logging.getLogger(__name__)

# Worktrees live under PROJECTS_DIR so they're accessible from host IDE
# Falls back to ~/.asana-agent/worktrees if PROJECTS_DIR not set
WORKTREE_BASE = (
    Path(PROJECTS_DIR) / ".asana-agent" / "worktrees"
    if PROJECTS_DIR
    else Path.home() / ".asana-agent" / "worktrees"
)
STALE_DAYS = 7  # Auto-cleanup threshold


def _run_git(args: list[str], cwd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    return subprocess.run(
        ["git"] + args,
        cwd=cwd, capture_output=True, text=True, timeout=timeout,
    )


def get_worktree_path(task_gid: str, repo_id: str) -> Path:
    """Get the worktree directory path for a task + repo combo."""
    wt_path = WORKTREE_BASE / task_gid / repo_id
    # Prevent path traversal via crafted task_gid or repo_id
    if not str(wt_path.resolve()).startswith(str(WORKTREE_BASE.resolve()) + os.sep):
        raise ValueError(f"Invalid path components: task_gid={task_gid}, repo_id={repo_id}")
    return wt_path


def create_worktree(task_gid: str, repo_id: str, branch_slug: str,
                    base_branch: str = None) -> dict:
    """
    Create a git worktree for a task in a specific repo.
    If base_branch is provided, the worktree branches from that branch
    (useful to continue work someone else started).
    Returns: { path, branch, created, status }
    """
    repo = get_repo(repo_id)
    if not repo:
        raise ValueError(f"Repo '{repo_id}' not configured")

    repo_path = repo["path"]
    default_branch = repo.get("default_branch", "master")
    wt_path = get_worktree_path(task_gid, repo_id)

    # If worktree already exists, return existing info
    if wt_path.exists() and (wt_path / ".git").exists():
        log.info("Worktree already exists: %s", wt_path)
        return get_worktree_status(task_gid, repo_id)

    # Ensure base directory exists
    wt_path.parent.mkdir(parents=True, exist_ok=True)

    # Fetch latest from remote
    fetch = _run_git(["fetch", "origin"], cwd=repo_path)
    if fetch.returncode != 0:
        log.warning("Fetch failed (continuing): %s", fetch.stderr)

    result = None

    if base_branch:
        # Continue from an existing branch — check it out directly as the worktree
        # First try remote version, then local
        remote_ref = f"origin/{base_branch}"
        ref_check = _run_git(["rev-parse", "--verify", remote_ref], cwd=repo_path)
        if ref_check.returncode == 0:
            # Remote branch exists — create worktree tracking it
            branch_name = base_branch
            local_check = _run_git(["rev-parse", "--verify", branch_name], cwd=repo_path)
            if local_check.returncode == 0:
                result = _run_git(["worktree", "add", str(wt_path), branch_name], cwd=repo_path)
            else:
                result = _run_git(
                    ["worktree", "add", "-b", branch_name, str(wt_path), remote_ref],
                    cwd=repo_path,
                )
        else:
            # Try as local branch
            local_check = _run_git(["rev-parse", "--verify", base_branch], cwd=repo_path)
            if local_check.returncode == 0:
                branch_name = base_branch
                result = _run_git(["worktree", "add", str(wt_path), branch_name], cwd=repo_path)
            else:
                # Branch gone — fall back to fresh branch
                log.warning("Branch '%s' not found — creating fresh branch instead", base_branch)

    if result is None:
        # Fresh branch from default_branch
        branch_name = f"feature/{task_gid}/{branch_slug}"
        branch_check = _run_git(["rev-parse", "--verify", branch_name], cwd=repo_path)
        if branch_check.returncode == 0:
            # Branch exists, create worktree from it
            result = _run_git(["worktree", "add", str(wt_path), branch_name], cwd=repo_path)
        else:
            # Create new branch from origin/default_branch
            base_ref = f"origin/{default_branch}"
            ref_check = _run_git(["rev-parse", "--verify", base_ref], cwd=repo_path)
            if ref_check.returncode != 0:
                base_ref = default_branch
            result = _run_git(
                ["worktree", "add", "-b", branch_name, str(wt_path), base_ref],
                cwd=repo_path,
            )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to create worktree: {result.stderr}")

    # Unset upstream so `git push` doesn't target master.
    # The branch was created from origin/master and inherits its tracking.
    _run_git(["branch", "--unset-upstream", branch_name], cwd=str(wt_path))

    log.info("Created worktree: %s (branch: %s)", wt_path, branch_name)
    return {
        "path": str(wt_path),
        "branch": branch_name,
        "repo_id": repo_id,
        "task_gid": task_gid,
        "created": datetime.now(timezone.utc).isoformat(),
        "status": "created",
    }


def delete_worktree(task_gid: str, repo_id: str, delete_branch: bool = True) -> bool:
    """Remove a worktree and optionally its local branch."""
    repo = get_repo(repo_id)
    if not repo:
        return False

    wt_path = get_worktree_path(task_gid, repo_id)
    repo_path = repo["path"]

    if not wt_path.exists():
        return False

    # Get branch name before removing
    branch_name = None
    if delete_branch:
        branch_result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=str(wt_path))
        if branch_result.returncode == 0:
            branch_name = branch_result.stdout.strip()

    # Remove worktree
    result = _run_git(["worktree", "remove", str(wt_path), "--force"], cwd=repo_path)
    if result.returncode != 0:
        # Fallback: manual removal
        shutil.rmtree(wt_path, ignore_errors=True)
        _run_git(["worktree", "prune"], cwd=repo_path)

    # Delete local branch
    if delete_branch and branch_name and branch_name.startswith("feature/"):
        _run_git(["branch", "-D", branch_name], cwd=repo_path)

    # Cleanup empty parent dirs
    task_dir = WORKTREE_BASE / task_gid
    if task_dir.exists() and not any(task_dir.iterdir()):
        task_dir.rmdir()

    log.info("Deleted worktree: %s", wt_path)
    return True


def get_worktree_status(task_gid: str, repo_id: str) -> Optional[dict]:
    """Get status of a worktree: branch, changed files, last commit."""
    wt_path = get_worktree_path(task_gid, repo_id)
    if not wt_path.exists():
        return None

    cwd = str(wt_path)

    # Branch
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
    branch_name = branch.stdout.strip() if branch.returncode == 0 else "unknown"

    # Changed files
    status = _run_git(["status", "--porcelain"], cwd=cwd)
    changed_files = []
    if status.returncode == 0 and status.stdout.strip():
        for line in status.stdout.strip().splitlines():
            changed_files.append(line.strip())

    # Diff stats (committed changes vs base)
    diff = _run_git(["diff", "--stat", "HEAD~1"], cwd=cwd)
    diff_summary = diff.stdout.strip() if diff.returncode == 0 else ""

    # Last commit
    log_result = _run_git(["log", "-1", "--format=%H|%s|%ai"], cwd=cwd)
    last_commit = None
    if log_result.returncode == 0 and log_result.stdout.strip():
        parts = log_result.stdout.strip().split("|", 2)
        if len(parts) == 3:
            last_commit = {"sha": parts[0][:8], "message": parts[1], "date": parts[2]}

    # Commit count on this branch (vs default)
    repo = get_repo(repo_id)
    default_branch = repo.get("default_branch", "master") if repo else "master"
    count_result = _run_git(["rev-list", "--count", f"{default_branch}..HEAD"], cwd=cwd)
    commit_count = int(count_result.stdout.strip()) if count_result.returncode == 0 else 0

    return {
        "path": str(wt_path),
        "branch": branch_name,
        "repo_id": repo_id,
        "task_gid": task_gid,
        "changed_files": changed_files,
        "uncommitted_count": len(changed_files),
        "commit_count": commit_count,
        "last_commit": last_commit,
        "status": "active",
    }


def list_worktrees(task_gid: str = None) -> list[dict]:
    """List all active worktrees, optionally filtered by task."""
    results = []
    if not WORKTREE_BASE.exists():
        return results

    if task_gid:
        task_dir = WORKTREE_BASE / task_gid
        if task_dir.exists():
            for repo_dir in task_dir.iterdir():
                if repo_dir.is_dir():
                    status = get_worktree_status(task_gid, repo_dir.name)
                    if status:
                        results.append(status)
    else:
        for task_dir in WORKTREE_BASE.iterdir():
            if task_dir.is_dir():
                for repo_dir in task_dir.iterdir():
                    if repo_dir.is_dir():
                        status = get_worktree_status(task_dir.name, repo_dir.name)
                        if status:
                            results.append(status)

    return results


def cleanup_stale_worktrees(max_age_days: int = STALE_DAYS) -> list[str]:
    """Remove worktrees older than max_age_days. Returns list of removed paths."""
    if not WORKTREE_BASE.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    removed = []

    for task_dir in WORKTREE_BASE.iterdir():
        if not task_dir.is_dir():
            continue
        for repo_dir in task_dir.iterdir():
            if not repo_dir.is_dir():
                continue
            # Check last modification time
            try:
                mtime = datetime.fromtimestamp(repo_dir.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    delete_worktree(task_dir.name, repo_dir.name)
                    removed.append(str(repo_dir))
            except OSError:
                continue

    return removed
