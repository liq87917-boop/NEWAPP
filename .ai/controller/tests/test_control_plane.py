from __future__ import annotations

import sys
import unittest
from pathlib import Path

CONTROLLER = Path(__file__).resolve().parents[1]
if str(CONTROLLER) not in sys.path:
    sys.path.insert(0, str(CONTROLLER))

from task_loader import QueueResult, load_tasks, queue_head, requires_human_gate
from common import config, path_matches


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

    def test_nonterminal_head_cannot_be_skipped(self) -> None:
        first = self.tasks[0]["id"]
        result = queue_head(self.tasks, {"task_statuses": {first: {"status": "failed"}}})
        self.assertIsNone(result.task)
        self.assertIn(first, result.reason)

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

    def test_hidden_control_artifact_matches_allowed_path(self) -> None:
        self.assertTrue(path_matches(".ai/generated/evidence.json", [".ai/generated/**"]))
        self.assertTrue(path_matches("./.ai/generated/evidence.json", [".ai/generated/**"]))

    def test_github_relay_is_private_pr_only(self) -> None:
        settings = config()["github_relay"]
        self.assertTrue(settings["enabled"])
        self.assertTrue(settings["require_private"])
        self.assertTrue(settings["require_pull_request"])
        self.assertEqual("main", settings["base_branch"])


if __name__ == "__main__":
    unittest.main()
