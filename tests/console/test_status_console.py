"""Status console contract tests for NEWAPP-006 ("Establish automated status console").

Every test is read-only. They parse the protected launcher, run the read-only ``status`` command in a
subprocess, or drive the controller queue policy with synthetic in-memory state. No test writes
controller state, evidence, a branch or a commit; the report round-trip test targets a temporary
directory only.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

CONSOLE_DIR = Path(__file__).resolve().parent
if str(CONSOLE_DIR) not in sys.path:
    sys.path.insert(0, str(CONSOLE_DIR))

from status_snapshot import (  # noqa: E402
    CONSOLE_COMMANDS,
    CONTROLLER_ENTRY_POINT,
    ENVIRONMENT_FILE,
    REPORT_RELATIVE_PATH,
    REPOSITORY_ROOT,
    TASK_ID,
    build_report,
    console_entry_point_facts,
    content_rule_findings,
    controller_contract_facts,
    controller_modules,
    environment_values,
    find_secret_value_leaks,
    main,
    queue_semantics_facts,
    status_snapshot,
)

STATE_RELATIVE_PATH = ".ai/project_state.json"
AUDIT_RELATIVE_PATH = ".ai/audit.jsonl"
STATUS_COMMAND = [sys.executable, str(REPOSITORY_ROOT / CONTROLLER_ENTRY_POINT), "status"]


def file_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def task_loader() -> Any:
    return controller_modules()["task_loader"]


def read_state() -> dict[str, Any]:
    return json.loads((REPOSITORY_ROOT / STATE_RELATIVE_PATH).read_text(encoding="utf-8"))


def run_status_command() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        STATUS_COMMAND,
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        timeout=180,
    )


class ConsoleEntryPointTests(unittest.TestCase):
    """The launcher must start from the repository root and reach the protected controller."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.facts = console_entry_point_facts(REPOSITORY_ROOT)
        cls.source = (REPOSITORY_ROOT / "start_agent.bat").read_text(encoding="utf-8", errors="replace")

    def test_console_entry_point_exists(self) -> None:
        self.assertTrue(self.facts["exists"])
        self.assertIsNotNone(self.facts["sha256"])

    def test_console_starts_from_repository_root(self) -> None:
        self.assertTrue(self.facts["changes_to_repository_root"])
        self.assertIn('cd /d "%~dp0"', self.source)

    def test_console_dispatches_controller_and_forwards_arguments(self) -> None:
        self.assertTrue(self.facts["dispatches_controller"])
        self.assertTrue(self.facts["forwards_explicit_arguments"])
        self.assertEqual(CONTROLLER_ENTRY_POINT, self.facts["controller_entry_point"])
        self.assertIn("agent_loop.py", self.source)
        self.assertIn("%*", self.source)

    def test_console_default_is_rolling_run_with_documented_preflight(self) -> None:
        self.assertEqual("run", self.facts["default_command"])
        self.assertTrue(self.facts["read_only_path_documented"])
        self.assertTrue(self.facts["python_selection"]["local_virtual_environment"])

    def test_console_propagates_exit_code_and_reports_blockers(self) -> None:
        self.assertTrue(self.facts["exit_code_propagated"])
        self.assertTrue(self.facts["keeps_window_open_on_blocker"])


class ControllerConsoleContractTests(unittest.TestCase):
    """The protected controller must keep exposing machine-readable console commands."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.facts = controller_contract_facts(REPOSITORY_ROOT)
        cls.state_path = REPOSITORY_ROOT / STATE_RELATIVE_PATH
        cls.audit_path = REPOSITORY_ROOT / AUDIT_RELATIVE_PATH

    def test_controller_exposes_status_and_preflight_commands(self) -> None:
        self.assertTrue(self.facts["exists"])
        self.assertTrue(self.facts["contract_intact"], self.facts["markers"])
        for command in CONSOLE_COMMANDS:
            self.assertTrue(self.facts["commands"][command], command)

    def test_preflight_is_read_only_by_default(self) -> None:
        self.assertTrue(self.facts["markers"]["preflight_read_only_signature"])

    def test_status_command_is_machine_readable(self) -> None:
        result = run_status_command()
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        for key in ("project_state", "queue_head", "queue_reason", "rolling_queue", "tasks"):
            self.assertIn(key, payload)
        self.assertIsInstance(payload["tasks"], list)
        self.assertTrue(payload["tasks"])
        self.assertTrue(all({"id", "status"} <= set(row) for row in payload["tasks"]))

        state = read_state()
        self.assertEqual(state, payload["project_state"])
        for key in ("phase", "current_task", "blocker", "last_validation"):
            self.assertEqual(state.get(key), payload["project_state"].get(key), key)

    def test_status_command_changes_no_controller_state(self) -> None:
        before = (file_digest(self.state_path), file_digest(self.audit_path))
        result = run_status_command()
        self.assertEqual(0, result.returncode, result.stderr)
        after = (file_digest(self.state_path), file_digest(self.audit_path))
        self.assertEqual(before, after, "the read-only status command must not rewrite control state")


class RollingQueueSemanticsTests(unittest.TestCase):
    """Pending GPT review must not globally block unrelated dependency-safe work."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.loader = task_loader()
        cls.tasks = cls.loader.load_tasks()
        cls.semantics = queue_semantics_facts(cls.tasks, cls.loader)

    def test_blueprint_has_a_dependency_safe_ready_task(self) -> None:
        self.assertTrue(self.semantics["available"], self.semantics)
        self.assertTrue(self.semantics["baseline_ready"], self.semantics)

    def test_pending_review_does_not_block_unrelated_task(self) -> None:
        self.assertTrue(self.semantics["pending_review_does_not_block_unrelated_task"], self.semantics)
        self.assertNotEqual(self.semantics["selected_after_review"], self.semantics["pending_review_task"])

    def test_review_wait_still_selects_a_dependency_safe_task(self) -> None:
        completed = {task["id"]: {"status": "completed"} for task in self.tasks if not task["depends_on"]}
        self.assertTrue(completed)
        first = self.loader.queue_head(self.tasks, {"task_statuses": dict(completed)})
        self.assertEqual("ready", first.reason)
        chosen = first.task["id"]

        pending = dict(completed)
        pending[chosen] = {"status": "awaiting_review"}
        state = {"task_statuses": pending}
        after = self.loader.queue_head(self.tasks, state)
        self.assertIsNotNone(after.task, "a pending review must not globally block the queue")
        self.assertEqual("ready", after.reason)
        self.assertNotEqual(chosen, after.task["id"])
        for dep in next(task["depends_on"] for task in self.tasks if task["id"] == after.task["id"]):
            self.assertEqual("completed", self.loader.effective_status(dep, state))

    def test_active_execution_remains_exclusive(self) -> None:
        self.assertTrue(self.semantics["active_execution_is_exclusive"], self.semantics)

    def test_completed_queue_reports_queue_empty(self) -> None:
        self.assertTrue(self.semantics["completed_queue_is_empty"], self.semantics)

    def test_console_snapshot_matches_controller_queue_selection(self) -> None:
        snapshot = status_snapshot(REPOSITORY_ROOT)
        head = self.loader.queue_head(self.tasks, read_state())
        self.assertEqual(head.reason, snapshot["queue"]["queue_reason"])
        self.assertEqual(head.task["id"] if head.task else None, snapshot["queue"]["queue_head"])

    def test_rolling_policy_allows_unrelated_work_while_review_pending(self) -> None:
        rolling = status_snapshot(REPOSITORY_ROOT)["rolling_queue"]
        self.assertTrue(rolling["enabled"])
        self.assertTrue(rolling["allow_unrelated_tasks_while_review_pending"])
        self.assertGreaterEqual(rolling["review_interval_minutes"], 1)


class SnapshotSafetyTests(unittest.TestCase):
    """The console view must stay read-only, machine-readable and free of secret values."""

    def test_snapshot_builder_writes_nothing(self) -> None:
        generated = REPOSITORY_ROOT / ".ai" / "generated"
        before = (
            file_digest(REPOSITORY_ROOT / STATE_RELATIVE_PATH),
            file_digest(REPOSITORY_ROOT / AUDIT_RELATIVE_PATH),
            sorted(path.name for path in generated.iterdir()),
        )
        snapshot = status_snapshot(REPOSITORY_ROOT)
        after = (
            file_digest(REPOSITORY_ROOT / STATE_RELATIVE_PATH),
            file_digest(REPOSITORY_ROOT / AUDIT_RELATIVE_PATH),
            sorted(path.name for path in generated.iterdir()),
        )
        self.assertEqual(before, after)
        self.assertEqual([], list(generated.glob("*.tmp")))
        self.assertTrue(snapshot["read_only"])

    def test_snapshot_is_json_serialisable(self) -> None:
        snapshot = status_snapshot(REPOSITORY_ROOT)
        self.assertEqual(snapshot, json.loads(json.dumps(snapshot, ensure_ascii=False)))

    def test_snapshot_records_no_environment_value(self) -> None:
        text = json.dumps(status_snapshot(REPOSITORY_ROOT), ensure_ascii=False, indent=2)
        leaks = find_secret_value_leaks(text, environment_values(REPOSITORY_ROOT))
        self.assertEqual([], leaks, "environment variables whose value reached the snapshot: " + ", ".join(leaks))

    def test_snapshot_passes_repository_content_rules(self) -> None:
        text = json.dumps(status_snapshot(REPOSITORY_ROOT), ensure_ascii=False, indent=2)
        self.assertEqual([], content_rule_findings(text))

    def test_snapshot_declares_environment_file_is_never_recorded(self) -> None:
        safety = status_snapshot(REPOSITORY_ROOT)["secret_safety"]
        self.assertFalse(safety["environment_values_read_into_snapshot"])
        self.assertEqual(ENVIRONMENT_FILE, safety["environment_file"]["path_label"])
        self.assertFalse(safety["environment_file"]["content_recorded"])
        self.assertTrue(safety["forbidden_key_name_patterns"])

    def test_snapshot_surfaces_blockers_current_task_and_last_validation(self) -> None:
        first_task = task_loader().load_tasks()[0]["id"]
        synthetic = copy.deepcopy(read_state())
        synthetic["phase"] = "blocked"
        synthetic["current_task"] = first_task
        synthetic["blocker"] = "unit-test blocker message"
        synthetic["paused"] = True
        synthetic["pause_reason"] = "unit-test pause reason"
        synthetic["task_statuses"] = dict(synthetic.get("task_statuses", {}))
        synthetic["task_statuses"][first_task] = {"status": "failed", "error": "unit-test failure"}
        synthetic["last_validation"] = {
            "status": "failed",
            "exit_code": 3,
            "profile": "safe",
            "steps": [{"exit_code": 3}],
            "log": ".ai/logs/unit-test.log",
        }

        snapshot = status_snapshot(REPOSITORY_ROOT, project_state=synthetic)
        self.assertEqual("blocked", snapshot["queue"]["phase"])
        self.assertEqual(first_task, snapshot["queue"]["current_task"])
        self.assertTrue(snapshot["queue"]["paused"])
        self.assertIn("unit-test blocker message", snapshot["blockers"])
        self.assertTrue(any("unit-test pause reason" in item for item in snapshot["blockers"]))
        self.assertIn(f"{first_task} status=failed", snapshot["blockers"])
        self.assertEqual("failed", snapshot["last_validation"]["status"])
        self.assertEqual(3, snapshot["last_validation"]["exit_code"])
        self.assertEqual(1, snapshot["last_validation"]["step_count"])
        self.assertNotIn("unit-test", json.dumps(read_state(), ensure_ascii=False))


class ConsoleReportTests(unittest.TestCase):
    """The generated artifact must be machine-readable evidence for GPT review."""

    def test_report_verifies_the_live_console_contract(self) -> None:
        report = build_report(REPOSITORY_ROOT)
        self.assertEqual("verified", report["status"], report["verification_summary"])
        self.assertEqual([], report["verification_summary"]["checks_failed"])
        self.assertEqual([], report["verification_summary"]["secret_value_leaks"])
        self.assertEqual([], report["verification_summary"]["content_rule_findings"])
        self.assertEqual(len(report["verification"]), report["verification_summary"]["checks_total"])
        self.assertTrue(all(report["verification"].values()))
        self.assertTrue(report["queue_semantics"]["pending_review_does_not_block_unrelated_task"])
        self.assertTrue(report["read_only"])
        self.assertEqual(TASK_ID, report["task_id"])
        self.assertTrue(report["unresolved_issues"])
        self.assertTrue(report["limitations"])

    def test_write_mode_is_opt_in(self) -> None:
        generated = REPOSITORY_ROOT / ".ai" / "generated"
        before = sorted(path.name for path in generated.iterdir())
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            exit_code = main([])
        self.assertEqual(0, exit_code, stream.getvalue())
        self.assertIn(TASK_ID, stream.getvalue())
        self.assertEqual(before, sorted(path.name for path in generated.iterdir()))

    def test_json_mode_is_machine_readable(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            exit_code = main(["--json"])
        self.assertEqual(0, exit_code)
        payload = json.loads(stream.getvalue())
        self.assertEqual(TASK_ID, payload["task_id"])
        self.assertIn("status_snapshot", payload)
        self.assertIn("queue_semantics", payload)

    def test_report_writes_only_the_requested_path(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "console-status-report.json"
            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = main(["--write", "--report", str(target)])
            self.assertEqual(0, exit_code)
            self.assertTrue(target.is_file())
            self.assertEqual([], list(Path(folder).glob("*.tmp")))
            written = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(TASK_ID, written["task_id"])
            self.assertEqual("verified", written["status"])
            self.assertIn("status_snapshot", written)
            self.assertTrue(REPORT_RELATIVE_PATH.startswith(".ai/generated/"))


if __name__ == "__main__":
    unittest.main()
