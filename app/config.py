"""Central configuration — all env vars and constants."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Asana
ASANA_PAT = os.getenv("ASANA_PAT", "")
ASANA_BASE = "https://app.asana.com/api/1.0"
PROJECT_GID = os.getenv("ASANA_PROJECT_GID", "1120029023219792")
SECTION_GID = os.getenv("ASANA_SECTION_GID", "1204812858137872")
STORY_POINT_FIELD_GID = os.getenv("ASANA_STORY_POINT_FIELD_GID", "1204816034572110")
DEFAULT_SECTION = os.getenv("DEFAULT_SECTION", "Tareas Pendientes")

TASK_OPT_FIELDS = ",".join([
    "name", "notes", "html_notes", "assignee.name", "due_on", "completed",
    "tags.name", "custom_fields.name", "custom_fields.display_value",
    "permalink_url", "memberships.section.name", "memberships.project.name", "memberships.project.gid",
    "num_subtasks",
])

# AI
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# Projects root (required for AI Agent — all repos must be under this dir)
PROJECTS_DIR = os.getenv("PROJECTS_DIR", "")

# Paths
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = _PROJECT_ROOT / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"
CLASSIFICATIONS_FILE = DATA_DIR / "classifications.json"
HISTORY_FILE = DATA_DIR / "history.json"
RESOLVED_FILE = DATA_DIR / "resolved.json"
AI_CACHE_FILE = DATA_DIR / "ai_cache.json"
AGENT_QUEUE_CONFIG_FILE = DATA_DIR / "agent_queue_config.json"
AGENT_SETTINGS_FILE = DATA_DIR / "agent_settings.json"

# Cluster colors (shared between routes and frontend)
CLUSTER_COLORS = {
    "ebitda": "#e74c3c",
    "trazabilidad": "#9b59b6",
    "turnos": "#3498db",
    "pedidos": "#f39c12",
    "almacen": "#1abc9c",
    "sentry": "#95a5a6",
    "integracion": "#e67e22",
    "standalone": "#7f8c8d",
}
