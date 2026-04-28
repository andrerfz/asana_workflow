"""Planning phase — generate implementation plan from context."""
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..phases import AgentPhase
from ..claude_client import _run_claude_cli
from ..state import add_log, update_phase, load_agent_run, save_agent_run, _accumulate_cost
from ...services.repo_manager import get_repo

log = logging.getLogger(__name__)


async def agent_plan(task_gid: str, context: str, run: dict) -> Optional[str]:
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
        run["plan"] = plan_text
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
