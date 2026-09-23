from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Iterator

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from cline_executor import execute
from browser_acceptance import evaluate as browser_acceptance
from common import ROOT, audit, atomic_json, config, git, read_env, save_state, state, utc_now
from evidence import build as build_evidence
from git_manager import changed_paths, checkpoint, guard_changes, has_head, is_repository
from task_loader import effective_status, load_tasks, queue_head, requires_human_gate
from validator import runtime_checks, validate


def set_task_status(project_state: dict[str, Any], task_id: str, status: str, **details: Any) -> None:
    statuses = project_state.setdefault("task_statuses", {})
    entry = statuses.setdefault(task_id, {})
    entry.update({"status": status, "updated_at": utc_now(), **details})
    save_state(project_state)


@contextlib.contextmanager
def controller_lock() -> Iterator[None]:
    lock_path = ROOT / config()["evidence"]["locks_dir"] / "controller.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.seek(0); stream.write(b"0"); stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another NEWAPP controller is already running") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def approval(task_id: str) -> dict[str, Any] | None:
    path = ROOT / config()["evidence"]["decisions_dir"] / f"{task_id}-approved.json"
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if value.get("task_id") == task_id and value.get("decision") == "approved" else None


def preflight(write_state: bool = True) -> int:
    cfg = config()
    tasks = load_tasks()
    env = read_env(ROOT / cfg["environment"]["file"])
    groups: dict[str, Any] = {}
    blockers: list[str] = []
    for group, keys in cfg["environment"]["required_key_groups"].items():
        missing = [key for key in keys if not env.get(key)]
        groups[group] = {"configured": len(keys) - len(missing), "required": len(keys), "missing_keys": missing}
        if group == "brain" and missing:
            blockers.append("GPT brain configuration missing: " + ", ".join(missing))
    git_ok = is_repository()
    head_ok = has_head()
    if cfg["runtime"].get("require_git") and not git_ok:
        blockers.append("Git repository is not initialized")
    if cfg["runtime"].get("require_baseline_commit") and not head_ok:
        blockers.append("Git baseline commit is missing")
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8") if (ROOT / ".gitignore").exists() else ""
    for required in (".env", "agent.env"):
        if required not in ignore:
            blockers.append(f".gitignore does not protect {required}")
    checks = runtime_checks()
    if not checks["cline"]:
        blockers.append("Cline CLI is unavailable")
    result = {
        "status": "ready" if not blockers else "blocked",
        "project": cfg["project"]["name"],
        "task_count": len(tasks),
        "task_source": cfg["sources"]["tasks"],
        "environment_groups": groups,
        "runtime": checks,
        "git": {"repository": git_ok, "baseline_commit": head_ok},
        "blockers": blockers,
        "safe_default": "preflight_only_no_business_task_started",
    }
    if write_state:
        current = state()
        save_state(current, phase="ready" if not blockers else "preflight_blocked", blocker="; ".join(blockers) if blockers else None)
        audit("preflight", status=result["status"], blockers=blockers, task_count=len(tasks))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not any("task" in item.lower() and "missing" in item.lower() for item in blockers) else 2


def status_command() -> int:
    project_state = state()
    tasks = load_tasks()
    head = queue_head(tasks, project_state)
    rows = [{"id": task["id"], "status": effective_status(task["id"], project_state), "title": task.get("title")} for task in tasks]
    print(json.dumps({"project_state": project_state, "queue_head": head.task["id"] if head.task else None, "queue_reason": head.reason, "tasks": rows}, ensure_ascii=False, indent=2))
    return 0


def allowed_paths(task: dict[str, Any]) -> list[str]:
    values = task.get("allowed_paths")
    return [str(item) for item in values] if isinstance(values, list) and values else list(config()["paths"]["executor_allowed"])


def run_one(*, plan_only: bool = False) -> int:
    from gpt_brain import plan as brain_plan, review as brain_review

    with controller_lock():
        project_state = state()
        if project_state.get("paused"):
            print(f"Controller paused: {project_state.get('pause_reason')}", file=sys.stderr)
            return 11
        tasks = load_tasks()
        head = queue_head(tasks, project_state)
        if head.task is None:
            print(head.reason, file=sys.stderr if head.reason != "queue_empty" else sys.stdout)
            return 0 if head.reason == "queue_empty" else 10
        task = head.task
        gate, gate_reason = requires_human_gate(task)
        if gate and not approval(task["id"]):
            set_task_status(project_state, task["id"], "awaiting_human", reason=gate_reason)
            save_state(project_state, phase="awaiting_human", current_task=task["id"], blocker=gate_reason)
            audit("human_gate_required", task_id=task["id"], reason=gate_reason)
            print(f"{task['id']} requires Human Gate approval: {gate_reason}", file=sys.stderr)
            return 12
        set_task_status(project_state, task["id"], "awaiting_brain")
        save_state(project_state, phase="planning", current_task=task["id"], blocker=None)
        try:
            decision = brain_plan(task)
        except Exception as exc:
            set_task_status(project_state, task["id"], "blocked", error=str(exc))
            save_state(project_state, phase="blocked", blocker=str(exc))
            audit("brain_plan_failed", task_id=task["id"], error=str(exc))
            print(f"GPT planning failed: {exc}", file=sys.stderr)
            return 14
        audit("brain_plan", task_id=task["id"], decision=decision.decision, rationale=decision.rationale)
        if decision.decision != "execute":
            status = "awaiting_human" if decision.decision == "human_gate" else "blocked"
            set_task_status(project_state, task["id"], status, reason=decision.rationale)
            save_state(project_state, phase=status, blocker=decision.rationale)
            print(decision.model_dump_json(indent=2))
            return 12 if status == "awaiting_human" else 13
        if plan_only:
            set_task_status(project_state, task["id"], "queued", last_plan=decision.model_dump())
            save_state(project_state, phase="ready", current_task=None)
            print(decision.model_dump_json(indent=2))
            return 0
        run_id = utc_now().replace("-", "").replace(":", "").replace(".", "") + "-" + uuid.uuid4().hex[:8]
        before = set(changed_paths())
        previous_attempts = int(project_state.setdefault("task_statuses", {}).setdefault(task["id"], {}).get("attempts", 0))
        max_attempts = int(config()["runtime"].get("max_attempts_per_task", 3))
        if previous_attempts >= max_attempts:
            set_task_status(project_state, task["id"], "failed", error="maximum attempts exhausted")
            save_state(project_state, phase="failed", blocker="maximum attempts exhausted")
            return 15
        set_task_status(project_state, task["id"], "executing", run_id=run_id, attempts=previous_attempts + 1)
        save_state(project_state, phase="executing", last_run_id=run_id)
        try:
            executor_result = execute(task, decision.model_dump(), run_id, allowed_paths(task))
        except Exception as exc:
            set_task_status(project_state, task["id"], "failed", error=str(exc), run_id=run_id)
            save_state(project_state, phase="failed", blocker=str(exc))
            audit("executor_exception", task_id=task["id"], run_id=run_id, error=str(exc))
            raise
        if executor_result["exit_code"] != 0:
            set_task_status(project_state, task["id"], "failed", executor=executor_result)
            save_state(project_state, phase="failed", blocker=f"Cline exited {executor_result['exit_code']}")
            audit("executor_failed", task_id=task["id"], run_id=run_id, exit_code=executor_result["exit_code"])
            return 20
        set_task_status(project_state, task["id"], "code_ready", executor=executor_result)
        save_state(project_state, phase="validating", blocker=None)
        try:
            validation = validate(task, run_id, "safe")
            guard = guard_changes(before, allowed_paths(task))
            browser = browser_acceptance(task, run_id)
            manifest = build_evidence(task, run_id, executor_result, validation, guard, browser)
        except Exception as exc:
            set_task_status(project_state, task["id"], "failed", error=str(exc), run_id=run_id)
            save_state(project_state, phase="failed", blocker=str(exc))
            audit("validation_exception", task_id=task["id"], run_id=run_id, error=str(exc))
            print(f"Validation/evidence failed: {exc}", file=sys.stderr)
            return 21
        if manifest["status"] != "ready_for_gpt_review":
            set_task_status(project_state, task["id"], "failed", evidence_status=manifest["status"])
            save_state(project_state, phase="failed", blocker="Validation/evidence/path guard did not pass", last_validation=validation)
            audit("evidence_insufficient", task_id=task["id"], run_id=run_id)
            return 21
        set_task_status(project_state, task["id"], "awaiting_review")
        save_state(project_state, phase="awaiting_review", last_validation=validation)
        try:
            review = brain_review(task, manifest)
        except Exception as exc:
            set_task_status(project_state, task["id"], "failed", error=str(exc), run_id=run_id)
            save_state(project_state, phase="failed", blocker=str(exc))
            audit("brain_review_failed", task_id=task["id"], run_id=run_id, error=str(exc))
            print(f"GPT final review failed: {exc}", file=sys.stderr)
            return 22
        review_path = ROOT / config()["evidence"]["decisions_dir"] / f"{run_id}-gpt-review.json"
        atomic_json(review_path, review.model_dump())
        if review.decision != "accept":
            status = "awaiting_human" if review.decision == "human_gate" else "failed"
            set_task_status(project_state, task["id"], status, review=review.model_dump())
            save_state(project_state, phase=status, blocker=review.rationale, last_review=review.model_dump())
            audit("gpt_review_rejected", task_id=task["id"], run_id=run_id, decision=review.decision)
            return 22
        set_task_status(project_state, task["id"], "completed", review=review.model_dump(), run_id=run_id)
        save_state(project_state, phase="ready", current_task=None, last_completed_task=task["id"], blocker=None, last_review=review.model_dump())
        commit_result = checkpoint(task["id"], str(task.get("title", "task")), manifest["path_guard"]["changed_paths"]) if config()["runtime"].get("auto_commit_after_acceptance") else {"status": "disabled"}
        audit("task_completed", task_id=task["id"], run_id=run_id, checkpoint=commit_result)
        print(json.dumps({"task": task["id"], "status": "completed", "checkpoint": commit_result}, ensure_ascii=False, indent=2))
        return 0


def approve(args: argparse.Namespace) -> int:
    task_ids = {task["id"] for task in load_tasks()}
    if args.task_id not in task_ids:
        print(f"Unknown task: {args.task_id}", file=sys.stderr); return 2
    path = ROOT / config()["evidence"]["decisions_dir"] / f"{args.task_id}-approved.json"
    record = {"task_id": args.task_id, "decision": "approved", "approved_by": args.by, "reason": args.reason, "scope": "non-destructive isolated/test operation only", "at": utc_now()}
    atomic_json(path, record)
    project_state = state()
    if effective_status(args.task_id, project_state) == "awaiting_human":
        set_task_status(project_state, args.task_id, "retry", approval=str(path.relative_to(ROOT)).replace("\\", "/"))
        save_state(project_state, phase="ready", current_task=None, blocker=None)
    audit("human_gate_approved", task_id=args.task_id, approved_by=args.by, reason=args.reason)
    print(f"Approved {args.task_id} within non-destructive test-only scope")
    return 0


def pause_resume(paused: bool, reason: str | None = None) -> int:
    project_state = state()
    save_state(project_state, paused=paused, pause_reason=reason if paused else None, phase="paused" if paused else "ready")
    audit("controller_paused" if paused else "controller_resumed", reason=reason)
    return 0


def retry(args: argparse.Namespace) -> int:
    project_state = state()
    if args.task_id not in {task["id"] for task in load_tasks()}:
        print(f"Unknown task: {args.task_id}", file=sys.stderr); return 2
    current = effective_status(args.task_id, project_state)
    if current not in {"failed", "blocked", "awaiting_human"}:
        print(f"{args.task_id} status={current} cannot be retried", file=sys.stderr); return 3
    set_task_status(project_state, args.task_id, "retry", retry_by=args.by, retry_reason=args.reason)
    save_state(project_state, phase="ready", current_task=None, blocker=None)
    audit("task_retried", task_id=args.task_id, by=args.by, reason=args.reason)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="NEWAPP guarded GPT/Cline automation control plane")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("preflight")
    sub.add_parser("status")
    sub.add_parser("plan")
    sub.add_parser("run-once")
    sub.add_parser("run")
    approve_parser = sub.add_parser("approve")
    approve_parser.add_argument("task_id"); approve_parser.add_argument("--by", required=True); approve_parser.add_argument("--reason", required=True)
    pause_parser = sub.add_parser("pause"); pause_parser.add_argument("--reason", required=True)
    sub.add_parser("resume")
    retry_parser = sub.add_parser("retry")
    retry_parser.add_argument("task_id"); retry_parser.add_argument("--by", required=True); retry_parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    command = args.command or config()["runtime"]["default_command"]
    if command == "preflight": return preflight()
    if command == "status": return status_command()
    if command == "plan": return run_one(plan_only=True)
    if command == "run-once": return run_one()
    if command == "approve": return approve(args)
    if command == "pause": return pause_resume(True, args.reason)
    if command == "resume": return pause_resume(False)
    if command == "retry": return retry(args)
    if command == "run":
        while True:
            result = run_one()
            if result != 0: return result
            if queue_head(load_tasks(), state()).reason == "queue_empty": return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
