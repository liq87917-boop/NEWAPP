"""Unit tests for the NEWAPP-001 repository baseline report utilities.

Tests either use disposable temporary directories or read the real repository in a read-only way.
No test writes to ``.ai/generated`` except into a temporary path, and the controller module is only
loaded read-only to compare the mirrored path-guard normalization with ``common.path_matches``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

BASELINE_DIR = Path(__file__).resolve().parent
if str(BASELINE_DIR) not in sys.path:
    sys.path.insert(0, str(BASELINE_DIR))

from repository_baseline import (  # noqa: E402
    GITIGNORE_REQUIRED_PATTERNS,
    REPOSITORY_RULE_FILES,
    REPORT_RELATIVE_PATH,
    TASK_ID,
    atomic_write_json,
    build_report,
    collect_facts,
    environment_file_facts,
    git_facts,
    gitignore_facts,
    main,
    normalize_for_path_guard,
    path_guard_compatibility,
    policy_facts,
    repository_rule_facts,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONTROLLER_COMMON = REPOSITORY_ROOT / ".ai" / "controller" / "common.py"


def fake_facts(**overrides: Any) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "generated_at": "2026-09-23T00:00:00Z",
        "executor_payload_received": False,
        "payload_reconstruction": {
            "controller_payload_section_present": False,
            "sources": ["docs/NEWAPP_TASKS_V1.yaml#NEWAPP-001"],
            "note": "unit test fixture",
        },
        "controller": {
            "available": True,
            "phase": "executing",
            "run_id": "test-run",
            "branch": "agent/test",
            "task_status": "executing",
        },
        "git": {
            "repository_present": True,
            "baseline_commit_present": True,
            "head_commit": "0" * 40,
            "branch": "agent/test",
            "tracked_file_count": 3,
        },
        "environment_file": {
            "path_label": ".env",
            "exists_locally": True,
            "ignored_by_git": True,
            "tracked_by_git": False,
            "content_read": False,
        },
        "gitignore_coverage": {
            "gitignore_present": True,
            "required_patterns": [".env"],
            "missing_patterns": [],
            "covered_count": 1,
            "required_count": 1,
        },
        "repository_rules": [
            {"path": ".clinerules", "exists": True, "sha256": "0" * 64, "missing_markers": [], "separation_confirmed": True}
        ],
        "secret_scan": {
            "scope": "git_tracked_files",
            "tracked_file_count": 3,
            "files_scanned": 3,
            "scanned_paths": ["src/app.py"],
            "files_skipped_binary": [],
            "files_skipped_large": [],
            "files_missing_on_disk": [],
            "content_rules": [],
            "path_rules": [],
            "findings_count": 0,
            "findings": [],
            "values_recorded": False,
            "status": "passed",
        },
        "policy": {"available": True},
    }
    facts.update(overrides)
    return facts


class GitignoreFactsTests(unittest.TestCase):
    def test_missing_patterns_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".gitignore").write_text(".env\n", encoding="utf-8", newline="\n")
            facts = gitignore_facts(root)
            self.assertTrue(facts["gitignore_present"])
            self.assertEqual(len(GITIGNORE_REQUIRED_PATTERNS), facts["required_count"])
            self.assertEqual(1, facts["covered_count"])
            self.assertIn("*.pem", facts["missing_patterns"])

    def test_every_required_pattern_can_be_covered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".gitignore").write_text("\n".join(GITIGNORE_REQUIRED_PATTERNS) + "\n", encoding="utf-8", newline="\n")
            facts = gitignore_facts(root)
            self.assertEqual([], facts["missing_patterns"])
            self.assertEqual(facts["required_count"], facts["covered_count"])

    def test_absent_gitignore_reports_everything_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            facts = gitignore_facts(Path(temporary))
            self.assertFalse(facts["gitignore_present"])
            self.assertEqual(0, facts["covered_count"])
            self.assertEqual(list(GITIGNORE_REQUIRED_PATTERNS), facts["missing_patterns"])


class RepositoryRuleFactsTests(unittest.TestCase):
    def test_missing_marker_marks_separation_unconfirmed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".clinerules").write_text("executor and controller only\n", encoding="utf-8", newline="\n")
            facts = repository_rule_facts(root, rules=[(".clinerules", ("executor", "controller", "gpt"))])
            self.assertFalse(facts[0]["separation_confirmed"])
            self.assertEqual(["gpt"], facts[0]["missing_markers"])
            self.assertIn("sha256", facts[0])

    def test_complete_rule_file_is_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".clinerules").write_text("GPT brain, controller and executor\n", encoding="utf-8", newline="\n")
            facts = repository_rule_facts(root, rules=[(".clinerules", ("executor", "controller", "gpt"))])
            self.assertTrue(facts[0]["separation_confirmed"])

    def test_absent_rule_file_is_not_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            facts = repository_rule_facts(Path(temporary))
            self.assertEqual(len(REPOSITORY_RULE_FILES), len(facts))
            self.assertFalse(any(item["separation_confirmed"] for item in facts))


class BuildReportTests(unittest.TestCase):
    def test_report_is_evidence_only_and_value_free(self) -> None:
        report = build_report(fake_facts())
        self.assertEqual(TASK_ID, report["task_id"])
        self.assertEqual("evidence_collected", report["status"])
        self.assertFalse(report["secret_values_included"])
        self.assertFalse(report["executor_payload_received"])
        self.assertIn("GPT", report["completion_authority"])
        self.assertEqual(3, len(report["acceptance_evidence"]))
        self.assertTrue(all(item["satisfied"] for item in report["acceptance_evidence"]))

    def test_tracked_env_switches_status_to_attention_required(self) -> None:
        facts = fake_facts(
            environment_file={
                "path_label": ".env",
                "exists_locally": True,
                "ignored_by_git": True,
                "tracked_by_git": True,
                "content_read": False,
            }
        )
        report = build_report(facts)
        self.assertEqual("attention_required", report["status"])
        self.assertFalse(report["acceptance_evidence"][0]["satisfied"])

    def test_scan_findings_switch_status_to_attention_required(self) -> None:
        scan = dict(fake_facts()["secret_scan"])
        scan.update({"findings_count": 1, "findings": [{"rule": "credential_assignment", "path": "src/a.py", "line": 3}], "status": "failed"})
        report = build_report(fake_facts(secret_scan=scan))
        self.assertEqual("attention_required", report["status"])
        self.assertFalse(report["acceptance_evidence"][1]["satisfied"])

    def test_report_round_trips_through_the_atomic_writer(self) -> None:
        report = build_report(fake_facts())
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "nested" / "report.json"
            atomic_write_json(target, report)
            self.assertEqual(report, json.loads(target.read_text(encoding="utf-8")))
            self.assertEqual([], list(target.parent.glob("*.tmp")))


class RepositoryFactsTests(unittest.TestCase):
    def test_environment_file_is_described_without_reading_content(self) -> None:
        facts = environment_file_facts(REPOSITORY_ROOT)
        self.assertEqual(".env", facts["path_label"])
        self.assertTrue(facts["exists_locally"])
        self.assertTrue(facts["ignored_by_git"])
        self.assertFalse(facts["tracked_by_git"])
        self.assertFalse(facts["content_read"])

    def test_git_facts_on_the_real_repository(self) -> None:
        facts = git_facts(REPOSITORY_ROOT)
        self.assertTrue(facts["repository_present"])
        self.assertTrue(facts["baseline_commit_present"])
        self.assertEqual(40, len(facts["head_commit"]))
        self.assertTrue(facts["branch"])
        self.assertGreaterEqual(facts["tracked_file_count"], 40)

    def test_policy_facts_come_from_the_controller_configuration(self) -> None:
        facts = policy_facts(REPOSITORY_ROOT)
        self.assertTrue(facts["available"])
        self.assertGreater(facts["protected_path_pattern_count"], 0)
        self.assertIn("*.md", facts["executor_allowed_paths"])
        self.assertIn("NEWAPP-009", facts["human_gate_task_ids"])

    def test_collect_facts_writes_nothing(self) -> None:
        generated = REPOSITORY_ROOT / ".ai" / "generated"
        before = sorted(path.name for path in generated.iterdir())
        facts = collect_facts(
            REPOSITORY_ROOT,
            generated_at="2026-09-23T00:00:00Z",
            payload_sources=[".ai/brain/decisions/NEWAPP-001-plan.json"],
        )
        after = sorted(path.name for path in generated.iterdir())
        self.assertEqual(before, after)
        self.assertEqual([], list(generated.glob("*.tmp")))
        report = build_report(facts)
        self.assertIn(report["status"], {"evidence_collected", "attention_required"})
        self.assertFalse(report["secret_values_included"])


class PathGuardCompatibilityTests(unittest.TestCase):
    ALLOWED = (".ai/generated/**", ".github/**", "docs/**", "tests/**", "*.md", ".gitignore")

    def test_dot_directory_artifact_is_accepted_by_the_controller_guard(self) -> None:
        view = path_guard_compatibility(
            [".ai/generated/report.json", "docs/report.json", "tests/baseline/x.py", ".gitignore"],
            self.ALLOWED,
        )
        accepted = {entry["path"]: entry["accepted"] for entry in view["paths"]}
        self.assertTrue(accepted[".ai/generated/report.json"])
        self.assertTrue(accepted["docs/report.json"])
        self.assertTrue(accepted["tests/baseline/x.py"])
        self.assertTrue(accepted[".gitignore"])
        self.assertTrue(view["all_paths_accepted"])
        self.assertEqual(".ai/generated/report.json", view["paths"][0]["normalized_for_guard"])
        self.assertEqual([".ai/generated/**"], view["paths"][0]["matched_patterns"])
        self.assertNotIn("lstrip", view["normalization"])

    def test_only_exact_leading_dot_slash_prefixes_are_removed(self) -> None:
        self.assertEqual(".ai/generated/report.json", normalize_for_path_guard("./.ai/generated/report.json"))
        self.assertEqual(".ai/generated/report.json", normalize_for_path_guard("././.ai/generated/report.json"))
        self.assertEqual(".clinerules", normalize_for_path_guard(".clinerules"))
        self.assertEqual("../docs/report.json", normalize_for_path_guard("..\\docs\\report.json"))
        self.assertEqual("docs/report.json", normalize_for_path_guard("docs\\report.json"))

    def test_dot_slash_prefixed_artifact_and_backslashes_are_accepted(self) -> None:
        view = path_guard_compatibility(
            ["./.ai/generated/report.json", ".ai\\generated\\report.json"],
            [".ai/generated/**"],
        )
        for entry in view["paths"]:
            self.assertEqual(".ai/generated/report.json", entry["normalized_for_guard"])
            self.assertTrue(entry["accepted"])
        self.assertTrue(view["all_paths_accepted"])

    def test_accepted_paths_only_report_all_paths_accepted(self) -> None:
        view = path_guard_compatibility(["docs/report.json"], ["docs/**"])
        self.assertTrue(view["all_paths_accepted"])
        self.assertEqual(["docs/**"], view["paths"][0]["matched_patterns"])

    def test_unresolved_issue_is_reported_for_rejected_paths(self) -> None:
        report = build_report(
            fake_facts(
                executor_paths=["src/app.py", ".ai/generated/report.json"],
                policy={"available": True, "executor_allowed_paths": [".ai/generated/**"]},
            )
        )
        issues = report["unresolved_issues"]
        self.assertEqual(1, len(issues))
        self.assertEqual(["src/app.py"], issues[0]["paths"])
        self.assertNotIn("lstrip", issues[0]["reason"])
        self.assertFalse(report["path_guard_compatibility"]["all_paths_accepted"])

    def test_no_unresolved_issue_when_all_paths_are_accepted(self) -> None:
        report = build_report(
            fake_facts(
                executor_paths=[".ai/generated/report.json", "docs/report.json"],
                policy={"available": True, "executor_allowed_paths": [".ai/generated/**", "docs/**"]},
            )
        )
        self.assertEqual([], report["unresolved_issues"])
        self.assertTrue(report["path_guard_compatibility"]["all_paths_accepted"])



class RealRepositoryGuardTests(unittest.TestCase):
    """Check the corrected normalization against the real policy and the controller module."""

    EXECUTOR_PATHS = (
        REPORT_RELATIVE_PATH,
        "docs/NEWAPP-001-baseline-report.json",
        "docs/REPOSITORY_BASELINE.md",
        "tests/__init__.py",
        "tests/baseline/__init__.py",
        "tests/baseline/repository_baseline.py",
        "tests/baseline/secret_scan.py",
        "tests/baseline/test_repository_baseline.py",
        "tests/baseline/test_secret_scan.py",
    )

    @staticmethod
    def load_controller_common() -> Any:
        """Load ``.ai/controller/common.py`` read-only; it has no import-time side effects."""
        spec = importlib.util.spec_from_file_location("newapp_controller_common_probe", CONTROLLER_COMMON)
        if spec is None or spec.loader is None:  # pragma: no cover - defensive
            raise unittest.SkipTest("controller common.py cannot be loaded")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_candidate_artifacts_are_accepted_by_the_configured_guard(self) -> None:
        policy = policy_facts(REPOSITORY_ROOT)
        self.assertTrue(policy["available"])
        view = path_guard_compatibility(self.EXECUTOR_PATHS, policy["executor_allowed_paths"])
        rejected = [entry["path"] for entry in view["paths"] if not entry["accepted"]]
        self.assertEqual([], rejected)
        self.assertTrue(view["all_paths_accepted"])

    @unittest.skipUnless(CONTROLLER_COMMON.is_file(), "controller common.py is unavailable")
    def test_controller_accepts_the_plan_required_artifact(self) -> None:
        module = self.load_controller_common()
        allowed = policy_facts(REPOSITORY_ROOT)["executor_allowed_paths"]
        self.assertTrue(module.path_matches(REPORT_RELATIVE_PATH, allowed))
        self.assertTrue(module.path_matches("./" + REPORT_RELATIVE_PATH, allowed))
        self.assertTrue(module.path_matches(".github/workflows/control-plane.yml", allowed))
        self.assertFalse(module.path_matches(".env", allowed))
        self.assertFalse(module.path_matches("src/app.py", ["docs/**"]))

    @unittest.skipUnless(CONTROLLER_COMMON.is_file(), "controller common.py is unavailable")
    def test_mirror_matches_the_controller_path_matches(self) -> None:
        module = self.load_controller_common()
        patterns = (".ai/generated/**", ".github/**", "docs/**", "tests/**", "*.md", ".gitignore", "src/**")
        paths = self.EXECUTOR_PATHS + ("./.ai/generated/NEWAPP-001-baseline-report.json", "src/app.py", ".env")
        for path in paths:
            with self.subTest(path=path):
                expected = bool(module.path_matches(path, patterns))
                mirrored = path_guard_compatibility([path], patterns)["paths"][0]["accepted"]
                self.assertEqual(expected, mirrored)


class CommandLineTests(unittest.TestCase):
    def test_write_creates_every_requested_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / ".ai" / "agent_config.yaml"
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text(
                json.dumps({"paths": {"executor_allowed": ["docs/**", ".ai/generated/**"]}}),
                encoding="utf-8",
                newline="\n",
            )
            code = main(
                [
                    "--root",
                    str(root),
                    "--write",
                    "--report",
                    "docs/report.json",
                    "--report",
                    ".ai/generated/inner-report.json",
                ]
            )
            first = root / "docs" / "report.json"
            second = root / ".ai" / "generated" / "inner-report.json"
            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())
            self.assertEqual(first.read_text(encoding="utf-8"), second.read_text(encoding="utf-8"))
            payload = json.loads(first.read_text(encoding="utf-8"))
            guard = payload["path_guard_compatibility"]
            self.assertTrue(guard["all_paths_accepted"])
            accepted = {entry["path"]: entry for entry in guard["paths"]}
            self.assertEqual(".ai/generated/inner-report.json", accepted[".ai/generated/inner-report.json"]["normalized_for_guard"])
            self.assertTrue(accepted[".ai/generated/inner-report.json"]["accepted"])
            self.assertEqual([], payload["unresolved_issues"])
            self.assertFalse(payload["secret_values_included"])
            self.assertEqual("attention_required", payload["status"])  # a disposable root has no .env
            self.assertEqual(1, code)

    def test_disposable_root_is_scanned_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = build_report(
                collect_facts(root, generated_at="2026-09-23T00:00:00Z", payload_sources=["docs/x.yaml#NEWAPP-001"])
            )
            self.assertIn(report["secret_scan"]["status"], {"passed", "not_scanned"})
            self.assertFalse(report["secret_values_included"])
            self.assertIn(report["git"]["repository_present"], {True, False})


if __name__ == "__main__":
    unittest.main()
