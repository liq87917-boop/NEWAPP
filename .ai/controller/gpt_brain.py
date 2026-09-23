from __future__ import annotations

from pathlib import Path
from typing import Any

from common import ROOT, atomic_json, config, load_json, utc_now

PLAN_DECISIONS = {"execute", "human_gate", "block"}
REVIEW_DECISIONS = {"accept", "reject", "human_gate"}


def _dirs() -> tuple[Path, Path]:
    settings = config()["brain"]
    requests = ROOT / settings["requests_dir"]
    decisions = ROOT / settings["decisions_dir"]
    requests.mkdir(parents=True, exist_ok=True)
    decisions.mkdir(parents=True, exist_ok=True)
    return requests, decisions


def plan_decision_path(task_id: str) -> Path:
    return _dirs()[1] / f"{task_id}-plan.json"


def review_decision_path(task_id: str, run_id: str) -> Path:
    return _dirs()[1] / f"{task_id}-{run_id}-review.json"


def request_plan(task: dict[str, Any]) -> Path:
    requests, _ = _dirs()
    path = requests / f"{task['id']}-plan-request.json"
    atomic_json(path, {
        "request_type": "desktop_gpt_plan",
        "created_at": utc_now(),
        "task": task,
        "brain_rules": config()["sources"]["brain_rules"],
        "required_decision": {
            "task_id": task["id"],
            "decision": sorted(PLAN_DECISIONS),
            "rationale": "non-empty string",
            "validation_focus": ["one or more checks"],
            "risks": []
        },
        "record_command": f"start_agent.bat record-plan {task['id']} --decision execute --rationale <text> --validation-focus <check>"
    })
    return path


def load_plan(task_id: str) -> dict[str, Any] | None:
    path = plan_decision_path(task_id)
    if not path.exists():
        return None
    value = load_json(path)
    if value.get("task_id") != task_id or value.get("decision") not in PLAN_DECISIONS or not str(value.get("rationale", "")).strip():
        raise ValueError(f"Invalid desktop GPT plan decision: {path}")
    return value


def record_plan(task_id: str, decision: str, rationale: str, validation_focus: list[str], risks: list[str], actor: str) -> Path:
    if decision not in PLAN_DECISIONS:
        raise ValueError(f"Unsupported plan decision: {decision}")
    path = plan_decision_path(task_id)
    atomic_json(path, {
        "task_id": task_id,
        "decision": decision,
        "rationale": rationale,
        "validation_focus": validation_focus,
        "risks": risks,
        "actor": actor,
        "source": "codex_desktop_or_mobile_remote",
        "recorded_at": utc_now()
    })
    return path


def request_review(task: dict[str, Any], run_id: str, manifest_path: str) -> Path:
    requests, _ = _dirs()
    path = requests / f"{task['id']}-{run_id}-review-request.json"
    atomic_json(path, {
        "request_type": "desktop_gpt_final_review",
        "created_at": utc_now(),
        "task_id": task["id"],
        "run_id": run_id,
        "task": task,
        "evidence_manifest": manifest_path,
        "brain_rules": config()["sources"]["brain_rules"],
        "required_decision": {
            "task_id": task["id"],
            "run_id": run_id,
            "decision": sorted(REVIEW_DECISIONS),
            "rationale": "non-empty string",
            "criteria_results": [],
            "required_fixes": []
        },
        "record_command": f"start_agent.bat record-review {task['id']} {run_id} --decision accept --rationale <text>"
    })
    return path


def record_review(task_id: str, run_id: str, decision: str, rationale: str, criteria_results: list[str], required_fixes: list[str], actor: str) -> Path:
    if decision not in REVIEW_DECISIONS:
        raise ValueError(f"Unsupported review decision: {decision}")
    path = review_decision_path(task_id, run_id)
    atomic_json(path, {
        "task_id": task_id,
        "run_id": run_id,
        "decision": decision,
        "rationale": rationale,
        "criteria_results": criteria_results,
        "required_fixes": required_fixes,
        "actor": actor,
        "source": "codex_desktop_or_mobile_remote",
        "recorded_at": utc_now()
    })
    return path
