"""Investigation phase — explore codebase with read-only tools before planning."""
import logging
from typing import Optional

from ..claude_client import _run_claude_cli
from ..state import add_log, _accumulate_cost
from ...services.repo_manager import list_repos
from .timer import agent_timers
from .context import load_claude_md_guides

log = logging.getLogger(__name__)


async def agent_investigate(task_gid: str, context: str, run: dict) -> Optional[str]:
    """Run the investigation phase — explore codebase with read-only tools before planning."""
    try:
        wt_path = run["repos"][0].get("worktree_path", ".")

        # Build list of all repo paths for cross-project exploration
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
        claude_guides = load_claude_md_guides(run)

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

        skill_instruction = (
            "\n\n## Skills\n"
            "Before exploring manually, check if any available skill matches this task type and invoke it "
            "with the Skill tool — it will return richer diagnostic context than manual exploration.\n"
            "Examples of when to invoke a skill:\n"
            "- Bug, error, unexpected behavior, regression → `Skill(skill='fix-issues')`\n"
            "- Database data discrepancy or query → `Skill(skill='db-query')`\n"
            "- Security concern → `Skill(skill='security-review')`\n"
            "Invoke the matching skill FIRST, then continue investigating manually as needed. "
            "If no skill matches, skip this step."
        )

        prompt = f"{context}{claude_guides}{skill_instruction}\n\nInvestigate the codebase and produce a report. Use Read, Glob, and Grep tools to explore."

        timer = agent_timers.get(task_gid)
        result = await _run_claude_cli(
            prompt=prompt,
            cwd=wt_path,
            max_turns=15,
            allowed_tools=["Read", "Glob", "Grep", "LS", "Bash(git log:*)", "Bash(git diff:*)", "Bash(find:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(wc:*)", "Skill", "ToolSearch"],
            system_prompt=system,
            task_gid=task_gid,
            model="opus",
            subprocess_timeout=timer.remaining if timer else None,
        )

        report = result.get("text", "").strip()

        try:
            _accumulate_cost(task_gid, result)
        except Exception as e:
            log.warning(f"Failed to accumulate cost for investigation: {e}")

        if result["returncode"] != 0 and not report:
            error = result.get("stderr", "") or result.get("raw_output", "Unknown error")
            add_log(task_gid, f"Investigation failed (exit {result['returncode']}): {error[:500]}", "error")
            return None

        if report:
            add_log(task_gid, f"Investigation complete ({len(report)} chars)")
        return report

    except Exception as e:
        add_log(task_gid, f"Investigation failed: {e}", "warning")
        return None
