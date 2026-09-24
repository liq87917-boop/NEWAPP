"""Read-only status console contract helper for NEWAPP-006 ("Establish automated status console").

``start_agent.bat`` and ``.ai/controller/**`` are protected control-plane paths, so this module does
not reimplement or edit the console. It renders the same machine-readable state the console prints
(``.ai/project_state.json`` plus ``docs/NEWAPP_TASKS_V1.yaml``) together with read-only Git facts, so
the tests in this package can prove the NEWAPP-006 acceptance criteria:

* the console starts from the repository root and forwards commands to the controller,
* ``status``/``preflight`` stay machine-readable and read-only,
* a pending GPT review does not globally block an unrelated dependency-safe task,
* no secret value reaches console output or generated evidence.

Refresh the machine-readable evidence with::

    .venv\\Scripts\\python.exe tests\\console\\status_snapshot.py --write \\
        --report .ai/generated/NEWAPP-006-status-console.json

Collection is read-only: this module never writes controller state, never creates a Git object and
never records an environment value. ``.env`` values are touched in process memory only by
:func:`find_secret_value_leaks`, which reports the offending variable *name* and never its value.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

CONSOLE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = CONSOLE_DIR.parents[1]
CONTROLLER_DIR = REPOSITORY_ROOT / ".ai" / "controller"
BASELINE_DIR = REPOSITORY_ROOT / "tests" / "baseline"
for _candidate in (CONSOLE_DIR, BASELINE_DIR):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from secret_scan import text_rule_findings  # noqa: E402

TASK_ID = "NEWAPP-006"
TASK_TITLE = "Establish automated status console"
TASK_PHASE = "P0"
REPORT_RELATIVE_PATH = ".ai/generated/NEWAPP-006-status-console.json"
CONSOLE_ENTRY_POINT = "start_agent.bat"
CONTROLLER_ENTRY_POINT = ".ai/controller/agent_loop.py"
ENVIRONMENT_FILE = ".env"

# Console commands that must exist for the operator-facing status console.
CONSOLE_COMMANDS: tuple[str, ...] = ("preflight", "status", "plan", "run-once", "run")

# Sources the console and this helper read; the state file is the only mutable one.
MACHINE_READABLE_SOURCES: tuple[tuple[str, str], ...] = (
    (".ai/project_state.json", "mutable queue, phase, blocker and last-validation state"),
    ("docs/NEWAPP_TASKS_V1.yaml", "immutable task blueprint and dependency graph"),
    (".ai/agent_config.yaml", "controller policy: allowed/protected paths, gates, rolling queue"),
    (".ai/audit.jsonl", "append-only control-plane audit trail"),
)

ACTIVE_EXECUTION_STATES = {"executing", "code_ready", "validating"}
TERMINAL_STATES = {"completed", "deferred", "skipped"}
ATTENTION_STATES = {"failed", "blocked", "awaiting_human"}

CONTROLLER_DISPATCH_MARKERS: tuple[tuple[str, str], ...] = (
    ("status_subcommand", 'sub.add_parser("status")'),
    ("preflight_subcommand", 'sub.add_parser("preflight")'),
    ("status_dispatch", 'if command == "status": return status_command()'),
    ("preflight_dispatch", 'if command == "preflight": return preflight()'),
    ("preflight_read_only_signature", "def preflight(write_state: bool = False) -> int:"),
    ("status_reader", "def status_command() -> int:"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def load_config(root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    """Read the controller policy the same way ``.ai/controller/common.load_yaml`` does."""
    raw = (root / ".ai" / "agent_config.yaml").read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        import yaml  # imported lazily so a JSON policy needs no extra dependency

        value = yaml.safe_load(raw)
    if not isinstance(value, dict):
        raise ValueError("Expected an object in .ai/agent_config.yaml")
    return value


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


_controller_modules: dict[str, Any] | None = None


def controller_modules() -> dict[str, Any]:
    """Import the controller queue policy read-only so tests never duplicate queue rules."""
    global _controller_modules
    if _controller_modules is None:
        if str(CONTROLLER_DIR) not in sys.path:
            sys.path.insert(0, str(CONTROLLER_DIR))
        import common
        import task_loader

        _controller_modules = {"common": common, "task_loader": task_loader}
    return _controller_modules


def run_git(root: Path, arguments: Sequence[str]) -> tuple[int, str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    return result.returncode, (result.stdout or "").strip()


def git_facts(root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    """Read Git state without changing the worktree, the index or the refs."""
    inside_code, inside = run_git(root, ["rev-parse", "--is-inside-work-tree"])
    repository_present = inside_code == 0 and inside.lower() == "true"
    head_code, head = run_git(root, ["rev-parse", "HEAD"]) if repository_present else (1, "")
    branch = ""
    clean = False
    tracked_file_count = 0
    if repository_present:
        _, branch = run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"])
        status_code, status_text = run_git(root, ["status", "--porcelain"])
        clean = status_code == 0 and not status_text.strip()
        _, listing = run_git(root, ["ls-files"])
        tracked_file_count = len([line for line in listing.splitlines() if line.strip()])
    return {
        "repository_present": repository_present,
        "baseline_commit_present": head_code == 0 and bool(head),
        "head_commit": head or None,
        "branch": branch or None,
        "worktree_clean": clean,
        "tracked_file_count": tracked_file_count,
    }


def console_entry_point_facts(root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    """Describe the launcher contract of ``start_agent.bat`` without executing it."""
    path = root / CONSOLE_ENTRY_POINT
    text = read_text(path)
    return {
        "path": CONSOLE_ENTRY_POINT,
        "exists": path.is_file(),
        "sha256": sha256_file(path),
        "changes_to_repository_root": 'cd /d "%~dp0"' in text,
        "python_selection": {
            "local_virtual_environment": ".venv\\Scripts\\python.exe" in text,
            "windows_launcher": "py -3" in text,
            "system_interpreter": "where python" in text,
        },
        "controller_entry_point": CONTROLLER_ENTRY_POINT,
        "dispatches_controller": "agent_loop.py" in text,
        "forwards_explicit_arguments": "%*" in text,
        "default_command": "run" if 'agent_loop.py" run' in text else None,
        "read_only_path_documented": "start_agent.bat preflight" in text,
        "keeps_window_open_on_blocker": "pause >nul" in text,
        "exit_code_propagated": "exit /b %EXITCODE%" in text,
    }


def machine_readable_source_facts(root: Path = REPOSITORY_ROOT) -> list[dict[str, Any]]:
    return [
        {"path": path, "role": role, "exists": (root / path).is_file(), "sha256": sha256_file(root / path)}
        for path, role in MACHINE_READABLE_SOURCES
    ]


def controller_contract_facts(root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    """Statically confirm the protected controller still exposes the console commands."""
    path = root / CONTROLLER_ENTRY_POINT
    text = read_text(path)
    markers = {name: marker in text for name, marker in CONTROLLER_DISPATCH_MARKERS}
    commands = {name: f'"{name}"' in text for name in CONSOLE_COMMANDS}
    return {
        "path": CONTROLLER_ENTRY_POINT,
        "exists": path.is_file(),
        "sha256": sha256_file(path),
        "markers": markers,
        "commands": commands,
        "contract_intact": path.is_file() and all(markers.values()) and all(commands.values()),
    }


def environment_values(root: Path = REPOSITORY_ROOT) -> dict[str, str]:
    """Read ``.env`` into process memory only; callers must never record the returned values."""
    common = controller_modules()["common"]
    return common.read_env(root / ENVIRONMENT_FILE)


MIN_SECRET_MATCH_LENGTH = 4


def find_secret_value_leaks(text: str, values: dict[str, str]) -> list[str]:
    """Return only the *names* of environment entries whose value appears in ``text``."""
    leaks: list[str] = []
    for name, value in values.items():
        candidate = str(value)
        if len(candidate) < MIN_SECRET_MATCH_LENGTH:
            continue
        if candidate in text:
            leaks.append(str(name))
    return sorted(leaks)


def content_rule_findings(text: str) -> list[dict[str, Any]]:
    """Reuse the reviewed NEWAPP-001 scanner rules; only rule ids, paths and lines are returned."""
    return text_rule_findings("console_status_snapshot", text)


def synthetic_state(completed: Iterable[str]) -> dict[str, Any]:
    """Build the minimal control state the queue policy needs (fixture helper)."""
    return {"task_statuses": {task_id: {"status": "completed"} for task_id in completed}}


def with_task_status(project_state: dict[str, Any], task_id: str, status: str) -> dict[str, Any]:
    updated = copy.deepcopy(project_state)
    updated.setdefault("task_statuses", {}).setdefault(task_id, {})["status"] = status
    return updated


def queue_semantics_facts(tasks: Sequence[dict[str, Any]], task_loader: Any | None = None) -> dict[str, Any]:
    """Prove the rolling-queue policy the console displays, using dependency-safe fixtures."""
    module = task_loader or controller_modules()["task_loader"]
    task_list = list(tasks)
    dependencies = {task["id"]: list(task["depends_on"]) for task in task_list}
    root_ids = [task["id"] for task in task_list if not task["depends_on"]]
    if not root_ids:
        return {"available": False}

    def satisfied(task_id: str, control_state: dict[str, Any]) -> bool:
        return all(module.effective_status(dep, control_state) == "completed" for dep in dependencies.get(task_id, []))

    def runnable(task_id: str, control_state: dict[str, Any]) -> bool:
        return module.effective_status(task_id, control_state) == "queued" and satisfied(task_id, control_state)

    base_state = synthetic_state(root_ids)
    base_head = module.queue_head(task_list, base_state)
    if base_head.task is None:
        return {"available": False, "baseline_ready": False, "baseline_reason": base_head.reason}
    baseline_task = base_head.task["id"]

    unrelated = [task["id"] for task in task_list if task["id"] != baseline_task and runnable(task["id"], base_state)]
    review_target = unrelated[0] if unrelated else baseline_task
    review_state = with_task_status(base_state, review_target, "awaiting_review")
    review_head = module.queue_head(task_list, review_state)
    if unrelated:
        pending_case = "unrelated_task_still_selected"
        selected = review_head.task["id"] if review_head.task else None
        pending_ok = selected is not None and selected != review_target and runnable(selected, review_state)
    else:
        pending_case = "no_unrelated_runnable_task_in_blueprint"
        pending_ok = review_head.task is None or review_head.task["id"] != review_target

    active_state = with_task_status(base_state, root_ids[0], "executing")
    active_head = module.queue_head(task_list, active_state)
    all_completed = module.queue_head(task_list, synthetic_state(dependencies))
    return {
        "available": True,
        "baseline_ready": base_head.reason == "ready",
        "baseline_task": baseline_task,
        "pending_review_case": pending_case,
        "pending_review_task": review_target,
        "selected_after_review": review_head.task["id"] if review_head.task else None,
        "pending_review_does_not_block_unrelated_task": bool(pending_ok),
        "active_execution_is_exclusive": active_head.task is None and "active execution" in active_head.reason,
        "completed_queue_is_empty": all_completed.task is None and all_completed.reason == "queue_empty",
    }


def _entry(statuses: dict[str, Any], task_id: str) -> dict[str, Any]:
    value = statuses.get(task_id, {})
    return value if isinstance(value, dict) else {}


def status_snapshot(
    root: Path = REPOSITORY_ROOT,
    *,
    project_state: dict[str, Any] | None = None,
    config_data: dict[str, Any] | None = None,
    tasks: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Render the console status view from machine-readable state without writing anything."""
    modules = controller_modules()
    task_loader = modules["task_loader"]
    task_list = list(tasks) if tasks is not None else task_loader.load_tasks()
    control_state = copy.deepcopy(project_state) if project_state is not None else read_json(root / ".ai" / "project_state.json")
    policy = config_data if config_data is not None else load_config(root)
    statuses = control_state.get("task_statuses", {})
    if not isinstance(statuses, dict):
        statuses = {}

    effective = {task["id"]: task_loader.effective_status(task["id"], control_state) for task in task_list}
    head = task_loader.queue_head(task_list, control_state)
    decisions_dir = root / str((policy.get("brain") or {}).get("decisions_dir", ".ai/brain/decisions"))
    counts = Counter(effective[task["id"]] for task in task_list)
    active = sorted(task_id for task_id, status in effective.items() if status in ACTIVE_EXECUTION_STATES)
    attention = [
        {
            "task_id": task["id"],
            "status": effective[task["id"]],
            "reason": _entry(statuses, task["id"]).get("reason") or _entry(statuses, task["id"]).get("error"),
        }
        for task in task_list
        if effective[task["id"]] in ATTENTION_STATES
    ]
    blockers: list[str] = []
    if control_state.get("blocker"):
        blockers.append(str(control_state["blocker"]))
    if control_state.get("paused"):
        blockers.append("controller paused: " + str(control_state.get("pause_reason") or "no reason recorded"))
    blockers.extend(f"{item['task_id']} status={item['status']}" for item in attention if item["status"] != "awaiting_human")
    if active:
        blockers.append("active execution holds the queue: " + ", ".join(active))

    validation = control_state.get("last_validation") or {}
    rolling = policy.get("rolling_queue") or {}
    return {
        "generated_at": utc_now(),
        "read_only": True,
        "console": {
            "entry_point": console_entry_point_facts(root),
            "controller": controller_contract_facts(root),
            "commands": list(CONSOLE_COMMANDS),
        },
        "sources": machine_readable_source_facts(root),
        "git": git_facts(root),
        "queue": {
            "phase": control_state.get("phase"),
            "paused": bool(control_state.get("paused")),
            "pause_reason": control_state.get("pause_reason"),
            "current_task": control_state.get("current_task"),
            "last_completed_task": control_state.get("last_completed_task"),
            "last_run_id": control_state.get("last_run_id"),
            "queue_head": head.task["id"] if head.task else None,
            "queue_reason": head.reason,
            "status_counts": dict(sorted(counts.items())),
            "active_executions": active,
            "pending_reviews": [task["id"] for task in task_list if effective[task["id"]] == "awaiting_review"],
            "planned_tasks": [
                task["id"]
                for task in task_list
                if (decisions_dir / f"{task['id']}-plan.json").is_file() and effective[task["id"]] not in TERMINAL_STATES
            ],
            "attention": attention,
            "rows": [{"id": task["id"], "status": effective[task["id"]], "title": task.get("title")} for task in task_list],
        },
        "last_validation": {
            "recorded": bool(validation),
            "status": validation.get("status"),
            "exit_code": validation.get("exit_code"),
            "profile": validation.get("profile"),
            "step_count": len(validation.get("steps") or []),
            "log": validation.get("log"),
        },
        "blockers": blockers,
        "rolling_queue": {
            "enabled": bool(rolling.get("enabled")),
            "target_size": int(rolling.get("target_size") or 0),
            "idle_poll_seconds": int(rolling.get("idle_poll_seconds") or 0),
            "review_interval_minutes": int(rolling.get("review_interval_minutes") or 0),
            "allow_unrelated_tasks_while_review_pending": bool(rolling.get("allow_unrelated_tasks_while_review_pending")),
        },
        "secret_safety": {
            "environment_values_read_into_snapshot": False,
            "environment_file": {"path_label": ENVIRONMENT_FILE, "content_recorded": False},
            "forbidden_key_name_patterns": list((policy.get("environment") or {}).get("never_log_patterns", [])),
            "recorded_value_policy": "task ids, statuses, counts, repository-relative paths and hashes only",
        },
    }


def build_report(root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    """Assemble the machine-readable NEWAPP-006 evidence from live read-only state."""
    modules = controller_modules()
    snapshot = status_snapshot(root)
    text = json.dumps(snapshot, ensure_ascii=False, indent=2)
    leaks = find_secret_value_leaks(text, environment_values(root))
    findings = content_rule_findings(text)
    semantics = queue_semantics_facts(modules["task_loader"].load_tasks(), modules["task_loader"])
    entry = snapshot["console"]["entry_point"]
    controller = snapshot["console"]["controller"]
    rolling = snapshot["rolling_queue"]
    verification = {
        "console_entry_point_exists": entry["exists"],
        "console_starts_from_repository_root": entry["changes_to_repository_root"],
        "console_dispatches_controller_with_arguments": entry["dispatches_controller"] and entry["forwards_explicit_arguments"],
        "console_default_command_is_rolling_run": entry["default_command"] == "run",
        "console_documents_read_only_preflight": entry["read_only_path_documented"],
        "console_propagates_exit_code": entry["exit_code_propagated"],
        "controller_exposes_console_commands": controller["contract_intact"],
        "preflight_defaults_to_read_only": controller["markers"]["preflight_read_only_signature"],
        "snapshot_is_json_serialisable": json.loads(text) == snapshot,
        "queue_reason_is_machine_readable": bool(snapshot["queue"]["queue_reason"]),
        "snapshot_contains_no_known_environment_value": not leaks,
        "snapshot_passes_repository_content_rules": not findings,
        "pending_review_does_not_block_unrelated_task": bool(semantics.get("pending_review_does_not_block_unrelated_task")),
        "active_execution_is_exclusive": bool(semantics.get("active_execution_is_exclusive")),
        "completed_queue_reports_queue_empty": bool(semantics.get("completed_queue_is_empty")),
        "rolling_queue_allows_unrelated_work_while_review_pending": rolling["allow_unrelated_tasks_while_review_pending"],
    }
    failed = sorted(name for name, value in verification.items() if value is not True)
    return {
        "task_id": TASK_ID,
        "task_title": TASK_TITLE,
        "task_phase": TASK_PHASE,
        "artifact": "console_status_contract_report",
        "generated_at": utc_now(),
        "generated_by": "newapp_executor (Cline/DeepSeek)",
        "completion_authority": "GPT brain final review; this artifact is evidence only",
        "read_only": True,
        "status": "verified" if not failed and not leaks and not findings else "attention_required",
        "verification": verification,
        "verification_summary": {
            "checks_total": len(verification),
            "checks_passed": len(verification) - len(failed),
            "checks_failed": failed,
            "secret_value_leaks": leaks,
            "content_rule_findings": findings,
        },
        "queue_semantics": semantics,
        "status_snapshot": snapshot,
        "unresolved_issues": [
            "The protected controller `status` command prints phase, current task, blockers and last validation from .ai/project_state.json but not Git facts; Git facts are printed by `preflight`. This helper collects them read-only. Adding them to `status` would require editing the protected path .ai/controller/agent_loop.py, so this executor reports the gap instead of editing it.",
            ".ai/agent_config.yaml (protected) defines no validation.task_commands entry for NEWAPP-006, so controller `safe` validation runs compileall only. Wiring `{python} -m unittest discover -s tests/console -p test_*.py` into controller validation is a controller/GPT decision.",
            ".github/workflows/** is a protected path, so the new console tests are not wired into CI by this task.",
        ],
        "limitations": [
            "Facts are point-in-time: branch, head commit, tracked-file count and queue state change while the rolling controller keeps running.",
            "The secret-value check compares the generated snapshot text against values present in the local .env (4 characters or longer) and the reviewed NEWAPP-001 content rules; the whole-repository scan remains tests/baseline/secret_scan.py.",
            "Behavioural checks are fixture based: they exercise the controller's own queue policy with synthetic states and never start a second controller or executor.",
            "docs/CONSOLE_STATUS_CONTRACT.md restates no volatile value; it points at this artifact for branch, commit, counts and hashes.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the NEWAPP status console contract snapshot without changing controller state")
    parser.add_argument("--root", default=str(REPOSITORY_ROOT))
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    parser.add_argument("--write", action="store_true", help="write the report to every --report path")
    parser.add_argument("--report", action="append", default=[], help="report path, absolute or relative to --root (repeatable)")
    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        report = build_report(root)
    except Exception as exc:  # fail closed: an unreadable source must not look verified
        print(json.dumps({"status": "error", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    if args.write:
        for target in args.report or [REPORT_RELATIVE_PATH]:
            candidate = Path(target)
            atomic_write_json(candidate if candidate.is_absolute() else root / candidate, report)
    summary = report["verification_summary"]
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            "task={task} status={status} checks={passed}/{total} leaks={leaks} content_findings={findings}".format(
                task=report["task_id"],
                status=report["status"],
                passed=summary["checks_passed"],
                total=summary["checks_total"],
                leaks=len(summary["secret_value_leaks"]),
                findings=len(summary["content_rule_findings"]),
            )
        )
        for name in summary["checks_failed"]:
            print(f"  FAILED {name}")
    return 0 if report["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())


