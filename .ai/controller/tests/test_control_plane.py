from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

CONTROLLER = Path(__file__).resolve().parents[1]
if str(CONTROLLER) not in sys.path:
    sys.path.insert(0, str(CONTROLLER))

from task_loader import QueueResult, load_tasks, queue_head, requires_human_gate
from common import config, path_matches
from agent_loop import preflight
from cline_executor import console_message
from browser_acceptance import evaluate as browser_acceptance
from evidence import screenshot_requirement


class ControlPlaneContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tasks = load_tasks()

    def test_blueprint_has_unique_valid_dependency_graph(self) -> None:
        self.assertGreater(len(self.tasks), 0)
        self.assertEqual(len({task["id"] for task in self.tasks}), len(self.tasks))

    def test_first_task_is_queue_head(self) -> None:
        result = queue_head(self.tasks, {"task_statuses": {}})
        self.assertEqual("ready", result.reason)
        self.assertEqual(self.tasks[0]["id"], result.task["id"])

    def test_pending_review_does_not_block_unrelated_ready_task(self) -> None:
        state = {
            "task_statuses": {
                "NEWAPP-001": {"status": "completed"},
                "NEWAPP-002": {"status": "awaiting_review"},
            }
        }
        result = queue_head(self.tasks, state)
        self.assertEqual("ready", result.reason)
        self.assertEqual("NEWAPP-006", result.task["id"])

    def test_active_execution_remains_exclusive(self) -> None:
        state = {
            "task_statuses": {
                "NEWAPP-001": {"status": "completed"},
                "NEWAPP-002": {"status": "executing"},
            }
        }
        result = queue_head(self.tasks, state)
        self.assertIsNone(result.task)
        self.assertIn("active execution", result.reason)

    def test_shared_database_migration_has_human_gate(self) -> None:
        task = next(item for item in self.tasks if item["id"] == "NEWAPP-009")
        required, _ = requires_human_gate(task)
        self.assertTrue(required)

    def test_read_only_schema_inspection_does_not_need_gate(self) -> None:
        task = next(item for item in self.tasks if item["id"] == "NEWAPP-003")
        required, _ = requires_human_gate(task)
        self.assertFalse(required)

    def test_brain_uses_desktop_bridge_without_api_key(self) -> None:
        settings = config()["brain"]
        self.assertEqual("codex_remote_file_bridge", settings["mode"])
        self.assertFalse(settings["api_key_required"])

    def test_executor_is_explicitly_pinned_to_deepseek(self) -> None:
        self.assertEqual("deepseek", config()["runtime"]["cline_provider"])

    def test_preflight_is_read_only_by_default(self) -> None:
        signature = inspect.signature(preflight)
        self.assertFalse(signature.parameters["write_state"].default)

    def test_newapp_002_has_focused_validation_commands(self) -> None:
        commands = config()["validation"]["task_commands"]["NEWAPP-002"]
        flattened = [" ".join(command) for command in commands]
        self.assertTrue(any("unittest discover -s tests/config" in command for command in flattened))
        self.assertTrue(any("tests/baseline/secret_scan.py --json" in command for command in flattened))

    def test_newapp_003_has_focused_validation_commands(self) -> None:
        commands = config()["validation"]["task_commands"]["NEWAPP-003"]
        flattened = [" ".join(command) for command in commands]
        self.assertTrue(any("unittest discover -s tests/schema" in command for command in flattened))
        self.assertTrue(any("tests/baseline/secret_scan.py --json" in command for command in flattened))

    def test_missing_real_browser_command_is_temporarily_nonblocking(self) -> None:
        self.assertFalse(config()["browser_acceptance"]["blocking"])
        result = browser_acceptance({"id": "TEST", "title": "UI screen"}, "test-run")
        self.assertEqual("deferred_nonblocking", result["status"])
        self.assertFalse(result["blocking"])

    def test_inquiry_text_does_not_trigger_ui_screenshot_gate(self) -> None:
        task = {"id": "TEST", "title": "Inspect inquiry schema"}
        self.assertFalse(screenshot_requirement(task))

    def test_cline_console_suppresses_reasoning_event_noise(self) -> None:
        line = '{"ts":"2026-09-23T12:08:06.121Z","type":"agent_event","event":{"type":"content_start","contentType":"reasoning","reasoning":"status","redacted":false}}'
        self.assertIsNone(console_message(line))

    def test_cline_console_keeps_errors_visible(self) -> None:
        line = '{"type":"agent_event","event":{"type":"error","message":"boom"}}'
        self.assertEqual("[Cline] ERROR: boom", console_message(line))

    def test_hidden_control_artifact_matches_allowed_path(self) -> None:
        self.assertTrue(path_matches(".ai/generated/evidence.json", [".ai/generated/**"]))
        self.assertTrue(path_matches("./.ai/generated/evidence.json", [".ai/generated/**"]))

    def test_rolling_queue_is_enabled(self) -> None:
        settings = config()["rolling_queue"]
        self.assertTrue(settings["enabled"])
        self.assertEqual(4, settings["target_size"])
        self.assertEqual(60, settings["review_interval_minutes"])
        self.assertTrue(settings["allow_unrelated_tasks_while_review_pending"])

    def test_github_relay_uses_private_git_transport_without_gh_requirement(self) -> None:
        settings = config()["github_relay"]
        self.assertTrue(settings["enabled"])
        self.assertTrue(settings["require_private"])
        self.assertFalse(settings["require_pull_request"])
        self.assertFalse(settings["require_github_cli"])
        self.assertEqual("git_ssh", settings["transport"])
        self.assertEqual("main", settings["base_branch"])

    def test_github_relay_is_local_only_until_remote_write_is_authorized(self) -> None:
        self.assertEqual("local_only", config()["github_relay"]["publication_mode"])


if __name__ == "__main__":
    unittest.main()
