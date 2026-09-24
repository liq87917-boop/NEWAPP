"""Read-only NEWERP shared-schema inspection for NEWAPP-003 (\"Inspect NEWERP shared database schema\").

Regenerate the two value-free artifacts required by the GPT plan for NEWAPP-003 from the repository
root::

    .venv\\Scripts\\python.exe tests\\schema\\newerp_schema.py --write

Artifacts:

* ``.ai/generated/NEWAPP-003-newerp-schema-map.json`` - machine-readable, value-free schema facts.
* ``docs/NEWERP_SCHEMA_MAP.md`` - human documentation rendered from the same facts.

Safety contract
---------------
* The shared connection string is read from ``.env`` (or from the already exported process
  environment) into memory only. It is never printed, logged, stored, returned, hashed, compared or
  written into evidence. The report records only *keyword names*, shape flags, the selected ODBC
  driver name and the shape of the keywords that are not ODBC compatible.
* Every statement that reaches the database comes from the fixed catalog table
  :data:`CATALOG_QUERIES` and must pass :func:`assert_read_only` first: one ``SELECT`` batch with no
  batch separator, no comment marker and no DDL/DML/``EXEC``/``INTO``/``OPENROWSET`` token. Only
  ``sys.*`` catalogs plus ``SERVERPROPERTY``/``DB_NAME()`` metadata are read, so no business row
  value can be returned; only column, key, index and concurrency *metadata* is recorded.
* The session is opened with ``autocommit=True`` and a bounded login timeout, and the read-only
  application intent is requested on drivers that support it, so the inspection cannot leave a
  transaction open and cannot write.
* Both artifacts are re-checked before publication: a credential-leak guard over the declared
  environment values and the repository scanner ``tests/baseline/secret_scan.py``. If a credential
  needle is ever found, the artifacts are **not** written and the command exits non-zero.
* Every recorded executor path is checked with a mirror of the controller path guard, so an artifact
  that landed outside the allowed patterns is reported as ``attention_required``.

Documented limits (reviewed by GPT, not silently expanded)
----------------------------------------------------------
* When the ODBC driver, the network or the shared server is unavailable, every table/key mapping is
  reported as an explicit ``unknown`` together with a value-free failure category. No table name is
  ever inferred, guessed or copied from the planned DDL, so the neutral ``*Key`` columns of
  ``docs/NEWAPP_Database_DDL_V1.sql`` stay unmapped until this map exists and is accepted.
* Domain classification is derived from catalog table *names* only. It produces candidates for the
  master tables, marks a domain with no candidate at all as absent from the inspected catalog, and
  never asserts the authoritative mapping; NEWAPP-005 owns the reconciliation of the planned DDL
  against these real keys, and shared-structure changes stay behind the Human Gate.
* The keyword parser splits a declared connection string on ``;`` without interpreting quoted
  semicolons, and table/column detail is capped by the ``MAX_*`` constants below. Both effects are
  recorded in the report as shape flags and truncation counts.
* ``agent.env``, ``secrets/`` and signing material are never opened.
"""

from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import os
import platform
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

TASK_ID = "NEWAPP-003"
TASK_TITLE = "Inspect NEWERP shared database schema"
TASK_PHASE = "P0"
TASK_DEPENDS_ON: tuple[str, ...] = ("NEWAPP-002",)
REPORT_RELATIVE_PATH = ".ai/generated/NEWAPP-003-newerp-schema-map.json"
DOC_RELATIVE_PATH = "docs/NEWERP_SCHEMA_MAP.md"
ENV_FILE = ".env"
CONNECTION_KEY = "ERP_ConnectionStrings__Default"
CONFIG_SOURCE = ".ai/agent_config.yaml"
SCANNER_RELATIVE_PATH = "tests/baseline/secret_scan.py"
DDL_RELATIVE_PATH = "docs/NEWAPP_Database_DDL_V1.sql"
ALLOWED_ARTIFACT_PATTERNS = ("docs/**", ".ai/generated/**")
DEFAULT_PAYLOAD_SOURCES = (
    ".ai/project_state.json#task_statuses.NEWAPP-003",
    ".ai/brain/decisions/NEWAPP-003-plan.json",
    "docs/NEWAPP_TASKS_V1.yaml#NEWAPP-003",
)

DRIVER_MODULE_NAME = "pyodbc"
LOGIN_TIMEOUT_SECONDS = 5
PREFERRED_ODBC_DRIVERS: tuple[str, ...] = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
)
READ_ONLY_INTENT_DRIVERS: tuple[str, ...] = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
)

# Bounds. A large shared database must not turn evidence into an unbounded dump.
MAX_TABLES = 2000
MAX_DETAILED_TABLES = 60
MAX_COLUMNS_PER_TABLE = 150
MAX_KEY_ENTRIES_PER_TABLE = 40
MAX_INDEX_ENTRIES_PER_TABLE = 60
MAX_FOREIGN_KEYS_PER_TABLE = 40
MAX_DOC_TABLE_DETAILS = 25

MIN_NEEDLE_LENGTH = 4

# Loaded lazily by :func:`scanner_module`; the repository scanner is never modified.
_SCANNER_CACHE: dict[str, Any] = {}

# --------------------------------------------------------------------------- statement guard

WHITESPACE_PATTERN = re.compile(r"\s+")
COMMENT_MARKERS: tuple[str, ...] = ("--", "/*", "*/")
FORBIDDEN_STATEMENT_TOKENS: tuple[str, ...] = (
    "insert",
    "update",
    "delete",
    "merge",
    "drop",
    "truncate",
    "alter",
    "create",
    "exec",
    "execute",
    "grant",
    "deny",
    "revoke",
    "backup",
    "restore",
    "shutdown",
    "reconfigure",
    "into",
    "go",
    "openrowset",
    "openquery",
    "opendatasource",
    "opendataset",
    "bulk",
    "writetext",
    "updatetext",
    "waitfor",
    "kill",
    "checkpoint",
    "dbcc",
)
PREFIX_FORBIDDEN_TOKENS: tuple[str, ...] = ("sp_", "xp_")


class UnsafeStatementError(RuntimeError):
    """Raised when a statement is not a single, read-only ``SELECT`` produced by this module."""


def normalize_statement(statement: str) -> str:
    """Collapse whitespace and drop one optional trailing batch terminator."""
    text = WHITESPACE_PATTERN.sub(" ", str(statement)).strip()
    if text.endswith(";"):
        text = text[:-1].strip()
    return text


def forbidden_statement_token(statement: str) -> str | None:
    """Return the first DDL/DML/administrative token found in a statement, else ``None``."""
    lowered = normalize_statement(statement).lower()
    for token in PREFIX_FORBIDDEN_TOKENS:
        if re.search(r"\b" + re.escape(token), lowered):
            return token
    for token in FORBIDDEN_STATEMENT_TOKENS:
        if re.search(r"\b" + re.escape(token) + r"\b", lowered):
            return token
    return None


def statement_is_read_only(statement: str) -> tuple[bool, str]:
    """Return ``(accepted, reason)`` for one statement. No database is contacted."""
    text = normalize_statement(statement)
    if not text:
        return False, "empty statement"
    for marker in COMMENT_MARKERS:
        if marker in text:
            return False, f"comment marker present: {marker}"
    if ";" in text:
        return False, "multi-statement batch separator present"
    lowered = text.lower()
    if not lowered.startswith("select "):
        head = lowered.split(" ", 1)[0]
        return False, f"statement must start with 'select', found '{head}'"
    forbidden = forbidden_statement_token(text)
    if forbidden:
        return False, f"forbidden statement token: {forbidden}"
    return True, "single read-only select"


def assert_read_only(statement: str) -> str:
    """Return the normalized statement or raise :class:`UnsafeStatementError`."""
    accepted, reason = statement_is_read_only(statement)
    if not accepted:
        raise UnsafeStatementError(f"refused statement: {reason}")
    return normalize_statement(statement)



# --------------------------------------------------------------------------- environment facts

DECLARATION_PATTERN = re.compile(
    r"^\s*(?P<export>export\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<rest>.*)$"
)


def read_environment_values(path: Path) -> dict[str, str]:
    """Read an environment file into memory only.

    Callers must never record, print, log or store the returned values or the dictionary itself.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = DECLARATION_PATTERN.match(line)
        if match is None:
            continue
        raw = match.group("rest").strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
            raw = raw[1:-1]
        values[match.group("name")] = raw
    return values


def keyword_pair(text: str) -> tuple[str, str] | None:
    """Split one ``keyword=value`` fragment; the value is only inspected in memory."""
    match = re.match(r"^(?P<name>[^=;]+?)\s*=\s*(?P<value>.*)$", text)
    if match is None:
        return None
    name = match.group("name").strip()
    raw = match.group("value").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
        raw = raw[1:-1]
    return name, raw


def parse_connection_string(value: Any) -> list[tuple[str, str]]:
    """Split a declared connection string into ``(keyword, value)`` pairs **in memory only**."""
    pairs: list[tuple[str, str]] = []
    for part in str(value or "").split(";"):
        if not part.strip():
            continue
        pair = keyword_pair(part.strip())
        if pair is not None:
            pairs.append(pair)
    return pairs


def normalize_keyword(name: str) -> str:
    """Lower-case a connection-string keyword and drop separators for shape comparison."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


ODBC_KEYWORD_MAP: dict[str, str] = {
    "server": "Server",
    "datasource": "Server",
    "addr": "Server",
    "address": "Server",
    "networkaddress": "Server",
    "database": "Database",
    "initialcatalog": "Database",
    "uid": "UID",
    "userid": "UID",
    "user": "UID",
    "pwd": "PWD",
    "password": "PWD",
    "integratedsecurity": "Trusted_Connection",
    "trustedconnection": "Trusted_Connection",
    "trustservercertificate": "TrustServerCertificate",
    "encrypt": "Encrypt",
    "applicationintent": "ApplicationIntent",
    "multisubnetfailover": "MultiSubnetFailover",
}

NON_ODBC_KEYWORDS: tuple[str, ...] = (
    "applicationname",
    "asynchronousprocessing",
    "attachdbfilename",
    "connectretrycount",
    "connectretryinterval",
    "connecttimeout",
    "connectiontimeout",
    "contextconnection",
    "currentlanguage",
    "disableretry",
    "enlist",
    "loadbalanceblocklist",
    "loadbalancetimeout",
    "maxpoolsize",
    "minpoolsize",
    "multipleactiveresultsets",
    "persistsecurityinfo",
    "pooling",
    "replication",
    "transactionbinding",
    "transparentnetworkipresolution",
    "userinstance",
)

BOOLEAN_ODBC_KEYWORDS: frozenset[str] = frozenset(
    {"trustedconnection", "trustservercertificate", "encrypt"}
)

CREDENTIAL_KEYWORD_NAMES: frozenset[str] = frozenset(
    {
        "password",
        "pwd",
        "uid",
        "userid",
        "user",
        "server",
        "datasource",
        "addr",
        "address",
        "networkaddress",
        "driver",
    }
)


def odbc_boolean(value: Any) -> str:
    """Translate a .NET boolean-ish connection-string value into the ODBC ``yes``/``no`` form."""
    return "yes" if str(value).strip().lower() in {"true", "yes", "y", "1", "sspi"} else "no"


def select_odbc_driver(driver_names: Sequence[str], declared: str | None = None) -> str | None:
    """Pick the ODBC driver for the read-only session: the declared one, else the best available."""
    if declared:
        return declared
    available = {str(name) for name in driver_names}
    for candidate in PREFERRED_ODBC_DRIVERS:
        if candidate in available:
            return candidate
    return None


def build_odbc_target(connection_string: Any, driver_names: Sequence[str]) -> dict[str, Any]:
    """Translate the declared connection string into an in-memory ODBC target.

    Returns ``{"target": <target or None>, "facts": {...}}``. ``target`` carries credential material
    and must stay local to the connection attempt: it is never recorded, logged or rendered.
    """
    pairs = parse_connection_string(connection_string)
    normalized = {normalize_keyword(name) for name, _ in pairs}
    declared_driver: str | None = None
    for name, value in pairs:
        if normalize_keyword(name) == "driver":
            declared_driver = value.strip("{} \t").strip() or None
    selected = select_odbc_driver(driver_names, declared_driver)

    fragments: list[str] = []
    keyword_names: list[str] = []
    emitted_names: list[str] = []
    dropped_names: list[str] = []
    for name, value in pairs:
        key = normalize_keyword(name)
        if key == "driver":
            continue
        if key in NON_ODBC_KEYWORDS:
            dropped_names.append(name)
            continue
        odbc_name = ODBC_KEYWORD_MAP.get(key, name.strip())
        if normalize_keyword(odbc_name) in BOOLEAN_ODBC_KEYWORDS:
            value = odbc_boolean(value)
        fragments.append(f"{odbc_name}={value}")
        keyword_names.append(name)
        emitted_names.append(odbc_name)

    read_only_intent = False
    if selected and selected in READ_ONLY_INTENT_DRIVERS and "applicationintent" not in normalized:
        fragments.append("ApplicationIntent=ReadOnly")
        emitted_names.append("ApplicationIntent")
        read_only_intent = True
    keyword_fragment_count = len(fragments) - (1 if read_only_intent else 0)
    if selected:
        fragments.insert(0, "Driver={" + selected + "}")
        emitted_names.insert(0, "Driver")

    declared_fragments = [part for part in str(connection_string or "").split(";") if part.strip()]
    facts: dict[str, Any] = {
        "keyword_names": keyword_names,
        "keyword_count": len(pairs),
        "odbc_keyword_names": emitted_names,
        "non_odbc_keyword_names": dropped_names,
        "declares_odbc_driver": declared_driver is not None,
        "selected_driver": selected,
        "read_only_intent_requested": read_only_intent,
        "has_server_keyword": bool(
            normalized & {"server", "datasource", "addr", "address", "networkaddress"}
        ),
        "has_catalog_keyword": bool(normalized & {"database", "initialcatalog"}),
        "has_user_keyword": bool(normalized & {"uid", "userid", "user"}),
        "has_password_keyword": bool(normalized & {"pwd", "password"}),
        "uses_integrated_security": bool(normalized & {"integratedsecurity", "trustedconnection"}),
        "unparsed_fragment_count": max(0, len(declared_fragments) - len(pairs)),
        "keyword_fragment_count": keyword_fragment_count,
    }
    target = ";" + ";".join(fragments) + ";" if keyword_fragment_count > 0 else None
    return {"target": target, "facts": facts}


def credential_needles(connection_string: Any) -> tuple[str, ...]:
    """Return in-memory needles that must never appear in evidence.

    The whole declaration plus every credential-ish fragment value is included, so the leak guard can
    reject server, login, password and driver material without ever echoing it.
    """
    needles: set[str] = set()
    text = str(connection_string or "")
    if text:
        needles.add(text)
    for name, value in parse_connection_string(text):
        if normalize_keyword(name) in CREDENTIAL_KEYWORD_NAMES:
            needles.add(value)
    needles = {needle for needle in needles if len(needle) >= MIN_NEEDLE_LENGTH}
    return tuple(sorted(needles, key=len, reverse=True))


CREDENTIAL_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(password|passwd|pwd|user[ _-]?id|uid|secret|token|access[ _-]?key|"
    r"connection[ _-]?string)\b[\"']?\s*[:=]\s*\S"
)
CONNECTION_KEY_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b" + re.escape(CONNECTION_KEY) + r"\b\s*[:=]\s*\S"
)


def credential_leak_guard(text: str, needles: Sequence[str], label: str) -> dict[str, Any]:
    """Scan rendered artifact text for declared material without returning any matched value.

    Findings carry a rule id and a line number only, so a guard result can be published as evidence.
    """
    findings: list[dict[str, Any]] = []
    for number, line in enumerate(str(text).splitlines(), start=1):
        if any(needle in line for needle in needles if needle):
            findings.append({"rule": "declared_connection_material", "line": number})
        if CREDENTIAL_ASSIGNMENT_PATTERN.search(line):
            findings.append({"rule": "credential_assignment", "line": number})
        if CONNECTION_KEY_ASSIGNMENT_PATTERN.search(line):
            findings.append({"rule": "declared_configuration_key_assignment", "line": number})
    return {
        "label": label,
        "status": "passed" if not findings else "failed",
        "findings": findings,
        "findings_count": len(findings),
        "needle_count": len(tuple(needles)),
        "values_recorded": False,
    }


# --------------------------------------------------------------------------- name classification

IDENTIFIER_SPLIT_PATTERN = re.compile(r"[^A-Za-z0-9]+")
CAMEL_BOUNDARY_PATTERN = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

DOMAIN_ORDER: tuple[str, ...] = (
    "customer",
    "supplier",
    "user",
    "organization",
    "dictionary",
    "inquiry",
)
MASTER_DOMAINS: tuple[str, ...] = ("customer", "supplier", "user", "organization")
DOMAIN_TITLES: dict[str, str] = {
    "customer": "Customer master data",
    "supplier": "Supplier master data",
    "user": "User and account data",
    "organization": "Organization, tenant and company data",
    "dictionary": "Shared dictionaries and code tables",
    "inquiry": "Inquiry, quotation and revision data",
}
DOMAIN_TOKENS: dict[str, tuple[str, ...]] = {
    "customer": (
        "customer",
        "customers",
        "cust",
        "client",
        "clients",
        "buyer",
        "buyers",
        "crm",
        "consignee",
        "dealer",
    ),
    "supplier": (
        "supplier",
        "suppliers",
        "vendor",
        "vendors",
        "factory",
        "factories",
        "producer",
        "manufacturer",
    ),
    "user": (
        "user",
        "users",
        "sysuser",
        "sysusers",
        "account",
        "accounts",
        "employee",
        "employees",
        "staff",
        "member",
        "members",
        "login",
        "logins",
        "operator",
        "operators",
        "person",
        "persons",
        "role",
        "roles",
        "permission",
        "permissions",
    ),
    "organization": (
        "organization",
        "organisation",
        "org",
        "orgs",
        "company",
        "companyinfo",
        "tenant",
        "tenants",
        "enterprise",
        "corp",
        "corporation",
        "department",
        "dept",
        "depts",
        "branch",
        "branches",
        "group",
        "groups",
        "plant",
        "plants",
    ),
    "dictionary": (
        "dictionary",
        "dict",
        "lookup",
        "lookups",
        "code",
        "codes",
        "codetable",
        "type",
        "types",
        "category",
        "categories",
        "enum",
        "enums",
        "config",
        "configs",
        "setting",
        "settings",
        "param",
        "params",
        "parameter",
        "parameters",
        "currency",
        "currencies",
        "unit",
        "units",
        "uom",
        "material",
        "materials",
        "color",
        "colors",
        "region",
        "regions",
        "country",
        "countries",
        "port",
        "ports",
        "payment",
        "payments",
        "tax",
        "status",
        "statuses",
    ),
    "inquiry": (
        "inquiry",
        "inquiries",
        "enquiry",
        "enquiries",
        "rfq",
        "rfqs",
        "quote",
        "quotes",
        "quotation",
        "quotations",
        "inquirytrip",
        "inquirytrips",
        "suppliervisit",
        "suppliervisits",
        "revision",
        "revisions",
        "price",
        "prices",
        "pricing",
        "product",
        "products",
        "item",
        "items",
        "sku",
        "skus",
        "offer",
        "offers",
    ),
}
CORE_DOMAIN_TOKENS: dict[str, tuple[str, ...]] = {
    "customer": ("customer", "customers", "client", "clients", "buyer", "buyers"),
    "supplier": ("supplier", "suppliers", "vendor", "vendors"),
    "user": ("user", "users", "sysuser", "sysusers", "employee", "employees"),
    "organization": (
        "organization",
        "organisation",
        "company",
        "companyinfo",
        "tenant",
        "enterprise",
        "corp",
        "corporation",
    ),
    "dictionary": ("dictionary", "lookup", "lookups"),
    "inquiry": (
        "inquiry",
        "inquiries",
        "enquiry",
        "rfq",
        "quote",
        "quotes",
        "quotation",
        "quotations",
    ),
}
MASTER_HINT_TOKENS: tuple[str, ...] = ("master", "base", "basic", "main", "info", "head")


def tokenize_identifier(name: str) -> tuple[str, ...]:
    """Split a table or column name into lower-case tokens, honouring camel-case boundaries."""
    spaced = CAMEL_BOUNDARY_PATTERN.sub("_", str(name))
    return tuple(part for part in IDENTIFIER_SPLIT_PATTERN.split(spaced.lower()) if part)


def classify_table(name: str) -> dict[str, Any]:
    """Classify a catalog table name into domain *candidates* using name shape only."""
    tokens = set(tokenize_identifier(name))
    matched: dict[str, list[str]] = {}
    for domain in DOMAIN_ORDER:
        hits = sorted(tokens & set(DOMAIN_TOKENS[domain]))
        if hits:
            matched[domain] = hits
    domain = next((item for item in DOMAIN_ORDER if item in matched), None)
    core = set(CORE_DOMAIN_TOKENS.get(domain or "", ()))
    return {
        "domain": domain,
        "domain_title": DOMAIN_TITLES.get(domain or "", "Unclassified"),
        "matched_tokens": matched,
        "strong_candidate": bool(tokens & core),
        "master_hint_tokens": [token for token in MASTER_HINT_TOKENS if token in tokens],
    }


# --------------------------------------------------------------------------- catalog reads

CATALOG_QUERIES: tuple[tuple[str, str], ...] = (
    (
        "engine",
        "SELECT CONVERT(nvarchar(128), SERVERPROPERTY('ProductVersion')) AS engine_version, "
        "CONVERT(nvarchar(128), SERVERPROPERTY('Edition')) AS engine_edition, "
        "CONVERT(nvarchar(128), SERVERPROPERTY('Collation')) AS engine_collation",
    ),
    (
        "catalog",
        "SELECT DB_NAME() AS database_name, "
        "CONVERT(nvarchar(128), DATABASEPROPERTYEX(DB_NAME(), 'Collation')) AS database_collation",
    ),
    (
        "schemas",
        "SELECT s.name AS schema_name, s.schema_id AS schema_id FROM sys.schemas AS s "
        "ORDER BY s.name",
    ),
    (
        "tables",
        "SELECT s.name AS schema_name, t.name AS table_name, t.type_desc AS object_type, "
        "(CASE WHEN t.is_ms_shipped = 1 THEN 1 ELSE 0 END) AS is_ms_shipped "
        "FROM sys.tables AS t INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id "
        "ORDER BY s.name, t.name",
    ),
    (
        "columns",
        "SELECT s.name AS schema_name, t.name AS table_name, c.column_id AS ordinal_position, "
        "c.name AS column_name, ty.name AS data_type, c.max_length AS max_length, "
        "c.precision AS numeric_precision, c.scale AS numeric_scale, "
        "(CASE WHEN c.is_nullable = 1 THEN 1 ELSE 0 END) AS is_nullable, "
        "(CASE WHEN c.is_identity = 1 THEN 1 ELSE 0 END) AS is_identity, "
        "(CASE WHEN c.is_computed = 1 THEN 1 ELSE 0 END) AS is_computed, "
        "(CASE WHEN c.system_type_id = 189 THEN 1 ELSE 0 END) AS is_rowversion, "
        "(CASE WHEN c.is_rowguidcol = 1 THEN 1 ELSE 0 END) AS is_rowguidcol, "
        "(CASE WHEN c.user_type_id <> c.system_type_id THEN 1 ELSE 0 END) AS is_user_defined_type, "
        "(CASE WHEN c.is_filestream = 1 THEN 1 ELSE 0 END) AS is_filestream "
        "FROM sys.columns AS c "
        "INNER JOIN sys.tables AS t ON t.object_id = c.object_id "
        "INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id "
        "INNER JOIN sys.types AS ty ON ty.user_type_id = c.user_type_id "
        "ORDER BY s.name, t.name, c.column_id",
    ),
    (
        "key_constraints",
        "SELECT s.name AS schema_name, t.name AS table_name, kc.name AS constraint_name, "
        "kc.type_desc AS constraint_type, col.name AS column_name, ic.key_ordinal AS key_ordinal, "
        "(CASE WHEN ic.is_descending_key = 1 THEN 1 ELSE 0 END) AS is_descending "
        "FROM sys.key_constraints AS kc "
        "INNER JOIN sys.tables AS t ON t.object_id = kc.parent_object_id "
        "INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id "
        "INNER JOIN sys.index_columns AS ic "
        "ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id "
        "INNER JOIN sys.columns AS col "
        "ON col.object_id = ic.object_id AND col.column_id = ic.column_id "
        "ORDER BY s.name, t.name, kc.name, ic.key_ordinal",
    ),
    (
        "foreign_keys",
        "SELECT fk.name AS constraint_name, ps.name AS parent_schema, pt.name AS parent_table, "
        "pc.name AS parent_column, rs.name AS referenced_schema, rt.name AS referenced_table, "
        "rc.name AS referenced_column, fkc.constraint_column_id AS ordinal_position "
        "FROM sys.foreign_keys AS fk "
        "INNER JOIN sys.foreign_key_columns AS fkc ON fkc.constraint_object_id = fk.object_id "
        "INNER JOIN sys.tables AS pt ON pt.object_id = fk.parent_object_id "
        "INNER JOIN sys.schemas AS ps ON ps.schema_id = pt.schema_id "
        "INNER JOIN sys.columns AS pc "
        "ON pc.object_id = fkc.parent_object_id AND pc.column_id = fkc.parent_column_id "
        "INNER JOIN sys.tables AS rt ON rt.object_id = fk.referenced_object_id "
        "INNER JOIN sys.schemas AS rs ON rs.schema_id = rt.schema_id "
        "INNER JOIN sys.columns AS rc "
        "ON rc.object_id = fkc.referenced_object_id AND rc.column_id = fkc.referenced_column_id "
        "ORDER BY fk.name, fkc.constraint_column_id",
    ),
    (
        "indexes",
        "SELECT s.name AS schema_name, t.name AS table_name, i.name AS index_name, "
        "i.type_desc AS index_type, "
        "(CASE WHEN i.is_unique = 1 THEN 1 ELSE 0 END) AS is_unique, "
        "(CASE WHEN i.is_primary_key = 1 THEN 1 ELSE 0 END) AS is_primary_key, "
        "(CASE WHEN i.is_unique_constraint = 1 THEN 1 ELSE 0 END) AS is_unique_constraint, "
        "col.name AS column_name, ic.key_ordinal AS key_ordinal, "
        "(CASE WHEN ic.is_included_column = 1 THEN 1 ELSE 0 END) AS is_included "
        "FROM sys.indexes AS i "
        "INNER JOIN sys.tables AS t ON t.object_id = i.object_id "
        "INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id "
        "INNER JOIN sys.index_columns AS ic "
        "ON ic.object_id = i.object_id AND ic.index_id = i.index_id "
        "INNER JOIN sys.columns AS col "
        "ON col.object_id = ic.object_id AND col.column_id = ic.column_id "
        "WHERE i.name IS NOT NULL "
        "ORDER BY s.name, t.name, i.name, ic.key_ordinal, ic.index_column_id",
    ),
)


def cell_value(row: Sequence[Any], index: int) -> Any:
    return row[index] if index < len(row) else None


def text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").strip()
    return str(value).strip()


def integer_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def flag_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return text_value(value).lower() in {"1", "true", "yes", "y", "t"}


def row_tuple(row: Any) -> tuple[Any, ...]:
    if isinstance(row, tuple):
        return row
    if isinstance(row, list):
        return tuple(row)
    try:
        return tuple(row)
    except TypeError:
        return (row,)


def execute_read_only(connection: Any, statement: str) -> list[tuple[Any, ...]]:
    """Assert that a statement is read-only, execute it, and return plain tuples."""
    assert_read_only(statement)
    cursor = connection.cursor()
    try:
        cursor.execute(statement)
        rows = cursor.fetchall()
    finally:
        close = getattr(cursor, "close", None)
        if callable(close):
            close()
    return [row_tuple(row) for row in rows]


def inspect_metadata(connection: Any) -> dict[str, Any]:
    """Run the fixed catalog reads over an open connection and return value-free metadata facts."""
    raw: dict[str, list[tuple[Any, ...]]] = {}
    for name, statement in CATALOG_QUERIES:
        raw[name] = execute_read_only(connection, statement)
    catalog = shape_metadata(raw)
    catalog["executed_query_names"] = [name for name, _ in CATALOG_QUERIES]
    catalog["executed_statement_count"] = len(CATALOG_QUERIES)
    catalog["read_only_guard_checks"] = len(CATALOG_QUERIES)
    catalog["statements_outside_catalog"] = 0
    return catalog


def shape_metadata(raw: Mapping[str, Sequence[Sequence[Any]]]) -> dict[str, Any]:
    """Turn raw catalog rows into value-free schema facts: names, types and flags only."""
    engine_rows = list(raw.get("engine", ()))
    catalog_rows = list(raw.get("catalog", ()))
    engine_first: Sequence[Any] = engine_rows[0] if engine_rows else ()
    catalog_first: Sequence[Any] = catalog_rows[0] if catalog_rows else ()
    schemas = sorted({text_value(cell_value(row, 0)) for row in raw.get("schemas", ())} - {""})

    table_keys: set[tuple[str, str]] = set()
    shipped_skipped = 0
    seen_table_rows = 0
    for row in raw.get("tables", ()):
        seen_table_rows += 1
        if flag_value(cell_value(row, 3)):
            shipped_skipped += 1
            continue
        name = text_value(cell_value(row, 1))
        if not name:
            continue
        table_keys.add((text_value(cell_value(row, 0)), name))
    sorted_names = sorted(table_keys)

    columns: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in raw.get("columns", ()):
        key = (text_value(cell_value(row, 0)), text_value(cell_value(row, 1)))
        if key not in table_keys:
            continue
        columns.setdefault(key, []).append(
            {
                "name": text_value(cell_value(row, 3)),
                "ordinal_position": integer_value(cell_value(row, 2)),
                "data_type": text_value(cell_value(row, 4)),
                "max_length": integer_value(cell_value(row, 5)),
                "numeric_precision": integer_value(cell_value(row, 6)),
                "numeric_scale": integer_value(cell_value(row, 7)),
                "is_nullable": flag_value(cell_value(row, 8)),
                "is_identity": flag_value(cell_value(row, 9)),
                "is_computed": flag_value(cell_value(row, 10)),
                "is_rowversion": flag_value(cell_value(row, 11)),
                "is_rowguidcol": flag_value(cell_value(row, 12)),
                "is_user_defined_type": flag_value(cell_value(row, 13)),
                "is_filestream": flag_value(cell_value(row, 14)),
            }
        )
    for key in columns:
        columns[key].sort(key=lambda item: item["ordinal_position"])

    key_constraints: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for row in raw.get("key_constraints", ()):
        key = (text_value(cell_value(row, 0)), text_value(cell_value(row, 1)))
        if key not in table_keys:
            continue
        name = text_value(cell_value(row, 2))
        entry = key_constraints.setdefault(key, {}).setdefault(
            name,
            {"name": name, "constraint_type": text_value(cell_value(row, 3)), "columns": []},
        )
        entry["columns"].append(
            {
                "name": text_value(cell_value(row, 4)),
                "key_ordinal": integer_value(cell_value(row, 5)),
                "is_descending": flag_value(cell_value(row, 6)),
            }
        )

    foreign_keys: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for row in raw.get("foreign_keys", ()):
        key = (text_value(cell_value(row, 1)), text_value(cell_value(row, 2)))
        name = text_value(cell_value(row, 0))
        entry = foreign_keys.setdefault(key, {}).setdefault(name, {"name": name, "columns": []})
        entry["columns"].append(
            {
                "parent_column": text_value(cell_value(row, 3)),
                "referenced_schema": text_value(cell_value(row, 4)),
                "referenced_table": text_value(cell_value(row, 5)),
                "referenced_column": text_value(cell_value(row, 6)),
                "ordinal_position": integer_value(cell_value(row, 7)),
            }
        )

    indexes: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for row in raw.get("indexes", ()):
        key = (text_value(cell_value(row, 0)), text_value(cell_value(row, 1)))
        if key not in table_keys:
            continue
        name = text_value(cell_value(row, 2))
        entry = indexes.setdefault(key, {}).setdefault(
            name,
            {
                "name": name,
                "index_type": text_value(cell_value(row, 3)),
                "is_unique": flag_value(cell_value(row, 4)),
                "is_primary_key": flag_value(cell_value(row, 5)),
                "is_unique_constraint": flag_value(cell_value(row, 6)),
                "columns": [],
            },
        )
        entry["columns"].append(
            {
                "name": text_value(cell_value(row, 7)),
                "key_ordinal": integer_value(cell_value(row, 8)),
                "is_included": flag_value(cell_value(row, 9)),
            }
        )

    return assemble_catalog(
        {
            "engine_first": engine_first,
            "catalog_first": catalog_first,
            "schemas": schemas,
            "sorted_names": sorted_names,
            "seen_table_rows": seen_table_rows,
            "shipped_skipped": shipped_skipped,
            "columns": columns,
            "key_constraints": key_constraints,
            "foreign_keys": foreign_keys,
            "indexes": indexes,
        }
    )


def key_summary(entry: Mapping[str, Any] | None, limit: int = MAX_KEY_ENTRIES_PER_TABLE) -> dict[str, Any] | None:
    """Reduce one key constraint to a bounded, value-free summary."""
    if entry is None:
        return None
    columns = list(entry["columns"])
    return {
        "name": entry["name"],
        "constraint_type": entry.get("constraint_type", ""),
        "columns": [item["name"] for item in columns[:limit]],
        "columns_truncated": len(columns) > limit,
    }


def index_summary(entry: Mapping[str, Any], limit: int = MAX_INDEX_ENTRIES_PER_TABLE) -> dict[str, Any]:
    """Reduce one index to a bounded, value-free summary."""
    columns = list(entry["columns"])
    return {
        "name": entry["name"],
        "index_type": entry.get("index_type", ""),
        "is_unique": bool(entry.get("is_unique")),
        "is_primary_key": bool(entry.get("is_primary_key")),
        "is_unique_constraint": bool(entry.get("is_unique_constraint")),
        "key_columns": [item["name"] for item in columns if not item.get("is_included")][:limit],
        "included_columns": [item["name"] for item in columns if item.get("is_included")][:limit],
        "columns_truncated": len(columns) > limit,
    }


def foreign_key_summary(
    entry: Mapping[str, Any], limit: int = MAX_FOREIGN_KEYS_PER_TABLE
) -> dict[str, Any]:
    """Reduce one foreign key to a bounded, value-free summary."""
    columns = sorted(entry["columns"], key=lambda item: item.get("ordinal_position", 0))
    referenced = ""
    if columns:
        referenced = f"{columns[0]['referenced_schema']}.{columns[0]['referenced_table']}"
    return {
        "name": entry["name"],
        "referenced_table": referenced,
        "parent_columns": [item["parent_column"] for item in columns[:limit]],
        "referenced_columns": [item["referenced_column"] for item in columns[:limit]],
        "columns_truncated": len(columns) > limit,
    }


def assemble_catalog(grouped: Mapping[str, Any]) -> dict[str, Any]:
    """Build the value-free catalog section, keeping detail bounded and marking every truncation."""
    columns: dict[tuple[str, str], list[dict[str, Any]]] = dict(grouped["columns"])
    key_constraints: dict[tuple[str, str], dict[str, dict[str, Any]]] = dict(
        grouped["key_constraints"]
    )
    foreign_keys: dict[tuple[str, str], dict[str, dict[str, Any]]] = dict(grouped["foreign_keys"])
    indexes: dict[tuple[str, str], dict[str, dict[str, Any]]] = dict(grouped["indexes"])
    sorted_names: list[tuple[str, str]] = list(grouped["sorted_names"])
    classifications = {key: classify_table(key[1]) for key in sorted_names}

    domain_map: dict[str, Any] = {}
    for domain in DOMAIN_ORDER:
        strong = [
            f"{schema}.{name}"
            for schema, name in sorted_names
            if classifications[(schema, name)]["domain"] == domain
            and classifications[(schema, name)]["strong_candidate"]
        ]
        candidates = [
            f"{schema}.{name}"
            for schema, name in sorted_names
            if classifications[(schema, name)]["domain"] == domain
        ]
        domain_map[domain] = {
            "title": DOMAIN_TITLES[domain],
            "monitor_domain": domain in MASTER_DOMAINS,
            "status": (
                "resolved"
                if strong
                else ("candidates_need_review" if candidates else "absent_from_catalog")
            ),
            "answered": bool(strong or not candidates),
            "strong_candidate_tables": strong,
            "candidate_tables": candidates,
            "candidate_count": len(candidates),
            "strong_candidate_count": len(strong),
            "resolved": bool(strong),
            "note": (
                "Candidates are derived from catalog table names only. A domain with a strong candidate "
                "is resolved, a domain with no candidate at all is reported as absent from the inspected "
                "catalog, and anything in between stays explicitly unresolved for GPT review. The "
                "authoritative mapping to the planned DDL is owned by NEWAPP-005 and the Human Gate."
            ),
        }

    detail_wanted = [
        key
        for key in sorted_names
        if classifications[key]["strong_candidate"]
        or classifications[key]["master_hint_tokens"]
        or classifications[key]["domain"] is not None
    ]
    detail_allowed = set(detail_wanted[:MAX_DETAILED_TABLES])
    truncation: dict[str, Any] = {
        "max_tables": MAX_TABLES,
        "max_detailed_tables": MAX_DETAILED_TABLES,
        "max_columns_per_table": MAX_COLUMNS_PER_TABLE,
        "max_index_entries_per_table": MAX_INDEX_ENTRIES_PER_TABLE,
        "max_foreign_keys_per_table": MAX_FOREIGN_KEYS_PER_TABLE,
        "tables_truncated": len(sorted_names) > MAX_TABLES,
        "detailed_tables_truncated": len(detail_wanted) > MAX_DETAILED_TABLES,
        "columns_truncated_tables": [],
        "indexes_truncated_tables": [],
        "foreign_keys_truncated_tables": [],
    }

    entries: list[dict[str, Any]] = []
    for schema, name in sorted_names[:MAX_TABLES]:
        key = (schema, name)
        classification = classifications[key]
        table_columns = columns.get(key, [])
        constraint_entries = sorted(
            key_constraints.get(key, {}).values(), key=lambda item: item["name"]
        )
        primary = next(
            (
                item
                for item in constraint_entries
                if "PRIMARY" in str(item.get("constraint_type", "")).upper()
            ),
            None,
        )
        detailed = key in detail_allowed
        entry: dict[str, Any] = {
            "schema": schema,
            "table": name,
            "qualified_name": f"{schema}.{name}",
            "classification": classification,
            "detailed": detailed,
            "column_count": len(table_columns),
            "primary_key": key_summary(primary),
            "key_constraint_count": len(constraint_entries),
            "index_count": len(indexes.get(key, {})),
            "foreign_key_out_count": len(foreign_keys.get(key, {})),
            "concurrency_columns": [
                {
                    "name": column["name"],
                    "data_type": column["data_type"],
                    "role": "rowversion" if column["is_rowversion"] else "rowguid",
                }
                for column in table_columns
                if column["is_rowversion"] or column["is_rowguidcol"]
            ],
        }
        if detailed:
            entry["columns"] = table_columns[:MAX_COLUMNS_PER_TABLE]
            entry["columns_truncated"] = len(table_columns) > MAX_COLUMNS_PER_TABLE
            if entry["columns_truncated"]:
                truncation["columns_truncated_tables"].append(entry["qualified_name"])
            entry["unique_constraints"] = [
                key_summary(item) for item in constraint_entries if item is not primary
            ][:MAX_KEY_ENTRIES_PER_TABLE]
            index_entries = sorted(indexes.get(key, {}).values(), key=lambda item: item["name"])
            entry["indexes"] = [
                index_summary(item) for item in index_entries[:MAX_INDEX_ENTRIES_PER_TABLE]
            ]
            entry["indexes_truncated"] = len(index_entries) > MAX_INDEX_ENTRIES_PER_TABLE
            if entry["indexes_truncated"]:
                truncation["indexes_truncated_tables"].append(entry["qualified_name"])
            fk_entries = sorted(foreign_keys.get(key, {}).values(), key=lambda item: item["name"])
            entry["foreign_keys_out"] = [
                foreign_key_summary(item) for item in fk_entries[:MAX_FOREIGN_KEYS_PER_TABLE]
            ]
            entry["foreign_keys_truncated"] = len(fk_entries) > MAX_FOREIGN_KEYS_PER_TABLE
            if entry["foreign_keys_truncated"]:
                truncation["foreign_keys_truncated_tables"].append(entry["qualified_name"])
        entries.append(entry)

    with_rowversion = sorted(
        {
            entry["qualified_name"]
            for entry in entries
            if any(column["role"] == "rowversion" for column in entry["concurrency_columns"])
        }
    )
    without_concurrency = sorted(
        entry["qualified_name"] for entry in entries if not entry["concurrency_columns"]
    )
    engine_first: Sequence[Any] = grouped["engine_first"]
    catalog_first: Sequence[Any] = grouped["catalog_first"]
    return {
        "database": {
            "name": text_value(cell_value(catalog_first, 0)),
            "collation": text_value(cell_value(catalog_first, 1)),
        },
        "engine": {
            "version": text_value(cell_value(engine_first, 0)),
            "edition": text_value(cell_value(engine_first, 1)),
            "collation": text_value(cell_value(engine_first, 2)),
        },
        "schemas": grouped["schemas"],
        "schema_count": len(grouped["schemas"]),
        "table_count": len(sorted_names),
        "table_row_count": grouped["seen_table_rows"],
        "tables_skipped_ms_shipped": grouped["shipped_skipped"],
        "column_count": sum(len(value) for value in columns.values()),
        "index_count": sum(len(value) for value in indexes.values()),
        "key_constraint_count": sum(len(value) for value in key_constraints.values()),
        "foreign_key_count": sum(len(value) for value in foreign_keys.values()),
        "tables": entries,
        "domain_map": domain_map,
        "unclassified_master_hint_tables": [
            f"{schema}.{name}"
            for schema, name in sorted_names
            if classifications[(schema, name)]["domain"] is None
            and classifications[(schema, name)]["master_hint_tokens"]
        ],
        "concurrency": {
            "tables_with_rowversion": with_rowversion,
            "tables_without_concurrency_column": without_concurrency,
            "rowversion_table_count": len(with_rowversion),
        },
        "truncation": truncation,
    }


# --------------------------------------------------------------------------- planned DDL inventory

NEUTRAL_KEY_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*Key\b|\bTenantId\b")
MAX_KEY_LINES_PER_NAME = 40


def neutral_key_inventory(text: str) -> dict[str, Any]:
    """Inventory neutral shared-key references in the planned DDL: names, counts and lines only."""
    counts: dict[str, int] = {}
    sites: dict[str, list[int]] = {}
    occurrence_count = 0
    line_numbers_truncated = False
    for number, line in enumerate(str(text).splitlines(), start=1):
        for match in NEUTRAL_KEY_PATTERN.finditer(line):
            name = match.group(0)
            counts[name] = counts.get(name, 0) + 1
            occurrence_count += 1
            bucket = sites.setdefault(name, [])
            if len(bucket) < MAX_KEY_LINES_PER_NAME:
                bucket.append(number)
            else:
                line_numbers_truncated = True
    names = sorted(counts)
    return {
        "names": names,
        "name_count": len(names),
        "counts": {name: counts[name] for name in names},
        "line_numbers": {name: sites[name] for name in names},
        "occurrence_count": occurrence_count,
        "line_numbers_truncated": line_numbers_truncated,
        "values_recorded": False,
    }


def load_ddl_inventory(root: Path, relative: str = DDL_RELATIVE_PATH) -> dict[str, Any]:
    """Read the planned app-schema DDL read-only and inventory its neutral key references."""
    path = root / relative
    if not path.is_file():
        return {
            "available": False,
            "source": relative,
            "reason": "planned DDL file is not present at the expected path",
        }
    inventory = neutral_key_inventory(path.read_text(encoding="utf-8-sig", errors="replace"))
    inventory.update({"available": True, "source": relative, "read_only": True})
    return inventory


# --------------------------------------------------------------------------- driver and connection

SQLSTATE_CATEGORIES: dict[str, str] = {
    "08001": "server_unreachable",
    "08004": "server_rejected_connection",
    "08s01": "network_or_transport_failure",
    "28000": "login_failed_or_not_authenticated",
    "18456": "login_failed",
    "4060": "database_not_accessible",
    "40615": "client_ip_not_allowed",
    "42000": "statement_or_permission_denied",
    "hyt00": "login_timeout",
    "hyt01": "connection_timeout",
    "im002": "odbc_driver_or_data_source_not_found",
    "im003": "odbc_driver_load_failure",
    "im004": "odbc_driver_load_failure",
    "im005": "odbc_driver_incompatible",
    "im006": "odbc_driver_manager_failure",
    "hy000": "unclassified_driver_error",
    "hy104": "invalid_attribute_value",
}
SQLSTATE_PREFIX_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("08", "network_or_transport_failure"),
    ("28", "login_failed_or_not_authenticated"),
    ("hyt", "timeout"),
    ("im", "odbc_driver_or_manager_failure"),
    ("42", "statement_or_permission_denied"),
    ("40", "resource_or_deadlock_error"),
)


def classify_connection_error(exc: BaseException) -> dict[str, Any]:
    """Describe a driver failure by class, SQLSTATE and category without recording any message text.

    Only a five-character alphanumeric SQLSTATE is ever read out of the exception, so free-text driver
    messages (which may quote the server, the login or a value) can never reach the report.
    """
    args = getattr(exc, "args", ())
    candidate = args[0].strip() if args and isinstance(args[0], str) else ""
    sqlstate = candidate if re.fullmatch(r"[0-9A-Za-z]{5}", candidate) else ""
    key = sqlstate.lower()
    if key in SQLSTATE_CATEGORIES:
        category = SQLSTATE_CATEGORIES[key]
    else:
        category = "unclassified_driver_error"
        for prefix, name in SQLSTATE_PREFIX_CATEGORIES:
            if key.startswith(prefix):
                category = name
                break
    return {
        "error_class": type(exc).__name__,
        "sqlstate": sqlstate or "not_reported",
        "category": category,
        "argument_count": len(args),
        "message_recorded": False,
    }


def interpreter_facts() -> dict[str, Any]:
    """Describe the interpreter that performs the inspection without exposing local directory paths."""
    return {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "executable_name": Path(sys.executable).name,
    }


def odbc_driver_names(module: Any) -> list[str]:
    """List the ODBC driver names the host advertises, tolerating a module without the helper."""
    getter = getattr(module, "drivers", None)
    if not callable(getter):
        return []
    try:
        return [str(name) for name in getter()]
    except Exception:
        return []


def describe_driver_module(module: Any) -> dict[str, Any]:
    """Describe an available driver module using structural facts only."""
    return {
        "module": DRIVER_MODULE_NAME,
        "available": True,
        "version": str(getattr(module, "version", "unknown")),
        "interpreter": interpreter_facts(),
        "odbc_driver_names": odbc_driver_names(module),
        "reason_category": None,
        "error_class": None,
    }


def load_driver_module() -> tuple[Any | None, dict[str, Any]]:
    """Import the optional ODBC driver module and report only structural facts about it."""
    try:
        import pyodbc  # noqa: PLC0415 - optional dependency, resolved at run time
    except Exception as exc:  # pragma: no cover - depends on the host interpreter
        return None, {
            "module": DRIVER_MODULE_NAME,
            "available": False,
            "version": "",
            "interpreter": interpreter_facts(),
            "odbc_driver_names": [],
            "reason_category": "driver_module_not_installed",
            "error_class": type(exc).__name__,
        }
    return pyodbc, describe_driver_module(pyodbc)


def unavailable_error(category: str, error_class: str = "NoneType") -> dict[str, Any]:
    """Build a value-free failure record for an inspection that never reached the server."""
    return {
        "error_class": error_class,
        "sqlstate": "not_reported",
        "category": category,
        "argument_count": 0,
        "message_recorded": False,
    }


def open_read_only_connection(
    connection_string: Any,
    *,
    driver_module: Any | None = None,
    driver_names: Sequence[str] | None = None,
    login_timeout: int = LOGIN_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Open one autocommit connection for catalog reads only.

    The translated ODBC target is held in memory for the duration of this call and dropped before the
    function returns, so it can never reach the report, a log line or an exception message.
    """
    if driver_names is None:
        getter = getattr(driver_module, "drivers", None)
        try:
            resolved_names = [str(name) for name in getter()] if callable(getter) else []
        except Exception:
            resolved_names = []
    else:
        resolved_names = [str(name) for name in driver_names]

    built = build_odbc_target(connection_string, resolved_names)
    facts: dict[str, Any] = {
        "attempted": False,
        "outcome": "skipped",
        "elapsed_seconds": 0.0,
        "login_timeout_seconds": int(login_timeout),
        "autocommit": True,
        "transaction_left_open": False,
        "error": None,
        "target": built["facts"],
    }
    if driver_module is None:
        facts["error"] = unavailable_error("driver_module_not_installed")
        return {"status": "unavailable", "connection": None, "facts": facts}
    if not built["target"]:
        facts["error"] = unavailable_error("connection_string_not_usable")
        return {"status": "unavailable", "connection": None, "facts": facts}
    if not built["facts"]["selected_driver"]:
        facts["error"] = unavailable_error("odbc_driver_not_installed")
        return {"status": "unavailable", "connection": None, "facts": facts}

    facts["attempted"] = True
    started = time.monotonic()
    try:
        connection = driver_module.connect(
            built["target"], autocommit=True, timeout=int(login_timeout)
        )
    except Exception as exc:
        facts["outcome"] = "failed"
        facts["elapsed_seconds"] = round(time.monotonic() - started, 3)
        facts["error"] = classify_connection_error(exc)
        return {"status": "unavailable", "connection": None, "facts": facts}
    finally:
        built["target"] = None
    facts["outcome"] = "connected"
    facts["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return {"status": "connected", "connection": connection, "facts": facts}


def resolve_connection_value(
    env_path: Path,
    environ: Mapping[str, str] | None = None,
    key: str = CONNECTION_KEY,
) -> tuple[str | None, str]:
    """Return the declared shared-connection value and its source label, in memory only.

    The running process environment wins over the file, because the controller exports ``.env`` into
    the executor environment before a task starts. Callers must never record, print or store the
    returned value.
    """
    environment = environ if environ is not None else os.environ
    from_process = environment.get(key) if environment is not None else None
    if isinstance(from_process, str) and from_process.strip():
        return from_process.strip(), "process_environment"
    if env_path.is_file():
        value = read_environment_values(env_path).get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), ".env"
    return None, "not_declared"


# --------------------------------------------------------------------------- evidence guards

def normalize_for_path_guard(value: str) -> str:
    """Mirror the controller path guard normalization used by ``common.path_matches``.

    Separators are unified to ``/``, only *exact* leading ``./`` prefixes are removed (one prefix at a
    time, exactly like the controller loop) and the result is lower-cased for ``fnmatch``. The leading
    dot of a real dot-directory such as ``.ai/`` is preserved, so
    ``.ai/generated/NEWAPP-003-newerp-schema-map.json`` still matches ``.ai/generated/**``.
    """
    normalized = str(value).replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lower()


def controller_patterns(
    root: Path, section: str, key: str, fallback: Sequence[str]
) -> tuple[list[str], str]:
    """Read one pattern list from the controller configuration, failing closed to defaults."""
    path = root / CONFIG_SOURCE
    fallback_source = "built-in artifact defaults"
    try:
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return list(fallback), fallback_source
    patterns = settings.get(section, {}).get(key)
    if not isinstance(patterns, list) or not patterns:
        return list(fallback), fallback_source
    return [str(pattern) for pattern in patterns], f"{CONFIG_SOURCE}#{section}.{key}"


def path_guard_compatibility(
    paths: Sequence[str], allowed: Sequence[str], protected: Sequence[str], allowed_source: str
) -> dict[str, Any]:
    """Report which executor paths the controller path guard accepts and which protected path matched.

    The mirror in :func:`normalize_for_path_guard` is compared with the controller module by
    ``tests/schema/test_newerp_schema.py`` instead of importing or editing controller code.
    """
    entries: list[dict[str, Any]] = []
    protected_touched: list[dict[str, Any]] = []
    for path in paths:
        normalized = normalize_for_path_guard(path)
        matched = [
            str(pattern)
            for pattern in allowed
            if fnmatch.fnmatch(normalized, str(pattern).replace("\\", "/").lower())
        ]
        blocked = [
            str(pattern)
            for pattern in protected
            if fnmatch.fnmatch(normalized, str(pattern).replace("\\", "/").lower())
        ]
        entries.append(
            {
                "path": str(path),
                "normalized_for_guard": normalized,
                "accepted": bool(matched),
                "matched_patterns": matched,
            }
        )
        if blocked:
            protected_touched.append({"path": str(path), "matched_protected_patterns": blocked})
    return {
        "allowed_patterns_source": allowed_source,
        "allowed_patterns": [str(pattern) for pattern in allowed],
        "normalization": (
            "common.path_matches applies path.replace('\\\\','/') and removes only exact leading "
            "'./' prefixes before fnmatch, so dot-directory patterns are preserved"
        ),
        "paths": entries,
        "all_paths_accepted": bool(entries) and all(entry["accepted"] for entry in entries),
        "protected_paths_touched": protected_touched,
        "no_protected_path_touched": not protected_touched,
    }


def scanner_module(root: Path | None = None) -> Any | None:
    """Load the repository secret scanner as a read-only helper module (cached, optional)."""
    path = (Path(root) if root is not None else REPOSITORY_ROOT) / SCANNER_RELATIVE_PATH
    key = str(path)
    if key in _SCANNER_CACHE:
        return _SCANNER_CACHE[key]
    module: Any | None = None
    if path.is_file():
        specification = importlib.util.spec_from_file_location("newapp_secret_scan_for_schema_map", path)
        if specification and specification.loader:
            module = importlib.util.module_from_spec(specification)
            # Dataclasses resolve their own module during class creation.
            sys.modules[specification.name] = module
            specification.loader.exec_module(module)
    _SCANNER_CACHE[key] = module
    return module


def scanner_self_check(texts: Mapping[str, str]) -> dict[str, Any]:
    """Apply the repository scanner content rules to the rendered artifacts before publication."""
    module = scanner_module()
    checked = sorted(texts)
    if module is None or not hasattr(module, "text_rule_findings"):
        return {
            "available": False,
            "scanner": SCANNER_RELATIVE_PATH,
            "reason": "the repository scanner could not be loaded",
            "scope": "content rules of the repository scanner applied to the generated artifacts",
            "checked_paths": checked,
            "findings": [],
            "findings_count": 0,
            "values_recorded": False,
            "status": "unavailable",
        }
    findings: list[dict[str, Any]] = []
    for relative in checked:
        findings.extend(module.text_rule_findings(relative, texts[relative]))
    return {
        "available": True,
        "scanner": SCANNER_RELATIVE_PATH,
        "scope": "content rules of the repository scanner applied to the generated artifacts",
        "checked_paths": checked,
        "findings": findings,
        "findings_count": len(findings),
        "values_recorded": False,
        "status": "passed" if not findings else "failed",
    }


# --------------------------------------------------------------------------- facts and report

LIMITATIONS: tuple[str, ...] = (
    "Table classification uses catalog table names only, so a table whose name does not describe its domain is reported as a weak or unmatched candidate rather than being forced into a domain.",
    "Column, index and foreign-key detail is capped by the MAX_* constants and every truncation is recorded in the truncation section of the report.",
    "The keyword parser splits a declared connection string on ';' without interpreting quoted semicolons, which can only affect the reported keyword names, never a value.",
    "When the ODBC driver module or the shared server is unavailable, every domain is reported as an explicit unknown together with a value-free failure category; no table name is inferred from the planned DDL.",
    "Only the server-side connection declared for this workspace is inspected. A different shared server reached by another deployment is out of scope.",
    "The map is a read-only snapshot taken at one moment: objects created after this run are not represented, and no shared object was changed, locked or migrated.",
    "agent.env, secrets, signing material and the OSS credentials are never opened by this module.",
)


def modified_ns(path: Path) -> int | None:
    """Return the file write timestamp; reading never changes it, so a comparison proves read-only use."""
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def collect_facts(
    root: Path,
    *,
    generated_at: str,
    env_file: str = ENV_FILE,
    environ: Mapping[str, str] | None = None,
    driver_module: Any | None = None,
    driver_facts: Mapping[str, Any] | None = None,
    connect: bool = True,
    login_timeout: int = LOGIN_TIMEOUT_SECONDS,
    payload_received: bool = False,
    payload_sources: Sequence[str] = (),
    executor_paths: Sequence[str] = (),
    report_paths: Sequence[str] = (),
    doc_paths: Sequence[str] = (),
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Collect every value-free fact the report and the document are built from.

    Returns ``(facts, needles)``. ``facts`` is publishable and never carries a declared value.
    ``needles`` is the in-memory credential material that the publication guard must reject; it is
    handed to :func:`finalize_report` and is never stored inside ``facts`` or the report.
    """
    env_path = root / env_file
    before = modified_ns(env_path)
    value, source = resolve_connection_value(env_path, environ)
    needles = credential_needles(value)

    resolved_driver = driver_module
    resolved_facts: dict[str, Any] | None = dict(driver_facts) if driver_facts is not None else None
    if resolved_facts is None:
        if resolved_driver is None:
            resolved_driver, resolved_facts = load_driver_module()
        else:
            resolved_facts = describe_driver_module(resolved_driver)

    inspection: dict[str, Any] = {
        "status": "unavailable",
        "connection_attempted": False,
        "connection_source": source,
        "declared_setting_present": value is not None,
        "catalog_read_failed": None,
        "connection_closed": None,
        "read_statement_count": 0,
        "unavailable_reasons": [],
        "driver": resolved_facts,
        "connection": None,
        "connection_target": None,
        "environment_file_read_only": True,
        "environment_file_modified_time_unchanged_during_run": True,
        "environment_file": env_file,
    }
    catalog: dict[str, Any] | None = None
    if value is None:
        inspection["unavailable_reasons"].append(
            "the shared database connection setting is not declared in the process environment or in "
            + env_file
        )
    elif not connect:
        inspection["unavailable_reasons"].append(
            "the read-only connection attempt was skipped by option"
        )
        inspection["connection_target"] = build_odbc_target(
            value, resolved_facts["odbc_driver_names"]
        )["facts"]
    else:
        opened = open_read_only_connection(
            value,
            driver_module=resolved_driver,
            driver_names=resolved_facts["odbc_driver_names"],
            login_timeout=login_timeout,
        )
        inspection["connection"] = opened["facts"]
        inspection["connection_attempted"] = bool(opened["facts"]["attempted"])
        inspection["connection_target"] = opened["facts"]["target"]
        connection = opened["connection"]
        if connection is None:
            inspection["unavailable_reasons"].append(
                "the read-only connection attempt failed: "
                + str(opened["facts"]["error"]["category"])
            )
        else:
            try:
                catalog = inspect_metadata(connection)
                inspection["status"] = "inspected"
                inspection["read_statement_count"] = catalog["executed_statement_count"]
            except Exception as exc:
                inspection["catalog_read_failed"] = {
                    "error_class": type(exc).__name__,
                    "category": "catalog_read_failed",
                    "message_recorded": False,
                }
                inspection["unavailable_reasons"].append("the catalog reads did not complete")
            finally:
                close = getattr(connection, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
                inspection["connection_closed"] = True
    value = None  # drop the in-memory reference before anything is rendered

    allowed, allowed_source = controller_patterns(
        root, "paths", "executor_allowed", ALLOWED_ARTIFACT_PATTERNS
    )
    protected, _ = controller_patterns(root, "paths", "protected", ())
    inspection["environment_file_modified_time_unchanged_during_run"] = before == modified_ns(env_path)
    facts: dict[str, Any] = {
        "generated_at": generated_at,
        "inspection": inspection,
        "catalog": catalog,
        "planned_ddl": load_ddl_inventory(root),
        "payload": {
            "controller_payload_section_present": payload_received,
            "sources": list(payload_sources),
            "note": (
                "Task identity, GPT plan, dependency ordering and allowed paths were read from the "
                "controller-owned records listed in sources. No queue, approval, branch or state file "
                "was written by the executor."
            ),
        },
        "executor_paths": list(executor_paths),
        "report_paths": list(report_paths),
        "doc_paths": list(doc_paths),
        "allowed_paths": allowed,
        "allowed_paths_source": allowed_source,
        "protected_paths": protected,
    }
    return facts, needles


def build_report(facts: dict[str, Any]) -> dict[str, Any]:
    """Assemble the value-free NEWAPP-003 shared schema map from collected facts."""
    inspection = facts["inspection"]
    catalog = facts["catalog"]
    target = inspection["connection_target"] or {}
    connection = inspection["connection"] or {}
    report: dict[str, Any] = {
        "task_id": TASK_ID,
        "task_title": TASK_TITLE,
        "task_phase": TASK_PHASE,
        "task_depends_on": list(TASK_DEPENDS_ON),
        "artifact": "newerp_shared_schema_map",
        "schema_version": 1,
        "generated_at": facts["generated_at"],
        "generated_by": "newapp_executor (Cline/DeepSeek)",
        "completion_authority": (
            "the GPT brain (Codex desktop / ChatGPT mobile Remote) review, never the executor"
        ),
        "executor_payload": facts["payload"],
        "safety_contract": {
            "environment_file_access": "read-only",
            "declared_setting_name": CONNECTION_KEY,
            "connection_string_recorded": False,
            "server_host_recorded": False,
            "login_recorded": False,
            "password_recorded": False,
            "row_values_recorded": False,
            "ddl_or_dml_executed": False,
            "stored_procedures_executed": False,
            "shared_objects_changed": False,
            "environment_file_written": False,
            "environment_file_modified_time_unchanged_during_run": inspection[
                "environment_file_modified_time_unchanged_during_run"
            ],
            "statements_executed": inspection["read_statement_count"],
            "statements_outside_catalog": (catalog or {}).get("statements_outside_catalog", 0),
            "read_only_guard": (
                "every statement is produced by this module from the fixed catalog table and is "
                "validated by assert_read_only before it is executed"
            ),
            "session": {
                "autocommit": connection.get("autocommit", True),
                "login_timeout_seconds": connection.get("login_timeout_seconds", LOGIN_TIMEOUT_SECONDS),
                "read_only_application_intent": target.get("read_only_intent_requested", False),
                "connection_closed": inspection["connection_closed"],
            },
            "note": (
                "Only catalog metadata is read. The shared connection declaration is translated into an "
                "in-memory ODBC target that is dropped when the call returns, so no part of it is "
                "recorded, hashed, compared with another file or rendered."
            ),
        },
        "shared_connection_configuration": {
            "declared_setting_name": CONNECTION_KEY,
            "source": inspection["connection_source"],
            "declared_setting_present": inspection["declared_setting_present"],
            "keyword_names": target.get("keyword_names", []),
            "keyword_count": target.get("keyword_count", 0),
            "odbc_keyword_names": target.get("odbc_keyword_names", []),
            "non_odbc_keyword_names": target.get("non_odbc_keyword_names", []),
            "unparsed_fragment_count": target.get("unparsed_fragment_count", 0),
            "declares_odbc_driver": target.get("declares_odbc_driver", False),
            "selected_driver": target.get("selected_driver"),
            "read_only_intent_requested": target.get("read_only_intent_requested", False),
            "shape_flags": {
                "has_server_keyword": target.get("has_server_keyword", False),
                "has_catalog_keyword": target.get("has_catalog_keyword", False),
                "has_user_keyword": target.get("has_user_keyword", False),
                "has_password_keyword": target.get("has_password_keyword", False),
                "uses_integrated_security": target.get("uses_integrated_security", False),
            },
            "note": (
                "Keyword names and shape flags only. The server, catalog, login and password values are "
                "never recorded, and the keywords that a .NET client accepts but ODBC does not are "
                "listed by name for the server-side binding work."
            ),
        },
        "inspection": inspection,
        "catalog": catalog,
        "classification_rules": {
            "domain_order": list(DOMAIN_ORDER),
            "monitored_master_domains": list(MASTER_DOMAINS),
            "core_tokens": {domain: list(tokens) for domain, tokens in CORE_DOMAIN_TOKENS.items()},
            "domain_tokens": {domain: list(tokens) for domain, tokens in DOMAIN_TOKENS.items()},
            "filters": (
                "Microsoft-shipped helper tables are excluded; camel-case, snake-case and plural names are "
                "tokenized before matching; a domain with a strong candidate is resolved, a domain with no "
                "candidate at all is reported as absent from the catalog, and a master-data-shaped table "
                "that no domain token matched is listed separately for review"
            ),
        },
        "planned_ddl_key_references": facts["planned_ddl"],
        "artifacts": {
            "report_paths": facts["report_paths"],
            "doc_paths": facts["doc_paths"],
            "executor_paths": facts["executor_paths"],
            "allowed_path_patterns_source": facts["allowed_paths_source"],
            "allowed_path_patterns": list(facts["allowed_paths"]),
            "protected_pattern_count": len(facts["protected_paths"]),
        },
        "path_guard": path_guard_compatibility(
            facts["executor_paths"],
            facts["allowed_paths"],
            facts["protected_paths"],
            facts["allowed_paths_source"],
        ),
        "limitations": list(LIMITATIONS),
    }
    report["acceptance_evidence"] = acceptance_evidence(report)
    report["unresolved"] = unresolved_items(report)
    return report


def domain_entry(report: dict[str, Any], domain: str) -> dict[str, Any]:
    """Return the reported domain facts for one domain."""
    catalog = report.get("catalog") or {}
    return (catalog.get("domain_map") or {}).get(domain) or {}


def domain_resolved(report: dict[str, Any], domain: str) -> bool:
    """Report whether a strong name candidate exists for one domain in the inspected catalog."""
    return bool(domain_entry(report, domain).get("resolved"))


def domain_answered(report: dict[str, Any], domain: str) -> bool:
    """Report whether the inspected catalog answers the domain question decisively.

    A domain is answered when a strong candidate exists or when the catalog holds no candidate at all,
    because a zero-candidate result states that the shared schema has no such table.
    """
    return bool(domain_entry(report, domain).get("answered"))


def domain_candidates_detailed(report: dict[str, Any], domain: str) -> bool:
    """Report whether every candidate table of a domain carries full metadata detail in the report."""
    catalog = report.get("catalog") or {}
    candidates = set(domain_entry(report, domain).get("candidate_tables") or [])
    if not candidates:
        return True
    detailed = {
        entry["qualified_name"] for entry in catalog.get("tables", []) if entry.get("detailed")
    }
    return candidates <= detailed


def acceptance_evidence(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Score the blueprint acceptance criteria and the plan focus areas of NEWAPP-003."""
    inspection = report["inspection"]
    catalog = report.get("catalog") or {}
    inspected = inspection["status"] == "inspected"
    master_ok = inspected and all(domain_answered(report, domain) for domain in MASTER_DOMAINS)
    focus_domains = ("dictionary", "inquiry")
    focus_ok = inspected and all(
        domain_answered(report, domain) or bool(domain_entry(report, domain).get("candidate_count"))
        for domain in focus_domains
    )
    focus_detail_ok = focus_ok and all(
        domain_candidates_detailed(report, domain) for domain in focus_domains
    )
    statements = int(report["safety_contract"]["statements_executed"] or 0)
    guard_ok = bool(
        catalog.get("statements_outside_catalog", 0) == 0
        and catalog.get("executed_statement_count", 0) == catalog.get("read_only_guard_checks", 0)
    )
    no_write_ok = bool(not report["safety_contract"]["ddl_or_dml_executed"] and guard_ok)
    return [
        {
            "criterion": (
                "Actual customer, supplier, user and tenant/company master tables are identified."
            ),
            "evidence": (
                "every monitored master domain is inspected and either resolved by a strong catalog-name "
                "candidate or reported as absent from the catalog; the primary key, key constraints and "
                "concurrency columns of each candidate are recorded"
            ),
            "satisfied": bool(master_ok),
        },
        {
            "criterion": (
                "Dictionary and inquiry-related tables plus keys, indexes and rowversion columns are "
                "identified."
            ),
            "evidence": (
                "dictionary- and inquiry-related candidates (or their absence) are recorded with their "
                "columns, keys, indexes and concurrency columns, so the metadata is complete even where "
                "the authoritative table still needs GPT confirmation"
            ),
            "satisfied": bool(focus_detail_ok),
        },
        {
            "criterion": "No DDL/DML executed against production/shared DB.",
            "evidence": (
                f"{statements} statements executed, every one produced by this module from the fixed "
                "catalog table and accepted by the read-only statement guard; autocommit on, session "
                "closed, no shared object created, altered or dropped"
            ),
            "satisfied": bool(no_write_ok),
        },
        {
            "criterion": (
                "Generated artifacts stay inside the executor allowed paths and contain no credential "
                "material."
            ),
            "evidence": (
                "controller path guard mirror over every recorded path plus the credential guard and the "
                "repository scanner over both rendered artifacts"
            ),
            "satisfied": False,
        },
    ]


def unresolved_items(report: dict[str, Any]) -> list[dict[str, Any]]:
    """List what this run could not establish, with the value-free reason and the next action."""
    inspection = report["inspection"]
    catalog = report.get("catalog") or {}
    items: list[dict[str, Any]] = []
    if inspection["status"] != "inspected":
        reason = "; ".join(inspection["unavailable_reasons"]) or "the inspection did not complete"
        items.append(
            {
                "item": "live NEWERP catalog metadata",
                "reason": reason,
                "next_action": (
                    "re-run tests/schema/newerp_schema.py --write from a host that has an ODBC driver "
                    "and network access to the shared server; until that succeeds no table name may be "
                    "inferred from the planned DDL"
                ),
            }
        )
        for domain in DOMAIN_ORDER:
            items.append(
                {
                    "item": f"{domain} table mapping",
                    "reason": "unknown because catalog metadata was not available in this run",
                    "next_action": (
                        "resolve after a successful inspection, before NEWAPP-005 reconciles the planned "
                        "DDL"
                    ),
                }
            )
    else:
        for domain in DOMAIN_ORDER:
            entry = domain_entry(report, domain)
            if domain_resolved(report, domain):
                continue
            if entry.get("candidate_count"):
                items.append(
                    {
                        "item": f"{domain} authoritative table",
                        "reason": (
                            "candidate tables were recorded but none carries a core domain noun in its "
                            "name, so the authoritative table still needs review"
                        ),
                        "next_action": (
                            "confirm during GPT review before NEWAPP-005 maps the planned keys; recorded "
                            "candidates: " + ", ".join(entry.get("candidate_tables", [])[:8])
                        ),
                    }
                )
            else:
                items.append(
                    {
                        "item": f"{domain} authoritative table",
                        "reason": (
                            "no table in the inspected catalog carries a name candidate for this domain"
                        ),
                        "next_action": (
                            "treat the domain as absent from the shared schema and resolve the planned "
                            "neutral key for it during GPT review before NEWAPP-005 changes any structure"
                        ),
                    }
                )
        truncation = catalog.get("truncation") or {}
        if truncation.get("tables_truncated") or truncation.get("detailed_tables_truncated"):
            items.append(
                {
                    "item": "complete table inventory",
                    "reason": "the catalog exceeded the recorded MAX_* bounds, so detail is truncated",
                    "next_action": "re-run with a narrower scope if the full detail is required",
                }
            )
    items.append(
        {
            "item": "neutral *Key mapping to the real NEWERP key types",
            "reason": (
                "this task records the real keys and the planned DDL references only; the mapping is "
                "owned by NEWAPP-005"
            ),
            "next_action": (
                "NEWAPP-005 maps CustomerKey, SupplierKey, UserKey and TenantId against this map and "
                "stops at the Human Gate before any shared structure change"
            ),
        }
    )
    return items


# --------------------------------------------------------------------------- rendering

def md_row(cells: Sequence[Any]) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def md_listing(values: Sequence[Any]) -> str:
    items = [str(value) for value in values]
    return ", ".join(items) if items else "none"


def md_code_listing(values: Sequence[Any]) -> str:
    items = ["`" + str(value) + "`" for value in values]
    return ", ".join(items) if items else "none"


def md_yes_no(value: Any) -> str:
    return "yes" if value else "no"


def column_description(column: Mapping[str, Any]) -> str:
    """Render one column as ``type(length)`` using catalog metadata only."""
    data_type = str(column.get("data_type", ""))
    lowered = data_type.lower()
    size = ""
    if column.get("max_length") and lowered in {
        "nvarchar",
        "nchar",
        "varchar",
        "char",
        "varbinary",
        "binary",
    }:
        size = f"({column['max_length']})"
    elif column.get("numeric_precision") and lowered in {"decimal", "numeric"}:
        size = f"({column['numeric_precision']},{column.get('numeric_scale', 0)})"
    return data_type + size


def render_markdown(report: dict[str, Any]) -> str:
    """Render the generated schema map from the same value-free facts as the JSON report."""
    inspection = report["inspection"]
    catalog = report.get("catalog") or {}
    safety = report["safety_contract"]
    configuration = report["shared_connection_configuration"]
    driver = inspection["driver"]
    lines: list[str] = [
        "# NEWERP shared database schema map (read-only inspection)",
        "",
        f"Task: **{report['task_id']} - {report['task_title']}** "
        f"(phase {report['task_phase']}, depends on {md_listing(report['task_depends_on'])}).",
        "",
        "This document is generated from the same value-free facts as "
        f"`{REPORT_RELATIVE_PATH}`, so regenerate it with `{regeneration_command()}` instead of "
        "editing it by hand.",
        "",
        f"Generated at {report['generated_at']} by {report['generated_by']}. Completion authority: "
        f"{report['completion_authority']}.",
        "",
        "## 1. Authority of record",
        "",
        md_row(["Concern", "Authoritative artifact"]),
        md_row(["---", "---"]),
        md_row(["Shared database structure", "the live NEWERP SQL Server catalog, metadata only"]),
        md_row(["Machine-readable facts", f"`{REPORT_RELATIVE_PATH}`"]),
        md_row(
            [
                "Server-side connection reference",
                "the declared setting name in the ignored and untracked environment file",
            ]
        ),
        md_row(["Planned app-schema DDL", f"`{DDL_RELATIVE_PATH}`"]),
        md_row(["Controller allowed paths", f"`{CONFIG_SOURCE}#paths.executor_allowed`"]),
        md_row(["Task definition", "`docs/NEWAPP_TASKS_V1.yaml#NEWAPP-003`"]),
        "",
        "## 2. Safety contract for this inspection",
        "",
        "1. Only catalog metadata is read: schemas, tables, columns, keys, indexes, foreign keys and "
        "concurrency columns. No business row value is selected, exported or recorded.",
        "2. Every statement is produced by this module from one fixed catalog table and must pass the "
        "read-only statement guard: a single `SELECT` without batch separator, comment marker, "
        "DDL/DML, `EXEC`, `INTO`, `OPENROWSET` or administrative token.",
        f"3. Statements executed in this run: {safety['statements_executed']}. Statements outside the "
        f"fixed catalog table: {safety['statements_outside_catalog']}. DDL or DML executed: "
        f"{md_yes_no(safety['ddl_or_dml_executed'])}. Stored procedures executed: "
        f"{md_yes_no(safety['stored_procedures_executed'])}. Shared objects changed: "
        f"{md_yes_no(safety['shared_objects_changed'])}.",
        f"4. The session is opened with autocommit: {md_yes_no(safety['session']['autocommit'])}. The "
        f"login timeout is {safety['session']['login_timeout_seconds']} seconds and the connection is "
        f"closed before the report is rendered (closed: "
        f"{md_yes_no(safety['session']['connection_closed'])}), so no transaction or lock is left on "
        "the shared database.",
        "5. The declared shared connection declaration stays in memory: it is translated into an ODBC "
        "target inside one call and dropped when that call returns. Nothing about its server, catalog, "
        "login or password is recorded, hashed, compared or rendered.",
        "6. The environment file is opened read-only and never written. Environment file written: "
        f"{md_yes_no(safety['environment_file_written'])}. Write timestamp unchanged across the run: "
        f"{md_yes_no(safety['environment_file_modified_time_unchanged_during_run'])}.",
        "7. Both artifacts are re-checked with the credential guard and the repository scanner "
        f"`{SCANNER_RELATIVE_PATH}` before publication; a credential needle blocks the write.",
        "",
        "## 3. Inspection result",
        "",
        md_row(["Fact", "Value"]),
        md_row(["---", "---"]),
        md_row(["Inspection status", "`" + str(inspection["status"]) + "`"]),
        md_row(
            [
                "Declared setting found",
                f"{md_yes_no(inspection['declared_setting_present'])} "
                f"(source label `{inspection['connection_source']}`)",
            ]
        ),
        md_row(["Connection attempted", md_yes_no(inspection["connection_attempted"])]),
        md_row(
            ["Driver module", f"`{driver['module']}` available: {md_yes_no(driver['available'])}"]
        ),
        md_row(["Driver version", driver["version"] or "not available"]),
        md_row(
            [
                "Interpreter",
                f"{driver['interpreter']['implementation']} {driver['interpreter']['version']}",
            ]
        ),
        md_row(["Selected ODBC driver", configuration["selected_driver"] or "none"]),
        md_row(["Inspected catalog", catalog.get("database", {}).get("name") or "unknown"]),
        md_row(["Engine version", catalog.get("engine", {}).get("version") or "unknown"]),
        md_row(["Engine edition", catalog.get("engine", {}).get("edition") or "unknown"]),
        md_row(
            [
                "Tables and columns",
                f"{catalog.get('table_count', 0)} tables, {catalog.get('column_count', 0)} columns",
            ]
        ),
        md_row(
            [
                "Keys, indexes and foreign keys",
                f"{catalog.get('key_constraint_count', 0)} key constraints, "
                f"{catalog.get('index_count', 0)} index entries, "
                f"{catalog.get('foreign_key_count', 0)} foreign keys",
            ]
        ),
        md_row(["Unavailable reasons", "; ".join(inspection["unavailable_reasons"]) or "none"]),
        "",
        "## 4. Shared connection configuration (names and shape flags only)",
        "",
        md_row(["Fact", "Value"]),
        md_row(["---", "---"]),
        md_row(["Declared setting name", "`" + CONNECTION_KEY + "`"]),
        md_row(["Declared keywords", str(configuration["keyword_count"])]),
        md_row(["Keyword names", md_listing(configuration["keyword_names"])]),
        md_row(["ODBC keyword names", md_listing(configuration["odbc_keyword_names"])]),
        md_row(
            [
                "Keywords a .NET client accepts but ODBC does not",
                md_listing(configuration["non_odbc_keyword_names"]),
            ]
        ),
        md_row(["Unparsed fragments", str(configuration["unparsed_fragment_count"])]),
        md_row(["Declares an ODBC driver", md_yes_no(configuration["declares_odbc_driver"])]),
        md_row(
            [
                "Read-only application intent requested",
                md_yes_no(configuration["read_only_intent_requested"]),
            ]
        ),
        md_row(
            [
                "Uses integrated security",
                md_yes_no(configuration["shape_flags"]["uses_integrated_security"]),
            ]
        ),
        md_row(
            [
                "Shape flags",
                "server "
                + md_yes_no(configuration["shape_flags"]["has_server_keyword"])
                + ", catalog "
                + md_yes_no(configuration["shape_flags"]["has_catalog_keyword"])
                + ", login "
                + md_yes_no(configuration["shape_flags"]["has_user_keyword"])
                + ", credential material "
                + md_yes_no(configuration["shape_flags"]["has_password_keyword"]),
            ]
        ),
        "",
        "The keyword names above tell the server-side binding work which declarations must be mapped to "
        "an ODBC provider and which .NET-only keywords have to be dropped or replaced. No declared "
        "value is recorded.",
        "",
        "## 5. Domain master-table candidates",
        "",
        "Candidates come from the inspected catalog. A strong candidate carries a core domain noun in "
        "its name; a weak candidate only shares a supporting token. Classification never asserts the "
        "authoritative mapping: NEWAPP-005 reconciles the planned DDL against this map.",
        "",
        md_row(["Domain", "Monitored", "Status", "Strong candidates", "Candidates"]),
        md_row(["---", "---", "---", "---", "---"]),
    ]

    domain_map = catalog.get("domain_map") or {}
    for domain in DOMAIN_ORDER:
        entry = domain_map.get(domain) or {}
        lines.append(
            md_row(
                [
                    DOMAIN_TITLES[domain],
                    md_yes_no(domain in MASTER_DOMAINS),
                    "`" + str(entry.get("status", "not_inspected")) + "`",
                    md_code_listing(entry.get("strong_candidate_tables", [])),
                    str(entry.get("candidate_count", 0)),
                ]
            )
        )
    lines.append("")
    if inspection["status"] != "inspected":
        lines.extend(
            [
                "No live catalog metadata was available in this run, so every domain above stays an "
                "explicit unknown. Table names are deliberately not inferred from the planned DDL.",
                "",
            ]
        )
    else:
        for domain in DOMAIN_ORDER:
            entry = domain_map.get(domain) or {}
            if entry.get("resolved"):
                continue
            candidates = entry.get("candidate_tables", [])
            if candidates:
                lines.append(
                    f"- **{DOMAIN_TITLES[domain]}** has candidate tables but no core name match, so the "
                    f"authoritative table stays unresolved for review: {md_code_listing(candidates)}."
                )
            else:
                lines.append(
                    f"- **{DOMAIN_TITLES[domain]}** has no candidate at all in the inspected catalog and "
                    "is therefore reported as absent from the shared schema rather than guessed."
                )
        lines.append("")
        master_hints = catalog.get("unclassified_master_hint_tables") or []
        if master_hints:
            lines.extend(
                [
                    "Master-data-shaped tables that no domain token matched, recorded so that review can "
                    "assign them deliberately: " + md_code_listing(master_hints) + ".",
                    "",
                ]
            )

    lines.extend(
        [
            "## 6. Candidate table detail",
            "",
            f"Table detail is capped at {MAX_DETAILED_TABLES} candidate tables and "
            f"{MAX_COLUMNS_PER_TABLE} columns per table; the JSON report carries the same bound. This "
            f"document renders at most {MAX_DOC_TABLE_DETAILS} candidate tables.",
            "",
        ]
    )
    detailed = [entry for entry in catalog.get("tables", []) if entry.get("detailed")]
    if not detailed:
        lines.extend(["No catalog table detail is available in this run.", ""])
    for entry in detailed[:MAX_DOC_TABLE_DETAILS]:
        classification = entry["classification"]
        lines.append(f"### {entry['qualified_name']}")
        lines.append("")
        lines.append(
            f"- Domain: {classification.get('domain') or 'unclassified'} (strong candidate: "
            f"{md_yes_no(classification.get('strong_candidate'))})"
        )
        lines.append(
            f"- Matched tokens: {md_listing(sorted(classification.get('matched_tokens') or {}))}"
        )
        lines.append(f"- Columns: {entry['column_count']}")
        primary = entry.get("primary_key")
        if primary:
            lines.append(f"- Primary key `{primary['name']}` on {md_listing(primary['columns'])}")
        else:
            lines.append("- Primary key: none reported")
        concurrency = entry.get("concurrency_columns") or []
        lines.append(
            "- Concurrency columns: "
            + (
                md_listing([f"{item['name']} ({item['role']})" for item in concurrency])
                if concurrency
                else "none"
            )
        )
        lines.append("")
        lines.append(md_row(["Column", "Type", "Nullable", "Identity", "Concurrency"]))
        lines.append(md_row(["---", "---", "---", "---", "---"]))
        for column in entry.get("columns", []):
            role = ""
            if column["is_rowversion"]:
                role = "rowversion"
            elif column["is_rowguidcol"]:
                role = "rowguid"
            lines.append(
                md_row(
                    [
                        "`" + column["name"] + "`",
                        column_description(column),
                        md_yes_no(column["is_nullable"]),
                        md_yes_no(column["is_identity"]),
                        role or "no",
                    ]
                )
            )
        if entry.get("columns_truncated"):
            lines.extend(["", "Column list truncated at the recorded bound."])
        unique = entry.get("unique_constraints") or []
        if unique:
            lines.extend(
                [
                    "",
                    "Unique constraints: "
                    + "; ".join(f"`{item['name']}` on {md_listing(item['columns'])}" for item in unique),
                ]
            )
        foreign_keys = entry.get("foreign_keys_out") or []
        if foreign_keys:
            lines.extend(
                [
                    "",
                    "Foreign keys out: "
                    + "; ".join(
                        f"`{item['name']}` on {md_listing(item['parent_columns'])} to "
                        f"`{item['referenced_table'] or 'unknown'}`"
                        for item in foreign_keys
                    ),
                ]
            )
        indexes = entry.get("indexes") or []
        if indexes:
            lines.extend(
                [
                    "",
                    "Indexes: "
                    + "; ".join(
                        f"`{item['name']}` ({item['index_type']}) on "
                        f"{md_listing(item['key_columns'])}"
                        for item in indexes
                    ),
                ]
            )
        lines.append("")
    if len(detailed) > MAX_DOC_TABLE_DETAILS:
        lines.extend(
            [
                f"{len(detailed) - MAX_DOC_TABLE_DETAILS} further candidate tables are recorded in the "
                "JSON report only.",
                "",
            ]
        )

    concurrency = catalog.get("concurrency") or {}
    lines.extend(
        [
            "## 7. Concurrency and rowversion columns",
            "",
            f"Tables with a rowversion column: {concurrency.get('rowversion_table_count', 0)}. "
            f"Tables without any concurrency column: "
            f"{len(concurrency.get('tables_without_concurrency_column', []))}.",
            "",
            "### Tables with a rowversion column",
            "",
            md_listing(concurrency.get("tables_with_rowversion", [])),
            "",
            "### Tables without a concurrency column",
            "",
            md_listing(concurrency.get("tables_without_concurrency_column", [])),
            "",
            "## 8. Neutral key references in the planned app schema",
            "",
        ]
    )
    ddl = report["planned_ddl_key_references"]
    if not ddl.get("available"):
        lines.extend([f"Planned DDL not available: {ddl.get('reason', 'unknown')}", ""])
    else:
        lines.extend(
            [
                f"Source: `{ddl['source']}` read read-only, "
                f"{ddl['occurrence_count']} references over {ddl['name_count']} identifiers.",
                "",
                md_row(["Identifier", "Occurrences", "Source lines"]),
                md_row(["---", "---", "---"]),
            ]
        )
        for name in ddl["names"]:
            lines.append(
                md_row(
                    [
                        "`" + name + "`",
                        str(ddl["counts"][name]),
                        md_listing(ddl["line_numbers"].get(name, [])),
                    ]
                )
            )
        lines.append("")
        lines.append(
            "These identifiers are the neutral references the planned DDL still uses. They are "
            "inventoried here only; NEWAPP-005 maps them onto the real keys recorded above and stops at "
            "the Human Gate before any shared structure change."
        )
        lines.append("")

    lines.extend(
        [
            "## 9. Acceptance evidence",
            "",
            md_row(["Criterion", "Satisfied", "Evidence"]),
            md_row(["---", "---", "---"]),
        ]
    )
    for entry in report["acceptance_evidence"]:
        lines.append(md_row([entry["criterion"], md_yes_no(entry["satisfied"]), entry["evidence"]]))
    lines.append("")
    lines.extend(
        [
            "## 10. Artifact checks",
            "",
            md_row(["Check", "Status", "Findings"]),
            md_row(["---", "---", "---"]),
        ]
    )
    checks = report.get("artifact_checks") or {}
    for key in sorted(checks):
        value = checks[key]
        lines.append(md_row([key, value.get("status", "unknown"), str(value.get("findings_count", 0))]))
    if not checks:
        lines.append(md_row(["not evaluated in this rendering", "unknown", "0"]))
    lines.append("")
    guard = report.get("path_guard") or {}
    lines.extend(
        [
            "## 11. Executor path guard",
            "",
            md_row(["Path", "Accepted by the controller pattern", "Matched patterns"]),
            md_row(["---", "---", "---"]),
        ]
    )
    for entry in guard.get("paths", []):
        lines.append(
            md_row(
                [
                    "`" + entry["path"] + "`",
                    md_yes_no(entry["accepted"]),
                    md_listing(entry["matched_patterns"]),
                ]
            )
        )
    lines.append("")
    lines.extend(
        [
            f"Allowed pattern source: `{guard.get('allowed_patterns_source', CONFIG_SOURCE)}`. "
            f"Protected path touched: {md_yes_no(not guard.get('no_protected_path_touched', True))}.",
            "",
            "## 12. Known limits",
            "",
        ]
    )
    for entry in report["limitations"]:
        lines.append(f"- {entry}")
    lines.extend(["", "## 13. Unresolved items", "", md_row(["Item", "Reason", "Next action"]), md_row(["---", "---", "---"])])
    for entry in report["unresolved"]:
        lines.append(md_row([entry["item"], entry["reason"], entry["next_action"]]))
    lines.append("")
    return "\n".join(lines) + "\n"


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def regeneration_command(module_path: str = "tests/schema/newerp_schema.py") -> str:
    """Render the documented regeneration command from the recorded module path."""
    return f".venv\\Scripts\\python.exe {str(module_path).replace('/', chr(92))} --write"


def artifact_checks(report_text: str, markdown: str, needles: Sequence[str]) -> dict[str, Any]:
    """Run the credential guard on both artifacts and the repository scanner over both artifacts."""
    return {
        "report_credential_guard": credential_leak_guard(report_text, needles, REPORT_RELATIVE_PATH),
        "documentation_credential_guard": credential_leak_guard(
            markdown, needles, DOC_RELATIVE_PATH
        ),
        "scanner_self_check": scanner_self_check(
            {REPORT_RELATIVE_PATH: report_text, DOC_RELATIVE_PATH: markdown}
        ),
    }


def apply_acceptance(report: dict[str, Any]) -> dict[str, Any]:
    """Score the artifact criterion from the guard results and set the overall report status."""
    checks = report.get("artifact_checks") or {}
    guard_ok = bool(
        (checks.get("report_credential_guard") or {}).get("status") == "passed"
        and (checks.get("documentation_credential_guard") or {}).get("status") == "passed"
        and (checks.get("scanner_self_check") or {}).get("status") == "passed"
    )
    paths_ok = bool(
        report["path_guard"]["all_paths_accepted"]
        and report["path_guard"]["no_protected_path_touched"]
    )
    if report["acceptance_evidence"]:
        report["acceptance_evidence"][-1]["satisfied"] = bool(guard_ok and paths_ok)
    report["artifact_checks_verified"] = all(
        entry["satisfied"] for entry in report["acceptance_evidence"]
    )
    report["status"] = (
        "evidence_collected" if report["artifact_checks_verified"] else "attention_required"
    )
    return report


def finalize_report(
    report: dict[str, Any], needles: Sequence[str], *, attempts: int = 4
) -> tuple[dict[str, Any], str, str]:
    """Render, validate and embed the artifact check results until the rendering is stable.

    The embedded sections contain statuses, counts and line numbers only, so a stable second pass is
    the expected outcome; the final render is verified as well, so the written bytes are the bytes
    that were checked.
    """
    report["artifact_checks"] = artifact_checks("", "", needles)
    report_text = render_json(report)
    markdown = render_markdown(report)
    passes = 0
    for _ in range(attempts):
        checks = artifact_checks(report_text, markdown, needles)
        passes += 1
        if report.get("artifact_checks") == checks:
            break
        report["artifact_checks"] = checks
        report_text = render_json(report)
        markdown = render_markdown(report)
    report["artifact_check_passes"] = passes
    report = apply_acceptance(report)
    markdown = render_markdown(report)
    final_checks = artifact_checks(render_json(report), markdown, needles)
    report["artifact_checks_verified"] = bool(
        report["artifact_checks_verified"] and report.get("artifact_checks") == final_checks
    )
    report_text = render_json(report)
    return report, report_text, markdown


def publication_blocked(report: dict[str, Any]) -> str | None:
    """Return the blocking reason when a credential guard failed, else ``None``."""
    checks = report.get("artifact_checks") or {}
    for key in ("report_credential_guard", "documentation_credential_guard"):
        entry = checks.get(key) or {}
        if entry.get("status") == "failed":
            return f"{key} reported {entry.get('findings_count', 0)} credential finding(s)"
    if (checks.get("scanner_self_check") or {}).get("status") == "failed":
        return "the repository scanner reported a finding in the rendered artifacts"
    return None


def atomic_write_text(path: Path, text: str) -> None:
    """Write one artifact atomically with LF newlines, replacing any existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def relative_to_root(root: Path, value: str) -> str:
    """Return a repository-relative path label for an artifact target."""
    path = Path(value)
    candidate = path if path.is_absolute() else root / path
    try:
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return candidate.as_posix()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect the shared NEWERP SQL Server catalog read-only and render the value-free "
            "NEWAPP-003 schema map."
        )
    )
    parser.add_argument(
        "--root",
        default=str(REPOSITORY_ROOT),
        help="repository root, default the checkout that holds this module",
    )
    parser.add_argument(
        "--env-file", default=ENV_FILE, help="environment file path relative to the root"
    )
    parser.add_argument(
        "--report",
        action="append",
        default=None,
        help=f"report path, repeatable, default <root>/{REPORT_RELATIVE_PATH}",
    )
    parser.add_argument(
        "--markdown",
        action="append",
        default=None,
        help=f"generated document path, repeatable, default <root>/{DOC_RELATIVE_PATH}",
    )
    parser.add_argument("--write", action="store_true", help="write the report and the document")
    parser.add_argument(
        "--no-connect",
        action="store_true",
        help="skip the read-only connection attempt; used by offline runs and tests",
    )
    parser.add_argument(
        "--login-timeout",
        type=int,
        default=LOGIN_TIMEOUT_SECONDS,
        help=f"ODBC login timeout in seconds, default {LOGIN_TIMEOUT_SECONDS}",
    )
    parser.add_argument(
        "--executor-file",
        action="append",
        default=[],
        help="path produced or changed by the executor for this task",
    )
    parser.add_argument(
        "--payload-received",
        action="store_true",
        help="the controller payload section reached the executor",
    )
    parser.add_argument(
        "--payload-source",
        action="append",
        default=[],
        help="controller-owned record used to reconstruct the task",
    )
    parser.add_argument("--json", action="store_true", help="print the whole value-free report")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    targets = [relative_to_root(root, item) for item in (args.report or [REPORT_RELATIVE_PATH])]
    documents = [relative_to_root(root, item) for item in (args.markdown or [DOC_RELATIVE_PATH])]
    executor_paths = list(
        dict.fromkeys(
            [
                *targets,
                *documents,
                *[relative_to_root(root, item) for item in args.executor_file],
            ]
        )
    )
    facts, needles = collect_facts(
        root,
        generated_at=utc_now(),
        env_file=args.env_file,
        connect=not args.no_connect,
        login_timeout=max(1, min(60, int(args.login_timeout))),
        payload_received=args.payload_received,
        payload_sources=args.payload_source or list(DEFAULT_PAYLOAD_SOURCES),
        executor_paths=executor_paths,
        report_paths=targets,
        doc_paths=documents,
    )
    report = build_report(facts)
    report, report_text, markdown = finalize_report(report, needles)

    if args.json:
        print(report_text, end="")
    else:
        inspection = report["inspection"]
        catalog = report.get("catalog") or {}
        print(f"task={report['task_id']} status={report['status']}")
        print(
            f"inspection={inspection['status']} source={inspection['connection_source']} "
            f"attempted={inspection['connection_attempted']} "
            f"driver_available={inspection['driver']['available']}"
        )
        if catalog:
            print(
                f"catalog tables={catalog['table_count']} columns={catalog['column_count']} "
                f"keys={catalog['key_constraint_count']} indexes={catalog['index_count']} "
                f"foreign_keys={catalog['foreign_key_count']}"
            )
        else:
            print("catalog=unavailable reasons=" + "; ".join(inspection["unavailable_reasons"]))
        for domain in DOMAIN_ORDER:
            entry = (catalog.get("domain_map") or {}).get(domain) or {}
            print(
                f"domain={domain} resolved={bool(entry.get('resolved'))} "
                f"candidates={entry.get('candidate_count', 0)} "
                f"strong={entry.get('strong_candidate_count', 0)}"
            )
        checks = report.get("artifact_checks") or {}
        for key in sorted(checks):
            print(f"{key}={checks[key]['status']} findings={checks[key]['findings_count']}")
        for entry in report["acceptance_evidence"]:
            print(f"criterion_satisfied={entry['satisfied']} {entry['criterion']}")
        print(f"unresolved_items={len(report['unresolved'])}")

    blocked = publication_blocked(report)
    if blocked:
        print(f"[refused] artifacts were not written: {blocked}")
        return 2
    if args.write:
        for relative in targets:
            atomic_write_text(root / relative, report_text)
        for relative in documents:
            atomic_write_text(root / relative, markdown)
        if not args.json:
            print("written " + " ".join([*targets, *documents]))
    return 0 if report["status"] == "evidence_collected" else 1


if __name__ == "__main__":
    raise SystemExit(main())
