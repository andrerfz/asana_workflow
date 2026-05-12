"""Coding phase — implement approved plan in worktree."""
import logging
import subprocess

from ..phases import AgentPhase
from ..claude_client import _run_claude_cli
from ..state import (
    BASH_BLOCKLIST, CODING_TEST_BLOCK,
    add_log, update_phase, load_agent_run, save_agent_run,
    add_conversation_message, _accumulate_cost, _check_secrets,
)
from ...services.repo_manager import get_repo
from ...services.worktree_manager import get_worktree_status
from .timer import agent_timers

log = logging.getLogger(__name__)


async def agent_code(task_gid: str, context: str, run: dict, repo_entry: dict) -> bool:
    """Run the coding phase for a single repo."""
    try:
        wt_path = repo_entry["worktree_path"]
        plan = run.get("plan", "")

        repo = get_repo(repo_entry["id"])
        docker_hint = ""
        if repo and repo.get("test_docker_cmd"):
            docker_hint = (
                f" This project uses Docker containers. You can run commands inside the project's "
                f"containers using `docker compose exec`. For example: `{repo['test_docker_cmd']}`. "
                f"The docker-compose.yml is at the project root: {repo['path']}."
            )
        test_hint = ""
        if repo and repo.get("test_description"):
            test_hint = f" TESTING: {repo['test_description']}"

        task_url = f"https://app.asana.com/0/0/{task_gid}"
        system = (
            "You are a senior developer implementing changes. "
            "Follow the approved plan exactly. Write clean, production-quality code. "
            f"{BASH_BLOCKLIST} "
            f"{CODING_TEST_BLOCK} "
            f"IMPORTANT: Work ONLY in the current working directory (worktree). "
            f"Do NOT cd or navigate to any other directory. All file paths are relative to cwd. "
            f"NEVER run git merge, git rebase, git pull, or git checkout of other branches. "
            f"Branch references or MR links in the task are historical context — that work is already in your branch. "
            f"Commit your changes when done.{docker_hint}{test_hint} "
            f"IMPLEMENTATION BUDGET: You have 30 turns. The investigation is already done — do NOT re-read the "
            f"entire codebase. The plan tells you exactly which files to change. Open only those files, make the "
            f"changes, and commit. If you spend more than 5 turns reading without writing any code, you will run "
            f"out of turns and produce zero commits. START WRITING CODE IN YOUR FIRST 3 TURNS."
        )

        commit_instructions = (
            f"## COMMIT RULES (MANDATORY)\n"
            f"When committing, you MUST follow these rules exactly:\n"
            f"1. Use git conventional commit format: feat:, fix:, refactor:, etc.\n"
            f"2. Do NOT include Co-Authored-By or any author lines.\n"
            f"3. ALWAYS append these exact two lines at the END of the commit message body:\n"
            f"```\n"
            f"Ref.: {task_url}\n"
            f"Related issue: {task_gid}\n"
            f"```\n"
            f"Example:\n"
            f"```\n"
            f"fix: correct rounding precision in price calculation\n\n"
            f"Ref.: {task_url}\n"
            f"Related issue: {task_gid}\n"
            f"```\n"
        )

        # Re-read plan from disk to ensure we have the latest version (after revisions)
        latest_run = load_agent_run(task_gid)
        if latest_run and latest_run.get("plan"):
            plan = latest_run["plan"]

        prompt = (
            f"{context}\n\n## Approved Plan\n{plan}\n\n{commit_instructions}\n\n"
            f"## ACTION REQUIRED\n"
            f"The investigation is complete. The plan above tells you exactly what to change.\n"
            f"DO NOT re-read the entire codebase. Open the specific files from the plan, make the changes, commit.\n"
            f"Your first tool call must be Write or Edit — not Read or Grep.\n"
            f"If you need to verify a single detail, one Read is acceptable. Then write code immediately.\n"
            f"Produce at least one commit before this session ends."
        )

        add_log(task_gid, f"[{repo_entry['id']}] Claude Code starting (plan: {plan[:80]}...)")

        timer = agent_timers.get(task_gid)
        # Cap coding at 25 min — enough for real work, prevents silent rate-limit stalls
        # from consuming the full 45-min agent budget with no output
        subprocess_timeout = min(1500.0, timer.remaining if timer else 1500.0)

        result = await _run_claude_cli(
            prompt=prompt,
            cwd=wt_path,
            max_turns=30,
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Skill(db-query)"],
            system_prompt=system,
            task_gid=task_gid,
            subprocess_timeout=subprocess_timeout,
        )

        try:
            _accumulate_cost(task_gid, result)
        except Exception as e:
            log.warning(f"Failed to accumulate cost for coding: {e}")

        # Persist session_id for guide/resume capability
        if result.get("session_id"):
            run = load_agent_run(task_gid)
            if run:
                run["claude_session_id"] = result["session_id"]
                save_agent_run(task_gid, run)

        # Check for pending guide feedback (user sent guidance while coding)
        while True:
            run = load_agent_run(task_gid)
            pending_guide = run.pop("pending_guide", None) if run else None
            if not pending_guide or not pending_guide.get("session_id"):
                break
            add_log(task_gid, f"[{repo_entry['id']}] Resuming session with user guidance...")
            save_agent_run(task_gid, run)  # persist the pop
            timer = agent_timers.get(task_gid)
            guide_timeout = min(1500.0, timer.remaining if timer else 1500.0)
            guide_result = await _run_claude_cli(
                prompt=pending_guide["feedback"],
                cwd=wt_path,
                max_turns=30,
                allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Skill(db-query)"],
                system_prompt=system,
                task_gid=task_gid,
                resume_session_id=pending_guide["session_id"],
                subprocess_timeout=guide_timeout,
            )
            try:
                _accumulate_cost(task_gid, guide_result)
            except Exception as e:
                log.warning(f"Failed to accumulate guide cost: {e}")
            # Update session_id from resumed session
            if guide_result.get("session_id"):
                run = load_agent_run(task_gid)
                if run:
                    run["claude_session_id"] = guide_result["session_id"]
                    save_agent_run(task_gid, run)
            # Save agent response to conversation
            agent_response = guide_result.get("text", "").strip()
            if agent_response:
                add_conversation_message(task_gid, "agent", agent_response)
            result = guide_result  # use the latest result for success/failure check

        add_log(task_gid, f"[{repo_entry['id']}] Claude Code finished (exit {result['returncode']})")

        if result.get("timed_out"):
            timer = agent_timers.get(task_gid)
            mins = timer.elapsed_minutes if timer else "?"
            last_text = (result.get("text") or "")[:200]
            detail = f" Last output: {last_text}" if last_text else " (no output — likely rate-limit stall)"
            add_log(task_gid, f"[{repo_entry['id']}] Coding timed out (25 min cap).{detail}", "error")
            update_phase(task_gid, AgentPhase.ERROR, error=f"Coding timed out (25 min cap).{detail}")
            return False

        if result["returncode"] != 0:
            error = result.get("stderr", "") or result.get("text", "Unknown error")
            # Ignore non-zero exit from guided termination (process was killed)
            run = load_agent_run(task_gid)
            if run and run.get("pending_guide"):
                pass
            else:
                add_log(task_gid, f"[{repo_entry['id']}] Coding failed (exit {result['returncode']}): {error[:500]}", "error")
                update_phase(task_gid, AgentPhase.ERROR, error=f"Claude Code error: {error[:200]}")
                return False

        auto_commit_if_dirty(wt_path, repo_entry["id"], task_gid)

        wt_status = get_worktree_status(task_gid, repo_entry["id"])
        if wt_status:
            repo_entry["commits"] = wt_status.get("commit_count", 0)

        # Safety checks: max files changed limit
        try:
            diff_stat = subprocess.run(
                ["git", "diff", "--stat", "--name-only", "HEAD~1..HEAD"],
                cwd=wt_path, capture_output=True, text=True, timeout=10,
            )
            if diff_stat.returncode == 0:
                changed_files = [f for f in diff_stat.stdout.strip().split("\n") if f.strip()]
                max_files = 20
                if len(changed_files) > max_files:
                    add_log(task_gid, f"[{repo_entry['id']}] Warning: {len(changed_files)} files changed (limit: {max_files})", "warning")
        except Exception:
            pass

        _check_secrets(wt_path, task_gid, repo_entry["id"])

        if repo_entry["commits"] == 0:
            add_log(task_gid, f"[{repo_entry['id']}] Warning: coding phase produced 0 commits", "warning")
            cli_text = result.get("text", "")[:500]
            if cli_text:
                add_log(task_gid, f"[{repo_entry['id']}] CLI output: {cli_text}", "info")

            # Auto-resume once if rate limit hit or agent ran out of turns without committing
            session_id = result.get("session_id")
            if session_id and not result.get("_resumed_once"):
                add_log(task_gid, f"[{repo_entry['id']}] 0 commits — auto-resuming session to force implementation", "warning")
                timer = agent_timers.get(task_gid)
                resume_result = await _run_claude_cli(
                    prompt=(
                        "You did not write any code or make any commits in the previous session. "
                        "The investigation is complete. You know which files to change. "
                        "Open the specific files from the plan RIGHT NOW and write the implementation. "
                        "Do NOT read any more files. Write the code, then commit it. "
                        "This is your final chance — produce at least one commit."
                    ),
                    cwd=wt_path,
                    max_turns=20,
                    allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Skill(db-query)"],
                    system_prompt=system,
                    task_gid=task_gid,
                    resume_session_id=session_id,
                    subprocess_timeout=min(900.0, timer.remaining if timer else 900.0),  # 15 min for auto-resume
                )
                resume_result["_resumed_once"] = True
                try:
                    _accumulate_cost(task_gid, resume_result)
                except Exception:
                    pass
                auto_commit_if_dirty(wt_path, repo_entry["id"], task_gid)
                wt_status = get_worktree_status(task_gid, repo_entry["id"])
                if wt_status:
                    repo_entry["commits"] = wt_status.get("commit_count", 0)
                if repo_entry["commits"] > 0:
                    add_log(task_gid, f"[{repo_entry['id']}] Auto-resume produced {repo_entry['commits']} commits")
                else:
                    add_log(task_gid, f"[{repo_entry['id']}] Auto-resume still produced 0 commits", "warning")

        add_log(task_gid, f"[{repo_entry['id']}] Coding complete ({repo_entry['commits']} commits)")
        return True

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        add_log(task_gid, f"[{repo_entry['id']}] Coding failed: {e} | {tb.splitlines()[-3] if tb else ''}", "error")
        log.exception("Coding phase error for task %s repo %s", task_gid, repo_entry.get('id'))
        update_phase(task_gid, AgentPhase.ERROR, error=str(e))
        return False


def auto_commit_if_dirty(wt_path: str, repo_id: str, task_gid: str):
    """Safety net: if Claude Code left uncommitted changes, commit them."""
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=wt_path,
            capture_output=True, text=True, timeout=10,
        )
        if status.returncode == 0 and status.stdout.strip():
            subprocess.run(["git", "add", "-u"], cwd=wt_path, capture_output=True, timeout=10)
            diff_check = subprocess.run(
                ["git", "diff", "--cached", "--quiet"], cwd=wt_path,
                capture_output=True, timeout=10,
            )
            if diff_check.returncode != 0:
                add_log(task_gid, f"[{repo_id}] Found uncommitted changes, auto-committing...", "warning")
                subprocess.run(
                    ["git", "commit", "-m", "chore: auto-commit uncommitted agent changes"],
                    cwd=wt_path, capture_output=True, timeout=10,
                )
    except Exception as e:
        add_log(task_gid, f"[{repo_id}] Auto-commit check failed: {e}", "warning")
