"""Local JSON persistence for overrides, history, and AI cache."""
import json

from config import CLASSIFICATIONS_FILE, HISTORY_FILE, RESOLVED_FILE, AI_CACHE_FILE


# --- Overrides / Classifications ---

def load_overrides() -> dict:
    """Load manual classification overrides from disk."""
    if CLASSIFICATIONS_FILE.exists():
        try:
            return json.loads(CLASSIFICATIONS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {"overrides": {}}
    return {"overrides": {}}


def save_overrides(data: dict):
    """Save manual classification overrides to disk."""
    CLASSIFICATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CLASSIFICATIONS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# --- History ---

def load_history() -> list:
    """Load task history snapshots from disk."""
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_history(history: list):
    """Save task history snapshots to disk."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False))


# --- Resolved Tasks ---

def load_resolved() -> list:
    """Load resolved tasks list from disk."""
    if RESOLVED_FILE.exists():
        try:
            return json.loads(RESOLVED_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_resolved(resolved: list):
    """Save resolved tasks list to disk."""
    RESOLVED_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESOLVED_FILE.write_text(json.dumps(resolved, indent=2, ensure_ascii=False))


# --- AI Cache ---

def load_ai_cache() -> dict:
    """Load AI classification cache from disk."""
    if AI_CACHE_FILE.exists():
        try:
            return json.loads(AI_CACHE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_ai_cache(cache: dict):
    """Save AI classification cache to disk."""
    AI_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    AI_CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


def clear_ai_cache():
    """Delete AI classification cache file."""
    if AI_CACHE_FILE.exists():
        AI_CACHE_FILE.unlink()
