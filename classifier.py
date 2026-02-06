"""
Auto-classification engine for Asana tasks.
Detects clusters, scope scores, areas, and priority.
"""

import re
from typing import Optional

# --- Cluster detection keywords ---
CLUSTER_RULES = [
    {
        "id": "ebitda",
        "name": "EBITDA Reports",
        "color": "#e74c3c",
        "keywords": ["ebitda", "cuenta_explotacion", "cuenta explotacion"],
        "name_patterns": [r"informe\s+ebitda", r"ebitda"],
    },
    {
        "id": "trazabilidad",
        "name": "Trazabilidad",
        "color": "#9b59b6",
        "keywords": ["trazabilidad"],
        "name_patterns": [r"trazabilidad", r"informe\s+de\s+trazabilidad"],
        "name_bonus": 2,  # Extra weight: if "trazabilidad" is in the name, it wins over pedidos/albarán
    },
    {
        "id": "turnos",
        "name": "Planificacion Turnos",
        "color": "#3498db",
        "keywords": ["planificación de turnos", "planificador de turnos", "turnos planificados"],
        "name_patterns": [r"turnos?", r"planificaci[oó]n"],
    },
    {
        "id": "pedidos",
        "name": "Pedidos / Albaranes",
        "color": "#f39c12",
        "keywords": ["pedidos", "albarán", "albaranes", "albarán"],
        "name_patterns": [r"pedidos?", r"albar[aá]n"],
    },
    {
        "id": "almacen",
        "name": "Almacen",
        "color": "#1abc9c",
        "keywords": ["almacén", "almacen", "ubicación"],
        "name_patterns": [r"almac[eé]n", r"ubicaci[oó]n"],
    },
    {
        "id": "sentry",
        "name": "Sentry / Monitoring",
        "color": "#95a5a6",
        "keywords": ["sentry"],
        "name_patterns": [r"\[sentry\]", r"sentry"],
    },
    {
        "id": "integracion",
        "name": "Integraciones",
        "color": "#e67e22",
        "keywords": ["integración", "integracion"],
        "name_patterns": [r"integraci[oó]n"],
    },
]

# --- Area detection from task name prefix ---
AREA_PATTERNS = [
    (r"^Back\s+Clientes", "backend_clientes"),
    (r"^Back\s+[Pp]roveedor", "backend_proveedor"),
    (r"^Back\s+proveedores", "backend_proveedor"),
    (r"^Back\s+API", "backend_api"),
    (r"^Back\s+Api", "backend_api"),
    (r"\bAPP\b", "mobile_app"),
    (r"^\[Sentry\]", "monitoring"),
]


def detect_cluster(name: str, notes: str) -> Optional[dict]:
    """Detect which cluster a task belongs to based on name and notes."""
    text = f"{name} {notes}".lower()
    best_match = None
    best_score = 0

    for rule in CLUSTER_RULES:
        score = 0
        # Check name patterns (higher weight)
        for pattern in rule["name_patterns"]:
            if re.search(pattern, name, re.IGNORECASE):
                score += 3
        # Apply name_bonus if rule has one (for disambiguation)
        if rule.get("name_bonus") and score > 0:
            score += rule["name_bonus"]
        # Check keywords in full text
        for kw in rule["keywords"]:
            if kw.lower() in text:
                score += 1

        if score > best_score:
            best_score = score
            best_match = rule

    if best_score >= 1:
        return {"id": best_match["id"], "name": best_match["name"], "color": best_match["color"]}
    return {"id": "standalone", "name": "Standalone", "color": "#7f8c8d"}


def detect_area(name: str) -> str:
    """Detect functional area from task name prefix."""
    for pattern, area in AREA_PATTERNS:
        if re.search(pattern, name):
            return area
    return "other"


def compute_scope_score(task: dict) -> int:
    """
    Compute scope score 1-5 based on task characteristics.
    1=Tiny (query fix), 2=Small (single file), 3=Medium (multi-file),
    4=Large (new endpoint+tests), 5=XL (cross-system/new feature)
    """
    name = task.get("name") or ""
    notes = task.get("notes") or ""
    tipo = _get_custom_field(task, "Tipo")

    # Base score from type
    if tipo == "Mejora":
        base = 3
    elif tipo == "Error":
        base = 2
    else:
        base = 2

    modifiers = 0

    # Feature detection (new endpoint, new functionality)
    feature_signals = [
        r"nueva?\s+opci[oó]n", r"poder\s+\w+", r"añadir",
        r"nuevo\s+endpoint", r"nuevo\s+bot[oó]n",
        r"nueva?\s+funci", r"implementar",
    ]
    for sig in feature_signals:
        if re.search(sig, f"{name} {notes}", re.IGNORECASE):
            modifiers += 2
            break

    # Complexity signals
    if len(notes) > 800:
        modifiers += 1  # Detailed description = complex issue

    # Cross-system (mentions both API and APP, or Back + APP)
    cross_system_count = 0
    for tag in ["Back Clientes", "Back Proveedor", "Back API", "APP", "Api"]:
        if tag.lower() in name.lower():
            cross_system_count += 1
    if cross_system_count >= 2:
        modifiers += 1

    # Multiple clients affected
    tags = task.get("tags", [])
    client_tags = [t for t in tags if t.get("name", "").startswith("Cliente:")]
    if len(client_tags) > 1:
        modifiers += 1

    # Has MR links = already partially scoped
    if "merge_requests" in notes or "gitlab" in notes.lower():
        modifiers += 0  # neutral

    # Mentions "todos los sitios" or "todos los" = wide scope
    if re.search(r"todos?\s+los\s+sitios", notes, re.IGNORECASE):
        modifiers += 1
    if re.search(r"en\s+todos", notes, re.IGNORECASE):
        modifiers += 1

    # Filter/query issue = usually small
    if re.search(r"filtro\s+\w+\s+no", name, re.IGNORECASE):
        modifiers -= 1

    # Sentry error = usually small fix
    if "[sentry]" in name.lower():
        modifiers -= 1

    # Tablet/responsive = medium (CSS + possibly JS)
    if re.search(r"tablet|responsive|pantalla", f"{name} {notes}", re.IGNORECASE):
        modifiers += 1

    # Has acceptance criteria / tests mentioned = larger scope
    if re.search(r"criterios?\s+de\s+aceptaci[oó]n|tests?:", notes, re.IGNORECASE):
        modifiers += 1

    score = base + modifiers
    return max(1, min(5, score))


def compute_priority(task: dict, cluster: dict, scope: int) -> int:
    """
    Compute priority 1-10 (10=highest urgency).
    Factors: type, client impact, cluster importance, scope.
    """
    priority = 5  # baseline
    tipo = _get_custom_field(task, "Tipo")
    canal = _get_custom_field(task, "Canal")
    tags = task.get("tags", [])

    # Error > Mejora > Otros
    if tipo == "Error":
        priority += 2
    elif tipo == "Mejora":
        priority += 0

    # Client-reported = higher urgency
    if canal == "Cliente":
        priority += 1

    # High-value clusters
    if cluster["id"] == "ebitda":
        priority += 2  # Financial reports = critical
    elif cluster["id"] in ("turnos", "pedidos"):
        priority += 1  # Operational

    # Multiple clients
    client_tags = [t for t in tags if t.get("name", "").startswith("Cliente:")]
    if len(client_tags) > 1:
        priority += 1

    # Inverse relationship with scope for errors (small fix = quick win = do first)
    if tipo == "Error" and scope <= 2:
        priority += 1  # Quick wins first

    return max(1, min(10, priority))


def classify_task(task: dict) -> dict:
    """Full classification of a single task."""
    name = task.get("name") or ""
    notes = task.get("notes") or ""

    cluster = detect_cluster(name, notes)
    area = detect_area(name)
    scope = compute_scope_score(task)
    priority = compute_priority(task, cluster, scope)

    return {
        "task_gid": task["gid"],
        "name": name,
        "cluster": cluster,
        "area": area,
        "scope_score": scope,
        "priority": priority,
        "tipo": _get_custom_field(task, "Tipo") or "N/A",
        "canal": _get_custom_field(task, "Canal") or "N/A",
        "desarrollador": _get_custom_field(task, "Desarrollador") or "N/A",
        "tags": [t.get("name", "") for t in task.get("tags", [])],
        "notes_preview": notes[:200] + ("..." if len(notes) > 200 else ""),
        "permalink_url": task.get("permalink_url", ""),
        "due_on": task.get("due_on"),
        "completed": task.get("completed", False),
        "current_story_points": _get_custom_field(task, "Story Point"),
    }


def _get_custom_field(task: dict, field_name: str) -> Optional[str]:
    """Extract custom field display_value by name."""
    for cf in task.get("custom_fields", []):
        if cf.get("name") == field_name:
            return cf.get("display_value")
    return None
