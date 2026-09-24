"""Reconcile the planned NEWAPP app-schema DDL against the real NEWERP keys (NEWAPP-005).

Regenerate the artifacts from the repository root::

    .venv\\Scripts\\python.exe tests\\schema\\ddl_reconciliation.py --write
    <interpreter that can import the ODBC module> tests\\schema\\ddl_reconciliation.py --write --compile

Artifacts:

* ``.ai/generated/NEWAPP-005-ddl-reconciliation.json`` - machine-readable, value-free reconciliation facts.
* ``docs/NEWAPP_DDL_RECONCILIATION.md`` - human migration plan and rollback notes rendered from those facts.
* ``database/NEWAPP_app_schema_reconciled_V1.sql`` - generated additive draft in which every resolved neutral key
  carries the real NEWERP key type. This module never applies the draft.

Safety contract
---------------
* The planned DDL (``docs/NEWAPP_Database_DDL_V1.sql``) and the accepted NEWAPP-003 map
  (``.ai/generated/NEWAPP-003-newerp-schema-map.json``) are opened read-only. No shared object is created,
  altered, dropped or queried by this task, and no business row is selected.
* A neutral key is only retyped when the accepted map records exactly one authoritative target column with a
  recorded type. A key whose target still needs review keeps its neutral declaration and becomes an explicit
  unresolved item, so no type and no table name is ever guessed.
* ``database/NEWAPP_app_schema_reconciled_V1.sql`` may only contain additive ``app`` schema objects. Every batch
  must pass the static guard (no DROP/TRUNCATE/DELETE/UPDATE/INSERT/MERGE/ALTER, no ``db_owner``/``dbo`` target,
  no ``USE``, wrapped in an ``OBJECT_ID``/``NOT EXISTS`` guard) before it can be rendered.
* The optional disposable compile check runs the generated draft on a local, disposable target only
  (``(localdb)\\...`` plus ``tempdb`` or a ``NEWAPP_Disposable*`` catalog) inside one transaction that is always
  rolled back. That proves the draft compiles and re-runs idempotently while nothing is persisted. A target that
  shares the declared shared server or catalog, or that contains declared credential material, is refused.
* A shared structure change is a Human Gate: this module never applies the draft, never adds a foreign key to a
  NEWERP table and never migrates a shared database.
* Secrets are read into memory only. The declared value is never printed, logged, stored, hashed or compared
  with anything but the in-memory guard needles; only keyword names, shape flags and booleans are recorded.
* Every recorded path is checked with a mirror of the controller path guard, and the rendered artifacts are
  re-checked with the repository scanner before publication.

Documented limits (reviewed by GPT, not silently expanded)
---------------------------------------------------------
* The reconciliation is only as good as the accepted NEWAPP-003 snapshot: a table created after that inspection
  is not represented, and the map is a metadata snapshot rather than a live binding.
* Retyping a neutral key to ``BIGINT`` matches the shared primary key type. It does not create the foreign key,
  which stays a Human-Gated shared-structure change owned by the migration task.
* ``TenantId`` keeps ``UNIQUEIDENTIFIER`` because the accepted map reports the organization/tenant domain as
  absent from the inspected catalog. The binding of that partition key is an explicit unresolved item.
* The compile check substitutes a source-level guarantee for the acceptance wording "disposable copy/test DB":
  the draft compiles and re-runs inside a rolled-back transaction on a local disposable engine. It cannot prove
  behaviour against shared data, which stays with the Human-Gated migration task (NEWAPP-009).
* ``agent.env``, ``secrets/``, signing material and the OSS credentials are never opened by this module.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_DIR = Path(__file__).resolve().parent
if str(SCHEMA_DIR) not in sys.path:
    # The NEWAPP-003 helper module lives next to this one; it is imported read-only and never modified.
    sys.path.insert(0, str(SCHEMA_DIR))

import newerp_schema  # noqa: E402  (shared read-only helper module of NEWAPP-003)

TASK_ID = "NEWAPP-005"
TASK_TITLE = "Reconcile DDL with actual NEWERP keys"
TASK_PHASE = "P0"
TASK_DEPENDS_ON: tuple[str, ...] = ("NEWAPP-003",)
DDL_RELATIVE_PATH = "docs/NEWAPP_Database_DDL_V1.sql"
SCHEMA_MAP_RELATIVE_PATH = ".ai/generated/NEWAPP-003-newerp-schema-map.json"
REPORT_RELATIVE_PATH = ".ai/generated/NEWAPP-005-ddl-reconciliation.json"
DOC_RELATIVE_PATH = "docs/NEWAPP_DDL_RECONCILIATION.md"
SCRIPT_RELATIVE_PATH = "database/NEWAPP_app_schema_reconciled_V1.sql"
SCANNER_RELATIVE_PATH = "tests/baseline/secret_scan.py"
CONFIG_SOURCE = ".ai/agent_config.yaml"
ENV_FILE = ".env"
CONNECTION_KEY = "ERP_ConnectionStrings__Default"
ALLOWED_ARTIFACT_PATTERNS = ("docs/**", ".ai/generated/**", "database/**")
DEFAULT_PAYLOAD_SOURCES = (
    ".ai/project_state.json#task_statuses.NEWAPP-005",
    ".ai/brain/decisions/NEWAPP-005-plan.json",
    "docs/NEWAPP_TASKS_V1.yaml#NEWAPP-005",
)
MODULE_RELATIVE_PATH = "tests/schema/ddl_reconciliation.py"

EXECUTOR_PATHS: tuple[str, ...] = (
    REPORT_RELATIVE_PATH,
    DOC_RELATIVE_PATH,
    SCRIPT_RELATIVE_PATH,
    "tests/schema/__init__.py",
    "tests/schema/ddl_reconciliation.py",
    "tests/schema/test_ddl_reconciliation.py",
)

# --------------------------------------------------------------------------- classification rules

CLASSIFICATION_RULES: tuple[dict[str, Any], ...] = (
    {
        "resolution": "resolved_direct",
        "rule": (
            "Exactly one authoritative target column is recorded for the neutral key in the accepted NEWAPP-003 "
            "map, with a recorded physical type. The app column is retyped to that type and a direct foreign key or "
            "repository join is the preferred mapping."
        ),
    },
    {
        "resolution": "type_resolved_target_needs_review",
        "rule": (
            "Every recorded candidate target shares one physical type, so the storage type is unambiguous, but the "
            "authoritative table still needs GPT review. The app column is retyped and the choice is recorded as an "
            "open review item."
        ),
    },
    {
        "resolution": "app_local",
        "rule": (
            "The identifier is owned by NEWAPP and has no NEWERP counterpart (OSS object key, idempotency key, "
            "change-log entity key). The neutral declaration is kept and no shared mapping is claimed."
        ),
    },
    {
        "resolution": "unresolved_human_gate",
        "rule": (
            "No authoritative target, or no recorded type, exists in the accepted map. The neutral declaration is "
            "kept, the item is recorded as unresolved and the binding stays behind the Human Gate. A type or table "
            "name is never guessed."
        ),
    },
)

# The accepted NEWAPP-003 map is the only source for target tables, target columns and their types.
USER_POINTER_KEYS: tuple[str, ...] = (
    "UserKey",
    "CreatedByUserKey",
    "UpdatedByUserKey",
    "UploadedByUserKey",
    "SubmittedByUserKey",
    "RequestedByUserKey",
    "CorrectedByUserKey",
    "ChangedByUserKey",
)


def _registration(
    neutral_key: str,
    declared_type: str,
    *,
    target: str | None = None,
    candidate_targets: Sequence[str] = (),
    strategy: str,
    gate: str,
    app_local: bool = False,
    family: str | None = None,
    review_pointer: str | None = None,
) -> dict[str, Any]:
    """Describe how one neutral key is reconciled against the accepted NEWAPP-003 map."""
    return {
        "neutral_key": neutral_key,
        "declared_type": declared_type,
        "target": target,
        "candidate_targets": tuple(candidate_targets),
        "strategy": strategy,
        "gate": gate,
        "app_local": bool(app_local),
        "family": family,
        "review_pointer": review_pointer,
    }


KEY_REGISTRATIONS: tuple[dict[str, Any], ...] = (
    _registration(
        "CustomerKey",
        "NVARCHAR(80)",
        target="db_owner.BaseCustomers.Id",
        strategy=(
            "Direct foreign key, or repository join, to the shared customer master. No duplicate customer master "
            "table is created."
        ),
        gate="The constraint itself is a shared-structure change and stays behind the Human Gate.",
    ),
    _registration(
        "SupplierKey",
        "NVARCHAR(80)",
        target="db_owner.BaseSuppliers.Id",
        strategy=(
            "Direct foreign key, or repository join, to the shared supplier master. No duplicate supplier master "
            "table is created."
        ),
        gate="The constraint itself is a shared-structure change and stays behind the Human Gate.",
    ),
    _registration(
        "UserKey",
        "NVARCHAR(80)",
        target="db_owner.SysUsers.Id",
        family="user_pointer",
        strategy=(
            "Shared user account pointer used by the mobile profile, identity, device, idempotency and audit tables."
        ),
        gate="The constraint itself is a shared-structure change and stays behind the Human Gate.",
    ),
    _registration(
        "SalesUserKey",
        "NVARCHAR(80)",
        candidate_targets=("db_owner.SysUsers.Id", "db_owner.BaseEmployees.Id"),
        strategy=(
            "Both candidates are shared primary keys of the same recorded type, so the sales-user pointer can carry "
            "the shared key type; which table owns the sales relationship must be confirmed in review."
        ),
        gate="The authoritative table choice and any constraint stay behind the Human Gate.",
    ),
    _registration(
        "SalesGroupKey",
        "NVARCHAR(80)",
        strategy=(
            "No group or team table is recorded in the accepted map, so the group pointer stays app-owned and "
            "neutral until review names an authoritative table."
        ),
        gate="A group-table binding is a shared-structure decision and stays behind the Human Gate.",
        review_pointer=(
            "db_owner.SysRoles is the only role-shaped candidate recorded by NEWAPP-003 and is not the authoritative "
            "sales group."
        ),
    ),
    _registration(
        "TargetGroupKey",
        "NVARCHAR(80)",
        strategy=(
            "Invite-code targeting follows the unknown group dimension of SalesGroupKey and stays app-owned and "
            "neutral until review names an authoritative table."
        ),
        gate="A group-table binding is a shared-structure decision and stays behind the Human Gate.",
    ),
    _registration(
        "TemplateKey",
        "NVARCHAR(80)",
        strategy="The export-template pointer is app-owned; no shared template binding is claimed.",
        gate="A template-table binding is a shared-structure decision and stays behind the Human Gate.",
        review_pointer=(
            "db_owner.SysPrintTemplates appears in the inspected catalog without recorded column detail, so it can "
            "only be a review pointer."
        ),
    ),
    _registration(
        "TenantId",
        "UNIQUEIDENTIFIER",
        strategy=(
            "The accepted map reports the organization, tenant and company domain as absent from the inspected "
            "catalog, so the partition key keeps its neutral declaration and every app table keeps a tenant "
            "partition until review decides the authoritative binding."
        ),
        gate="Binding TenantId to a shared object is a shared-structure decision and stays behind the Human Gate.",
    ),
    _registration(
        "ObjectKey",
        "NVARCHAR(600)",
        app_local=True,
        strategy=(
            "App-owned OSS object key; the shared bucket contract is documented by NEWAPP-004, not by this task."
        ),
        gate="None: no shared structure is involved.",
    ),
    _registration(
        "IdempotencyKey",
        "NVARCHAR(100)",
        app_local=True,
        strategy="App-owned client idempotency key; it is never written to a shared object.",
        gate="None: no shared structure is involved.",
    ),
    _registration(
        "EntityKey",
        "NVARCHAR(120)",
        app_local=True,
        strategy="App-owned change-log entity key that carries the already mapped key value of the changed entity.",
        gate="None: no shared structure is involved.",
    ),
) + tuple(
    _registration(
        name,
        "NVARCHAR(80)",
        target="db_owner.SysUsers.Id",
        family="user_pointer",
        strategy="Audit or ownership pointer to the shared user account, so it carries the shared user key type.",
        gate="The constraint itself is a shared-structure change and stays behind the Human Gate.",
    )
    for name in USER_POINTER_KEYS
    if name != "UserKey"
)

REGISTRATION_BY_KEY: dict[str, dict[str, Any]] = {
    str(entry["neutral_key"]): dict(entry) for entry in KEY_REGISTRATIONS
}

# --------------------------------------------------------------------------- declared type mapping

SIMPLE_TYPE_DECLARATIONS: dict[str, str] = {
    "bigint": "BIGINT",
    "int": "INT",
    "smallint": "SMALLINT",
    "tinyint": "TINYINT",
    "bit": "BIT",
    "uniqueidentifier": "UNIQUEIDENTIFIER",
    "date": "DATE",
    "datetime2": "DATETIME2",
    "datetime": "DATETIME",
    "timestamp": "ROWVERSION",
    "rowversion": "ROWVERSION",
    "varbinary": "VARBINARY",
}
LENGTH_TYPE_DECLARATIONS: dict[str, str] = {
    "nvarchar": "NVARCHAR",
    "nchar": "NCHAR",
    "varchar": "VARCHAR",
    "char": "CHAR",
    "binary": "BINARY",
}


def physical_declaration(
    data_type: str,
    max_length: int | None = None,
    numeric_precision: int | None = None,
    numeric_scale: int | None = None,
) -> str | None:
    """Render the app-side declaration for one recorded catalog type, or ``None`` when it is not renderable.

    Returning ``None`` keeps a caller from guessing: a type that cannot be rendered faithfully is reported as an
    unresolved item instead of a substituted declaration.
    """
    name = str(data_type or "").strip().lower()
    if not name:
        return None
    if name in SIMPLE_TYPE_DECLARATIONS:
        return SIMPLE_TYPE_DECLARATIONS[name]
    if name in LENGTH_TYPE_DECLARATIONS:
        if max_length is None or int(max_length) <= 0:
            return LENGTH_TYPE_DECLARATIONS[name]
        return f"{LENGTH_TYPE_DECLARATIONS[name]}({int(max_length)})"
    if name in {"decimal", "numeric"}:
        if numeric_precision is None:
            return None
        return f"{name.upper()}({int(numeric_precision)},{int(numeric_scale or 0)})"
    return None


# --------------------------------------------------------------------------- accepted map reader


def load_schema_map(root: Path, relative: str = SCHEMA_MAP_RELATIVE_PATH) -> dict[str, Any]:
    """Read the accepted NEWAPP-003 map read-only and index its recorded tables, keys and columns."""
    path = root / relative
    facts: dict[str, Any] = {
        "available": False,
        "source": relative,
        "read_only": True,
        "task_id": None,
        "status": None,
        "inspection_status": None,
        "catalog_database": None,
        "table_count": 0,
        "tables": {},
        "domains": {},
        "unresolved": [],
        "reason": None,
    }
    if not path.is_file():
        facts["reason"] = "the accepted NEWAPP-003 schema map is not present at the expected path"
        return facts
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        facts["reason"] = "the accepted NEWAPP-003 schema map could not be read: " + type(exc).__name__
        return facts

    tables: dict[str, dict[str, Any]] = {}
    catalog = payload.get("catalog") or {}
    for entry in catalog.get("tables") or []:
        if not isinstance(entry, Mapping):
            continue
        qualified = str(entry.get("qualified_name") or "")
        if not qualified:
            continue
        classification = entry.get("classification") or {}
        columns: dict[str, dict[str, Any]] = {}
        for column in entry.get("columns") or []:
            if isinstance(column, Mapping) and column.get("name"):
                columns[str(column["name"])] = {
                    "data_type": str(column.get("data_type") or ""),
                    "max_length": column.get("max_length"),
                    "numeric_precision": column.get("numeric_precision"),
                    "numeric_scale": column.get("numeric_scale"),
                    "is_identity": bool(column.get("is_identity")),
                    "is_nullable": bool(column.get("is_nullable")),
                }
        primary_key = entry.get("primary_key") or {}
        tables[qualified.lower()] = {
            "qualified_name": qualified,
            "domain": classification.get("domain"),
            "strong_candidate": bool(classification.get("strong_candidate")),
            "detailed": bool(entry.get("detailed")),
            "column_count": int(entry.get("column_count") or 0),
            "primary_key_columns": [str(name) for name in (primary_key.get("columns") or [])],
            "columns": columns,
        }
    facts.update(
        {
            "available": True,
            "task_id": payload.get("task_id"),
            "status": payload.get("status"),
            "inspection_status": (payload.get("inspection") or {}).get("status"),
            "catalog_database": ((payload.get("catalog") or {}).get("database")),
            "table_count": len(tables),
            "tables": tables,
            "domains": {
                str(name): dict(entry)
                for name, entry in (catalog.get("domain_map") or {}).items()
                if isinstance(entry, Mapping)
            },
            "unresolved": payload.get("unresolved") or [],
        }
    )
    return facts


def recorded_target(schema_map: Mapping[str, Any], target: str | None) -> dict[str, Any]:
    """Resolve one ``schema.table.column`` target against the accepted map, value-free."""
    result: dict[str, Any] = {
        "target": target,
        "recorded": False,
        "table_recorded": False,
        "column_recorded": False,
        "data_type": None,
        "declaration": None,
        "domain": None,
        "primary_key": False,
        "is_identity": False,
        "reason": None,
    }
    if not target:
        result["reason"] = "no target was registered for this neutral key"
        return result
    parts = str(target).split(".")
    if len(parts) != 3:
        result["reason"] = "the registered target is not a schema.table.column reference"
        return result
    schema, table, column = parts
    entry = (schema_map.get("tables") or {}).get(f"{schema}.{table}".lower())
    if not isinstance(entry, Mapping):
        result["reason"] = "the target table is not recorded in the accepted map"
        return result
    result["table_recorded"] = True
    result["domain"] = entry.get("domain")
    column_entry = (entry.get("columns") or {}).get(str(column))
    if not isinstance(column_entry, Mapping):
        result["reason"] = "the target column has no recorded detail in the accepted map"
        return result
    result["column_recorded"] = True
    result["data_type"] = column_entry.get("data_type")
    result["is_identity"] = bool(column_entry.get("is_identity"))
    result["primary_key"] = str(column) in [
        str(name) for name in entry.get("primary_key_columns") or []
    ]
    result["declaration"] = physical_declaration(
        str(column_entry.get("data_type") or ""),
        column_entry.get("max_length"),
        column_entry.get("numeric_precision"),
        column_entry.get("numeric_scale"),
    )
    result["recorded"] = result["declaration"] is not None
    if not result["recorded"]:
        result["reason"] = "the recorded catalog type cannot be rendered as a declaration without guessing"
    return result


# --------------------------------------------------------------------------- planned DDL parsing

GO_PATTERN = re.compile(r"^\s*GO\s*;?\s*$", re.IGNORECASE)
BLOCK_COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)
LINE_COMMENT_PATTERN = re.compile(r"--[^\n]*")
CREATE_TABLE_PATTERN = re.compile(
    r"^\s*CREATE\s+TABLE\s+(?P<name>[A-Za-z_]\w*\.[A-Za-z_]\w*)\s*\(", re.IGNORECASE
)
COLUMN_DECLARATION_PATTERN = re.compile(
    r"^\s{4,}(?P<name>[A-Za-z_]\w*)\s+"
    r"(?P<type>[A-Za-z]+(?:\s*\(\s*\d+(?:\s*,\s*\d+)?\s*\))?)"
    r"(?P<rest>\s.*)?$"
)
OBJECT_ID_GUARD_PATTERN = re.compile(r"^\s*IF\s+OBJECT_ID\s*\(", re.IGNORECASE)
NOT_EXISTS_GUARD_PATTERN = re.compile(r"^\s*IF\s+NOT\s+EXISTS\s*\(", re.IGNORECASE)
NEUTRAL_KEY_NAME_PATTERN = re.compile(r"^(?:[A-Za-z_]\w*Key|TenantId)$")
CONSTRAINT_LINE_PATTERN = re.compile(
    r"^\s*(?:CONSTRAINT|PRIMARY|FOREIGN|UNIQUE|CHECK|INDEX)\b", re.IGNORECASE
)
DESTRUCTIVE_TOKEN_PATTERN = re.compile(
    r"\b(?:drop|truncate|delete|update|insert|merge|alter|backup|restore|shrink|dbcc|kill|grant|deny|"
    r"revoke|openrowset|openquery|bulk|checkpoint|reconfigure|shutdown|writetext|updatetext)\b"
    r"|\b(?:sp_|xp_)",
    re.IGNORECASE,
)
EXTERNAL_SCHEMA_PATTERN = re.compile(r"\b(?:db_owner|dbo|newerp)\s*\.", re.IGNORECASE)
USE_STATEMENT_PATTERN = re.compile(r"^\s*USE\s+", re.IGNORECASE)
BEGIN_PATTERN = re.compile(r"\bBEGIN\b", re.IGNORECASE)
END_PATTERN = re.compile(r"\bEND\b", re.IGNORECASE)
CREATE_INDEX_PATTERN = re.compile(r"\bcreate\s+(?:unique\s+)?index\b", re.IGNORECASE)
CREATE_VIEW_PATTERN = re.compile(r"\bcreate\s+view\b", re.IGNORECASE)
OBJECT_ID_TARGET_PATTERN = re.compile(
    r"^\s*IF\s+OBJECT_ID\s*\(\s*N?'(?P<name>[A-Za-z_]\w*\.[A-Za-z_]\w*)'", re.IGNORECASE
)


def strip_sql_comments(text: str) -> str:
    """Remove block and line comments so a guard never inspects comment prose."""
    without_block = BLOCK_COMMENT_PATTERN.sub(" ", str(text))
    return LINE_COMMENT_PATTERN.sub(" ", without_block)


def split_batches(text: str) -> list[dict[str, Any]]:
    """Split a T-SQL script on ``GO`` separators and describe each batch without recording any value."""
    all_lines = str(text).splitlines()
    groups: list[dict[str, Any]] = []
    current: list[str] = []
    start_line = 1
    for number, line in enumerate(all_lines, start=1):
        if GO_PATTERN.match(line):
            if any(part.strip() for part in current):
                groups.append({"lines": current, "start_line": start_line, "end_line": number - 1})
            current = []
            start_line = number + 1
            continue
        current.append(line)
    if any(part.strip() for part in current):
        groups.append({"lines": current, "start_line": start_line, "end_line": len(all_lines)})

    described: list[dict[str, Any]] = []
    for index, group in enumerate(groups, start=1):
        guarded_text = strip_sql_comments("\n".join(group["lines"]))
        described.append(
            {
                "index": index,
                "start_line": group["start_line"],
                "end_line": group["end_line"],
                "statement_text": guarded_text,
                "line_count": len(group["lines"]),
                "guarded": bool(
                    any(OBJECT_ID_GUARD_PATTERN.match(line) for line in group["lines"])
                    or any(NOT_EXISTS_GUARD_PATTERN.match(line) for line in group["lines"])
                ),
                "contains_create": bool(re.search(r"\bcreate\b", guarded_text, re.IGNORECASE)),
                "destructive_tokens": sorted(
                    {
                        match.group(0).lower()
                        for match in DESTRUCTIVE_TOKEN_PATTERN.finditer(guarded_text)
                    }
                ),
                "external_schema_hits": len(EXTERNAL_SCHEMA_PATTERN.findall(guarded_text)),
                "use_statement": bool(
                    any(USE_STATEMENT_PATTERN.match(line) for line in group["lines"])
                ),
                "begin_count": len(BEGIN_PATTERN.findall(guarded_text)),
                "end_count": len(END_PATTERN.findall(guarded_text)),
                "open_parentheses": guarded_text.count("("),
                "close_parentheses": guarded_text.count(")"),
                "terminated": bool(
                    re.match(
                        r"^(?:.*;|END\s*;?)$",
                        [line for line in group["lines"] if line.strip()][-1].strip(),
                        re.IGNORECASE,
                    )
                ),
            }
        )
    return described


def parse_planned_ddl(text: str) -> dict[str, Any]:
    """Inventory the tables, column declarations and neutral-key declaration sites of a T-SQL script."""
    tables: list[dict[str, Any]] = []
    declarations: dict[str, list[dict[str, Any]]] = {}
    current: dict[str, Any] | None = None
    pending_guard_target: str | None = None
    for number, line in enumerate(str(text).splitlines(), start=1):
        guard = OBJECT_ID_TARGET_PATTERN.match(line)
        if guard:
            pending_guard_target = guard.group("name").lower()
        create = CREATE_TABLE_PATTERN.match(line)
        if create:
            current = {
                "name": create.group("name"),
                "line": number,
                "columns": [],
                "guarded": pending_guard_target == create.group("name").lower(),
            }
            tables.append(current)
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith(");") or stripped.upper().startswith("END"):
            current = None
            continue
        column = COLUMN_DECLARATION_PATTERN.match(line)
        if column and not CONSTRAINT_LINE_PATTERN.match(line):
            name = column.group("name")
            declared_type = re.sub(r"\s+", "", column.group("type")).upper()
            current["columns"].append({"name": name, "declared_type": declared_type})
            if NEUTRAL_KEY_NAME_PATTERN.match(name):
                declarations.setdefault(name, []).append(
                    {
                        "table": current["name"],
                        "column": name,
                        "declared_type": declared_type,
                        "line": number,
                    }
                )
    plain = strip_sql_comments(str(text))
    return {
        "table_count": len(tables),
        "tables": tables,
        "column_count": sum(len(table["columns"]) for table in tables),
        "declarations": {name: declarations[name] for name in sorted(declarations)},
        "declaration_count": sum(len(entries) for entries in declarations.values()),
        "create_table_count": len(tables),
        "create_index_count": len(CREATE_INDEX_PATTERN.findall(plain)),
        "create_view_count": len(CREATE_VIEW_PATTERN.findall(plain)),
    }


# --------------------------------------------------------------------------- reconciliation


def key_resolution_rows(
    schema_map: Mapping[str, Any], ddl_inventory: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Classify every registered neutral key from the accepted map and the planned declarations."""
    declarations = ddl_inventory.get("declarations") or {}
    rows: list[dict[str, Any]] = []
    for registration in KEY_REGISTRATIONS:
        key = str(registration["neutral_key"])
        sites = list(declarations.get(key, []))
        row: dict[str, Any] = {
            "neutral_key": key,
            "family": registration.get("family"),
            "declared_type": registration["declared_type"],
            "declared_types": sorted({str(site["declared_type"]) for site in sites}),
            "declaration_count": len(sites),
            "declaration_tables": [str(site["table"]) for site in sites],
            "strategy": registration["strategy"],
            "gate": registration["gate"],
            "review_pointer": registration.get("review_pointer"),
            "evidence": [],
            "target_table": None,
            "target_column": None,
            "target_type": None,
            "target_primary_key": False,
            "resolved_type": None,
            "resolution": "unresolved_human_gate",
            "raised_to_shared_type": False,
            "reason": None,
        }
        if registration["app_local"]:
            row["resolution"] = "app_local"
            row["resolved_type"] = registration["declared_type"]
            row["reason"] = "the identifier is owned by NEWAPP and has no NEWERP counterpart"
        elif registration["target"]:
            evidence = recorded_target(schema_map, str(registration["target"]))
            row["evidence"] = [evidence]
            if evidence["recorded"] and evidence["primary_key"]:
                schema_name, table_name, column_name = str(registration["target"]).split(".")
                row.update(
                    {
                        "resolution": "resolved_direct",
                        "target_table": f"{schema_name}.{table_name}",
                        "target_column": column_name,
                        "target_type": evidence["data_type"],
                        "target_primary_key": True,
                        "resolved_type": evidence["declaration"],
                        "reason": "one authoritative target column with a recorded type",
                    }
                )
            else:
                row["reason"] = (
                    "the registered target is not a recorded primary key of the accepted map: "
                    + str(evidence["reason"])
                )
        elif registration["candidate_targets"]:
            evidences = [
                recorded_target(schema_map, str(target))
                for target in registration["candidate_targets"]
            ]
            row["evidence"] = evidences
            renderable = {
                str(evidence["declaration"]) for evidence in evidences if evidence["recorded"]
            }
            if evidences and all(evidence["recorded"] for evidence in evidences) and len(renderable) == 1:
                row.update(
                    {
                        "resolution": "type_resolved_target_needs_review",
                        "resolved_type": renderable.pop(),
                        "reason": (
                            "every recorded candidate target shares one physical type, so the storage type is "
                            "unambiguous while the authoritative table still needs review"
                        ),
                    }
                )
            else:
                row["reason"] = (
                    "the recorded candidate targets do not share one renderable type: "
                    + "; ".join(sorted(str(evidence["reason"]) for evidence in evidences))
                )
        else:
            reason = "the accepted map records no authoritative target for this key"
            if key == "TenantId":
                status = ((schema_map.get("domains") or {}).get("organization") or {}).get("status")
                reason = (
                    "the accepted map reports the organization/tenant domain as "
                    + str(status)
                    + " and lists no binding table, so the partition key keeps its neutral declaration"
                )
            row["reason"] = reason
        row["raised_to_shared_type"] = bool(
            row["resolved_type"]
            and row["resolution"] in {"resolved_direct", "type_resolved_target_needs_review"}
            and row["resolved_type"] != registration["declared_type"]
        )
        rows.append(row)
    return rows


def retype_plan(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return the columns that must carry the shared key type in the reconciled draft."""
    plan: list[dict[str, Any]] = []
    for row in rows:
        if not row.get("raised_to_shared_type"):
            continue
        plan.append(
            {
                "neutral_key": row["neutral_key"],
                "declared_type": row["declared_type"],
                "resolved_type": row["resolved_type"],
                "target_table": row.get("target_table"),
                "target_column": row.get("target_column"),
                "resolution": row["resolution"],
                "declaration_count": int(row.get("declaration_count") or 0),
            }
        )
    return plan


def line_table_index(text: str) -> list[str | None]:
    """Map every line to the ``app`` table it belongs to, for value-free substitution records."""
    index: list[str | None] = []
    current: str | None = None
    for line in str(text).splitlines():
        create = CREATE_TABLE_PATTERN.match(line)
        if create:
            current = create.group("name")
        index.append(current)
        stripped = line.strip()
        if current is not None and (stripped.startswith(");") or stripped.upper().startswith("END")):
            current = None
    return index


def reconcile_ddl(
    text: str, rows: Sequence[Mapping[str, Any]]
) -> tuple[str, list[dict[str, Any]]]:
    """Apply the retype plan to a copy of the planned DDL, returning the text and the substitutions."""
    plan = {str(entry["neutral_key"]): entry for entry in retype_plan(rows)}
    tables = line_table_index(text)
    output: list[str] = []
    substitutions: list[dict[str, Any]] = []
    for number, line in enumerate(str(text).splitlines(), start=1):
        column = COLUMN_DECLARATION_PATTERN.match(line)
        entry = plan.get(column.group("name")) if column else None
        if entry is None or CONSTRAINT_LINE_PATTERN.match(line):
            output.append(line)
            continue
        declared = re.sub(r"\s+", "", column.group("type")).upper()
        if declared != entry["declared_type"]:
            # A declaration that does not match the registered type is never rewritten silently.
            output.append(line)
            continue
        start, end = column.span("type")
        target = None
        if entry.get("target_table") and entry.get("target_column"):
            target = f"{entry['target_table']}.{entry['target_column']}"
        substitutions.append(
            {
                "table": tables[number - 1],
                "column": column.group("name"),
                "from": declared,
                "to": entry["resolved_type"],
                "line": number,
                "neutral_key": entry["neutral_key"],
                "resolution": entry["resolution"],
                "target": target,
            }
        )
        output.append(line[:start] + str(entry["resolved_type"]) + line[end:])
    return "\n".join(output) + "\n", substitutions


def script_header(
    generated_at: str,
    digests: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    substitutions: Sequence[Mapping[str, Any]],
    table_count: int,
) -> str:
    """Render the review banner that precedes the generated draft, as a T-SQL block comment."""
    retyped = [row for row in rows if row.get("raised_to_shared_type")]
    unresolved = [row for row in rows if row["resolution"] == "unresolved_human_gate"]
    lines = [
        "/*",
        "NEWAPP app schema - reconciled draft V1 (generated, review required before any execution).",
        "",
        "Generated at {ts} by tests/schema/ddl_reconciliation.py (NEWAPP-005).".format(ts=generated_at),
        "Planned DDL contract: {path} sha256 {digest}".format(
            path=DDL_RELATIVE_PATH, digest=digests.get(DDL_RELATIVE_PATH, "not_recorded")
        ),
        "Accepted shared-key map: {path} sha256 {digest}".format(
            path=SCHEMA_MAP_RELATIVE_PATH, digest=digests.get(SCHEMA_MAP_RELATIVE_PATH, "not_recorded")
        ),
        "",
        (
            "This file is additive and idempotent: {tables} app tables, each creation guarded by an OBJECT_ID or "
            "NOT EXISTS check, {subs} column declarations raised to the recorded shared key type."
        ).format(tables=table_count, subs=len(substitutions)),
        "Retyped keys: "
        + ", ".join(
            "{name} -> {type} ({target})".format(
                name=row["neutral_key"],
                type=row["resolved_type"],
                target=row["target_table"] + "." + str(row["target_column"])
                if row.get("target_table") and row.get("target_column")
                else "shared key type recorded by NEWAPP-003",
            )
            for row in retyped
        ),
        "Kept neutral on purpose: "
        + ", ".join("{name} {type}".format(name=row["neutral_key"], type=row["declared_type"]) for row in unresolved),
        "",
        "NOT APPROVED FOR EXECUTION. Applying this draft to the shared NEWERP database is a shared structure change:",
        "it stays behind the Human Gate owned by the controller and the GPT review, and the migration task runs it in a",
        "disposable database first. No NEWERP object is created, altered or dropped, and no duplicate customer or",
        "supplier master table is introduced by this script.",
        "*/",
    ]
    return "\n".join(lines) + "\n"


def declaration_signature(inventory: Mapping[str, Any], key: str) -> list[tuple[str, str, str]]:
    """Return the value-free declaration signature of one neutral key: table, column and declared type."""
    return sorted(
        (str(site["table"]), str(site["column"]), str(site["declared_type"]))
        for site in (inventory.get("declarations") or {}).get(key, [])
    )


def static_checks(
    contract_text: str,
    reconciled_text: str,
    rows: Sequence[Mapping[str, Any]],
    substitutions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Prove the generated draft is additive, guarded and limited to the registered retypes."""
    contract = parse_planned_ddl(contract_text)
    reconciled = parse_planned_ddl(reconciled_text)
    batches = split_batches(reconciled_text)
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    unguarded = [batch["index"] for batch in batches if batch["contains_create"] and not batch["guarded"]]
    add(
        "every_create_batch_is_guarded",
        not unguarded,
        "every batch that creates an object is wrapped in an OBJECT_ID / NOT EXISTS guard",
    )
    destructive = [
        {"batch": batch["index"], "tokens": batch["destructive_tokens"]}
        for batch in batches
        if batch["destructive_tokens"]
    ]
    add(
        "no_destructive_statement",
        not destructive,
        "no DROP, TRUNCATE, DELETE, UPDATE, INSERT, MERGE, ALTER or administrative token occurs in any statement",
    )
    external = [batch["index"] for batch in batches if batch["external_schema_hits"]]
    add(
        "no_external_schema_reference",
        not external,
        "no statement references a db_owner, dbo or NEWERP object, so no shared object is touched",
    )
    switching = [batch["index"] for batch in batches if batch["use_statement"]]
    add("no_database_switch", not switching, "the draft contains no USE statement")
    unbalanced = [batch["index"] for batch in batches if batch["begin_count"] != batch["end_count"]]
    add("begin_end_balanced", not unbalanced, "BEGIN and END counts match in every batch")
    parentheses = [
        batch["index"] for batch in batches if batch["open_parentheses"] != batch["close_parentheses"]
    ]
    add("parentheses_balanced", not parentheses, "parenthesis counts match in every batch")
    unterminated = [batch["index"] for batch in batches if not batch["terminated"]]
    add(
        "every_batch_terminated",
        not unterminated,
        "every batch ends with a terminated statement or an END block terminator",
    )

    contract_tables = [str(table["name"]) for table in contract["tables"]]
    reconciled_tables = [str(table["name"]) for table in reconciled["tables"]]
    add(
        "table_set_unchanged",
        contract_tables == reconciled_tables,
        "the draft declares exactly the app tables of the planned DDL contract",
    )
    contract_columns = {
        str(table["name"]): [str(column["name"]) for column in table["columns"]]
        for table in contract["tables"]
    }
    reconciled_columns = {
        str(table["name"]): [str(column["name"]) for column in table["columns"]]
        for table in reconciled["tables"]
    }
    add(
        "column_set_unchanged",
        contract_columns == reconciled_columns,
        "the draft declares exactly the columns of the planned DDL contract in the same order",
    )

    expected = {
        str(entry["neutral_key"]): (str(entry["declared_type"]), str(entry["resolved_type"]))
        for entry in retype_plan(rows)
        if int(entry["declaration_count"]) > 0
    }
    applied: dict[str, tuple[str, str]] = {}
    for substitution in substitutions:
        applied[str(substitution["column"])] = (
            str(substitution["from"]),
            str(substitution["to"]),
        )
    add(
        "only_registered_columns_retyped",
        applied == expected,
        "the rewritten declarations are exactly the registered resolved keys with their recorded shared type",
    )

    retyped = [row for row in rows if row.get("raised_to_shared_type")]
    not_applied = [
        str(row["neutral_key"])
        for row in retyped
        if declaration_signature(reconciled, str(row["neutral_key"]))
        != [
            (table, column, str(row["resolved_type"]))
            for table, column, _ in declaration_signature(contract, str(row["neutral_key"]))
        ]
    ]
    add(
        "shared_type_applied_to_every_declaration_site",
        not not_applied,
        "every declaration site of a resolved key carries the recorded shared key type",
    )

    untouched = [
        str(row["neutral_key"])
        for row in rows
        if row["resolution"] in {"unresolved_human_gate", "app_local"}
        and declaration_signature(reconciled, str(row["neutral_key"]))
        != declaration_signature(contract, str(row["neutral_key"]))
    ]
    add(
        "unresolved_keys_kept_neutral",
        not untouched,
        "keys that are app-owned or still unresolved keep their planned declaration unchanged",
    )
    counts_contract = (
        contract["create_table_count"],
        contract["create_index_count"],
        contract["create_view_count"],
    )
    counts_reconciled = (
        reconciled["create_table_count"],
        reconciled["create_index_count"],
        reconciled["create_view_count"],
    )
    add(
        "object_counts_unchanged",
        counts_contract == counts_reconciled,
        "the draft adds no object beyond the planned DDL contract",
    )
    add(
        "no_generated_view_or_foreign_key",
        reconciled["create_view_count"] == 0,
        "view and foreign-key proposals stay documented review items instead of generated statements",
    )
    banner = str(reconciled_text).split("*/", 1)[0] if str(reconciled_text).startswith("/*") else ""
    add(
        "review_banner_present",
        "NOT APPROVED FOR EXECUTION" in banner,
        "the draft carries the generated review banner that states this task must not apply it",
    )

    failed = [str(entry["check"]) for entry in checks if not entry["passed"]]
    return {
        "status": "passed" if not failed else "failed",
        "checks": checks,
        "check_count": len(checks),
        "passed_count": len(checks) - len(failed),
        "failed_count": len(failed),
        "issues": failed,
        "batch_count": len(batches),
        "guarded_batch_count": len([batch for batch in batches if batch["guarded"]]),
        "destructive_batches": destructive,
        "external_schema_batches": external,
        "create_table_count": reconciled["create_table_count"],
        "create_index_count": reconciled["create_index_count"],
        "column_count": reconciled["column_count"],
        "substitution_count": len(substitutions),
        "unresolved_declaration_columns": sorted(
            str(row["neutral_key"]) for row in rows if row["resolution"] == "unresolved_human_gate"
        ),
        "app_local_columns": sorted(
            str(row["neutral_key"]) for row in rows if row["resolution"] == "app_local"
        ),
    }


# --------------------------------------------------------------------------- disposable compile check

DISPOSABLE_SERVER_PREFIX = "(localdb)"
DISPOSABLE_CATALOGS: tuple[str, ...] = ("tempdb",)
DISPOSABLE_CATALOG_PREFIXES: tuple[str, ...] = ("newapp_disposable", "newapp_test")
DEFAULT_DISPOSABLE_INSTANCE = r"(localdb)\MSSQLLocalDB"
DEFAULT_DISPOSABLE_CATALOG = "tempdb"
COMPILE_LOGIN_TIMEOUT_SECONDS = 15
DEFAULT_COMPILE_PASSES = 2
PREFERRED_DISPOSABLE_DRIVER = "ODBC Driver 17 for SQL Server"

COMPILE_STATUS_NOT_REQUESTED = "not_requested"
COMPILE_STATUS_COMPILED = "compiled_and_rolled_back"
COMPILE_STATUS_ENGINE_UNAVAILABLE = "engine_unavailable"
COMPILE_STATUS_TARGET_REFUSED = "target_refused"
COMPILE_STATUS_GUARD_REFUSED = "statement_guard_refused"
COMPILE_STATUS_FAILED = "compile_failed"
COMPILE_STATUS_PERSISTED = "objects_persisted_risk"
COMPILE_APP_TABLE_COUNT_QUERY = (
    "SELECT COUNT(*) FROM sys.tables WHERE schema_id = SCHEMA_ID('app')"
)


def build_disposable_target(
    instance: str,
    catalog: str,
    driver_names: Sequence[str],
) -> dict[str, Any]:
    """Assemble the local disposable ODBC target in memory and describe it without recording a secret."""
    driver = newerp_schema.select_odbc_driver(list(driver_names), PREFERRED_DISPOSABLE_DRIVER)
    parts = {
        "server": str(instance).strip(),
        "catalog": str(catalog).strip(),
        "driver": driver,
    }
    target = None
    if driver:
        target = (
            "DRIVER={" + str(driver) + "};Server=" + parts["server"] + ";Database=" + parts["catalog"]
            + ";Trusted_Connection=yes;Encrypt=no;ApplicationIntent=ReadWrite"
        )
    return {"parts": parts, "odbc_target": target}


def disposable_target_guard(parts: Mapping[str, Any], declared_value: Any) -> dict[str, Any]:
    """Refuse any compile target that is not local, disposable and unrelated to the declared shared database."""
    server = str(parts.get("server") or "").strip()
    catalog = str(parts.get("catalog") or "").strip()
    driver = str(parts.get("driver") or "").strip()
    server_kind = "localdb" if server.lower().startswith(DISPOSABLE_SERVER_PREFIX) else "not_disposable"
    catalog_lower = catalog.lower()
    if catalog_lower in DISPOSABLE_CATALOGS:
        catalog_kind = "scratch_database"
    elif catalog_lower.startswith(DISPOSABLE_CATALOG_PREFIXES):
        catalog_kind = "app_disposable_database"
    else:
        catalog_kind = "not_disposable"

    declared_server = ""
    declared_catalog = ""
    for keyword, value in newerp_schema.parse_connection_string(declared_value):
        normalized = newerp_schema.normalize_keyword(keyword)
        if normalized in {"server", "data source", "address", "addr", "network address"}:
            declared_server = str(value).strip().lower()
        elif normalized in {"database", "initial catalog"}:
            declared_catalog = str(value).strip().lower()

    target_text = "|".join([server, catalog, driver]).lower()
    needles = [needle for needle in newerp_schema.credential_needles(declared_value) if needle]
    facts: dict[str, Any] = {
        "allowed": False,
        "reasons": [],
        "server_kind": server_kind,
        "catalog_kind": catalog_kind,
        "driver_selected": bool(driver),
        "integrated_security": True,
        "shares_declared_server": bool(declared_server) and declared_server == server.lower(),
        "shares_declared_catalog": bool(declared_catalog) and declared_catalog == catalog_lower,
        "contains_declared_credential_material": any(needle.lower() in target_text for needle in needles),
        "declared_value_recorded": False,
        "connection_string_recorded": False,
    }
    if server_kind != "localdb":
        facts["reasons"].append("the target server is not a local disposable LocalDB instance")
    if catalog_kind == "not_disposable":
        facts["reasons"].append(
            "the target catalog is neither the scratch database nor a NEWAPP disposable catalog"
        )
    if not driver:
        facts["reasons"].append("no ODBC driver is available to reach a disposable engine")
    if facts["shares_declared_server"]:
        facts["reasons"].append("the target server is the declared shared server")
    if facts["shares_declared_catalog"]:
        facts["reasons"].append("the target catalog is the declared shared catalog")
    if facts["contains_declared_credential_material"]:
        facts["reasons"].append("the target would carry declared credential material")
    facts["allowed"] = not facts["reasons"]
    return facts


def disposable_statement_guard(batches: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Refuse to execute any batch that is not additive, guarded and free of external references."""
    offending = [
        {
            "batch": batch["index"],
            "destructive_tokens": list(batch["destructive_tokens"]),
            "external_schema_hits": int(batch["external_schema_hits"]),
            "use_statement": bool(batch["use_statement"]),
            "unguarded_create": bool(batch["contains_create"] and not batch["guarded"]),
        }
        for batch in batches
        if batch["destructive_tokens"]
        or batch["external_schema_hits"]
        or batch["use_statement"]
        or (batch["contains_create"] and not batch["guarded"])
    ]
    return {
        "status": "passed" if not offending else "failed",
        "batch_count": len(batches),
        "offending_batches": offending,
        "offending_count": len(offending),
    }


def app_schema_object_count(cursor: Any) -> int | None:
    """Count the app schema tables visible to one cursor, without reading a business value."""
    cursor.execute(COMPILE_APP_TABLE_COUNT_QUERY)
    row = cursor.fetchone()
    if row is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError, IndexError):
        return None


def run_disposable_compile(
    batches: Sequence[Mapping[str, Any]],
    *,
    driver_module: Any,
    odbc_target: str,
    login_timeout: int = COMPILE_LOGIN_TIMEOUT_SECONDS,
    passes: int = DEFAULT_COMPILE_PASSES,
) -> dict[str, Any]:
    """Run every batch on the disposable target twice inside one transaction that is always rolled back.

    The connection is opened with ``autocommit=False`` and is never committed, so the drafted objects exist only
    inside the transaction: the first pass proves the draft compiles, the second pass proves the guards make it
    idempotent, and the rollback plus a post-rollback count prove that nothing was persisted.
    """
    facts: dict[str, Any] = {
        "attempted": False,
        "outcome": "skipped",
        "status": COMPILE_STATUS_ENGINE_UNAVAILABLE,
        "passes_requested": int(passes),
        "passes_completed": 0,
        "batches_executed": 0,
        "statements_executed": 0,
        "tables_visible_in_transaction": None,
        "tables_after_rollback": None,
        "rollback_confirmed": None,
        "transaction_rolled_back": None,
        "commit_called": False,
        "connection_closed": None,
        "autocommit": False,
        "elapsed_seconds": 0.0,
        "errors": [],
    }
    if driver_module is None:
        facts["errors"] = [
            {
                "error_class": "NoneType",
                "sqlstate": "not_reported",
                "category": "driver_module_not_installed",
                "message_recorded": False,
            }
        ]
        return facts

    started = time.monotonic()
    facts["attempted"] = True
    try:
        connection = driver_module.connect(
            odbc_target, autocommit=False, timeout=int(login_timeout)
        )
    except Exception as exc:
        facts["outcome"] = "failed"
        facts["status"] = COMPILE_STATUS_ENGINE_UNAVAILABLE
        facts["elapsed_seconds"] = round(time.monotonic() - started, 3)
        facts["errors"] = [newerp_schema.classify_connection_error(exc)]
        return facts

    cursor = connection.cursor()
    try:
        for pass_index in range(1, int(passes) + 1):
            for batch in batches:
                statement = str(batch.get("statement_text") or "").strip()
                if not statement:
                    continue
                cursor.execute(statement)
                facts["batches_executed"] += 1
                facts["statements_executed"] += 1
            facts["passes_completed"] = pass_index
            if pass_index == 1:
                facts["tables_visible_in_transaction"] = app_schema_object_count(cursor)
    except Exception as exc:
        facts["outcome"] = "failed"
        facts["status"] = COMPILE_STATUS_FAILED
        facts["errors"].append(newerp_schema.classify_connection_error(exc))
    else:
        facts["outcome"] = "executed"
        facts["status"] = COMPILE_STATUS_COMPILED
    finally:
        rollback = getattr(connection, "rollback", None)
        if callable(rollback):
            try:
                rollback()
                facts["transaction_rolled_back"] = True
            except Exception as exc:
                facts["transaction_rolled_back"] = False
                facts["errors"].append(newerp_schema.classify_connection_error(exc))
        if facts["transaction_rolled_back"]:
            try:
                facts["tables_after_rollback"] = app_schema_object_count(cursor)
            except Exception as exc:
                facts["errors"].append(newerp_schema.classify_connection_error(exc))
        close = getattr(connection, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
            facts["connection_closed"] = True
        facts["elapsed_seconds"] = round(time.monotonic() - started, 3)

    visible = facts["tables_visible_in_transaction"]
    after = facts["tables_after_rollback"]
    facts["rollback_confirmed"] = bool(
        facts["transaction_rolled_back"] and after == 0 and visible is not None and visible > 0
    )
    return facts


def disposable_compile_check(
    reconciled_text: str,
    *,
    driver_module: Any,
    driver_names: Sequence[str],
    declared_value: Any,
    instance: str = DEFAULT_DISPOSABLE_INSTANCE,
    catalog: str = DEFAULT_DISPOSABLE_CATALOG,
    expected_table_count: int = 0,
    login_timeout: int = COMPILE_LOGIN_TIMEOUT_SECONDS,
    passes: int = DEFAULT_COMPILE_PASSES,
) -> dict[str, Any]:
    """Guard the target and the statements, then compile the draft twice inside one rolled-back transaction."""
    batches = split_batches(reconciled_text)
    statement_guard = disposable_statement_guard(batches)
    built = build_disposable_target(instance, catalog, driver_names)
    target_guard = disposable_target_guard(built["parts"], declared_value)
    facts: dict[str, Any] = {
        "requested": True,
        "status": COMPILE_STATUS_ENGINE_UNAVAILABLE,
        "reason": None,
        "target": {
            "instance": built["parts"]["server"],
            "catalog": built["parts"]["catalog"],
            "driver": built["parts"]["driver"],
            "server_kind": target_guard["server_kind"],
            "catalog_kind": target_guard["catalog_kind"],
            "integrated_security": True,
            "connection_string_recorded": False,
            "declared_value_recorded": False,
        },
        "target_guard": target_guard,
        "statement_guard": statement_guard,
        "interpreter": newerp_schema.interpreter_facts(),
        "driver_module_available": driver_module is not None,
        "passes_requested": int(passes),
        "expected_table_count": int(expected_table_count),
        "execution": None,
        "idempotent_second_pass": False,
        "tables_created_visible": None,
        "expected_table_count_matched": False,
        "shared_connection_used": False,
        "applied_to_shared_database": False,
    }
    if statement_guard["status"] != "passed":
        facts["status"] = COMPILE_STATUS_GUARD_REFUSED
        facts["reason"] = "a batch failed the additive statement guard, so nothing was executed"
        return facts
    if not target_guard["allowed"]:
        facts["status"] = COMPILE_STATUS_TARGET_REFUSED
        facts["reason"] = "the disposable target guard refused the target, so nothing was executed"
        return facts
    if driver_module is None:
        facts["reason"] = "the ODBC driver module is not importable in this interpreter"
        return facts
    if not built["odbc_target"]:
        facts["reason"] = "no disposable ODBC target could be assembled"
        return facts

    execution = run_disposable_compile(
        batches,
        driver_module=driver_module,
        odbc_target=built["odbc_target"],
        login_timeout=login_timeout,
        passes=passes,
    )
    facts["execution"] = execution
    facts["status"] = str(execution["status"])
    facts["idempotent_second_pass"] = int(execution["passes_completed"]) >= 2
    facts["tables_created_visible"] = execution["tables_visible_in_transaction"]
    facts["expected_table_count_matched"] = (
        execution["tables_visible_in_transaction"] == int(expected_table_count)
    )
    if facts["status"] == COMPILE_STATUS_COMPILED and not execution["rollback_confirmed"]:
        facts["status"] = COMPILE_STATUS_PERSISTED
        facts["reason"] = "the rolled-back transaction left app objects visible after the rollback"
    elif facts["status"] == COMPILE_STATUS_COMPILED and not facts["expected_table_count_matched"]:
        facts["status"] = COMPILE_STATUS_FAILED
        facts["reason"] = "the number of visible app tables does not match the drafted table count"
    elif facts["status"] == COMPILE_STATUS_COMPILED:
        facts["reason"] = (
            "every batch compiled twice inside one transaction that was rolled back, and no app object remained"
        )
    return facts


# --------------------------------------------------------------------------- facts and report

LIMITATIONS: tuple[str, ...] = (
    "The reconciliation reads the accepted NEWAPP-003 snapshot, so a shared table created after that inspection is not represented and the map is metadata rather than a live binding.",
    "Raising a neutral key to the recorded shared key type aligns the column type; it does not create the foreign key, which stays a Human-Gated shared-structure change.",
    "TenantId keeps its UNIQUEIDENTIFIER declaration because the accepted map reports the organization, tenant and company domain as absent from the inspected catalog.",
    "Group and template pointers keep their neutral declarations because no authoritative table for them is recorded; they are review items, not resolved mappings.",
    "The disposable compile check runs the draft inside one rolled-back transaction on a local disposable engine, so it proves compilation, guard coverage and idempotent re-run rather than behaviour against shared data.",
    "When the ODBC driver module is not importable in the generating interpreter, the compile check is reported as engine_unavailable together with the regenerating command instead of an implicit pass.",
    "Applying the draft to the shared NEWERP database, adding a foreign key to a shared table and migrating a shared database are outside this task and stay behind the Human Gate.",
    "agent.env, secrets, signing material and the OSS credentials are never opened by this module.",
)


def sha256_text(text: str) -> str:
    """Hash rendered artifact text with the repository digest algorithm."""
    import hashlib

    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def collect_facts(
    root: Path,
    *,
    generated_at: str,
    env_file: str = ENV_FILE,
    environ: Mapping[str, str] | None = None,
    driver_module: Any | None = None,
    driver_facts: Mapping[str, Any] | None = None,
    compile_check: bool = False,
    disposable_instance: str = DEFAULT_DISPOSABLE_INSTANCE,
    disposable_catalog: str = DEFAULT_DISPOSABLE_CATALOG,
    payload_received: bool = False,
    payload_sources: Sequence[str] = DEFAULT_PAYLOAD_SOURCES,
    executor_paths: Sequence[str] = EXECUTOR_PATHS,
    report_paths: Sequence[str] = (),
    doc_paths: Sequence[str] = (),
    script_paths: Sequence[str] = (),
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Collect every value-free fact the report, the document and the draft are built from.

    Returns ``(facts, needles)``. ``facts`` is publishable and never carries a declared value; ``needles`` is the
    in-memory credential material the publication guard must reject and is never stored inside ``facts``.
    """
    env_path = root / env_file
    before = newerp_schema.modified_ns(env_path)
    declared_value, declared_source = newerp_schema.resolve_connection_value(env_path, environ)
    needles = newerp_schema.credential_needles(declared_value)

    ddl_path = root / DDL_RELATIVE_PATH
    contract_text = ddl_path.read_text(encoding="utf-8-sig", errors="replace") if ddl_path.is_file() else ""
    map_path = root / SCHEMA_MAP_RELATIVE_PATH
    map_text = map_path.read_text(encoding="utf-8", errors="replace") if map_path.is_file() else ""
    digests = {
        DDL_RELATIVE_PATH: sha256_text(contract_text) if contract_text else "not_available",
        SCHEMA_MAP_RELATIVE_PATH: sha256_text(map_text) if map_text else "not_available",
    }

    ddl_inventory = parse_planned_ddl(contract_text)
    schema_map = load_schema_map(root)
    rows = key_resolution_rows(schema_map, ddl_inventory)
    body, substitutions = reconcile_ddl(contract_text, rows)
    header = script_header(
        generated_at, digests, rows, substitutions, ddl_inventory["create_table_count"]
    )
    header_lines = len(header.splitlines())
    for substitution in substitutions:
        substitution["line"] = int(substitution["line"]) + header_lines
    script_text = header + body
    checks = static_checks(contract_text, script_text, rows, substitutions)

    resolved_driver = driver_module
    resolved_driver_facts: dict[str, Any] | None = (
        dict(driver_facts) if driver_facts is not None else None
    )
    if compile_check and resolved_driver_facts is None:
        if resolved_driver is None:
            resolved_driver, resolved_driver_facts = newerp_schema.load_driver_module()
        else:
            resolved_driver_facts = newerp_schema.describe_driver_module(resolved_driver)
    driver_names = list((resolved_driver_facts or {}).get("odbc_driver_names") or [])

    if compile_check:
        compile_facts = disposable_compile_check(
            script_text,
            driver_module=resolved_driver,
            driver_names=driver_names,
            declared_value=declared_value,
            instance=disposable_instance,
            catalog=disposable_catalog,
            expected_table_count=checks["create_table_count"],
        )
    else:
        compile_facts = {
            "requested": False,
            "status": COMPILE_STATUS_NOT_REQUESTED,
            "reason": (
                "the compile check is opt-in: regenerate with --compile in an interpreter where the ODBC driver "
                "module is importable"
            ),
            "target": None,
            "target_guard": None,
            "statement_guard": None,
            "execution": None,
            "idempotent_second_pass": False,
            "tables_created_visible": None,
            "expected_table_count_matched": False,
            "shared_connection_used": False,
            "applied_to_shared_database": False,
        }
    declared_value = None  # drop the in-memory reference before anything is rendered

    allowed, allowed_source = newerp_schema.controller_patterns(
        root, "paths", "executor_allowed", ALLOWED_ARTIFACT_PATTERNS
    )
    protected, _ = newerp_schema.controller_patterns(root, "paths", "protected", ())
    facts: dict[str, Any] = {
        "generated_at": generated_at,
        "contract": {
            "path": DDL_RELATIVE_PATH,
            "sha256": digests[DDL_RELATIVE_PATH],
            "read_only": True,
            "table_count": ddl_inventory["create_table_count"],
            "index_count": ddl_inventory["create_index_count"],
            "column_count": ddl_inventory["column_count"],
            "declared_neutral_keys": sorted(ddl_inventory["declarations"]),
        },
        "schema_map": {
            "path": SCHEMA_MAP_RELATIVE_PATH,
            "sha256": digests[SCHEMA_MAP_RELATIVE_PATH],
            "read_only": True,
            "available": schema_map["available"],
            "task_id": schema_map["task_id"],
            "status": schema_map["status"],
            "inspection_status": schema_map["inspection_status"],
            "table_count": schema_map["table_count"],
            "organization_domain_status": (
                (schema_map.get("domains") or {}).get("organization") or {}
            ).get("status"),
            "reason": schema_map["reason"],
        },
        "connection_diagnostic": {
            "declared_setting_name": CONNECTION_KEY,
            "declared_setting_present": declared_source != "not_declared",
            "declared_setting_source": declared_source,
            "declared_value_recorded": False,
            "environment_file": env_file,
            "environment_file_read_only": True,
            "environment_file_modified_time_unchanged_during_run": before
            == newerp_schema.modified_ns(env_path),
            "shared_connection_used": False,
        },
        "reconciliation": {
            "rule_count": len(CLASSIFICATION_RULES),
            "rules": [dict(rule) for rule in CLASSIFICATION_RULES],
            "rows": rows,
            "row_count": len(rows),
            "resolved_count": len([row for row in rows if row["resolution"] == "resolved_direct"]),
            "needs_review_count": len(
                [row for row in rows if row["resolution"] == "type_resolved_target_needs_review"]
            ),
            "app_local_count": len([row for row in rows if row["resolution"] == "app_local"]),
            "unresolved_count": len(
                [row for row in rows if row["resolution"] == "unresolved_human_gate"]
            ),
            "retyped_columns": [
                str(row["neutral_key"]) for row in rows if row.get("raised_to_shared_type")
            ],
            "kept_neutral_columns": [
                str(row["neutral_key"])
                for row in rows
                if row["resolution"] in {"unresolved_human_gate", "app_local"}
            ],
        },
        "draft": {
            "path": SCRIPT_RELATIVE_PATH,
            "sha256": sha256_text(script_text),
            "generated": True,
            "applied": False,
            "applied_to_shared_database": False,
            "batch_count": checks["batch_count"],
            "substitution_count": len(substitutions),
            "substitutions": substitutions,
            "guard_facts": checks,
            "application_owner": (
                "review only: the controller Human Gate and the GPT review own any application of this draft"
            ),
        },
        # Rendered draft text for the writer; build_report never copies it into the published report.
        "draft_text": script_text,
        "compile_check": compile_facts,
        "human_gate": {
            "shared_structure_change": True,
            "applied_by_this_task": False,
            "foreign_key_to_shared_table_generated": False,
            "duplicate_master_table_created": False,
            "requires_approval_before_execution": True,
            "note": (
                "Applying the draft, adding a constraint to a shared table or migrating the shared database is a "
                "shared-structure change that stays behind the controller Human Gate and the GPT review."
            ),
        },
        "payload": {
            "controller_payload_section_present": payload_received,
            "sources": list(payload_sources),
            "note": (
                "Task identity, GPT plan, dependency ordering and allowed paths were read from the controller-owned "
                "records listed in sources. No queue, approval, branch or state file was written by the executor."
            ),
        },
        "executor_paths": list(executor_paths),
        "report_paths": list(report_paths),
        "doc_paths": list(doc_paths),
        "script_paths": list(script_paths),
        "allowed_paths": allowed,
        "allowed_paths_source": allowed_source,
        "protected_paths": protected,
    }
    return facts, needles


def build_report(facts: dict[str, Any]) -> dict[str, Any]:
    """Assemble the value-free NEWAPP-005 reconciliation report from the collected facts."""
    reconciliation = facts["reconciliation"]
    draft = facts["draft"]
    compile_check = facts["compile_check"]
    execution = compile_check.get("execution") or {}
    executor_paths = (
        list(facts["executor_paths"])
        + list(facts["report_paths"])
        + list(facts["doc_paths"])
        + list(facts["script_paths"])
    )
    path_view = newerp_schema.path_guard_compatibility(
        executor_paths,
        facts["allowed_paths"],
        facts["protected_paths"],
        facts["allowed_paths_source"],
    )
    report: dict[str, Any] = {
        "task_id": TASK_ID,
        "task_title": TASK_TITLE,
        "task_phase": TASK_PHASE,
        "task_depends_on": list(TASK_DEPENDS_ON),
        "artifact": "newapp_ddl_key_reconciliation",
        "schema_version": 1,
        "generated_at": facts["generated_at"],
        "generated_by": "newapp_executor (Cline/DeepSeek)",
        "completion_authority": (
            "the GPT brain (Codex desktop / ChatGPT mobile Remote) review, never the executor"
        ),
        "executor_payload": facts["payload"],
        "safety_contract": {
            "shared_connection_used": False,
            "declared_value_recorded": False,
            "environment_file_written": False,
            "shared_objects_created_or_changed": False,
            "ddl_or_dml_executed_against_shared_database": False,
            "draft_applied": False,
            "disposable_target_only": compile_check["status"]
            in {
                COMPILE_STATUS_COMPILED,
                COMPILE_STATUS_FAILED,
                COMPILE_STATUS_PERSISTED,
            },
            "compile_transaction_rolled_back": execution.get("transaction_rolled_back"),
            "objects_persisted_after_rollback": execution.get("tables_after_rollback"),
            "duplicate_master_table_created": False,
            "foreign_key_to_shared_table_generated": False,
            "secrets_read_into_memory_only": True,
        },
        "source_contracts": {
            "planned_ddl": facts["contract"],
            "accepted_schema_map": facts["schema_map"],
        },
        "shared_connection_diagnostic": facts["connection_diagnostic"],
        "classification_rules": reconciliation["rules"],
        "reconciliation": {key: value for key, value in reconciliation.items() if key != "rules"},
        "reconciled_draft": draft,
        "disposable_compile_check": compile_check,
        "human_gate": facts["human_gate"],
        "limitations": list(LIMITATIONS),
        "artifacts": {
            "reports": list(facts["report_paths"]),
            "documents": list(facts["doc_paths"]),
            "drafts": list(facts["script_paths"]),
            "executor_paths": list(facts["executor_paths"]),
            "planned_ddl_contract": facts["contract"]["path"],
            "accepted_schema_map": facts["schema_map"]["path"],
        },
        "path_guard": path_view,
        "artifact_checks": {},
        "artifact_check_passes": 0,
        "artifact_checks_verified": False,
        "status": "attention_required",
        "unresolved": [],
        "acceptance_evidence": [],
    }
    report["acceptance_evidence"] = acceptance_evidence(report)
    report["unresolved"] = unresolved_items(report)
    return report


def acceptance_evidence(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Score the task acceptance criteria and the plan validation focus from the recorded facts."""
    reconciliation = report["reconciliation"]
    checks = report["reconciled_draft"]["guard_facts"]
    compile_check = report["disposable_compile_check"]
    execution = compile_check.get("execution") or {}
    declared_keys = set(report["source_contracts"]["planned_ddl"]["declared_neutral_keys"])
    classified_keys = {str(row["neutral_key"]) for row in reconciliation["rows"]}
    resolved = {
        str(row["neutral_key"])
        for row in reconciliation["rows"]
        if row["resolution"] in {"resolved_direct", "type_resolved_target_needs_review"}
    }
    unresolved_keys = {
        str(row["neutral_key"])
        for row in reconciliation["rows"]
        if row["resolution"] == "unresolved_human_gate"
    }
    compile_ok = bool(
        compile_check["status"] == COMPILE_STATUS_COMPILED
        and compile_check["idempotent_second_pass"]
        and compile_check["expected_table_count_matched"]
        and execution.get("rollback_confirmed")
    )
    return [
        {
            "criterion": (
                "Every neutral CustomerKey, SupplierKey, UserKey and TenantId reference is classified against the "
                "accepted NEWAPP-003 map; resolved keys carry the recorded shared key type and unresolved keys keep "
                "their neutral declaration."
            ),
            "evidence": (
                "declared neutral keys: "
                + str(len(declared_keys))
                + "; classified rows: "
                + str(len(reconciliation["rows"]))
                + "; shared type applied: "
                + ", ".join(reconciliation["retyped_columns"])
                + "; kept neutral: "
                + ", ".join(reconciliation["kept_neutral_columns"])
            ),
            "satisfied": bool(
                declared_keys
                and declared_keys <= classified_keys
                and {"CustomerKey", "SupplierKey", "UserKey"} <= resolved
                and "TenantId" in unresolved_keys
            ),
        },
        {
            "criterion": "The reconciled draft compiles and re-runs idempotently in a disposable database.",
            "evidence": (
                "compile status: "
                + str(compile_check["status"])
                + "; passes completed: "
                + str(execution.get("passes_completed"))
                + "; batches executed: "
                + str(execution.get("batches_executed"))
                + "; app tables visible in the transaction: "
                + str(execution.get("tables_visible_in_transaction"))
                + "; app tables after rollback: "
                + str(execution.get("tables_after_rollback"))
            ),
            "satisfied": compile_ok,
        },
        {
            "criterion": (
                "No destructive change to an existing NEWERP table, no shared object touched and no duplicate "
                "customer or supplier master table created."
            ),
            "evidence": (
                "static guard status: "
                + str(checks["status"])
                + "; destructive batches: "
                + str(len(checks["destructive_batches"]))
                + "; external schema batches: "
                + str(len(checks["external_schema_batches"]))
                + "; shared objects changed: no"
            ),
            "satisfied": bool(
                checks["status"] == "passed"
                and not checks["destructive_batches"]
                and not checks["external_schema_batches"]
                and not report["human_gate"]["applied_by_this_task"]
            ),
        },
        {
            "criterion": (
                "A migration plan and rollback notes exist, and every shared-structure change stops at the Human "
                "Gate."
            ),
            "evidence": (
                "documents: "
                + ", ".join(report["artifacts"]["documents"])
                + "; applied by this task: no; approval required before execution: yes"
            ),
            "satisfied": bool(
                report["artifacts"]["documents"]
                and report["human_gate"]["requires_approval_before_execution"]
                and not report["human_gate"]["applied_by_this_task"]
            ),
        },
        {
            "criterion": (
                "Generated artifacts stay inside the executor allowed paths and contain no credential material."
            ),
            "evidence": "checked by the credential guard, the repository scanner and the path guard",
            "satisfied": False,
        },
    ]


def unresolved_items(report: dict[str, Any]) -> list[dict[str, Any]]:
    """List the explicit unresolved items, including the compile-check state and the Human Gate boundary."""
    items: list[dict[str, Any]] = []
    rows = report["reconciliation"]["rows"]
    for row in rows:
        if row["resolution"] == "unresolved_human_gate":
            items.append(
                {
                    "item": "authoritative shared binding for " + str(row["neutral_key"]),
                    "reason": str(row["reason"]),
                    "next_action": (
                        "decide the binding during GPT review; the declaration stays neutral until then and any "
                        "constraint stays behind the Human Gate"
                    ),
                }
            )
        elif row["resolution"] == "type_resolved_target_needs_review":
            targets = ", ".join(
                str(evidence["target"])
                for evidence in row["evidence"]
                if evidence.get("target")
            )
            items.append(
                {
                    "item": "authoritative table for " + str(row["neutral_key"]),
                    "reason": "the storage type is recorded but more than one candidate target exists: " + targets,
                    "next_action": (
                        "confirm which candidate owns the relationship during GPT review; the draft already carries "
                        "the recorded shared key type"
                    ),
                }
            )
    compile_check = report["disposable_compile_check"]
    if compile_check["status"] == COMPILE_STATUS_NOT_REQUESTED:
        items.append(
            {
                "item": "disposable compile check",
                "reason": str(compile_check["reason"]),
                "next_action": (
                    "re-run the module with --compile in an interpreter where the ODBC driver module is importable "
                    "to add the live compile evidence; the venv interpreter without the module reports it explicitly"
                ),
            }
        )
    elif compile_check["status"] in {COMPILE_STATUS_ENGINE_UNAVAILABLE, COMPILE_STATUS_TARGET_REFUSED}:
        items.append(
            {
                "item": "disposable compile check",
                "reason": "the check could not run: " + str(compile_check["reason"]),
                "next_action": (
                    "provide a local disposable engine (a LocalDB instance or an approved NEWAPP disposable "
                    "catalog) and re-run with --compile; the shared database is never used"
                ),
            }
        )
    elif compile_check["status"] in {COMPILE_STATUS_FAILED, COMPILE_STATUS_PERSISTED}:
        items.append(
            {
                "item": "disposable compile check",
                "reason": "the check reported a failure: " + str(compile_check["reason"]),
                "next_action": "fix the draft in a follow-up task before any migration review",
            }
        )
    items.append(
        {
            "item": "shared schema application of the reconciled draft",
            "reason": (
                "applying the draft, adding a constraint to a shared table or migrating the shared database is a "
                "shared-structure change owned by the Human Gate"
            ),
            "next_action": (
                "record the Human Gate approval through the controller and execute the migration in a disposable "
                "database first; this task only produces the reviewed draft"
            ),
        }
    )
    items.append(
        {
            "item": "foreign key and view proposals",
            "reason": (
                "a direct foreign key to a shared master table and a view-backed read model are the preferred "
                "mapping, but both would change shared structures"
            ),
            "next_action": (
                "raise them as a separate gated change after the migration review instead of generating them in "
                "this draft"
            ),
        }
    )
    return items


def md_row(cells: Sequence[Any]) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def md_yes_no(value: Any) -> str:
    return "yes" if value else "no"


def regeneration_command(module_path: str = MODULE_RELATIVE_PATH) -> str:
    """Render the documented regeneration command from the recorded module path."""
    return (
        ".venv\\Scripts\\python.exe "
        + str(module_path).replace("/", "\\")
        + " --write   (add --compile in an interpreter that can import the ODBC driver module)"
    )


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def mapping_table(report: dict[str, Any]) -> list[str]:
    """Render the neutral-key reconciliation table."""
    lines = [
        md_row(
            [
                "Neutral key",
                "Declared",
                "Sites",
                "Resolution",
                "Shared target",
                "Recorded type",
                "Draft type",
            ]
        ),
        md_row(["---", "---", "---", "---", "---", "---", "---"]),
    ]
    for row in report["reconciliation"]["rows"]:
        target = "-"
        if row["target_table"] and row["target_column"]:
            target = f"{row['target_table']}.{row['target_column']}"
        elif row["evidence"]:
            candidate = ", ".join(
                str(evidence["target"]) for evidence in row["evidence"] if evidence.get("target")
            )
            target = candidate or "-"
        draft_type = row["resolved_type"] or "-"
        if row["resolution"] in {"unresolved_human_gate", "app_local"}:
            draft_type = row["declared_type"] + " (kept)"
        lines.append(
            md_row(
                [
                    f"`{row['neutral_key']}`",
                    f"`{row['declared_type']}`",
                    row["declaration_count"],
                    f"`{row['resolution']}`",
                    target,
                    f"`{row['target_type']}`" if row["target_type"] else "-",
                    f"`{draft_type}`",
                ]
            )
        )
    return lines


def render_markdown(report: dict[str, Any]) -> str:
    """Render the human migration plan and rollback notes from the same value-free facts."""
    contract = report["source_contracts"]["planned_ddl"]
    schema_map = report["source_contracts"]["accepted_schema_map"]
    checks = report["reconciled_draft"]["guard_facts"]
    compile_check = report["disposable_compile_check"]
    execution = compile_check.get("execution") or {}
    lines: list[str] = []
    add = lines.append
    add("# NEWAPP app-schema DDL reconciliation against the actual NEWERP keys")
    add("")
    add(
        "Task: **"
        + report["task_id"]
        + " - "
        + report["task_title"]
        + "** (phase "
        + report["task_phase"]
        + ", depends on "
        + ", ".join(report["task_depends_on"])
        + ")."
    )
    add("")
    add(
        "This document is generated from the same value-free facts as `.ai/generated/NEWAPP-005-ddl-reconciliation.json`"
        " and the generated draft `database/NEWAPP_app_schema_reconciled_V1.sql`, so regenerate all three with `"
        + regeneration_command()
        + "` instead of editing them by hand."
    )
    add("")
    add(
        "Generated at "
        + str(report["generated_at"])
        + " by "
        + str(report["generated_by"])
        + ". Completion authority: "
        + str(report["completion_authority"])
        + "."
    )
    add("")
    add("## 1. Authority of record")
    add("")
    add(md_row(["Concern", "Authoritative artifact"]))
    add(md_row(["---", "---"]))
    add(md_row(["Planned app-schema DDL contract", "`" + str(contract["path"]) + "`"]))
    add(md_row(["Actual shared keys and types", "`" + str(schema_map["path"]) + "` (accepted NEWAPP-003 map)"]))
    add(md_row(["Machine-readable facts", "`.ai/generated/NEWAPP-005-ddl-reconciliation.json`"]))
    add(md_row(["Generated reconciled draft", "`" + str(report["reconciled_draft"]["path"]) + "`"]))
    add(md_row(["Controller allowed paths", "`.ai/agent_config.yaml#paths.executor_allowed`"]))
    add(md_row(["Task definition", "`docs/NEWAPP_TASKS_V1.yaml#NEWAPP-005`"]))
    add(md_row(["GPT plan for this task", "`.ai/brain/decisions/NEWAPP-005-plan.json`"]))
    add("")
    add("## 2. Safety contract for this reconciliation")
    add("")
    add("1. The planned DDL contract and the accepted NEWAPP-003 map are opened read-only. No shared object was created, altered, dropped or queried and no business row was read by this task.")
    add("2. The shared connection declaration stays in memory: it is only read to prove that the optional compile target is not the shared server, the shared catalog or a declared credential, and nothing about it is recorded, hashed or rendered.")
    add("3. Declared shared connection present: " + md_yes_no(report["shared_connection_diagnostic"]["declared_setting_present"]) + " (source label `" + str(report["shared_connection_diagnostic"]["declared_setting_source"]) + "`), value recorded: no, shared connection used: no.")
    add("4. The environment file is opened read-only and never written. Write timestamp unchanged across the run: " + md_yes_no(report["shared_connection_diagnostic"]["environment_file_modified_time_unchanged_during_run"]) + ".")
    add("5. A neutral key is retyped only when the accepted map records a single authoritative target column with a recorded type; a key whose target needs review keeps its neutral declaration and becomes an explicit unresolved item.")
    add("6. The generated draft contains only additive, guarded app-schema objects: " + str(checks["create_table_count"]) + " tables, " + str(checks["create_index_count"]) + " indexes, no DDL that changes an existing object, no foreign key to a shared table and no duplicate customer or supplier master table.")
    add("7. The optional compile check runs the draft on a local disposable target inside one transaction that is always rolled back. Shared objects changed: no. Draft applied by this task: no.")
    add("8. Both generated artifacts and the draft are re-checked with the credential guard, the repository scanner and the path guard before publication.")
    add("")
    add("## 3. Source contracts inspected")
    add("")
    add(md_row(["Fact", "Value"]))
    add(md_row(["---", "---"]))
    add(md_row(["Planned DDL digest", "`sha256:" + str(contract["sha256"])[:16] + "...`"]))
    add(md_row(["Accepted map digest", "`sha256:" + str(schema_map["sha256"])[:16] + "...`"]))
    add(md_row(["Planned DDL objects", str(contract["table_count"]) + " tables, " + str(contract["index_count"]) + " indexes, " + str(contract["column_count"]) + " columns"]))
    add(md_row(["Accepted map status", f"`{schema_map['status']}` (task {schema_map['task_id']}, inspection `{schema_map['inspection_status']}`)"]))
    add(md_row(["Accepted map tables", schema_map["table_count"]]))
    add(md_row(["Organization/tenant domain in the accepted map", f"`{schema_map['organization_domain_status']}`"]))
    add(md_row(["Neutral keys declared by the contract", ", ".join(f"`{name}`" for name in contract["declared_neutral_keys"])]))
    add("")
    add("## 4. Neutral key reconciliation")
    add("")
    add(
        "Every neutral key declared by the contract is classified by the rules below. A key is only raised to a shared "
        "type when the accepted map records a single authoritative target column with a recorded type; anything else "
        "keeps its neutral declaration and is listed as an unresolved item in section 12."
    )
    add("")
    add(md_row(["Resolution", "Rule"]))
    add(md_row(["---", "---"]))
    for rule in report["classification_rules"]:
        add(md_row([f"`{rule['resolution']}`", rule["rule"]]))
    add("")
    add(md_row(["Statistic", "Value"]))
    add(md_row(["---", "---"]))
    add(md_row(["Classified keys", report["reconciliation"]["row_count"]]))
    add(md_row(["Resolved with a direct target", report["reconciliation"]["resolved_count"]]))
    add(md_row(["Type resolved, target needs review", report["reconciliation"]["needs_review_count"]]))
    add(md_row(["App-owned identifiers", report["reconciliation"]["app_local_count"]]))
    add(md_row(["Unresolved behind the Human Gate", report["reconciliation"]["unresolved_count"]]))
    add("")
    lines.extend(mapping_table(report))
    add("")
    add("## 5. Mapping policy")
    add("")
    add("1. Preferred mapping for a resolved key is a direct foreign key to the shared master column, or a repository join when the constraint is not approved yet.")
    add("2. A view-backed read model is an acceptable alternative mapping for an app extension table, but creating a view over a shared table is a shared-structure change, so it is recorded as a proposal instead of a generated statement.")
    add("3. No duplicate customer, supplier, user or organization master table is created: the existing NEWERP tables stay the system of record and this draft only adds app extension tables that reference them by key.")
    add("4. A key that is not confirmed by the accepted map keeps its neutral declaration, so a later shared-structure decision can bind it without rewriting an unverified type.")
    add("")
    add("## 6. Generated reconciled draft")
    add("")
    add(md_row(["Fact", "Value"]))
    add(md_row(["---", "---"]))
    add(md_row(["Draft path", "`" + str(report["reconciled_draft"]["path"]) + "`"]))
    add(md_row(["Draft digest", "`sha256:" + str(report["reconciled_draft"]["sha256"])[:16] + "...`"]))
    add(md_row(["Applied", "no (review artifact only)"]) )
    add(md_row(["Batches", report["reconciled_draft"]["batch_count"]]))
    add(md_row(["Guarded batches", checks["guarded_batch_count"]]))
    add(md_row(["Column declarations retyped", report["reconciled_draft"]["substitution_count"]]))
    add(md_row(["Static guard status", f"`{checks['status']}` (" + str(checks["passed_count"]) + "/" + str(checks["check_count"]) + " checks)"]))
    add("")
    add(md_row(["Guard check", "Result", "Detail"]))
    add(md_row(["---", "---", "---"]))
    for check in checks["checks"]:
        add(md_row([f"`{check['check']}`", md_yes_no(check["passed"]), check["detail"]]))
    add("")
    if report["reconciled_draft"]["substitutions"]:
        candidates_by_key: dict[str, str] = {}
        for row in report["reconciliation"]["rows"]:
            targets = [
                str(evidence["target"]) for evidence in row["evidence"] if evidence.get("target")
            ]
            if targets:
                candidates_by_key[str(row["neutral_key"])] = " or ".join(targets)
        add(md_row(["Line", "Table", "Column", "From", "To", "Neutral key", "Shared target"]))
        add(md_row(["---", "---", "---", "---", "---", "---", "---"]))
        for substitution in report["reconciled_draft"]["substitutions"]:
            target_label = (
                substitution["target"]
                or candidates_by_key.get(str(substitution["neutral_key"]))
                or "-"
            )
            add(
                md_row(
                    [
                        substitution["line"],
                        "`" + str(substitution["table"]) + "`",
                        "`" + str(substitution["column"]) + "`",
                        "`" + str(substitution["from"]) + "`",
                        "`" + str(substitution["to"]) + "`",
                        "`" + str(substitution["neutral_key"]) + "`",
                        "`" + str(target_label) + "`",
                    ]
                )
            )
        add("")
    add("## 7. Migration plan")
    add("")
    add("The plan is ordered so that every state-changing step is reviewable, reversible in a disposable database and gated before the shared database is touched.")
    add("")
    add(md_row(["Step", "Action", "Verification", "Gate"]))
    add(md_row(["---", "---", "---", "---"]))
    digest = "sha256:" + str(report["reconciled_draft"]["sha256"])[:16] + "..."
    add(
        md_row(
            [
                "1",
                "GPT review accepts this reconciliation and the generated draft digest `" + digest + "`.",
                "Every reconciliation row has a resolution and every unresolved item is acknowledged.",
                "GPT review",
            ]
        )
    )
    add(
        md_row(
            [
                "2",
                "Record the controller Human Gate approval for applying the app-schema draft.",
                "The approval names the disposable database and forbids destructive statements.",
                "Human Gate",
            ]
        )
    )
    add(
        md_row(
            [
                "3",
                "Run the draft twice in a disposable database (owner: the migration task).",
                "Both runs succeed, the second run changes nothing, and the app object inventory matches "
                + str(checks["create_table_count"])
                + " tables and "
                + str(checks["create_index_count"])
                + " indexes.",
                "Human Gate",
            ]
        )
    )
    add(
        md_row(
            [
                "4",
                "Compare the shared catalog metadata before and after to confirm that no NEWERP object changed.",
                "No shared table, column, index or constraint differs and no duplicate master table exists.",
                "Human Gate",
            ]
        )
    )
    add(
        md_row(
            [
                "5",
                "Apply the same reviewed draft to the shared database inside an approved window, recording the applied digest.",
                "The applied digest equals the reviewed digest and the verification of step 4 still passes.",
                "Human Gate",
            ]
        )
    )
    add(
        md_row(
            [
                "6",
                "Implement the server-side repository mappings with the now-recorded key types.",
                "Queries read the existing shared master data and no app-only master copy is written.",
                "dependency NEWAPP-008",
            ]
        )
    )
    add(
        md_row(
            [
                "7",
                "Raise the foreign key and view proposals as a separate change.",
                "The proposal lists the exact constraint per resolved key and repeats the non-destructive verification.",
                "Human Gate",
            ]
        )
    )
    add("")
    add("## 8. Rollback notes")
    add("")
    add("1. The draft is additive: it only creates app-schema objects, so a rollback never has to restore a modified shared table.")
    add("2. Record the applied digest `sha256:" + str(report["reconciled_draft"]["sha256"])[:16] + "...` and keep the pre-apply catalog metadata snapshot, so a rollback can prove which app objects were added.")
    add("3. Reversing the change means removing the app objects that this draft created, in reverse creation order, and that removal is itself a destructive operation: it is never executed by this module and requires a separate Human Gate approval.")
    add("4. If business rows were already written into the app tables, take a backup of those app tables before the removal and restore them only through the approved migration procedure.")
    add("5. Because every creation is guarded by an `OBJECT_ID` or `NOT EXISTS` check, re-running the draft after a partial failure is safe and converges to the same object inventory.")
    add("6. Keys that stay neutral keep their declarations across a rollback, so no key value is converted back and forth.")
    add("7. This task executed no rollback and generated no destructive statement; the rollback plan is documentation for the gated migration task.")
    add("")
    add("## 9. Disposable compile check")
    add("")
    target = compile_check.get("target") or {}
    add(md_row(["Fact", "Value"]))
    add(md_row(["---", "---"]))
    add(md_row(["Requested", md_yes_no(compile_check["requested"])]))
    add(md_row(["Status", f"`{compile_check['status']}`"]))
    add(md_row(["Reason", compile_check.get("reason") or "-"]))
    add(md_row(["Target instance", f"`{target.get('instance', '-')}` (" + str(target.get("server_kind", "-")) + ")"]))
    add(md_row(["Target catalog", f"`{target.get('catalog', '-')}` (" + str(target.get("catalog_kind", "-")) + ")"]))
    add(md_row(["Selected driver", target.get("driver") or "-"]))
    add(md_row(["Integrated security", md_yes_no(target.get("integrated_security"))]))
    add(md_row(["Shared connection used", md_yes_no(compile_check.get("shared_connection_used"))]))
    add(md_row(["Connection string recorded", md_yes_no(target.get("connection_string_recorded"))]))
    add(md_row(["Passes completed", execution.get("passes_completed", 0)]))
    add(md_row(["Batches executed", execution.get("batches_executed", 0)]))
    add(md_row(["App tables visible in the transaction", execution.get("tables_visible_in_transaction")]))
    add(md_row(["App tables after rollback", execution.get("tables_after_rollback")]))
    add(md_row(["Rollback confirmed", md_yes_no(execution.get("rollback_confirmed"))]))
    add(md_row(["Commit issued", md_yes_no(execution.get("commit_called"))]))
    target_guard = compile_check.get("target_guard") or {}
    statement_guard = compile_check.get("statement_guard") or {}
    if target_guard:
        add(
            md_row(
                [
                    "Target guard",
                    f"`{'passed' if target_guard.get('allowed') else 'refused'}`",
                    "; ".join(target_guard.get("reasons") or []) or "target is local, disposable and unrelated to the shared database",
                ]
            )
        )
    if statement_guard:
        add(
            md_row(
                [
                    "Statement guard",
                    f"`{statement_guard.get('status')}`",
                    "evaluated " + str(statement_guard.get("batch_count", 0)) + " batches before execution",
                ]
            )
        )
    add("")
    add(
        "The check never uses the shared server, its catalog or its credentials: a target that is not a local "
        "disposable LocalDB instance or a disposable catalog is refused before any statement runs. The transaction is "
        "rolled back and the post-rollback count proves that no app object remained."
    )
    add("")
    add("## 10. Human Gate boundary")
    add("")
    add(md_row(["Concern", "State"]))
    add(md_row(["---", "---"]))
    add(md_row(["Shared structure change required", md_yes_no(report["human_gate"]["shared_structure_change"])]))
    add(md_row(["Applied by this task", md_yes_no(report["human_gate"]["applied_by_this_task"])]))
    add(md_row(["Foreign key to a shared table generated", md_yes_no(report["human_gate"]["foreign_key_to_shared_table_generated"])]))
    add(md_row(["Duplicate master table created", md_yes_no(report["human_gate"]["duplicate_master_table_created"])]))
    add(md_row(["Approval required before execution", md_yes_no(report["human_gate"]["requires_approval_before_execution"])]))
    add("")
    add(str(report["human_gate"]["note"]))
    add("")
    add("## 11. Known limits")
    add("")
    for index, limitation in enumerate(report["limitations"], start=1):
        add(str(index) + ". " + str(limitation))
    add("")
    add("## 12. Unresolved items")
    add("")
    add(md_row(["Item", "Reason", "Next action"]))
    add(md_row(["---", "---", "---"]))
    for item in report["unresolved"]:
        add(md_row([item["item"], item["reason"], item["next_action"]]))
    add("")
    add("## 13. Acceptance evidence")
    add("")
    add(md_row(["Criterion", "Evidence", "Satisfied"]))
    add(md_row(["---", "---", "---"]))
    for entry in report["acceptance_evidence"]:
        add(md_row([entry["criterion"], entry["evidence"], md_yes_no(entry["satisfied"])]))
    add("")
    add(
        "Artifact guard status: report `"
        + str((report["artifact_checks"].get("report_credential_guard") or {}).get("status"))
        + "`, document `"
        + str((report["artifact_checks"].get("documentation_credential_guard") or {}).get("status"))
        + "`, draft `"
        + str((report["artifact_checks"].get("draft_credential_guard") or {}).get("status"))
        + "`, repository scanner `"
        + str((report["artifact_checks"].get("scanner_self_check") or {}).get("status"))
        + "`; path guard accepted every recorded path: "
        + md_yes_no(report["path_guard"]["all_paths_accepted"])
        + "."
    )
    add("")
    add("---")
    add("")
    add("Regenerate with `" + regeneration_command() + "`.")
    add("")
    return "\n".join(lines) + "\n"


def artifact_checks(
    report_text: str, markdown: str, draft_text: str, needles: Sequence[str]
) -> dict[str, Any]:
    """Run the credential guard on all three artifacts and the repository scanner over all three."""
    return {
        "report_credential_guard": newerp_schema.credential_leak_guard(
            report_text, needles, REPORT_RELATIVE_PATH
        ),
        "documentation_credential_guard": newerp_schema.credential_leak_guard(
            markdown, needles, DOC_RELATIVE_PATH
        ),
        "draft_credential_guard": newerp_schema.credential_leak_guard(
            draft_text, needles, SCRIPT_RELATIVE_PATH
        ),
        "scanner_self_check": newerp_schema.scanner_self_check(
            {
                REPORT_RELATIVE_PATH: report_text,
                DOC_RELATIVE_PATH: markdown,
                SCRIPT_RELATIVE_PATH: draft_text,
            }
        ),
    }


def apply_acceptance(report: dict[str, Any]) -> dict[str, Any]:
    """Score the artifact criterion from the guard results and set the overall report status."""
    checks = report.get("artifact_checks") or {}
    guard_ok = bool(
        (checks.get("report_credential_guard") or {}).get("status") == "passed"
        and (checks.get("documentation_credential_guard") or {}).get("status") == "passed"
        and (checks.get("draft_credential_guard") or {}).get("status") == "passed"
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
    report: dict[str, Any],
    needles: Sequence[str],
    *,
    draft_text: str,
    attempts: int = 4,
) -> tuple[dict[str, Any], str, str, str]:
    """Render, validate and embed the artifact check results until the rendering is stable."""
    report["artifact_checks"] = artifact_checks("", "", "", needles)
    report_text = render_json(report)
    markdown = render_markdown(report)
    passes = 0
    for _ in range(int(attempts)):
        checks = artifact_checks(report_text, markdown, draft_text, needles)
        passes += 1
        if report.get("artifact_checks") == checks:
            break
        report["artifact_checks"] = checks
        report_text = render_json(report)
        markdown = render_markdown(report)
    report["artifact_check_passes"] = passes
    report = apply_acceptance(report)
    markdown = render_markdown(report)
    final_checks = artifact_checks(render_json(report), markdown, draft_text, needles)
    report["artifact_checks_verified"] = bool(
        report["artifact_checks_verified"] and report.get("artifact_checks") == final_checks
    )
    report_text = render_json(report)
    return report, report_text, markdown, draft_text


def publication_blocked(report: dict[str, Any]) -> str | None:
    """Return the blocking reason when a credential guard failed, else ``None``."""
    checks = report.get("artifact_checks") or {}
    for key in (
        "report_credential_guard",
        "documentation_credential_guard",
        "draft_credential_guard",
    ):
        entry = checks.get(key) or {}
        if entry.get("status") == "failed":
            return f"{key} reported {entry.get('findings_count', 0)} credential finding(s)"
    if (checks.get("scanner_self_check") or {}).get("status") == "failed":
        return "the repository scanner reported a finding in the rendered artifacts"
    return None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile the planned NEWAPP app-schema DDL with the actual NEWERP keys, render the value-free "
            "NEWAPP-005 artifacts and optionally compile the draft on a local disposable engine."
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
        "--write", action="store_true", help="write the report, the document and the draft"
    )
    parser.add_argument(
        "--compile",
        action="store_true",
        help=(
            "also run the drafted batches twice inside one rolled-back transaction on a local disposable engine; "
            "requires an interpreter where the ODBC driver module is importable"
        ),
    )
    parser.add_argument(
        "--disposable-instance",
        default=DEFAULT_DISPOSABLE_INSTANCE,
        help="local disposable instance for --compile; only a (localdb) instance is accepted",
    )
    parser.add_argument(
        "--disposable-catalog",
        default=DEFAULT_DISPOSABLE_CATALOG,
        help=(
            "disposable catalog for --compile; only the scratch database or a NEWAPP disposable catalog is accepted"
        ),
    )
    parser.add_argument(
        "--report",
        action="append",
        default=None,
        help=f"report path, repeatable, default <root>/{REPORT_RELATIVE_PATH}",
    )
    parser.add_argument(
        "--doc", default=None, help=f"documentation path, default <root>/{DOC_RELATIVE_PATH}"
    )
    parser.add_argument(
        "--script", default=None, help=f"draft path, default <root>/{SCRIPT_RELATIVE_PATH}"
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    report_targets = [Path(item) for item in (args.report or [str(root / REPORT_RELATIVE_PATH)])]
    doc_targets = [Path(args.doc) if args.doc else root / DOC_RELATIVE_PATH]
    script_targets = [Path(args.script) if args.script else root / SCRIPT_RELATIVE_PATH]

    facts, needles = collect_facts(
        root,
        generated_at=utc_now(),
        env_file=args.env_file,
        compile_check=bool(args.compile),
        disposable_instance=args.disposable_instance,
        disposable_catalog=args.disposable_catalog,
        payload_received=True,
        report_paths=[newerp_schema.relative_to_root(root, str(item)) for item in report_targets],
        doc_paths=[newerp_schema.relative_to_root(root, str(item)) for item in doc_targets],
        script_paths=[newerp_schema.relative_to_root(root, str(item)) for item in script_targets],
    )
    report = build_report(facts)
    report, report_text, markdown, draft_text = finalize_report(
        report, needles, draft_text=str(facts["draft_text"])
    )
    blocked = publication_blocked(report)
    if blocked:
        print(
            json.dumps(
                {"status": "publication_blocked", "reason": blocked, "task_id": TASK_ID},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    written: list[str] = []
    if args.write:
        for target, text in (
            [(item, report_text) for item in report_targets]
            + [(item, markdown) for item in doc_targets]
            + [(item, draft_text) for item in script_targets]
        ):
            newerp_schema.atomic_write_text(target, text)
            written.append(newerp_schema.relative_to_root(root, str(target)))

    compile_facts = report["disposable_compile_check"]
    execution = compile_facts.get("execution") or {}
    summary = {
        "task_id": TASK_ID,
        "status": report["status"],
        "write": bool(args.write),
        "artifacts_written": written,
        "report": report["artifacts"]["reports"],
        "documents": report["artifacts"]["documents"],
        "drafts": report["artifacts"]["drafts"],
        "reconciliation": {
            "rows": report["reconciliation"]["row_count"],
            "resolved": report["reconciliation"]["resolved_count"],
            "needs_review": report["reconciliation"]["needs_review_count"],
            "app_local": report["reconciliation"]["app_local_count"],
            "unresolved": report["reconciliation"]["unresolved_count"],
            "retyped_columns": report["reconciliation"]["retyped_columns"],
        },
        "draft": {
            "path": report["reconciled_draft"]["path"],
            "sha256": report["reconciled_draft"]["sha256"],
            "applied": report["reconciled_draft"]["applied"],
        },
        "static_checks": report["reconciled_draft"]["guard_facts"]["status"],
        "compile_check": {
            "status": compile_facts["status"],
            "passes_completed": execution.get("passes_completed"),
            "batches_executed": execution.get("batches_executed"),
            "tables_visible_in_transaction": execution.get("tables_visible_in_transaction"),
            "tables_after_rollback": execution.get("tables_after_rollback"),
            "rollback_confirmed": execution.get("rollback_confirmed"),
        },
        "acceptance_evidence_satisfied": sum(
            1 for entry in report["acceptance_evidence"] if entry["satisfied"]
        ),
        "acceptance_evidence_total": len(report["acceptance_evidence"]),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
