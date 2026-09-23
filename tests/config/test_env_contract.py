"""Unit tests for the NEWAPP-002 local configuration contract utilities.

Every test uses disposable temporary directories, except the read-only checks that inspect the real
checkout (key names in ``.env``, the controller required-key groups and the committed artifacts). No
test writes into the repository, touches a database, OSS, an AI provider or the network, and no test
records, prints, compares or hashes a value.

Synthetic fixtures use placeholder-shaped right-hand sides, so this tracked test file can never trip
the scanner it collaborates with.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parent
if str(CONFIG_DIR) not in sys.path:
    sys.path.insert(0, str(CONFIG_DIR))

from env_contract import (  # noqa: E402
    BASE_GROUPS,
    BINDING_TEMPLATES,
    DOC_RELATIVE_PATH,
    ENV_FILE,
    GROUP_ORDER,
    GROUP_TOKENS,
    NAME_PATTERN,
    PLATFORM_BINDING_RULES,
    REPORT_RELATIVE_PATH,
    SCANNER_RELATIVE_PATH,
    TASK_ID,
    analyse_env_file,
    binding_map,
    build_report,
    classify_name,
    collect_facts,
    finalize_report,
    main,
    normalize_for_path_guard,
    path_guard_compatibility,
    read_env_declarations,
    regeneration_command,
    render_json,
    render_markdown,
    scanner_module,
    scanner_self_check,
    value_leak_guard,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPOSITORY_ROOT / REPORT_RELATIVE_PATH
DOC_PATH = REPOSITORY_ROOT / DOC_RELATIVE_PATH
CONTROLLER_COMMON = REPOSITORY_ROOT / ".ai" / "controller" / "common.py"

# Mirror of the controller policy in .ai/agent_config.yaml (paths.executor_allowed / paths.protected).
# The tests compare the module path guard against these patterns; the controller file itself is only
# ever read, never written, by the executor.
CONTROLLER_ALLOWED_PATTERNS = (
    "src/**",
    "tests/**",
    "docs/**",
    "database/**",
    ".github/**",
    ".ai/generated/**",
    "*.sln",
    "*.md",
    ".gitignore",
)
CONTROLLER_PROTECTED_PATTERNS = (
    ".env",
    ".env.*",
    "agent.env",
    "agent.env.*",
    ".ai/controller/**",
    ".ai/agent_config.yaml",
    ".ai/project_state.json",
    ".ai/decisions/**",
    ".ai/brain/**",
    ".ai/locks/**",
    ".github/workflows/**",
    ".clinerules",
    "start_agent.bat",
    "**/*.pfx",
    "**/*.p12",
    "**/*.jks",
    "**/*.keystore",
    "**/*.pem",
    "**/*.key",
)
EXECUTOR_PATHS = (
    REPORT_RELATIVE_PATH,
    DOC_RELATIVE_PATH,
    "tests/config/__init__.py",
    "tests/config/env_contract.py",
    "tests/config/test_env_contract.py",
)

# Placeholder-shaped synthetic values. No real credential value is used or needed by these tests.
CONNECTION_VALUE = "example-connection"
ENDPOINT_VALUE = "example-endpoint"
BUCKET_VALUE = "example-bucket"
IDENTIFIER_VALUE = "example-identifier"
MATERIAL_VALUE = "example-material"
SIGNING_VALUE = "example-signing"
FLAG_VALUE = "example-flag"
SETTING_VALUE = "example-setting"
SYNTHETIC_VALUES = (
    CONNECTION_VALUE,
    ENDPOINT_VALUE,
    BUCKET_VALUE,
    IDENTIFIER_VALUE,
    MATERIAL_VALUE,
    SIGNING_VALUE,
    FLAG_VALUE,
    SETTING_VALUE,
)

SYNTHETIC_ENV = "\n".join(
    [
        "# synthetic declaration fixture for NEWAPP-002 tests",
        "",
        f'export ERP_ConnectionStrings__Default="{CONNECTION_VALUE}"',
        f"ERP_Oss__Endpoint={ENDPOINT_VALUE}",
        f"ERP_Oss__Bucket={BUCKET_VALUE}",
        f"ERP_Oss__AccessKeyId={IDENTIFIER_VALUE}",
        f"ERP_Oss__AccessKeySecret={MATERIAL_VALUE}",
        f"ERP_Jwt__Key='{SIGNING_VALUE}'",
        f"NEWAPP_Feature_Flag={FLAG_VALUE}",
        f"UNPREFIXED_SETTING={SETTING_VALUE}",
        "EMPTY_SETTING=",
        "  MALFORMED LINE  ",
        f"ERP_Oss__Bucket={BUCKET_VALUE}",
    ]
) + "\n"

REQUIRED_KEY_GROUPS = {
    "database": ["ERP_ConnectionStrings__Default"],
    "oss": [
        "ERP_Oss__Endpoint",
        "ERP_Oss__Bucket",
        "ERP_Oss__AccessKeyId",
        "ERP_Oss__AccessKeySecret",
    ],
    "auth": ["ERP_Jwt__Key"],
}

REQUIRED_DOC_STATEMENTS = (
    "share one SQL Server database",
    "No NEWAPP/NEWERP data synchronisation service",
    "never connects to SQL Server",
    "never embeds OSS credentials",
    "behind the NEWAPP server API",
    REPORT_RELATIVE_PATH,
)


def write_text(root: Path, relative: str, text: str, *, newline: str = "\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline=newline)
    return path


def populate_root(
    root: Path,
    *,
    env_text: str | None = SYNTHETIC_ENV,
    groups: Any = REQUIRED_KEY_GROUPS,
    allowed: Any = None,
    protected: Any = None,
) -> Path:
    """Fill a disposable root with a synthetic environment file and a controller configuration."""
    if env_text is not None:
        write_text(root, ENV_FILE, env_text)
    configuration: dict[str, Any] = {}
    if groups is not None:
        configuration["environment"] = {"required_key_groups": groups}
    paths: dict[str, Any] = {}
    if allowed is not None:
        paths["executor_allowed"] = list(allowed)
    if protected is not None:
        paths["protected"] = list(protected)
    if paths:
        configuration["paths"] = paths
    if configuration:
        write_text(root, ".ai/agent_config.yaml", json.dumps(configuration))
    return root


def policy_root(temporary: str, **overrides: Any) -> Path:
    """Build a disposable root that also carries the mirrored controller path policy."""
    return populate_root(
        Path(temporary),
        allowed=CONTROLLER_ALLOWED_PATTERNS,
        protected=CONTROLLER_PROTECTED_PATTERNS,
        **overrides,
    )


class NameClassificationTests(unittest.TestCase):
    def test_local_names_are_classified_by_service(self) -> None:
        expected = {
            "ERP_ConnectionStrings__Default": "database",
            "ERP_Oss__Endpoint": "oss",
            "ERP_Oss__Bucket": "oss",
            "ERP_Oss__AccessKeyId": "oss",
            "ERP_Oss__AccessKeySecret": "oss",
            "ERP_Jwt__Key": "auth",
        }
        for name, group in expected.items():
            with self.subTest(name=name):
                self.assertEqual(group, classify_name(name)["group"])

    def test_ai_provider_names_are_recognised(self) -> None:
        for name in ("OpenAI_ApiKey", "DEEPSEEK__ApiKey", "ANTHROPIC_API_KEY", "LLM_Model"):
            with self.subTest(name=name):
                self.assertEqual("ai_provider", classify_name(name)["group"])

    def test_application_prefix_and_unknown_names(self) -> None:
        self.assertEqual("application", classify_name("NEWAPP_Feature_Flag")["group"])
        self.assertEqual("application", classify_name("ERP_Something_Else")["group"])
        self.assertEqual("unknown", classify_name("MYSTERY_SETTING")["group"])

    def test_precedence_uses_the_first_matching_service(self) -> None:
        result = classify_name("ERP_Oss__Jwt__Key")
        self.assertEqual("oss", result["group"])
        self.assertEqual(["oss", "auth"], result["matched_groups"])
        self.assertEqual(["oss"], result["matched_tokens"])

    def test_every_name_maps_to_a_known_group(self) -> None:
        for name in ("", "x", "A_B", "NEWAPP_X", "999", *REQUIRED_KEY_GROUPS["oss"]):
            with self.subTest(name=name):
                self.assertIn(classify_name(name)["group"], GROUP_ORDER)

    def test_group_tokens_are_lowercase_alphanumeric(self) -> None:
        for group in BASE_GROUPS:
            for token in GROUP_TOKENS[group]:
                with self.subTest(group=group, token=token):
                    self.assertRegex(token, r"^[a-z0-9]+$")


class EnvParsingTests(unittest.TestCase):
    def test_declarations_shapes_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = populate_root(Path(temporary), groups=None)
            facts = analyse_env_file(root / ENV_FILE)
            self.assertTrue(facts["exists"])
            self.assertEqual(13, facts["line_count"])
            self.assertEqual(10, facts["declaration_count"])
            self.assertEqual(1, facts["comment_line_count"])
            self.assertEqual(1, facts["blank_line_count"])
            self.assertEqual([12], facts["malformed_line_numbers"])
            self.assertEqual(["ERP_Oss__Bucket"], facts["duplicate_names"])
            self.assertEqual(["EMPTY_SETTING"], facts["empty_value_names"])
            self.assertEqual(2, facts["quoted_value_count"])
            self.assertEqual(
                ["ERP_ConnectionStrings__Default"], facts["export_prefixed_names"]
            )
            self.assertEqual(
                [
                    "ERP_ConnectionStrings__Default",
                    "ERP_Oss__Endpoint",
                    "ERP_Oss__Bucket",
                    "ERP_Oss__AccessKeyId",
                    "ERP_Oss__AccessKeySecret",
                    "ERP_Jwt__Key",
                    "NEWAPP_Feature_Flag",
                    "UNPREFIXED_SETTING",
                    "EMPTY_SETTING",
                    "ERP_Oss__Bucket",
                ],
                facts["names"],
            )

    def test_category_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = populate_root(Path(temporary), groups=None)
            groups = analyse_env_file(root / ENV_FILE)["groups"]
            self.assertEqual(1, groups["database"]["count"])
            self.assertEqual(5, groups["oss"]["count"])
            self.assertEqual(1, groups["auth"]["count"])
            self.assertEqual(0, groups["ai_provider"]["count"])
            self.assertEqual(1, groups["application"]["count"])
            self.assertEqual(2, groups["unknown"]["count"])

    def test_no_value_text_reaches_the_collected_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = populate_root(Path(temporary), groups=None)
            facts = analyse_env_file(root / ENV_FILE)
            serialized = json.dumps(facts, ensure_ascii=False)
            for value in SYNTHETIC_VALUES:
                with self.subTest(value=value):
                    self.assertNotIn(value, serialized)
            self.assertFalse(facts["values_recorded"])
            guard = value_leak_guard(serialized, facts["names"], "facts")
            self.assertEqual("passed", guard["status"])
            self.assertEqual([], guard["delimiter_after_name_line_numbers"])
            for name in facts["names"]:
                self.assertRegex(name, NAME_PATTERN)

    def test_parsing_leaves_the_environment_file_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = populate_root(Path(temporary), groups=None)
            path = root / ENV_FILE
            before_bytes = path.read_bytes()
            before_mtime = path.stat().st_mtime_ns
            facts = analyse_env_file(path)
            self.assertEqual(before_bytes, path.read_bytes())
            self.assertEqual(before_mtime, path.stat().st_mtime_ns)
            self.assertTrue(facts["modified_time_unchanged_during_run"])
            self.assertEqual(len(before_bytes), facts["byte_count"])

    def test_absent_environment_file_is_reported_without_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            facts = analyse_env_file(Path(temporary) / ENV_FILE)
            self.assertFalse(facts["exists"])
            self.assertEqual(0, facts["declaration_count"])
            self.assertEqual([], facts["names"])
            self.assertTrue(facts["modified_time_unchanged_during_run"])

    def test_bom_and_crlf_declarations_are_tolerated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ENV_FILE
            text = f"ALPHA_SETTING={SETTING_VALUE}\r\nBETA_SETTING=\r\n"
            path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
            facts = analyse_env_file(path)
            self.assertEqual(["ALPHA_SETTING", "BETA_SETTING"], facts["names"])
            self.assertEqual(["BETA_SETTING"], facts["empty_value_names"])


class RequiredKeyContractTests(unittest.TestCase):
    def test_all_required_names_present_and_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = populate_root(Path(temporary))
            contract = collect_facts(root, generated_at="2026-09-23T00:00:00Z")["required_keys"]
            self.assertTrue(contract["available"])
            self.assertEqual(6, contract["required_key_count"])
            self.assertEqual(6, contract["present_key_count"])
            self.assertEqual(0, contract["missing_key_count"])
            self.assertEqual(0, contract["unconfigured_key_count"])
            self.assertTrue(contract["all_required_keys_present"])
            for group, facts in contract["groups"].items():
                with self.subTest(group=group):
                    self.assertTrue(facts["all_present"])

    def test_missing_and_empty_names_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = populate_root(
                Path(temporary),
                groups={
                    "database": ["ERP_ConnectionStrings__Default", "ABSENT_SETTING"],
                    "oss": ["ERP_Oss__Endpoint"],
                },
                env_text=(
                    f"ERP_ConnectionStrings__Default={CONNECTION_VALUE}\n"
                    "ERP_Oss__Endpoint=\n"
                ),
            )
            contract = collect_facts(root, generated_at="2026-09-23T00:00:00Z")["required_keys"]
            self.assertEqual(
                ["ABSENT_SETTING"], contract["groups"]["database"]["missing"]
            )
            self.assertEqual(
                ["ERP_Oss__Endpoint"], contract["groups"]["oss"]["unconfigured"]
            )
            self.assertEqual(1, contract["missing_key_count"])
            self.assertEqual(1, contract["unconfigured_key_count"])
            self.assertFalse(contract["groups"]["oss"]["all_present"])
            self.assertFalse(contract["all_required_keys_present"])

    def test_absent_controller_configuration_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = populate_root(Path(temporary), groups=None)
            contract = collect_facts(root, generated_at="2026-09-23T00:00:00Z")["required_keys"]
            self.assertFalse(contract["available"])
            self.assertFalse(contract["all_required_keys_present"])
            self.assertEqual({}, contract["groups"])

    def test_malformed_controller_configuration_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_text(root, ".ai/agent_config.yaml", "{ not json")
            contract = collect_facts(root, generated_at="2026-09-23T00:00:00Z")["required_keys"]
            self.assertFalse(contract["available"])
            self.assertFalse(contract["all_required_keys_present"])


class BindingMapTests(unittest.TestCase):
    def test_binding_map_covers_every_template(self) -> None:
        names = [template["name"] for template in BINDING_TEMPLATES]
        contract = {"groups": {"oss": {"required": ["ERP_Oss__Endpoint"]}}}
        mapping = binding_map(names, contract)
        self.assertTrue(all(entry["present_locally"] for entry in mapping["entries"]))
        self.assertTrue(all(entry["client_exposure"] == "forbidden" for entry in mapping["entries"]))
        self.assertEqual([], mapping["unmapped_names"])
        self.assertEqual([], mapping["missing_bound_names"])
        self.assertEqual(list(PLATFORM_BINDING_RULES), mapping["platform_rules"])
        self.assertEqual(0, mapping["unmapped_count"])
        self.assertEqual(0, mapping["missing_bound_count"])

    def test_unmapped_and_missing_bound_names_are_listed(self) -> None:
        mapping = binding_map(
            ["NEWAPP_EXTRA_SETTING"], {"groups": {"oss": {"required": ["ERP_Oss__Endpoint"]}}}
        )
        self.assertEqual(["NEWAPP_EXTRA_SETTING"], mapping["unmapped_names"])
        self.assertEqual(["ERP_Oss__Endpoint"], mapping["missing_bound_names"])
        self.assertEqual(1, mapping["unmapped_count"])
        self.assertEqual(1, mapping["missing_bound_count"])


class ValueGuardTests(unittest.TestCase):
    """The value guard is the check that keeps the published artifacts free of values."""

    def test_assignment_line_is_flagged_without_returning_the_value(self) -> None:
        line = f"ERP_Oss__AccessKeySecret = {MATERIAL_VALUE}"
        guard = value_leak_guard(line + "\n", ["ERP_Oss__AccessKeySecret"], REPORT_RELATIVE_PATH)
        self.assertEqual("failed", guard["status"])
        self.assertEqual([1], guard["delimiter_after_name_line_numbers"])
        self.assertNotIn(MATERIAL_VALUE, json.dumps(guard, ensure_ascii=False))
        self.assertFalse(guard["values_recorded"])

    def test_colon_delimiter_after_a_name_is_flagged(self) -> None:
        guard = value_leak_guard(
            "ERP_Oss__Endpoint: " + ENDPOINT_VALUE + "\n", ["ERP_Oss__Endpoint"], DOC_RELATIVE_PATH
        )
        self.assertEqual("failed", guard["status"])
        self.assertEqual([1], guard["delimiter_after_name_line_numbers"])
        self.assertNotIn(ENDPOINT_VALUE, json.dumps(guard, ensure_ascii=False))

    def test_any_assignment_character_is_flagged(self) -> None:
        clean = value_leak_guard("counts only, no delimiters\n", ["ALPHA_SETTING"], "clean.md")
        self.assertEqual("passed", clean["status"])
        self.assertEqual(0, clean["equal_sign_count"])
        leaky = value_leak_guard("total " + "=" + " 3\n", ["ALPHA_SETTING"], "leaky.md")
        self.assertEqual("failed", leaky["status"])
        self.assertEqual(1, leaky["equal_sign_count"])

    def test_invalid_key_name_is_flagged(self) -> None:
        guard = value_leak_guard("plain text\n", ["NOT-A-NAME"], REPORT_RELATIVE_PATH)
        self.assertEqual("failed", guard["status"])
        self.assertEqual(["NOT-A-NAME"], guard["non_name_character_key_names"])

    def test_declared_name_inside_a_table_cell_passes(self) -> None:
        text = "\n".join(["| `ERP_Oss__Endpoint` | oss | yes |", ""])
        guard = value_leak_guard(text, ["ERP_Oss__Endpoint"], DOC_RELATIVE_PATH)
        self.assertEqual("passed", guard["status"])
        self.assertEqual([], guard["delimiter_after_name_line_numbers"])


def render_artifacts(root: Path) -> tuple[dict[str, Any], str, str]:
    """Collect facts, build the report and render both artifacts for one root."""
    facts = collect_facts(
        root,
        generated_at="2026-09-23T00:00:00Z",
        executor_paths=EXECUTOR_PATHS,
        report_paths=[REPORT_RELATIVE_PATH],
        doc_paths=[DOC_RELATIVE_PATH],
    )
    return finalize_report(build_report(facts), facts["environment"]["names"])


class ArtifactRenderingTests(unittest.TestCase):
    """The rendered report and document are the evidence, so both must be value free."""

    def render(self, root: Path) -> tuple[dict[str, Any], str, str]:
        return render_artifacts(root)

    def test_rendered_artifacts_contain_no_values_or_assignment_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report, report_text, markdown = self.render(policy_root(temporary))
            self.assertEqual("evidence_collected", report["status"])
            self.assertEqual("passed", report["report_value_guard"]["status"])
            self.assertEqual("passed", report["documentation_value_guard"]["status"])
            for text, label in ((report_text, REPORT_RELATIVE_PATH), (markdown, DOC_RELATIVE_PATH)):
                with self.subTest(artifact=label):
                    self.assertNotIn("=", text)
                    for value in SYNTHETIC_VALUES:
                        self.assertNotIn(value, text)
                    for name in report["environment"]["names"]:
                        self.assertNotIn(name + "=", text)

    def test_repository_scanner_passes_over_both_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report, _, _ = self.render(policy_root(temporary))
            scan = report["scanner_self_check"]
            self.assertTrue(scan["available"])
            self.assertEqual(SCANNER_RELATIVE_PATH, scan["scanner"])
            self.assertEqual("passed", scan["status"])
            self.assertEqual([], scan["findings"])
            self.assertEqual(
                sorted([DOC_RELATIVE_PATH, REPORT_RELATIVE_PATH]), sorted(scan["checked_paths"])
            )
            self.assertFalse(scan["values_recorded"])

    def test_rendering_is_deterministic_for_identical_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = policy_root(temporary)
            _, first_text, first_doc = self.render(root)
            _, second_text, second_doc = self.render(root)
            self.assertEqual(first_text, second_text)
            self.assertEqual(first_doc, second_doc)

    def test_document_states_the_required_key_report_and_platform_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, _, markdown = self.render(policy_root(temporary))
            for statement in REQUIRED_DOC_STATEMENTS:
                with self.subTest(statement=statement):
                    self.assertIn(statement, markdown)
            for rule in PLATFORM_BINDING_RULES:
                with self.subTest(rule=rule[:40]):
                    self.assertIn(rule, markdown)
            self.assertIn("## 6. Required key groups and missing-key report", markdown)
            self.assertIn("python tests/config/env_contract.py --write", markdown)

    def test_path_guard_accepts_every_recorded_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report, _, markdown = self.render(policy_root(temporary))
            guard = report["path_guard"]
            self.assertTrue(guard["all_paths_accepted"])
            self.assertEqual([], guard["protected_paths_touched"])
            self.assertTrue(guard["no_protected_path_touched"])
            self.assertEqual(list(CONTROLLER_ALLOWED_PATTERNS), guard["allowed_patterns"])
            accepted = {entry["path"]: entry for entry in guard["paths"]}
            self.assertEqual(sorted(EXECUTOR_PATHS), sorted(accepted))
            for path in EXECUTOR_PATHS:
                with self.subTest(path=path):
                    self.assertTrue(accepted[path]["accepted"])
            self.assertIn("Every recorded executor path accepted: yes.", markdown)

    def test_protected_path_is_reported_and_blocks_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = policy_root(temporary)
            facts = collect_facts(
                root,
                generated_at="2026-09-23T00:00:00Z",
                executor_paths=[*EXECUTOR_PATHS, ".env"],
            )
            report, _, markdown = finalize_report(build_report(facts), facts["environment"]["names"])
            guard = report["path_guard"]
            self.assertFalse(guard["all_paths_accepted"])
            self.assertEqual([".env"], [entry["path"] for entry in guard["protected_paths_touched"]])
            self.assertFalse(guard["no_protected_path_touched"])
            self.assertEqual("attention_required", report["status"])
            self.assertFalse(report["acceptance_evidence"][-1]["satisfied"])
            self.assertIn("Protected paths touched: .env.", markdown)


class RegenerationCommandTests(unittest.TestCase):
    def test_command_lists_the_recorded_paths_without_assignment_characters(self) -> None:
        report = {
            "artifacts": {
                "report_paths": [REPORT_RELATIVE_PATH],
                "doc_paths": [DOC_RELATIVE_PATH],
                "executor_paths": [*EXECUTOR_PATHS, REPORT_RELATIVE_PATH],
            }
        }
        command = regeneration_command(report)
        self.assertIn("python tests/config/env_contract.py --write", command)
        self.assertIn("--report " + REPORT_RELATIVE_PATH, command)
        self.assertIn("--markdown " + DOC_RELATIVE_PATH, command)
        self.assertIn("--executor-file tests/config/env_contract.py", command)
        self.assertEqual(1, command.count("--report"))
        self.assertEqual(1, command.count("--markdown"))
        self.assertNotIn("=", command)

    def test_mirror_normalization_keeps_dot_directories_and_drops_prefixes(self) -> None:
        self.assertEqual(
            ".ai/generated/newapp-002-env-contract.json",
            normalize_for_path_guard("./" + REPORT_RELATIVE_PATH),
        )
        self.assertEqual(
            "docs/configuration_contract.md", normalize_for_path_guard(".\\docs\\CONFIGURATION_CONTRACT.md")
        )
        mirror = path_guard_compatibility(
            [REPORT_RELATIVE_PATH, DOC_RELATIVE_PATH, ".env"],
            CONTROLLER_ALLOWED_PATTERNS,
            CONTROLLER_PROTECTED_PATTERNS,
            ".ai/agent_config.yaml#paths.executor_allowed",
        )
        self.assertFalse(mirror["all_paths_accepted"])
        self.assertEqual([".env"], [entry["path"] for entry in mirror["protected_paths_touched"]])


class ParserAndRendererTests(unittest.TestCase):
    """Direct checks on the parser and the renderers the report is built from."""

    def test_parser_returns_names_and_shapes_without_any_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = populate_root(Path(temporary), groups=None)
            parsed = read_env_declarations(root / ENV_FILE)
            self.assertFalse(parsed["values_returned"])
            serialized = json.dumps(parsed, ensure_ascii=False)
            for value in SYNTHETIC_VALUES:
                with self.subTest(value=value):
                    self.assertNotIn(value, serialized)
            self.assertEqual(
                [
                    "configured",
                    "duplicate",
                    "export_prefixed",
                    "group",
                    "group_title",
                    "line",
                    "matched_groups",
                    "matched_tokens",
                    "name",
                    "quoted",
                ],
                sorted(parsed["entries"][0]),
            )
            self.assertEqual(13, parsed["line_count"])
            self.assertEqual(["ERP_Oss__Bucket"], parsed["duplicate_names"])

    def test_scanner_module_returns_none_when_the_checkout_lacks_the_scanner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.assertIsNone(scanner_module(Path(temporary)))
            self.assertIsNone(scanner_module(Path(temporary)))

    def test_scanner_self_check_flags_a_leaky_artifact_without_echoing_it(self) -> None:
        fake_identifier = "AK" + "IA" + "IOSFODNN7EXAMPL" + "E"
        result = scanner_self_check({"docs/leaky.md": f"identifier {fake_identifier}\n"})
        self.assertEqual("failed", result["status"])
        self.assertEqual(["known_token_prefix"], [item["rule"] for item in result["findings"]])
        self.assertEqual(["docs/leaky.md"], result["checked_paths"])
        self.assertNotIn(fake_identifier, json.dumps(result, ensure_ascii=False))

    def test_renderers_match_the_finalized_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report, report_text, markdown = render_artifacts(policy_root(temporary))
            self.assertEqual(report_text, render_json(report))
            self.assertEqual(markdown, render_markdown(report))
            self.assertEqual(report, json.loads(render_json(report)))
            self.assertNotIn("=", render_json(report))
            self.assertNotIn("=", render_markdown(report))


class CommandLineTests(unittest.TestCase):
    def test_write_creates_both_artifacts_in_a_disposable_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = policy_root(temporary)
            environment = root / ENV_FILE
            before = (environment.stat().st_mtime_ns, environment.stat().st_size)
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = main(
                    [
                        "--root",
                        str(root),
                        "--write",
                        "--executor-file",
                        "tests/config/env_contract.py",
                        "--executor-file",
                        "tests/config/test_env_contract.py",
                    ]
                )
            report_path = root / REPORT_RELATIVE_PATH
            doc_path = root / DOC_RELATIVE_PATH
            self.assertEqual(0, code)
            self.assertTrue(report_path.is_file())
            self.assertTrue(doc_path.is_file())
            report_text = report_path.read_text(encoding="utf-8")
            markdown = doc_path.read_text(encoding="utf-8")
            payload = json.loads(report_text)
            self.assertEqual(TASK_ID, payload["task_id"])
            self.assertEqual("evidence_collected", payload["status"])
            self.assertFalse(payload["safety_contract"]["values_recorded"])
            self.assertFalse(payload["safety_contract"]["environment_file_written"])
            self.assertTrue(
                payload["safety_contract"]["environment_file_modified_time_unchanged_during_run"]
            )
            for text in (report_text, markdown):
                self.assertNotIn("=", text)
                for value in SYNTHETIC_VALUES:
                    self.assertNotIn(value, text)
            self.assertEqual(before, (environment.stat().st_mtime_ns, environment.stat().st_size))
            printed = buffer.getvalue()
            self.assertIn("status=evidence_collected", printed)
            self.assertIn("written", printed)
            for name in payload["environment"]["names"]:
                self.assertNotIn(name + "=", printed)

    def test_missing_environment_file_is_reported_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = policy_root(temporary, env_text=None)
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = main(["--root", str(root)])
            self.assertEqual(1, code)
            self.assertFalse((root / REPORT_RELATIVE_PATH).exists())
            self.assertFalse((root / DOC_RELATIVE_PATH).exists())
            self.assertIn("status=attention_required", buffer.getvalue())


class RealRepositoryTests(unittest.TestCase):
    """Read-only checks against this checkout; nothing here writes or compares secret material."""

    def test_real_configuration_projections_are_clean(self) -> None:
        facts = collect_facts(
            REPOSITORY_ROOT,
            generated_at="2026-09-23T00:00:00Z",
            executor_paths=EXECUTOR_PATHS,
            report_paths=[REPORT_RELATIVE_PATH],
            doc_paths=[DOC_RELATIVE_PATH],
        )
        report, report_text, markdown = finalize_report(
            build_report(facts), facts["environment"]["names"]
        )
        self.assertEqual("evidence_collected", report["status"])
        self.assertNotIn("=", report_text)
        self.assertNotIn("=", markdown)
        self.assertTrue(report["required_key_groups"]["all_required_keys_present"])
        self.assertEqual([], report["path_guard"]["protected_paths_touched"])

    def test_real_controller_configuration_supplies_both_pattern_lists(self) -> None:
        facts = collect_facts(REPOSITORY_ROOT, generated_at="2026-09-23T00:00:00Z")
        self.assertGreater(len(facts["allowed_paths"]), 0)
        self.assertGreater(len(facts["protected_paths"]), 0)
        self.assertIn(".ai/agent_config.yaml", facts["protected_paths"])
        self.assertIn("docs/**", facts["allowed_paths"])

    @unittest.skipUnless(CONTROLLER_COMMON.is_file(), "controller common.py is unavailable")
    def test_mirror_matches_the_controller_path_matches(self) -> None:
        specification = importlib.util.spec_from_file_location(
            "newapp_controller_common_probe", CONTROLLER_COMMON
        )
        self.assertIsNotNone(specification)
        assert specification is not None and specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        paths = (
            *EXECUTOR_PATHS,
            "./" + REPORT_RELATIVE_PATH,
            ".\\docs\\CONFIGURATION_CONTRACT.md",
            ".env",
            ".ai/controller/common.py",
            "src/app.py",
        )
        for path in paths:
            with self.subTest(path=path):
                expected = bool(module.path_matches(path, CONTROLLER_ALLOWED_PATTERNS))
                mirrored = path_guard_compatibility(
                    [path],
                    CONTROLLER_ALLOWED_PATTERNS,
                    CONTROLLER_PROTECTED_PATTERNS,
                    "test fixture",
                )["paths"][0]["accepted"]
                self.assertEqual(expected, mirrored)
        self.assertTrue(module.path_matches(REPORT_RELATIVE_PATH, CONTROLLER_ALLOWED_PATTERNS))
        self.assertTrue(module.path_matches(DOC_RELATIVE_PATH, CONTROLLER_ALLOWED_PATTERNS))
        self.assertFalse(module.path_matches(".env", CONTROLLER_ALLOWED_PATTERNS))

    def test_real_environment_file_is_still_ignored_and_untracked(self) -> None:
        environment = REPOSITORY_ROOT / ENV_FILE
        if not environment.is_file():
            self.skipTest("the local environment file is absent on this checkout")
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", ENV_FILE],
            cwd=str(REPOSITORY_ROOT),
            capture_output=True,
            text=True,
            shell=False,
        )
        self.assertEqual(0, ignored.returncode, "the local environment file must stay ignored by git")
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", ENV_FILE],
            cwd=str(REPOSITORY_ROOT),
            capture_output=True,
            text=True,
            shell=False,
        )
        self.assertNotEqual(0, tracked.returncode, "the local environment file must stay untracked")


class CommittedArtifactTests(unittest.TestCase):
    """The two generated artifacts are the publishable evidence reviewed by the GPT brain."""

    def test_committed_artifacts_exist_and_are_value_free(self) -> None:
        self.assertTrue(REPORT_PATH.is_file(), "regenerate with tests/config/env_contract.py --write")
        self.assertTrue(DOC_PATH.is_file(), "regenerate with tests/config/env_contract.py --write")
        report_text = REPORT_PATH.read_text(encoding="utf-8")
        markdown = DOC_PATH.read_text(encoding="utf-8")
        payload = json.loads(report_text)
        self.assertEqual(TASK_ID, payload["task_id"])
        self.assertEqual("evidence_collected", payload["status"])
        self.assertFalse(payload["safety_contract"]["values_recorded"])
        self.assertFalse(payload["safety_contract"]["environment_file_written"])
        self.assertTrue(payload["path_guard"]["all_paths_accepted"])
        self.assertEqual([], payload["path_guard"]["protected_paths_touched"])
        declared = [entry["name"] for entry in payload["environment"]["entries"]]
        self.assertTrue(declared)
        for text, label in ((report_text, REPORT_RELATIVE_PATH), (markdown, DOC_RELATIVE_PATH)):
            with self.subTest(artifact=label):
                self.assertNotIn("=", text)
                self.assertEqual("passed", value_leak_guard(text, declared, label)["status"])
                for name in declared:
                    self.assertNotIn(name + "=", text)
        for statement in REQUIRED_DOC_STATEMENTS:
            with self.subTest(statement=statement):
                self.assertIn(statement, markdown)

    def test_committed_report_matches_the_local_environment_names(self) -> None:
        environment = REPOSITORY_ROOT / ENV_FILE
        if not environment.is_file():
            self.skipTest("the local environment file is absent on this checkout")
        self.assertTrue(REPORT_PATH.is_file(), "regenerate with tests/config/env_contract.py --write")
        payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        local = analyse_env_file(environment, ENV_FILE)
        self.assertEqual(local["names"], payload["environment"]["names"])
        self.assertEqual(local["declaration_count"], payload["environment"]["declaration_count"])
        self.assertEqual(
            local["malformed_line_numbers"], payload["environment"]["malformed_line_numbers"]
        )


if __name__ == "__main__":
    unittest.main()
