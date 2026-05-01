"""Finalizing phase — auto-cleanup after QA approval.

Runs automatically with no human interaction:
- Squash/rewrite commits to conventional format
- Run lint auto-fix if configured
- Remove TODOs/FIXMEs introduced by the agent
- Push branch to remote
"""
import logging
import re
import subprocess

from ..phases import AgentPhase
from ..claude_client import _run_claude_cli
from ..state import (
    BASH_BLOCKLIST, add_log, update_phase, load_agent_run, save_agent_run,
    _accumulate_cost, _broadcast_state,
)
from ...services.repo_manager import get_repo
from ...services.worktree_manager import get_worktree_status

log = logging.getLogger(__name__)


async def agent_finalize(task_gid: str, run: dict) -> bool:
    """Run the finalizing phase — auto-cleanup after QA approval.

    Returns True if finalization succeeded (or had nothing to do).
    """
    update_phase(task_gid, AgentPhase.FINALIZING)
    await _broadcast_state(task_gid)
    add_log(task_gid, "Finalizing: auto-cleanup before delivery...")

    for repo_entry in run.get("repos", []):
        wt_path = repo_entry.get("worktree_path")
        if not wt_path:
            continue

        repo = get_repo(repo_entry["id"])
        repo_id = repo_entry["id"]
        default_branch = repo.get("default_branch", "master") if repo else "master"

        # 1. Count commits on branch
        commit_count = _count_branch_commits(wt_path, default_branch)
        if commit_count == 0:
            add_log(task_gid, f"[{repo_id}] No commits to finalize")
            continue

        # 2. Check what needs fixing
        needs_squash = commit_count > 1
        bad_commits = _check_conventional_commits(wt_path, default_branch)
        has_lint = bool(repo and repo.get("lint_cmd"))

        if not needs_squash and not bad_commits and not has_lint:
            add_log(task_gid, f"[{repo_id}] Already clean — skipping finalize")
            continue

        # 3. Run Claude to squash + reformat commits + lint fix
        issues = []
        if needs_squash:
            issues.append(f"- Squash {commit_count} commits into 1 clean conventional commit")
        if bad_commits:
            issues.append(f"- {len(bad_commits)} commits have non-conventional messages: {', '.join(bad_commits[:5])}")
        if has_lint:
            issues.append(f"- Run lint fix: `{repo['lint_cmd']}`")

        task_url = f"https://app.asana.com/0/0/{task_gid}"
        task_name = run.get("task_name", task_gid)

        prompt = (
            f"## Final Cleanup\n\n"
            f"The code has been approved by QA. Now clean up before delivery:\n\n"
            + "\n".join(issues) + "\n\n"
            f"### Commit Rules\n"
            f"After squashing, the SINGLE final commit must:\n"
            f"1. Use conventional format: feat:, fix:, refactor:, etc.\n"
            f"2. Summarize ALL changes in one clear message based on the task: {task_name}\n"
            f"3. End with:\n"
            f"```\n"
            f"Ref.: {task_url}\n"
            f"Related issue: {task_gid}\n"
            f"```\n\n"
            f"### Steps\n"
            f"1. {'Run lint auto-fix if applicable' if has_lint else 'Skip lint'}\n"
            f"2. Soft-reset all commits: `git reset --soft origin/{default_branch}`\n"
            f"3. Stage all changes: `git add -A`\n"
            f"4. Create ONE conventional commit with the proper message\n"
            f"5. Verify with `git log --oneline -5`\n\n"
            f"Do NOT modify any code logic. Only reformat commits and run lint."
        )

        add_log(task_gid, f"[{repo_id}] Finalizing ({', '.join(issues)})...")

        result = await _run_claude_cli(
            prompt=prompt,
            cwd=wt_path,
            max_turns=10,
            allowed_tools=["Bash", "Read", "Glob"],
            system_prompt=(
                "You are finalizing a branch for delivery. Your ONLY job is to: "
                "squash commits into one clean conventional commit, run lint fix if asked, "
                "and verify the result. Do NOT change any code logic. Do NOT modify files "
                "beyond what lint auto-fix does. "
                f"{BASH_BLOCKLIST}"
            ),
            task_gid=task_gid,
        )

        try:
            _accumulate_cost(task_gid, result)
        except Exception as e:
            log.warning(f"Failed to accumulate finalize cost: {e}")

        if result["returncode"] != 0:
            error = result.get("stderr", "") or result.get("text", "")
            add_log(task_gid, f"[{repo_id}] Finalize failed (exit {result['returncode']}): {error[:300]}", "warning")
            # Non-fatal — continue with delivery even if finalize fails
            add_log(task_gid, f"[{repo_id}] Proceeding with delivery despite finalize failure")
            continue

        # Update commit count after squash
        wt_status = get_worktree_status(task_gid, repo_id)
        if wt_status:
            repo_entry["commits"] = wt_status.get("commit_count", 0)

        # Verify conventional commit
        final_bad = _check_conventional_commits(wt_path, default_branch)
        if final_bad:
            add_log(task_gid, f"[{repo_id}] Warning: commits still non-conventional after finalize", "warning")
        else:
            add_log(task_gid, f"[{repo_id}] Finalized: {repo_entry.get('commits', '?')} commit(s), conventional format")

    save_agent_run(task_gid, run)

    # Push all branches to remote
    for repo_entry in run.get("repos", []):
        wt_path = repo_entry.get("worktree_path")
        branch = repo_entry.get("branch")
        if not wt_path or not branch:
            continue
        repo_id = repo_entry["id"]
        try:
            push = subprocess.run(
                ["git", "push", "--force-with-lease", "-u", "origin", branch],
                cwd=wt_path, capture_output=True, text=True, timeout=60,
            )
            if push.returncode == 0:
                add_log(task_gid, f"[{repo_id}] Pushed branch {branch}")
                # Parse MR/PR URL from push output (GitLab/GitHub remote hints)
                combined = (push.stdout or "") + (push.stderr or "")
                if combined.strip():
                    log.debug("[%s] Push remote output: %s", repo_id, combined[:500])
                mr_match = re.search(r'https?://\S+(?:merge_requests|pull/new|pulls/new)\S*', combined)
                if mr_match:
                    repo_entry["mr_url"] = mr_match.group(0).rstrip(".")
                    add_log(task_gid, f"[{repo_id}] MR/PR link: {repo_entry['mr_url']}")
                else:
                    log.debug("[%s] No MR/PR URL found in push output", repo_id)
            else:
                add_log(task_gid, f"[{repo_id}] Push failed: {push.stderr[:200]}", "warning")
        except Exception as e:
            add_log(task_gid, f"[{repo_id}] Push error: {e}", "warning")

    # Persist mr_url fields set during push
    save_agent_run(task_gid, run)
    add_log(task_gid, "Finalization complete")
    return True


def _count_branch_commits(wt_path: str, default_branch: str) -> int:
    """Count commits on branch ahead of default branch."""
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"origin/{default_branch}..HEAD"],
            cwd=wt_path, capture_output=True, text=True, timeout=10,
        )
        return int(result.stdout.strip()) if result.returncode == 0 else 0
    except Exception:
        return 0


def _check_conventional_commits(wt_path: str, default_branch: str) -> list[str]:
    """Return list of non-conventional commit messages on branch."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"origin/{default_branch}..HEAD"],
            cwd=wt_path, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []
        prefixes = ("feat:", "fix:", "chore:", "refactor:", "docs:", "test:", "style:", "perf:", "ci:", "build:")
        bad = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            msg = line.split(" ", 1)[1] if " " in line else line
            if not any(msg.lower().startswith(p) for p in prefixes):
                bad.append(msg[:60])
        return bad
    except Exception:
        return []
