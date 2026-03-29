"""Agent phase definitions and workflow graph."""
import copy
from enum import Enum


class AgentPhase(str, Enum):
    QUEUED = "queued"
    INIT = "init"
    INVESTIGATING = "investigating"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    CODING = "coding"
    TESTING = "testing"
    QA_REVIEW = "qa_review"
    DONE = "done"
    ERROR = "error"
    PAUSED = "paused"       # Waiting for human input
    CANCELLED = "cancelled"

    @property
    def color(self):
        return {
            "queued": "#6b7280", "init": "#8b5cf6", "investigating": "#0ea5e9",
            "planning": "#d97706",
            "awaiting_approval": "#eab308", "coding": "#3b82f6", "testing": "#22c55e",
            "done": "#8b5cf6", "error": "#ef4444", "paused": "#eab308",
            "cancelled": "#4b5563",
        }.get(self.value, "#6b7280")


# ─── Workflow Graph (auto-discovered by UI) ───

WORKFLOW_GRAPH: dict = {
    "nodes": [
        {
            "id": "queued",
            "label": "Queued",
            "icon": "⏱",
            "color": "#6b7280",
            "desc": "Task queued for agent processing.",
            "row": 0, "col": 0,
        },
        {
            "id": "init",
            "label": "Init",
            "icon": "⚙",
            "color": "#8b5cf6",
            "desc": "Create git worktree (fresh or from existing branch).\nMount repos, resolve branch suggestions.\nMove Asana task → configured 'On Start' section.",
            "row": 0, "col": 1,
        },
        {
            "id": "investigating",
            "label": "Investigating",
            "icon": "🔎",
            "color": "#0ea5e9",
            "desc": "Claude Code explores the codebase with read-only tools.\nReads CLAUDE.md guides, inspects project structure and related repos.\nProduces investigation report for the planning phase.",
            "row": 0, "col": 2,
        },
        {
            "id": "planning",
            "label": "Planning",
            "icon": "📋",
            "color": "#d97706",
            "desc": "Claude Code generates implementation plan.\nContext includes: task details, investigation report, Asana comments.\nPlan posted as Asana comment.",
            "row": 0, "col": 3,
        },
        {
            "id": "awaiting_approval",
            "label": "Awaiting Approval",
            "icon": "⏳",
            "color": "#eab308",
            "desc": "Plan shown in dashboard for review.\nUser can: Approve / Reject / Revise with feedback.\nRevise loops back to Planning with feedback context.",
            "row": 0, "col": 4,
        },
        {
            "id": "coding",
            "label": "Coding",
            "icon": "💻",
            "color": "#3b82f6",
            "desc": "Claude Code implements the approved plan.\nWorks in isolated git worktree.\nAuto-commits uncommitted changes as safety net.",
            "row": 1, "col": 0,
        },
        {
            "id": "rebase",
            "label": "Rebase",
            "icon": "🔀",
            "color": "#06b6d4",
            "desc": "Fetch & rebase onto latest default branch.\nAuto-resolve conflicts with Claude Code.\nFailure posts details to Asana.",
            "row": 1, "col": 1,
        },
        {
            "id": "testing",
            "label": "Testing",
            "icon": "🧪",
            "color": "#22c55e",
            "desc": "Run test command (Docker or local).\nOn failure: Claude Code fixes → re-test (up to 3 rounds).\nDocker tests run from project root.",
            "row": 1, "col": 2,
        },
        {
            "id": "qa_review",
            "label": "QA Review",
            "icon": "🔍",
            "color": "#a855f7",
            "desc": "AI analyzes diffs vs task requirements.\nGenerates QA findings report.\nHuman approves for delivery or rejects for fixes.",
            "row": 1, "col": 3,
        },
        {
            "id": "done",
            "label": "Done",
            "icon": "✅",
            "color": "#10b981",
            "desc": "Push branch to remote.\nMove Asana task → configured 'On Done' section.\nPost summary comment with branches & commit count.",
            "row": 1, "col": 4,
        },
        {
            "id": "error",
            "label": "Error",
            "icon": "❌",
            "color": "#ef4444",
            "desc": "Any phase failure lands here.\nError posted as Asana comment.\nUser can retry from dashboard.",
            "row": 2, "col": 1,
        },
        {
            "id": "paused",
            "label": "Paused",
            "icon": "💬",
            "color": "#eab308",
            "desc": "Agent asks a question and waits.\nUser answers in dashboard.\nResumes automatically after answer.",
            "row": 2, "col": 2,
        },
    ],
    "edges": [
        {"from": "queued", "to": "init", "type": "main"},
        {"from": "init", "to": "investigating", "type": "main"},
        {"from": "investigating", "to": "planning", "type": "main"},
        {"from": "planning", "to": "awaiting_approval", "type": "main"},
        {"from": "awaiting_approval", "to": "coding", "type": "main", "label": "Approved"},
        {"from": "awaiting_approval", "to": "planning", "type": "loop", "label": "Revise"},
        {"from": "coding", "to": "rebase", "type": "main"},
        {"from": "rebase", "to": "testing", "type": "main"},
        {"from": "testing", "to": "qa_review", "type": "main", "label": "Pass"},
        {"from": "testing", "to": "coding", "type": "loop", "label": "Fix & retry"},
        {"from": "qa_review", "to": "done", "type": "main", "label": "Approve"},
        {"from": "qa_review", "to": "coding", "type": "loop", "label": "Reject"},
        # Error edges — any active phase can error
        {"from": "init", "to": "error", "type": "error"},
        {"from": "investigating", "to": "error", "type": "error"},
        {"from": "planning", "to": "error", "type": "error"},
        {"from": "coding", "to": "error", "type": "error"},
        {"from": "rebase", "to": "error", "type": "error"},
        {"from": "testing", "to": "error", "type": "error"},
        {"from": "qa_review", "to": "error", "type": "error"},
        # Pause edges
        {"from": "coding", "to": "paused", "type": "pause"},
        {"from": "paused", "to": "coding", "type": "pause", "label": "Answer"},
    ],
}


def get_workflow_graph(settings: dict) -> dict:
    """Return the workflow graph definition with current section names injected."""
    graph = copy.deepcopy(WORKFLOW_GRAPH)
    # Inject actual section names into node descriptions
    for node in graph["nodes"]:
        if node["id"] == "init" and settings.get("section_on_start"):
            node["desc"] = node["desc"].replace(
                "configured 'On Start' section",
                f"'{settings['section_on_start']}' section",
            )
        elif node["id"] == "done" and settings.get("section_on_done"):
            node["desc"] = node["desc"].replace(
                "configured 'On Done' section",
                f"'{settings['section_on_done']}' section",
            )
    return graph
