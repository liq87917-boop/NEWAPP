from __future__ import annotations

from dataclasses import dataclass
import ast
import re
from typing import Any

from common import ROOT, config

TERMINAL = {"completed", "deferred", "skipped"}
RUNNABLE = {"queued", "retry"}


@dataclass(frozen=True)
class QueueResult:
    task: dict[str, Any] | None
    reason: str


def load_tasks() -> list[dict[str, Any]]:
    source = ROOT / config()["sources"]["tasks"]
    tasks = _parse_task_blueprint(source.read_text(encoding="utf-8-sig"))
    if not tasks:
        raise ValueError(f"No task list in {source}")
    normalized: list[dict[str, Any]] = []
    for item in tasks:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("Every task must be an object with a string id")
        copy = dict(item)
        deps = copy.get("depends_on", [])
        if isinstance(deps, str):
            deps = [deps]
        if not isinstance(deps, list) or any(not isinstance(dep, str) for dep in deps):
            raise ValueError(f"{copy['id']}: depends_on must be a string list")
        copy["depends_on"] = deps
        normalized.append(copy)
    validate_graph(normalized)
    return normalized


def _inline_list(value: str) -> list[str]:
    value = value.strip()
    if value == "[]":
        return []
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        parsed = [part.strip() for part in value.strip("[]").split(",") if part.strip()]
    if not isinstance(parsed, list):
        raise ValueError(f"Expected YAML list, got: {value}")
    return [str(item) for item in parsed]


def _parse_task_blueprint(raw: str) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    active_list: str | None = None
    in_tasks = False
    for line in raw.splitlines():
        if line.strip() == "tasks:":
            in_tasks = True
            continue
        if not in_tasks:
            continue
        match = re.match(r"^  - id:\s*(NEWAPP-\d+)\s*$", line)
        if match:
            current = {"id": match.group(1), "actions": [], "acceptance": []}
            tasks.append(current)
            active_list = None
            continue
        if current is None:
            continue
        field = re.match(r"^    (phase|title|depends_on|actions|acceptance):\s*(.*)$", line)
        if field:
            key, value = field.groups()
            if key in {"actions", "acceptance"}:
                active_list = key
                if value:
                    current[key] = _inline_list(value)
                    active_list = None
            elif key == "depends_on":
                current[key] = _inline_list(value)
                active_list = None
            else:
                current[key] = value.strip().strip("'").strip('"')
                active_list = None
            continue
        item = re.match(r"^      -\s+(['\"]?)(.*?)\1\s*$", line)
        if item and active_list:
            current[active_list].append(item.group(2))
    return tasks


def validate_graph(tasks: list[dict[str, Any]]) -> None:
    ids = [task["id"] for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate task ids")
    by_id = {task["id"]: task for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ValueError(f"Dependency cycle at {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dep in by_id[task_id]["depends_on"]:
            if dep not in by_id:
                raise ValueError(f"{task_id}: missing dependency {dep}")
            visit(dep)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in ids:
        visit(task_id)


def effective_status(task_id: str, project_state: dict[str, Any]) -> str:
    return str(project_state.get("task_statuses", {}).get(task_id, {}).get("status", "queued"))


def queue_head(tasks: list[dict[str, Any]], project_state: dict[str, Any]) -> QueueResult:
    by_id = {task["id"]: task for task in tasks}
    for task in tasks:
        status = effective_status(task["id"], project_state)
        if status in TERMINAL:
            continue
        if status not in RUNNABLE:
            return QueueResult(None, f"{task['id']} status={status} blocks the queue")
        for dep in task["depends_on"]:
            dep_status = effective_status(dep, project_state)
            if dep_status != "completed":
                return QueueResult(None, f"{task['id']} waits for {dep} status={dep_status}")
        return QueueResult(by_id[task["id"]], "ready")
    return QueueResult(None, "queue_empty")


def task_text(task: dict[str, Any]) -> str:
    parts = [str(task.get("title", ""))]
    for key in ("actions",):
        value = task.get(key, [])
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
    return "\n".join(parts).lower()


def requires_human_gate(task: dict[str, Any]) -> tuple[bool, str]:
    settings = config()["human_gate"]
    if task["id"] in set(settings.get("task_ids", [])):
        return True, "task is explicitly classified as high risk"
    text = task_text(task)
    matched = [term for term in settings.get("trigger_terms", []) if str(term).lower() in text]
    if matched:
        return True, "matched risk terms: " + ", ".join(matched)
    return False, "not required"
