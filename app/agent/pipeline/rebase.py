"""Rebase phase — fetch latest default branch and rebase onto it."""
import logging
import subprocess

from ..phases import AgentPhase
from ..claude_client import _run_claude_cli, get_best_model
from ..state import BASH_BLOCKLIST, add_log, update_phase, _accumulate_cost
from ..asana_helpers import _post_asana_comment
from ...services.repo_manager import get_repo

log = logging.getLogger(__name__)


async def rebase_from_default(task_gid: str, repo_entry: dict) -> bool:
    """Fetch latest default branch and rebase onto it."""
    repo = get_repo(repo_entry["id"])
    if not repo:
        return True

    wt_path = repo_entry["worktree_path"]
    default_branch = repo.get("default_branch", "master")
    repo_id = repo_entry["id"]

    add_log(task_gid, f"[{repo_id}] Rebasing onto latest {default_branch}...")

    try:
        fetch = subprocess.run(
            ["git", "fetch", "origin", default_branch],
            cwd=wt_path, capture_output=True, text=True, timeout=30,
        )
        if fetch.returncode != 0:
            add_log(task_gid, f"[{repo_id}] Fetch failed: {fetch.stderr[:200]}", "warning")
            return True

        rebase = subprocess.run(
            ["git", "rebase", f"origin/{default_branch}"],
            cwd=wt_path, capture_output=True, text=True, timeout=60,
        )

        if rebase.returncode == 0:
            add_log(task_gid, f"[{repo_id}] Rebase successful — branch is up to date with {default_branch}")
            return True

        conflict_output = (rebase.stdout + rebase.stderr)[-1500:]
        add_log(task_gid, f"[{repo_id}] Rebase conflicts detected", "warning")

        subprocess.run(
            ["git", "rebase", "--abort"],
            cwd=wt_path, capture_output=True, text=True, timeout=10,
        )

        add_log(task_gid, f"[{repo_id}] Attempting auto-resolve via Claude Code...")
        fix_result = await _run_claude_cli(
            prompt=(
                f"A git rebase onto origin/{default_branch} failed with conflicts.\n"
                f"Run `git rebase origin/{default_branch}`, resolve ALL conflicts, "
                f"then `git add` the resolved files and `git rebase --continue`.\n"
                f"Conflict output:\n{conflict_output[:1000]}\n\n"
                f"Resolve conflicts preserving the intent of our feature branch changes."
            ),
            cwd=wt_path,
            max_turns=15,
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
            system_prompt=(
                "You are resolving git rebase conflicts. Keep our feature branch changes "
                "where they don't contradict upstream. For real conflicts, prefer our changes "
                "but ensure correctness. "
                f"{BASH_BLOCKLIST}"
            ),
            task_gid=task_gid,
            model=get_best_model(),
        )

        try:
            _accumulate_cost(task_gid, fix_result)
        except Exception as e:
            log.warning(f"Failed to accumulate cost for rebase auto-resolve: {e}")

        if fix_result["returncode"] == 0:
            add_log(task_gid, f"[{repo_id}] Rebase conflicts auto-resolved")
            return True

        add_log(task_gid, f"[{repo_id}] Could not auto-resolve rebase conflicts", "error")
        update_phase(task_gid, AgentPhase.ERROR,
                     error=f"Rebase conflicts on {repo_id} — resolve manually in worktree")
        await _post_asana_comment(
            task_gid,
            f"🤖 Rebase conflicts detected on {repo_id}.\n\n"
            f"Branch could not be auto-rebased onto {default_branch}.\n"
            f"Please resolve manually in the worktree:\n`{wt_path}`",
            dedup_prefix=f"🤖 Rebase conflicts detected on {repo_id}."
        )
        return False

    except subprocess.TimeoutExpired:
        add_log(task_gid, f"[{repo_id}] Rebase timed out", "warning")
        return True
    except Exception as e:
        add_log(task_gid, f"[{repo_id}] Rebase error: {e}", "warning")
        return True
