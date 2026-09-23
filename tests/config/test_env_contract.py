"""Unit tests for the NEWAPP-002 value-free environment configuration contract.

Every test uses a disposable temporary directory or reads the real repository read-only. The real
``.env`` is never opened for writing, never compared, never hashed and never printed: the fixtures
below are synthetic values assembled at runtime so this tracked test file can never trip the secret
scanner it cooperates with.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CONFIG_DIR = Path(__file__).resolve().parent
if str(CONFIG_DIR) not in sys.path:
    sys.path.insert(0, str(CONFIG_DIR))

import env_contract as contract  # noqa: E402
from env_contract import (  # noqa: E402
    DOCUMENT_RELATIVE_PATH,
    ENV_FILE,
    GROUP_ORDER,
    REPORT_RELATIVE_PATH,
    build_report,
    classify_key_name,
    collect_facts,
    configuration_key_for,
    environment_file_facts,
    find_value_free_violations,
    main,
    parse_env_text,
    policy_facts,
    read_environment_facts,
    render_artifacts,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# Synthetic fixtures, assembled at runtime so no credential-shaped literal appears in this file.
FAKE_DB_VALUE = "".join(["Synthetic", "NotAReal", "ConnectionValue", "1"])
FAKE_ID_VALUE = "".join(["Synthetic", "NotAReal", "IdValue", "2"])
FAKE_SECRET_VALUE = "".join(["Synthetic", "NotAReal", "OssValue", "3"])
FAKE_JWT_VALUE = "".join(["Synthetic", "NotAReal", "JwtValue", "4"])
FAKE_ASSIGNED_LINE = "pass" + "word" + " = " + FAKE_DB_VALUE

POLICY_DOCUMENT = {
    "project": {"name": "NEWAPP-TEST", "shares_database_and_oss_with": "NEWERP"},
    "paths": {"executor_allowed": ["docs/**", ".ai/generated/**", "tests/**", "*.md"]},
    "environment": {
        "file": ".env",
        "required_key_groups": {
            "database": ["ERP_ConnectionStrings__Default"],
            "oss": ["ERP_Oss__Endpoint", "ERP_Oss__Bucket", "ERP_Oss__AccessKeyId", "ERP_Oss__AccessKeySecret"],
            "authentication": ["ERP_Jwt__Key"],
            "ai": ["ERP_Ai__ApiKey"],
        },
    },
}


def write_text(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def env_fixture() -> str:
    return "\n".join(
        [
            "# synthetic fixture for tests",
            "",
            f"ERP_ConnectionStrings__Default={FAKE_DB_VALUE}",
            "ERP_Oss__Endpoint=oss-endpoint.example.invalid",
            "ERP_Oss__Bucket=bucket-name",
            f"ERP_Oss__AccessKeyId={FAKE_ID_VALUE}",
            f"ERP_Oss__AccessKeySecret={FAKE_SECRET_VALUE}",
            f"ERP_Jwt__Key={FAKE_JWT_VALUE}",
            "APP_LOG_LEVEL=Information",
            "ERP_Empty__Setting=",
            f"ERP_Exported__Setting={FAKE_DB_VALUE}",
            "",
        ]
    )


class ParseEnvTextTests(unittest.TestCase):
    def test_names_and_presence_booleans_only(self) -> None:
        facts = parse_env_text(env_fixture())
        self.assertIn("ERP_ConnectionStrings__Default", facts["key_names"])
        self.assertIn("ERP_Jwt__Key", facts["key_names"])
        self.assertEqual(9, facts["key_count"])
        self.assertEqual(9, facts["unique_key_count"])
        self.assertEqual(["ERP_Empty__Setting"], facts["empty_value_key_names"])
        self.assertIn("APP_LOG_LEVEL", facts["configured_key_names"])
        self.assertEqual(1, facts["comment_line_count"])
        self.assertEqual(1, facts["blank_line_count"])
        self.assertEqual(0, facts["malformed_line_count"])
        for value in (FAKE_DB_VALUE, FAKE_ID_VALUE, FAKE_SECRET_VALUE, FAKE_JWT_VALUE, "bucket-name"):
            self.assertNotIn(value, json.dumps(facts, ensure_ascii=False))

    def test_export_prefix_and_quotes_are_supported(self) -> None:
        text = "\n".join(['export ERP_App__Setting="quoted"', "ERP_Other__Setting=''", "ERP_Third__Setting=x"])
        facts = parse_env_text(text)
        self.assertEqual(["ERP_App__Setting", "ERP_Other__Setting", "ERP_Third__Setting"], facts["key_names"])
        self.assertEqual(["ERP_Other__Setting"], facts["empty_value_key_names"])

    def test_malformed_lines_are_counted_not_echoed(self) -> None:
        text = "\n".join(["ERP_Good__Name=1", "this line has no separator", "  "])
        facts = parse_env_text(text)
        self.assertEqual(1, facts["malformed_line_count"])
        self.assertEqual(["ERP_Good__Name"], facts["key_names"])
        self.assertNotIn("this line has no separator", json.dumps(facts))

    def test_duplicate_names_are_reported_by_name(self) -> None:
        facts = parse_env_text("\n".join(["ERP_Dup__Name=1", "ERP_Dup__Name=2"]))
        self.assertEqual(["ERP_Dup__Name"], facts["duplicate_key_names"])
        self.assertEqual(1, facts["unique_key_count"])


class ClassificationTests(unittest.TestCase):
    EXPECTED = {
        "database": ["ERP_ConnectionStrings__Default"],
        "oss": ["ERP_Oss__Endpoint"],
        "auth": ["ERP_Jwt__Key"],
    }

    def test_policy_group_membership_wins_over_token_rules(self) -> None:
        declared = {"application": ["ERP_Oss__Endpoint"]}
        self.assertEqual("application", classify_key_name("ERP_Oss__Endpoint", declared))

    def test_token_rules_classify_every_documented_group(self) -> None:
        cases = {
            "ERP_ConnectionStrings__Default": "database",
            "ERP_Oss__AccessKeySecret": "oss",
            "ERP_Jwt__Key": "auth",
            "AI__Deepseek__ApiKey": "ai_provider",
            "LOG_LEVEL": "application",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(expected, classify_key_name(name))

    def test_unknown_name_is_unclassified(self) -> None:
        self.assertIsNone(classify_key_name("Mystery__Thing"))
        self.assertIsNone(classify_key_name("Mystery__Thing", self.EXPECTED))

    def test_configuration_key_convention(self) -> None:
        cases = {
            "ERP_ConnectionStrings__Default": "ConnectionStrings:Default",
            "ERP_Oss__AccessKeyId": "Oss:AccessKeyId",
            "ERP_Jwt__Key": "Jwt:Key",
            "ERP_A__B__C": "A:B:C",
            "LOG_LEVEL": "LOG_LEVEL",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(expected, configuration_key_for(name))

    def test_policy_facts_reads_and_aliases_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = disposable_root(Path(temporary), policy=POLICY_DOCUMENT)
            facts = policy_facts(root)
            self.assertTrue(facts["available"])
            self.assertEqual(["ERP_ConnectionStrings__Default"], facts["expected_groups"]["database"])
            self.assertEqual(["ERP_Jwt__Key"], facts["expected_groups"]["auth"])
            self.assertEqual(["ERP_Ai__ApiKey"], facts["expected_groups"]["ai_provider"])
            self.assertIn("tests/**", facts["executor_allowed_paths"])
            self.assertEqual(["database", "oss", "auth", "ai_provider"], [g for g in GROUP_ORDER if g in facts["expected_groups"]])

    def test_unknown_policy_group_ids_are_listed_by_name(self) -> None:
        policy = json.loads(json.dumps(POLICY_DOCUMENT))
        policy["environment"]["required_key_groups"]["queue"] = ["ERP_Queue__Name"]
        with tempfile.TemporaryDirectory() as temporary:
            root = disposable_root(Path(temporary), policy=policy)
            facts = policy_facts(root)
            self.assertEqual(["queue"], facts["unknown_group_ids"])
            self.assertNotIn("queue", facts["expected_groups"])

    def test_absent_policy_is_not_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            facts = policy_facts(Path(temporary))
            self.assertFalse(facts["available"])
            self.assertEqual({}, facts["expected_groups"])


def disposable_root(root: Path, *, env_text: str | None = None, policy: dict | None = None) -> Path:
    write_text(root, ".gitignore", ".env\n")
    if env_text is not None:
        write_text(root, ENV_FILE, env_text)
    if policy is not None:
        write_text(root, ".ai/agent_config.yaml", json.dumps(policy, indent=2) + "\n")
    return root


def init_repository(root: Path) -> None:
    """Create a disposable Git repository so the ignore/tracked checks are exercised for real."""
    run = lambda *args: subprocess.run(  # noqa: E731
        ["git", *args], cwd=str(root), capture_output=True, text=True, shell=False, check=True
    )
    run("init", "-q")
    run("config", "user.email", "config-contract@example.invalid")
    run("config", "user.name", "NEWAPP config contract test")


class ReportBuildingTests(unittest.TestCase):
    def _collect(self, root: Path) -> dict:
        return collect_facts(
            root,
            generated_at="2026-09-23T00:00:00Z",
            policy_relative=".ai/agent_config.yaml",
            payload_sources=["docs/NEWAPP_TASKS_V1.yaml#NEWAPP-002"],
            executor_paths=["docs/CONFIGURATION_CONTRACT.md", "tests/config/env_contract.py"],
            report_paths=[REPORT_RELATIVE_PATH],
            document_paths=[DOCUMENT_RELATIVE_PATH],
        )

    def test_missing_and_unclassified_names_are_reported(self) -> None:
        policy = json.loads(json.dumps(POLICY_DOCUMENT))
        policy["environment"]["required_key_groups"]["ai"] = ["ERP_Ai__ApiKey", "ERP_Ai__Model"]
        with tempfile.TemporaryDirectory() as temporary:
            root = disposable_root(Path(temporary), env_text=env_fixture(), policy=policy)
            report = build_report(self._collect(root))
            self.assertEqual(["ERP_Ai__ApiKey", "ERP_Ai__Model"], report["missing_key_names"])
            groups = {group["id"]: group for group in report["groups"]}
            self.assertEqual(0, groups["ai_provider"]["present_count"])
            self.assertEqual(2, groups["ai_provider"]["expected_count"])
            self.assertEqual(9, report["key_inventory"]["unique_key_count"])
            self.assertEqual(
                {"database", "oss", "auth", "application"},
                {entry["group"] for entry in report["binding_map"]},
            )
            self.assertNotIn("Mystery__Thing", json.dumps(report))

    def test_unclassified_names_stay_out_of_the_application_group(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = disposable_root(Path(temporary), env_text=env_fixture() + "Mystery__Thing=1\n")
            report = build_report(self._collect(root))
            self.assertEqual(["Mystery__Thing"], report["unclassified_key_names"])
            groups = {group["id"]: group for group in report["groups"]}
            self.assertNotIn("Mystery__Thing", groups["application"]["present_names"])
            entry = next(item for item in report["binding_map"] if item["env_name"] == "Mystery__Thing")
            self.assertEqual("unclassified", entry["group"])
            self.assertFalse(entry["value_fields_recorded"])
            self.assertEqual("attention_required", report["status"])  # no Git repository in the fixture root

    def test_report_is_value_free_and_evidence_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = disposable_root(Path(temporary), env_text=env_fixture(), policy=POLICY_DOCUMENT)
            report = build_report(self._collect(root))
            text = json.dumps(report, ensure_ascii=False)
            for value in (FAKE_DB_VALUE, FAKE_ID_VALUE, FAKE_SECRET_VALUE, FAKE_JWT_VALUE):
                self.assertNotIn(value, text)
            self.assertFalse(report["secret_values_included"])
            self.assertFalse(report["read_only_guard"]["values_recorded"])
            self.assertFalse(report["read_only_guard"]["values_hashed"])
            self.assertTrue(report["read_only_guard"]["read_only_collection"])
            self.assertEqual(4, len(report["acceptance_evidence"]))
            self.assertIn("GPT", report["completion_authority"])
            self.assertEqual([], report["unresolved_issues"])
            self.assertTrue(report["path_guard_compatibility"]["all_paths_accepted"])

    def test_acceptance_evidence_reacts_to_a_missing_environment_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = disposable_root(Path(temporary), policy=POLICY_DOCUMENT)
            report = build_report(self._collect(root))
            self.assertEqual("attention_required", report["status"])
            criteria = {item["criterion"]: item["satisfied"] for item in report["acceptance_evidence"]}
            self.assertFalse(criteria[".env remains present locally and untracked."])
            self.assertTrue(criteria["Every parsed key name is grouped or listed by name only."])



class ReadOnlyGuardTests(unittest.TestCase):
    def test_collection_is_read_only_and_value_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = disposable_root(Path(temporary), env_text=env_fixture())
            before = (root / ENV_FILE).stat()
            facts = read_environment_facts(root)
            after = (root / ENV_FILE).stat()
            self.assertTrue(facts["present"])
            self.assertTrue(facts["read_only_collection"])
            self.assertTrue(facts["file_unchanged_after_read"])
            self.assertEqual((before.st_size, before.st_mtime_ns), (after.st_size, after.st_mtime_ns))
            self.assertEqual(9, facts["parsing"]["unique_key_count"])
            self.assertFalse(facts["values_recorded"])
            self.assertFalse(facts["values_hashed"])
            self.assertFalse(facts["assignment_lines_reproduced"])
            text = json.dumps(facts, ensure_ascii=False)
            for value in (FAKE_DB_VALUE, FAKE_ID_VALUE, FAKE_SECRET_VALUE, FAKE_JWT_VALUE):
                self.assertNotIn(value, text)

    def test_absent_environment_file_is_reported_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            facts = read_environment_facts(Path(temporary))
            self.assertFalse(facts["present"])
            self.assertEqual(0, facts["parsing"]["unique_key_count"])
            self.assertTrue(facts["read_only_collection"])

    def test_git_facts_expose_labels_and_booleans_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = disposable_root(Path(temporary), env_text=env_fixture())
            facts = environment_file_facts(root)
            self.assertEqual({"path_label", "exists_locally", "ignored_by_git", "tracked_by_git"}, set(facts))
            self.assertEqual(ENV_FILE, facts["path_label"])
            self.assertTrue(facts["exists_locally"])


class ValueFreeCheckTests(unittest.TestCase):
    KEY = "ERP_Jwt__Key"

    def test_key_name_assignment_is_detected_by_line_number(self) -> None:
        findings = find_value_free_violations("\n".join(["# note", f"{self.KEY}={FAKE_JWT_VALUE}"]), [self.KEY], "doc.md")
        self.assertEqual([{"rule": "key_name_assignment", "artifact": "doc.md", "line": 2}], findings)
        self.assertNotIn(FAKE_JWT_VALUE, json.dumps(findings))

    def test_exported_assignment_is_detected(self) -> None:
        findings = find_value_free_violations(f"export {self.KEY}={FAKE_JWT_VALUE}", [self.KEY], "doc.md")
        self.assertEqual(["key_name_assignment"], [item["rule"] for item in findings])

    def test_credential_keyword_assignment_is_detected(self) -> None:
        findings = find_value_free_violations(FAKE_ASSIGNED_LINE, ["ERP_Other__Name"], "doc.md")
        self.assertEqual([{"rule": "keyword_assignment", "artifact": "doc.md", "line": 1}], findings)
        self.assertNotIn(FAKE_DB_VALUE, json.dumps(findings))

    def test_placeholder_values_are_not_reported(self) -> None:
        text = "\n".join(["password: string", "api_key = ${API_KEY}", "secret: <placeholder>"])
        self.assertEqual([], find_value_free_violations(text, [], "doc.md"))

    def test_rendered_report_and_document_are_clean(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = disposable_root(Path(temporary), env_text=env_fixture(), policy=POLICY_DOCUMENT)
            facts = collect_facts(
                root,
                generated_at="2026-09-23T00:00:00Z",
                report_paths=[REPORT_RELATIVE_PATH],
                document_paths=[DOCUMENT_RELATIVE_PATH],
                executor_paths=[DOCUMENT_RELATIVE_PATH],
            )
            report = build_report(facts)
            names = report["key_inventory"]["key_names"]
            json_text, document_text, violations = render_artifacts(
                report, names, REPORT_RELATIVE_PATH, DOCUMENT_RELATIVE_PATH
            )
            self.assertEqual([], violations)
            self.assertIn("## 3. Key groups", document_text)
            for name in names:
                self.assertIn(f"`{name}`", document_text)
                self.assertIn(name, json_text)
            for value in (FAKE_DB_VALUE, FAKE_ID_VALUE, FAKE_SECRET_VALUE, FAKE_JWT_VALUE):
                self.assertNotIn(value, json_text)
                self.assertNotIn(value, document_text)



@unittest.skipUnless(shutil.which("git"), "git is required for the disposable repository test")
class WriteArtifactTests(unittest.TestCase):
    def prepare(self, root: Path) -> None:
        disposable_root(root, env_text=env_fixture(), policy=POLICY_DOCUMENT)
        init_repository(root)

    def test_write_creates_value_free_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.prepare(root)
            env_path = root / ENV_FILE
            before = env_path.stat()
            code = main(["--root", str(root), "--write", "--executor-file", DOCUMENT_RELATIVE_PATH])
            after = env_path.stat()
            self.assertEqual(0, code)
            self.assertEqual((before.st_size, before.st_mtime_ns), (after.st_size, after.st_mtime_ns))
            report_path = root / REPORT_RELATIVE_PATH
            document_path = root / DOCUMENT_RELATIVE_PATH
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual("evidence_collected", report["status"])
            self.assertEqual("passed", report["value_free_check"]["status"])
            self.assertEqual(0, report["value_free_check"]["violations_count"])
            self.assertFalse(report["secret_values_included"])
            self.assertIn("ERP_Oss__AccessKeySecret", report["key_inventory"]["key_names"])
            self.assertEqual([], report["unresolved_issues"])
            artifacts = report_path.read_text(encoding="utf-8") + document_path.read_text(encoding="utf-8")
            for value in (FAKE_DB_VALUE, FAKE_ID_VALUE, FAKE_SECRET_VALUE, FAKE_JWT_VALUE):
                self.assertNotIn(value, artifacts)
            self.assertEqual(
                [],
                find_value_free_violations(artifacts, report["key_inventory"]["key_names"], "artifacts"),
            )
            self.assertEqual([], list(report_path.parent.glob("*.tmp")))
            self.assertEqual([], list(document_path.parent.glob("*.tmp")))

    def test_write_without_the_flag_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.prepare(root)
            code = main(["--root", str(root)])
            self.assertEqual(0, code)
            self.assertFalse((root / REPORT_RELATIVE_PATH).exists())
            self.assertFalse((root / DOCUMENT_RELATIVE_PATH).exists())

    def test_missing_names_are_reported_in_both_artifacts(self) -> None:
        policy = json.loads(json.dumps(POLICY_DOCUMENT))
        policy["environment"]["required_key_groups"]["ai"] = ["ERP_Ai__ApiKey"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            disposable_root(root, env_text=env_fixture(), policy=policy)
            init_repository(root)
            code = main(["--root", str(root), "--write"])
            self.assertEqual(0, code)
            report = json.loads((root / REPORT_RELATIVE_PATH).read_text(encoding="utf-8"))
            self.assertEqual(["ERP_Ai__ApiKey"], report["missing_key_names"])
            self.assertEqual(0, report["key_inventory"]["malformed_line_count"])
            document = (root / DOCUMENT_RELATIVE_PATH).read_text(encoding="utf-8")
            self.assertIn("Missing names: `ERP_Ai__ApiKey`", document)
            self.assertIn("Missing from this group: `ERP_Ai__ApiKey`", document)

    def test_value_leak_stops_the_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.prepare(root)
            poisoned = "ERP_Jwt__Key" + "=" + FAKE_JWT_VALUE + "\n"
            with mock.patch.object(contract, "render_markdown", return_value=poisoned):
                code = main(["--root", str(root), "--write"])
            self.assertEqual(1, code)
            self.assertFalse((root / REPORT_RELATIVE_PATH).exists())
            self.assertFalse((root / DOCUMENT_RELATIVE_PATH).exists())



class RealRepositoryTests(unittest.TestCase):
    def test_policy_expectations_come_from_the_controller_configuration(self) -> None:
        facts = policy_facts(REPOSITORY_ROOT)
        self.assertTrue(facts["available"])
        self.assertIn("ERP_ConnectionStrings__Default", facts["expected_groups"].get("database", []))
        self.assertIn("ERP_Jwt__Key", facts["expected_groups"].get("auth", []))
        self.assertIn("tests/**", facts["executor_allowed_paths"])
        self.assertEqual([], facts["unknown_group_ids"])

    @unittest.skipUnless((REPOSITORY_ROOT / ENV_FILE).is_file(), "the local environment file is absent")
    def test_real_environment_file_is_described_read_only(self) -> None:
        env_path = REPOSITORY_ROOT / ENV_FILE
        before = env_path.stat()
        facts = read_environment_facts(REPOSITORY_ROOT)
        after = env_path.stat()
        self.assertTrue(facts["present"])
        self.assertTrue(facts["read_only_collection"])
        self.assertTrue(facts["file_unchanged_after_read"])
        self.assertTrue(facts["git_status_unchanged"])
        self.assertEqual((before.st_size, before.st_mtime_ns), (after.st_size, after.st_mtime_ns))
        self.assertEqual(0, facts["parsing"]["malformed_line_count"])
        self.assertGreaterEqual(facts["parsing"]["unique_key_count"], 1)
        self.assertFalse(facts["values_recorded"])
        git_facts = environment_file_facts(REPOSITORY_ROOT)
        self.assertTrue(git_facts["ignored_by_git"])
        self.assertFalse(git_facts["tracked_by_git"])

    @unittest.skipUnless(
        (REPOSITORY_ROOT / REPORT_RELATIVE_PATH).is_file(),
        "the NEWAPP-002 report has not been generated yet",
    )
    def test_committed_artifacts_are_value_free_and_state_the_binding(self) -> None:
        report_path = REPOSITORY_ROOT / REPORT_RELATIVE_PATH
        document_path = REPOSITORY_ROOT / DOCUMENT_RELATIVE_PATH
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual("NEWAPP-002", report["task_id"])
        self.assertFalse(report["secret_values_included"])
        self.assertFalse(report["read_only_guard"]["values_recorded"])
        self.assertFalse(report["read_only_guard"]["values_hashed"])
        self.assertEqual("passed", report["value_free_check"]["status"])
        names = report["key_inventory"]["key_names"]
        artifacts = {
            "report": report_path.read_text(encoding="utf-8"),
            "document": document_path.read_text(encoding="utf-8"),
        }
        for label, text in artifacts.items():
            with self.subTest(artifact=label):
                self.assertEqual([], find_value_free_violations(text, names, label))
        document = artifacts["document"]
        self.assertIn("share one SQL Server database", document)
        self.assertIn("No NEWAPP/NEWERP synchronization service", document)
        self.assertIn("connects directly to SQL Server", document)
        self.assertIn("ConfigMapping layer", document)
        for name in names:
            self.assertIn(f"`{name}`", document)
        self.assertNotIn(FAKE_DB_VALUE, document)


if __name__ == "__main__":
    unittest.main()

