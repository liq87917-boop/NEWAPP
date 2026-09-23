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
from git_manager import changed_paths, guard_changes, has_head, is_repository
from gpt_brain import load_plan, record_plan, record_review, request_plan, request_review
from github_relay import finalize_review, prepare_task_branch, preflight as github_preflight, publish_branch_metadata, publish_candidate, publish_control_update
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
    relay = github_preflight()
    blockers.extend(relay["blockers"])
    result = {
        "status": "ready" if not blockers else "blocked",
        "project": cfg["project"]["name"],
        "task_count": len(tasks),
        "task_source": cfg["sources"]["tasks"],
        "environment_groups": groups,
        "runtime": checks,
        "git": {"repository": git_ok, "baseline_commit": head_ok},
        "brain": {"mode": cfg["brain"]["mode"], "api_key_required": False},
        "github_relay": relay,
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
        try:
            decision = load_plan(task["id"])
        except Exception as exc:
            set_task_status(project_state, task["id"], "blocked", error=str(exc))
            save_state(project_state, phase="blocked", blocker=str(exc))
            audit("brain_plan_failed", task_id=task["id"], error=str(exc))
            print(f"Desktop GPT plan decision is invalid: {exc}", file=sys.stderr)
            return 14
        if decision is None:
            request_path = request_plan(task)
            relative_request = str(request_path.relative_to(ROOT)).replace("\\", "/")
            set_task_status(project_state, task["id"], "awaiting_brain", request=relative_request)
            save_state(project_state, phase="awaiting_codex_gpt", current_task=task["id"], blocker="Codex desktop/mobile GPT plan decision required")
            audit("desktop_brain_plan_requested", task_id=task["id"], request=relative_request)
            try:
                relay = publish_control_update(f"{task['id']}: request GPT plan", [relative_request, ".ai/project_state.json", ".ai/audit.jsonl"])
            except Exception as exc:
                set_task_status(project_state, task["id"], "blocked", error=str(exc))
                save_state(project_state, phase="blocked", blocker=str(exc))
                audit("github_plan_request_publish_failed", task_id=task["id"], error=str(exc))
                print(f"GitHub plan request publication failed: {exc}", file=sys.stderr)
                return 19
            print(json.dumps({"status": "awaiting_codex_gpt", "task_id": task["id"], "request": relative_request}, ensure_ascii=False, indent=2))
            return 16
        if decision["decision"] != "execute":
            audit("brain_plan", task_id=task["id"], decision=decision["decision"], rationale=decision["rationale"])
            status = "awaiting_human" if decision["decision"] == "human_gate" else "blocked"
            set_task_status(project_state, task["id"], status, reason=decision["rationale"])
            save_state(project_state, phase=status, blocker=decision["rationale"])
            print(json.dumps(decision, ensure_ascii=False, indent=2))
            return 12 if status == "awaiting_human" else 13
        if plan_only:
            set_task_status(project_state, task["id"], "queued", last_plan=decision)
            save_state(project_state, phase="ready", current_task=None)
            print(json.dumps(decision, ensure_ascii=False, indent=2))
            return 0
        run_id = utc_now().replace("-", "").replace(":", "").replace(".", "") + "-" + uuid.uuid4().hex[:8]
        try:
            branch = prepare_task_branch(task["id"], run_id)
        except Exception as exc:
            set_task_status(project_state, task["id"], "blocked", error=str(exc), run_id=run_id)
            save_state(project_state, phase="blocked", blocker=str(exc))
            audit("github_branch_prepare_failed", task_id=task["id"], run_id=run_id, error=str(exc))
            print(f"GitHub relay could not prepare task branch: {exc}", file=sys.stderr)
            return 18
        audit("brain_plan", task_id=task["id"], run_id=run_id, branch=branch, decision=decision["decision"], rationale=decision["rationale"])
        previous_attempts = int(project_state.setdefault("task_statuses", {}).setdefault(task["id"], {}).get("attempts", 0))
        max_attempts = int(config()["runtime"].get("max_attempts_per_task", 3))
        if previous_attempts >= max_attempts:
            set_task_status(project_state, task["id"], "failed", error="maximum attempts exhausted")
            save_state(project_state, phase="failed", blocker="maximum attempts exhausted")
            return 15
        set_task_status(project_state, task["id"], "executing", run_id=run_id, branch=branch, attempts=previous_attempts + 1)
        save_state(project_state, phase="executing", last_run_id=run_id)
        before = set(changed_paths())
        try:
            executor_result = execute(task, decision, run_id, allowed_paths(task))
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
        review_request = request_review(task, run_id, manifest["manifest_path"])
        relative_request = str(review_request.relative_to(ROOT)).replace("\\", "/")
        set_task_status(project_state, task["id"], "awaiting_review", run_id=run_id, evidence_manifest=manifest["manifest_path"], changed_paths=manifest["path_guard"]["changed_paths"], review_request=relative_request)
        save_state(project_state, phase="awaiting_codex_gpt_review", last_validation=validation, blocker="Codex desktop/mobile GPT final review required")
        audit("desktop_brain_review_requested", task_id=task["id"], run_id=run_id, request=relative_request)
        try:
            relay = publish_candidate(task, run_id, branch, manifest["path_guard"]["changed_paths"], manifest["manifest_path"], relative_request)
            request_value = json.loads(review_request.read_text(encoding="utf-8"))
            request_value.update({
                "github_pr": relay.get("pr_url"),
                "github_branch": branch,
                "github_review_url": relay.get("review_url"),
                "github_relay_mode": relay.get("relay_mode", "git_branch"),
            })
            atomic_json(review_request, request_value)
            set_task_status(
                project_state,
                task["id"],
                "awaiting_review",
                github_pr=relay.get("pr_url"),
                github_review_url=relay.get("review_url"),
                github_relay_mode=relay.get("relay_mode", "git_branch"),
                branch=branch,
            )
            save_state(project_state)
            publish_branch_metadata(f"{task['id']}: attach GPT review metadata", [relative_request, ".ai/project_state.json"], branch)
        except Exception as exc:
            set_task_status(project_state, task["id"], "blocked", error=str(exc), run_id=run_id, branch=branch)
            save_state(project_state, phase="blocked", blocker=str(exc))
            audit("github_candidate_publish_failed", task_id=task["id"], run_id=run_id, error=str(exc))
            print(f"GitHub candidate publication failed: {exc}", file=sys.stderr)
            return 23
        print(json.dumps({
            "status": "awaiting_codex_gpt_review",
            "task_id": task["id"],
            "run_id": run_id,
            "request": relative_request,
            "github_branch": branch,
            "github_review_url": relay.get("review_url"),
            "github_pr": relay.get("pr_url"),
            "github_relay_mode": relay.get("relay_mode", "git_branch"),
        }, ensure_ascii=False, indent=2))
        return 17


def recover_stale(args: argparse.Namespace) -> int:
    """Recover an orphaned local execution after the controller process was interrupted."""
    with controller_lock():
        project_state = state()
        task_ids = {task["id"] for task in load_tasks()}
        task_id = args.task_id
        if task_id not in task_ids:
            print(f"Unknown task: {task_id}", file=sys.stderr)
            return 2

        entry = project_state.get("task_statuses", {}).get(task_id, {})
        current_status = str(entry.get("status", "queued"))
        recoverable = {"executing", "code_ready", "validating"}
        if current_status not in recoverable:
            print(f"{task_id} status={current_status} is not an orphan-recoverable state", file=sys.stderr)
            return 3

        settings = config()["github_relay"]
        base_branch = str(settings["base_branch"])
        remote = str(settings["remote"])
        recorded_branch = str(entry.get("branch") or "")
        run_id = str(entry.get("run_id") or "")
        branch_result = git(["branch", "--show-current"])
        if branch_result.returncode != 0:
            print((branch_result.stderr or branch_result.stdout).strip(), file=sys.stderr)
            return 4
        current_branch = branch_result.stdout.strip()

        if current_branch != base_branch:
            if recorded_branch and current_branch != recorded_branch:
                print(
                    f"Refusing recovery: current branch {current_branch} does not match recorded task branch {recorded_branch}",
                    file=sys.stderr,
                )
                return 5
            dirty = bool(git(["status", "--porcelain"]).stdout.strip())
            stash_created = False
            if dirty:
                stash_message = f"NEWAPP recovery {task_id} {run_id or 'unknown-run'}"
                stash = git(["stash", "push", "-u", "-m", stash_message])
                if stash.returncode != 0:
                    print(f"Cannot preserve orphaned work: {(stash.stderr or stash.stdout).strip()}", file=sys.stderr)
                    return 6
                stash_created = True
            switch = git(["switch", base_branch])
            if switch.returncode != 0:
                print(f"Cannot return to {base_branch}: {(switch.stderr or switch.stdout).strip()}", file=sys.stderr)
                return 7
            pull = git(["pull", "--ff-only", remote, base_branch])
            if pull.returncode != 0:
                print(f"Cannot refresh {base_branch}: {(pull.stderr or pull.stdout).strip()}", file=sys.stderr)
                return 8
        else:
            stash_created = False

        # Reload main after switching branches so an orphaned branch-local state file
        # cannot overwrite a newer control decision already published to GitHub.
        project_state = state()
        set_task_status(
            project_state,
            task_id,
            "retry",
            recovery={
                "reason": args.reason,
                "by": args.by,
                "orphaned_status": current_status,
                "orphaned_run_id": run_id or None,
                "orphaned_branch": recorded_branch or None,
                "work_preserved_in_stash": stash_created,
            },
        )
        save_state(project_state, phase="ready", current_task=None, blocker=None)
        audit(
            "orphaned_execution_recovered",
            task_id=task_id,
            previous_status=current_status,
            run_id=run_id or None,
            branch=recorded_branch or None,
            work_preserved_in_stash=stash_created,
            by=args.by,
            reason=args.reason,
        )
        relay = publish_control_update(
            f"{task_id}: recover orphaned execution",
            [".ai/project_state.json", ".ai/audit.jsonl"],
        )
        print(json.dumps({
            "status": "recovered",
            "task_id": task_id,
            "previous_status": current_status,
            "next_status": "retry",
            "work_preserved_in_stash": stash_created,
            "github": relay,
        }, ensure_ascii=False, indent=2))
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


def record_plan_command(args: argparse.Namespace) -> int:
    project_state = state()
    if args.task_id not in {task["id"] for task in load_tasks()}:
        print(f"Unknown task: {args.task_id}", file=sys.stderr); return 2
    path = record_plan(args.task_id, args.decision, args.rationale, args.validation_focus, args.risk, args.by)
    next_status = "retry" if args.decision == "execute" else ("awaiting_human" if args.decision == "human_gate" else "blocked")
    set_task_status(project_state, args.task_id, next_status, brain_decision=str(path.relative_to(ROOT)).replace("\\", "/"))
    save_state(project_state, phase="ready" if next_status == "retry" else next_status, current_task=None if next_status == "retry" else args.task_id, blocker=None if next_status == "retry" else args.rationale)
    audit("desktop_brain_plan_recorded", task_id=args.task_id, decision=args.decision, actor=args.by)
    paths = [str(path.relative_to(ROOT)).replace("\\", "/"), ".ai/project_state.json", ".ai/audit.jsonl"]
    request_path = ROOT / config()["brain"]["requests_dir"] / f"{args.task_id}-plan-request.json"
    if request_path.exists():
        paths.append(str(request_path.relative_to(ROOT)).replace("\\", "/"))
    relay = publish_control_update(f"{args.task_id}: GPT plan decision", paths)
    print(json.dumps({"decision": str(path), "github": relay}, ensure_ascii=False, indent=2))
    return 0


def record_review_command(args: argparse.Namespace) -> int:
    project_state = state()
    task = next((item for item in load_tasks() if item["id"] == args.task_id), None)
    if task is None:
        print(f"Unknown task: {args.task_id}", file=sys.stderr); return 2
    entry = project_state.get("task_statuses", {}).get(args.task_id, {})
    if entry.get("status") != "awaiting_review" or entry.get("run_id") != args.run_id:
        print("Review does not match the pending task/run", file=sys.stderr); return 3
    path = record_review(args.task_id, args.run_id, args.decision, args.rationale, args.criterion, args.required_fix, args.by)
    review = json.loads(path.read_text(encoding="utf-8"))
    if args.decision != "accept":
        next_status = "awaiting_human" if args.decision == "human_gate" else "failed"
        set_task_status(project_state, args.task_id, next_status, review=review)
        save_state(project_state, phase=next_status, blocker=args.rationale, last_review=review)
        audit("desktop_brain_review_recorded", task_id=args.task_id, run_id=args.run_id, decision=args.decision, actor=args.by)
        relay = finalize_review(args.task_id, str(entry["branch"]), args.decision, [str(path.relative_to(ROOT)).replace("\\", "/"), ".ai/project_state.json", ".ai/audit.jsonl"], args.rationale)
        print(json.dumps({"task": args.task_id, "status": next_status, "github": relay}, ensure_ascii=False, indent=2))
        return 0
    set_task_status(project_state, args.task_id, "completed", review=review, run_id=args.run_id)
    save_state(project_state, phase="ready", current_task=None, last_completed_task=args.task_id, blocker=None, last_review=review)
    audit("task_completed", task_id=args.task_id, run_id=args.run_id, actor=args.by)
    relay = finalize_review(args.task_id, str(entry["branch"]), args.decision, [str(path.relative_to(ROOT)).replace("\\", "/"), ".ai/project_state.json", ".ai/audit.jsonl"], args.rationale)
    print(json.dumps({"task": args.task_id, "status": "completed", "github": relay}, ensure_ascii=False, indent=2))
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
    recover_parser = sub.add_parser("recover")
    recover_parser.add_argument("task_id"); recover_parser.add_argument("--by", default="Codex GPT Recovery"); recover_parser.add_argument("--reason", default="Controller process was interrupted and left an orphaned execution state")
    plan_parser = sub.add_parser("record-plan")
    plan_parser.add_argument("task_id"); plan_parser.add_argument("--decision", choices=["execute", "human_gate", "block"], required=True); plan_parser.add_argument("--rationale", required=True); plan_parser.add_argument("--validation-focus", action="append", default=[]); plan_parser.add_argument("--risk", action="append", default=[]); plan_parser.add_argument("--by", default="Codex GPT Desktop/Mobile Remote")
    review_parser = sub.add_parser("record-review")
    review_parser.add_argument("task_id"); review_parser.add_argument("run_id"); review_parser.add_argument("--decision", choices=["accept", "reject", "human_gate"], required=True); review_parser.add_argument("--rationale", required=True); review_parser.add_argument("--criterion", action="append", default=[]); review_parser.add_argument("--required-fix", action="append", default=[]); review_parser.add_argument("--by", default="Codex GPT Desktop/Mobile Remote")
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
    if command == "recover": return recover_stale(args)
    if command == "record-plan": return record_plan_command(args)
    if command == "record-review": return record_review_command(args)
    if command == "run":
        while True:
            result = run_one()
            if result != 0: return result
            if queue_head(load_tasks(), state()).reason == "queue_empty": return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
