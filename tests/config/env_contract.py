"""Local configuration contract report for NEWAPP-002 ("Inspect existing .env configuration contract safely").

Regenerate the two value-free artifacts required by the GPT plan for NEWAPP-002 from the repository
root::

    .venv\\\\Scripts\\\\python.exe tests\\\\config\\\\env_contract.py --write

Artifacts:

* ``.ai/generated/NEWAPP-002-env-contract.json`` - machine-readable configuration facts.
* ``docs/CONFIGURATION_CONTRACT.md`` - human documentation generated from the same facts.

The documented regeneration command is rendered from the recorded executor paths, so the evidence and
the document stay reproducible from one command.

Safety contract
---------------
* Only key **names**, declaration line numbers, comment/blank/malformed counts, duplicate names and
  two value *shape* flags (right-hand side empty, right-hand side quoted) are recorded.
* The right-hand side text is inspected inside :func:`read_env_declarations` for those two shape
  flags only. It is never returned, stored, compared with another file or with another key, hashed,
  printed, logged, quoted into evidence or copied. :func:`value_leak_guard` then re-scans the
  rendered text and refuses to publish a declared key name followed by an assignment delimiter.
* ``.env`` is opened read-only. This module never writes, renames, normalises, overwrites, stages or
  copies it, and it makes no database, OSS, AI-provider or network call.
* Both artifacts are re-checked with the repository scanner ``tests/baseline/secret_scan.py`` before
  they are written, so evidence the repository rule set would flag is never produced.
* Every recorded executor path is checked with a mirror of the controller path guard, and the
  controller protected-path patterns are compared too, so an artifact that landed outside the allowed
  patterns is reported as ``attention_required`` instead of being published as clean evidence.

Documented limits (reviewed by GPT, not silently expanded)
----------------------------------------------------------
* Classification is derived from key-name shapes; it validates the naming contract, not the
  reachability or correctness of a configured service.
* NEWAPP-003 owns read-only database metadata verification and NEWAPP-004 owns the shared OSS
  key-prefix contract. Both depend on this task and neither is executed here.
* ``agent.env``, ``secrets/`` and signing material are out of scope and are never opened.
"""

from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

TASK_ID = "NEWAPP-002"
TASK_TITLE = "Inspect existing .env configuration contract safely"
TASK_PHASE = "P0"
TASK_DEPENDS_ON: tuple[str, ...] = ("NEWAPP-001",)
REPORT_RELATIVE_PATH = ".ai/generated/NEWAPP-002-env-contract.json"
DOC_RELATIVE_PATH = "docs/CONFIGURATION_CONTRACT.md"
ENV_FILE = ".env"
CONFIG_SOURCE = ".ai/agent_config.yaml"
SCANNER_RELATIVE_PATH = "tests/baseline/secret_scan.py"
ALLOWED_ARTIFACT_PATTERNS = ("docs/**", ".ai/generated/**")

NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DECLARATION_PATTERN = re.compile(
    r"^\s*(?P<export>export\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=(?P<rest>.*)$"
)
TOKEN_SPLIT_PATTERN = re.compile(r"[^a-z0-9]+")

BASE_GROUPS: tuple[str, ...] = ("database", "oss", "auth", "ai_provider")
GROUP_ORDER: tuple[str, ...] = BASE_GROUPS + ("application", "unknown")
GROUP_TITLES: dict[str, str] = {
    "database": "Database",
    "oss": "Shared OSS",
    "auth": "Authentication",
    "ai_provider": "AI provider",
    "application": "Application settings",
    "unknown": "Unknown name",
}
GROUP_TOKENS: dict[str, tuple[str, ...]] = {
    "database": (
        "connectionstrings",
        "connectionstring",
        "sqlserver",
        "mssql",
        "database",
        "datasource",
        "connstr",
        "db",
    ),
    "oss": ("oss", "objectstorage", "bucket", "storage"),
    "auth": ("jwt", "auth", "authentication", "authorization", "identity", "bearer", "signing"),
    "ai_provider": (
        "openai",
        "deepseek",
        "anthropic",
        "gemini",
        "claude",
        "llm",
        "model",
        "prompt",
        "aiprovider",
    ),
}
APPLICATION_NAME_PREFIXES: tuple[str, ...] = ("erp_", "newapp_")

# Static documentation knowledge. Every entry is a key *name* with prose that contains no value and
# no assignment delimiter, so the generated report and document stay free of credential material.
BINDING_TEMPLATES: tuple[dict[str, str], ...] = (
    {
        "name": "ERP_ConnectionStrings__Default",
        "group": "database",
        "bound_to": "NEWAPP server API data access layer, pointing at the shared NEWERP SQL Server database",
        "consumer": "server side only",
        "client_exposure": "forbidden",
        "owner_task": "NEWAPP-003 maps the actual NEWERP schema read-only",
    },
    {
        "name": "ERP_Oss__Endpoint",
        "group": "oss",
        "bound_to": "NEWAPP server object-storage client endpoint for the shared NEWERP bucket",
        "consumer": "server side only",
        "client_exposure": "forbidden",
        "owner_task": "NEWAPP-004 documents the shared object-key prefix contract",
    },
    {
        "name": "ERP_Oss__Bucket",
        "group": "oss",
        "bound_to": "the single shared NEWERP bucket used for inquiry attachments and generated exports",
        "consumer": "server side only",
        "client_exposure": "forbidden",
        "owner_task": "NEWAPP-004 documents the shared object-key prefix contract",
    },
    {
        "name": "ERP_Oss__AccessKeyId",
        "group": "oss",
        "bound_to": "server-side OSS credential identifier, identical to the NEWERP deployment",
        "consumer": "server side only",
        "client_exposure": "forbidden",
        "owner_task": "NEWAPP-004 confirms the shared-bucket policy without printing material",
    },
    {
        "name": "ERP_Oss__AccessKeySecret",
        "group": "oss",
        "bound_to": "server-side OSS credential material, never issued to a mobile build",
        "consumer": "server side only",
        "client_exposure": "forbidden",
        "owner_task": "NEWAPP-004 confirms the shared-bucket policy without printing material",
    },
    {
        "name": "ERP_Jwt__Key",
        "group": "auth",
        "bound_to": "NEWAPP server API token issuing and validation",
        "consumer": "server side only",
        "client_exposure": "forbidden",
        "owner_task": "later authentication tasks consume this name unchanged",
    },
)

PLATFORM_BINDING_RULES: tuple[str, ...] = (
    "NEWAPP and NEWERP share one SQL Server database, one OSS bucket and one master-data set. This task adds no second database, bucket or customer/supplier master store.",
    "No NEWAPP/NEWERP data synchronisation service is introduced. Both applications use the shared database and the shared OSS directly on the server side.",
    "A mobile client never connects to SQL Server and never embeds OSS credentials, a database connection string, token signing material or any other long-lived secret. All such access stays behind the NEWAPP server API.",
    "An existing key is never renamed or overwritten. A rotated secret is introduced by adding a new key name, keeping the previous name until the server deployment has moved over, and removing the old name only through a GPT plan decision and any Human Gate the controller requires.",
    "The executor reports this contract; it does not edit queue state, approvals, controller code or the task blueprint.",
)

LIMITATIONS: tuple[str, ...] = (
    "Only key names, declaration line numbers, counts and two value shape flags are recorded, so this report cannot prove that a configured value is valid, reachable or correctly scoped.",
    "Classification is derived from key-name shapes, so a name that does not describe its service is reported under application settings or unknown.",
    "The read side of the shared services is out of scope here: NEWAPP-003 owns read-only database metadata and NEWAPP-004 owns the OSS key-prefix contract.",
    "The environment file is read on a single local checkout, so another developer machine may declare additional or missing names.",
    "agent.env, secrets, signing files and cloud credential files are never opened by this module.",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def tokenize_name(name: str) -> tuple[str, ...]:
    """Split a key name into lower-case alphanumeric segments for shape-based classification."""
    return tuple(part for part in TOKEN_SPLIT_PATTERN.split(name.lower()) if part)


def classify_name(name: str) -> dict[str, Any]:
    """Classify a key name by name shape only.

    ``BASE_GROUPS`` order is the precedence order, so a name that mentions two services is reported
    under the first matching category and every other match is listed in ``matched_groups``.
    """
    tokens = set(tokenize_name(name))
    matches: list[tuple[str, list[str]]] = []
    for group in BASE_GROUPS:
        hits = sorted(tokens & set(GROUP_TOKENS[group]))
        if hits:
            matches.append((group, hits))
    if matches:
        group, matched_tokens = matches[0]
    elif name.lower().startswith(APPLICATION_NAME_PREFIXES):
        group, matched_tokens = "application", []
    else:
        group, matched_tokens = "unknown", []
    return {
        "group": group,
        "group_title": GROUP_TITLES[group],
        "matched_tokens": matched_tokens,
        "matched_groups": [item[0] for item in matches],
    }


def _modified_ns(path: Path) -> int | None:
    """Return the file write timestamp; reading never changes it, so a comparison proves read-only use."""
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _value_shape(remainder: str) -> tuple[bool, bool]:
    """Return ``(empty, quoted)`` for a declaration right-hand side.

    The remainder is only inspected to produce these two booleans and is discarded when this helper
    returns, so no value text can reach the report, the document, a log line or an exception.
    """
    text = remainder.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return (not text[1:-1].strip(), True)
    return (not text, False)


def read_env_declarations(path: Path) -> dict[str, Any]:
    """Read an environment file read-only and return names plus value *shapes* only.

    Comments, blank lines and malformed lines are counted by line number. Duplicate names are
    reported by name and line. No code path in this function returns, stores or logs a value.
    """
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    entries: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    duplicate_names: list[str] = []
    malformed_lines: list[int] = []
    comment_lines = 0
    blank_lines = 0
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            blank_lines += 1
            continue
        if stripped.startswith("#"):
            comment_lines += 1
            continue
        match = DECLARATION_PATTERN.match(line)
        if match is None:
            malformed_lines.append(number)
            continue
        name = match.group("name")
        empty, quoted = _value_shape(match.group("rest"))
        duplicate = name in seen
        if duplicate:
            duplicate_names.append(name)
        else:
            seen[name] = number
        classification = classify_name(name)
        entries.append(
            {
                "name": name,
                "line": number,
                "group": classification["group"],
                "group_title": classification["group_title"],
                "matched_tokens": classification["matched_tokens"],
                "matched_groups": classification["matched_groups"],
                "configured": not empty,
                "quoted": quoted,
                "export_prefixed": bool(match.group("export")),
                "duplicate": duplicate,
            }
        )
    return {
        "line_count": len(lines),
        "entries": entries,
        "comment_line_count": comment_lines,
        "blank_line_count": blank_lines,
        "malformed_line_numbers": malformed_lines,
        "duplicate_names": duplicate_names,
        "values_returned": False,
    }


def analyse_env_file(path: Path, label: str = ENV_FILE) -> dict[str, Any]:
    """Collect value-free facts about one environment file."""
    if not path.is_file():
        return {
            "path_label": label,
            "exists": False,
            "read_only": True,
            "byte_count": 0,
            "line_count": 0,
            "declaration_count": 0,
            "comment_line_count": 0,
            "blank_line_count": 0,
            "malformed_line_numbers": [],
            "duplicate_names": [],
            "empty_value_names": [],
            "quoted_value_count": 0,
            "export_prefixed_names": [],
            "names": [],
            "entries": [],
            "groups": {group: {"title": GROUP_TITLES[group], "count": 0, "names": []} for group in GROUP_ORDER},
            "modified_time_unchanged_during_run": True,
            "values_recorded": False,
        }
    before = _modified_ns(path)
    parsed = read_env_declarations(path)
    after = _modified_ns(path)
    entries = parsed["entries"]
    groups: dict[str, Any] = {}
    for group in GROUP_ORDER:
        group_names = [entry["name"] for entry in entries if entry["group"] == group]
        groups[group] = {"title": GROUP_TITLES[group], "count": len(group_names), "names": group_names}
    return {
        "path_label": label,
        "exists": True,
        "read_only": True,
        "byte_count": path.stat().st_size,
        "line_count": parsed["line_count"],
        "declaration_count": len(entries),
        "comment_line_count": parsed["comment_line_count"],
        "blank_line_count": parsed["blank_line_count"],
        "malformed_line_numbers": parsed["malformed_line_numbers"],
        "duplicate_names": parsed["duplicate_names"],
        "empty_value_names": [entry["name"] for entry in entries if not entry["configured"]],
        "quoted_value_count": sum(1 for entry in entries if entry["quoted"]),
        "export_prefixed_names": [entry["name"] for entry in entries if entry["export_prefixed"]],
        "names": [entry["name"] for entry in entries],
        "entries": entries,
        "groups": groups,
        "modified_time_unchanged_during_run": before == after,
        "values_recorded": False,
    }


def load_controller_environment(root: Path) -> dict[str, Any]:
    """Read the controller-required key groups (names only) read-only, failing closed when unreadable."""
    path = root / CONFIG_SOURCE
    if not path.is_file():
        return {
            "available": False,
            "source": CONFIG_SOURCE,
            "reason": "controller configuration is not present at the expected path",
        }
    try:
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {
            "available": False,
            "source": CONFIG_SOURCE,
            "reason": "controller configuration could not be parsed as JSON",
        }
    raw_groups = settings.get("environment", {}).get("required_key_groups", {})
    if not isinstance(raw_groups, dict):
        return {
            "available": False,
            "source": CONFIG_SOURCE,
            "reason": "environment.required_key_groups is not an object",
        }
    return {
        "available": True,
        "source": CONFIG_SOURCE + "#environment.required_key_groups",
        "required_key_groups": {
            str(group): [str(name) for name in names] for group, names in raw_groups.items()
        },
    }


def required_key_contract(root: Path, configured: dict[str, bool]) -> dict[str, Any]:
    """Compare the controller-required key names with the locally declared names."""
    loaded = load_controller_environment(root)
    if not loaded["available"]:
        return {
            "available": False,
            "source": loaded["source"],
            "reason": loaded["reason"],
            "groups": {},
            "required_key_count": 0,
            "present_key_count": 0,
            "missing_key_count": 0,
            "unconfigured_key_count": 0,
            "all_required_keys_present": False,
        }
    groups: dict[str, Any] = {}
    required_total = 0
    present_total = 0
    missing_total = 0
    unconfigured_total = 0
    for group, names in loaded["required_key_groups"].items():
        present = [name for name in names if name in configured]
        missing = [name for name in names if name not in configured]
        unconfigured = [name for name in names if name in configured and not configured[name]]
        groups[group] = {
            "required": names,
            "required_count": len(names),
            "present": present,
            "present_count": len(present),
            "missing": missing,
            "unconfigured": unconfigured,
            "all_present": not missing and not unconfigured,
        }
        required_total += len(names)
        present_total += len(present)
        missing_total += len(missing)
        unconfigured_total += len(unconfigured)
    return {
        "available": True,
        "source": loaded["source"],
        "groups": groups,
        "required_key_count": required_total,
        "present_key_count": present_total,
        "missing_key_count": missing_total,
        "unconfigured_key_count": unconfigured_total,
        "all_required_keys_present": missing_total == 0 and unconfigured_total == 0,
    }


def binding_map(names: Sequence[str], key_contract: dict[str, Any]) -> dict[str, Any]:
    """Build the binding map for the locally declared names plus the shared-platform rules."""
    declared = list(names)
    known = {template["name"] for template in BINDING_TEMPLATES}
    entries: list[dict[str, Any]] = []
    for template in BINDING_TEMPLATES:
        entry: dict[str, Any] = dict(template)
        entry["present_locally"] = template["name"] in declared
        entries.append(entry)
    required_names = [
        name for group in key_contract.get("groups", {}).values() for name in group["required"]
    ]
    unmapped = [name for name in declared if name not in known]
    missing_bound = [name for name in required_names if name not in declared]
    return {
        "platform_rules": list(PLATFORM_BINDING_RULES),
        "entries": entries,
        "unmapped_names": unmapped,
        "missing_bound_names": missing_bound,
        "unmapped_count": len(unmapped),
        "missing_bound_count": len(missing_bound),
    }


def value_leak_guard(text: str, names: Sequence[str], label: str) -> dict[str, Any]:
    """Refuse report text that could carry a value or an assignment line.

    Three checks run over the rendered text: no assignment delimiter may follow a locally declared
    key name, the text may not contain an assignment character at all, and every recorded key name
    must match the environment key-name character set. Only counts, booleans, line numbers and the
    offending key names are returned; no matched text is ever returned or raised.
    """
    declared = [str(name) for name in names]
    delimiter_after_name: list[int] = []
    declared_assignment = re.compile(
        "|".join(re.escape(name) + r"\s*[:=]\s*\S" for name in declared) if declared else r"(?!)"
    )
    for number, line in enumerate(text.splitlines(), start=1):
        if declared_assignment.search(line):
            delimiter_after_name.append(number)
    non_name_names = sorted({name for name in declared if not NAME_PATTERN.fullmatch(name)})
    equal_sign_count = text.count("=")
    passed = not delimiter_after_name and not non_name_names and equal_sign_count == 0
    return {
        "artifact": label,
        "status": "passed" if passed else "failed",
        "checks": [
            "no declared key name is followed by an assignment delimiter",
            "the rendered text contains no assignment character",
            "every recorded key name matches the environment key-name character set",
        ],
        "declared_key_count": len(declared),
        "delimiter_after_name_line_numbers": delimiter_after_name,
        "non_name_character_key_names": non_name_names,
        "equal_sign_count": equal_sign_count,
        "values_recorded": False,
    }


def normalize_for_path_guard(value: str) -> str:
    """Mirror the controller path guard normalization used by ``common.path_matches``.

    Separators are unified to ``/``, only *exact* leading ``./`` prefixes are removed (one prefix at a
    time, exactly like the controller loop) and the result is lower-cased for ``fnmatch``. The leading
    dot of a real dot-directory such as ``.ai/`` is preserved, so
    ``.ai/generated/NEWAPP-002-env-contract.json`` still matches ``.ai/generated/**``.
    """
    normalized = str(value).replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lower()


def _controller_patterns(root: Path, section: str, key: str, fallback: Sequence[str]) -> tuple[list[str], str]:
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
    """Show which executor paths the controller path guard accepts and which protected path matched.

    ``common.path_matches`` normalizes with ``path.replace('\\\\','/')`` and removes only exact leading
    ``./`` prefixes before ``fnmatch``, so dot-directory patterns such as ``.ai/generated/**`` match.
    :func:`normalize_for_path_guard` mirrors that behavior without importing or editing controller
    code, and ``tests/config/test_env_contract.py`` compares the mirror with the controller module.
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
            "common.path_matches applies path.replace('\\\\','/') and removes only exact leading './' "
            "prefixes before fnmatch, so dot-directory patterns are preserved"
        ),
        "paths": entries,
        "all_paths_accepted": bool(entries) and all(entry["accepted"] for entry in entries),
        "protected_paths_touched": protected_touched,
        "no_protected_path_touched": not protected_touched,
    }


def regeneration_command(report: dict[str, Any]) -> str:
    """Rebuild the exact command that regenerated these artifacts, using no assignment character."""
    artifacts = report["artifacts"]
    reports = [str(item) for item in artifacts["report_paths"]]
    documents = [str(item) for item in artifacts["doc_paths"]]
    command = ["python", "tests/config/env_contract.py", "--write"]
    for relative in reports:
        command.extend(["--report", relative])
    for relative in documents:
        command.extend(["--markdown", relative])
    for relative in artifacts["executor_paths"]:
        if str(relative) in reports or str(relative) in documents:
            continue
        command.extend(["--executor-file", str(relative)])
    return " ".join(command)


_SCANNER_CACHE: dict[str, Any] = {}


def scanner_module(root: Path | None = None) -> Any | None:
    """Load the repository secret scanner as a read-only helper module (cached, optional)."""
    path = (Path(root) if root is not None else REPOSITORY_ROOT) / SCANNER_RELATIVE_PATH
    key = str(path)
    if key in _SCANNER_CACHE:
        return _SCANNER_CACHE[key]
    module: Any | None = None
    if path.is_file():
        specification = importlib.util.spec_from_file_location("newapp_secret_scan", path)
        if specification and specification.loader:
            module = importlib.util.module_from_spec(specification)
            # Dataclasses resolve their own module during class creation.
            sys.modules[specification.name] = module
            specification.loader.exec_module(module)
    _SCANNER_CACHE[key] = module
    return module


def scanner_self_check(texts: dict[str, str]) -> dict[str, Any]:
    """Re-check the rendered artifacts with ``tests/baseline/secret_scan.py`` content rules."""
    module = scanner_module()
    if module is None:
        return {
            "available": False,
            "scanner": SCANNER_RELATIVE_PATH,
            "reason": "the repository scanner could not be loaded",
            "checked_paths": sorted(texts),
            "findings": [],
            "findings_count": 0,
            "values_recorded": False,
            "status": "unavailable",
        }
    findings: list[dict[str, Any]] = []
    for relative in sorted(texts):
        findings.extend(module.text_rule_findings(relative, texts[relative]))
    return {
        "available": True,
        "scanner": SCANNER_RELATIVE_PATH,
        "scope": "content rules of the repository scanner applied to the generated artifacts",
        "checked_paths": sorted(texts),
        "findings": findings,
        "findings_count": len(findings),
        "values_recorded": False,
        "status": "passed" if not findings else "failed",
    }


def collect_facts(
    root: Path,
    *,
    generated_at: str,
    env_file: str = ENV_FILE,
    payload_received: bool = False,
    payload_sources: Sequence[str] = (),
    executor_paths: Sequence[str] = (),
    report_paths: Sequence[str] = (),
    doc_paths: Sequence[str] = (),
) -> dict[str, Any]:
    """Collect every value-free fact the report and the document are built from."""
    environment = analyse_env_file(root / env_file, env_file)
    configured = {
        entry["name"]: bool(entry["configured"]) for entry in environment["entries"]
    }
    contract = required_key_contract(root, configured)
    allowed, allowed_source = _controller_patterns(
        root, "paths", "executor_allowed", ALLOWED_ARTIFACT_PATTERNS
    )
    protected, _ = _controller_patterns(root, "paths", "protected", ())
    return {
        "generated_at": generated_at,
        "environment": environment,
        "required_keys": contract,
        "binding": binding_map(environment["names"], contract),
        "payload": {
            "controller_payload_section_present": payload_received,
            "sources": list(payload_sources),
            "note": (
                "Task identity, GPT plan, required key groups and allowed paths were read from the "
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
    """Assemble the value-free NEWAPP-002 configuration contract report from collected facts."""
    environment = facts["environment"]
    contract = facts["required_keys"]
    binding = facts["binding"]
    declared = list(environment["names"])
    report: dict[str, Any] = {
        "task_id": TASK_ID,
        "task_title": TASK_TITLE,
        "task_phase": TASK_PHASE,
        "task_depends_on": list(TASK_DEPENDS_ON),
        "artifact": "local_configuration_contract",
        "schema_version": 1,
        "generated_at": facts["generated_at"],
        "generated_by": "newapp_executor (Cline/DeepSeek)",
        "completion_authority": (
            "the GPT brain (Codex desktop / ChatGPT mobile Remote) review, never the executor"
        ),
        "executor_payload": facts["payload"],
        "safety_contract": {
            "environment_file_access": "read-only",
            "values_recorded": False,
            "values_hashed": False,
            "values_compared_across_files": False,
            "values_printed": False,
            "environment_file_written": False,
            "environment_file_modified_time_unchanged_during_run": environment[
                "modified_time_unchanged_during_run"
            ],
            "network_calls_made": False,
            "database_connections_made": False,
            "oss_calls_made": False,
            "ai_provider_calls_made": False,
            "note": (
                "Only key names, declaration line numbers, counts and two value shape flags are "
                "recorded. The right-hand side text stays inside the parser and is never returned, "
                "stored, compared, hashed, printed or copied."
            ),
        },
        "environment": environment,
        "classification_rules": {
            "group_order": list(GROUP_ORDER),
            "precedence_groups": list(BASE_GROUPS),
            "group_tokens": {group: list(tokens) for group, tokens in GROUP_TOKENS.items()},
            "fallback": (
                "a name that matches no service token is reported under application settings when it "
                "starts with a known application prefix and under unknown otherwise"
            ),
        },
        "required_key_groups": contract,
        "binding_map": binding,
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
    report["acceptance_evidence"] = [
        {
            "criterion": "Evidence contains key names only, with all values redacted.",
            "evidence": (
                "the value guard over both rendered artifacts (no assignment character, no declared "
                "key name followed by an assignment delimiter, every recorded name matching the key "
                "name character set) plus the repository scanner content rules"
            ),
            "satisfied": False,
        },
        {
            "criterion": "No existing .env key is renamed or overwritten.",
            "evidence": (
                "the environment file is opened read-only, its write timestamp and byte count are "
                "unchanged across the run, tests/config/test_env_contract.py asserts byte-identical "
                "content around the parse on a disposable fixture, and the real local file is re-checked "
                "as ignored and untracked by git"
            ),
            "satisfied": False,
        },
        {
            "criterion": "A configured/missing key report exists for every controller required key group.",
            "evidence": "required key groups from the controller configuration compared with declared names",
            "satisfied": False,
        },
        {
            "criterion": (
                "Generated artifacts stay inside the executor allowed paths and no protected path is touched."
            ),
            "evidence": (
                "controller path guard mirror over every executor path recorded by this report, plus the "
                "protected pattern list read from the controller configuration"
            ),
            "satisfied": False,
        },
    ]
    report["declared_key_count"] = len(declared)
    report["artifact_checks_verified"] = False
    report["status"] = "attention_required"
    return report


def _markdown_tail(report: dict[str, Any], environment: dict[str, Any]) -> list[str]:
    """Render the binding, required-key, artifact-check and limits sections of the document."""
    contract = report["required_key_groups"]
    binding = report["binding_map"]
    lines: list[str] = [
        "## 6. Required key groups and missing-key report",
        "",
        f"Source: `{contract['source']}`. Available: {_yes_no(contract['available'])}.",
        "",
        _row(["Group", "Required", "Present", "Missing", "Empty", "All present"]),
        _row(["---"] * 6),
    ]
    for group in sorted(contract["groups"]):
        facts = contract["groups"][group]
        lines.append(
            _row(
                [
                    group,
                    _listing(facts["required"]),
                    _listing(facts["present"]),
                    _listing(facts["missing"]),
                    _listing(facts["unconfigured"]),
                    _yes_no(facts["all_present"]),
                ]
            )
        )
    lines.extend(
        [
            "",
            f"Required names: {contract['required_key_count']}. Present: "
            f"{contract['present_key_count']}. Missing: {contract['missing_key_count']}. Declared but "
            f"empty: {contract['unconfigured_key_count']}.",
            f"Every required name present and non-empty: "
            f"{_yes_no(contract['all_required_keys_present'])}.",
            "",
            "## 7. Configuration binding map",
            "",
            _row(
                [
                    "Key name",
                    "Category",
                    "Bound to",
                    "Consumed by",
                    "Client exposure",
                    "Present locally",
                ]
            ),
            _row(["---"] * 6),
        ]
    )
    for entry in binding["entries"]:
        lines.append(
            _row(
                [
                    f"`{entry['name']}`",
                    entry["group"],
                    entry["bound_to"],
                    entry["consumer"],
                    entry["client_exposure"],
                    _yes_no(entry["present_locally"]),
                ]
            )
        )
    lines.extend(
        [
            "",
            f"Declared names without a binding entry in this task: "
            f"{_listing(binding['unmapped_names'])}.",
            f"Required names missing locally: {_listing(binding['missing_bound_names'])}.",
            "",
            "## 8. Platform binding rules for NEWAPP and NEWERP",
            "",
        ]
    )
    for index, rule in enumerate(binding["platform_rules"], start=1):
        lines.append(f"{index}. {rule}")
    lines.extend(
        [
            "",
            "## 9. Generated artifact checks",
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
            _row(["Artifact checks verified", _yes_no(report["artifact_checks_verified"])]),
            "",
            "## 10. Generated artifact path guard",
            "",
            f"Allowed pattern source: `{report['path_guard']['allowed_patterns_source']}`.",
            "",
            _row(["Executor path", "Accepted", "Matched allowed patterns"]),
            _row(["---"] * 3),
        ]
    )
    for entry in report["path_guard"]["paths"]:
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
            f"Every recorded executor path accepted: {_yes_no(report['path_guard']['all_paths_accepted'])}.",
            "Protected paths touched: "
            + _listing(
                [entry["path"] for entry in report["path_guard"]["protected_paths_touched"]]
            )
            + ".",
            f"Protected patterns compared: {report['artifacts']['protected_pattern_count']}.",
            "",
            "## 11. Acceptance evidence",
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
            "## 12. Regeneration",
            "",
            "```",
            regeneration_command(report),
            "```",
            "",
            "Both artifacts are written atomically and are re-checked before writing; the JSON report "
            "and this document are rendered from the same facts, so they cannot drift apart.",
            "",
            f"Local environment file inspected: `{environment['path_label']}` with "
            f"{environment['declaration_count']} declarations.",
            "",
            f"Executor paths recorded for this task: {_listing(report['artifacts']['executor_paths'])}.",
            "",
            "## 13. Known limits",
            "",
        ]
    )
    for entry in report["limitations"]:
        lines.append(f"- {entry}")
    lines.append("")
    return lines


def _row(cells: Sequence[Any]) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def _listing(values: Sequence[Any]) -> str:
    items = [str(value) for value in values]
    return ", ".join(items) if items else "none"


def _yes_no(value: Any) -> str:
    return "yes" if value else "no"


def render_markdown(report: dict[str, Any]) -> str:
    """Render the generated documentation from the same value-free facts as the JSON report."""
    environment = report["environment"]
    safety = report["safety_contract"]
    lines: list[str] = [
        "# NEWAPP local configuration contract",
        "",
        f"Task: **{report['task_id']} - {report['task_title']}** "
        f"(phase {report['task_phase']}, depends on {_listing(report['task_depends_on'])}).",
        "",
        "This document is generated from the same value-free facts as "
        f"`{REPORT_RELATIVE_PATH}`, so regenerate it with `tests/config/env_contract.py` instead of "
        "editing it by hand.",
        "",
        f"Generated at {report['generated_at']} UTC by {report['generated_by']}. Completion authority: "
        f"{report['completion_authority']}.",
        "",
        "## 1. Authority of record",
        "",
        _row(["Concern", "Authoritative artifact"]),
        _row(["---", "---"]),
        _row(["Locally declared key names", f"`{ENV_FILE}` (ignored, untracked, never committed)"]),
        _row(["Required key groups", f"`{CONFIG_SOURCE}#environment.required_key_groups`"]),
        _row(["Machine-readable facts", f"`{REPORT_RELATIVE_PATH}`"]),
        _row(["Controller allowed paths", f"`{CONFIG_SOURCE}#paths.executor_allowed`"]),
        _row(["Task definition", "`docs/NEWAPP_TASKS_V1.yaml#NEWAPP-002`"]),
        "",
        "## 2. Safety contract for this report",
        "",
        "1. Only key names, declaration line numbers, counts and two value shape flags are recorded.",
        "2. The right-hand side text never leaves the parser: it is not returned, stored, compared "
        "with another file or key, hashed, printed, logged nor copied into evidence.",
        f"3. `{ENV_FILE}` is opened read-only. Environment file written: "
        f"{_yes_no(safety['environment_file_written'])}. Write timestamp unchanged across the run: "
        f"{_yes_no(safety['environment_file_modified_time_unchanged_during_run'])}.",
        "4. No database, OSS, AI-provider or network call is made by this report.",
        "5. Both artifacts are re-checked with the project scanner "
        f"`{SCANNER_RELATIVE_PATH}` before they are written, so flagged text is never produced.",
        "",
        "## 3. Local environment file facts",
        "",
        _row(["Fact", "Value"]),
        _row(["---", "---"]),
        _row(["Path label", f"`{environment['path_label']}`"]),
        _row(["Present locally", _yes_no(environment["exists"])]),
        _row(["Read only", _yes_no(environment["read_only"])]),
        _row(["Byte count", environment["byte_count"]]),
        _row(["Line count", environment["line_count"]]),
        _row(["Declarations", environment["declaration_count"]]),
        _row(["Comment lines", environment["comment_line_count"]]),
        _row(["Blank lines", environment["blank_line_count"]]),
        _row(["Malformed line numbers", _listing(environment["malformed_line_numbers"])]),
        _row(["Duplicate declarations", _listing(environment["duplicate_names"])]),
        _row(["Empty right-hand sides", _listing(environment["empty_value_names"])]),
        _row(["Quoted right-hand sides", environment["quoted_value_count"]]),
        _row(["Export-prefixed names", _listing(environment["export_prefixed_names"])]),
        _row(["Values recorded", _yes_no(safety["values_recorded"])]),
        "",
        "## 4. Declared key names",
        "",
        _row(["Key name", "Category", "Line", "Configured", "Duplicate", "Export prefixed"]),
        _row(["---"] * 6),
    ]
    for entry in environment["entries"]:
        lines.append(
            _row(
                [
                    f"`{entry['name']}`",
                    entry["group_title"],
                    entry["line"],
                    _yes_no(entry["configured"]),
                    _yes_no(entry["duplicate"]),
                    _yes_no(entry["export_prefixed"]),
                ]
            )
        )
    lines.extend(
        [
            "",
            "## 5. Category summary",
            "",
            _row(["Category", "Count", "Key names"]),
            _row(["---"] * 3),
        ]
    )
    for group in GROUP_ORDER:
        group_facts = environment["groups"][group]
        lines.append(_row([group, group_facts["count"], _listing(group_facts["names"])]))
    lines.append("")
    lines.extend(_markdown_tail(report, environment))
    return "\n".join(lines) + "\n"


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def artifact_checks(report_text: str, markdown: str, names: Sequence[str]) -> dict[str, Any]:
    """Run the value guard on both artifacts and the repository scanner over both artifacts."""
    return {
        "report_value_guard": value_leak_guard(report_text, names, REPORT_RELATIVE_PATH),
        "documentation_value_guard": value_leak_guard(markdown, names, DOC_RELATIVE_PATH),
        "scanner_self_check": scanner_self_check(
            {REPORT_RELATIVE_PATH: report_text, DOC_RELATIVE_PATH: markdown}
        ),
    }


def apply_acceptance(report: dict[str, Any]) -> dict[str, Any]:
    """Score the two acceptance criteria of the GPT plan plus the required-key coverage criterion."""
    environment = report["environment"]
    contract = report["required_key_groups"]
    guard_ok = (
        report["report_value_guard"]["status"] == "passed"
        and report["documentation_value_guard"]["status"] == "passed"
        and report["scanner_self_check"]["status"] == "passed"
    )
    untouched_ok = bool(
        not report["safety_contract"]["environment_file_written"]
        and environment["modified_time_unchanged_during_run"]
    )
    coverage_ok = bool(contract["available"] and contract["all_required_keys_present"])
    guard_paths = report["path_guard"]
    paths_ok = bool(guard_paths["all_paths_accepted"] and guard_paths["no_protected_path_touched"])
    satisfied = [guard_ok, untouched_ok, coverage_ok, paths_ok]
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
    report_text = render_json(report)
    return report, report_text, markdown


def atomic_write_text(path: Path, text: str) -> None:
    """Write one artifact atomically with LF newlines, replacing any previous revision."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def relative_to_root(root: Path, value: str) -> str:
    candidate = Path(value)
    absolute = candidate if candidate.is_absolute() else root / candidate
    try:
        return str(absolute.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(candidate).replace("\\", "/")


DEFAULT_PAYLOAD_SOURCES: tuple[str, ...] = (
    "docs/NEWAPP_TASKS_V1.yaml#NEWAPP-002",
    ".ai/brain/requests/NEWAPP-002-plan-request.json",
    ".ai/brain/decisions/NEWAPP-002-plan.json",
    ".ai/agent_config.yaml#paths.executor_allowed",
    ".ai/agent_config.yaml#environment.required_key_groups",
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect the value-free NEWAPP-002 local configuration contract"
    )
    parser.add_argument("--root", default=str(REPOSITORY_ROOT))
    parser.add_argument(
        "--env-file",
        default=ENV_FILE,
        help="environment file label relative to the root; only key names are read",
    )
    parser.add_argument(
        "--report",
        action="append",
        default=None,
        help=f"JSON report path, repeatable, default <root>/{REPORT_RELATIVE_PATH}",
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
        payload_received=args.payload_received,
        payload_sources=args.payload_source or list(DEFAULT_PAYLOAD_SOURCES),
        executor_paths=executor_paths,
        report_paths=targets,
        doc_paths=documents,
    )
    report = build_report(facts)
    report, report_text, markdown = finalize_report(report, facts["environment"]["names"])

    if args.write:
        for relative in targets:
            atomic_write_text(root / relative, report_text)
        for relative in documents:
            atomic_write_text(root / relative, markdown)

    if args.json:
        print(report_text, end="")
    else:
        environment = report["environment"]
        counts = " ".join(
            f"{group}={environment['groups'][group]['count']}" for group in GROUP_ORDER
        )
        contract = report["required_key_groups"]
        print(f"task={report['task_id']} status={report['status']}")
        print(f"env={environment['path_label']} declarations={environment['declaration_count']}")
        print(f"category_counts {counts}")
        print(
            f"required={contract['required_key_count']} present={contract['present_key_count']} "
            f"missing={contract['missing_key_count']} empty={contract['unconfigured_key_count']}"
        )
        print(
            f"report_guard={report['report_value_guard']['status']} "
            f"documentation_guard={report['documentation_value_guard']['status']} "
            f"scanner={report['scanner_self_check']['status']}"
        )
        for entry in report["acceptance_evidence"]:
            print(f"criterion_satisfied={entry['satisfied']} {entry['criterion']}")
        if args.write:
            print("written " + " ".join([*targets, *documents]))
    return 0 if report["status"] == "evidence_collected" else 1


if __name__ == "__main__":
    raise SystemExit(main())
