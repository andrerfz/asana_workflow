"""Agent execution engine — start, stop, plan, code, test, QA, and manual flows."""
import asyncio
import json
import logging
import re as _re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .phases import AgentPhase
from .state import (
    AGENT_RUNS_DIR, BASH_BLOCKLIST, TOKEN_PRICING,
    _active_workers, _broadcast_state, _accumulate_cost,
    load_agent_run, save_agent_run, create_agent_run,
    add_log, update_phase, clear_agent_run,
    get_agent_status, list_active_agents, get_worktree_diff,
    load_run_history, load_agent_settings, save_agent_settings,
    _check_secrets, _sync_agent_files,
    register_event_callback,
)
from .claude_client import check_claude_code_status, _run_claude_cli, kill_active_claude
from .asana_helpers import (
    _move_task_section, _post_asana_comment, _auto_complete_subtasks,
    _fetch_subtasks_context, _get_branch_state, _fetch_task_comments,
    _qa_verdict_is_pass, _build_fix_instructions,
)
from .stream_parser import extract_text_from_stream, detect_infra_error
from .queue import agent_queue
from ..services.repo_manager import get_repo, get_repos_for_task, list_repos
from ..services.worktree_manager import create_worktree, get_worktree_status
from ..services.asana_client import fetch_subtasks
from .memory import get_memory_context, update_memory_after_run

log = logging.getLogger(__name__)


# ─── Work Timer (pauses during human waits) ───

import time as _time

_agent_timers: dict[str, "_AgentTimer"] = {}


class _AgentTimer:
    """Tracks active work time, excluding pauses for human input."""

    def __init__(self, budget_seconds: float):
        self.budget = budget_seconds
        self.elapsed = 0.0
        self._started_at: Optional[float] = _time.monotonic()

    def pause(self):
        """Pause the timer (entering human-wait phase)."""
        if self._started_at is not None:
            self.elapsed += _time.monotonic() - self._started_at
            self._started_at = None

    def resume(self):
        """Resume the timer (exiting human-wait phase)."""
        if self._started_at is None:
            self._started_at = _time.monotonic()

    @property
    def remaining(self) -> float:
        """Seconds of work budget remaining."""
        current = self.elapsed
        if self._started_at is not None:
            current += _time.monotonic() - self._started_at
        return max(0, self.budget - current)

    @property
    def exceeded(self) -> bool:
        return self.remaining <= 0

    @property
    def elapsed_minutes(self) -> int:
        current = self.elapsed
        if self._started_at is not None:
            current += _time.monotonic() - self._started_at
        return int(current / 60)


def _check_timeout(task_gid: str) -> bool:
    """Check if the agent has exceeded its work-time budget. Returns True if timed out."""
    timer = _agent_timers.get(task_gid)
    if timer and timer.exceeded:
        mins = timer.elapsed_minutes
        update_phase(task_gid, AgentPhase.ERROR, error=f"Agent work-time timeout ({mins} minutes of active work)")
        add_log(task_gid, f"Agent timeout exceeded ({mins} min active work)", "error")
        return True
    return False


# ─── Start / Stop / Answer ───

async def start_agent(task_gid: str, task: dict, branch_slug: str,
                      base_branch: str = None) -> dict:
    """Start an agent worker for a task."""
    if task_gid in _active_workers and not _active_workers[task_gid].done():
        raise ValueError(f"Agent already running for task {task_gid}")

    # Claim the slot immediately to prevent duplicate starts across await points
    _sentinel = asyncio.get_event_loop().create_future()
    _active_workers[task_gid] = _sentinel

    try:
        cli_status = check_claude_code_status()
        if not cli_status["available"]:
            raise ValueError(cli_status["error"])
        if not cli_status["authenticated"]:
            raise ValueError("Claude Code not authenticated. Run 'claude login' on your Mac, then restart the container.")

        repos = get_repos_for_task(task)
        if not repos:
            raise ValueError("No repos configured for this task area. Add repos in Settings → Repositories.")

        # Check if queue is full — if so, enqueue instead of starting immediately
        if agent_queue.running_count >= agent_queue.config["max_parallel"]:
            priority = task.get("priority", 3)
            agent_queue.enqueue(task_gid, priority, task, branch_slug, base_branch)
            run = create_agent_run(task_gid, task.get("name", ""), repos)
            run["phase"] = "queued"
            save_agent_run(task_gid, run)
            await _broadcast_state(task_gid)
            _active_workers.pop(task_gid, None)
            return load_agent_run(task_gid)

        # Create run state
        run = create_agent_run(task_gid, task.get("name", ""), repos)

        # Create worktrees
        update_phase(task_gid, AgentPhase.INIT)
        await _broadcast_state(task_gid)
        for repo_entry in run["repos"]:
            try:
                wt = create_worktree(task_gid, repo_entry["id"], branch_slug, base_branch=base_branch)
                repo_entry["worktree_path"] = wt["path"]
                repo_entry["branch"] = wt["branch"]
                repo_entry["status"] = "ready"
                add_log(task_gid, f"Worktree created: {wt['path']} (branch: {wt['branch']})")

                repo = get_repo(repo_entry["id"])
                if repo:
                    _sync_agent_files(repo["path"], wt["path"], repo_entry["id"], task_gid)
            except Exception as e:
                repo_entry["status"] = "error"
                add_log(task_gid, f"Failed to create worktree for {repo_entry['id']}: {e}", "error")
                update_phase(task_gid, AgentPhase.ERROR, error=str(e))
                _active_workers.pop(task_gid, None)
                return load_agent_run(task_gid)

        save_agent_run(task_gid, run)

        # Launch background worker with timeout enforcement
        # Timeout only counts active work (planning, coding, testing, QA) — not human wait time
        settings = load_agent_settings()
        timeout_minutes = settings.get("agent_timeout_minutes", 45)
        _agent_timers[task_gid] = _AgentTimer(timeout_minutes * 60)

        async def run_with_timeout():
            try:
                return await _run_agent(task_gid, task)
            finally:
                _agent_timers.pop(task_gid, None)

        worker = asyncio.create_task(run_with_timeout())
        _active_workers[task_gid] = worker  # replace sentinel with actual worker
        agent_queue.register_running(task_gid, worker)
        return load_agent_run(task_gid)
    except Exception:
        _active_workers.pop(task_gid, None)
        raise


async def resume_agent(task_gid: str, task: dict, feedback: str) -> dict:
    """Resume a done/error agent with user feedback, reusing existing worktrees.

    Skips investigation and planning — jumps straight to coding with the
    user's feedback injected as context alongside the previous run's plan
    and investigation.
    """
    if task_gid in _active_workers and not _active_workers[task_gid].done():
        raise ValueError(f"Agent already running for task {task_gid}")

    prev_run = load_agent_run(task_gid)
    if not prev_run:
        raise ValueError("No previous agent run to resume")
    if prev_run["phase"] not in (AgentPhase.DONE.value, AgentPhase.ERROR.value, AgentPhase.CANCELLED.value):
        raise ValueError(f"Can only resume from done/error/cancelled, current phase: {prev_run['phase']}")

    # Validate worktrees still exist
    valid_repos = []
    for repo_entry in prev_run.get("repos", []):
        wt = repo_entry.get("worktree_path")
        if wt and Path(wt).exists():
            valid_repos.append(repo_entry)
    if not valid_repos:
        raise ValueError("No valid worktrees remain — use Start Agent instead")

    # Check if previous investigation flagged additional repos that were never created
    prev_investigation = prev_run.get("investigation", "")
    if prev_investigation:
        missing_repos = _parse_additional_repos(prev_investigation, {"repos": valid_repos})
        if missing_repos:
            # Extract branch slug from existing worktree
            existing_branch = next((r.get("branch", "") for r in valid_repos if r.get("branch")), "")
            slug_parts = existing_branch.split("/")
            slug = slug_parts[-1] if len(slug_parts) >= 3 else "work"
            log.info("Resume: creating worktrees for previously identified repos: %s", missing_repos)
            for repo_id in missing_repos:
                try:
                    wt = create_worktree(task_gid, repo_id, slug)
                    new_entry = {"id": repo_id, "status": "coding", "commits": 0,
                                 "worktree_path": wt["path"], "branch": wt["branch"]}
                    valid_repos.append(new_entry)
                    repo = get_repo(repo_id)
                    if repo:
                        _sync_agent_files(repo["path"], wt["path"], repo_id, task_gid)
                    log.info("Resume: created worktree for %s at %s", repo_id, wt["path"])
                except Exception as e:
                    log.warning("Failed to create worktree for missing repo %s on resume: %s", repo_id, e)

    # Claim slot
    _sentinel = asyncio.get_event_loop().create_future()
    _active_workers[task_gid] = _sentinel

    try:
        cli_status = check_claude_code_status()
        if not cli_status["available"]:
            raise ValueError(cli_status["error"])

        # Preserve previous context
        prev_plan = prev_run.get("plan", "")
        prev_error = prev_run.get("error", "")

        # Reset the run state for a new cycle, keeping repos/worktrees
        for repo_entry in valid_repos:
            repo_entry["status"] = "coding"
        prev_run["phase"] = AgentPhase.CODING.value
        prev_run["is_active"] = True
        prev_run["error"] = None
        prev_run["qa_report"] = None
        prev_run["question"] = None
        prev_run["completed_at"] = None
        prev_run["resume_feedback"] = feedback
        prev_run["repos"] = valid_repos
        save_agent_run(task_gid, prev_run)
        update_phase(task_gid, AgentPhase.CODING)
        await _broadcast_state(task_gid)
        add_log(task_gid, f"Resuming with feedback: {feedback[:200]}")

        # Set up timeout
        settings = load_agent_settings()
        timeout_minutes = settings.get("agent_timeout_minutes", 45)
        _agent_timers[task_gid] = _AgentTimer(timeout_minutes * 60)

        async def run_resumed():
            try:
                return await _run_agent_resumed(
                    task_gid, task, feedback,
                    prev_plan, prev_investigation, prev_error,
                )
            finally:
                _agent_timers.pop(task_gid, None)

        worker = asyncio.create_task(run_resumed())
        _active_workers[task_gid] = worker
        agent_queue.register_running(task_gid, worker)
        return load_agent_run(task_gid)
    except Exception:
        _active_workers.pop(task_gid, None)
        raise


async def stop_agent(task_gid: str) -> bool:
    """Stop a running agent."""
    worker = _active_workers.get(task_gid)
    if worker:
        worker.cancel()
        try:
            await worker
        except (asyncio.CancelledError, Exception):
            pass
        run = load_agent_run(task_gid)
        if run and run.get("phase") != AgentPhase.CANCELLED.value:
            update_phase(task_gid, AgentPhase.CANCELLED)
            add_log(task_gid, "Agent cancelled by user")
        await _broadcast_state(task_gid)
        return True
    # If not running, check if queued
    if agent_queue.dequeue(task_gid):
        update_phase(task_gid, AgentPhase.CANCELLED)
        add_log(task_gid, "Agent dequeued by user")
        await _broadcast_state(task_gid)
        return True
    # Not running or queued — still mark cancelled if there's an active run file
    run = load_agent_run(task_gid)
    if run and run.get("phase") not in (None, AgentPhase.DONE.value, AgentPhase.CANCELLED.value):
        update_phase(task_gid, AgentPhase.CANCELLED)
        add_log(task_gid, "Agent cancelled by user (orphaned run)")
        await _broadcast_state(task_gid)
        return True
    return False


async def answer_question(task_gid: str, answer: str) -> bool:
    """Provide an answer to a paused or awaiting_approval agent."""
    if not answer or not answer.strip():
        return False
    run = load_agent_run(task_gid)
    if not run or run["phase"] not in (AgentPhase.PAUSED.value, AgentPhase.AWAITING_APPROVAL.value, AgentPhase.QA_REVIEW.value):
        return False
    if not run.get("question"):
        return False

    run["question"]["answer"] = answer.strip()
    run["question"]["answered_at"] = datetime.now(timezone.utc).isoformat()

    old_phase = run["phase"]
    answer_lower = answer.strip().lower()
    if old_phase == AgentPhase.AWAITING_APPROVAL.value:
        if answer_lower == "approve":
            run["phase"] = AgentPhase.CODING.value
        elif answer_lower == "reject":
            run["phase"] = AgentPhase.CANCELLED.value
        elif answer_lower.startswith("revise:"):
            run["phase"] = AgentPhase.PLANNING.value
    elif old_phase == AgentPhase.QA_REVIEW.value:
        if answer_lower == "approve":
            run["phase"] = AgentPhase.DONE.value
        elif answer_lower.startswith("reject"):
            run["phase"] = AgentPhase.CODING.value

    save_agent_run(task_gid, run)
    add_log(task_gid, f"Human answered: {answer}")
    await _broadcast_state(task_gid)
    return True


# ─── Guide (send feedback to running agent) ───


async def guide_agent(task_gid: str, feedback: str) -> bool:
    """Interrupt the running Claude process and resume with user feedback."""
    run = load_agent_run(task_gid)
    if not run:
        return False
    worker = _active_workers.get(task_gid)
    if not worker or worker.done():
        return False

    session_id = run.get("claude_session_id")
    if not session_id:
        add_log(task_gid, "Guide requested but no session_id captured yet — feedback will be queued", "warning")

    # Store feedback signal before killing so _agent_code sees it on re-entry
    run["pending_guide"] = {
        "feedback": feedback,
        "session_id": session_id,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }
    save_agent_run(task_gid, run)
    add_log(task_gid, f"Guide signal stored. Terminating active Claude process...")

    killed = await kill_active_claude(task_gid)
    if killed:
        add_log(task_gid, "Claude process terminated — will resume with guidance")
    else:
        add_log(task_gid, "No active Claude process found (may have just finished)", "warning")

    return True


# ─── Quality Checks ───

async def _quality_checks(task_gid: str, run: dict) -> list[dict]:
    """Run quality checks on all repos."""
    checks = []

    for repo_entry in run["repos"]:
        repo = get_repo(repo_entry["id"])
        if not repo or not repo_entry.get("worktree_path"):
            continue

        wt_path = repo_entry["worktree_path"]
        repo_id = repo_entry["id"]

        # 1. Conventional commit check
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-10"],
                cwd=wt_path, capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                conventional_prefixes = ("feat:", "fix:", "chore:", "refactor:", "docs:", "test:", "style:", "perf:", "ci:", "build:")
                commits = [l.split(" ", 1)[1] if " " in l else l for l in result.stdout.strip().split("\n") if l.strip()]
                bad_commits = [c for c in commits if not any(c.lower().startswith(p) for p in conventional_prefixes)]
                checks.append({
                    "repo": repo_id,
                    "check": "Conventional commits",
                    "passed": len(bad_commits) == 0,
                    "detail": f"{len(bad_commits)} non-conventional commits" if bad_commits else "All commits follow convention",
                })
        except Exception:
            pass

        # 2. No TODO/FIXME introduced
        try:
            result = subprocess.run(
                ["git", "diff", "--unified=0", "HEAD~1..HEAD"],
                cwd=wt_path, capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                added_lines = [l for l in result.stdout.split("\n") if l.startswith("+") and not l.startswith("+++")]
                todos = [l for l in added_lines if "TODO" in l or "FIXME" in l or "HACK" in l]
                checks.append({
                    "repo": repo_id,
                    "check": "No TODOs/FIXMEs",
                    "passed": len(todos) == 0,
                    "detail": f"{len(todos)} TODO/FIXME/HACK found in new code" if todos else "Clean",
                })
        except Exception:
            pass

        # 3. Lint check (if configured)
        if repo.get("lint_cmd"):
            try:
                result = subprocess.run(
                    ["/bin/sh", "-c", repo["lint_cmd"]],
                    cwd=wt_path, capture_output=True, text=True, timeout=60,
                )
                checks.append({
                    "repo": repo_id,
                    "check": "Lint",
                    "passed": result.returncode == 0,
                    "detail": "Passed" if result.returncode == 0 else result.stderr[:200] or result.stdout[:200],
                })
            except Exception as e:
                checks.append({"repo": repo_id, "check": "Lint", "passed": False, "detail": str(e)})

    return checks


def _has_migration_files(wt_path: str) -> bool:
    """Check if the agent's commits include migration files."""
    try:
        default_branch = "master"
        result = subprocess.run(
            ["git", "diff", "--name-only", f"origin/{default_branch}...HEAD"],
            cwd=wt_path, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return True  # assume yes if we can't check
        files = result.stdout.strip().split("\n")
        migration_patterns = ["migration", "migrate", "schema"]
        return any(
            any(p in f.lower() for p in migration_patterns)
            for f in files if f.strip()
        )
    except Exception:
        return True  # assume yes on error


def _select_test_cmd(repo: dict, wt_path: str) -> Optional[str]:
    """Pick the best test command: fast (no-migration) when safe, full otherwise."""
    fast_cmd = repo.get("test_worktree_cmd_fast")
    full_cmd = repo.get("test_worktree_cmd") or repo.get("test_docker_cmd") or repo.get("test_cmd")
    if fast_cmd and not _has_migration_files(wt_path):
        log.info("No migration files detected — using fast test command: %s", fast_cmd)
        return fast_cmd
    return full_cmd


# ─── Agent Main Loop ───

async def _run_agent(task_gid: str, task: dict):
    """Main agent execution loop using Claude Code CLI."""
    try:
        run = load_agent_run(task_gid)
        if not run:
            return

        # Fetch Asana comments to enrich context
        comments_context = await _fetch_task_comments(task_gid)
        subtasks_context = await _fetch_subtasks_context(task_gid)
        branch_state = _get_branch_state(run)

        # Detect QA return: task has previous runs + open subtasks = QA sent it back
        qa_context = ""
        previous_runs = load_run_history(task_gid)
        has_completed_run = any(r.get("phase") == "done" for r in previous_runs)
        subtasks = await fetch_subtasks(task_gid)
        open_subtasks = [s for s in subtasks if not s.get("completed")]
        if has_completed_run and open_subtasks:
            qa_context = (
                "\n\n## ⚠ QA Return\n"
                "This task was previously completed and delivered, but QA found issues. "
                "The open subtasks below describe what needs to be fixed. "
                "DO NOT redo all the work — focus ONLY on the open subtasks. "
                "The branch already has the previous implementation."
            )
            add_log(task_gid, f"QA return detected: {len(open_subtasks)} open subtasks from previous delivery")

        task_context = _build_task_context(task, run) + comments_context + subtasks_context + qa_context + branch_state

        # Asana: move task to "Desarrollo"
        settings = load_agent_settings()
        if settings.get("section_on_start"):
            await _move_task_section(task_gid, settings["section_on_start"])

        # Phase: INVESTIGATING — explore codebase before planning
        update_phase(task_gid, AgentPhase.INVESTIGATING)
        await _broadcast_state(task_gid)
        add_log(task_gid, "Investigating codebase...")

        investigation = await _agent_investigate(task_gid, task_context, run)
        if investigation:
            run = load_agent_run(task_gid)
            run["investigation"] = investigation
            save_agent_run(task_gid, run)
            task_context += f"\n\n## Investigation Report\n{investigation}"

            # Check if investigation recommends additional repos
            try:
                additional = _parse_additional_repos(investigation, run)
            except Exception as e:
                log.exception("Failed to parse additional repos from investigation")
                add_log(task_gid, f"Failed to parse additional repos: {e}", "warning")
                additional = []
            if additional:
                add_log(task_gid, f"Investigation recommends additional repos: {', '.join(additional)}")
                # Extract branch slug from existing worktree branch name
                existing_branch = next((r.get("branch", "") for r in run["repos"] if r.get("branch")), "")
                # Branch format: feature/{task_gid}/{slug} — extract the slug
                slug_parts = existing_branch.split("/")
                slug = slug_parts[-1] if len(slug_parts) >= 3 else "work"
                for repo_id in additional:
                    try:
                        wt = create_worktree(task_gid, repo_id, slug)
                        new_entry = {"id": repo_id, "status": "ready", "commits": 0,
                                     "worktree_path": wt["path"], "branch": wt["branch"]}
                        run["repos"].append(new_entry)
                        add_log(task_gid, f"Added repo {repo_id}: {wt['path']} (branch: {wt['branch']})")
                    except Exception as e:
                        add_log(task_gid, f"Failed to add repo {repo_id}: {e}", "warning")
                save_agent_run(task_gid, run)
                await _broadcast_state(task_gid)
                # Rebuild task context with new repos
                task_context = _build_task_context(task, run) + comments_context + subtasks_context + qa_context + branch_state
                task_context += f"\n\n## Investigation Report\n{investigation}"

        # Phase: PLANNING
        update_phase(task_gid, AgentPhase.PLANNING)
        await _broadcast_state(task_gid)

        plan = await _agent_plan(task_gid, task_context, run)
        if not plan:
            return

        run = load_agent_run(task_gid)
        run["plan"] = plan
        save_agent_run(task_gid, run)
        add_log(task_gid, f"Plan generated ({len(plan)} chars)")

        # Asana: post plan as comment
        await _post_asana_comment(task_gid, f"🤖 Agent Plan:\n\n{plan[:3000]}", dedup_prefix="🤖 Agent Plan:")

        # Phase: AWAITING APPROVAL (loop supports revise feedback)
        while True:
            update_phase(task_gid, AgentPhase.AWAITING_APPROVAL)
            await _broadcast_state(task_gid)
            add_log(task_gid, "Waiting for plan approval...")

            # Pause work timer — human is reviewing
            timer = _agent_timers.get(task_gid)
            if timer:
                timer.pause()

            answer = None
            while True:
                await asyncio.sleep(2)
                run = load_agent_run(task_gid)
                if not run or run["phase"] == AgentPhase.CANCELLED.value:
                    return
                q = run.get("question")
                if q and q.get("answer"):
                    answer = q["answer"]
                    break

            # Resume work timer — human responded
            if timer:
                timer.resume()

            answer_lower = answer.strip().lower()
            if answer_lower in ("reject", "no", "cancel"):
                update_phase(task_gid, AgentPhase.CANCELLED)
                add_log(task_gid, "Plan rejected by user")
                return

            if answer_lower.startswith("revise:"):
                feedback = answer[7:].strip()
                add_log(task_gid, f"Revising plan with feedback: {feedback}")
                run = load_agent_run(task_gid)
                run["question"] = None
                save_agent_run(task_gid, run)
                update_phase(task_gid, AgentPhase.PLANNING)
                await _broadcast_state(task_gid)

                revised_context = f"{task_context}\n\n## Previous Plan\n{plan}\n\n## User Feedback\n{feedback}"
                plan = await _agent_plan(task_gid, revised_context, run)
                if not plan:
                    return
                run = load_agent_run(task_gid)
                run["plan"] = plan
                save_agent_run(task_gid, run)
                add_log(task_gid, f"Revised plan generated ({len(plan)} chars)")
                continue

            if answer_lower not in ("approve", "yes", "ok", "lgtm"):
                add_log(task_gid, f"Unrecognized approval answer: '{answer_lower}'. Use approve/reject/revise:feedback.", "warning")
                run = load_agent_run(task_gid)
                run["question"]["answer"] = None
                save_agent_run(task_gid, run)
                continue

            # Approved — clear question and proceed to coding
            run = load_agent_run(task_gid)
            run["question"] = None
            save_agent_run(task_gid, run)
            break

        # ═══ CODING → TESTING → QA LOOP ═══
        qa_feedback = ""
        while True:
            if _check_timeout(task_gid):
                return
            run = load_agent_run(task_gid)
            run["qa_report"] = None
            run["question"] = None
            for repo_entry in run["repos"]:
                if repo_entry.get("worktree_path") and repo_entry["status"] == "done":
                    repo_entry["status"] = "coding"
            save_agent_run(task_gid, run)
            update_phase(task_gid, AgentPhase.CODING)
            await _broadcast_state(task_gid)

            coding_context = task_context
            if qa_feedback:
                coding_context += f"\n\n{qa_feedback}\n\nIMPORTANT: Your code was reviewed and needs fixes. Focus ONLY on fixing the specific issues listed above. Do NOT rewrite code that is already working. Make targeted, minimal fixes."

            coded_any = False
            for repo_entry in run["repos"]:
                add_log(task_gid, f"[{repo_entry['id']}] Repo status: {repo_entry['status']} | worktree: {bool(repo_entry.get('worktree_path'))}")
                if not repo_entry.get("worktree_path"):
                    add_log(task_gid, f"[{repo_entry['id']}] Skipping (no worktree)", "warning")
                    continue
                if repo_entry["status"] == "done":
                    add_log(task_gid, f"[{repo_entry['id']}] Skipping (already done)", "warning")
                    continue
                save_agent_run(task_gid, run)

                success = await _agent_code(task_gid, coding_context, run, repo_entry)
                if not success:
                    return

                coded_any = True
                repo_entry["status"] = "done"
                save_agent_run(task_gid, run)

            if not coded_any:
                add_log(task_gid, "No repos were coded — all skipped or none ready", "error")
                update_phase(task_gid, AgentPhase.ERROR, error="No repos were coded")
                return

            # Rebase onto latest default branch before testing
            for repo_entry in run["repos"]:
                if repo_entry.get("worktree_path"):
                    success = await _rebase_from_default(task_gid, repo_entry)
                    if not success:
                        return

            # Phase: TESTING
            if _check_timeout(task_gid):
                return
            update_phase(task_gid, AgentPhase.TESTING)
            await _broadcast_state(task_gid)

            for repo_entry in run["repos"]:
                repo = get_repo(repo_entry["id"])
                if repo and repo_entry.get("worktree_path"):
                    test_cmd = _select_test_cmd(repo, repo_entry["worktree_path"])
                    if test_cmd:
                        test_cwd = repo["path"] if (repo.get("test_docker_cmd") and not repo.get("test_worktree_cmd") and not repo.get("test_worktree_cmd_fast")) else repo_entry["worktree_path"]
                        success = await _agent_test(task_gid, repo_entry, test_cmd, test_cwd)
                        if not success:
                            return

            # Quality checks (informational)
            quality = await _quality_checks(task_gid, run)
            run = load_agent_run(task_gid)
            run["quality_checks"] = quality
            save_agent_run(task_gid, run)
            if quality:
                passed = sum(1 for c in quality if c["passed"])
                add_log(task_gid, f"Quality: {passed}/{len(quality)} checks passed")

            # Phase: QA REVIEW
            qa_report = await _agent_qa_review(task_gid, task, run)
            if qa_report is None:
                add_log(task_gid, "QA review failed to produce a report — retrying once...", "warning")
                qa_report = await _agent_qa_review(task_gid, task, run)
            if not qa_report:
                add_log(task_gid, "QA review could not produce a report after retry — stopping", "error")
                update_phase(task_gid, AgentPhase.ERROR, error="QA review failed to produce a report")
                return

            # QA auto-approved (PASS) — skip human review
            run = load_agent_run(task_gid)
            if not run.get("question"):
                add_log(task_gid, "QA auto-approved — skipping to done")
                break

            # Wait for QA approval — pause work timer
            add_log(task_gid, "Waiting for QA approval...")
            timer = _agent_timers.get(task_gid)
            if timer:
                timer.pause()

            qa_answer = None
            while True:
                await asyncio.sleep(2)
                run = load_agent_run(task_gid)
                if not run:
                    add_log(task_gid, "Run data missing — aborting", "error")
                    return
                if run.get("phase") in (AgentPhase.CANCELLED.value, AgentPhase.ERROR.value):
                    add_log(task_gid, f"Phase changed to {run['phase']} — aborting")
                    return
                q = run.get("question")
                if q and q.get("answer"):
                    qa_answer = q["answer"]
                    add_log(task_gid, f"Answer received in poll: {qa_answer[:50]}")
                    break

            # Resume work timer
            if timer:
                timer.resume()

            qa_lower = qa_answer.strip().lower()
            run = load_agent_run(task_gid)
            run["question"] = None
            save_agent_run(task_gid, run)

            if qa_lower in ("approve", "yes", "lgtm"):
                add_log(task_gid, "QA approved — proceeding to done")
                break
            else:
                user_feedback = ""
                if qa_lower.startswith("reject"):
                    user_feedback = qa_answer.strip()[len("reject"):].lstrip(": ").strip()
                elif qa_lower not in ("no", "reject", "fix", "redo"):
                    user_feedback = qa_answer.strip()
                qa_feedback = _build_fix_instructions(qa_report, user_feedback)
                add_log(task_gid, f"QA rejected — looping back to coding with feedback")
                await _broadcast_state(task_gid)
                continue

        # ═══ END CODING-QA LOOP ═══

        # Phase: DONE
        update_phase(task_gid, AgentPhase.DONE)
        await _broadcast_state(task_gid)
        add_log(task_gid, "Agent completed successfully")

        settings = load_agent_settings()
        if settings.get("section_on_done"):
            await _move_task_section(task_gid, settings["section_on_done"])
        run = load_agent_run(task_gid)
        branches = ", ".join(r.get("branch", "?") for r in run.get("repos", []))
        commit_total = sum(r.get("commits", 0) for r in run.get("repos", []))
        await _post_asana_comment(
            task_gid,
            f"🤖 Agent completed.\n\nBranches: {branches}\nCommits: {commit_total}\n\n"
            f"Review the changes and merge when ready.",
            dedup_prefix="🤖 Agent completed."
        )

        await _auto_complete_subtasks(task_gid, run)

        for repo_entry in run.get("repos", []):
            update_memory_after_run(repo_entry["id"], task_gid, run)

    except asyncio.CancelledError:
        update_phase(task_gid, AgentPhase.CANCELLED)
        raise
    except Exception as e:
        log.exception("Agent error for task %s", task_gid)
        update_phase(task_gid, AgentPhase.ERROR, error=str(e))
        add_log(task_gid, f"Agent error: {e}", "error")
        await _broadcast_state(task_gid)
        await _post_asana_comment(task_gid, f"🤖 Agent failed: {str(e)[:500]}", dedup_prefix="🤖 Agent failed:")
        settings = load_agent_settings()
        if settings.get("section_on_error"):
            await _move_task_section(task_gid, settings["section_on_error"])
        run = load_agent_run(task_gid)
        if run:
            for repo_entry in run.get("repos", []):
                update_memory_after_run(repo_entry["id"], task_gid, run)
    finally:
        _active_workers.pop(task_gid, None)
        agent_queue.unregister_running(task_gid)


async def _run_agent_resumed(task_gid: str, task: dict, feedback: str,
                             prev_plan: str, prev_investigation: str,
                             prev_error: str):
    """Resumed agent run — skips investigation/planning, jumps to coding with feedback."""
    try:
        run = load_agent_run(task_gid)
        if not run:
            return

        comments_context = await _fetch_task_comments(task_gid)
        subtasks_context = await _fetch_subtasks_context(task_gid)
        branch_state = _get_branch_state(run)

        task_context = _build_task_context(task, run) + comments_context + subtasks_context + branch_state

        if prev_investigation:
            task_context += f"\n\n## Investigation Report (from previous run)\n{prev_investigation}"
        if prev_plan:
            task_context += f"\n\n## Implementation Plan (from previous run)\n{prev_plan}"

        # Build resume context with user feedback
        resume_section = "\n\n## Resume Feedback\n"
        resume_section += "The agent previously ran on this task "
        if prev_error:
            resume_section += f"and encountered an error: {prev_error}\n\n"
        else:
            resume_section += "and completed.\n\n"
        resume_section += (
            f"The user is resuming with the following feedback:\n\n{feedback}\n\n"
            "IMPORTANT: The branch already has previous work. Review what exists, "
            "then apply ONLY the changes described in the feedback above. "
            "Do NOT redo work that is already done."
        )
        task_context += resume_section

        # Move task back to dev section
        settings = load_agent_settings()
        if settings.get("section_on_start"):
            await _move_task_section(task_gid, settings["section_on_start"])

        # Jump directly to coding → testing → QA loop
        qa_feedback = ""
        while True:
            if _check_timeout(task_gid):
                return
            run = load_agent_run(task_gid)
            run["qa_report"] = None
            run["question"] = None
            for repo_entry in run["repos"]:
                if repo_entry.get("worktree_path") and repo_entry["status"] == "done":
                    repo_entry["status"] = "coding"
            save_agent_run(task_gid, run)
            update_phase(task_gid, AgentPhase.CODING)
            await _broadcast_state(task_gid)

            coding_context = task_context
            if qa_feedback:
                coding_context += f"\n\n{qa_feedback}\n\nIMPORTANT: Your code was reviewed and needs fixes. Focus ONLY on fixing the specific issues listed above. Do NOT rewrite code that is already working. Make targeted, minimal fixes."

            coded_any = False
            for repo_entry in run["repos"]:
                if not repo_entry.get("worktree_path"):
                    continue
                if repo_entry["status"] == "done":
                    continue
                save_agent_run(task_gid, run)

                success = await _agent_code(task_gid, coding_context, run, repo_entry)
                if not success:
                    return
                run = load_agent_run(task_gid)
                if not run or run["phase"] == AgentPhase.CANCELLED.value:
                    return
                coded_any = True
                repo_entry["status"] = "done"
                save_agent_run(task_gid, run)

            if not coded_any:
                add_log(task_gid, "No repos were coded — all skipped or none ready", "error")
                update_phase(task_gid, AgentPhase.ERROR, error="No repos were coded")
                return

            # Rebase onto latest default branch
            for repo_entry in run["repos"]:
                if repo_entry.get("worktree_path"):
                    success = await _rebase_from_default(task_gid, repo_entry)
                    if not success:
                        return

            # Phase: TESTING
            if _check_timeout(task_gid):
                return
            update_phase(task_gid, AgentPhase.TESTING)
            await _broadcast_state(task_gid)

            for repo_entry in run["repos"]:
                repo = get_repo(repo_entry["id"])
                if repo and repo_entry.get("worktree_path"):
                    test_cmd = _select_test_cmd(repo, repo_entry["worktree_path"])
                    if test_cmd:
                        test_cwd = repo["path"] if (repo.get("test_docker_cmd") and not repo.get("test_worktree_cmd") and not repo.get("test_worktree_cmd_fast")) else repo_entry["worktree_path"]
                        success = await _agent_test(task_gid, repo_entry, test_cmd, test_cwd)
                        if not success:
                            return

            # Quality checks
            quality = await _quality_checks(task_gid, run)
            run = load_agent_run(task_gid)
            run["quality_checks"] = quality
            save_agent_run(task_gid, run)
            if quality:
                passed = sum(1 for c in quality if c["passed"])
                add_log(task_gid, f"Quality: {passed}/{len(quality)} checks passed")

            # Phase: QA REVIEW
            qa_report = await _agent_qa_review(task_gid, task, run)
            if qa_report is None:
                add_log(task_gid, "QA review failed — retrying once...", "warning")
                qa_report = await _agent_qa_review(task_gid, task, run)
            if not qa_report:
                add_log(task_gid, "QA review could not produce a report — stopping", "error")
                update_phase(task_gid, AgentPhase.ERROR, error="QA review failed to produce a report")
                return

            # QA auto-approved (PASS)
            run = load_agent_run(task_gid)
            if not run.get("question"):
                add_log(task_gid, "QA auto-approved — skipping to done")
                break

            # Wait for QA approval
            add_log(task_gid, "Waiting for QA approval...")
            timer = _agent_timers.get(task_gid)
            if timer:
                timer.pause()

            qa_answer = None
            while True:
                await asyncio.sleep(2)
                run = load_agent_run(task_gid)
                if not run:
                    return
                if run.get("phase") in (AgentPhase.CANCELLED.value, AgentPhase.ERROR.value):
                    return
                q = run.get("question")
                if q and q.get("answer"):
                    qa_answer = q["answer"]
                    break

            if timer:
                timer.resume()

            qa_lower = qa_answer.strip().lower()
            run = load_agent_run(task_gid)
            run["question"] = None
            save_agent_run(task_gid, run)

            if qa_lower in ("approve", "yes", "lgtm"):
                add_log(task_gid, "QA approved — proceeding to done")
                break
            else:
                user_feedback = ""
                if qa_lower.startswith("reject"):
                    user_feedback = qa_answer.strip()[len("reject"):].lstrip(": ").strip()
                elif qa_lower not in ("no", "reject", "fix", "redo"):
                    user_feedback = qa_answer.strip()
                qa_feedback = _build_fix_instructions(qa_report, user_feedback)
                add_log(task_gid, "QA rejected — looping back to coding with feedback")
                await _broadcast_state(task_gid)
                continue

        # Phase: DONE
        update_phase(task_gid, AgentPhase.DONE)
        await _broadcast_state(task_gid)
        add_log(task_gid, "Agent completed successfully (resumed run)")

        settings = load_agent_settings()
        if settings.get("section_on_done"):
            await _move_task_section(task_gid, settings["section_on_done"])
        run = load_agent_run(task_gid)
        branches = ", ".join(r.get("branch", "?") for r in run.get("repos", []))
        commit_total = sum(r.get("commits", 0) for r in run.get("repos", []))
        await _post_asana_comment(
            task_gid,
            f"🤖 Agent completed (resumed).\n\nBranches: {branches}\nCommits: {commit_total}\n\n"
            f"Review the changes and merge when ready.",
            dedup_prefix="🤖 Agent completed (resumed)."
        )

        await _auto_complete_subtasks(task_gid, run)

        for repo_entry in run.get("repos", []):
            update_memory_after_run(repo_entry["id"], task_gid, run)

    except asyncio.CancelledError:
        update_phase(task_gid, AgentPhase.CANCELLED)
        raise
    except Exception as e:
        log.exception("Resumed agent error for task %s", task_gid)
        update_phase(task_gid, AgentPhase.ERROR, error=str(e))
        add_log(task_gid, f"Agent error: {e}", "error")
        await _broadcast_state(task_gid)
        await _post_asana_comment(task_gid, f"🤖 Agent failed (resumed): {str(e)[:500]}", dedup_prefix="🤖 Agent failed (resumed):")
        settings = load_agent_settings()
        if settings.get("section_on_error"):
            await _move_task_section(task_gid, settings["section_on_error"])
        run = load_agent_run(task_gid)
        if run:
            for repo_entry in run.get("repos", []):
                update_memory_after_run(repo_entry["id"], task_gid, run)
    finally:
        _active_workers.pop(task_gid, None)
        agent_queue.unregister_running(task_gid)


# ─── Context Building ───

def _build_task_context(task: dict, run: dict) -> str:
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


# ─── Phase Implementations ───


def _load_claude_md_guides(run: dict) -> str:
    """Load CLAUDE.md files from projects root and each configured repo."""
    from ..config import PROJECTS_DIR
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


def _parse_additional_repos(investigation: str, run: dict) -> list[str]:
    """Parse ADDITIONAL_REPOS line from investigation report. Returns list of new repo IDs."""
    import re
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


async def _agent_investigate(task_gid: str, context: str, run: dict) -> Optional[str]:
    """Run the investigation phase — explore codebase with read-only tools before planning."""
    try:
        wt_path = run["repos"][0].get("worktree_path", ".")

        # Build list of all repo paths for cross-project exploration
        # Show actual worktree paths for task repos so the agent knows where to look
        all_repos = list_repos()
        task_repo_map = {r["id"]: r for r in run.get("repos", [])}
        repo_map = []
        for repo_entry in all_repos:
            rid = repo_entry["id"]
            lang = repo_entry.get("language", "unknown")
            if rid in task_repo_map:
                tr = task_repo_map[rid]
                wt = tr.get("worktree_path") or repo_entry.get("path", "")
                branch = tr.get("branch", "N/A")
                repo_map.append(f"- {rid} (YOUR WORKTREE, {lang}): {wt}  [branch: {branch}]")
            else:
                path = repo_entry.get("path", "")
                repo_map.append(f"- {rid} (related project, {lang}): {path}")
        repos_section = "\n".join(repo_map) if repo_map else "No repos configured."

        # Load CLAUDE.md guides
        claude_guides = _load_claude_md_guides(run)

        system = (
            "You are a senior developer investigating a codebase BEFORE writing an implementation plan. "
            "Your goal is to explore the code and produce a concise investigation report. "
            "You have READ-ONLY access to all configured project repositories.\n\n"
            "DO NOT modify any files. DO NOT create commits. DO NOT run destructive commands.\n\n"
            "## What to investigate:\n"
            "1. **Tech stack & structure**: Identify the language, framework, directory layout, and key patterns\n"
            "2. **Relevant files**: Find the specific files, classes, and functions related to the task\n"
            "3. **Dependencies**: Check if the task depends on other projects (e.g., shared migrations, APIs, shared models)\n"
            "4. **Testing**: How does this project run tests? Are there test examples to follow?\n"
            "5. **Gotchas**: Anything surprising (missing features you'd expect, unusual patterns)\n\n"
            "## Available repositories:\n"
            f"{repos_section}\n\n"
            "You can freely read files from ANY of these repos using their full paths. "
            "If the task mentions another project or you suspect cross-project dependencies, "
            "investigate the related repos too.\n\n"
            "## IMPORTANT: Additional repos needed\n"
            "If after investigating you determine that this task REQUIRES changes in a repo that is NOT "
            "currently assigned as YOUR WORKTREE, you MUST include a line at the very end of your report "
            "in this exact format:\n\n"
            "ADDITIONAL_REPOS: repo-id-1, repo-id-2\n\n"
            "Only include repos from the available list above. Only request repos where code changes "
            "are actually needed (e.g., migrations, shared models, API contracts). Do NOT request repos "
            "just because they are related.\n\n"
            "Output a structured investigation report with your findings. "
            "Keep it under 800 words. Focus on FACTS you found in the code, not assumptions."
        )

        prompt = f"{context}{claude_guides}\n\nInvestigate the codebase and produce a report. Use Read, Glob, and Grep tools to explore."

        result = await _run_claude_cli(
            prompt=prompt,
            cwd=wt_path,
            max_turns=15,
            allowed_tools=["Read", "Glob", "Grep", "LS", "Bash(git log:*)", "Bash(git diff:*)", "Bash(find:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(wc:*)"],
            system_prompt=system,
            task_gid=task_gid,
            model="opus",
        )

        report = result.get("text", "").strip()

        try:
            _accumulate_cost(task_gid, result)
        except Exception as e:
            log.warning(f"Failed to accumulate cost for investigation: {e}")

        if result["returncode"] != 0 and not report:
            error = result.get("stderr", "") or result.get("raw_output", "Unknown error")
            add_log(task_gid, f"Investigation failed (exit {result['returncode']}): {error[:500]}", "error")
            # Non-fatal — proceed to planning without investigation
            return None

        if report:
            add_log(task_gid, f"Investigation complete ({len(report)} chars)")
        return report

    except Exception as e:
        add_log(task_gid, f"Investigation failed: {e}", "warning")
        # Non-fatal — proceed to planning without investigation
        return None


async def _agent_plan(task_gid: str, context: str, run: dict) -> Optional[str]:
    """Run the planning phase."""
    try:
        wt_path = run["repos"][0].get("worktree_path", ".")

        repo_context = ""
        for r in run["repos"]:
            repo = get_repo(r["id"])
            if not repo:
                continue
            if repo.get("test_description"):
                repo_context += f"\n\n## Testing ({r['id']})\n{repo['test_description']}"
            if repo.get("context_files"):
                for cf in repo["context_files"]:
                    cf_path = Path(r.get("worktree_path", repo["path"])) / cf
                    if cf_path.exists():
                        try:
                            content = cf_path.read_text()[:5000]
                            repo_context += f"\n\n## Context: {cf}\n{content}"
                        except OSError:
                            pass

        system = (
            "You are a senior developer. Analyze the task and produce a concise implementation plan. "
            "List the files you will modify, the approach, and any questions or risks. "
            "Be specific about which repo and which files. Keep the plan under 500 words. "
            "Do NOT use any tools. Do NOT read or browse files. Just analyze the context provided and respond with the plan. "
            "Output ONLY the plan text, no markdown fences or extra formatting.\n\n"
            "IMPORTANT: NEVER include merge or rebase steps for other branches in your plan. "
            "Branch references or MR links in the task description are historical context only — "
            "that work is already incorporated in your working branch. "
            "Focus exclusively on writing new code to solve the task requirements."
        )

        prompt = f"{context}{repo_context}\n\nProduce an implementation plan. Do NOT use tools, just respond directly."

        result = await _run_claude_cli(
            prompt=prompt,
            cwd=wt_path,
            max_turns=1,
            allowed_tools=[],
            system_prompt=system,
            task_gid=task_gid,
        )

        plan_text = result.get("text", "").strip()

        try:
            _accumulate_cost(task_gid, result)
        except Exception as e:
            log.warning(f"Failed to accumulate cost for planning: {e}")

        if result["returncode"] != 0 and not plan_text:
            error = result.get("stderr", "") or result.get("raw_output", "Unknown error")
            add_log(task_gid, f"Planning failed (exit {result['returncode']}): {error[:500]}", "error")
            update_phase(task_gid, AgentPhase.ERROR, error=f"Claude Code error: {error[:200]}")
            return None

        if plan_text.startswith("Error:") and len(plan_text) < 100:
            add_log(task_gid, f"Planning returned error: {plan_text}", "error")
            update_phase(task_gid, AgentPhase.ERROR, error=plan_text)
            return None
        if not plan_text:
            add_log(task_gid, "Planning returned empty response", "error")
            update_phase(task_gid, AgentPhase.ERROR, error="Empty plan response")
            return None

        run = load_agent_run(task_gid)
        run["question"] = {
            "text": "Review the implementation plan. Approve to proceed or reject to cancel.",
            "plan": plan_text,
            "options": ["Approve", "Reject"],
            "asked_at": datetime.now(timezone.utc).isoformat(),
            "answer": None,
        }
        save_agent_run(task_gid, run)

        return plan_text

    except Exception as e:
        add_log(task_gid, f"Planning failed: {e}", "error")
        update_phase(task_gid, AgentPhase.ERROR, error=str(e))
        return None


async def _agent_code(task_gid: str, context: str, run: dict, repo_entry: dict) -> bool:
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
            f"IMPORTANT: Work ONLY in the current working directory (worktree). "
            f"Do NOT cd or navigate to any other directory. All file paths are relative to cwd. "
            f"NEVER run git merge, git rebase, git pull, or git checkout of other branches. "
            f"Branch references or MR links in the task are historical context — that work is already in your branch. "
            f"Commit your changes when done.{docker_hint}{test_hint}"
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

        prompt = f"{context}\n\n## Approved Plan\n{plan}\n\n{commit_instructions}\n\nImplement the plan now."

        add_log(task_gid, f"[{repo_entry['id']}] Claude Code starting...")

        result = await _run_claude_cli(
            prompt=prompt,
            cwd=wt_path,
            max_turns=30,
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
            system_prompt=system,
            task_gid=task_gid,
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
            guide_result = await _run_claude_cli(
                prompt=pending_guide["feedback"],
                cwd=wt_path,
                max_turns=30,
                allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
                system_prompt=system,
                task_gid=task_gid,
                resume_session_id=pending_guide["session_id"],
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
            result = guide_result  # use the latest result for success/failure check

        add_log(task_gid, f"[{repo_entry['id']}] Claude Code finished (exit {result['returncode']})")

        if result["returncode"] != 0:
            error = result.get("stderr", "") or result.get("text", "Unknown error")
            # Ignore non-zero exit from guided termination (process was killed)
            run = load_agent_run(task_gid)
            if run and run.get("pending_guide"):
                # Guide arrived right after process ended — will be handled on next loop
                pass
            else:
                add_log(task_gid, f"[{repo_entry['id']}] Coding failed (exit {result['returncode']}): {error[:500]}", "error")
                update_phase(task_gid, AgentPhase.ERROR, error=f"Claude Code error: {error[:200]}")
                return False

        _auto_commit_if_dirty(wt_path, repo_entry["id"], task_gid)

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

        add_log(task_gid, f"[{repo_entry['id']}] Coding complete ({repo_entry['commits']} commits)")
        return True

    except Exception as e:
        add_log(task_gid, f"[{repo_entry['id']}] Coding failed: {e}", "error")
        update_phase(task_gid, AgentPhase.ERROR, error=str(e))
        return False


async def _rebase_from_default(task_gid: str, repo_entry: dict) -> bool:
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


def _auto_commit_if_dirty(wt_path: str, repo_id: str, task_gid: str):
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


async def _agent_test(task_gid: str, repo_entry: dict, test_cmd: str, test_cwd: str = None) -> bool:
    """Run tests in the worktree. Retry with Claude Code self-fix on failure."""
    run = load_agent_run(task_gid)
    max_retries = run.get("max_retries", 3)
    cwd = test_cwd or repo_entry["worktree_path"]
    add_log(task_gid, f"[{repo_entry['id']}] Test command: {test_cmd}")

    # Pre-check: if test command uses Docker, verify infra is available
    if "docker" in test_cmd:
        try:
            docker_check = subprocess.run(
                ["docker", "info"], capture_output=True, text=True, timeout=10,
            )
            if docker_check.returncode != 0:
                add_log(task_gid, f"[{repo_entry['id']}] Docker daemon not reachable. Skipping tests.", "warning")
                return True

            if "docker compose" in test_cmd:
                repo = get_repo(repo_entry["id"])
                compose_dir = repo["path"] if repo else cwd
                ps_check = subprocess.run(
                    ["docker", "compose", "ps", "--services", "--filter", "status=running"],
                    capture_output=True, text=True, timeout=10, cwd=compose_dir,
                )
                if "laravel.test" not in (ps_check.stdout or ""):
                    add_log(task_gid, f"[{repo_entry['id']}] Sail not running (laravel.test service down). Skipping tests.", "warning")
                    return True
            else:
                net_check = subprocess.run(
                    ["docker", "network", "ls", "--filter", "name=yurest_back_sail", "--format", "{{.Name}}"],
                    capture_output=True, text=True, timeout=10,
                )
                if "yurest_back_sail" not in (net_check.stdout or ""):
                    add_log(task_gid, f"[{repo_entry['id']}] Sail network not found. Skipping tests.", "warning")
                    return True

        except Exception as e:
            add_log(task_gid, f"[{repo_entry['id']}] Docker pre-check failed: {e}. Skipping tests.", "warning")
            return True

    for attempt in range(max_retries + 1):
        add_log(task_gid, f"[{repo_entry['id']}] Running tests (attempt {attempt + 1})...")

        try:
            returncode, full_output = await _run_test_with_progress(
                task_gid, repo_entry["id"], test_cmd, cwd,
            )

            if returncode == 0:
                add_log(task_gid, f"[{repo_entry['id']}] Tests passed")
                return True

            error_output = full_output[-2000:]
            add_log(task_gid, f"[{repo_entry['id']}] Test output (last 500 chars): {error_output[-500:]}", "debug")

            matched_pattern = detect_infra_error(error_output)
            if matched_pattern:
                add_log(task_gid, f"[{repo_entry['id']}] Infrastructure issue (matched: '{matched_pattern}'). Skipping tests.", "warning")
                return True

            add_log(task_gid, f"[{repo_entry['id']}] Tests failed:\n{error_output[:500]}", "warning")

            if attempt < max_retries:
                run["retries"] = attempt + 1
                save_agent_run(task_gid, run)
                fix_success = await _agent_fix_tests(task_gid, repo_entry, error_output)
                if not fix_success:
                    break
            else:
                update_phase(task_gid, AgentPhase.ERROR,
                             error=f"Tests failed after {max_retries} retries")
                return False

        except subprocess.TimeoutExpired:
            add_log(task_gid, f"[{repo_entry['id']}] Test timeout (10 min)", "error")
            update_phase(task_gid, AgentPhase.ERROR, error="Test timeout")
            return False

    return False


async def _run_test_with_progress(task_gid: str, repo_id: str, test_cmd: str, cwd: str) -> tuple[int, str]:
    """Run test command with Popen, streaming progress updates via WebSocket."""
    import time

    proc = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: subprocess.Popen(
            ["/bin/sh", "-c", test_cmd] if isinstance(test_cmd, str) else test_cmd,
            cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True,
        ),
    )

    full_output = []
    phase = "setup"
    last_progress_pct = -1
    last_progress_time = time.monotonic()
    test_total = 0
    test_current = 0
    migration_count = 0

    progress_re = _re.compile(r'(\d+)\s*/\s*(\d+)\s*\(\s*(\d+)%\)')
    migration_re = _re.compile(r'^\s*\d{4}_\d{2}_\d{2}_\d+_\S+.*DONE', _re.MULTILINE)
    seeder_re = _re.compile(r'Database\\Seeders\\')
    summary_re = _re.compile(r'(?:Tests?:?\s*(\d+)|OK\s*\((\d+)\s*test)')

    try:
        while True:
            line = await asyncio.get_event_loop().run_in_executor(None, proc.stdout.readline)
            if not line and proc.poll() is not None:
                break
            if not line:
                continue

            full_output.append(line)

            if phase == "setup" and ("migration" in line.lower() or migration_re.search(line)):
                phase = "migrating"
                add_log(task_gid, f"[{repo_id}] Migrating database...")

            if phase != "seeding" and seeder_re.search(line):
                if phase == "migrating":
                    add_log(task_gid, f"[{repo_id}] Migrations done. Seeding...")
                phase = "seeding"

            if "ParaTest" in line or "PHPUnit" in line or "phpunit" in line.lower():
                if phase != "testing":
                    phase = "testing"
                    add_log(task_gid, f"[{repo_id}] Running tests...")

            if phase == "migrating" and "DONE" in line:
                migration_count += 1

            m = progress_re.search(line)
            if m:
                phase = "testing"
                test_current = int(m.group(1))
                test_total = int(m.group(2))
                pct = int(m.group(3))
                now = time.monotonic()
                if pct >= last_progress_pct + 10 or now - last_progress_time >= 30:
                    add_log(task_gid, f"[{repo_id}] Tests: {pct}% ({test_current}/{test_total})")
                    last_progress_pct = pct
                    last_progress_time = now

        proc.wait(timeout=600)

        output_str = "".join(full_output[-50:])
        if proc.returncode == 0:
            fail_count = output_str.count("E") + output_str.count("F")
            skip_count = output_str.count("S") + output_str.count("R")
            if test_total > 0:
                passed = test_total - fail_count - skip_count
                parts = [f"{passed} passed"]
                if skip_count > 0:
                    parts.append(f"{skip_count} skipped")
                if fail_count > 0:
                    parts.append(f"{fail_count} errors")
                add_log(task_gid, f"[{repo_id}] Results: {', '.join(parts)}")

        return proc.returncode, "".join(full_output)

    except Exception:
        proc.kill()
        proc.wait()
        raise


async def _agent_fix_tests(task_gid: str, repo_entry: dict, error_output: str) -> bool:
    """Attempt to fix failing tests using Claude Code CLI."""
    try:
        prompt = f"Tests are failing with this output:\n\n{error_output}\n\nFix the issues and commit."

        result = await _run_claude_cli(
            prompt=prompt,
            cwd=repo_entry["worktree_path"],
            max_turns=10,
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
            system_prompt=f"You are fixing failing tests. Read the error output, identify the issue, and fix it. Make minimal changes. {BASH_BLOCKLIST} NEVER modify Makefile, Dockerfile, docker-compose.yml, or any infrastructure/config files. Only fix application code and tests.",
            task_gid=task_gid,
        )

        try:
            _accumulate_cost(task_gid, result)
        except Exception as e:
            log.warning(f"Failed to accumulate cost for test fix: {e}")

        if result["returncode"] == 0:
            add_log(task_gid, f"[{repo_entry['id']}] Auto-fix attempt completed")
            return True

        add_log(task_gid, f"[{repo_entry['id']}] Auto-fix failed (exit {result['returncode']})", "error")
        return False

    except Exception as e:
        add_log(task_gid, f"[{repo_entry['id']}] Auto-fix failed: {e}", "error")
        return False


# ─── QA Review ───

async def _agent_qa_review(task_gid: str, task: dict, run: dict) -> Optional[str]:
    """Run QA review: analyze diffs vs task requirements using Claude CLI."""
    try:
        update_phase(task_gid, AgentPhase.QA_REVIEW)
        await _broadcast_state(task_gid)
        add_log(task_gid, "Starting QA review...")

        diff_context = ""
        for repo_entry in run.get("repos", []):
            wt_path = repo_entry.get("worktree_path")
            if not wt_path:
                continue
            default_branch = repo_entry.get("default_branch", "master")
            repo_id = repo_entry["id"]

            try:
                log_result = subprocess.run(
                    ["git", "log", "--oneline", f"origin/{default_branch}...HEAD"],
                    cwd=wt_path, capture_output=True, text=True, timeout=15
                )
                commits = log_result.stdout.strip() if log_result.returncode == 0 else "(no commits)"

                stat_result = subprocess.run(
                    ["git", "diff", "--stat", f"origin/{default_branch}...HEAD"],
                    cwd=wt_path, capture_output=True, text=True, timeout=15
                )
                stat = stat_result.stdout.strip() if stat_result.returncode == 0 else ""

                diff_result = subprocess.run(
                    ["git", "diff", f"origin/{default_branch}...HEAD"],
                    cwd=wt_path, capture_output=True, text=True, timeout=30
                )
                full_diff = diff_result.stdout[:15000] if diff_result.returncode == 0 else ""

                diff_context += (
                    f"\n### Repo: {repo_id}\n"
                    f"**Commits:**\n```\n{commits}\n```\n\n"
                    f"**Changed files:**\n```\n{stat}\n```\n\n"
                    f"**Diff:**\n```diff\n{full_diff}\n```\n"
                )
            except Exception as e:
                diff_context += f"\n### Repo: {repo_id}\n(Failed to get diff: {e})\n"

        if not diff_context.strip():
            add_log(task_gid, "QA review skipped — no diffs found", "warning")
            return None

        task_name = task.get("name", "Unknown")
        task_notes = task.get("notes", "")
        subtasks = await fetch_subtasks(task_gid)
        subtask_text = "\n".join(
            f"- {'✓' if s.get('completed') else '○'} {s.get('name', '?')}"
            + (f"\n  {s.get('notes', '')[:300]}" if s.get("notes") else "")
            for s in subtasks
        ) or "(no subtasks)"

        comments_context = await _fetch_task_comments(task_gid)

        prompt = (
            f"## QA Review\n\n"
            f"**Task:** {task_name}\n"
            f"**Description:** {task_notes[:2000]}\n\n"
            f"**Subtasks:**\n{subtask_text}\n\n"
            f"{comments_context}\n\n"
            f"## Implementation\n{diff_context}\n\n"
            f"## Instructions\n"
            f"Analyze the implementation against the task requirements. Provide a structured QA report:\n\n"
            f"1. **Requirements Coverage** — For each subtask/requirement, state if it's addressed by the commits (YES/PARTIAL/NO with brief reason)\n"
            f"2. **Code Quality** — Any obvious bugs, edge cases, or issues in the diff\n"
            f"3. **Missing Items** — Anything the task requires that isn't in the implementation\n"
            f"4. **Verdict** — PASS (ready for delivery) or FAIL (needs fixes, list what)\n\n"
            f"Be concise and specific. Reference file names and line numbers when flagging issues.\n\n"
            f"IMPORTANT: Keep the entire report under 3000 characters. Do NOT reproduce code from the diff. "
            f"Only reference file names and brief descriptions of issues."
        )

        cwd = "/tmp"
        for repo_entry in run.get("repos", []):
            if repo_entry.get("worktree_path"):
                cwd = repo_entry["worktree_path"]
                break

        result = await _run_claude_cli(
            prompt=prompt,
            cwd=cwd,
            max_turns=1,
            allowed_tools=[],
            system_prompt=(
                "You are a senior QA reviewer. Analyze the implementation diffs against "
                "the task requirements. Be thorough but concise. Focus on whether requirements "
                "are met and flag any real issues. Do NOT suggest style changes or minor nitpicks."
            ),
            task_gid=task_gid,
        )

        try:
            _accumulate_cost(task_gid, result)
        except Exception as e:
            log.warning(f"Failed to accumulate QA cost: {e}")

        qa_text = result.get("text", "").strip()
        if not qa_text:
            add_log(task_gid, "QA review returned empty response", "warning")
            return None

        if qa_text.startswith("{") and '"type"' in qa_text[:100]:
            add_log(task_gid, "QA response contains raw stream JSON — extracting text", "warning")
            # Log event types to help debug extraction failures
            try:
                event_types = {}
                for raw_line in qa_text.split("\n"):
                    if raw_line.strip().startswith("{"):
                        ev = json.loads(raw_line.strip())
                        et = ev.get("type", "?")
                        event_types[et] = event_types.get(et, 0) + 1
                add_log(task_gid, f"Stream event types: {event_types}", "debug")
            except Exception:
                pass
            extracted = extract_text_from_stream(qa_text)
            if not extracted:
                add_log(task_gid, "Could not extract QA text from stream", "warning")
                return None
            qa_text = extracted

        if len(qa_text) > 10000:
            add_log(task_gid, f"QA response too large ({len(qa_text)} chars), truncating to 10K", "warning")
            qa_text = qa_text[:10000]

        add_log(task_gid, f"QA review generated ({len(qa_text)} chars)")

        qa_passed = _qa_verdict_is_pass(qa_text)

        run = load_agent_run(task_gid)
        run["qa_report"] = qa_text

        if qa_passed:
            run["question"] = None
            save_agent_run(task_gid, run)
            add_log(task_gid, "QA verdict: PASS — auto-approved")
            await _post_asana_comment(task_gid, f"🔍 QA Review (PASS):\n\n{qa_text[:3000]}", dedup_prefix="🔍 QA Review")
            await _broadcast_state(task_gid)
            return qa_text
        else:
            run["question"] = {
                "text": qa_text,
                "type": "qa_review",
                "options": ["Approve", "Reject"],
                "asked_at": datetime.now(timezone.utc).isoformat(),
                "answer": None,
            }
            save_agent_run(task_gid, run)
            add_log(task_gid, "QA verdict: FAIL — waiting for your decision")
            await _post_asana_comment(task_gid, f"🔍 QA Review (FAIL):\n\n{qa_text[:3000]}", dedup_prefix="🔍 QA Review")
            await _broadcast_state(task_gid)
            return qa_text

    except Exception as e:
        add_log(task_gid, f"QA review failed: {e}", "error")
        log.exception("QA review error for task %s", task_gid)
        return None


# ─── Manual Flows ───

async def trigger_manual_qa(task_gid: str, task: dict):
    """Manually trigger QA review on a task that has worktrees with code to review."""
    if task_gid in _active_workers and not _active_workers[task_gid].done():
        raise ValueError(f"Agent already running for task {task_gid}")

    run = load_agent_run(task_gid)
    if not run:
        raise ValueError(f"No agent run found for {task_gid}")
    allowed_phases = (AgentPhase.DONE.value, AgentPhase.ERROR.value, AgentPhase.CANCELLED.value)
    if run["phase"] not in allowed_phases:
        raise ValueError(f"Task is in phase '{run['phase']}', expected done/error/cancelled")
    has_worktree = any(r.get("worktree_path") for r in run.get("repos", []))
    if not has_worktree:
        raise ValueError("No worktree found — nothing to review")

    async def _run_manual_qa():
        try:
            current_run = load_agent_run(task_gid)
            current_run["question"] = None
            current_run["qa_report"] = None
            save_agent_run(task_gid, current_run)
            qa_report = await _agent_qa_review(task_gid, task, current_run)
            if not qa_report:
                update_phase(task_gid, AgentPhase.DONE)
                await _broadcast_state(task_gid)
                return

            # QA auto-approved (PASS) — skip human review
            current_run = load_agent_run(task_gid)
            if not current_run.get("question"):
                add_log(task_gid, "QA auto-approved")
                update_phase(task_gid, AgentPhase.DONE)
                await _broadcast_state(task_gid)
                return

            pre_answer = current_run.get("question", {}).get("answer") if current_run.get("question") else None
            if pre_answer:
                add_log(task_gid, f"QA answer already received: {pre_answer[:50]}")
                answer = pre_answer
            else:
                add_log(task_gid, "Waiting for QA approval...")
                while True:
                    await asyncio.sleep(2)
                    current_run = load_agent_run(task_gid)
                    if not current_run:
                        add_log(task_gid, "Run data missing — aborting", "error")
                        return
                    if current_run.get("phase") in (AgentPhase.CANCELLED.value, AgentPhase.ERROR.value):
                        add_log(task_gid, f"Phase changed to {current_run['phase']} — aborting")
                        return
                    q = current_run.get("question")
                    if q and q.get("answer"):
                        answer = q["answer"]
                        add_log(task_gid, f"Answer received in poll: {answer[:50]}")
                        break

            if answer.strip().lower() in ("approve", "yes", "lgtm"):
                add_log(task_gid, "QA approved")
                current_run = load_agent_run(task_gid)
                current_run["question"] = None
                save_agent_run(task_gid, current_run)
                update_phase(task_gid, AgentPhase.DONE)
                await _broadcast_state(task_gid)
                return

            # QA rejected — loop: coding → rebase → test → QA until approved
            add_log(task_gid, "QA rejected — starting fix cycle")
            user_feedback = ""
            ans_lower = answer.strip().lower()
            if ans_lower.startswith("reject"):
                user_feedback = answer.strip()[len("reject"):].lstrip(": ").strip()
            elif ans_lower not in ("no", "reject", "fix", "redo"):
                user_feedback = answer.strip()
            qa_feedback = _build_fix_instructions(qa_report, user_feedback)

            comments_context = await _fetch_task_comments(task_gid)
            subtasks_context = await _fetch_subtasks_context(task_gid)
            branch_state = _get_branch_state(current_run)
            task_context = _build_task_context(task, current_run) + comments_context + subtasks_context + branch_state

            while True:
                current_run = load_agent_run(task_gid)
                update_phase(task_gid, AgentPhase.CODING)
                await _broadcast_state(task_gid)

                coding_context = task_context + f"\n\n{qa_feedback}\n\nIMPORTANT: Your code was reviewed and needs fixes. Focus ONLY on fixing the specific issues listed above. Do NOT rewrite code that is already working. Make targeted, minimal fixes."
                current_run["qa_report"] = None
                current_run["question"] = None
                for repo_entry in current_run["repos"]:
                    if repo_entry.get("worktree_path") and repo_entry["status"] == "done":
                        repo_entry["status"] = "coding"
                save_agent_run(task_gid, current_run)

                coded_any = False
                for repo_entry in current_run["repos"]:
                    if not repo_entry.get("worktree_path") or repo_entry["status"] == "done":
                        continue
                    save_agent_run(task_gid, current_run)

                    success = await _agent_code(task_gid, coding_context, current_run, repo_entry)
                    if not success:
                        return
                    coded_any = True
                    repo_entry["status"] = "done"
                    save_agent_run(task_gid, current_run)

                if not coded_any:
                    update_phase(task_gid, AgentPhase.ERROR, error="No repos coded during QA fix")
                    await _broadcast_state(task_gid)
                    return

                for repo_entry in current_run["repos"]:
                    if repo_entry.get("worktree_path"):
                        success = await _rebase_from_default(task_gid, repo_entry)
                        if not success:
                            return

                update_phase(task_gid, AgentPhase.TESTING)
                await _broadcast_state(task_gid)
                for repo_entry in current_run["repos"]:
                    repo = get_repo(repo_entry["id"])
                    if repo and repo_entry.get("worktree_path"):
                        test_cmd = _select_test_cmd(repo, repo_entry["worktree_path"])
                        if test_cmd:
                            test_cwd = repo["path"] if (repo.get("test_docker_cmd") and not repo.get("test_worktree_cmd") and not repo.get("test_worktree_cmd_fast")) else repo_entry["worktree_path"]
                            success = await _agent_test(task_gid, repo_entry, test_cmd, test_cwd)
                            if not success:
                                return

                current_run = load_agent_run(task_gid)
                qa_report = await _agent_qa_review(task_gid, task, current_run)
                if not qa_report:
                    break

                # QA auto-approved (PASS) — done
                current_run = load_agent_run(task_gid)
                if not current_run.get("question"):
                    add_log(task_gid, "QA auto-approved after fixes")
                    break

                add_log(task_gid, "Waiting for QA approval (fix cycle)...")
                while True:
                    await asyncio.sleep(2)
                    current_run = load_agent_run(task_gid)
                    if not current_run:
                        add_log(task_gid, "Run data missing — aborting", "error")
                        return
                    if current_run.get("phase") in (AgentPhase.CANCELLED.value, AgentPhase.ERROR.value):
                        add_log(task_gid, f"Phase changed to {current_run['phase']} — aborting")
                        return
                    q = current_run.get("question")
                    if q and q.get("answer"):
                        answer = q["answer"]
                        add_log(task_gid, f"Answer received in poll: {answer[:50]}")
                        break

                if answer.strip().lower() in ("approve", "yes", "lgtm"):
                    add_log(task_gid, "QA approved after fixes")
                    break
                else:
                    user_fb = ""
                    ans_lo = answer.strip().lower()
                    if ans_lo.startswith("reject"):
                        user_fb = answer.strip()[len("reject"):].lstrip(": ").strip()
                    elif ans_lo not in ("no", "reject", "fix", "redo"):
                        user_fb = answer.strip()
                    qa_feedback = _build_fix_instructions(qa_report, user_fb)
                    current_run = load_agent_run(task_gid)
                    current_run["question"] = None
                    for repo_entry in current_run["repos"]:
                        if repo_entry.get("worktree_path") and repo_entry["status"] == "done":
                            repo_entry["status"] = "coding"
                    save_agent_run(task_gid, current_run)
                    add_log(task_gid, "QA rejected — looping back to coding")
                    await _broadcast_state(task_gid)
                    continue

            # DONE
            update_phase(task_gid, AgentPhase.DONE)
            await _broadcast_state(task_gid)
            add_log(task_gid, "Agent completed after QA fixes")

        except asyncio.CancelledError:
            update_phase(task_gid, AgentPhase.CANCELLED)
            raise
        except Exception as e:
            log.exception("Manual QA error for %s", task_gid)
            update_phase(task_gid, AgentPhase.ERROR, error=str(e))
            add_log(task_gid, f"Manual QA error: {e}", "error")
            await _broadcast_state(task_gid)
        finally:
            _active_workers.pop(task_gid, None)
            agent_queue.unregister_running(task_gid)

    worker = asyncio.create_task(_run_manual_qa())
    _active_workers[task_gid] = worker
    agent_queue.register_running(task_gid, worker)
    return {"status": "qa_started", "task_gid": task_gid}


async def run_manual_tests(task_gid: str) -> dict:
    """Run tests manually on a task's worktree(s) without the full agent pipeline."""
    run = load_agent_run(task_gid)
    if not run:
        raise ValueError(f"No agent run found for task {task_gid}")
    if run.get("is_active"):
        raise ValueError("Agent is currently active — stop it first")

    repos_with_worktrees = [r for r in run.get("repos", []) if r.get("worktree_path")]
    if not repos_with_worktrees:
        raise ValueError("No worktrees found for this task")

    prev_phase = AgentPhase(run["phase"])
    update_phase(task_gid, AgentPhase.TESTING)
    await _broadcast_state(task_gid)

    results = []
    all_passed = True

    for repo_entry in repos_with_worktrees:
        repo = get_repo(repo_entry["id"])
        if not repo:
            continue
        test_cmd = _select_test_cmd(repo, repo_entry["worktree_path"])
        if not test_cmd:
            add_log(task_gid, f"[{repo_entry['id']}] No test command configured", "warning")
            results.append({"repo": repo_entry["id"], "passed": None, "message": "No test command"})
            continue

        test_cwd = repo["path"] if (repo.get("test_docker_cmd") and not repo.get("test_worktree_cmd") and not repo.get("test_worktree_cmd_fast")) else repo_entry["worktree_path"]
        add_log(task_gid, f"[{repo_entry['id']}] Starting manual test run...")

        returncode, full_output = await _run_test_with_progress(
            task_gid, repo_entry["id"], test_cmd, test_cwd,
        )

        passed = returncode == 0
        if not passed:
            all_passed = False
        results.append({
            "repo": repo_entry["id"],
            "passed": passed,
            "message": "Tests passed" if passed else full_output[-500:],
        })

    update_phase(task_gid, prev_phase if all_passed else AgentPhase.ERROR,
                 error=None if all_passed else "Manual tests failed")
    await _broadcast_state(task_gid)

    return {"task_gid": task_gid, "results": results, "all_passed": all_passed}
