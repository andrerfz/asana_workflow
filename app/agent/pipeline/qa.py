"""QA review phase — analyze diffs vs task requirements."""
import json
import logging
import subprocess
from datetime import datetime, timezone
from typing import Optional

from ..phases import AgentPhase
from ..claude_client import _run_claude_cli
from ..state import add_log, update_phase, load_agent_run, save_agent_run, _accumulate_cost, _broadcast_state
from ..asana_helpers import _post_asana_comment, _qa_verdict_is_pass, _fetch_task_comments
from ..stream_parser import extract_text_from_stream
from ...services.repo_manager import get_repo
from ...services.asana_client import fetch_subtasks

log = logging.getLogger(__name__)


async def quality_checks(task_gid: str, run: dict) -> list[dict]:
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


async def agent_qa_review(task_gid: str, task: dict, run: dict,
                          quality_results: list[dict] = None) -> Optional[str]:
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

        # Build quality checks section (informational, not blocking)
        quality_section = ""
        if quality_results:
            quality_lines = []
            for c in quality_results:
                icon = "✓" if c["passed"] else "✗"
                quality_lines.append(f"  {icon} [{c['repo']}] {c['check']} — {c['detail']}")
            quality_section = (
                f"\n## Automated Quality Checks (informational)\n"
                + "\n".join(quality_lines) + "\n"
            )

        # Check if this is a re-review after user rejection (focus on specific feedback)
        user_rejection_context = ""
        prev_qa = run.get("qa_report", "")
        resume_feedback = run.get("resume_feedback", "")
        if prev_qa or resume_feedback:
            user_rejection_context = "\n## IMPORTANT CONTEXT\n"
            if resume_feedback:
                user_rejection_context += (
                    f"The user resumed this task with specific feedback:\n"
                    f'"{resume_feedback}"\n\n'
                    f"Focus your review primarily on whether THIS SPECIFIC ISSUE was addressed.\n"
                )

        prompt = (
            f"## QA Review\n\n"
            f"**Task:** {task_name}\n"
            f"**Description:** {task_notes[:2000]}\n\n"
            f"**Subtasks:**\n{subtask_text}\n\n"
            f"{comments_context}\n\n"
            f"{user_rejection_context}"
            f"{quality_section}\n"
            f"## Implementation\n{diff_context}\n\n"
            f"## Instructions\n"
            f"Review the implementation against the task requirements:\n\n"
            f"1. **Requirements** — For each subtask, state DONE / PARTIAL / MISSING\n"
            f"2. **Real Bugs Only** — Flag actual bugs: logic errors, SQL injection, data corruption, crashes. "
            f"Do NOT flag: commit message format, code style, hypothetical edge cases, truncated diffs, "
            f"or files that seem unrelated (the developer may have valid reasons).\n"
            f"3. **Verdict** — PASS or FAIL.\n"
            f"   - PASS if the core task requirements are met and no real bugs found\n"
            f"   - FAIL only for: missing requirements, actual bugs, or security issues\n"
            f"   - Do NOT fail for: cosmetic issues, commit format, informational warnings\n\n"
            f"Keep under 2000 characters. Be concise."
        )

        cwd = "/tmp"
        for repo_entry in run.get("repos", []):
            if repo_entry.get("worktree_path"):
                cwd = repo_entry["worktree_path"]
                break

        result = await _run_claude_cli(
            prompt=prompt,
            cwd=cwd,
            max_turns=3,
            allowed_tools=[],
            system_prompt=(
                "You are a pragmatic QA reviewer. Your goal is to verify that the task requirements "
                "are met and catch real bugs. You are NOT looking for perfection — you are checking "
                "if the code solves the problem and doesn't break anything. "
                "Only FAIL for things that would actually cause problems in production. "
                "Commit format, code style, and minor warnings are NOT reasons to fail."
            ),
            task_gid=task_gid,
            model="opus",
        )

        try:
            _accumulate_cost(task_gid, result)
        except Exception as e:
            log.warning(f"Failed to accumulate QA cost: {e}")

        qa_text = result.get("text", "").strip()
        if not qa_text:
            # Diagnostic: check what the result dict actually contains
            rc = result.get("returncode")
            stderr = (result.get("stderr") or "")[:300]
            has_parsed = "parsed" in result
            raw_len = len(result.get("raw_output", ""))
            # Count event types in raw output for debugging
            event_types = {}
            for raw_line in result.get("raw_output", "").split("\n"):
                raw_line = raw_line.strip()
                if raw_line.startswith("{"):
                    try:
                        ev = json.loads(raw_line)
                        et = ev.get("type", "?")
                        event_types[et] = event_types.get(et, 0) + 1
                    except json.JSONDecodeError:
                        pass
            add_log(task_gid, f"QA empty text (exit={rc}, parsed={has_parsed}, raw_len={raw_len}, events={event_types})", "warning")
            # Fallback 1: try parsed result event
            if has_parsed:
                parsed_text = (result["parsed"].get("result") or "").strip()
                if parsed_text:
                    add_log(task_gid, f"Recovered {len(parsed_text)} chars from parsed result event")
                    qa_text = parsed_text
            # Fallback 2: try extracting from raw stream output
            if not qa_text and raw_len > 0:
                from ..stream_parser import extract_result_from_stream_lines
                raw_lines = result.get("raw_output", "").split("\n")
                extracted = extract_result_from_stream_lines(raw_lines)
                if extracted:
                    # If it looks like JSON stream, try text extraction
                    if extracted.startswith("{"):
                        from ..stream_parser import extract_text_from_stream
                        extracted = extract_text_from_stream(extracted) or ""
                    if extracted:
                        add_log(task_gid, f"Recovered {len(extracted)} chars from raw stream lines")
                        qa_text = extracted
            if not qa_text:
                return None

        if qa_text.startswith("{") and '"type"' in qa_text[:100]:
            add_log(task_gid, "QA response contains raw stream JSON — extracting text", "warning")
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

        # Treat very short responses as incomplete (rate limit / early cutoff) — caller will retry
        if len(qa_text) < 100:
            add_log(task_gid, f"QA response too short ({len(qa_text)} chars) — likely truncated by rate limit, treating as failed", "warning")
            return None

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
