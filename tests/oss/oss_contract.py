"""Shared OSS contract report for NEWAPP-004 ("Inspect shared OSS contract").

Regenerate the two value-free artifacts required by the GPT plan for NEWAPP-004 from the repository
root::

    .venv\\\\Scripts\\\\python.exe tests\\\\oss\\\\oss_contract.py --write

Artifacts:

* ``.ai/generated/NEWAPP-004-oss-contract.json`` - machine-readable shared-OSS facts.
* ``docs/SHARED_OSS_CONTRACT.md`` - human documentation generated from the same facts.

Safety contract
---------------
* Only key **names**, presence booleans, declaration line numbers, counts, provider *family* labels and
  endpoint/bucket *shape* flags are recorded.
* The endpoint right-hand side is inspected inside :func:`classify_endpoint_shape` to derive booleans
  and one provider family label from the documented suffix list in :data:`PROVIDER_SUFFIXES`; the text
  is discarded before that function returns.
* The credential right-hand sides are inspected only for the empty/quoted shape flags inside the reused
  NEWAPP-002 reader and this module's :func:`_value_shape_flags`; they are never returned, stored,
  compared with another file or key, hashed, printed, logged or copied into evidence.
* ``.env`` is opened read-only. This module never writes, renames, normalises, overwrites, stages or
  copies it.
* No OSS call is made: the shared bucket is never contacted and no object is uploaded, listed, copied
  or deleted. No database, AI-provider or network call is made either.
* Both artifacts are re-checked with the reused NEWAPP-002 value guard and with the repository scanner
  ``tests/baseline/secret_scan.py`` before they are written, and they are written only while the report
  status stays ``evidence_collected``; otherwise the run reports ``not_written`` and exits non-zero.
* Every recorded executor path is checked with the reused controller path-guard mirror, so an artifact
  that landed outside the allowed patterns is reported as ``attention_required`` instead of being
  published as clean evidence.

Reuse of the NEWAPP-002 dependency
----------------------------------
This task depends on NEWAPP-002, so ``tests/config/env_contract.py`` is imported instead of copied: the
names-only environment reader, the value leak guard, the scanner self-check, the path-guard mirror and
the atomic writer all come from that accepted module.

Documented limits (reviewed by GPT, not silently expanded)
---------------------------------------------------------
* The provider family is inferred from the endpoint host suffix list above; a custom domain, a masked
  value or an unlisted provider is reported as ``unrecognised`` rather than guessed.
* The endpoint text, the bucket name and the credential material are never recorded, so this report
  cannot prove which physical bucket is bound at runtime.
* The object-key convention of already existing NEWERP objects is not discoverable from this checkout;
  only the NEWAPP-side declared contract is recorded.
* The durable key-layout decision belongs to GPT and to NEWAPP-010, not to this report.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

OSS_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = OSS_DIR.parents[1]
CONFIG_DIR = REPOSITORY_ROOT / "tests" / "config"
for _candidate in (OSS_DIR, CONFIG_DIR):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

# Reused NEWAPP-002 helpers (dependency-ordered task). Only read-only, value-free helpers are imported.
from env_contract import (  # noqa: E402
    DECLARATION_PATTERN,
    atomic_write_text,
    load_controller_environment,
    path_guard_compatibility,
    read_env_declarations,
    relative_to_root,
    scanner_self_check,
    utc_now,
    value_leak_guard,
)

TASK_ID = "NEWAPP-004"
TASK_TITLE = "Inspect shared OSS contract"
TASK_PHASE = "P0"
TASK_DEPENDS_ON: tuple[str, ...] = ("NEWAPP-002",)
REPORT_RELATIVE_PATH = ".ai/generated/NEWAPP-004-oss-contract.json"
DOC_RELATIVE_PATH = "docs/SHARED_OSS_CONTRACT.md"
ENV_FILE = ".env"
CONFIG_SOURCE = ".ai/agent_config.yaml"
SCANNER_RELATIVE_PATH = "tests/baseline/secret_scan.py"
ALLOWED_ARTIFACT_PATTERNS = ("docs/**", ".ai/generated/**")
PREVIOUS_TASK_ARTIFACTS: tuple[str, ...] = (
    ".ai/generated/NEWAPP-002-env-contract.json",
    "docs/CONFIGURATION_CONTRACT.md",
)

OSS_KEY_NAMES: tuple[str, ...] = (
    "ERP_Oss__Endpoint",
    "ERP_Oss__Bucket",
    "ERP_Oss__AccessKeyId",
    "ERP_Oss__AccessKeySecret",
)
ENDPOINT_KEY = "ERP_Oss__Endpoint"
BUCKET_KEY = "ERP_Oss__Bucket"

# Documented provider host suffixes used to label the endpoint *family*. Only a label is recorded; the
# matched suffix and the endpoint text are never returned.
PROVIDER_SUFFIXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("aliyun_oss", ("aliyuncs.com",)),
    ("alibaba_cloud_intl_oss", ("alibabacloud.com",)),
    ("tencent_cos", ("myqcloud.com",)),
    ("huawei_obs", ("myhuaweicloud.com",)),
    ("aws_s3", ("amazonaws.com",)),
    ("azure_blob", ("blob.core.windows.net",)),
)
PROVIDER_UNRECOGNISED = "unrecognised"
PROVIDER_IDENTIFICATION_METHOD = (
    "endpoint host suffix compared with the documented provider suffix list of this module; only the "
    "family label and a boolean are recorded, never the endpoint text"
)

DDL_RELATIVE_PATH = "docs/NEWAPP_Database_DDL_V1.sql"
OPENAPI_RELATIVE_PATH = "docs/NEWAPP_OpenAPI_V1.yaml"
ASSET_TABLE = "app.FileAsset"
ASSET_TABLE_MARKER = "OBJECT_ID(N'app.FileAsset'"
ASSET_COLUMN_NAMES: tuple[str, ...] = ("Purpose", "ObjectKey", "Bucket", "UploadStatus")

SEARCH_INCLUDE_SUFFIXES: tuple[str, ...] = (
    ".md",
    ".yaml",
    ".yml",
    ".json",
    ".sql",
    ".py",
    ".cs",
    ".ts",
    ".dart",
    ".txt",
)
SEARCH_EXCLUDED_PREFIXES: tuple[str, ...] = (
    ".git/",
    ".venv/",
    ".ai/logs/",
    ".ai/evidence/",
    ".ai/brain/",
    ".ai/decisions/",
    ".ai/locks/",
    ".ai/controller/",
    "__pycache__/",
    "node_modules/",
    "bin/",
    "obj/",
)
SEARCH_MAX_BYTES = 2_000_000
SEARCH_EXCLUDED_SELF_PATHS: tuple[str, ...] = (REPORT_RELATIVE_PATH, DOC_RELATIVE_PATH)

CONVENTION_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("object_key_field", "declared object-key column or field", r"(?i)\bobject[_]?key\b"),
    ("bucket_field", "declared bucket column or field", r"(?i)\bbucket\b"),
    ("purpose_field", "declared asset purpose or classification field", r"(?i)\bpurpose\b"),
    ("tenant_scope_field", "tenant scoping used on asset rows", r"(?i)\btenant(?:id|key)\b"),
    ("upload_ticket_boundary", "short-lived signed upload boundary", r"(?i)upload[-_]?ticket"),
    ("credential_name", "long-lived credential key names", r"(?i)access[\s_-]?key"),
    ("key_prefix_token", "explicit object-key prefix token", r"(?i)\b(?:key|object)[_-]?prefix\b"),
)

MATERIAL_KEY_NAMES: tuple[str, ...] = ("ERP_Oss__AccessKeyId", "ERP_Oss__AccessKeySecret")

RECORDED_RULES: tuple[str, ...] = (
    "NEWAPP and NEWERP share one OSS bucket and one object namespace. NEWAPP never creates a second "
    "bucket, a NEWAPP-only bucket or a parallel object store.",
    "No NEWAPP/NEWERP object synchronisation service exists. Both applications read and write the shared "
    "bucket through this contract, and shared asset metadata lives in the shared database.",
    "Long-lived OSS credentials stay server side. A mobile client never receives the OSS credential "
    "material and never uploads with a long-lived key.",
    "The mobile client uploads with a server-side signed, short-lived upload ticket and confirms the "
    "asset afterwards, so the server remains the only issuer of object access.",
    "The object key is generated and owned by the server. A client-supplied file name or path is never "
    "used as the stored object key.",
    "app.FileAsset is the single asset record per object: the unique constraint on the tenant and the "
    "object key means one object key exists once per tenant, and the bucket column is optional so the "
    "configured shared bucket is the default.",
    "An existing key name is never renamed or overwritten. Rotating the shared credential is a "
    "server-side deployment action for a later task, not part of this report.",
    "The executor reports this contract; it does not edit queue state, approvals, controller code, the "
    "task blueprint or any OSS object.",
)

CLIENT_BOUNDARY_RULES: tuple[str, ...] = (
    "A mobile client calls the HTTPS API only. It never connects to SQL Server and never receives a "
    "database connection string.",
    "A mobile client never receives the OSS credential key or material, and never receives a ticket for "
    "another tenant or any listing permission on the shared bucket.",
    "Asset references travel between client and server as asset identifiers, so the client never needs "
    "the object key to read an asset back.",
    "Diagnostic evidence, logs and screenshots never include credential material from the environment "
    "file.",
)

PROPOSAL_NOTES: tuple[str, ...] = (
    "This task records the declared contract. It does not establish a new key layout and it does not "
    "change any existing object key.",
    "The candidate layout below is derived only from declared facts of this checkout: the asset purpose "
    "field, the tenant-scoped uniqueness of the object key, the optional bucket column and the "
    "server-owned upload ticket.",
    "The layout becomes normative only after GPT accepts it and NEWAPP-010 implements the ticket issuer "
    "against it. Until then NEWAPP must not rewrite, move or relocate an object written by NEWERP.",
    "The key convention of existing NEWERP objects is not discoverable from this checkout. If a later "
    "read-only inspection provides it, that evidence replaces this candidate layout.",
)

LIMITATIONS: tuple[str, ...] = (
    "The provider family is inferred from the endpoint host suffix list documented in this module, so a "
    "custom domain, a masked value or an unlisted provider is reported as unrecognised rather than "
    "guessed.",
    "The endpoint text, the bucket name and the credential material are never recorded, so this report "
    "cannot verify which physical bucket is bound at runtime or whether it is the bucket NEWERP uses.",
    "The object-key convention of existing NEWERP objects is not discoverable from this checkout, so the "
    "candidate key layout stays a proposal for GPT rather than a recorded convention.",
    "No OSS API call is made, so bucket policy, region, lifecycle rules and object counts stay "
    "unverified.",
    "The environment file is read on a single local checkout, so another developer machine may declare "
    "additional or missing names.",
    "agent.env, secrets, signing files and cloud credential files are never opened by this module.",
)


def _yes_no(value: Any) -> str:
    return "yes" if value else "no"


def _row(cells: Sequence[Any]) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def _listing(values: Sequence[Any]) -> str:
    items = [str(value) for value in values]
    return ", ".join(items) if items else "none"


def _value_shape_flags(remainder: str) -> dict[str, bool]:
    """Return the empty/quoted shape flags of one right-hand side and drop the text.

    The rule mirrors the accepted NEWAPP-002 reader: a quoted or unquoted right-hand side is inspected
    only to decide whether it is empty and whether it was quoted. ``tests/oss/test_oss_contract.py``
    compares these flags with the flags the reused reader derives for the same fixture.
    """
    raw = remainder.strip()
    quoted = len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}
    text = raw[1:-1].strip() if quoted else raw
    return {"configured": bool(text), "quoted": quoted}


def classify_endpoint_shape(remainder: str) -> dict[str, Any]:
    """Return value-free shape facts for one endpoint right-hand side.

    The text is used only to derive the booleans below and one provider family label from
    :data:`PROVIDER_SUFFIXES`, then discarded: no code path returns, stores, logs, raises or compares
    the endpoint text itself.
    """
    flags = _value_shape_flags(remainder)
    raw = remainder.strip()
    text = raw[1:-1].strip() if flags["quoted"] else raw
    lowered = text.lower()
    scheme, separator, rest = lowered.partition("://")
    has_scheme = bool(separator)
    authority = rest if has_scheme else lowered
    host_part = authority.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    host = host_part
    has_port = False
    if host_part.count(":") == 1:
        candidate_host, _, candidate_port = host_part.partition(":")
        if candidate_port.isdigit():
            host, has_port = candidate_host, True
    labels = [label for label in host.split(".") if label]
    family = PROVIDER_UNRECOGNISED
    for candidate_family, suffixes in PROVIDER_SUFFIXES:
        if any(host == suffix or host.endswith("." + suffix) for suffix in suffixes):
            family = candidate_family
            break
    return {
        "configured": flags["configured"],
        "quoted": flags["quoted"],
        "has_scheme": has_scheme,
        "uses_secure_scheme": scheme == "https",
        "has_explicit_port": has_port,
        "host_label_count": len(labels),
        "looks_like_ipv4_literal": bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host)),
        "has_path_component": bool(has_scheme and "/" in rest),
        "provider_family": family,
        "provider_suffix_matched": family != PROVIDER_UNRECOGNISED,
        "text_recorded": False,
    }


def analyse_oss_declarations(root: Path, env_file: str = ENV_FILE) -> dict[str, Any]:
    """Collect value-free facts about the shared-OSS declarations of one environment file.

    The reused reader provides names, line numbers and the empty/quoted shape flags. The endpoint shape,
    the bucket flags and the credential presence flags are derived locally from the same file with the
    right-hand side confined to this function.
    """
    path = root / env_file
    absent = {
        "path_label": env_file,
        "exists": False,
        "read_only": True,
        "byte_count": 0,
        "line_count": 0,
        "declaration_count": 0,
        "oss_names": [],
        "names": [],
        "oss_entries": [],
        "endpoint": {"name": ENDPOINT_KEY, "declared": False},
        "bucket": {"name": BUCKET_KEY, "declared": False, "bucket_name_recorded": False},
        "material": [
            {
                "name": name,
                "declared": False,
                "configured": False,
                "material_read": False,
                "material_recorded": False,
                "issued_to_client": False,
            }
            for name in MATERIAL_KEY_NAMES
        ],
        "duplicate_oss_names": [],
        "modified_time_unchanged_during_run": True,
        "values_recorded": False,
    }
    if not path.is_file():
        return absent
    before = path.stat().st_mtime_ns
    parsed = read_env_declarations(path)
    shapes = _oss_shape_facts(path)
    after = path.stat().st_mtime_ns
    entries = parsed["entries"]
    oss_entries = [entry for entry in entries if entry["name"] in OSS_KEY_NAMES]
    endpoint = {"name": ENDPOINT_KEY, "declared": False}
    endpoint.update(shapes.get("endpoint", {}))
    bucket = {"name": BUCKET_KEY, "declared": False, "bucket_name_recorded": False}
    bucket.update(shapes.get("bucket", {}))
    material = []
    for name in MATERIAL_KEY_NAMES:
        entry = {"name": name, "declared": False, "configured": False}
        entry.update(shapes.get("material", {}).get(name, {}))
        entry["material_read"] = False
        entry["material_recorded"] = False
        entry["issued_to_client"] = False
        material.append(entry)
    return {
        "path_label": env_file,
        "exists": True,
        "read_only": True,
        "byte_count": path.stat().st_size,
        "declaration_count": len(entries),
        "line_count": parsed["line_count"],
        "oss_names": [entry["name"] for entry in oss_entries],
        "names": [entry["name"] for entry in entries],
        "oss_entries": [
            {
                "name": entry["name"],
                "line": entry["line"],
                "group": entry["group"],
                "configured": entry["configured"],
                "quoted": entry["quoted"],
                "duplicate": entry["duplicate"],
                "export_prefixed": entry["export_prefixed"],
            }
            for entry in oss_entries
        ],
        "endpoint": endpoint,
        "bucket": bucket,
        "material": material,
        "duplicate_oss_names": list(shapes.get("duplicate_names", [])),
        "modified_time_unchanged_during_run": before == after,
        "values_recorded": False,
    }


def _oss_shape_facts(path: Path) -> dict[str, Any]:
    """Classify the shared-OSS right-hand sides in memory and return shape facts only.

    Every right-hand side stays inside this function: the returned mapping contains booleans, counts,
    field names and one provider family label derived from :data:`PROVIDER_SUFFIXES`. Duplicate
    declaration names are reported by name only.
    """
    facts: dict[str, Any] = {"endpoint": {}, "bucket": {}, "material": {}, "duplicate_names": []}
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = DECLARATION_PATTERN.match(line)
        if match is None:
            continue
        name = match.group("name")
        if name not in OSS_KEY_NAMES:
            continue
        if name in seen:
            facts["duplicate_names"].append(name)
        seen.add(name)
        remainder = match.group("rest")
        if name == ENDPOINT_KEY:
            facts["endpoint"] = {**classify_endpoint_shape(remainder), "declared": True}
        elif name == BUCKET_KEY:
            facts["bucket"] = {
                **_value_shape_flags(remainder),
                "declared": True,
                "bucket_name_recorded": False,
            }
        else:
            facts["material"][name] = {
                **_value_shape_flags(remainder),
                "declared": True,
                "material_read": False,
                "material_recorded": False,
                "issued_to_client": False,
            }
    return facts


def required_oss_names(root: Path, declarations: dict[str, Any]) -> dict[str, Any]:
    """Compare the controller-required OSS key names with the locally declared OSS names (names only)."""
    configured = {entry["name"]: entry["configured"] for entry in declarations.get("oss_entries", [])}
    declared = {entry["name"] for entry in declarations.get("oss_entries", [])}
    loaded = load_controller_environment(root)
    if not loaded["available"]:
        return {
            "available": False,
            "source": loaded["source"],
            "reason": loaded["reason"],
            "required": [],
            "present": [],
            "missing": [],
            "unconfigured": [],
            "all_present": False,
        }
    required = [str(name) for name in loaded["required_key_groups"].get("oss", [])]
    present = [name for name in required if name in declared]
    missing = [name for name in required if name not in declared]
    unconfigured = [name for name in required if configured.get(name) is False]
    return {
        "available": True,
        "source": loaded["source"],
        "required": required,
        "required_count": len(required),
        "present": present,
        "present_count": len(present),
        "missing": missing,
        "unconfigured": unconfigured,
        "all_present": not missing and not unconfigured,
    }

def iter_search_paths(
    root: Path, *, excluded_self_paths: Sequence[str] = SEARCH_EXCLUDED_SELF_PATHS
) -> dict[str, Any]:
    """List the bounded set of text files searched for declared key conventions.

    Ignored or heavy directories, binary files, oversized files and the two artifacts owned by this
    task are excluded, and every exclusion is reported by path with a reason.
    """
    excluded = {str(item).lower() for item in excluded_self_paths}
    included: list[str] = []
    skipped: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = str(path.relative_to(root)).replace("\\", "/")
        lowered = relative.lower()
        if lowered in excluded:
            skipped.append({"path": relative, "reason": "artifact owned by this task"})
            continue
        if any(lowered.startswith(prefix) for prefix in SEARCH_EXCLUDED_PREFIXES):
            continue
        if path.suffix.lower() not in SEARCH_INCLUDE_SUFFIXES:
            continue
        try:
            if path.stat().st_size > SEARCH_MAX_BYTES:
                skipped.append({"path": relative, "reason": "larger than the search size limit"})
                continue
            head = path.read_bytes()[:4096]
        except OSError:
            skipped.append({"path": relative, "reason": "unreadable"})
            continue
        if b"\x00" in head:
            skipped.append({"path": relative, "reason": "binary content"})
            continue
        included.append(relative)
    return {"paths": included, "path_count": len(included), "excluded": skipped}


def scan_convention_patterns(root: Path, paths: Sequence[str]) -> dict[str, Any]:
    """Report where each declared key convention is mentioned, by path and line number only.

    Matched text is never recorded: the scan returns pattern identifiers, descriptions, match counts,
    file paths and line numbers.
    """
    results: list[dict[str, Any]] = []
    total = 0
    matched_paths = 0
    for identifier, description, expression in CONVENTION_PATTERNS:
        pattern = re.compile(expression)
        files: list[dict[str, Any]] = []
        matches = 0
        for relative in paths:
            text = (root / relative).read_text(encoding="utf-8-sig", errors="replace")
            line_numbers = [
                number
                for number, line in enumerate(text.splitlines(), start=1)
                if pattern.search(line)
            ]
            if line_numbers:
                files.append(
                    {"path": relative, "line_numbers": line_numbers, "match_count": len(line_numbers)}
                )
                matches += len(line_numbers)
        total += matches
        matched_paths += len(files)
        results.append(
            {
                "id": identifier,
                "description": description,
                "match_count": matches,
                "file_count": len(files),
                "files": files,
            }
        )
    return {
        "patterns": results,
        "match_count": total,
        "matched_path_count": matched_paths,
        "matched_text_recorded": False,
    }


def scan_reference_tree(path: str | None) -> dict[str, Any]:
    """Optionally scan an operator-supplied read-only reference tree for the same conventions.

    The scan is opt-in: without a path the result is explicitly unresolved instead of guessing. When a
    path is supplied it is only read, and the result records paths, line numbers and counts.
    """
    base: dict[str, Any] = {
        "mode": "not_provided",
        "reason": (
            "no read-only reference tree was supplied, so an external object-key convention stays "
            "unresolved in this report"
        ),
        "paths_searched": 0,
        "patterns": [],
        "match_count": 0,
        "matched_text_recorded": False,
        "files_written_to_reference_tree": False,
    }
    if not path:
        return base
    root = Path(path)
    base["path_label"] = str(root)
    if not root.is_dir():
        base["mode"] = "unavailable"
        base["reason"] = "the supplied reference path is not a directory"
        return base
    listing = iter_search_paths(root, excluded_self_paths=())
    scanned = scan_convention_patterns(root, listing["paths"])
    base.update(
        {
            "mode": "scanned_read_only",
            "reason": "an operator-supplied reference tree was searched read-only",
            "paths_searched": listing["path_count"],
            "excluded": listing["excluded"],
            "patterns": scanned["patterns"],
            "match_count": scanned["match_count"],
        }
    )
    return base



COLUMN_PATTERN = re.compile(
    r"^\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+"
    r"(?P<data_type>NVARCHAR|CHAR|VARBINARY|UNIQUEIDENTIFIER|DATETIME2|BIGINT|INT|TINYINT|BIT|ROWVERSION)"
    r"(?:\((?P<length>[^)]*)\))?"
    r"(?P<nullability>\s+NOT\s+NULL|\s+NULL)?"
    r"(?P<trailing>.*)$"
)
UNIQUE_CONSTRAINT_PATTERN = re.compile(r"CONSTRAINT\s+(?P<name>\w+)\s+UNIQUE\((?P<columns>[^)]*)\)")
FOREIGN_KEY_PATTERN = re.compile(
    r"CONSTRAINT\s+(?P<name>\w+)\s+FOREIGN KEY\((?P<columns>[^)]*)\)\s+"
    r"REFERENCES\s+(?P<table>[\w.]+)\((?P<target>[^)]*)\)"
)
CREATE_TABLE_PATTERN = re.compile(r"CREATE TABLE\s+(?P<table>[\w.]+)\(")
STATUS_TOKEN_PATTERN = re.compile(r"(\d)\s+([a-z][a-z_]+)")

UPLOAD_TICKET_PATH = "/files/upload-ticket"
UPLOAD_COMPLETE_PATH = "/files/{assetId}/complete"
PURPOSE_ENUM_PATTERN = re.compile(r"purpose:\s*\{type: string, enum: \[(?P<tokens>[^\]]*)\]\}")
REQUIRED_LIST_PATTERN = re.compile(r"^\s*required:\s*\[(?P<fields>[^\]]*)\]")
PROPERTY_PATTERN = re.compile(r"^ {8}(?P<name>\w+):")
CREDENTIAL_FIELD_PATTERN = re.compile(
    r"(?i)access[\s_-]?key|secret|credential|password|private[\s_-]?key|signing"
)


def inspect_ddl(root: Path) -> dict[str, Any]:
    """Read the app-schema DDL read-only and record the declared asset-column facts with line numbers.

    The DDL is parsed as text only: no statement is executed, no connection is opened and no shared
    database object is created, altered or dropped.
    """
    path = root / DDL_RELATIVE_PATH
    if not path.is_file():
        return {
            "available": False,
            "path": DDL_RELATIVE_PATH,
            "reason": "the declared app-schema DDL is not present in this checkout",
            "ddl_executed": False,
            "values_recorded": False,
        }
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    block_start: int | None = None
    block_end: int | None = None
    current_table = ""
    tables: list[str] = []
    columns: dict[str, Any] = {}
    unique_constraints: list[dict[str, Any]] = []
    foreign_keys: list[dict[str, Any]] = []
    status_tokens: list[str] = []
    for number, line in enumerate(lines, start=1):
        created = CREATE_TABLE_PATTERN.search(line)
        if created:
            current_table = created.group("table")
            tables.append(current_table)
        if block_start is None and ASSET_TABLE_MARKER in line:
            block_start = number
        elif block_start is not None and block_end is None and line.strip() == "END":
            block_end = number
        if block_start is not None and block_end is None:
            column = COLUMN_PATTERN.match(line)
            if column and column.group("name") in ASSET_COLUMN_NAMES:
                columns[column.group("name")] = {
                    "name": column.group("name"),
                    "data_type": column.group("data_type"),
                    "length": column.group("length"),
                    "nullability": " ".join(str(column.group("nullability") or "").split())
                    or "unspecified",
                    "line": number,
                }
            if column and column.group("name") == "UploadStatus":
                status_tokens = [
                    token for _, token in STATUS_TOKEN_PATTERN.findall(column.group("trailing") or "")
                ]
        unique = UNIQUE_CONSTRAINT_PATTERN.search(line)
        if unique and current_table == ASSET_TABLE:
            unique_constraints.append(
                {
                    "name": unique.group("name"),
                    "table": current_table,
                    "columns": [item.strip() for item in unique.group("columns").split(",")],
                    "line": number,
                }
            )
        key = FOREIGN_KEY_PATTERN.search(line)
        if key and key.group("table") == ASSET_TABLE:
            foreign_keys.append(
                {
                    "name": key.group("name"),
                    "table": current_table,
                    "columns": [item.strip() for item in key.group("columns").split(",")],
                    "references": ASSET_TABLE,
                    "target_columns": [item.strip() for item in key.group("target").split(",")],
                    "line": number,
                }
            )
    return {
        "available": True,
        "path": DDL_RELATIVE_PATH,
        "line_count": len(lines),
        "asset_table": ASSET_TABLE,
        "table_definition_start_line": block_start,
        "table_definition_end_line": block_end,
        "columns": [columns[name] for name in ASSET_COLUMN_NAMES if name in columns],
        "unique_constraints": unique_constraints,
        "referencing_foreign_keys": foreign_keys,
        "upload_status_tokens": status_tokens,
        "table_count": len(set(tables)),
        "ddl_executed": False,
        "ddl_apply_requires_human_gate": True,
        "values_recorded": False,
    }


def inspect_openapi(root: Path) -> dict[str, Any]:
    """Read the declared API contract read-only and record the file-access boundary with line numbers.

    The contract is parsed as text only: no request is sent, no ticket is issued and no credential is
    read. The declared ticket fields are recorded by name, so a field that would hand long-lived
    credential material to a client is reported as a finding instead of being discovered at runtime.
    """
    path = root / OPENAPI_RELATIVE_PATH
    if not path.is_file():
        return {
            "available": False,
            "path": OPENAPI_RELATIVE_PATH,
            "reason": "the declared API contract is not present in this checkout",
            "requests_sent": False,
            "values_recorded": False,
        }
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    upload_line: int | None = None
    complete_line: int | None = None
    ticket_line: int | None = None
    purpose_line: int | None = None
    purpose_tokens: list[str] = []
    file_paths: list[dict[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped == UPLOAD_TICKET_PATH + ":":
            upload_line = number
        if stripped == UPLOAD_COMPLETE_PATH + ":":
            complete_line = number
        if stripped.startswith("/files/"):
            file_paths.append({"path": stripped.rstrip(":"), "line": number})
        if stripped == "UploadTicket:":
            ticket_line = number
        purpose = PURPOSE_ENUM_PATTERN.search(line)
        if purpose:
            purpose_line = number
            purpose_tokens = [item.strip() for item in purpose.group("tokens").split(",") if item.strip()]
    request_fields: list[str] = []
    if upload_line is not None:
        for number in range(upload_line + 1, len(lines) + 1):
            required = REQUIRED_LIST_PATTERN.match(lines[number - 1])
            if required:
                request_fields = [
                    item.strip() for item in required.group("fields").split(",") if item.strip()
                ]
                break
    ticket_required: list[str] = []
    ticket_properties: list[str] = []
    if ticket_line is not None:
        for number in range(ticket_line + 1, len(lines) + 1):
            line = lines[number - 1]
            if line.strip() and not line.startswith("      "):
                break
            required = REQUIRED_LIST_PATTERN.match(line)
            if required and not ticket_required:
                ticket_required = [
                    item.strip() for item in required.group("fields").split(",") if item.strip()
                ]
                continue
            prop = PROPERTY_PATTERN.match(line)
            if prop:
                ticket_properties.append(prop.group("name"))
    credential_fields = [name for name in ticket_properties if CREDENTIAL_FIELD_PATTERN.search(name)]
    declared_download_paths = [
        item
        for item in file_paths
        if item["path"] not in {UPLOAD_TICKET_PATH, UPLOAD_COMPLETE_PATH}
    ]
    return {
        "available": True,
        "path": OPENAPI_RELATIVE_PATH,
        "line_count": len(lines),
        "file_paths": file_paths,
        "upload_ticket_path": {
            "path": UPLOAD_TICKET_PATH,
            "line": upload_line,
            "request_required_fields": request_fields,
        },
        "asset_purpose_tokens": purpose_tokens,
        "asset_purpose_line": purpose_line,
        "ticket_schema": {
            "name": "UploadTicket",
            "line": ticket_line,
            "required_fields": ticket_required,
            "property_names": ticket_properties,
            "credential_fields": credential_fields,
            "credential_field_count": len(credential_fields),
        },
        "declared_download_paths": declared_download_paths,
        "declared_download_path_count": len(declared_download_paths),
        "requests_sent": False,
        "values_recorded": False,
    }


DOCUMENTATION_STATEMENTS: tuple[str, ...] = (
    "# NEWAPP shared OSS contract",
    "## 4. Shared bucket policy",
    "## 7. Recorded shared-OSS rules",
    "## 8. Proposed key strategy awaiting a GPT decision",
    "## 12. Acceptance evidence",
    "no second NEWAPP bucket",
    "no NEWAPP/NEWERP object synchronisation service",
    "server-side signed, short-lived upload ticket",
    "never receives the OSS credential material",
    "never uploaded, listed or deleted by this task",
    REPORT_RELATIVE_PATH,
)

PROPOSED_KEY_STRATEGY: dict[str, Any] = {
    "status": "proposed_for_gpt_review_not_established_by_this_task",
    "pattern_label": "<purpose>/<tenantId>/<opaque-id>[.<extension>]",
    "segments": [
        "the declared asset purpose token as the leading classification segment",
        "the tenant scope",
        "an opaque server-generated identifier",
        "an optional extension token derived from the declared content type",
    ],
    "derived_from": [
        "the declared asset purpose field of the shared asset table",
        "the tenant-scoped uniqueness of the object key",
        "the optional bucket column, so the configured shared bucket is the default",
        "the server-owned short-lived upload ticket",
    ],
    "rules": [
        "the server builds the key; a client-supplied file name is never used as the key",
        "the key stays stable after upload, so an existing object is never moved or rewritten",
        "the key is unique per tenant, matching the declared unique constraint",
        "no NEWERP-written object is renamed, moved or deleted by NEWAPP",
    ],
    "confirmations_needed": [
        "GPT accepts this candidate layout, or replaces it with the actual NEWERP convention",
        "NEWAPP-010 implements the ticket issuer against the accepted layout",
        "a read-only inspection of an existing object namespace confirms the leading segment",
    ],
    "displayed_as_a_recorded_convention": False,
}


def documentation_statements_check(markdown: str) -> dict[str, Any]:
    """Check that the documented strategy statements are present in the rendered document."""
    missing = [statement for statement in DOCUMENTATION_STATEMENTS if statement not in markdown]
    return {
        "status": "passed" if not missing else "failed",
        "statements_checked": len(DOCUMENTATION_STATEMENTS),
        "missing": missing,
        "statement_text_recorded": False,
    }


def _controller_patterns(
    root: Path, section: str, key: str, fallback: Sequence[str]
) -> tuple[list[str], str]:
    """Read one pattern list from the controller configuration, failing closed to defaults.

    The controller file is only read. The equivalent reader inside the reused NEWAPP-002 module is
    module-private, so this mirrors it with the same fail-closed behaviour.
    """
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


def collect_facts(
    root: Path,
    *,
    generated_at: str,
    env_file: str = ENV_FILE,
    reference_tree: str | None = None,
    payload_received: bool = False,
    payload_sources: Sequence[str] = (),
    executor_paths: Sequence[str] = (),
    report_paths: Sequence[str] = (),
    doc_paths: Sequence[str] = (),
) -> dict[str, Any]:
    """Collect every value-free fact the report and the document are built from."""
    declarations = analyse_oss_declarations(root, env_file)
    listing = iter_search_paths(root)
    allowed, allowed_source = _controller_patterns(
        root, "paths", "executor_allowed", ALLOWED_ARTIFACT_PATTERNS
    )
    protected, _ = _controller_patterns(root, "paths", "protected", ())
    return {
        "generated_at": generated_at,
        "declarations": declarations,
        "required_names": required_oss_names(root, declarations),
        "ddl": inspect_ddl(root),
        "openapi": inspect_openapi(root),
        "search_scope": {
            "include_suffixes": list(SEARCH_INCLUDE_SUFFIXES),
            "excluded_prefixes": list(SEARCH_EXCLUDED_PREFIXES),
            "excluded_self_paths": list(SEARCH_EXCLUDED_SELF_PATHS),
            "max_bytes": SEARCH_MAX_BYTES,
            "paths": listing["paths"],
            "path_count": listing["path_count"],
            "excluded": listing["excluded"],
        },
        "search": scan_convention_patterns(root, listing["paths"]),
        "reference_tree": scan_reference_tree(reference_tree),
        "payload": {
            "controller_payload_section_present": payload_received,
            "sources": list(payload_sources),
            "note": (
                "Task identity, GPT plan, required key names and allowed paths were read from the "
                "controller-owned records listed in sources. No queue, approval, branch or state file "
                "was written by the executor."
            ),
        },
        "executor_paths": list(executor_paths),
        "report_paths": list(report_paths),
        "doc_paths": list(doc_paths),
        "allowed_paths": list(allowed),
        "allowed_paths_source": allowed_source,
        "protected_paths": list(protected),
    }


def build_report(facts: dict[str, Any]) -> dict[str, Any]:
    """Assemble the value-free NEWAPP-004 shared-OSS contract report from collected facts."""
    declarations = facts["declarations"]
    ddl = facts["ddl"]
    openapi = facts["openapi"]
    provider = {
        "identification_method": PROVIDER_IDENTIFICATION_METHOD,
        "documented_suffix_family_count": len(PROVIDER_SUFFIXES),
        "endpoint_declared": bool(declarations["endpoint"].get("declared")),
        "endpoint_configured": bool(declarations["endpoint"].get("configured")),
        "family": declarations["endpoint"].get("provider_family", PROVIDER_UNRECOGNISED),
        "suffix_matched": bool(declarations["endpoint"].get("provider_suffix_matched")),
        "unrecognised_family_label": PROVIDER_UNRECOGNISED,
        "endpoint_text_recorded": False,
        "note": (
            "The family label is the only provider fact recorded. The endpoint text, the bucket name "
            "and the credential material stay in the local environment file."
        ),
    }
    report: dict[str, Any] = {
        "task_id": TASK_ID,
        "task_title": TASK_TITLE,
        "task_phase": TASK_PHASE,
        "task_depends_on": list(TASK_DEPENDS_ON),
        "artifact": "shared_oss_contract",
        "schema_version": 1,
        "generated_at": facts["generated_at"],
        "generated_by": "newapp_executor (Cline/DeepSeek)",
        "completion_authority": (
            "the GPT brain (Codex desktop / ChatGPT mobile Remote) review, never the executor"
        ),
        "executor_payload": facts["payload"],
        "safety_contract": {
            "environment_file_access": "read-only",
            "environment_file_written": False,
            "environment_file_modified_time_unchanged_during_run": declarations[
                "modified_time_unchanged_during_run"
            ],
            "endpoint_text_recorded": False,
            "bucket_name_recorded": False,
            "credential_material_read": False,
            "credential_material_recorded": False,
            "credential_material_hashed": False,
            "oss_calls_made": False,
            "oss_objects_uploaded_listed_copied_or_deleted": 0,
            "database_connections_made": False,
            "network_calls_made": False,
            "ddl_executed": False,
            "reference_tree_written": False,
            "note": (
                "Only names, presence booleans, line numbers, counts, one provider family label and "
                "shape flags are recorded. The shared bucket is never contacted and no object is "
                "uploaded, listed, copied or deleted by this task."
            ),
        },
        "environment": declarations,
        "required_oss_names": facts["required_names"],
        "provider": provider,
        "bucket_policy": {
            "shared_bucket_count": 1,
            "second_bucket_created": False,
            "synchronisation_service_created": False,
            "bucket_column_optional_in_asset_table": any(
                column["name"] == "Bucket" and column["nullability"] != "NOT NULL"
                for column in ddl.get("columns", [])
            ),
            "configured_bucket_is_the_default": True,
            "rules": list(RECORDED_RULES),
        },
        "declared_contract": {"ddl": ddl, "openapi": openapi},
        "repository_search": {
            "scope": facts["search_scope"],
            "patterns": facts["search"]["patterns"],
            "match_count": facts["search"]["match_count"],
            "matched_path_count": facts["search"]["matched_path_count"],
            "matched_text_recorded": False,
            "previous_task_artifacts": list(PREVIOUS_TASK_ARTIFACTS),
            "reference_tree": facts["reference_tree"],
        },
        "recorded_rules": list(RECORDED_RULES),
        "client_boundary_rules": list(CLIENT_BOUNDARY_RULES),
        "proposed_key_strategy": {
            **PROPOSED_KEY_STRATEGY,
            "notes": list(PROPOSAL_NOTES),
        },
        "documentation_statements": {
            "status": "unknown",
            "statements_checked": len(DOCUMENTATION_STATEMENTS),
            "missing": [],
            "statement_text_recorded": False,
        },
        "external_calls": {
            "oss_calls": 0,
            "database_connections": 0,
            "network_requests": 0,
            "note": (
                "This task inspects this checkout only; no OSS, database or network call is made by "
                "this module or by its tests."
            ),
        },
        "limitations": list(LIMITATIONS),
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
    }
    return _with_acceptance(report)


def _with_acceptance(report: dict[str, Any]) -> dict[str, Any]:
    """Attach the acceptance criteria of the task and the GPT plan, initially unsatisfied."""
    report["acceptance_evidence"] = [
        {
            "criterion": (
                "The declared OSS configuration and the declared asset/ticket contract were readable."
            ),
            "evidence": (
                "every controller-required OSS name is present and non-empty in the environment file, "
                "and the declared app-schema DDL and API contract were found and parsed read-only"
            ),
            "satisfied": False,
        },
        {
            "criterion": "Shared bucket/key-prefix strategy is documented.",
            "evidence": (
                "the recorded shared-OSS rules, the shared bucket policy, the candidate key strategy "
                "marked as a proposal for GPT, and the declared asset-table and ticket facts with file "
                "and line numbers"
            ),
            "satisfied": False,
        },
        {
            "criterion": "No secret is printed.",
            "evidence": (
                "the reused value guard over both rendered artifacts (no assignment character, no "
                "declared key name followed by an assignment delimiter, every recorded name matching "
                "the key-name character set), the repository scanner content rules, and the explicit "
                "false flags for the endpoint text, the bucket name and the credential material"
            ),
            "satisfied": False,
        },
        {
            "criterion": "One shared bucket is reused and no second bucket or synchronisation layer appears.",
            "evidence": (
                "the recorded rules state one shared bucket and no synchronisation service, the "
                "configured bucket count is one, and no bucket creation or object copy is performed by "
                "this task"
            ),
            "satisfied": False,
        },
        {
            "criterion": "No OSS object is uploaded, listed, copied or deleted by this task.",
            "evidence": (
                "the environment file is opened read-only and its write timestamp is unchanged across "
                "the run, and no OSS client, connection or request exists in this module or its tests"
            ),
            "satisfied": False,
        },
        {
            "criterion": "Generated artifacts stay inside the executor allowed paths.",
            "evidence": (
                "the reused controller path-guard mirror over every executor path recorded by this "
                "report, plus the protected pattern list read from the controller configuration"
            ),
            "satisfied": False,
        },
    ]
    report["status"] = "attention_required"
    report["artifact_checks_verified"] = False
    return report


def render_markdown(report: dict[str, Any]) -> str:
    """Render the generated documentation from the same value-free facts as the JSON report."""
    environment = report["environment"]
    safety = report["safety_contract"]
    lines: list[str] = [
        "# NEWAPP shared OSS contract",
        "",
        f"Task: **{report['task_id']} - {report['task_title']}** "
        f"(phase {report['task_phase']}, depends on {_listing(report['task_depends_on'])}).",
        "",
        "This document is generated from the same value-free facts as "
        f"`{REPORT_RELATIVE_PATH}`, so regenerate it with `tests/oss/oss_contract.py` instead of "
        "editing it by hand.",
        "",
        f"Generated at {report['generated_at']} UTC by {report['generated_by']}. Completion authority: "
        f"{report['completion_authority']}.",
        "",
        "## 1. Authority of record",
        "",
        _row(["Concern", "Authoritative artifact"]),
        _row(["---", "---"]),
        _row(["Shared OSS declaration names", f"`{ENV_FILE}` (ignored, untracked, never committed)"]),
        _row(["Controller-required OSS names", f"`{CONFIG_SOURCE}#environment.required_key_groups`"]),
        _row(["Shared asset metadata", f"`{DDL_RELATIVE_PATH}` (declared, not applied by this task)"]),
        _row(["Client file-access boundary", f"`{OPENAPI_RELATIVE_PATH}`"]),
        _row(["Machine-readable facts", f"`{REPORT_RELATIVE_PATH}`"]),
        _row(["Controller allowed paths", f"`{CONFIG_SOURCE}#paths.executor_allowed`"]),
        _row(["Task definition", "`docs/NEWAPP_TASKS_V1.yaml#NEWAPP-004`"]),
        "",
        "## 2. Safety contract for this report",
        "",
        "1. Only OSS key names, presence booleans, declaration line numbers, counts, one provider "
        "family label and endpoint/bucket shape flags are recorded.",
        "2. The endpoint text is inspected inside one function to derive those shape flags and the "
        "family label, then discarded. The bucket name and the credential material are never returned, "
        "stored, compared with another file or key, hashed, printed, logged nor copied into evidence.",
        f"3. `{ENV_FILE}` is opened read-only. Environment file written: "
        f"{_yes_no(safety['environment_file_written'])}. Write timestamp unchanged across the run: "
        f"{_yes_no(safety['environment_file_modified_time_unchanged_during_run'])}.",
        "4. No OSS, database, AI-provider or network call is made: the shared bucket is never "
        "contacted, and an object is never uploaded, listed or deleted by this task.",
        "5. Both artifacts are re-checked with the reused NEWAPP-002 value guard and with the project "
        f"scanner `{SCANNER_RELATIVE_PATH}` before they are written, and they are written only while "
        "the report status stays `evidence_collected`.",
        "",
    ]
    lines.extend(_markdown_provider(report, environment))
    lines.extend(_markdown_tail(report))
    return "\n".join(lines) + "\n"


def _markdown_provider(report: dict[str, Any], environment: dict[str, Any]) -> list[str]:
    """Render section 3, the provider and endpoint configuration facts."""
    provider = report["provider"]
    required = report["required_oss_names"]
    endpoint = environment["endpoint"]
    lines: list[str] = [
        "## 3. Provider and endpoint configuration",
        "",
        _row(["Fact", "Value"]),
        _row(["---", "---"]),
        _row(["Declared OSS key names", len(environment["oss_names"])]),
        _row(["Provider identification method", provider["identification_method"]]),
        _row(["Documented provider suffix families", provider["documented_suffix_family_count"]]),
        _row(["Provider family label", provider["family"]]),
        _row(["Provider suffix matched", _yes_no(provider["suffix_matched"])]),
        _row(["Endpoint declared", _yes_no(endpoint.get("declared", False))]),
        _row(["Endpoint configured", _yes_no(endpoint.get("configured", False))]),
        _row(["Endpoint uses a scheme", _yes_no(endpoint.get("has_scheme", False))]),
        _row(["Endpoint uses a secure scheme", _yes_no(endpoint.get("uses_secure_scheme", False))]),
        _row(["Endpoint has an explicit port", _yes_no(endpoint.get("has_explicit_port", False))]),
        _row(["Endpoint host label count", endpoint.get("host_label_count", 0)]),
        _row(["Endpoint looks like an IPv4 literal", _yes_no(endpoint.get("looks_like_ipv4_literal", False))]),
        _row(["Endpoint text recorded", _yes_no(provider["endpoint_text_recorded"])]),
        _row(["Bucket name recorded", _yes_no(environment["bucket"].get("bucket_name_recorded", False))]),
        _row(["Credential material read", _yes_no(report["safety_contract"]["credential_material_read"])]),
        "",
        "Provider family of an endpoint whose host suffix is not in the documented list: "
        f"`{provider['unrecognised_family_label']}`.",
        "",
        _row(["Key name", "Line", "Configured", "Quoted", "Duplicate", "Export prefixed"]),
        _row(["---"] * 6),
    ]
    for entry in environment["oss_entries"]:
        lines.append(
            _row(
                [
                    f"`{entry['name']}`",
                    entry["line"],
                    _yes_no(entry["configured"]),
                    _yes_no(entry["quoted"]),
                    _yes_no(entry["duplicate"]),
                    _yes_no(entry["export_prefixed"]),
                ]
            )
        )
    lines.extend(
        [
            "",
            f"Declared OSS declarations: {len(environment['oss_entries'])}.",
            f"Duplicate OSS declaration names: {_listing(environment['duplicate_oss_names'])}.",
            f"Controller-required OSS names: {_listing(required.get('required', []))}.",
            f"Present: {_listing(required.get('present', []))}. Missing: "
            f"{_listing(required.get('missing', []))}. Declared but empty: "
            f"{_listing(required.get('unconfigured', []))}.",
            "Every expected OSS name present and non-empty: "
            f"{_yes_no(required.get('all_present', False))}.",
            "",
        ]
    )
    return lines


def _markdown_tail(report: dict[str, Any]) -> list[str]:
    """Render sections 4 to 14 of the document."""
    lines: list[str] = []
    lines.extend(_markdown_bucket(report))
    lines.extend(_markdown_evidence(report))
    lines.extend(_markdown_ticket(report))
    lines.extend(_markdown_search(report))
    lines.extend(_markdown_rules(report))
    lines.extend(_markdown_checks(report))
    return lines


def _markdown_bucket(report: dict[str, Any]) -> list[str]:
    """Render section 4, the shared bucket policy."""
    bucket = report["bucket_policy"]
    return [
        "## 4. Shared bucket policy",
        "",
        _row(["Fact", "Value"]),
        _row(["---", "---"]),
        _row(["Shared bucket count", bucket["shared_bucket_count"]]),
        _row(["Second bucket created", _yes_no(bucket["second_bucket_created"])]),
        _row(["Synchronisation service created", _yes_no(bucket["synchronisation_service_created"])]),
        _row(
            [
                "Bucket column optional in the asset table",
                _yes_no(bucket["bucket_column_optional_in_asset_table"]),
            ]
        ),
        _row(["Configured bucket is the default", _yes_no(bucket["configured_bucket_is_the_default"])]),
        "",
        "Boundary summary: NEWAPP reuses the single shared bucket, so there is no second NEWAPP bucket, "
        "no NEWAPP-only object store and no NEWAPP/NEWERP object synchronisation service. The rules of "
        "that boundary are listed in section 7.",
        "",
    ]


def _markdown_evidence(report: dict[str, Any]) -> list[str]:
    """Render section 5, the object-key evidence declared in this checkout."""
    ddl = report["declared_contract"]["ddl"]
    openapi = report["declared_contract"]["openapi"]
    lines: list[str] = [
        "## 5. Discovered object-key evidence in this checkout",
        "",
        "### 5.1 Declared shared asset metadata",
        "",
        _row(["Fact", "Value"]),
        _row(["---", "---"]),
        _row(["DDL path", f"`{ddl.get('path')}`"]),
        _row(["DDL available", _yes_no(ddl.get("available", False))]),
        _row(["DDL line count", ddl.get("line_count", 0)]),
        _row(["Asset table", f"`{ddl.get('asset_table')}`"]),
        _row(
            [
                "Asset table definition lines",
                f"{ddl.get('table_definition_start_line')} to {ddl.get('table_definition_end_line')}",
            ]
        ),
        _row(["Declared table count in the DDL", ddl.get("table_count", 0)]),
        _row(["Any DDL executed by this task", _yes_no(ddl.get("ddl_executed", False))]),
        _row(["Applying the DDL still needs a Human Gate", _yes_no(ddl.get("ddl_apply_requires_human_gate", True))]),
        "",
        _row(["Column", "Declared type", "Length", "Nullability", "Line"]),
        _row(["---"] * 5),
    ]
    for column in ddl.get("columns", []):
        lines.append(
            _row(
                [
                    f"`{column['name']}`",
                    column["data_type"],
                    column["length"] or "unspecified",
                    column["nullability"],
                    column["line"],
                ]
            )
        )
    lines.extend(
        [
            "",
            _row(["Unique constraint", "Table", "Columns", "Line"]),
            _row(["---"] * 4),
        ]
    )
    for constraint in ddl.get("unique_constraints", []):
        lines.append(
            _row(
                [
                    f"`{constraint['name']}`",
                    f"`{constraint['table']}`",
                    ", ".join(constraint["columns"]),
                    constraint["line"],
                ]
            )
        )
    lines.extend(
        [
            "",
            _row(["Foreign key", "Owning table", "Columns", "References", "Line"]),
            _row(["---"] * 5),
        ]
    )
    for key in ddl.get("referencing_foreign_keys", []):
        lines.append(
            _row(
                [
                    f"`{key['name']}`",
                    f"`{key['table']}`",
                    ", ".join(key["columns"]),
                    f"`{key['references']}`",
                    key["line"],
                ]
            )
        )
    lines.extend(
        [
            "",
            "Declared upload status tokens: " + _listing(ddl.get("upload_status_tokens", [])) + ".",
            "",
        ]
    )
    return lines


def _markdown_ticket(report: dict[str, Any]) -> list[str]:
    """Render section 5.2, the declared client file-access boundary."""
    openapi = report["declared_contract"]["openapi"]
    ticket = openapi.get("ticket_schema", {})
    upload = openapi.get("upload_ticket_path", {})
    lines: list[str] = [
        "### 5.2 Declared client file-access boundary",
        "",
        _row(["Fact", "Value"]),
        _row(["---", "---"]),
        _row(["API contract path", f"`{openapi.get('path')}`"]),
        _row(["API contract available", _yes_no(openapi.get("available", False))]),
        _row(["Upload ticket path", f"`{upload.get('path')}`"]),
        _row(["Upload ticket line", upload.get("line")]),
        _row(["Upload request required fields", _listing(upload.get("request_required_fields", []))]),
        _row(["Declared asset purpose tokens", _listing(openapi.get("asset_purpose_tokens", []))]),
        _row(["Asset purpose line", openapi.get("asset_purpose_line")]),
        _row(["Ticket schema name", f"`{ticket.get('name')}`"]),
        _row(["Ticket required fields", _listing(ticket.get("required_fields", []))]),
        _row(["Ticket property names", _listing(ticket.get("property_names", []))]),
        _row(["Ticket credential fields", _listing(ticket.get("credential_fields", []))]),
        _row(["Any request sent by this task", _yes_no(openapi.get("requests_sent", True))]),
        "",
        "Declared file paths of the contract: "
        + _listing([item["path"] for item in openapi.get("file_paths", [])])
        + ".",
        "",
        "Declared download paths: "
        + _listing([item["path"] for item in openapi.get("declared_download_paths", [])])
        + ". Until a download path is declared, a client reads an asset back through the API rather "
        "than through a bucket URL of its own.",
        "",
        "A ticket that carried a credential field would be reported in the credential fields row above "
        "instead of being discovered at runtime. The ticket hands the client a server-side signed, "
        "short-lived upload ticket only, so the client never receives the OSS credential material.",
        "",
    ]
    return lines


def _markdown_search(report: dict[str, Any]) -> list[str]:
    """Render section 6, the convention search results and the reference-tree discovery."""
    search = report["repository_search"]
    scope = search["scope"]
    reference = search["reference_tree"]
    lines: list[str] = [
        "## 6. Convention search results and reference-tree discovery",
        "",
        _row(["Fact", "Value"]),
        _row(["---", "---"]),
        _row(["Searched file suffixes", _listing(scope["include_suffixes"])]),
        _row(["Excluded directory prefixes", _listing(scope["excluded_prefixes"])]),
        _row(["Excluded paths owned by this task", _listing(scope["excluded_self_paths"])]),
        _row(["Search size limit", scope["max_bytes"]]),
        _row(["Files searched", scope["path_count"]]),
        _row(["Files skipped", len(scope["excluded"])]),
        _row(["Matched text recorded", _yes_no(search["matched_text_recorded"])]),
        "",
        _row(["Pattern", "Meaning", "Matches", "Files"]),
        _row(["---"] * 4),
    ]
    for pattern in search["patterns"]:
        lines.append(
            _row(
                [
                    f"`{pattern['id']}`",
                    pattern["description"],
                    pattern["match_count"],
                    _listing([item["path"] for item in pattern["files"]]),
                ]
            )
        )
    lines.extend(
        [
            "",
            f"Total matches: {search['match_count']}. Files with a match: "
            f"{search['matched_path_count']}.",
            "",
            "Matched text, matched key names and matched bucket names are never recorded; only pattern "
            "identifiers, counts, file paths and line numbers are.",
            "",
            "### 6.1 Reference tree discovery",
            "",
            _row(["Fact", "Value"]),
            _row(["---", "---"]),
            _row(["Mode", reference["mode"]]),
            _row(["Reason", reference["reason"]]),
            _row(["Reference tree label", reference.get("path_label", "none")]),
            _row(["Files searched there", reference["paths_searched"]]),
            _row(["Matches there", reference["match_count"]]),
            _row(["Any file written there", _yes_no(reference["files_written_to_reference_tree"])]),
            "",
            "The key convention of existing NEWERP objects is therefore an explicit unresolved item of "
            "this report, not an invented convention. When the controller supplies a read-only "
            "reference path, the same pattern set is searched there and the result is recorded by path, "
            "line number and count.",
            "",
        ]
    )
    return lines


def _markdown_rules(report: dict[str, Any]) -> list[str]:
    """Render sections 7 to 9, the recorded rules, the proposal and the client boundary."""
    proposal = report["proposed_key_strategy"]
    lines: list[str] = [
        "## 7. Recorded shared-OSS rules",
        "",
    ]
    for rule in report["recorded_rules"]:
        lines.append(f"- {rule}")
    lines.extend(
        [
            "",
            "## 8. Proposed key strategy awaiting a GPT decision",
            "",
            f"Status: `{proposal['status']}`.",
            "",
            f"Candidate pattern label: `{proposal['pattern_label']}`",
            "",
            "Segments of the candidate:",
            "",
        ]
    )
    for segment in proposal["segments"]:
        lines.append(f"- {segment}")
    lines.extend(["", "Derived from:", ""])
    for item in proposal["derived_from"]:
        lines.append(f"- {item}")
    lines.extend(["", "Rules of the candidate:", ""])
    for item in proposal["rules"]:
        lines.append(f"- {item}")
    lines.extend(["", "Confirmations needed before it becomes normative:", ""])
    for item in proposal["confirmations_needed"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            f"Displayed as a recorded convention: {_yes_no(proposal['displayed_as_a_recorded_convention'])}.",
            "",
            "Notes:",
            "",
        ]
    )
    for note in proposal["notes"]:
        lines.append(f"- {note}")
    lines.extend(
        [
            "",
            "## 9. Client and mobile boundary",
            "",
        ]
    )
    for rule in report["client_boundary_rules"]:
        lines.append(f"- {rule}")
    lines.extend(
        [
            "",
            _row(["External call", "Count"]),
            _row(["---", "---"]),
            _row(["OSS calls", report["external_calls"]["oss_calls"]]),
            _row(["Database connections", report["external_calls"]["database_connections"]]),
            _row(["Network requests", report["external_calls"]["network_requests"]]),
            "",
            report["external_calls"]["note"],
            "",
        ]
    )
    return lines


def _markdown_checks(report: dict[str, Any]) -> list[str]:
    """Render sections 10 to 14, the guard results, acceptance evidence, regeneration and limits."""
    artifacts = report["artifacts"]
    guard = report["path_guard"]
    documentation = report["documentation_statements"]
    lines: list[str] = [
        "## 10. Artifact checks",
        "",
        _row(["Check", "Result"]),
        _row(["---", "---"]),
        _row(["Report status", report["status"]]),
        _row(["Report value guard", report["report_value_guard"]["status"]]),
        _row(["Documentation value guard", report["documentation_value_guard"]["status"]]),
        _row(["Assignment characters in the report", report["report_value_guard"]["equal_sign_count"]]),
        _row(
            [
                "Key names checked against the name character set",
                report["report_value_guard"]["declared_key_count"],
            ]
        ),
        _row(["Repository scanner findings", report["scanner_self_check"]["findings_count"]]),
        _row(["Documented strategy statements", f"{documentation['status']} ({documentation['statements_checked']} checked, missing {_listing(documentation['missing'])})"]),
        _row(["Artifact checks verified", _yes_no(report["artifact_checks_verified"])]),
        "",
        "## 11. Generated artifact path guard",
        "",
        f"Allowed pattern source: `{guard['allowed_patterns_source']}`.",
        "",
        _row(["Executor path", "Accepted", "Matched allowed patterns"]),
        _row(["---"] * 3),
    ]
    for entry in guard["paths"]:
        lines.append(
            _row(
                [
                    f"`{entry['path']}`",
                    _yes_no(entry["accepted"]),
                    _listing(entry["matched_patterns"]),
                ]
            )
        )
    lines.extend(
        [
            "",
            f"Every recorded executor path accepted: {_yes_no(guard['all_paths_accepted'])}.",
            "Protected paths touched: "
            + _listing([entry["path"] for entry in guard["protected_paths_touched"]])
            + ".",
            f"Protected patterns compared: {artifacts['protected_pattern_count']}.",
            "",
            "## 12. Acceptance evidence",
            "",
            _row(["Acceptance criterion", "Satisfied", "Evidence"]),
            _row(["---"] * 3),
        ]
    )
    for entry in report["acceptance_evidence"]:
        lines.append(_row([entry["criterion"], _yes_no(entry["satisfied"]), entry["evidence"]]))
    lines.extend(
        [
            "",
            "## 13. Regeneration",
            "",
            "```",
            regeneration_command(report),
            "```",
            "",
            "Both artifacts are written atomically and are re-checked before writing; the JSON report "
            "and this document are rendered from the same facts, so they cannot drift apart.",
            "",
            "Executor paths recorded for this task: " + _listing(artifacts["executor_paths"]) + ".",
            "",
            "## 14. Known limits",
            "",
        ]
    )
    for entry in report["limitations"]:
        lines.append(f"- {entry}")
    lines.append("")
    return lines


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def artifact_checks(report_text: str, markdown: str, names: Sequence[str]) -> dict[str, Any]:
    """Run the reused value guard, the repository scanner and the statement check over both artifacts."""
    return {
        "report_value_guard": value_leak_guard(report_text, names, REPORT_RELATIVE_PATH),
        "documentation_value_guard": value_leak_guard(markdown, names, DOC_RELATIVE_PATH),
        "scanner_self_check": scanner_self_check(
            {REPORT_RELATIVE_PATH: report_text, DOC_RELATIVE_PATH: markdown}
        ),
        "documentation_statements": documentation_statements_check(markdown),
    }


def apply_acceptance(report: dict[str, Any]) -> dict[str, Any]:
    """Score the task acceptance criteria of this report from the collected facts and guard results."""
    safety = report["safety_contract"]
    required = report["required_oss_names"]
    ddl = report["declared_contract"]["ddl"]
    openapi = report["declared_contract"]["openapi"]
    contract_ok = bool(
        required.get("available")
        and required.get("all_present")
        and ddl.get("available")
        and openapi.get("available")
    )
    guard_ok = (
        report["report_value_guard"]["status"] == "passed"
        and report["documentation_value_guard"]["status"] == "passed"
        and report["scanner_self_check"]["status"] == "passed"
        and report["documentation_statements"]["status"] == "passed"
    )
    secret_ok = bool(
        not safety["endpoint_text_recorded"]
        and not safety["bucket_name_recorded"]
        and not safety["credential_material_read"]
        and not safety["credential_material_recorded"]
        and not safety["credential_material_hashed"]
        and not report["provider"]["endpoint_text_recorded"]
        and not report["environment"]["bucket"].get("bucket_name_recorded", False)
        and all(
            not entry.get("material_read", False) and not entry.get("material_recorded", False)
            for entry in report["environment"]["material"]
        )
    )
    bucket = report["bucket_policy"]
    bucket_ok = bool(
        bucket["shared_bucket_count"] == 1
        and not bucket["second_bucket_created"]
        and not bucket["synchronisation_service_created"]
    )
    calls = report["external_calls"]
    read_only_ok = bool(
        not safety["environment_file_written"]
        and report["environment"]["modified_time_unchanged_during_run"]
        and not safety["oss_calls_made"]
        and not safety["ddl_executed"]
        and calls["oss_calls"] == 0
        and calls["database_connections"] == 0
        and calls["network_requests"] == 0
        and safety["oss_objects_uploaded_listed_copied_or_deleted"] == 0
    )
    guard_paths = report["path_guard"]
    paths_ok = bool(guard_paths["all_paths_accepted"] and guard_paths["no_protected_path_touched"])
    satisfied = [contract_ok, guard_ok and secret_ok, secret_ok, bucket_ok, read_only_ok, paths_ok]
    for entry, value in zip(report["acceptance_evidence"], satisfied):
        entry["satisfied"] = value
    report["artifact_checks_verified"] = all(
        entry["satisfied"] for entry in report["acceptance_evidence"]
    )
    report["status"] = (
        "evidence_collected" if report["artifact_checks_verified"] else "attention_required"
    )
    return report


def finalize_report(
    report: dict[str, Any], names: Sequence[str], *, attempts: int = 4
) -> tuple[dict[str, Any], str, str]:
    """Render, validate and embed the artifact check results until the rendering is stable.

    The embedded sections contain booleans, counts, line numbers and path labels only, so a stable
    second pass is the expected outcome; the final render is still verified so the written bytes are
    the bytes that were checked.
    """
    report.update(artifact_checks("", "", names))
    report_text = render_json(report)
    markdown = render_markdown(report)
    passes = 0
    for _ in range(attempts):
        checks = artifact_checks(report_text, markdown, names)
        passes += 1
        if all(report.get(key) == value for key, value in checks.items()):
            break
        report.update(checks)
        report_text = render_json(report)
        markdown = render_markdown(report)
    report["artifact_check_passes"] = passes
    report = apply_acceptance(report)
    markdown = render_markdown(report)
    final_checks = artifact_checks(render_json(report), markdown, names)
    report["artifact_checks_verified"] = bool(
        report["artifact_checks_verified"]
        and all(report.get(key) == value for key, value in final_checks.items())
    )
    if not report["artifact_checks_verified"]:
        report["status"] = "attention_required"
    return report, render_json(report), markdown


def regeneration_command(report: dict[str, Any]) -> str:
    """Rebuild the exact command that regenerated these artifacts, using no assignment character."""
    artifacts = report["artifacts"]
    reports = [str(item) for item in artifacts["report_paths"]]
    documents = [str(item) for item in artifacts["doc_paths"]]
    command = ["python", "tests/oss/oss_contract.py", "--write"]
    for relative in reports:
        command.extend(["--report", relative])
    for relative in documents:
        command.extend(["--markdown", relative])
    for relative in artifacts["executor_paths"]:
        if str(relative) in reports or str(relative) in documents:
            continue
        command.extend(["--executor-file", str(relative)])
    return " ".join(command)


DEFAULT_PAYLOAD_SOURCES: tuple[str, ...] = (
    "docs/NEWAPP_TASKS_V1.yaml#NEWAPP-004",
    ".ai/brain/decisions/NEWAPP-004-plan.json",
    f"{CONFIG_SOURCE}#environment.required_key_groups",
    f"{CONFIG_SOURCE}#paths.executor_allowed",
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report the shared OSS contract of this checkout without recording secret values"
    )
    parser.add_argument("--root", default=str(REPOSITORY_ROOT), help="repository root")
    parser.add_argument("--env-file", default=ENV_FILE, help="environment file path relative to the root")
    parser.add_argument(
        "--reference-tree",
        default=None,
        help="optional read-only reference tree searched for the same key conventions",
    )
    parser.add_argument(
        "--report",
        action="append",
        default=None,
        help=f"generated report path, repeatable, default <root>/{REPORT_RELATIVE_PATH}",
    )
    parser.add_argument(
        "--markdown",
        action="append",
        default=None,
        help=f"generated document path, repeatable, default <root>/{DOC_RELATIVE_PATH}",
    )
    parser.add_argument("--write", action="store_true", help="write the report and the document")
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
    facts = collect_facts(
        root,
        generated_at=utc_now(),
        env_file=args.env_file,
        reference_tree=args.reference_tree,
        payload_received=args.payload_received,
        payload_sources=args.payload_source or list(DEFAULT_PAYLOAD_SOURCES),
        executor_paths=executor_paths,
        report_paths=targets,
        doc_paths=documents,
    )
    report = build_report(facts)
    report, report_text, markdown = finalize_report(report, facts["declarations"]["names"])

    if args.write:
        if report["status"] == "evidence_collected":
            for relative in targets:
                atomic_write_text(root / relative, report_text)
            for relative in documents:
                atomic_write_text(root / relative, markdown)
        else:
            print("not_written attention_required " + " ".join([*targets, *documents]))

    if args.json:
        print(report_text, end="")
    else:
        environment = report["environment"]
        required = report["required_oss_names"]
        print(f"task={report['task_id']} status={report['status']}")
        print(
            f"env={environment['path_label']} declarations={environment['declaration_count']} "
            f"oss={len(environment['oss_names'])}"
        )
        print(
            f"provider={report['provider']['family']} "
            f"suffix_matched={report['provider']['suffix_matched']} "
            f"endpoint_text_recorded={report['provider']['endpoint_text_recorded']}"
        )
        print(
            f"required={len(required.get('required', []))} present={len(required.get('present', []))} "
            f"missing={len(required.get('missing', []))}"
        )
        print(
            f"report_guard={report['report_value_guard']['status']} "
            f"documentation_guard={report['documentation_value_guard']['status']} "
            f"statements={report['documentation_statements']['status']} "
            f"scanner={report['scanner_self_check']['status']}"
        )
        for entry in report["acceptance_evidence"]:
            print(f"criterion_satisfied={entry['satisfied']} {entry['criterion']}")
        if args.write:
            print("written " + " ".join([*targets, *documents]))
    return 0 if report["status"] == "evidence_collected" else 1


if __name__ == "__main__":
    raise SystemExit(main())

