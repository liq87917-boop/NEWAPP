"""Unit tests for the NEWAPP-004 shared OSS contract utilities.

Every test uses disposable temporary directories, except the read-only checks that inspect the real
checkout (declaration names in ``.env``, the declared DDL and API contract, the reused NEWAPP-002
helpers and the committed artifacts). No test writes into the repository, opens a database or OSS
connection, sends a network request, or records, prints, compares or hashes a credential value.

Synthetic fixtures use placeholder-shaped right-hand sides and placeholder host names, so this tracked
test file can never trip the scanner it collaborates with.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

OSS_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = OSS_DIR.parents[1]
CONFIG_DIR = REPOSITORY_ROOT / "tests" / "config"
for _candidate in (OSS_DIR, CONFIG_DIR):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

import env_contract  # noqa: E402  (the reused NEWAPP-002 dependency of this task)
import oss_contract  # noqa: E402
from oss_contract import (  # noqa: E402
    ASSET_TABLE,
    CLIENT_BOUNDARY_RULES,
    CONVENTION_PATTERNS,
    DDL_RELATIVE_PATH,
    DOC_RELATIVE_PATH,
    ENV_FILE,
    ENDPOINT_KEY,
    OPENAPI_RELATIVE_PATH,
    OSS_KEY_NAMES,
    PROVIDER_SUFFIXES,
    PROVIDER_UNRECOGNISED,
    RECORDED_RULES,
    REPORT_RELATIVE_PATH,
    SCANNER_RELATIVE_PATH,
    TASK_ID,
    analyse_oss_declarations,
    build_report,
    classify_endpoint_shape,
    collect_facts,
    finalize_report,
    inspect_ddl,
    inspect_openapi,
    iter_search_paths,
    main,
    required_oss_names,
    scan_convention_patterns,
    scan_reference_tree,
)

REPORT_PATH = REPOSITORY_ROOT / REPORT_RELATIVE_PATH
DOC_PATH = REPOSITORY_ROOT / DOC_RELATIVE_PATH
CONTROLLER_COMMON = REPOSITORY_ROOT / ".ai" / "controller" / "common.py"

# Mirror of the controller policy in .ai/agent_config.yaml (paths.executor_allowed / paths.protected).
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
    "tests/oss/__init__.py",
    "tests/oss/oss_contract.py",
    "tests/oss/test_oss_contract.py",
)

# Placeholder-shaped synthetic values. No real endpoint, bucket or credential is used by these tests.
ENDPOINT_VALUE = "https://synthetic-objects.aliyuncs.com"
UNKNOWN_ENDPOINT_VALUE = "https://objects.custom-provider.invalid"
MASKED_ENDPOINT_VALUE = "${OSS_ENDPOINT_PLACEHOLDER}"
BUCKET_VALUE = "example-bucket"
IDENTIFIER_VALUE = "example-identifier"
MATERIAL_VALUE = "example-material"
CONNECTION_VALUE = "example-connection"
SIGNING_VALUE = "example-signing"
SYNTHETIC_VALUES = (
    ENDPOINT_VALUE,
    UNKNOWN_ENDPOINT_VALUE,
    MASKED_ENDPOINT_VALUE,
    BUCKET_VALUE,
    IDENTIFIER_VALUE,
    MATERIAL_VALUE,
    CONNECTION_VALUE,
    SIGNING_VALUE,
)

SYNTHETIC_ENV = "\n".join(
    [
        "# synthetic declaration fixture for NEWAPP-004 tests",
        "",
        f'export ERP_ConnectionStrings__Default="{CONNECTION_VALUE}"',
        f"ERP_Oss__Endpoint={ENDPOINT_VALUE}",
        f"ERP_Oss__Bucket={BUCKET_VALUE}",
        f"ERP_Oss__AccessKeyId={IDENTIFIER_VALUE}",
        f"ERP_Oss__AccessKeySecret={MATERIAL_VALUE}",
        f"ERP_Jwt__Key='{SIGNING_VALUE}'",
        "EMPTY_SETTING=",
        f"ERP_Oss__Bucket={BUCKET_VALUE}",
    ]
) + "\n"

REQUIRED_KEY_GROUPS = {
    "oss": list(OSS_KEY_NAMES),
    "database": ["ERP_ConnectionStrings__Default"],
    "auth": ["ERP_Jwt__Key"],
}

SYNTHETIC_DDL = "\n".join(
    [
        "IF OBJECT_ID(N'app.FileAsset', N'U') IS NULL",
        "BEGIN",
        "    CREATE TABLE app.FileAsset(",
        "        AssetId UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_app_FileAsset PRIMARY KEY DEFAULT(NEWSEQUENTIALID()),",
        "        TenantId UNIQUEIDENTIFIER NOT NULL,",
        "        Purpose NVARCHAR(32) NOT NULL,",
        "        ObjectKey NVARCHAR(600) NOT NULL,",
        "        Bucket NVARCHAR(160) NULL,",
        "        UploadStatus TINYINT NOT NULL CONSTRAINT DF_app_FileAsset_UploadStatus DEFAULT(0), /*0 pending 1 ready 2 failed 3 deleted*/",
        "        CONSTRAINT UQ_app_FileAsset_Object UNIQUE(TenantId, ObjectKey)",
        "    );",
        "END",
        "GO",
        "IF OBJECT_ID(N'app.ExportJob', N'U') IS NULL",
        "BEGIN",
        "    CREATE TABLE app.ExportJob(",
        "        ResultAssetId UNIQUEIDENTIFIER NULL,",
        "        CONSTRAINT FK_app_ExportJob_Asset FOREIGN KEY(ResultAssetId) REFERENCES app.FileAsset(AssetId)",
        "    );",
        "END",
        "GO",
    ]
) + "\n"

SYNTHETIC_OPENAPI = "\n".join(
    [
        "paths:",
        "  /files/upload-ticket:",
        "    post:",
        "      operationId: createUploadTicket",
        "      requestBody:",
        "        required: true",
        "        content:",
        "          application/json:",
        "            schema:",
        "              type: object",
        "              required: [purpose, fileName, contentType, sha256]",
        "              properties:",
        "                purpose: {type: string, enum: [product, customer_photo]}",
        "  /files/{assetId}/complete:",
        "    post:",
        "      operationId: completeUpload",
        "components:",
        "  schemas:",
        "    UploadTicket:",
        "      type: object",
        "      required: [assetId, uploadUrl, expiresAt]",
        "      properties:",
        "        assetId: {type: string, format: uuid}",
        "        uploadUrl: {type: string, format: uri}",
        "        objectKey: {type: string}",
        "        expiresAt: {type: string, format: date-time}",
    ]
) + "\n"

CREDENTIAL_TICKET_FIELD = "accessKeySecret"
SYNTHETIC_OPENAPI_WITH_CREDENTIAL = SYNTHETIC_OPENAPI.replace(
    "        objectKey: {type: string}",
    "        objectKey: {type: string}\n        " + CREDENTIAL_TICKET_FIELD + ": {type: string}",
)


def write_text(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def populate_root(
    root: Path,
    *,
    env_text: str | None = SYNTHETIC_ENV,
    groups: Any = REQUIRED_KEY_GROUPS,
    ddl: str | None = SYNTHETIC_DDL,
    openapi: str | None = SYNTHETIC_OPENAPI,
    allowed: Any = None,
    protected: Any = None,
) -> Path:
    """Fill a disposable root with a synthetic environment file, contracts and controller policy."""
    if env_text is not None:
        write_text(root, ENV_FILE, env_text)
    if ddl is not None:
        write_text(root, DDL_RELATIVE_PATH, ddl)
    if openapi is not None:
        write_text(root, OPENAPI_RELATIVE_PATH, openapi)
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


def render_artifacts(
    root: Path, *, reference_tree: str | None = None
) -> tuple[dict[str, Any], str, str]:
    """Collect facts, build the report and render both artifacts for one root."""
    facts = collect_facts(
        root,
        generated_at="2026-09-24T00:00:00Z",
        reference_tree=reference_tree,
        executor_paths=EXECUTOR_PATHS,
        report_paths=[REPORT_RELATIVE_PATH],
        doc_paths=[DOC_RELATIVE_PATH],
    )
    return finalize_report(build_report(facts), facts["declarations"]["names"])


class EndpointShapeTests(unittest.TestCase):
    """The endpoint text must never leave the classifier; only shape facts and a family label may."""

    def test_every_documented_family_is_recognised(self) -> None:
        for family, suffixes in PROVIDER_SUFFIXES:
            for suffix in suffixes:
                with self.subTest(family=family, suffix=suffix):
                    shape = classify_endpoint_shape("https://example-objects." + suffix)
                    self.assertEqual(family, shape["provider_family"])
                    self.assertTrue(shape["provider_suffix_matched"])
                    self.assertTrue(shape["configured"])
                    self.assertTrue(shape["uses_secure_scheme"])
                    self.assertFalse(shape["text_recorded"])

    def test_custom_domain_is_reported_as_unrecognised(self) -> None:
        shape = classify_endpoint_shape(UNKNOWN_ENDPOINT_VALUE)
        self.assertEqual(PROVIDER_UNRECOGNISED, shape["provider_family"])
        self.assertFalse(shape["provider_suffix_matched"])
        self.assertTrue(shape["configured"])

    def test_masked_and_empty_endpoints_are_not_guessed(self) -> None:
        masked = classify_endpoint_shape(MASKED_ENDPOINT_VALUE)
        self.assertEqual(PROVIDER_UNRECOGNISED, masked["provider_family"])
        self.assertTrue(masked["configured"])
        empty = classify_endpoint_shape("")
        self.assertFalse(empty["configured"])
        self.assertEqual(PROVIDER_UNRECOGNISED, empty["provider_family"])

    def test_scheme_port_path_and_host_flags(self) -> None:
        shape = classify_endpoint_shape("https://example-objects.aliyuncs.com:8443/nested/path")
        self.assertTrue(shape["has_scheme"])
        self.assertTrue(shape["uses_secure_scheme"])
        self.assertTrue(shape["has_explicit_port"])
        self.assertTrue(shape["has_path_component"])
        self.assertEqual(3, shape["host_label_count"])
        self.assertFalse(shape["looks_like_ipv4_literal"])
        plain = classify_endpoint_shape("10.20.30.40")
        self.assertFalse(plain["has_scheme"])
        self.assertTrue(plain["looks_like_ipv4_literal"])
        self.assertEqual(4, plain["host_label_count"])

    def test_quoted_endpoints_are_flagged_without_returning_the_text(self) -> None:
        shape = classify_endpoint_shape('"' + ENDPOINT_VALUE + '"')
        self.assertTrue(shape["quoted"])
        self.assertTrue(shape["configured"])
        self.assertEqual("aliyun_oss", shape["provider_family"])

    def test_no_endpoint_text_is_returned_by_the_classifier(self) -> None:
        shape = classify_endpoint_shape(ENDPOINT_VALUE)
        rendered = json.dumps(shape)
        for fragment in ("synthetic-objects", "aliyuncs", "https", "://"):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, rendered)
        self.assertEqual(
            sorted(
                [
                    "configured",
                    "has_explicit_port",
                    "has_path_component",
                    "has_scheme",
                    "host_label_count",
                    "looks_like_ipv4_literal",
                    "provider_family",
                    "provider_suffix_matched",
                    "quoted",
                    "text_recorded",
                    "uses_secure_scheme",
                ]
            ),
            sorted(shape),
        )


class DeclarationFactsTests(unittest.TestCase):
    def test_declared_oss_names_and_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = policy_root(temporary)
            facts = analyse_oss_declarations(root)
            self.assertTrue(facts["exists"])
            self.assertTrue(facts["read_only"])
            self.assertEqual(sorted(OSS_KEY_NAMES), sorted(set(facts["oss_names"])))
            self.assertEqual(5, len(facts["oss_names"]))
            self.assertEqual(8, facts["declaration_count"])
            self.assertTrue(facts["endpoint"]["declared"])
            self.assertTrue(facts["endpoint"]["configured"])
            self.assertEqual("aliyun_oss", facts["endpoint"]["provider_family"])
            self.assertTrue(facts["bucket"]["declared"])
            self.assertFalse(facts["bucket"]["bucket_name_recorded"])
            self.assertEqual(["ERP_Oss__Bucket"], facts["duplicate_oss_names"])
            for entry in facts["material"]:
                with self.subTest(name=entry["name"]):
                    self.assertTrue(entry["declared"])
                    self.assertTrue(entry["configured"])
                    self.assertFalse(entry["material_read"])
                    self.assertFalse(entry["material_recorded"])
                    self.assertFalse(entry["issued_to_client"])
            self.assertTrue(facts["modified_time_unchanged_during_run"])
            self.assertFalse(facts["values_recorded"])

    def test_no_value_text_reaches_the_collected_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            facts = analyse_oss_declarations(policy_root(temporary))
            rendered = json.dumps(facts, ensure_ascii=False)
            for value in SYNTHETIC_VALUES:
                with self.subTest(value=value):
                    self.assertNotIn(value, rendered)
            self.assertNotIn("=", rendered)

    def test_shape_flags_agree_with_the_reused_reader(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = policy_root(temporary)
            reused = [
                entry
                for entry in env_contract.read_env_declarations(root / ENV_FILE)["entries"]
                if entry["name"] in OSS_KEY_NAMES
            ]
            mine = analyse_oss_declarations(root)
            self.assertEqual(
                [entry["name"] for entry in reused],
                [entry["name"] for entry in mine["oss_entries"]],
            )
            for reused_entry, mine_entry in zip(reused, mine["oss_entries"]):
                with self.subTest(name=mine_entry["name"], line=mine_entry["line"]):
                    self.assertEqual(reused_entry["line"], mine_entry["line"])
                    self.assertEqual(reused_entry["configured"], mine_entry["configured"])
                    self.assertEqual(reused_entry["quoted"], mine_entry["quoted"])
                    self.assertEqual(reused_entry["duplicate"], mine_entry["duplicate"])

    def test_absent_environment_file_is_reported_without_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            facts = analyse_oss_declarations(Path(temporary))
            self.assertFalse(facts["exists"])
            self.assertEqual([], facts["oss_names"])
            self.assertFalse(facts["endpoint"]["declared"])
            self.assertFalse(facts["values_recorded"])


class RequiredNameTests(unittest.TestCase):
    def test_all_required_names_present(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = policy_root(temporary)
            facts = required_oss_names(root, analyse_oss_declarations(root))
            self.assertTrue(facts["available"])
            self.assertEqual(4, facts["required_count"])
            self.assertEqual(4, facts["present_count"])
            self.assertEqual([], facts["missing"])
            self.assertEqual([], facts["unconfigured"])
            self.assertTrue(facts["all_present"])

    def test_missing_and_empty_names_are_reported(self) -> None:
        env_text = "\n".join(
            [
                f"ERP_Oss__Endpoint={ENDPOINT_VALUE}",
                f"ERP_Oss__Bucket={BUCKET_VALUE}",
                "ERP_Oss__AccessKeyId=",
            ]
        ) + "\n"
        with tempfile.TemporaryDirectory() as temporary:
            root = policy_root(temporary, env_text=env_text)
            facts = required_oss_names(root, analyse_oss_declarations(root))
            self.assertEqual(["ERP_Oss__AccessKeySecret"], facts["missing"])
            self.assertEqual(["ERP_Oss__AccessKeyId"], facts["unconfigured"])
            self.assertFalse(facts["all_present"])

    def test_absent_controller_configuration_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = populate_root(Path(temporary), groups=None)
            facts = required_oss_names(root, analyse_oss_declarations(root))
            self.assertFalse(facts["available"])
            self.assertEqual([], facts["required"])
            self.assertFalse(facts["all_present"])


class DdlInspectionTests(unittest.TestCase):
    def test_synthetic_ddl_reports_columns_constraints_and_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = populate_root(Path(temporary), allowed=CONTROLLER_ALLOWED_PATTERNS)
            facts = inspect_ddl(root)
            self.assertTrue(facts["available"])
            self.assertEqual(DDL_RELATIVE_PATH, facts["path"])
            self.assertEqual(ASSET_TABLE, facts["asset_table"])
            self.assertIsNotNone(facts["table_definition_start_line"])
            self.assertIsNotNone(facts["table_definition_end_line"])
            columns = {column["name"]: column for column in facts["columns"]}
            self.assertEqual(
                ["Bucket", "ObjectKey", "Purpose", "UploadStatus"], sorted(columns)
            )
            self.assertEqual("NOT NULL", columns["ObjectKey"]["nullability"])
            self.assertEqual("600", columns["ObjectKey"]["length"])
            self.assertEqual("NULL", columns["Bucket"]["nullability"])
            self.assertEqual(1, len(facts["unique_constraints"]))
            constraint = facts["unique_constraints"][0]
            self.assertEqual("UQ_app_FileAsset_Object", constraint["name"])
            self.assertEqual(["TenantId", "ObjectKey"], constraint["columns"])
            self.assertEqual(ASSET_TABLE, constraint["table"])
            self.assertEqual(1, len(facts["referencing_foreign_keys"]))
            key = facts["referencing_foreign_keys"][0]
            self.assertEqual("FK_app_ExportJob_Asset", key["name"])
            self.assertEqual("app.ExportJob", key["table"])
            self.assertEqual(["AssetId"], key["target_columns"])
            self.assertEqual(["pending", "ready", "failed", "deleted"], facts["upload_status_tokens"])
            self.assertFalse(facts["ddl_executed"])
            self.assertTrue(facts["ddl_apply_requires_human_gate"])
            self.assertFalse(facts["values_recorded"])

    def test_absent_ddl_is_reported_without_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            facts = inspect_ddl(populate_root(Path(temporary), ddl=None, groups=None))
            self.assertFalse(facts["available"])
            self.assertFalse(facts["ddl_executed"])
            self.assertIn("reason", facts)


class OpenApiInspectionTests(unittest.TestCase):
    def test_synthetic_contract_reports_the_ticket_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = populate_root(Path(temporary), allowed=CONTROLLER_ALLOWED_PATTERNS)
            facts = inspect_openapi(root)
            self.assertTrue(facts["available"])
            self.assertEqual("/files/upload-ticket", facts["upload_ticket_path"]["path"])
            self.assertIsNotNone(facts["upload_ticket_path"]["line"])
            self.assertEqual(
                ["purpose", "fileName", "contentType", "sha256"],
                facts["upload_ticket_path"]["request_required_fields"],
            )
            self.assertEqual(["product", "customer_photo"], facts["asset_purpose_tokens"])
            ticket = facts["ticket_schema"]
            self.assertEqual("UploadTicket", ticket["name"])
            self.assertEqual(["assetId", "uploadUrl", "expiresAt"], ticket["required_fields"])
            self.assertEqual(
                ["assetId", "uploadUrl", "objectKey", "expiresAt"], ticket["property_names"]
            )
            self.assertEqual([], ticket["credential_fields"])
            self.assertEqual(0, ticket["credential_field_count"])
            self.assertEqual([], facts["declared_download_paths"])
            self.assertFalse(facts["requests_sent"])
            self.assertFalse(facts["values_recorded"])

    def test_a_credential_field_in_a_ticket_is_reported_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = populate_root(
                Path(temporary),
                openapi=SYNTHETIC_OPENAPI_WITH_CREDENTIAL,
                allowed=CONTROLLER_ALLOWED_PATTERNS,
            )
            facts = inspect_openapi(root)
            self.assertEqual(
                [CREDENTIAL_TICKET_FIELD], facts["ticket_schema"]["credential_fields"]
            )
            self.assertEqual(1, facts["ticket_schema"]["credential_field_count"])

    def test_absent_contract_is_reported_without_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            facts = inspect_openapi(populate_root(Path(temporary), openapi=None, groups=None))
            self.assertFalse(facts["available"])
            self.assertFalse(facts["requests_sent"])


class SearchScopeTests(unittest.TestCase):
    def test_scope_excludes_ignored_directories_self_paths_and_binaries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_text(root, "docs/NEWAPP_OpenAPI_V1.yaml", SYNTHETIC_OPENAPI)
            write_text(root, ".ai/logs/20260101-run-cline.jsonl", "{}")
            write_text(root, ".ai/controller/agent_loop.py", "ObjectKey = 1")
            write_text(root, "docs/NEWAPP_Database_DDL_V1.sql", SYNTHETIC_DDL)
            write_text(root, "docs/SHARED_OSS_CONTRACT.md", "generated document")
            write_text(root, ".venv/lib/module.py", "ObjectKey = 1")
            write_text(root, "docs/image.docx", "binary placeholder")
            write_text(root, "docs/binary.json", "placeholder")
            (root / "docs" / "binary.json").write_bytes(b"\x00\x01\x02")
            write_text(root, "tests/oss/oss_contract.py", "ObjectKey = 1")
            listing = iter_search_paths(root)
            self.assertIn("docs/NEWAPP_OpenAPI_V1.yaml", listing["paths"])
            self.assertIn("docs/NEWAPP_Database_DDL_V1.sql", listing["paths"])
            self.assertIn("tests/oss/oss_contract.py", listing["paths"])
            for excluded in (
                ".ai/logs/20260101-run-cline.jsonl",
                ".ai/controller/agent_loop.py",
                "docs/SHARED_OSS_CONTRACT.md",
                ".venv/lib/module.py",
                "docs/image.docx",
                "docs/binary.json",
            ):
                with self.subTest(path=excluded):
                    self.assertNotIn(excluded, listing["paths"])
            reasons = {entry["path"]: entry["reason"] for entry in listing["excluded"]}
            self.assertIn("docs/SHARED_OSS_CONTRACT.md", reasons)
            self.assertIn("docs/binary.json", reasons)

    def test_pattern_scan_records_paths_and_lines_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_text(root, "docs/NEWAPP_Database_DDL_V1.sql", SYNTHETIC_DDL)
            write_text(root, "docs/NEWAPP_OpenAPI_V1.yaml", SYNTHETIC_OPENAPI)
            listing = iter_search_paths(root)
            scan = scan_convention_patterns(root, listing["paths"])
            by_id = {item["id"]: item for item in scan["patterns"]}
            self.assertEqual(sorted(item[0] for item in CONVENTION_PATTERNS), sorted(by_id))
            self.assertGreater(by_id["object_key_field"]["match_count"], 0)
            self.assertGreater(by_id["upload_ticket_boundary"]["match_count"], 0)
            self.assertEqual(0, by_id["key_prefix_token"]["match_count"])
            rendered = json.dumps(scan)
            for fragment in ("ObjectKey:", "NVARCHAR", "UNIQUE(", "UploadTicket:"):
                with self.subTest(fragment=fragment):
                    self.assertNotIn(fragment, rendered)
            self.assertFalse(scan["matched_text_recorded"])
            searched = {"docs/NEWAPP_Database_DDL_V1.sql", "docs/NEWAPP_OpenAPI_V1.yaml"}
            for item in scan["patterns"]:
                for entry in item["files"]:
                    with self.subTest(pattern=item["id"], path=entry["path"]):
                        self.assertIn(entry["path"], searched)
                        self.assertTrue(all(number > 0 for number in entry["line_numbers"]))


class ReferenceTreeTests(unittest.TestCase):
    def test_without_a_reference_tree_the_convention_stays_unresolved(self) -> None:
        outcome = scan_reference_tree(None)
        self.assertEqual("not_provided", outcome["mode"])
        self.assertEqual(0, outcome["paths_searched"])
        self.assertFalse(outcome["files_written_to_reference_tree"])
        self.assertIn("unresolved", outcome["reason"])

    def test_a_supplied_reference_tree_is_searched_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reference = Path(temporary) / "reference-tree"
            write_text(
                reference,
                "src/Storage/ObjectKeyBuilder.cs",
                "objectKey = purpose + \"/\" + tenantId;",
            )
            write_text(reference, "docs/README.md", "no asset token here")
            outcome = scan_reference_tree(str(reference))
            self.assertEqual("scanned_read_only", outcome["mode"])
            self.assertEqual(2, outcome["paths_searched"])
            by_id = {item["id"]: item for item in outcome["patterns"]}
            self.assertGreater(by_id["object_key_field"]["match_count"], 0)
            self.assertIn(
                "src/Storage/ObjectKeyBuilder.cs",
                [entry["path"] for entry in by_id["object_key_field"]["files"]],
            )
            self.assertFalse(outcome["files_written_to_reference_tree"])
            rendered = json.dumps(outcome)
            self.assertNotIn("tenantId", rendered)

    def test_an_unavailable_reference_path_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = str(Path(temporary) / "absent-tree")
            outcome = scan_reference_tree(missing)
            self.assertEqual("unavailable", outcome["mode"])
            self.assertEqual(missing, outcome["path_label"])
            self.assertEqual([], outcome["patterns"])


class ArtifactRenderingTests(unittest.TestCase):
    """The rendered report and document are the evidence, so both must be value free."""

    def test_rendered_artifacts_contain_no_values_or_assignment_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report, report_text, markdown = render_artifacts(policy_root(temporary))
            self.assertEqual("evidence_collected", report["status"])
            self.assertEqual("passed", report["report_value_guard"]["status"])
            self.assertEqual("passed", report["documentation_value_guard"]["status"])
            self.assertEqual("passed", report["documentation_statements"]["status"])
            for text, label in ((report_text, REPORT_RELATIVE_PATH), (markdown, DOC_RELATIVE_PATH)):
                with self.subTest(artifact=label):
                    self.assertNotIn("=", text)
                    for value in SYNTHETIC_VALUES:
                        self.assertNotIn(value, text)
                    for name in report["environment"]["names"]:
                        self.assertNotIn(name + "=", text)

    def test_guards_and_scanner_run_over_both_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report, report_text, markdown = render_artifacts(policy_root(temporary))
            scan = report["scanner_self_check"]
            self.assertTrue(scan["available"])
            self.assertEqual(SCANNER_RELATIVE_PATH, scan["scanner"])
            self.assertEqual("passed", scan["status"])
            self.assertEqual([], scan["findings"])
            self.assertEqual(
                sorted([DOC_RELATIVE_PATH, REPORT_RELATIVE_PATH]), sorted(scan["checked_paths"])
            )
            # The guards are the accepted NEWAPP-002 implementations, not copies.
            self.assertIs(env_contract.value_leak_guard, oss_contract.value_leak_guard)
            self.assertIs(env_contract.scanner_self_check, oss_contract.scanner_self_check)
            self.assertIs(env_contract.read_env_declarations, oss_contract.read_env_declarations)
            self.assertGreater(report["artifact_check_passes"], 0)
            self.assertIn("family", report["provider"])
            self.assertFalse(report["provider"]["endpoint_text_recorded"])

    def test_rendering_is_deterministic_for_identical_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = policy_root(temporary)
            _, first_text, first_doc = render_artifacts(root)
            _, second_text, second_doc = render_artifacts(root)
            self.assertEqual(first_text, second_text)
            self.assertEqual(first_doc, second_doc)

    def test_document_states_the_strategy_and_the_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, _, markdown = render_artifacts(policy_root(temporary))
            for statement in oss_contract.DOCUMENTATION_STATEMENTS:
                with self.subTest(statement=statement):
                    self.assertIn(statement, markdown)
            for rule in (*RECORDED_RULES, *CLIENT_BOUNDARY_RULES):
                with self.subTest(rule=rule[:40]):
                    self.assertIn(rule, markdown)
            self.assertIn("python tests/oss/oss_contract.py --write", markdown)
            self.assertIn("proposed_for_gpt_review_not_established_by_this_task", markdown)
            self.assertIn("Displayed as a recorded convention: no.", markdown)

    def test_path_guard_accepts_every_recorded_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report, _, markdown = render_artifacts(policy_root(temporary))
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

    def test_protected_path_blocks_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = policy_root(temporary)
            facts = collect_facts(
                root,
                generated_at="2026-09-24T00:00:00Z",
                executor_paths=[*EXECUTOR_PATHS, ".env"],
                report_paths=[REPORT_RELATIVE_PATH],
                doc_paths=[DOC_RELATIVE_PATH],
            )
            report, _, markdown = finalize_report(
                build_report(facts), facts["declarations"]["names"]
            )
            guard = report["path_guard"]
            self.assertFalse(guard["all_paths_accepted"])
            self.assertEqual(
                [".env"], [entry["path"] for entry in guard["protected_paths_touched"]]
            )
            self.assertFalse(guard["no_protected_path_touched"])
            self.assertEqual("attention_required", report["status"])
            self.assertFalse(report["acceptance_evidence"][-1]["satisfied"])
            self.assertIn("Protected paths touched: .env.", markdown)

    def test_unreadable_contracts_make_the_report_attention_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = policy_root(temporary, ddl=None, openapi=None)
            report, _, _ = render_artifacts(root)
            self.assertEqual("attention_required", report["status"])
            self.assertFalse(report["acceptance_evidence"][0]["satisfied"])


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
                        "tests/oss/oss_contract.py",
                        "--executor-file",
                        "tests/oss/test_oss_contract.py",
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
            safety = payload["safety_contract"]
            self.assertFalse(safety["environment_file_written"])
            self.assertFalse(safety["credential_material_read"])
            self.assertFalse(safety["oss_calls_made"])
            self.assertTrue(safety["environment_file_modified_time_unchanged_during_run"])
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

    def test_write_refuses_to_publish_an_attention_required_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = policy_root(temporary, env_text=None)
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = main(["--root", str(root), "--write"])
            self.assertEqual(1, code)
            self.assertFalse((root / REPORT_RELATIVE_PATH).exists())
            self.assertFalse((root / DOC_RELATIVE_PATH).exists())
            printed = buffer.getvalue()
            self.assertIn("status=attention_required", printed)
            self.assertIn("not_written", printed)

    def test_a_supplied_reference_tree_is_recorded_in_the_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = policy_root(temporary)
            reference = Path(temporary) / "reference-tree"
            write_text(reference, "src/Storage/KeyBuilder.cs", "objectKey builder for a bucket path")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = main(["--root", str(root), "--write", "--reference-tree", str(reference)])
            self.assertEqual(0, code)
            payload = json.loads((root / REPORT_RELATIVE_PATH).read_text(encoding="utf-8"))
            reference_facts = payload["repository_search"]["reference_tree"]
            self.assertEqual("scanned_read_only", reference_facts["mode"])
            self.assertEqual(1, reference_facts["paths_searched"])
            self.assertFalse(reference_facts["files_written_to_reference_tree"])
            self.assertIn(
                "src/Storage/KeyBuilder.cs",
                [
                    entry["path"]
                    for item in reference_facts["patterns"]
                    for entry in item["files"]
                ],
            )


class RealRepositoryTests(unittest.TestCase):
    """Read-only checks against this checkout; nothing here writes or compares secret material."""

    def test_real_projections_are_clean(self) -> None:
        facts = collect_facts(
            REPOSITORY_ROOT,
            generated_at="2026-09-24T00:00:00Z",
            executor_paths=EXECUTOR_PATHS,
            report_paths=[REPORT_RELATIVE_PATH],
            doc_paths=[DOC_RELATIVE_PATH],
        )
        report, report_text, markdown = finalize_report(
            build_report(facts), facts["declarations"]["names"]
        )
        self.assertEqual("evidence_collected", report["status"])
        self.assertNotIn("=", report_text)
        self.assertNotIn("=", markdown)
        self.assertTrue(report["required_oss_names"]["all_present"])
        self.assertTrue(report["declared_contract"]["ddl"]["available"])
        self.assertTrue(report["declared_contract"]["openapi"]["available"])
        self.assertEqual([], report["path_guard"]["protected_paths_touched"])
        self.assertFalse(report["provider"]["endpoint_text_recorded"])

    def test_real_declared_contract_facts(self) -> None:
        ddl = inspect_ddl(REPOSITORY_ROOT)
        self.assertTrue(ddl["available"])
        columns = {column["name"]: column for column in ddl["columns"]}
        self.assertEqual({"Purpose", "ObjectKey", "Bucket", "UploadStatus"}, set(columns))
        self.assertEqual("NULL", columns["Bucket"]["nullability"])
        unique = {constraint["name"] for constraint in ddl["unique_constraints"]}
        self.assertIn("UQ_app_FileAsset_Object", unique)
        self.assertGreaterEqual(len(ddl["referencing_foreign_keys"]), 4)
        openapi = inspect_openapi(REPOSITORY_ROOT)
        self.assertTrue(openapi["available"])
        self.assertEqual("/files/upload-ticket", openapi["upload_ticket_path"]["path"])
        self.assertEqual([], openapi["ticket_schema"]["credential_fields"])
        self.assertIn("objectKey", openapi["ticket_schema"]["property_names"])

    def test_reused_helpers_come_from_the_previous_task(self) -> None:
        for name in (
            "value_leak_guard",
            "scanner_self_check",
            "path_guard_compatibility",
            "read_env_declarations",
            "atomic_write_text",
            "relative_to_root",
        ):
            with self.subTest(helper=name):
                self.assertIs(getattr(env_contract, name), getattr(oss_contract, name))
        self.assertEqual(env_contract.SCANNER_RELATIVE_PATH, SCANNER_RELATIVE_PATH)

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
        self.assertTrue(REPORT_PATH.is_file(), "regenerate with tests/oss/oss_contract.py --write")
        self.assertTrue(DOC_PATH.is_file(), "regenerate with tests/oss/oss_contract.py --write")
        report_text = REPORT_PATH.read_text(encoding="utf-8")
        markdown = DOC_PATH.read_text(encoding="utf-8")
        payload = json.loads(report_text)
        self.assertEqual(TASK_ID, payload["task_id"])
        self.assertEqual("evidence_collected", payload["status"])
        self.assertFalse(payload["safety_contract"]["environment_file_written"])
        self.assertFalse(payload["safety_contract"]["credential_material_read"])
        self.assertTrue(payload["path_guard"]["all_paths_accepted"])
        self.assertEqual([], payload["path_guard"]["protected_paths_touched"])
        declared = [entry["name"] for entry in payload["environment"]["oss_entries"]]
        self.assertEqual(sorted(OSS_KEY_NAMES), sorted(declared))
        for text, label in ((report_text, REPORT_RELATIVE_PATH), (markdown, DOC_RELATIVE_PATH)):
            with self.subTest(artifact=label):
                self.assertNotIn("=", text)
                self.assertEqual(
                    "passed", oss_contract.value_leak_guard(text, declared, label)["status"]
                )
                for name in declared:
                    self.assertNotIn(name + "=", text)
        for statement in oss_contract.DOCUMENTATION_STATEMENTS:
            with self.subTest(statement=statement):
                self.assertIn(statement, markdown)

    def test_committed_report_matches_the_local_environment(self) -> None:
        environment = REPOSITORY_ROOT / ENV_FILE
        if not environment.is_file():
            self.skipTest("the local environment file is absent on this checkout")
        self.assertTrue(REPORT_PATH.is_file(), "regenerate with tests/oss/oss_contract.py --write")
        payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        local = analyse_oss_declarations(REPOSITORY_ROOT)
        self.assertEqual(local["oss_names"], payload["environment"]["oss_names"])
        self.assertEqual(local["declaration_count"], payload["environment"]["declaration_count"])
        self.assertEqual(local["endpoint"]["provider_family"], payload["provider"]["family"])
        self.assertEqual(
            local["duplicate_oss_names"], payload["environment"]["duplicate_oss_names"]
        )


if __name__ == "__main__":
    unittest.main()









