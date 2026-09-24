"""Unit tests for the NEWAPP-005 DDL reconciliation utilities.

Every test runs offline: the optional ODBC driver module and the database connection are replaced by fakes, so no
test opens a socket, reaches the shared server or executes SQL. Only the read-only checks that inspect the real
checkout (the committed artifacts, the planned DDL contract and the accepted map) read repository files. No test
records, prints, compares or hashes a declared value, and the synthetic fixtures use placeholder-shaped values so
this tracked test file can never trip the scanner it collaborates with.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from typing import Any, Sequence

SCHEMA_DIR = Path(__file__).resolve().parent
if str(SCHEMA_DIR) not in sys.path:
    sys.path.insert(0, str(SCHEMA_DIR))

import ddl_reconciliation  # noqa: E402  (module handle for constant patching)
import newerp_schema  # noqa: E402
from ddl_reconciliation import (  # noqa: E402
    COMPILE_APP_TABLE_COUNT_QUERY,
    COMPILE_STATUS_COMPILED,
    COMPILE_STATUS_ENGINE_UNAVAILABLE,
    COMPILE_STATUS_FAILED,
    COMPILE_STATUS_GUARD_REFUSED,
    COMPILE_STATUS_NOT_REQUESTED,
    COMPILE_STATUS_TARGET_REFUSED,
    DOC_RELATIVE_PATH,
    KEY_REGISTRATIONS,
    REGISTRATION_BY_KEY,
    REPORT_RELATIVE_PATH,
    SCRIPT_RELATIVE_PATH,
    TASK_ID,
    build_disposable_target,
    build_report,
    collect_facts,
    disposable_compile_check,
    disposable_statement_guard,
    disposable_target_guard,
    key_resolution_rows,
    load_schema_map,
    main,
    parse_planned_ddl,
    physical_declaration,
    publication_blocked,
    recorded_target,
    reconcile_ddl,
    render_json,
    run_disposable_compile,
    split_batches,
    static_checks,
    strip_sql_comments,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPOSITORY_ROOT / REPORT_RELATIVE_PATH
DOC_PATH = REPOSITORY_ROOT / DOC_RELATIVE_PATH
SCRIPT_PATH = REPOSITORY_ROOT / SCRIPT_RELATIVE_PATH
DDL_PATH = REPOSITORY_ROOT / ddl_reconciliation.DDL_RELATIVE_PATH

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

# Placeholder-shaped synthetic declaration. No real credential value is used or needed by these tests.
SYNTHETIC_DECLARED_CONNECTION = (
    "Server=example-shared-server;Database=example-shared-catalog;User Id=example-account;"
    "Password=example-material;TrustServerCertificate=True"
)
SYNTHETIC_LOCALDB_DRIVER = "ODBC Driver 17 for SQL Server"

FIXTURE_DDL = """/* fixture: additive app schema with one neutral key and one app-local key */
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'app')
    EXEC(N'CREATE SCHEMA app AUTHORIZATION dbo;');
GO

IF OBJECT_ID(N'app.Sample', N'U') IS NULL
BEGIN
    CREATE TABLE app.Sample(
        SampleId UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_app_Sample PRIMARY KEY,
        CustomerKey NVARCHAR(80) NOT NULL,
        ObjectKey NVARCHAR(600) NOT NULL
    );
END
GO
"""


def resolved_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row["resolution"] in {"resolved_direct", "type_resolved_target_needs_review"}
    ]


class PhysicalDeclarationTests(unittest.TestCase):
    def test_recorded_catalog_types_render_faithfully(self) -> None:
        self.assertEqual("BIGINT", physical_declaration("bigint"))
        self.assertEqual("NVARCHAR(80)", physical_declaration("nvarchar", 80))
        self.assertEqual("DECIMAL(18,2)", physical_declaration("decimal", None, 18, 2))

    def test_unrenderable_type_is_reported_as_none_instead_of_guessed(self) -> None:
        self.assertIsNone(physical_declaration("", None))
        self.assertIsNone(physical_declaration("geography", None))
        self.assertIsNone(physical_declaration("decimal", None, None, None))


class AcceptedMapTests(unittest.TestCase):
    def test_accepted_map_records_the_shared_master_keys(self) -> None:
        schema_map = load_schema_map(REPOSITORY_ROOT)
        self.assertTrue(schema_map["available"], schema_map["reason"])
        for target in (
            "db_owner.BaseCustomers.Id",
            "db_owner.BaseSuppliers.Id",
            "db_owner.SysUsers.Id",
            "db_owner.BaseEmployees.Id",
        ):
            with self.subTest(target=target):
                recorded = recorded_target(schema_map, target)
                self.assertTrue(recorded["recorded"], recorded["reason"])
                self.assertEqual("BIGINT", recorded["declaration"])
                self.assertTrue(recorded["primary_key"])

    def test_missing_target_is_reported_instead_of_guessed(self) -> None:
        schema_map = load_schema_map(REPOSITORY_ROOT)
        recorded = recorded_target(schema_map, "db_owner.NoSuchTable.NoSuchColumn")
        self.assertFalse(recorded["recorded"])
        self.assertIsNone(recorded["declaration"])
        self.assertTrue(recorded["reason"])


class RegistrationTests(unittest.TestCase):
    def test_every_registration_is_unique_and_named(self) -> None:
        keys = [str(entry["neutral_key"]) for entry in KEY_REGISTRATIONS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), set(REGISTRATION_BY_KEY))

    def test_every_contract_neutral_key_is_registered(self) -> None:
        inventory = parse_planned_ddl(DDL_PATH.read_text(encoding="utf-8-sig"))
        declared = set(inventory["declarations"])
        self.assertTrue(declared)
        self.assertLessEqual(declared, set(REGISTRATION_BY_KEY))

    def test_resolved_registrations_match_the_accepted_map(self) -> None:
        schema_map = load_schema_map(REPOSITORY_ROOT)
        rows = key_resolution_rows(
            schema_map, parse_planned_ddl(DDL_PATH.read_text(encoding="utf-8-sig"))
        )
        resolved = resolved_rows(rows)
        self.assertGreaterEqual(len(resolved), 3)
        for row in resolved:
            with self.subTest(key=row["neutral_key"]):
                if row["target_table"]:
                    recorded = recorded_target(
                        schema_map, f"{row['target_table']}.{row['target_column']}"
                    )
                    self.assertTrue(recorded["recorded"], recorded["reason"])
                    self.assertEqual(row["resolved_type"], recorded["declaration"])
        resolved_keys = {str(row["neutral_key"]) for row in resolved}
        self.assertIn("CustomerKey", resolved_keys)
        self.assertIn("SupplierKey", resolved_keys)
        self.assertIn("UserKey", resolved_keys)

    def test_keys_without_an_authoritative_target_stay_unresolved_and_neutral(self) -> None:
        schema_map = load_schema_map(REPOSITORY_ROOT)
        inventory = parse_planned_ddl(DDL_PATH.read_text(encoding="utf-8-sig"))
        by_key = {str(row["neutral_key"]): row for row in key_resolution_rows(schema_map, inventory)}
        self.assertEqual("unresolved_human_gate", by_key["TenantId"]["resolution"])
        self.assertFalse(by_key["TenantId"]["raised_to_shared_type"])
        self.assertEqual("UNIQUEIDENTIFIER", by_key["TenantId"]["declared_type"])
        for key in ("SalesGroupKey", "TargetGroupKey", "TemplateKey"):
            with self.subTest(key=key):
                self.assertEqual("unresolved_human_gate", by_key[key]["resolution"])
                self.assertFalse(by_key[key]["raised_to_shared_type"])

    def test_app_owned_identifiers_are_not_mapped_to_shared_objects(self) -> None:
        schema_map = load_schema_map(REPOSITORY_ROOT)
        rows = key_resolution_rows(
            schema_map, parse_planned_ddl(DDL_PATH.read_text(encoding="utf-8-sig"))
        )
        by_key = {str(row["neutral_key"]): row for row in rows}
        for key in ("ObjectKey", "IdempotencyKey", "EntityKey"):
            with self.subTest(key=key):
                self.assertEqual("app_local", by_key[key]["resolution"])
                self.assertFalse(by_key[key]["raised_to_shared_type"])


class DdlRewritingTests(unittest.TestCase):
    def rows_for_fixture(self) -> list[dict[str, Any]]:
        schema_map = load_schema_map(REPOSITORY_ROOT)
        return key_resolution_rows(schema_map, parse_planned_ddl(FIXTURE_DDL))

    def test_only_registered_resolved_columns_are_retyped(self) -> None:
        rows = self.rows_for_fixture()
        text, substitutions = reconcile_ddl(FIXTURE_DDL, rows)
        self.assertIn("CustomerKey BIGINT NOT NULL", text)
        self.assertIn("ObjectKey NVARCHAR(600) NOT NULL", text)
        self.assertEqual(1, len(substitutions))
        self.assertEqual("CustomerKey", substitutions[0]["column"])
        self.assertEqual("NVARCHAR(80)", substitutions[0]["from"])
        self.assertEqual("BIGINT", substitutions[0]["to"])
        self.assertEqual("app.Sample", substitutions[0]["table"])
        self.assertEqual("db_owner.BaseCustomers.Id", substitutions[0]["target"])

    def test_declaration_with_an_unexpected_type_is_never_rewritten(self) -> None:
        rows = self.rows_for_fixture()
        mutated = FIXTURE_DDL.replace("CustomerKey NVARCHAR(80)", "CustomerKey NVARCHAR(120)")
        text, substitutions = reconcile_ddl(mutated, rows)
        self.assertIn("CustomerKey NVARCHAR(120)", text)
        self.assertEqual([], substitutions)

    def test_rewrite_keeps_every_other_line_identical(self) -> None:
        rows = self.rows_for_fixture()
        text, _ = reconcile_ddl(FIXTURE_DDL, rows)
        original_lines = FIXTURE_DDL.splitlines()
        new_lines = text.splitlines()
        self.assertEqual(len(original_lines), len(new_lines))
        differences = [
            index
            for index, (before, after) in enumerate(zip(original_lines, new_lines))
            if before != after
        ]
        self.assertEqual(1, len(differences))

    def test_comments_are_removed_before_a_guard_inspects_a_statement(self) -> None:
        text = "CREATE TABLE app.X(Flag INT NOT NULL /* 0 delete, 1 drop */);"
        self.assertNotIn("delete", strip_sql_comments(text).lower())
        batches = split_batches(text)
        self.assertEqual([], batches[0]["destructive_tokens"])


class StaticGuardTests(unittest.TestCase):
    # The generated draft always starts with the review banner, so the fixtures carry one too.
    BANNER = "/*\nNOT APPROVED FOR EXECUTION - synthetic test fixture.\n*/\n"

    def rows(self) -> list[dict[str, Any]]:
        schema_map = load_schema_map(REPOSITORY_ROOT)
        return key_resolution_rows(schema_map, parse_planned_ddl(FIXTURE_DDL))

    def checks_for(self, text: str) -> dict[str, Any]:
        rows = self.rows()
        _, substitutions = reconcile_ddl(FIXTURE_DDL, rows)
        return static_checks(FIXTURE_DDL, self.BANNER + text, rows, substitutions)

    def test_clean_reconciled_fixture_passes_every_check(self) -> None:
        rows = self.rows()
        text, substitutions = reconcile_ddl(FIXTURE_DDL, rows)
        checks = static_checks(FIXTURE_DDL, self.BANNER + text, rows, substitutions)
        self.assertEqual("passed", checks["status"], checks["issues"])
        self.assertEqual(1, checks["create_table_count"])
        self.assertEqual(1, checks["substitution_count"])

    def test_destructive_statement_is_detected(self) -> None:
        poisoned = FIXTURE_DDL + "\nDROP TABLE app.Sample;\nGO\n"
        self.assertIn("no_destructive_statement", self.checks_for(poisoned)["issues"])

    def test_external_schema_reference_is_detected(self) -> None:
        poisoned = FIXTURE_DDL + "\nIF OBJECT_ID(N'app.T2', N'U') IS NULL SELECT 1 FROM db_owner.BaseCustomers;\nGO\n"
        self.assertIn("no_external_schema_reference", self.checks_for(poisoned)["issues"])

    def test_unguarded_create_is_detected(self) -> None:
        poisoned = FIXTURE_DDL + "\nCREATE TABLE app.T2(Id INT NOT NULL);\nGO\n"
        self.assertIn("every_create_batch_is_guarded", self.checks_for(poisoned)["issues"])

    def test_use_statement_is_detected(self) -> None:
        poisoned = "USE master;\nGO\n" + FIXTURE_DDL
        self.assertIn("no_database_switch", self.checks_for(poisoned)["issues"])

    def test_statement_guard_refuses_the_poisoned_batches(self) -> None:
        poisoned = FIXTURE_DDL + "\nDROP TABLE app.Sample;\nGO\n"
        guard = disposable_statement_guard(split_batches(poisoned))
        self.assertEqual("failed", guard["status"])
        self.assertGreaterEqual(guard["offending_count"], 1)


class FakeCursor:
    """Minimal cursor that records statements and answers only the app-object count query."""

    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self._row: tuple[int] | None = None

    def execute(self, statement: str) -> None:
        self.connection.executed.append(str(statement))
        if (
            self.connection.fail_on_execution is not None
            and len(self.connection.executed) == self.connection.fail_on_execution
        ):
            raise RuntimeError("simulated driver failure")
        self._row = None
        if str(statement).strip().upper().startswith("SELECT COUNT"):
            count = (
                self.connection.tables_after_rollback
                if self.connection.rolled_back
                else self.connection.tables_in_transaction
            )
            self._row = (count,)

    def fetchone(self) -> tuple[int] | None:
        return self._row


class FakeConnection:
    """Minimal connection that records commits, rollbacks and closures."""

    def __init__(
        self,
        tables_in_transaction: int = 5,
        tables_after_rollback: int = 0,
        fail_on_execution: int | None = None,
    ) -> None:
        self.executed: list[str] = []
        self.commits: list[bool] = []
        self.rolled_back = False
        self.closed = False
        self.tables_in_transaction = tables_in_transaction
        self.tables_after_rollback = tables_after_rollback
        self.fail_on_execution = fail_on_execution

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def rollback(self) -> None:
        self.rolled_back = True

    def commit(self) -> None:  # pragma: no cover - the compile path must never call this
        self.commits.append(True)

    def close(self) -> None:
        self.closed = True


class FakeDriverModule:
    """Stand-in for the optional ODBC driver module."""

    def __init__(
        self, connection: FakeConnection | None = None, error: Exception | None = None
    ) -> None:
        self.connection = connection
        self.error = error
        self.connect_calls: list[dict[str, Any]] = []

    def connect(self, target: str, autocommit: bool = True, timeout: int = 5) -> FakeConnection:
        self.connect_calls.append({"autocommit": autocommit, "timeout": timeout})
        if self.error is not None:
            raise self.error
        assert self.connection is not None
        return self.connection


class DisposableTargetGuardTests(unittest.TestCase):
    def test_local_scratch_target_is_accepted(self) -> None:
        built = build_disposable_target(
            ddl_reconciliation.DEFAULT_DISPOSABLE_INSTANCE,
            ddl_reconciliation.DEFAULT_DISPOSABLE_CATALOG,
            [SYNTHETIC_LOCALDB_DRIVER],
        )
        self.assertEqual(SYNTHETIC_LOCALDB_DRIVER, built["parts"]["driver"])
        guard = disposable_target_guard(built["parts"], SYNTHETIC_DECLARED_CONNECTION)
        self.assertTrue(guard["allowed"], guard["reasons"])
        self.assertEqual("localdb", guard["server_kind"])
        self.assertEqual("scratch_database", guard["catalog_kind"])
        self.assertFalse(guard["shares_declared_server"])
        self.assertFalse(guard["shares_declared_catalog"])
        self.assertFalse(guard["contains_declared_credential_material"])
        self.assertFalse(guard["connection_string_recorded"])

    def test_remote_server_is_refused(self) -> None:
        guard = disposable_target_guard(
            {"server": "shared-prod-server", "catalog": "tempdb", "driver": SYNTHETIC_LOCALDB_DRIVER},
            SYNTHETIC_DECLARED_CONNECTION,
        )
        self.assertFalse(guard["allowed"])
        self.assertEqual("not_disposable", guard["server_kind"])

    def test_shared_catalog_is_refused(self) -> None:
        guard = disposable_target_guard(
            {
                "server": "(localdb)\\MSSQLLocalDB",
                "catalog": "example-shared-catalog",
                "driver": SYNTHETIC_LOCALDB_DRIVER,
            },
            SYNTHETIC_DECLARED_CONNECTION,
        )
        self.assertFalse(guard["allowed"])
        self.assertTrue(guard["shares_declared_catalog"])
        self.assertEqual("not_disposable", guard["catalog_kind"])

    def test_declared_server_is_refused_even_on_a_local_instance(self) -> None:
        guard = disposable_target_guard(
            {
                "server": "(localdb)\\MSSQLLocalDB",
                "catalog": "tempdb",
                "driver": SYNTHETIC_LOCALDB_DRIVER,
            },
            "Server=(localdb)\\MSSQLLocalDB;Database=tempdb;Password=example-material",
        )
        self.assertFalse(guard["allowed"])
        self.assertTrue(guard["shares_declared_server"])
        self.assertTrue(guard["shares_declared_catalog"])

    def test_declared_credential_material_in_the_target_is_refused(self) -> None:
        guard = disposable_target_guard(
            {
                "server": "(localdb)\\example-material",
                "catalog": "tempdb",
                "driver": SYNTHETIC_LOCALDB_DRIVER,
            },
            SYNTHETIC_DECLARED_CONNECTION,
        )
        self.assertFalse(guard["allowed"])
        self.assertTrue(guard["contains_declared_credential_material"])

    def test_missing_driver_is_refused(self) -> None:
        guard = disposable_target_guard(
            {"server": "(localdb)\\MSSQLLocalDB", "catalog": "tempdb", "driver": None},
            SYNTHETIC_DECLARED_CONNECTION,
        )
        self.assertFalse(guard["allowed"])
        self.assertFalse(guard["driver_selected"])

    def test_target_guard_never_records_the_declared_value(self) -> None:
        guard = disposable_target_guard(
            {
                "server": "(localdb)\\MSSQLLocalDB",
                "catalog": "tempdb",
                "driver": SYNTHETIC_LOCALDB_DRIVER,
            },
            SYNTHETIC_DECLARED_CONNECTION,
        )
        rendered = json.dumps(guard)
        self.assertNotIn("example-material", rendered)
        self.assertNotIn("example-shared-server", rendered)


class DisposableCompileTests(unittest.TestCase):
    DRIVER_NAME = SYNTHETIC_LOCALDB_DRIVER

    def batches(self, text: str = FIXTURE_DDL) -> list[dict[str, Any]]:
        return split_batches(text)

    def test_compile_runs_twice_and_never_commits(self) -> None:
        connection = FakeConnection(tables_in_transaction=5, tables_after_rollback=0)
        module = FakeDriverModule(connection=connection)
        facts = run_disposable_compile(
            self.batches(), driver_module=module, odbc_target="target", login_timeout=7
        )
        self.assertEqual(COMPILE_STATUS_COMPILED, facts["status"])
        self.assertEqual(2, facts["passes_completed"])
        self.assertEqual(4, facts["batches_executed"])
        self.assertTrue(facts["transaction_rolled_back"])
        self.assertEqual(5, facts["tables_visible_in_transaction"])
        self.assertEqual(0, facts["tables_after_rollback"])
        self.assertTrue(facts["rollback_confirmed"])
        self.assertFalse(facts["commit_called"])
        self.assertEqual([], connection.commits)
        self.assertTrue(connection.closed)
        self.assertEqual([{"autocommit": False, "timeout": 7}], module.connect_calls)
        counted = [
            item for item in connection.executed if item.strip().upper().startswith("SELECT COUNT")
        ]
        self.assertEqual(2, len(counted))
        for statement in counted:
            self.assertEqual(COMPILE_APP_TABLE_COUNT_QUERY, statement.strip())

    def test_compile_without_the_driver_module_reports_engine_unavailable(self) -> None:
        facts = run_disposable_compile(self.batches(), driver_module=None, odbc_target="target")
        self.assertEqual(COMPILE_STATUS_ENGINE_UNAVAILABLE, facts["status"])
        self.assertFalse(facts["attempted"])
        self.assertEqual("driver_module_not_installed", facts["errors"][0]["category"])
        self.assertFalse(facts["errors"][0]["message_recorded"])

    def test_connect_failure_is_reported_without_message_text(self) -> None:
        module = FakeDriverModule(error=RuntimeError("simulated connection failure"))
        facts = run_disposable_compile(self.batches(), driver_module=module, odbc_target="target")
        self.assertEqual(COMPILE_STATUS_ENGINE_UNAVAILABLE, facts["status"])
        self.assertTrue(facts["attempted"])
        self.assertFalse(facts["errors"][0]["message_recorded"])
        self.assertNotIn("simulated connection failure", json.dumps(facts))

    def test_statement_failure_is_reported_without_text_and_still_rolls_back(self) -> None:
        connection = FakeConnection(fail_on_execution=2)
        module = FakeDriverModule(connection=connection)
        facts = run_disposable_compile(self.batches(), driver_module=module, odbc_target="target")
        self.assertEqual(COMPILE_STATUS_FAILED, facts["status"])
        self.assertFalse(facts["errors"][0]["message_recorded"])
        self.assertNotIn("simulated driver failure", json.dumps(facts))
        self.assertTrue(facts["transaction_rolled_back"])
        self.assertEqual([], connection.commits)

    def test_persisted_object_after_rollback_is_never_reported_as_confirmed(self) -> None:
        connection = FakeConnection(tables_in_transaction=5, tables_after_rollback=3)
        module = FakeDriverModule(connection=connection)
        facts = run_disposable_compile(self.batches(), driver_module=module, odbc_target="target")
        self.assertFalse(facts["rollback_confirmed"])

    def test_compile_check_refuses_a_poisoned_script_before_connecting(self) -> None:
        poisoned = FIXTURE_DDL + "\nDROP TABLE app.Sample;\nGO\n"
        connection = FakeConnection()
        module = FakeDriverModule(connection=connection)
        facts = disposable_compile_check(
            poisoned,
            driver_module=module,
            driver_names=[self.DRIVER_NAME],
            declared_value=SYNTHETIC_DECLARED_CONNECTION,
        )
        self.assertEqual(COMPILE_STATUS_GUARD_REFUSED, facts["status"])
        self.assertEqual([], module.connect_calls)
        self.assertEqual([], connection.executed)

    def test_compile_check_refuses_a_non_disposable_target_before_connecting(self) -> None:
        connection = FakeConnection()
        module = FakeDriverModule(connection=connection)
        facts = disposable_compile_check(
            FIXTURE_DDL,
            driver_module=module,
            driver_names=[self.DRIVER_NAME],
            declared_value=SYNTHETIC_DECLARED_CONNECTION,
            catalog="example-shared-catalog",
        )
        self.assertEqual(COMPILE_STATUS_TARGET_REFUSED, facts["status"])
        self.assertEqual([], module.connect_calls)

    def test_compile_check_reports_engine_unavailable_without_the_driver_module(self) -> None:
        facts = disposable_compile_check(
            FIXTURE_DDL,
            driver_module=None,
            driver_names=[self.DRIVER_NAME],
            declared_value=SYNTHETIC_DECLARED_CONNECTION,
            expected_table_count=1,
        )
        self.assertEqual(COMPILE_STATUS_ENGINE_UNAVAILABLE, facts["status"])
        self.assertFalse(facts["driver_module_available"])

    def test_compile_check_records_a_matching_table_inventory(self) -> None:
        connection = FakeConnection(tables_in_transaction=1, tables_after_rollback=0)
        module = FakeDriverModule(connection=connection)
        facts = disposable_compile_check(
            FIXTURE_DDL,
            driver_module=module,
            driver_names=[self.DRIVER_NAME],
            declared_value=SYNTHETIC_DECLARED_CONNECTION,
            expected_table_count=1,
        )
        self.assertEqual(COMPILE_STATUS_COMPILED, facts["status"])
        self.assertTrue(facts["expected_table_count_matched"])
        self.assertTrue(facts["idempotent_second_pass"])
        self.assertFalse(facts["shared_connection_used"])
        self.assertFalse(facts["applied_to_shared_database"])
        self.assertFalse(facts["target"]["connection_string_recorded"])

    def test_compile_check_fails_when_the_object_inventory_does_not_match(self) -> None:
        connection = FakeConnection(tables_in_transaction=9, tables_after_rollback=0)
        module = FakeDriverModule(connection=connection)
        facts = disposable_compile_check(
            FIXTURE_DDL,
            driver_module=module,
            driver_names=[self.DRIVER_NAME],
            declared_value=SYNTHETIC_DECLARED_CONNECTION,
            expected_table_count=1,
        )
        self.assertEqual(COMPILE_STATUS_FAILED, facts["status"])
        self.assertFalse(facts["expected_table_count_matched"])


class FactsAndReportTests(unittest.TestCase):
    def facts(self, compile_check: bool = False) -> tuple[dict[str, Any], tuple[str, ...]]:
        return collect_facts(
            REPOSITORY_ROOT,
            generated_at="2026-01-01T00:00:00Z",
            environ={"ERP_ConnectionStrings__Default": SYNTHETIC_DECLARED_CONNECTION},
            compile_check=compile_check,
            report_paths=[REPORT_RELATIVE_PATH],
            doc_paths=[DOC_RELATIVE_PATH],
            script_paths=[SCRIPT_RELATIVE_PATH],
        )

    def test_facts_never_carry_the_declared_value(self) -> None:
        facts, needles = self.facts()
        rendered = json.dumps({key: value for key, value in facts.items() if key != "draft_text"})
        self.assertTrue(needles)
        for needle in needles:
            self.assertNotIn(needle, rendered)
        self.assertFalse(facts["connection_diagnostic"]["declared_value_recorded"])
        self.assertFalse(facts["connection_diagnostic"]["shared_connection_used"])
        self.assertTrue(facts["connection_diagnostic"]["environment_file_read_only"])

    def test_offline_default_does_not_request_the_compile_check(self) -> None:
        facts, _ = self.facts()
        self.assertEqual(COMPILE_STATUS_NOT_REQUESTED, facts["compile_check"]["status"])
        self.assertFalse(facts["compile_check"]["requested"])

    def test_compile_check_runs_against_the_disposable_target_with_a_fake_driver(self) -> None:
        connection = FakeConnection(tables_in_transaction=20, tables_after_rollback=0)
        facts, _ = collect_facts(
            REPOSITORY_ROOT,
            generated_at="2026-01-01T00:00:00Z",
            environ={"ERP_ConnectionStrings__Default": SYNTHETIC_DECLARED_CONNECTION},
            compile_check=True,
            driver_module=FakeDriverModule(connection=connection),
            driver_facts={
                "module": "pyodbc",
                "available": True,
                "version": "synthetic",
                "odbc_driver_names": [SYNTHETIC_LOCALDB_DRIVER],
                "reason_category": None,
                "error_class": None,
                "interpreter": {"implementation": "CPython", "version": "0", "executable_name": "python"},
            },
            report_paths=[REPORT_RELATIVE_PATH],
            doc_paths=[DOC_RELATIVE_PATH],
            script_paths=[SCRIPT_RELATIVE_PATH],
        )
        self.assertEqual(COMPILE_STATUS_COMPILED, facts["compile_check"]["status"])
        self.assertTrue(facts["compile_check"]["expected_table_count_matched"])
        self.assertEqual(20, facts["compile_check"]["expected_table_count"])
        self.assertEqual([], connection.commits)
        self.assertFalse(facts["compile_check"]["shared_connection_used"])
        self.assertFalse(facts["compile_check"]["applied_to_shared_database"])

    def test_report_marks_every_criterion_and_stays_guard_clean(self) -> None:
        facts, needles = self.facts()
        report = build_report(facts)
        self.assertEqual(TASK_ID, report["task_id"])
        self.assertTrue(report["reconciled_draft"]["guard_facts"]["status"] == "passed")
        self.assertFalse(report["reconciled_draft"]["applied"])
        self.assertEqual(5, len(report["acceptance_evidence"]))
        self.assertEqual([], report["path_guard"]["protected_paths_touched"])
        self.assertTrue(report["path_guard"]["all_paths_accepted"])
        checks = ddl_reconciliation.artifact_checks(
            render_json(report),
            ddl_reconciliation.render_markdown(report),
            str(facts["draft_text"]),
            needles,
        )
        for key in (
            "report_credential_guard",
            "documentation_credential_guard",
            "draft_credential_guard",
            "scanner_self_check",
        ):
            with self.subTest(key=key):
                self.assertEqual("passed", checks[key]["status"], checks[key].get("findings"))

    def test_publication_blocked_reports_a_failed_guard(self) -> None:
        self.assertIsNone(publication_blocked({"artifact_checks": {}}))
        blocked = publication_blocked(
            {"artifact_checks": {"scanner_self_check": {"status": "failed", "findings_count": 2}}}
        )
        self.assertIsNotNone(blocked)


class CommittedArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        cls.report_text = REPORT_PATH.read_text(encoding="utf-8")
        cls.doc_text = DOC_PATH.read_text(encoding="utf-8")
        cls.draft_text = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_artifacts_exist_and_identify_the_task(self) -> None:
        self.assertTrue(REPORT_PATH.is_file())
        self.assertTrue(DOC_PATH.is_file())
        self.assertTrue(SCRIPT_PATH.is_file())
        self.assertEqual(TASK_ID, self.report["task_id"])
        self.assertEqual(["NEWAPP-003"], self.report["task_depends_on"])

    def test_report_is_guard_clean_and_records_the_verification(self) -> None:
        self.assertTrue(self.report["artifact_checks_verified"])
        self.assertEqual("evidence_collected", self.report["status"])
        for entry in self.report["acceptance_evidence"]:
            with self.subTest(criterion=entry["criterion"][:40]):
                self.assertTrue(entry["satisfied"], entry["evidence"])
        checks = self.report["artifact_checks"]
        for key in (
            "report_credential_guard",
            "documentation_credential_guard",
            "draft_credential_guard",
            "scanner_self_check",
        ):
            with self.subTest(key=key):
                self.assertEqual("passed", checks[key]["status"])
        self.assertTrue(self.report["path_guard"]["all_paths_accepted"])
        self.assertEqual([], self.report["path_guard"]["protected_paths_touched"])

    def test_report_never_records_the_declared_value(self) -> None:
        declared, source = newerp_schema.resolve_connection_value(REPOSITORY_ROOT / ".env")
        diagnostic = self.report["shared_connection_diagnostic"]
        self.assertFalse(diagnostic["declared_value_recorded"])
        self.assertFalse(diagnostic["shared_connection_used"])
        self.assertFalse(self.report["safety_contract"]["shared_connection_used"])
        self.assertFalse(self.report["safety_contract"]["ddl_or_dml_executed_against_shared_database"])
        self.assertTrue(self.report["safety_contract"]["secrets_read_into_memory_only"])
        self.assertTrue(source)
        if declared:
            for text in (self.report_text, self.doc_text, self.draft_text):
                self.assertNotIn(declared, text)

    def test_committed_draft_is_identical_to_the_recorded_digest(self) -> None:
        self.assertEqual(
            self.report["reconciled_draft"]["sha256"],
            ddl_reconciliation.sha256_text(self.draft_text),
        )

    def test_committed_draft_matches_the_planned_contract_and_stays_additive(self) -> None:
        contract_text = DDL_PATH.read_text(encoding="utf-8-sig")
        rows = key_resolution_rows(
            load_schema_map(REPOSITORY_ROOT), parse_planned_ddl(contract_text)
        )
        _, substitutions = reconcile_ddl(contract_text, rows)
        checks = static_checks(contract_text, self.draft_text, rows, substitutions)
        self.assertEqual("passed", checks["status"], checks["issues"])
        self.assertEqual([], checks["destructive_batches"])
        self.assertEqual([], checks["external_schema_batches"])
        self.assertTrue(all(check["passed"] for check in checks["checks"]))
        self.assertGreater(checks["create_table_count"], 0)
        self.assertEqual(len(substitutions), checks["substitution_count"])

    def test_committed_draft_carries_the_review_banner(self) -> None:
        self.assertTrue(self.draft_text.startswith("/*"))
        self.assertIn("NOT APPROVED FOR EXECUTION", self.draft_text)
        self.assertIn(self.report["source_contracts"]["planned_ddl"]["sha256"], self.draft_text)

    def test_committed_document_has_the_plan_and_the_rollback_notes(self) -> None:
        for heading in (
            "## 1. Authority of record",
            "## 4. Neutral key reconciliation",
            "## 6. Generated reconciled draft",
            "## 7. Migration plan",
            "## 8. Rollback notes",
            "## 9. Disposable compile check",
            "## 10. Human Gate boundary",
            "## 11. Known limits",
            "## 12. Unresolved items",
            "## 13. Acceptance evidence",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.doc_text)
        self.assertIn(REPORT_RELATIVE_PATH, self.doc_text)
        self.assertIn(SCRIPT_RELATIVE_PATH, self.doc_text)

    def test_committed_report_classifies_every_contract_key(self) -> None:
        declared = set(parse_planned_ddl(DDL_PATH.read_text(encoding="utf-8-sig"))["declarations"])
        classified = {str(row["neutral_key"]) for row in self.report["reconciliation"]["rows"]}
        self.assertLessEqual(declared, classified)
        self.assertFalse(self.report["human_gate"]["applied_by_this_task"])
        self.assertFalse(self.report["human_gate"]["foreign_key_to_shared_table_generated"])
        self.assertFalse(self.report["human_gate"]["duplicate_master_table_created"])

    def test_committed_report_records_an_explicit_resolution_per_key(self) -> None:
        allowed = {
            "resolved_direct",
            "type_resolved_target_needs_review",
            "app_local",
            "unresolved_human_gate",
        }
        for row in self.report["reconciliation"]["rows"]:
            with self.subTest(key=row["neutral_key"]):
                self.assertIn(row["resolution"], allowed)
                self.assertTrue(row["reason"])
                if row["resolution"] in {"unresolved_human_gate", "app_local"}:
                    self.assertFalse(row["raised_to_shared_type"])

    def test_new_tracked_candidates_pass_the_repository_scanner_content_rules(self) -> None:
        module_text = Path(ddl_reconciliation.__file__).read_text(encoding="utf-8")
        test_text = Path(__file__).read_text(encoding="utf-8")
        for label, text in (
            (REPORT_RELATIVE_PATH, self.report_text),
            (DOC_RELATIVE_PATH, self.doc_text),
            (SCRIPT_RELATIVE_PATH, self.draft_text),
            (ddl_reconciliation.MODULE_RELATIVE_PATH, module_text),
            ("tests/schema/test_ddl_reconciliation.py", test_text),
        ):
            with self.subTest(label=label):
                findings = newerp_schema.scanner_self_check({label: text})
                self.assertEqual("passed", findings["status"], findings["findings"])

    def test_every_recorded_path_is_accepted_by_the_controller_policy(self) -> None:
        view = newerp_schema.path_guard_compatibility(
            list(ddl_reconciliation.EXECUTOR_PATHS),
            CONTROLLER_ALLOWED_PATTERNS,
            CONTROLLER_PROTECTED_PATTERNS,
            "test mirror",
        )
        self.assertTrue(view["all_paths_accepted"], view["paths"])
        self.assertEqual([], view["protected_paths_touched"])


class CommandLineTests(unittest.TestCase):
    def test_dry_run_prints_a_summary_and_writes_nothing(self) -> None:
        before = {path: path.stat().st_mtime_ns for path in (REPORT_PATH, DOC_PATH, SCRIPT_PATH)}
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main([])
        self.assertEqual(0, code)
        summary = json.loads(buffer.getvalue())
        self.assertEqual(TASK_ID, summary["task_id"])
        self.assertFalse(summary["write"])
        self.assertEqual([], summary["artifacts_written"])
        after = {path: path.stat().st_mtime_ns for path in (REPORT_PATH, DOC_PATH, SCRIPT_PATH)}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
