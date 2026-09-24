"""Unit tests for the NEWAPP-003 read-only shared-schema inspection utilities.

Every test runs offline: the optional ODBC driver module and the database connection are replaced by
fakes inside the tests, so no test opens a socket, touches the shared server or executes SQL. Only
the read-only checks that inspect the real checkout (the declared setting *name*, the controller
pattern lists and the committed artifacts) read repository files. No test records, prints, compares or
hashes a declared value, and the synthetic fixtures use placeholder-shaped values so this tracked test
file can never trip the scanner it collaborates with.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

SCHEMA_DIR = Path(__file__).resolve().parent
if str(SCHEMA_DIR) not in sys.path:
    sys.path.insert(0, str(SCHEMA_DIR))

import newerp_schema  # noqa: E402  (module handle for constant patching)
from newerp_schema import (  # noqa: E402
    CATALOG_QUERIES,
    CONNECTION_KEY,
    DECLARATION_PATTERN,
    DOC_RELATIVE_PATH,
    DOMAIN_ORDER,
    ENV_FILE,
    MASTER_DOMAINS,
    MAX_COLUMNS_PER_TABLE,
    REPORT_RELATIVE_PATH,
    SCANNER_RELATIVE_PATH,
    TASK_ID,
    UnsafeStatementError,
    artifact_checks,
    build_odbc_target,
    build_report,
    classify_connection_error,
    classify_table,
    collect_facts,
    credential_leak_guard,
    credential_needles,
    execute_read_only,
    finalize_report,
    load_ddl_inventory,
    main,
    normalize_for_path_guard,
    open_read_only_connection,
    path_guard_compatibility,
    publication_blocked,
    render_json,
    resolve_connection_value,
    scanner_self_check,
    shape_metadata,
    statement_is_read_only,
    tokenize_identifier,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPOSITORY_ROOT / REPORT_RELATIVE_PATH
DOC_PATH = REPOSITORY_ROOT / DOC_RELATIVE_PATH
CONTROLLER_COMMON = REPOSITORY_ROOT / ".ai" / "controller" / "common.py"

# Mirror of the controller policy in .ai/agent_config.yaml (paths.executor_allowed / paths.protected).
# The tests compare the module path guard against these patterns; the controller file is only ever
# read, never written, by the executor.
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
    "tests/schema/__init__.py",
    "tests/schema/newerp_schema.py",
    "tests/schema/test_newerp_schema.py",
)

# Placeholder-shaped synthetic declaration. No real credential value is used or needed by these tests.
SYNTHETIC_CONNECTION = (
    "Server=example-server;Database=example-database;User Id=example-user;"
    "Password=example-material;TrustServerCertificate=True;"
    "MultipleActiveResultSets=True;Connect Timeout=15"
)
SYNTHETIC_ENV = (
    "# synthetic declaration fixture for NEWAPP-003 tests\n"
    f'export {CONNECTION_KEY}="{SYNTHETIC_CONNECTION}"\n'
    "ERP_Oss__Bucket=example-bucket\n"
)
FAKE_DRIVER_NAMES = ("ODBC Driver 17 for SQL Server",)
DDL_FIXTURE = (
    "CREATE TABLE app.CustomerExt(CustomerKey int NOT NULL, TenantId int NOT NULL);\n"
    "-- PRIMARY KEY stays untracked here, but CustomerKey and TenantId do not\n"
    "CREATE TABLE app.UserMobileProfile(UserKey int NOT NULL, CreatedByUserKey int NULL);\n"
    "CREATE TABLE app.InquiryTrip(SupplierKey int NOT NULL, InquirerUserKey int NULL);\n"
)

QUERY_MARKERS: tuple[tuple[str, str], ...] = (
    ("engine", "serverproperty"),
    ("catalog", "db_name"),
    ("schemas", "from sys.schemas"),
    ("tables", "from sys.tables"),
    ("columns", "from sys.columns"),
    ("key_constraints", "sys.key_constraints"),
    ("foreign_keys", "sys.foreign_keys"),
    ("indexes", "from sys.indexes"),
)


def query_name(statement: str) -> str:
    """Return the catalog read a fake connection should answer for one statement."""
    lowered = statement.lower()
    for name, marker in QUERY_MARKERS:
        if marker in lowered:
            return name
    return "unknown"


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self.rows: list[tuple[Any, ...]] = []
        self.closed = False

    def execute(self, statement: str) -> None:
        self.connection.statements.append(statement)
        name = query_name(statement)
        if self.connection.fail_on == name:
            raise RuntimeError("synthetic catalog failure")
        self.rows = [tuple(row) for row in self.connection.results.get(name, [])]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self.rows)

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    """Read-only stand-in for a driver connection: canned rows, recorded statements."""

    def __init__(
        self,
        results: dict[str, list[tuple[Any, ...]]] | None = None,
        *,
        fail_on: str | None = None,
    ) -> None:
        self.results = dict(results or {})
        self.fail_on = fail_on
        self.statements: list[str] = []
        self.cursors: list[FakeCursor] = []
        self.closed = False

    def cursor(self) -> FakeCursor:
        cursor = FakeCursor(self)
        self.cursors.append(cursor)
        return cursor

    def close(self) -> None:
        self.closed = True


class FakeDriverError(Exception):
    """Stand-in for a driver error that carries a SQLSTATE plus a free-text message."""


class FakeDriverModule:
    """Stand-in for the optional pyodbc module."""

    version = "0.0-test"

    def __init__(
        self,
        *,
        driver_names: tuple[str, ...] = FAKE_DRIVER_NAMES,
        connection: Any = None,
        error: BaseException | None = None,
    ) -> None:
        self._driver_names = list(driver_names)
        self._connection = connection
        self._error = error
        self.targets: list[str] = []
        self.kwargs: list[dict[str, Any]] = []

    def drivers(self) -> list[str]:
        return list(self._driver_names)

    def connect(self, target: str, **kwargs: Any) -> Any:
        self.targets.append(target)
        self.kwargs.append(dict(kwargs))
        if self._error is not None:
            raise self._error
        return self._connection


def write_text(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def populate_root(
    root: Path, *, env_text: str | None = SYNTHETIC_ENV, ddl_text: str | None = DDL_FIXTURE
) -> Path:
    """Fill a disposable root with a synthetic declaration, controller policy and planned DDL."""
    if env_text is not None:
        write_text(root, ENV_FILE, env_text)
    if ddl_text is not None:
        write_text(root, "docs/NEWAPP_Database_DDL_V1.sql", ddl_text)
    write_text(
        root,
        ".ai/agent_config.yaml",
        json.dumps(
            {
                "paths": {
                    "executor_allowed": list(CONTROLLER_ALLOWED_PATTERNS),
                    "protected": list(CONTROLLER_PROTECTED_PATTERNS),
                }
            }
        ),
    )
    return root


@contextlib.contextmanager
def disposable_root(**kwargs: Any) -> Any:
    """Yield a populated disposable repository root."""
    with tempfile.TemporaryDirectory() as temporary:
        yield populate_root(Path(temporary), **kwargs)


def catalog_results(**overrides: Any) -> dict[str, list[tuple[Any, ...]]]:
    """Canned catalog rows for the offline happy path."""
    results: dict[str, list[tuple[Any, ...]]] = {
        "engine": [("16.0.1000.6", "Developer Edition", "Chinese_PRC_CI_AS")],
        "catalog": [("NEWERP_TESTCATALOG", "Chinese_PRC_CI_AS")],
        "schemas": [("app", 5), ("dbo", 1)],
        "tables": [
            ("dbo", "CustomerMaster", "USER_TABLE", 0),
            ("dbo", "SupplierMaster", "USER_TABLE", 0),
            ("dbo", "SysUser", "USER_TABLE", 0),
            ("dbo", "CompanyInfo", "USER_TABLE", 0),
            ("dbo", "CurrencyLookup", "USER_TABLE", 0),
            ("dbo", "InquiryTrip", "USER_TABLE", 0),
            ("dbo", "dtproperties", "USER_TABLE", 1),
        ],
        "columns": [
            ("dbo", "CustomerMaster", 1, "CustomerId", "int", 4, 10, 0, 0, 1, 0, 0, 0, 0, 0),
            ("dbo", "CustomerMaster", 2, "CustomerCode", "nvarchar", 40, 0, 0, 0, 0, 0, 0, 0, 0, 0),
            ("dbo", "CustomerMaster", 3, "RowStamp", "timestamp", 8, 0, 0, 1, 0, 0, 1, 0, 0, 0),
            ("dbo", "SupplierMaster", 1, "SupplierId", "int", 4, 10, 0, 0, 1, 0, 0, 0, 0, 0),
            ("dbo", "SysUser", 1, "UserId", "int", 4, 10, 0, 0, 1, 0, 0, 0, 0, 0),
            ("dbo", "CompanyInfo", 1, "CompanyId", "int", 4, 10, 0, 0, 1, 0, 0, 0, 0, 0),
            ("dbo", "CurrencyLookup", 1, "CurrencyCode", "nvarchar", 6, 0, 0, 0, 0, 0, 0, 0, 0, 0),
            ("dbo", "InquiryTrip", 1, "InquiryTripId", "int", 4, 10, 0, 0, 1, 0, 0, 0, 0, 0),
            ("dbo", "InquiryTrip", 2, "SupplierId", "int", 4, 10, 0, 1, 0, 0, 0, 0, 0, 0),
        ],
        "key_constraints": [
            (
                "dbo",
                "CustomerMaster",
                "PK_CustomerMaster",
                "PRIMARY_KEY_CONSTRAINT",
                "CustomerId",
                1,
                0,
            ),
            ("dbo", "InquiryTrip", "PK_InquiryTrip", "PRIMARY_KEY_CONSTRAINT", "InquiryTripId", 1, 0),
            ("dbo", "InquiryTrip", "UQ_InquiryTrip", "UNIQUE_CONSTRAINT", "SupplierId", 1, 0),
        ],
        "foreign_keys": [
            (
                "FK_InquiryTrip_Supplier",
                "dbo",
                "InquiryTrip",
                "SupplierId",
                "dbo",
                "SupplierMaster",
                "SupplierId",
                1,
            )
        ],
        "indexes": [
            (
                "dbo",
                "InquiryTrip",
                "IX_InquiryTrip_Supplier",
                "NONCLUSTERED",
                0,
                0,
                0,
                "SupplierId",
                1,
                0,
            ),
            (
                "dbo",
                "InquiryTrip",
                "PK_InquiryTrip",
                "CLUSTERED",
                1,
                1,
                0,
                "InquiryTripId",
                1,
                0,
            ),
        ],
    }
    results.update(overrides)
    return results


class StatementGuardTests(unittest.TestCase):
    UNSAFE_STATEMENTS = (
        "DROP TABLE dbo.Customer",
        "TRUNCATE TABLE dbo.Customer",
        "ALTER TABLE dbo.Customer ADD LegacyFlag bit NULL",
        "CREATE TABLE dbo.Scratch(Id int)",
        "INSERT INTO dbo.Customer(CustomerId) VALUES (1)",
        "UPDATE dbo.Customer SET CustomerCode = 2",
        "DELETE FROM dbo.Customer",
        "MERGE dbo.Customer AS target USING dbo.Other AS source ON 1 = 1 WHEN MATCHED THEN DELETE",
        "EXEC sp_who",
        "EXECUTE dbo.SomeProcedure 1",
        "GRANT SELECT ON dbo.Customer TO public",
        "REVOKE SELECT ON dbo.Customer FROM public",
        "DENY SELECT ON dbo.Customer TO public",
        "BACKUP DATABASE NEWERP TO DISK = 'none'",
        "RESTORE DATABASE NEWERP FROM DISK = 'none'",
        "SELECT * INTO dbo.Scratch FROM dbo.Customer",
        "SELECT * FROM OPENROWSET('SQLNCLI', 'x', 'SELECT 1')",
        "SELECT * FROM OPENQUERY(linked_server, 'SELECT 1')",
        "DBCC CHECKDB",
        "WAITFOR DELAY '00:00:05'",
        "SELECT 1; DROP TABLE dbo.Customer",
        "SELECT 1; SELECT 2",
        "SELECT 1 -- trailing comment",
        "SELECT 1 /* block comment */",
        "SELECT 1\nGO\nSELECT 2",
    )

    def test_every_catalog_statement_is_a_single_read_only_select(self) -> None:
        for name, statement in CATALOG_QUERIES:
            with self.subTest(name=name):
                accepted, reason = statement_is_read_only(statement)
                self.assertTrue(accepted, reason)
                self.assertEqual(statement, newerp_schema.normalize_statement(statement))
                self.assertNotIn(";", statement)

    def test_catalog_statement_names_cover_every_reported_read(self) -> None:
        names = [name for name, _ in CATALOG_QUERIES]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(
            {
                "engine",
                "catalog",
                "schemas",
                "tables",
                "columns",
                "key_constraints",
                "foreign_keys",
                "indexes",
            },
            set(names),
        )

    def test_ddl_dml_and_administrative_statements_are_refused(self) -> None:
        for statement in self.UNSAFE_STATEMENTS:
            with self.subTest(statement=statement.splitlines()[0]):
                accepted, reason = statement_is_read_only(statement)
                self.assertFalse(accepted)
                self.assertTrue(reason)

    def test_refusal_never_echoes_the_statement(self) -> None:
        with self.assertRaises(UnsafeStatementError) as context:
            newerp_schema.assert_read_only("DROP TABLE dbo.SecretCustomerTable")
        self.assertNotIn("SecretCustomerTable", str(context.exception))

    def test_plain_select_and_trailing_terminator_are_accepted(self) -> None:
        accepted, reason = statement_is_read_only("SELECT 1;")
        self.assertTrue(accepted, reason)
        self.assertEqual("SELECT 1", newerp_schema.normalize_statement("SELECT 1;"))

    def test_empty_statement_and_common_table_expression_are_refused(self) -> None:
        for statement in ("", "   ", "WITH source AS (SELECT 1) SELECT * FROM source"):
            with self.subTest(statement=statement):
                accepted, reason = statement_is_read_only(statement)
                self.assertFalse(accepted)
                self.assertTrue(reason)


class ConnectionTargetTests(unittest.TestCase):
    def facts_text(self, facts: dict[str, Any]) -> str:
        return json.dumps(facts, ensure_ascii=False, sort_keys=True)

    def test_declaration_is_translated_into_an_odbc_target(self) -> None:
        built = build_odbc_target(SYNTHETIC_CONNECTION, FAKE_DRIVER_NAMES)
        facts = built["facts"]
        target = built["target"] or ""
        self.assertEqual("ODBC Driver 17 for SQL Server", facts["selected_driver"])
        self.assertFalse(facts["declares_odbc_driver"])
        self.assertTrue(facts["read_only_intent_requested"])
        self.assertTrue(target.startswith(";Driver={ODBC Driver 17 for SQL Server};"))
        self.assertIn("ApplicationIntent=ReadOnly", target)
        self.assertIn("UID=", target)
        self.assertIn("PWD=", target)
        self.assertIn("TrustServerCertificate=yes", target)
        self.assertNotIn("MultipleActiveResultSets", target)
        self.assertNotIn("Connect Timeout", target)

    def test_keyword_names_are_reported_without_values(self) -> None:
        facts = build_odbc_target(SYNTHETIC_CONNECTION, FAKE_DRIVER_NAMES)["facts"]
        self.assertEqual(
            ["Server", "Database", "User Id", "Password", "TrustServerCertificate"],
            facts["keyword_names"],
        )
        self.assertEqual(
            ["MultipleActiveResultSets", "Connect Timeout"], facts["non_odbc_keyword_names"]
        )
        self.assertTrue(facts["has_server_keyword"])
        self.assertTrue(facts["has_catalog_keyword"])
        self.assertTrue(facts["has_user_keyword"])
        self.assertTrue(facts["has_password_keyword"])
        self.assertFalse(facts["uses_integrated_security"])
        text = self.facts_text(facts)
        for value in ("example-server", "example-database", "example-user", "example-material"):
            self.assertNotIn(value, text)

    def test_integrated_security_and_data_source_aliases_are_translated(self) -> None:
        declaration = (
            "Data Source=example-server;Initial Catalog=example-database;"
            "Integrated Security=SSPI;Encrypt=False"
        )
        built = build_odbc_target(declaration, FAKE_DRIVER_NAMES)
        facts = built["facts"]
        target = built["target"] or ""
        self.assertTrue(facts["uses_integrated_security"])
        self.assertIn("Trusted_Connection=yes", target)
        self.assertIn("Encrypt=no", target)
        self.assertIn("Server=example-server", target)
        self.assertIn("Database=example-database", target)

    def test_declared_driver_wins_and_legacy_driver_skips_the_intent(self) -> None:
        built = build_odbc_target(f"Driver={{SQL Server}};{SYNTHETIC_CONNECTION}", FAKE_DRIVER_NAMES)
        self.assertEqual("SQL Server", built["facts"]["selected_driver"])
        self.assertTrue(built["facts"]["declares_odbc_driver"])
        self.assertFalse(built["facts"]["read_only_intent_requested"])
        self.assertNotIn("ApplicationIntent", built["target"] or "")

    def test_missing_odbc_driver_is_reported_without_connecting(self) -> None:
        driver = FakeDriverModule(driver_names=(), connection=FakeConnection())
        opened = open_read_only_connection(SYNTHETIC_CONNECTION, driver_module=driver)
        self.assertEqual("unavailable", opened["status"])
        self.assertFalse(opened["facts"]["attempted"])
        self.assertEqual("odbc_driver_not_installed", opened["facts"]["error"]["category"])
        self.assertEqual([], driver.targets)

    def test_credential_needles_cover_the_declaration_and_its_parts(self) -> None:
        needles = credential_needles(SYNTHETIC_CONNECTION)
        for expected in (
            SYNTHETIC_CONNECTION,
            "example-server",
            "example-user",
            "example-material",
        ):
            self.assertIn(expected, needles)
        self.assertEqual((), credential_needles(""))
        self.assertNotIn("abc", credential_needles("Password=abc"))


class ConnectionAttemptTests(unittest.TestCase):
    def test_connected_session_is_autocommit_with_a_bounded_timeout(self) -> None:
        connection = FakeConnection()
        driver = FakeDriverModule(connection=connection)
        opened = open_read_only_connection(
            SYNTHETIC_CONNECTION, driver_module=driver, login_timeout=7
        )
        self.assertEqual("connected", opened["status"])
        self.assertIs(connection, opened["connection"])
        self.assertEqual([{"autocommit": True, "timeout": 7}], driver.kwargs)
        self.assertEqual(1, len(driver.targets))
        self.assertIn("Driver={ODBC Driver 17 for SQL Server}", driver.targets[0])
        self.assertTrue(opened["facts"]["attempted"])
        self.assertTrue(opened["facts"]["autocommit"])
        self.assertFalse(opened["facts"]["transaction_left_open"])
        self.assertIsNone(opened["facts"]["error"])

    def test_login_failure_is_reported_by_category_without_the_message(self) -> None:
        error = FakeDriverError("28000", "Login failed for user example-user")
        driver = FakeDriverModule(error=error)
        opened = open_read_only_connection(SYNTHETIC_CONNECTION, driver_module=driver)
        self.assertEqual("unavailable", opened["status"])
        record = opened["facts"]["error"]
        self.assertEqual("FakeDriverError", record["error_class"])
        self.assertEqual("28000", record["sqlstate"])
        self.assertEqual("login_failed_or_not_authenticated", record["category"])
        self.assertFalse(record["message_recorded"])
        self.assertNotIn("Login failed", json.dumps(opened["facts"]))

    def test_free_text_first_argument_is_not_read_as_a_sqlstate(self) -> None:
        driver = FakeDriverModule(error=FakeDriverError("connection attempt failed for example-server"))
        opened = open_read_only_connection(SYNTHETIC_CONNECTION, driver_module=driver)
        record = opened["facts"]["error"]
        self.assertEqual("not_reported", record["sqlstate"])
        self.assertEqual("unclassified_driver_error", record["category"])
        self.assertNotIn("example-server", json.dumps(opened["facts"]))

    def test_sqlstate_categories_cover_transport_timeout_and_driver_failures(self) -> None:
        expectations = {
            "08001": "server_unreachable",
            "08S01": "network_or_transport_failure",
            "HYT00": "login_timeout",
            "IM002": "odbc_driver_or_data_source_not_found",
            "42000": "statement_or_permission_denied",
            "18456": "login_failed",
        }
        for sqlstate, category in expectations.items():
            with self.subTest(sqlstate=sqlstate):
                record = classify_connection_error(FakeDriverError(sqlstate, "text"))
                self.assertEqual(category, record["category"])

    def test_missing_driver_module_skips_the_attempt(self) -> None:
        opened = open_read_only_connection(SYNTHETIC_CONNECTION, driver_module=None)
        self.assertEqual("unavailable", opened["status"])
        self.assertFalse(opened["facts"]["attempted"])
        self.assertEqual("driver_module_not_installed", opened["facts"]["error"]["category"])

    def test_unusable_declaration_skips_the_attempt(self) -> None:
        driver = FakeDriverModule(connection=FakeConnection())
        opened = open_read_only_connection("not-a-connection-declaration", driver_module=driver)
        self.assertEqual("unavailable", opened["status"])
        self.assertFalse(opened["facts"]["attempted"])
        self.assertEqual("connection_string_not_usable", opened["facts"]["error"]["category"])
        self.assertEqual([], driver.targets)

    def test_declaration_with_only_droppable_keywords_is_not_usable(self) -> None:
        built = build_odbc_target("Connect Timeout=15;Pooling=True", FAKE_DRIVER_NAMES)
        self.assertIsNone(built["target"])
        self.assertEqual(0, built["facts"]["keyword_fragment_count"])
        self.assertEqual(["Connect Timeout", "Pooling"], built["facts"]["non_odbc_keyword_names"])


class MetadataInspectionTests(unittest.TestCase):
    def inspected(self) -> tuple[FakeConnection, dict[str, Any]]:
        connection = FakeConnection(catalog_results())
        driver = FakeDriverModule(connection=connection)
        opened = open_read_only_connection(SYNTHETIC_CONNECTION, driver_module=driver)
        self.assertEqual("connected", opened["status"])
        return connection, newerp_schema.inspect_metadata(connection)

    def test_catalog_reads_shape_tables_keys_indexes_and_concurrency(self) -> None:
        _, catalog = self.inspected()
        self.assertEqual("NEWERP_TESTCATALOG", catalog["database"]["name"])
        self.assertEqual("16.0.1000.6", catalog["engine"]["version"])
        self.assertEqual(6, catalog["table_count"])
        self.assertEqual(1, catalog["tables_skipped_ms_shipped"])
        self.assertEqual(2, catalog["schema_count"])
        self.assertEqual(3, catalog["key_constraint_count"])
        self.assertEqual(1, catalog["foreign_key_count"])
        self.assertEqual(2, catalog["index_count"])
        self.assertEqual(8, catalog["executed_statement_count"])
        self.assertEqual(8, catalog["read_only_guard_checks"])
        self.assertEqual(0, catalog["statements_outside_catalog"])

        customer = next(
            entry for entry in catalog["tables"] if entry["qualified_name"] == "dbo.CustomerMaster"
        )
        self.assertTrue(customer["detailed"])
        self.assertEqual("customer", customer["classification"]["domain"])
        self.assertTrue(customer["classification"]["strong_candidate"])
        self.assertEqual("PK_CustomerMaster", customer["primary_key"]["name"])
        self.assertEqual(["CustomerId"], customer["primary_key"]["columns"])
        self.assertEqual(
            [{"name": "RowStamp", "data_type": "timestamp", "role": "rowversion"}],
            customer["concurrency_columns"],
        )
        self.assertEqual(["dbo.CustomerMaster"], catalog["concurrency"]["tables_with_rowversion"])

    def test_inquiry_keys_indexes_and_foreign_keys_are_captured(self) -> None:
        _, catalog = self.inspected()
        inquiry = next(
            entry for entry in catalog["tables"] if entry["qualified_name"] == "dbo.InquiryTrip"
        )
        self.assertTrue(inquiry["detailed"])
        self.assertEqual(["InquiryTripId"], inquiry["primary_key"]["columns"])
        self.assertEqual(["UQ_InquiryTrip"], [item["name"] for item in inquiry["unique_constraints"]])
        self.assertEqual(
            ["FK_InquiryTrip_Supplier"], [item["name"] for item in inquiry["foreign_keys_out"]]
        )
        self.assertEqual("dbo.SupplierMaster", inquiry["foreign_keys_out"][0]["referenced_table"])
        self.assertEqual(
            ["IX_InquiryTrip_Supplier", "PK_InquiryTrip"],
            [item["name"] for item in inquiry["indexes"]],
        )

    def test_domain_map_resolves_the_fixture_domains(self) -> None:
        _, catalog = self.inspected()
        for domain in DOMAIN_ORDER:
            with self.subTest(domain=domain):
                entry = catalog["domain_map"][domain]
                self.assertTrue(entry["resolved"], domain)
                self.assertEqual("resolved", entry["status"])
                self.assertTrue(entry["answered"])
                self.assertGreaterEqual(entry["strong_candidate_count"], 1)
        for domain in MASTER_DOMAINS:
            self.assertTrue(catalog["domain_map"][domain]["monitor_domain"])

    def test_a_domain_without_any_candidate_is_reported_as_absent(self) -> None:
        tables = [row for row in catalog_results()["tables"] if row[1] != "CompanyInfo"]
        columns = [row for row in catalog_results()["columns"] if row[1] != "CompanyInfo"]
        catalog = shape_metadata(catalog_results(tables=tables, columns=columns))
        entry = catalog["domain_map"]["organization"]
        self.assertEqual("absent_from_catalog", entry["status"])
        self.assertFalse(entry["resolved"])
        self.assertTrue(entry["answered"])
        self.assertEqual([], entry["candidate_tables"])

    def test_unclassified_master_hint_tables_are_listed_separately(self) -> None:
        tables = [
            *catalog_results()["tables"],
            ("dbo", "BaseOtherInfos", "USER_TABLE", 0),
            ("dbo", "SalesOrders", "USER_TABLE", 0),
        ]
        catalog = shape_metadata(catalog_results(tables=tables))
        self.assertEqual(["dbo.BaseOtherInfos"], catalog["unclassified_master_hint_tables"])
        entry = next(
            item for item in catalog["tables"] if item["qualified_name"] == "dbo.BaseOtherInfos"
        )
        self.assertTrue(entry["detailed"])
        self.assertIsNone(entry["classification"]["domain"])

    def test_domain_candidate_tables_are_recorded_with_full_detail(self) -> None:
        catalog = shape_metadata(catalog_results())
        for domain in ("dictionary", "inquiry"):
            with self.subTest(domain=domain):
                candidates = set(catalog["domain_map"][domain]["candidate_tables"])
                detailed = {
                    entry["qualified_name"] for entry in catalog["tables"] if entry["detailed"]
                }
                self.assertTrue(candidates)
                self.assertTrue(candidates <= detailed)

    def test_only_catalog_statements_are_executed_and_cursors_are_closed(self) -> None:
        connection, _ = self.inspected()
        catalog_statements = [statement for _, statement in CATALOG_QUERIES]
        self.assertEqual(catalog_statements, connection.statements)
        self.assertEqual(len(catalog_statements), len(connection.cursors))
        self.assertTrue(all(cursor.closed for cursor in connection.cursors))

    def test_non_select_statement_is_refused_before_the_cursor_is_used(self) -> None:
        connection = FakeConnection()
        with self.assertRaises(UnsafeStatementError):
            execute_read_only(connection, "DROP TABLE dbo.CustomerMaster")
        self.assertEqual([], connection.statements)
        self.assertEqual([], connection.cursors)

    def test_ms_shipped_tables_are_skipped(self) -> None:
        _, catalog = self.inspected()
        self.assertNotIn(
            "dbo.dtproperties", [entry["qualified_name"] for entry in catalog["tables"]]
        )

    def test_column_detail_is_truncated_at_the_recorded_bound(self) -> None:
        columns = [
            ("dbo", "CustomerMaster", index, f"Column{index:03d}", "int", 4, 10, 0, 0, 0, 0, 0, 0, 0, 0)
            for index in range(1, MAX_COLUMNS_PER_TABLE + 6)
        ]
        catalog = shape_metadata(catalog_results(columns=columns))
        entry = next(
            item for item in catalog["tables"] if item["qualified_name"] == "dbo.CustomerMaster"
        )
        self.assertTrue(entry["columns_truncated"])
        self.assertEqual(MAX_COLUMNS_PER_TABLE, len(entry["columns"]))
        self.assertIn("dbo.CustomerMaster", catalog["truncation"]["columns_truncated_tables"])

    def test_detailed_table_cap_is_recorded(self) -> None:
        with mock.patch.object(newerp_schema, "MAX_DETAILED_TABLES", 1):
            catalog = shape_metadata(catalog_results())
        detailed = [entry for entry in catalog["tables"] if entry["detailed"]]
        self.assertEqual(1, len(detailed))
        self.assertTrue(catalog["truncation"]["detailed_tables_truncated"])

    def test_catalog_failure_is_recorded_without_any_message_text(self) -> None:
        with disposable_root() as root:
            connection = FakeConnection(catalog_results(), fail_on="columns")
            driver = FakeDriverModule(connection=connection)
            facts, _ = collect_facts(
                root,
                generated_at="2026-09-24T00:00:00Z",
                driver_module=driver,
                connect=True,
            )
        inspection = facts["inspection"]
        self.assertEqual("unavailable", inspection["status"])
        self.assertIsNone(facts["catalog"])
        self.assertEqual("RuntimeError", inspection["catalog_read_failed"]["error_class"])
        self.assertEqual("catalog_read_failed", inspection["catalog_read_failed"]["category"])
        self.assertTrue(inspection["connection_closed"])
        self.assertNotIn("synthetic catalog failure", json.dumps(facts))
        self.assertTrue(
            any("did not complete" in reason for reason in inspection["unavailable_reasons"])
        )


class TableClassificationTests(unittest.TestCase):
    def test_tokens_split_camel_snake_and_plural_names(self) -> None:
        self.assertEqual(("customer", "master"), tokenize_identifier("CustomerMaster"))
        self.assertEqual(("supplier", "visit", "detail"), tokenize_identifier("supplier_visit_detail"))
        self.assertEqual(("sys", "user"), tokenize_identifier("SysUser"))
        self.assertEqual(("inquiry", "trip"), tokenize_identifier("InquiryTrip"))

    def test_core_nouns_make_strong_candidates(self) -> None:
        for name in ("Customer", "CustomerMaster", "Customers", "ClientInfo", "BuyerBase"):
            with self.subTest(name=name):
                classification = classify_table(name)
                self.assertEqual("customer", classification["domain"])
                self.assertTrue(classification["strong_candidate"])

    def test_supporting_tokens_stay_weak(self) -> None:
        classification = classify_table("CustInfo")
        self.assertEqual("customer", classification["domain"])
        self.assertFalse(classification["strong_candidate"])

    def test_domain_order_decides_a_shared_name(self) -> None:
        classification = classify_table("SupplierInquiry")
        self.assertEqual("supplier", classification["domain"])
        self.assertIn("inquiry", classification["matched_tokens"])

    def test_unmatched_and_empty_names_are_unclassified(self) -> None:
        for name in ("AbcXyz", "", "T_1234"):
            with self.subTest(name=name):
                classification = classify_table(name)
                self.assertIsNone(classification["domain"])
                self.assertFalse(classification["strong_candidate"])

    def test_master_hint_tokens_are_reported(self) -> None:
        self.assertEqual(
            ["master"], classify_table("SupplierMaster")["master_hint_tokens"]
        )
        self.assertEqual([], classify_table("InquiryTrip")["master_hint_tokens"])


class DdlInventoryTests(unittest.TestCase):
    def test_neutral_key_references_are_counted_by_line(self) -> None:
        inventory = newerp_schema.neutral_key_inventory(DDL_FIXTURE)
        self.assertEqual(
            ["CreatedByUserKey", "CustomerKey", "InquirerUserKey", "SupplierKey", "TenantId", "UserKey"],
            inventory["names"],
        )
        self.assertEqual(2, inventory["counts"]["CustomerKey"])
        self.assertEqual([1, 2], inventory["line_numbers"]["CustomerKey"])
        self.assertNotIn("KEY", inventory["names"])
        self.assertFalse(inventory["line_numbers_truncated"])

    def test_lower_case_key_and_primary_key_are_not_inventoried(self) -> None:
        inventory = newerp_schema.neutral_key_inventory("x key int, PRIMARY KEY (x)\n")
        self.assertEqual([], inventory["names"])

    def test_missing_planned_ddl_is_reported_without_error(self) -> None:
        with disposable_root(ddl_text=None) as root:
            inventory = load_ddl_inventory(root)
        self.assertFalse(inventory["available"])
        self.assertTrue(inventory["reason"])

    def test_real_planned_ddl_is_inventoried_read_only(self) -> None:
        inventory = load_ddl_inventory(REPOSITORY_ROOT)
        self.assertTrue(inventory["available"])
        self.assertIn("CustomerKey", inventory["names"])
        self.assertIn("SupplierKey", inventory["names"])
        self.assertIn("UserKey", inventory["names"])
        self.assertIn("TenantId", inventory["names"])


class FactsAndReportTests(unittest.TestCase):
    def collect(
        self, root: Path, *, connect: bool, driver_module: Any = None, environ: Any = None
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        return collect_facts(
            root,
            generated_at="2026-09-24T00:00:00Z",
            environ=environ,
            driver_module=driver_module,
            connect=connect,
            payload_received=True,
            payload_sources=(".ai/project_state.json#task_statuses.NEWAPP-003",),
            executor_paths=EXECUTOR_PATHS,
            report_paths=(REPORT_RELATIVE_PATH,),
            doc_paths=(DOC_RELATIVE_PATH,),
        )

    def test_offline_collection_reports_explicit_unknowns(self) -> None:
        with disposable_root() as root:
            before = (root / ENV_FILE).read_bytes()
            facts, needles = self.collect(root, connect=False)
            after = (root / ENV_FILE).read_bytes()
        self.assertEqual(before, after)
        inspection = facts["inspection"]
        self.assertEqual("unavailable", inspection["status"])
        self.assertFalse(inspection["connection_attempted"])
        self.assertTrue(inspection["declared_setting_present"])
        self.assertEqual(".env", inspection["connection_source"])
        self.assertTrue(inspection["environment_file_modified_time_unchanged_during_run"])
        self.assertTrue(inspection["unavailable_reasons"])
        self.assertIsNone(facts["catalog"])
        self.assertTrue(needles)

        report = build_report(facts)
        self.assertEqual(TASK_ID, report["task_id"])
        self.assertFalse(report["safety_contract"]["connection_string_recorded"])
        self.assertFalse(report["safety_contract"]["server_host_recorded"])
        self.assertFalse(report["safety_contract"]["password_recorded"])
        self.assertFalse(report["safety_contract"]["ddl_or_dml_executed"])
        self.assertEqual(0, report["safety_contract"]["statements_executed"])
        self.assertTrue(report["executor_payload"]["controller_payload_section_present"])
        self.assertFalse(report["acceptance_evidence"][0]["satisfied"])
        self.assertFalse(report["acceptance_evidence"][1]["satisfied"])
        self.assertTrue(report["acceptance_evidence"][2]["satisfied"])
        self.assertTrue(
            any(item["item"] == "live NEWERP catalog metadata" for item in report["unresolved"])
        )
        mapping_items = [item for item in report["unresolved"] if item["item"].endswith("table mapping")]
        self.assertEqual(len(DOMAIN_ORDER), len(mapping_items))
        report_text = render_json(report)
        for needle in needles:
            self.assertNotIn(needle, report_text)

    def test_inspected_run_satisfies_every_criterion(self) -> None:
        with disposable_root() as root:
            driver = FakeDriverModule(connection=FakeConnection(catalog_results()))
            facts, needles = self.collect(root, connect=True, driver_module=driver)
            self.assertEqual("inspected", facts["inspection"]["status"])
            self.assertTrue(facts["inspection"]["connection_closed"])
            report = build_report(facts)
            report, report_text, markdown = finalize_report(report, needles)
        self.assertTrue(report["artifact_checks_verified"])
        self.assertEqual("evidence_collected", report["status"])
        self.assertTrue(all(entry["satisfied"] for entry in report["acceptance_evidence"]))
        self.assertEqual(8, report["safety_contract"]["statements_executed"])
        self.assertEqual("passed", report["artifact_checks"]["report_credential_guard"]["status"])
        self.assertEqual("passed", report["artifact_checks"]["scanner_self_check"]["status"])
        self.assertIn("## 6. Candidate table detail", markdown)
        self.assertIn("dbo.CustomerMaster", markdown)
        self.assertIn("## 13. Unresolved items", markdown)
        for needle in needles:
            self.assertNotIn(needle, report_text)
            self.assertNotIn(needle, markdown)

    def test_finalize_is_deterministic_for_identical_facts(self) -> None:
        with disposable_root() as root:
            driver = FakeDriverModule(connection=FakeConnection(catalog_results()))
            with mock.patch.object(newerp_schema.time, "monotonic", return_value=1234.0):
                first_facts, needles = self.collect(root, connect=True, driver_module=driver)
                second_facts, _ = self.collect(root, connect=True, driver_module=driver)
        first = finalize_report(build_report(first_facts), needles)
        second = finalize_report(build_report(second_facts), needles)
        self.assertEqual(first[1], second[1])
        self.assertEqual(first[2], second[2])

    def test_declaration_may_come_from_the_process_environment(self) -> None:
        with disposable_root(env_text=None) as root:
            facts, needles = self.collect(
                root, connect=False, environ={CONNECTION_KEY: SYNTHETIC_CONNECTION}
            )
        self.assertTrue(facts["inspection"]["declared_setting_present"])
        self.assertEqual("process_environment", facts["inspection"]["connection_source"])
        self.assertTrue(needles)

    def test_missing_declaration_is_reported_and_never_invented(self) -> None:
        with disposable_root(env_text="# no declaration here\n") as root:
            facts, needles = self.collect(root, connect=False, environ={})
        self.assertFalse(facts["inspection"]["declared_setting_present"])
        self.assertEqual("not_declared", facts["inspection"]["connection_source"])
        self.assertEqual((), needles)
        self.assertTrue(
            any("not declared" in reason for reason in facts["inspection"]["unavailable_reasons"])
        )
        report = build_report(facts)
        self.assertIsNone(report["shared_connection_configuration"]["selected_driver"])
        self.assertFalse(report["shared_connection_configuration"]["declared_setting_present"])

    def test_resolve_connection_value_prefers_the_process_environment(self) -> None:
        with disposable_root() as root:
            value, source = resolve_connection_value(
                root / ENV_FILE, {CONNECTION_KEY: "example-value"}
            )
            self.assertEqual("process_environment", source)
            self.assertEqual("example-value", value)
            value, source = resolve_connection_value(root / ENV_FILE, {})
            self.assertEqual(".env", source)
            self.assertEqual(SYNTHETIC_CONNECTION, value)
            value, source = resolve_connection_value(root / "missing.env", {})
            self.assertEqual("not_declared", source)
            self.assertIsNone(value)


class ArtifactGuardTests(unittest.TestCase):
    def rendered(self, root: Path) -> tuple[dict[str, Any], str, str, tuple[str, ...]]:
        driver = FakeDriverModule(connection=FakeConnection(catalog_results()))
        facts, needles = collect_facts(
            root,
            generated_at="2026-09-24T00:00:00Z",
            driver_module=driver,
            connect=True,
            executor_paths=EXECUTOR_PATHS,
            report_paths=(REPORT_RELATIVE_PATH,),
            doc_paths=(DOC_RELATIVE_PATH,),
        )
        report, report_text, markdown = finalize_report(build_report(facts), needles)
        return report, report_text, markdown, needles

    def test_credential_guard_flags_a_needle_without_echoing_it(self) -> None:
        text = f"line one\nassignment for {CONNECTION_KEY} is kept in memory\n"
        guard = credential_leak_guard(text, ("kept in memory",), "sample")
        self.assertEqual("failed", guard["status"])
        self.assertEqual(1, guard["findings_count"])
        self.assertEqual("declared_connection_material", guard["findings"][0]["rule"])
        self.assertEqual(2, guard["findings"][0]["line"])
        self.assertNotIn("kept in memory", json.dumps(guard))

    def test_credential_guard_flags_assignment_shapes(self) -> None:
        for line in (
            "Password: example-material",
            "PWD=example-material",
            "User Id: example-user",
            f"{CONNECTION_KEY}=example-declaration",
        ):
            with self.subTest(line=line):
                self.assertEqual("failed", credential_leak_guard(line, (), "sample")["status"])
        self.assertEqual(
            "passed", credential_leak_guard("Password material recorded | no", (), "sample")["status"]
        )

    def test_scanner_self_check_passes_over_the_rendered_artifacts(self) -> None:
        with disposable_root() as root:
            report, report_text, markdown, _ = self.rendered(root)
        check = scanner_self_check({REPORT_RELATIVE_PATH: report_text, DOC_RELATIVE_PATH: markdown})
        self.assertTrue(check["available"])
        self.assertEqual(SCANNER_RELATIVE_PATH, check["scanner"])
        self.assertEqual("passed", check["status"])
        self.assertEqual("passed", report["artifact_checks"]["scanner_self_check"]["status"])

    def test_publication_is_refused_when_a_guard_fails(self) -> None:
        with disposable_root() as root:
            report, _, _, _ = self.rendered(root)
        report["artifact_checks"]["report_credential_guard"]["status"] = "failed"
        report["artifact_checks"]["report_credential_guard"]["findings_count"] = 1
        self.assertIn("report_credential_guard", publication_blocked(report) or "")
        report["artifact_checks"]["report_credential_guard"]["status"] = "passed"
        self.assertIsNone(publication_blocked(report))

    def test_path_guard_accepts_every_recorded_path(self) -> None:
        guard = path_guard_compatibility(
            EXECUTOR_PATHS,
            CONTROLLER_ALLOWED_PATTERNS,
            CONTROLLER_PROTECTED_PATTERNS,
            "test patterns",
        )
        self.assertTrue(guard["all_paths_accepted"])
        self.assertTrue(guard["no_protected_path_touched"])

    def test_protected_path_blocks_the_artifact_criterion(self) -> None:
        guard = path_guard_compatibility(
            (".ai/controller/agent_loop.py",),
            CONTROLLER_ALLOWED_PATTERNS,
            CONTROLLER_PROTECTED_PATTERNS,
            "test patterns",
        )
        self.assertFalse(guard["all_paths_accepted"])
        self.assertFalse(guard["no_protected_path_touched"])

    def test_mirror_matches_the_controller_path_matches(self) -> None:
        common = load_controller_common()
        for path in (
            *EXECUTOR_PATHS,
            ".ai/controller/agent_loop.py",
            "./docs/NEWERP_SCHEMA_MAP.md",
            ".ai/generated/NEWAPP-003-newerp-schema-map.json",
        ):
            with self.subTest(path=path):
                guard = path_guard_compatibility(
                    (path,),
                    CONTROLLER_ALLOWED_PATTERNS,
                    CONTROLLER_PROTECTED_PATTERNS,
                    "test patterns",
                )
                normalized = str(path).replace("\\", "/")
                while normalized.startswith("./"):
                    normalized = normalized[2:]
                self.assertEqual(normalized.lower(), normalize_for_path_guard(path))
                self.assertEqual(
                    common.path_matches(path, CONTROLLER_ALLOWED_PATTERNS),
                    guard["paths"][0]["accepted"],
                )
                self.assertEqual(
                    common.path_matches(path, CONTROLLER_PROTECTED_PATTERNS),
                    not guard["no_protected_path_touched"],
                )


class CommandLineTests(unittest.TestCase):
    def run_cli(self, root: Path, *extra: str) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(["--root", str(root), *extra])
        return code, buffer.getvalue()

    def test_no_connect_write_creates_both_artifacts_and_reports_attention(self) -> None:
        with disposable_root() as root:
            code, output = self.run_cli(
                root,
                "--no-connect",
                "--write",
                "--executor-file",
                "tests/schema/newerp_schema.py",
            )
            report = json.loads((root / REPORT_RELATIVE_PATH).read_text(encoding="utf-8"))
            markdown = (root / DOC_RELATIVE_PATH).read_text(encoding="utf-8")
        self.assertEqual(1, code)
        self.assertIn("inspection=unavailable", output)
        self.assertIn("unresolved_items=8", output)
        self.assertIn("written " + REPORT_RELATIVE_PATH, output)
        self.assertEqual(TASK_ID, report["task_id"])
        self.assertEqual("attention_required", report["status"])
        self.assertFalse(report["artifact_checks_verified"])
        self.assertEqual("passed", report["artifact_checks"]["report_credential_guard"]["status"])
        self.assertIn("# NEWERP shared database schema map", markdown)
        self.assertIn(REPORT_RELATIVE_PATH, markdown)

    def test_json_mode_prints_a_value_free_report(self) -> None:
        with disposable_root() as root:
            code, output = self.run_cli(root, "--no-connect", "--json")
        self.assertEqual(1, code)
        report = json.loads(output)
        self.assertEqual(TASK_ID, report["task_id"])
        for value in ("example-server", "example-database", "example-user", "example-material"):
            self.assertNotIn(value, output)

    def test_credential_needle_blocks_publication(self) -> None:
        leaked = (
            "Server=NEWAPP-003;Database=example-database;"
            "User Id=example-user;Password=example-material"
        )
        with disposable_root(env_text=f"{CONNECTION_KEY}={leaked}\n") as root:
            code, output = self.run_cli(root, "--no-connect", "--write")
            report_exists = (root / REPORT_RELATIVE_PATH).exists()
            doc_exists = (root / DOC_RELATIVE_PATH).exists()
        self.assertEqual(2, code)
        self.assertIn("[refused]", output)
        self.assertFalse(report_exists)
        self.assertFalse(doc_exists)

    def test_missing_environment_file_is_reported(self) -> None:
        with disposable_root(env_text=None) as root:
            code, output = self.run_cli(root, "--no-connect", "--write")
            report = json.loads((root / REPORT_RELATIVE_PATH).read_text(encoding="utf-8"))
        self.assertEqual(1, code)
        self.assertFalse(report["inspection"]["declared_setting_present"])
        self.assertIn("catalog=unavailable", output)


def load_controller_common() -> Any:
    """Load the controller ``common`` module read-only to compare the mirrored path guard."""
    specification = importlib.util.spec_from_file_location(
        "newapp_controller_common", CONTROLLER_COMMON
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def declared_key_names(path: Path) -> set[str]:
    """Read an environment file and return the declared *names* only, never a value."""
    names: set[str] = set()
    if not path.is_file():
        return names
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = DECLARATION_PATTERN.match(line)
        if match is not None:
            names.add(match.group("name"))
    return names


class RealRepositoryTests(unittest.TestCase):
    def test_real_controller_configuration_matches_the_mirror(self) -> None:
        settings = json.loads((REPOSITORY_ROOT / ".ai/agent_config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(
            CONTROLLER_ALLOWED_PATTERNS, tuple(settings["paths"]["executor_allowed"])
        )
        self.assertEqual(CONTROLLER_PROTECTED_PATTERNS, tuple(settings["paths"]["protected"]))
        self.assertIn(
            settings["environment"]["file"],
            (".env", "./.env"),
        )

    def test_real_declaration_declares_the_connection_key_name(self) -> None:
        names = declared_key_names(REPOSITORY_ROOT / ENV_FILE)
        self.assertIn(CONNECTION_KEY, names)
        self.assertTrue(DOC_PATH.is_file())

    def test_real_controller_config_keeps_the_read_only_task_outside_the_human_gate(self) -> None:
        settings = json.loads((REPOSITORY_ROOT / ".ai/agent_config.yaml").read_text(encoding="utf-8"))
        self.assertNotIn(TASK_ID, settings["human_gate"]["task_ids"])
        self.assertTrue(settings["human_gate"]["always_for_shared_database_structure"])

    def test_committed_artifacts_exist_and_pass_the_guards(self) -> None:
        report_text = REPORT_PATH.read_text(encoding="utf-8")
        markdown = DOC_PATH.read_text(encoding="utf-8")
        for label, text in (
            (REPORT_RELATIVE_PATH, report_text),
            (DOC_RELATIVE_PATH, markdown),
        ):
            with self.subTest(label=label):
                self.assertEqual("passed", credential_leak_guard(text, (), label)["status"])
        check = scanner_self_check({REPORT_RELATIVE_PATH: report_text, DOC_RELATIVE_PATH: markdown})
        self.assertEqual("passed", check["status"])

    def test_committed_report_states_the_outcome_and_the_explicit_unknowns(self) -> None:
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(TASK_ID, report["task_id"])
        self.assertIn(report["inspection"]["status"], {"inspected", "unavailable"})
        self.assertFalse(report["safety_contract"]["connection_string_recorded"])
        self.assertFalse(report["safety_contract"]["row_values_recorded"])
        self.assertFalse(report["safety_contract"]["ddl_or_dml_executed"])
        self.assertEqual(0, report["safety_contract"]["statements_outside_catalog"])
        if report["inspection"]["status"] == "inspected":
            self.assertIsNotNone(report["catalog"])
            self.assertEqual(len(DOMAIN_ORDER), len(report["catalog"]["domain_map"]))
        else:
            self.assertIsNone(report["catalog"])
            self.assertTrue(report["inspection"]["unavailable_reasons"])
            self.assertTrue(
                any(
                    item["item"] == "live NEWERP catalog metadata" for item in report["unresolved"]
                )
            )
            mapping_items = [
                item for item in report["unresolved"] if "table mapping" in item["item"]
            ]
            self.assertEqual(len(DOMAIN_ORDER), len(mapping_items))
        self.assertEqual(len(newerp_schema.LIMITATIONS), len(report["limitations"]))
        self.assertTrue(report["planned_ddl_key_references"]["available"])
        self.assertIn("CustomerKey", report["planned_ddl_key_references"]["names"])

    def test_committed_document_is_generated_from_the_report(self) -> None:
        markdown = DOC_PATH.read_text(encoding="utf-8")
        self.assertIn("# NEWERP shared database schema map", markdown)
        self.assertIn(REPORT_RELATIVE_PATH, markdown)
        self.assertIn("regenerate it with", markdown)
        self.assertIn("## 12. Known limits", markdown)
        self.assertIn("## 13. Unresolved items", markdown)


if __name__ == "__main__":
    unittest.main()
