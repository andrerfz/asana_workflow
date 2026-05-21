"""Investigation phase — explore codebase with read-only tools before planning."""
import logging
import re
from typing import Optional

from ..claude_client import _run_claude_cli, get_best_model
from ..state import add_log, _accumulate_cost
from ...services.repo_manager import list_repos
from .timer import agent_timers
from .context import load_claude_md_guides

log = logging.getLogger(__name__)


def _extract_search_anchors(context: str) -> list[str]:
    """Extract likely code identifiers from task name/description to seed targeted grep searches."""
    # Common words that are useless as search anchors
    _STOPWORDS = {
        "para", "que", "con", "por", "una", "los", "las", "del", "como", "esta",
        "desde", "hasta", "cuando", "donde", "sobre", "entre", "tiene", "hacer",
        "the", "for", "with", "from", "this", "that", "when", "where", "what",
        "back", "area", "back", "clientes", "proveedores", "agent", "task",
    }

    # First line of context is usually "# Task: <name>" — highest signal
    first_line = context.split("\n")[0].replace("# Task:", "").strip()
    # Also grab the description header line if present
    desc_start = re.search(r'## Description\n(.{0,300})', context)
    desc_snippet = desc_start.group(1) if desc_start else ""
    high_signal_text = f"{first_line} {desc_snippet}"

    anchors = []

    # 1. CamelCase / PascalCase identifiers anywhere in context (class/method names)
    anchors += re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b', context[:4000])

    # 2. snake_case identifiers in context (DB columns, PHP functions, routes)
    anchors += re.findall(r'\b[a-z][a-z0-9]*(?:_[a-z0-9]+){1,}\b', context[:4000])

    # 3. Domain words from task name/description (≥6 chars) — appear verbatim
    #    in file names, routes, blade views, and class names
    for word in re.findall(r'\b[a-zA-Z]{6,}\b', high_signal_text):
        if word.lower() not in _STOPWORDS:
            anchors.append(word.lower())

    # Deduplicate case-insensitively (prefer original casing), drop purely numeric, keep top 12
    seen_lower: set = set()
    result = []
    for a in anchors:
        a_clean = a.strip()
        if a_clean and a_clean.lower() not in seen_lower and not a_clean.isdigit() and len(a_clean) >= 5:
            seen_lower.add(a_clean.lower())
            result.append(a_clean)
        if len(result) >= 12:
            break
    return result


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

        # Extract search anchors from task name + description to seed targeted greps
        anchors = _extract_search_anchors(context)
        anchors_section = ""
        if anchors:
            anchors_list = "\n".join(f"  - `{a}`" for a in anchors)
            anchors_section = (
                f"\n\n## SEARCH ANCHORS — start here\n"
                f"The task name and description contain these likely identifiers. "
                f"Your FIRST tool calls must be Grep searches for these terms to locate the relevant files. "
                f"Do NOT start by listing directories or reading random files.\n"
                f"{anchors_list}\n"
                f"Grep each one against the worktree. The first match will tell you where the task lives. "
                f"Then read only the files you find — not the whole codebase."
            )

        # Surface QA report if this is a QA return
        qa_section = ""
        if "## ⚠ QA Return" in context or "QA Return" in context:
            # Extract QA report text if embedded in context
            qa_match = re.search(r'qa_report["\s:]+(.{100,2000}?)(?:\n##|\Z)', context, re.DOTALL)
            if qa_match:
                qa_section = (
                    f"\n\n## QA FEEDBACK — primary focus\n"
                    f"This task was returned by QA. The reviewer reported:\n"
                    f"{qa_match.group(1).strip()[:1500]}\n"
                    f"Start your investigation from the files and logic mentioned in this feedback."
                )

        system = (
            "You are a senior developer investigating a codebase BEFORE writing an implementation plan. "
            "Your goal is to find exactly WHERE in the code this task lives and produce a focused report. "
            "You have READ-ONLY access to all configured project repositories.\n\n"
            "DO NOT modify any files. DO NOT create commits. DO NOT run destructive commands.\n\n"
            "## Investigation order (follow this strictly):\n"
            "1. **Grep the search anchors first** — use the identifiers from the task to find the relevant files immediately\n"
            "2. **Read only those files** — once you find the relevant class/method/view, read it and its direct dependencies\n"
            "3. **Check cross-project impact** — does this touch shared models, APIs, or migrations in other repos?\n"
            "4. **Testing** — find an existing test for this area to understand how tests are structured\n"
            "5. **Gotchas** — note anything surprising only if you find it naturally; do NOT go hunting\n\n"
            "Stop as soon as you have enough to write a precise implementation plan. "
            "Do NOT read every file in the directory. Do NOT explore unrelated areas.\n\n"
            "## Available repositories:\n"
            f"{repos_section}\n\n"
            "## IMPORTANT: Additional repos needed\n"
            "If this task REQUIRES changes in a repo NOT currently your worktree, include at the very end:\n\n"
            "ADDITIONAL_REPOS: repo-id-1, repo-id-2\n\n"
            "Only request repos where code changes are actually needed. "
            "Output a structured report under 600 words. Facts only, no assumptions."
        )

        prompt = (
            f"{context}{claude_guides}{anchors_section}{qa_section}\n\n"
            f"Investigate and produce a report. Grep the search anchors first, then read only the files you find."
        )

        timer = agent_timers.get(task_gid)
        # Hard cap: investigation must finish in 10 min — anchors make it fast now
        phase_timeout = min(600.0, timer.remaining if timer else 600.0)
        result = await _run_claude_cli(
            prompt=prompt,
            cwd=wt_path,
            max_turns=20,
            allowed_tools=["Read", "Glob", "Grep", "LS", "Bash(git log:*)", "Bash(git diff:*)", "Bash(find:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(wc:*)"],
            system_prompt=system,
            task_gid=task_gid,
            model=get_best_model(),  # opus unnecessary now that anchors guide the search
            subprocess_timeout=phase_timeout,
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
