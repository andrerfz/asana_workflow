"""Agent execution engine — start, stop, plan, code, test, QA, and manual flows.

Phase implementations live in the pipeline/ subpackage. This module contains
only the public API (start/stop/resume/answer/guide/chat) and the main
orchestration loops that wire the phases together.
"""
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from .phases import AgentPhase
from .state import (
    AGENT_RUNS_DIR,
    _active_workers, _broadcast_state, _accumulate_cost,
    load_agent_run, save_agent_run, create_agent_run,
    add_log, update_phase, clear_agent_run, add_conversation_message,
    get_agent_status, list_active_agents, get_worktree_diff,
    load_run_history, load_agent_settings, save_agent_settings,
    _check_secrets, _sync_agent_files,
    register_event_callback,
)
from .claude_client import check_claude_code_status, _run_claude_cli, kill_active_claude
from .asana_helpers import (
    _move_task_section, _post_asana_comment, _auto_complete_subtasks,
    _fetch_subtasks_context, _get_branch_state, _fetch_task_comments,
    _build_fix_instructions,
)
from .queue import agent_queue
from ..services.repo_manager import get_repo, get_repos_for_task
from ..services.worktree_manager import create_worktree
from ..services.asana_client import fetch_subtasks
from .memory import update_memory_after_run

# Pipeline phase implementations
from .pipeline import (
    AgentTimer, agent_timers, check_timeout,
    build_task_context, load_claude_md_guides, parse_additional_repos,
    agent_investigate, agent_plan, agent_code,
    rebase_from_default, agent_test, select_test_cmd,
    agent_qa_review, quality_checks, agent_finalize,
)

log = logging.getLogger(__name__)


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
        settings = load_agent_settings()
        timeout_minutes = settings.get("agent_timeout_minutes", 45)
        agent_timers[task_gid] = AgentTimer(timeout_minutes * 60)

        async def run_with_timeout():
            try:
                return await _run_agent(task_gid, task)
            finally:
                agent_timers.pop(task_gid, None)

        worker = asyncio.create_task(run_with_timeout())
        _active_workers[task_gid] = worker  # replace sentinel with actual worker
        agent_queue.register_running(task_gid, worker)
        return load_agent_run(task_gid)
    except Exception:
        _active_workers.pop(task_gid, None)
        raise


async def resume_agent(task_gid: str, task: dict, feedback: str) -> dict:
    """Resume a done/error agent with user feedback, reusing existing worktrees."""
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
        missing_repos = parse_additional_repos(prev_investigation, {"repos": valid_repos})
        if missing_repos:
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
        agent_timers[task_gid] = AgentTimer(timeout_minutes * 60)

        async def run_resumed():
            try:
                return await _run_agent_resumed(
                    task_gid, task, feedback,
                    prev_plan, prev_investigation, prev_error,
                )
            finally:
                agent_timers.pop(task_gid, None)

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

    run["pending_guide"] = {
        "feedback": feedback,
        "session_id": session_id,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }
    save_agent_run(task_gid, run)
    add_conversation_message(task_gid, "user", feedback)
    add_log(task_gid, f"Guide signal stored. Terminating active Claude process...")

    killed = await kill_active_claude(task_gid)
    if killed:
        add_log(task_gid, "Claude process terminated — will resume with guidance")
    else:
        add_log(task_gid, "No active Claude process found (may have just finished)", "warning")

    return True


async def chat_agent(task_gid: str, message: str) -> str:
    """Run a read-only chat turn with the agent."""
    try:
        run = load_agent_run(task_gid)
        if not run:
            raise ValueError("No agent run found")

        repo_entry = next((r for r in run.get("repos", []) if r.get("worktree_path")), None)
        if not repo_entry:
            raise ValueError("No worktree available for this task")

        wt_path = repo_entry["worktree_path"]
        plan = run.get("plan", "")
        qa_report = run.get("qa_report", "")

        context_parts = [f"Task: {run.get('task_name', task_gid)}"]
        if plan:
            context_parts.append(f"Plan:\n{plan[:800]}")
        if qa_report:
            context_parts.append(f"QA Report:\n{qa_report[:800]}")
        context = "\n\n".join(context_parts)

        add_conversation_message(task_gid, "user", message)
        add_log(task_gid, "[chat] Thinking...", "debug")

        from .state import _emit_event

        collected_chunks: list[str] = []

        async def _on_chunk(chunk: str):
            collected_chunks.append(chunk)
            await _emit_event("agent:chat_token", {"task_gid": task_gid, "chunk": chunk})

        result = await _run_claude_cli(
            prompt=f"{context}\n\n---\nUser question: {message}\n\nAnswer based on the actual code in the worktree. Be concise.",
            cwd=wt_path,
            max_turns=5,
            allowed_tools=["Read", "Glob", "Grep", "LS", "Bash(git log:*)", "Bash(git diff:*)", "Bash(find:*)", "Bash(ls:*)"],
            system_prompt=(
                "You are a senior developer answering questions about the current state of the code. "
                "Read-only access only — do NOT modify files, do NOT commit. "
                "Answer concisely and factually based on what you find in the code."
            ),
            task_gid=task_gid,
            subprocess_timeout=300.0,
            on_text_chunk=_on_chunk,
        )

        # Signal end of stream
        await _emit_event("agent:chat_token", {"task_gid": task_gid, "chunk": None, "done": True})

        # Use streamed chunks first; fall back to result event text (never raw JSON)
        response = "".join(collected_chunks).strip()
        if not response:
            parsed = result.get("parsed") or {}
            response = (parsed.get("result") or "").strip()
        if not response:
            response = "No response — Claude may have timed out or returned empty output."
        add_conversation_message(task_gid, "agent", response)
        return response

    except Exception as e:
        log.exception("chat_agent failed for %s", task_gid)
        error_msg = f"Error: {e}"
        add_conversation_message(task_gid, "agent", error_msg)
        return error_msg


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

        task_context = build_task_context(task, run) + comments_context + subtasks_context + qa_context + branch_state

        # Asana: move task to "Desarrollo"
        settings = load_agent_settings()
        if settings.get("section_on_start"):
            await _move_task_section(task_gid, settings["section_on_start"])

        # Phase: INVESTIGATING
        update_phase(task_gid, AgentPhase.INVESTIGATING)
        await _broadcast_state(task_gid)
        add_log(task_gid, "Investigating codebase...")

        investigation = await agent_investigate(task_gid, task_context, run)
        if investigation:
            run = load_agent_run(task_gid)
            run["investigation"] = investigation
            save_agent_run(task_gid, run)
            task_context += f"\n\n## Investigation Report\n{investigation}"

            # Check if investigation recommends additional repos
            try:
                additional = parse_additional_repos(investigation, run)
            except Exception as e:
                log.exception("Failed to parse additional repos from investigation")
                add_log(task_gid, f"Failed to parse additional repos: {e}", "warning")
                additional = []
            if additional:
                add_log(task_gid, f"Investigation recommends additional repos: {', '.join(additional)}")
                existing_branch = next((r.get("branch", "") for r in run["repos"] if r.get("branch")), "")
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
                task_context = build_task_context(task, run) + comments_context + subtasks_context + qa_context + branch_state
                task_context += f"\n\n## Investigation Report\n{investigation}"

        # Phase: PLANNING
        update_phase(task_gid, AgentPhase.PLANNING)
        await _broadcast_state(task_gid)

        plan = await agent_plan(task_gid, task_context, run)
        if not plan:
            return

        run = load_agent_run(task_gid)
        run["plan"] = plan
        save_agent_run(task_gid, run)
        add_log(task_gid, f"Plan generated ({len(plan)} chars)")

        await _post_asana_comment(task_gid, f"🤖 Agent Plan:\n\n{plan[:3000]}", dedup_prefix="🤖 Agent Plan:")

        # Phase: AWAITING APPROVAL (loop supports revise feedback)
        while True:
            update_phase(task_gid, AgentPhase.AWAITING_APPROVAL)
            await _broadcast_state(task_gid)
            add_log(task_gid, "Waiting for plan approval...")

            timer = agent_timers.get(task_gid)
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
                plan = await agent_plan(task_gid, revised_context, run)
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

            run = load_agent_run(task_gid)
            run["question"] = None
            save_agent_run(task_gid, run)
            break

        # ═══ CODING → TESTING → QA LOOP ═══
        await _coding_test_qa_loop(task_gid, task, task_context, run)

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

        task_context = build_task_context(task, run) + comments_context + subtasks_context + branch_state

        if prev_investigation:
            task_context += f"\n\n## Investigation Report (from previous run)\n{prev_investigation}"
        if prev_plan:
            task_context += f"\n\n## Implementation Plan (from previous run)\n{prev_plan}"

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

        settings = load_agent_settings()
        if settings.get("section_on_start"):
            await _move_task_section(task_gid, settings["section_on_start"])

        # Jump directly to coding → testing → QA loop
        await _coding_test_qa_loop(task_gid, task, task_context, run, resumed=True)

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


# ─── Shared Coding → Testing → QA Loop ───

async def _wait_for_answer(task_gid: str) -> str | None:
    """Poll for a human answer. Returns None if run is cancelled/missing."""
    while True:
        await asyncio.sleep(2)
        run = load_agent_run(task_gid)
        if not run:
            add_log(task_gid, "Run data missing — aborting", "error")
            return None
        if run.get("phase") in (AgentPhase.CANCELLED.value, AgentPhase.ERROR.value):
            add_log(task_gid, f"Phase changed to {run['phase']} — aborting")
            return None
        q = run.get("question")
        if q and q.get("answer"):
            answer = q["answer"]
            add_log(task_gid, f"Answer received: {answer[:50]}")
            return answer


def _extract_user_feedback(answer: str) -> str:
    """Extract user feedback text from a QA rejection answer."""
    ans_lower = answer.strip().lower()
    if ans_lower.startswith("reject"):
        return answer.strip()[len("reject"):].lstrip(": ").strip()
    if ans_lower not in ("no", "reject", "fix", "redo"):
        return answer.strip()
    return ""


async def _coding_test_qa_loop(task_gid: str, task: dict, task_context: str,
                               run: dict, resumed: bool = False,
                               initial_qa_feedback: str = ""):
    """Core loop: code → rebase → test → QA → approve/reject. Used by fresh, resumed, and manual QA runs."""
    qa_feedback = initial_qa_feedback
    while True:
        if check_timeout(task_gid):
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
            if not resumed:
                add_log(task_gid, f"[{repo_entry['id']}] Repo status: {repo_entry['status']} | worktree: {bool(repo_entry.get('worktree_path'))}")
            save_agent_run(task_gid, run)

            success = await agent_code(task_gid, coding_context, run, repo_entry)
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

        # Rebase onto latest default branch before testing
        for repo_entry in run["repos"]:
            if repo_entry.get("worktree_path"):
                success = await rebase_from_default(task_gid, repo_entry)
                if not success:
                    return

        # Phase: TESTING
        if check_timeout(task_gid):
            return
        update_phase(task_gid, AgentPhase.TESTING)
        await _broadcast_state(task_gid)

        for repo_entry in run["repos"]:
            repo = get_repo(repo_entry["id"])
            if repo and repo_entry.get("worktree_path"):
                test_cmd = select_test_cmd(repo, repo_entry["worktree_path"])
                if test_cmd:
                    test_cwd = repo["path"] if (repo.get("test_docker_cmd") and not repo.get("test_worktree_cmd") and not repo.get("test_worktree_cmd_fast")) else repo_entry["worktree_path"]
                    success = await agent_test(task_gid, repo_entry, test_cmd, test_cwd)
                    if not success:
                        return

        # Quality checks — fed into QA as hard evidence
        quality = await quality_checks(task_gid, run)
        run = load_agent_run(task_gid)
        run["quality_checks"] = quality
        save_agent_run(task_gid, run)
        if quality:
            passed = sum(1 for c in quality if c["passed"])
            total = len(quality)
            add_log(task_gid, f"Quality: {passed}/{total} checks passed")

        # Phase: QA REVIEW — pass quality results so QA can reference them
        qa_report = await agent_qa_review(task_gid, task, run, quality_results=quality)
        if qa_report is None:
            add_log(task_gid, "QA review failed to produce a report — retrying in 30s...", "warning")
            await asyncio.sleep(30)
            qa_report = await agent_qa_review(task_gid, task, run, quality_results=quality)
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
        timer = agent_timers.get(task_gid)
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
            user_feedback = _extract_user_feedback(qa_answer)
            qa_feedback = _build_fix_instructions(qa_report, user_feedback)
            # Store user feedback so next QA review focuses on it
            run = load_agent_run(task_gid)
            run["resume_feedback"] = user_feedback or "Fix the issues flagged by QA"
            save_agent_run(task_gid, run)
            add_log(task_gid, f"QA rejected — looping back to coding with feedback")
            await _broadcast_state(task_gid)
            continue

    # ═══ END CODING-QA LOOP — FINALIZE → DONE ═══

    # Phase: FINALIZING — auto-cleanup (squash commits, lint fix, push)
    run = load_agent_run(task_gid)
    await agent_finalize(task_gid, run)

    # Phase: DONE
    label = " (resumed run)" if resumed else ""
    update_phase(task_gid, AgentPhase.DONE)
    await _broadcast_state(task_gid)
    add_log(task_gid, f"Agent completed successfully{label}")

    settings = load_agent_settings()
    if settings.get("section_on_done"):
        await _move_task_section(task_gid, settings["section_on_done"])
    run = load_agent_run(task_gid)
    branches = ", ".join(r.get("branch", "?") for r in run.get("repos", []))
    commit_total = sum(r.get("commits", 0) for r in run.get("repos", []))
    resumed_label = " (resumed)" if resumed else ""
    await _post_asana_comment(
        task_gid,
        f"🤖 Agent completed{resumed_label}.\n\nBranches: {branches}\nCommits: {commit_total}\n\n"
        f"Review the changes and merge when ready.",
        dedup_prefix=f"🤖 Agent completed{resumed_label}."
    )

    await _auto_complete_subtasks(task_gid, run)

    for repo_entry in run.get("repos", []):
        update_memory_after_run(repo_entry["id"], task_gid, run)


# ─── Manual Flows ───

async def trigger_manual_qa(task_gid: str, task: dict):
    """Manually trigger QA review on a task that has worktrees with code to review.

    Runs QA first. If QA passes → done. If QA fails and user rejects →
    enters the shared coding→test→QA loop to fix issues.
    """
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

            # Run quality checks + QA review
            quality = await quality_checks(task_gid, current_run)
            current_run = load_agent_run(task_gid)
            current_run["quality_checks"] = quality
            save_agent_run(task_gid, current_run)

            qa_report = await agent_qa_review(task_gid, task, current_run, quality_results=quality)
            if qa_report is None:
                add_log(task_gid, "QA review failed — retrying in 30s...", "warning")
                await asyncio.sleep(30)
                qa_report = await agent_qa_review(task_gid, task, current_run, quality_results=quality)
            if not qa_report:
                add_log(task_gid, "QA review could not produce a report", "error")
                update_phase(task_gid, AgentPhase.ERROR, error="QA review failed to produce a report")
                await _broadcast_state(task_gid)
                return

            # QA auto-approved (PASS)
            current_run = load_agent_run(task_gid)
            if not current_run.get("question"):
                add_log(task_gid, "QA auto-approved")
                update_phase(task_gid, AgentPhase.DONE)
                await _broadcast_state(task_gid)
                return

            # Wait for human QA decision
            answer = await _wait_for_answer(task_gid)
            if answer is None:
                return

            if answer.strip().lower() in ("approve", "yes", "lgtm"):
                add_log(task_gid, "QA approved")
                current_run = load_agent_run(task_gid)
                current_run["question"] = None
                save_agent_run(task_gid, current_run)
                update_phase(task_gid, AgentPhase.DONE)
                await _broadcast_state(task_gid)
                return

            # QA rejected — build context and enter shared coding→test→QA loop
            add_log(task_gid, "QA rejected — starting fix cycle")
            comments_context = await _fetch_task_comments(task_gid)
            subtasks_context = await _fetch_subtasks_context(task_gid)
            branch_state = _get_branch_state(current_run)
            task_context = build_task_context(task, current_run) + comments_context + subtasks_context + branch_state

            # Inject the QA rejection as initial qa_feedback so the loop starts with fixes
            user_feedback = _extract_user_feedback(answer)
            initial_qa_feedback = _build_fix_instructions(qa_report, user_feedback)

            await _coding_test_qa_loop(task_gid, task, task_context, current_run,
                                       initial_qa_feedback=initial_qa_feedback)

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
        test_cmd = select_test_cmd(repo, repo_entry["worktree_path"])
        if not test_cmd:
            add_log(task_gid, f"[{repo_entry['id']}] No test command configured", "warning")
            results.append({"repo": repo_entry["id"], "passed": None, "message": "No test command"})
            continue

        test_cwd = repo["path"] if (repo.get("test_docker_cmd") and not repo.get("test_worktree_cmd") and not repo.get("test_worktree_cmd_fast")) else repo_entry["worktree_path"]
        add_log(task_gid, f"[{repo_entry['id']}] Starting manual test run...")

        from .pipeline.test import run_test_with_progress
        returncode, full_output = await run_test_with_progress(
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
