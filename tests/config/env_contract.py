"""Value-free ``.env`` configuration contract for NEWAPP-002.

Task: **NEWAPP-002 — Inspect existing ``.env`` configuration contract safely** (phase P0). The GPT
plan requires the local configuration contract to be documented from key **names** and
configured/missing booleans only, plus a binding map and missing-key report, without touching the
environment file.

Generate both artifacts from the repository root::

    .venv\\Scripts\\python.exe tests\\config\\env_contract.py --write \\
        --report .ai/generated/NEWAPP-002-env-contract.json \\
        --markdown docs/CONFIGURATION_CONTRACT.md \\
        --executor-file docs/CONFIGURATION_CONTRACT.md \\
        --executor-file tests/config/__init__.py \\
        --executor-file tests/config/env_contract.py \\
        --executor-file tests/config/test_env_contract.py

Safety contract
---------------
* ``.env`` is opened read-only. A value is inspected in memory only to decide whether a name is
  configured or has an empty value; the value itself is then discarded.
* No value, quote, prefix, suffix, length or hash of a value is recorded, printed, logged or
  compared, and the environment file is never renamed, rewritten, staged or copied.
* A finding contains a rule id, an artifact label and a line number - never matched text.
* :func:`find_value_free_violations` re-checks both rendered artifacts with the repository secret
  rules before anything is written; a violation stops the write (fail closed).
* Collection is read-only: only ``--write`` adds the report and the document.

Documented limits
-----------------
* Only names, group ids, booleans and counts are recorded; high-entropy values are out of scope
  because no value is ever recorded.
* Missing or empty names are *reported*, never written into ``.env``; repairs stay a GPT/human
  decision.
* A name that matches no group rule is listed by name only and is never renamed automatically.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

CONFIG_DIR = Path(__file__).resolve().parent
if str(CONFIG_DIR.parent / "baseline") not in sys.path:
    sys.path.insert(0, str(CONFIG_DIR.parent / "baseline"))

from repository_baseline import path_guard_compatibility  # noqa: E402
from secret_scan import ASSIGNMENT_PATTERN, MIN_ASSIGNMENT_LENGTH, is_placeholder_value  # noqa: E402

TASK_ID = "NEWAPP-002"
TASK_TITLE = "Inspect existing .env configuration contract safely"
TASK_PHASE = "P0"
ENV_FILE = ".env"
POLICY_RELATIVE_PATH = ".ai/agent_config.yaml"
REPORT_RELATIVE_PATH = ".ai/generated/NEWAPP-002-env-contract.json"
DOCUMENT_RELATIVE_PATH = "docs/CONFIGURATION_CONTRACT.md"
GENERATED_BY = "newapp_executor (Cline/DeepSeek)"
COMPLETION_AUTHORITY = "GPT brain final review; this artifact is evidence only"

ASSIGNMENT_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")

GROUP_ORDER: tuple[str, ...] = ("database", "oss", "auth", "ai_provider", "application")

GROUP_LABELS: dict[str, str] = {
    "database": "Shared SQL Server database",
    "oss": "Shared OSS object storage",
    "auth": "Authentication and token signing",
    "ai_provider": "AI provider",
    "application": "Application settings (not credentials)",
}

GROUP_CONSUMERS: dict[str, str] = {
    "database": "NEWAPP server API / worker only",
    "oss": "NEWAPP server API / worker only",
    "auth": "NEWAPP server API / worker only",
    "ai_provider": "NEWAPP server API / AI worker only",
    "application": "NEWAPP server configuration",
}

GROUP_ALIASES: dict[str, str] = {
    "database": "database",
    "db": "database",
    "sqlserver": "database",
    "oss": "oss",
    "object_storage": "oss",
    "storage": "oss",
    "auth": "auth",
    "authentication": "auth",
    "ai": "ai_provider",
    "ai_provider": "ai_provider",
    "app": "application",
    "application": "application",
    "settings": "application",
}

TOKEN_SPLIT = re.compile(r"__|_")
TOKEN_RULES: tuple[tuple[str, frozenset[str]], ...] = (
    (
        "database",
        frozenset({"connectionstrings", "connectionstring", "database", "db", "sqlserver", "mssql", "datasource"}),
    ),
    (
        "oss",
        frozenset({"oss", "storage", "bucket", "accesskey", "accesskeyid", "accesskeysecret", "endpoint", "region"}),
    ),
    (
        "auth",
        frozenset({"jwt", "auth", "authentication", "authorization", "signing", "issuer", "audience", "login", "identity"}),
    ),
    (
        "ai_provider",
        frozenset({"ai", "llm", "openai", "deepseek", "claude", "anthropic", "gemini", "qwen", "moonshot", "model", "ocr", "vision"}),
    ),
    (
        "application",
        frozenset({"app", "application", "setting", "settings", "log", "logging", "cors", "url", "baseurl", "timeout", "limit", "feature", "environment", "env", "port", "host"}),
    ),
)

APP_PREFIX = "ERP_"

BINDING_CONVENTION = (
    "Observed ASP.NET Core environment-variable convention: the application prefix 'ERP_' is "
    "removed and the '__' hierarchy separator becomes ':'."
)

BINDING_STATEMENTS: tuple[str, ...] = (
    "NEWAPP and NEWERP share one SQL Server database, one OSS and one master-data set; NEWAPP adds no second customer/supplier master-data store.",
    "No NEWAPP/NEWERP synchronization service is introduced by this task or by the configuration contract.",
    "Database and OSS access stays behind the NEWAPP server API/worker: no mobile client (Flutter or ArkTS) holds those names' values and no mobile client connects directly to SQL Server.",
    "Existing key names are neither renamed nor overwritten by automation; where a name differs from a code default, a ConfigMapping layer is added instead of renaming a user secret.",
)

LIMITATIONS: tuple[str, ...] = (
    "Only key names, group ids, booleans and counts are recorded; a value is read in memory solely to decide between configured and empty and is then discarded.",
    "No value, quote, prefix, suffix, length or hash of a value is recorded, printed, logged, stored in an exception message or compared.",
    "The contract describes the local environment file observed at generation time; a name added later appears only after the next run.",
    "A name that matches no group rule is listed by name only and is not renamed, reclassified or written back automatically.",
    "This document and the JSON report are evidence only; GPT review decides completion.",
)

VALUE_FREE_RULES: tuple[tuple[str, str], ...] = (
    ("key_name_assignment", "A line assigns a value to a real configuration key name"),
    ("keyword_assignment", "A credential keyword is assigned a non-placeholder value"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_git(root: Path, arguments: Sequence[str]) -> tuple[int, str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    return result.returncode, (result.stdout or "").strip()


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def atomic_write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def relative_target(root: Path, candidate: str) -> tuple[str, Path]:
    item = Path(candidate)
    absolute = item if item.is_absolute() else root / item
    try:
        relative = str(absolute.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        relative = str(candidate).replace("\\", "/")
    return relative, absolute


def load_policy_document(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8-sig")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - PyYAML is an environment requirement
            raise RuntimeError("PyYAML is required to read the controller configuration") from exc
        value = yaml.safe_load(raw)
    if not isinstance(value, dict):
        raise ValueError("expected a mapping in the controller configuration")
    return value


def policy_facts(root: Path, policy_relative: str = POLICY_RELATIVE_PATH) -> dict[str, Any]:
    """Read the expected key groups from the controller configuration (read-only)."""
    path = root / policy_relative
    if not path.is_file():
        return {"available": False, "reason": "the controller configuration file is absent", "expected_groups": {}}
    try:
        settings = load_policy_document(path)
    except Exception:
        return {"available": False, "reason": "the controller configuration could not be parsed", "expected_groups": {}}
    environment = settings.get("environment") if isinstance(settings.get("environment"), dict) else {}
    raw_groups = environment.get("required_key_groups") if isinstance(environment.get("required_key_groups"), dict) else {}
    expected: dict[str, list[str]] = {}
    unknown_group_ids: list[str] = []
    for raw_id, raw_names in raw_groups.items():
        canonical = GROUP_ALIASES.get(str(raw_id).strip().lower())
        if canonical is None:
            unknown_group_ids.append(str(raw_id))
            continue
        names = [str(item) for item in raw_names] if isinstance(raw_names, list) else []
        bucket = expected.setdefault(canonical, [])
        bucket.extend(name for name in names if name not in bucket)
    paths = settings.get("paths") if isinstance(settings.get("paths"), dict) else {}
    allowed = paths.get("executor_allowed") if isinstance(paths.get("executor_allowed"), list) else []
    return {
        "available": True,
        "path_label": policy_relative,
        "section": "environment.required_key_groups",
        "expected_groups": {group: expected[group] for group in GROUP_ORDER if expected.get(group)},
        "unknown_group_ids": sorted(unknown_group_ids),
        "env_file_label": str(environment.get("file", ENV_FILE)),
        "executor_allowed_paths": [str(item) for item in allowed],
    }


def environment_file_facts(root: Path, env_relative: str = ENV_FILE) -> dict[str, Any]:
    """Describe the environment file by path label and Git status only."""
    ignored_code, _ = run_git(root, ["check-ignore", "-q", env_relative])
    tracked_code, _ = run_git(root, ["ls-files", "--error-unmatch", env_relative])
    return {
        "path_label": env_relative,
        "exists_locally": (root / env_relative).is_file(),
        "ignored_by_git": ignored_code == 0,
        "tracked_by_git": tracked_code == 0,
    }


def parse_env_text(text: str) -> dict[str, Any]:
    """Collect key names and presence booleans; a value never leaves this function."""
    names: list[str] = []
    empty_names: list[str] = []
    malformed = 0
    comments = 0
    blanks = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            blanks += 1
            continue
        if stripped.startswith("#"):
            comments += 1
            continue
        match = ASSIGNMENT_LINE.match(line)
        if match is None:
            malformed += 1
            continue
        name = match.group(1)
        names.append(name)
        if not _value_is_present(match.group(2)):
            empty_names.append(name)
    unique = sorted(set(names))
    configured = [name for name in unique if name not in set(empty_names)]
    return {
        "key_names": unique,
        "key_count": len(names),
        "unique_key_count": len(unique),
        "duplicate_key_names": sorted({name for name in names if names.count(name) > 1}),
        "configured_key_names": configured,
        "empty_value_key_names": sorted(set(empty_names)),
        "malformed_line_count": malformed,
        "comment_line_count": comments,
        "blank_line_count": blanks,
    }


def _value_is_present(raw_value: str) -> bool:
    """Return a presence boolean for a raw assignment value; the value itself is discarded."""
    stripped = raw_value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        stripped = stripped[1:-1]
    return bool(stripped.strip())




def empty_parsing() -> dict[str, Any]:
    return {
        "key_names": [],
        "key_count": 0,
        "unique_key_count": 0,
        "duplicate_key_names": [],
        "configured_key_names": [],
        "empty_value_key_names": [],
        "malformed_line_count": 0,
        "comment_line_count": 0,
        "blank_line_count": 0,
    }


def read_environment_facts(root: Path, env_relative: str = ENV_FILE) -> dict[str, Any]:
    """Read key names from the environment file behind a write-detection guard.

    The file is opened read-only and only names plus presence booleans leave this function. The guard
    records metadata equality and Git-status equality as booleans; no size, timestamp, hash or value
    is stored, and nothing is ever written back.
    """
    path = root / env_relative
    if not path.is_file():
        return {
            "present": False,
            "read_only_collection": True,
            "file_unchanged_after_read": True,
            "git_status_unchanged": True,
            "values_recorded": False,
            "values_hashed": False,
            "assignment_lines_reproduced": False,
            "parsing": empty_parsing(),
        }
    before_status, _ = run_git(root, ["status", "--porcelain=v1", "--", env_relative])
    before_stat = path.stat()
    parsing = parse_env_text(path.read_text(encoding="utf-8-sig", errors="replace"))
    after_stat = path.stat()
    after_status, _ = run_git(root, ["status", "--porcelain=v1", "--", env_relative])
    return {
        "present": True,
        "read_only_collection": True,
        "file_unchanged_after_read": before_stat.st_size == after_stat.st_size
        and before_stat.st_mtime_ns == after_stat.st_mtime_ns,
        "git_status_unchanged": before_status == after_status,
        "values_recorded": False,
        "values_hashed": False,
        "assignment_lines_reproduced": False,
        "parsing": parsing,
    }


def expected_group_for(name: str, expected_groups: dict[str, list[str]]) -> str | None:
    for group in GROUP_ORDER:
        if name in expected_groups.get(group, []):
            return group
    return None


def classify_key_name(name: str, expected_groups: dict[str, list[str]] | None = None) -> str | None:
    """Return the group id for a name, or ``None`` when only the name can be reported."""
    declared = expected_group_for(name, expected_groups or {})
    if declared is not None:
        return declared
    body = name[len(APP_PREFIX):] if name.startswith(APP_PREFIX) else name
    tokens = {token.lower() for token in TOKEN_SPLIT.split(body) if token}
    for group, keywords in TOKEN_RULES:
        if tokens & keywords:
            return group
    return None


def configuration_key_for(name: str, prefix: str = APP_PREFIX) -> str:
    """Derive the ASP.NET Core configuration key from a name, without touching the environment file."""
    body = name[len(prefix):] if prefix and name.startswith(prefix) else name
    return ":".join(part for part in body.split("__") if part)



def build_groups(key_facts: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Group the recorded names and compute the missing-key report."""
    expected_groups = policy.get("expected_groups", {}) if policy.get("available") else {}
    names = list(key_facts.get("key_names", []))
    configured = set(key_facts.get("configured_key_names", []))
    empty = set(key_facts.get("empty_value_key_names", []))
    members: dict[str, list[str]] = {}
    unclassified: list[str] = []
    for name in names:
        group = classify_key_name(name, expected_groups)
        if group is None:
            unclassified.append(name)
        else:
            members.setdefault(group, []).append(name)
    groups: list[dict[str, Any]] = []
    for group in GROUP_ORDER:
        expected = list(expected_groups.get(group, []))
        present = sorted(members.get(group, []))
        groups.append(
            {
                "id": group,
                "label": GROUP_LABELS[group],
                "consumer": GROUP_CONSUMERS[group],
                "from_policy": group in expected_groups,
                "expected_names": expected,
                "present_names": present,
                "configured_names": [name for name in present if name in configured],
                "empty_value_names": [name for name in present if name in empty],
                "missing_names": [name for name in expected if name not in set(present)],
                "expected_count": len(expected),
                "present_count": len(present),
            }
        )
    return {
        "groups": groups,
        "unclassified_key_names": sorted(unclassified),
        "missing_key_names": sorted({name for group in groups for name in group["missing_names"]}),
    }


def build_binding_map(key_facts: dict[str, Any], classification: dict[str, Any]) -> list[dict[str, Any]]:
    """Map every recorded name to its group, configuration key and consumer."""
    group_of = {name: group["id"] for group in classification["groups"] for name in group["present_names"]}
    entries: list[dict[str, Any]] = []
    for name in key_facts.get("key_names", []):
        group = group_of.get(name)
        entries.append(
            {
                "env_name": name,
                "group": group if group else "unclassified",
                "configuration_key": configuration_key_for(name),
                "consumer": GROUP_CONSUMERS.get(group or "", "review required before this name is used"),
                "value_fields_recorded": False,
            }
        )
    return entries


def find_value_free_violations(
    text: str,
    key_names: Sequence[str] = (),
    artifact_label: str = "artifact",
) -> list[dict[str, Any]]:
    """Re-check a rendered artifact; a finding carries a rule id, a label and a line number only."""
    patterns = [re.compile(r"^\s*(?:export\s+)?" + re.escape(name) + r"\s*=") for name in key_names]
    violations: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if any(pattern.match(line) for pattern in patterns):
            violations.append({"rule": "key_name_assignment", "artifact": artifact_label, "line": number})
        match = ASSIGNMENT_PATTERN.search(line)
        if match is None:
            continue
        value = next((group for group in (match.group(index) for index in (1, 2, 3)) if group), None)
        if value is None or len(value.strip()) < MIN_ASSIGNMENT_LENGTH or is_placeholder_value(value):
            continue
        violations.append({"rule": "keyword_assignment", "artifact": artifact_label, "line": number})
    return violations


def git_facts(root: Path) -> dict[str, Any]:
    inside_code, _ = run_git(root, ["rev-parse", "--is-inside-work-tree"])
    head_code, head_commit = run_git(root, ["rev-parse", "--verify", "HEAD"])
    branch_code, branch = run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    return {
        "repository_present": inside_code == 0,
        "head_commit": head_commit.splitlines()[0] if head_code == 0 and head_commit else None,
        "branch": branch if branch_code == 0 else None,
    }


def controller_facts(root: Path, task_id: str = TASK_ID) -> dict[str, Any]:
    path = root / ".ai" / "project_state.json"
    if not path.is_file():
        return {"available": False}
    try:
        state = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {"available": False}
    entry = state.get("task_statuses", {}).get(task_id, {})
    return {
        "available": True,
        "phase": state.get("phase"),
        "run_id": entry.get("run_id") or state.get("last_run_id"),
        "branch": entry.get("branch"),
        "task_status": entry.get("status"),
    }



def build_report(facts: dict[str, Any]) -> dict[str, Any]:
    """Assemble the value-free NEWAPP-002 configuration-contract report."""
    env_file = facts["environment_file"]
    guard = facts["read_only_guard"]
    parsing = guard["parsing"]
    policy = facts["policy"]
    classification = facts["classification"]
    binding_map = facts["binding_map"]
    guard_view = facts["path_guard_compatibility"]
    names = list(parsing["key_names"])

    env_ok = bool(env_file["exists_locally"] and env_file["ignored_by_git"] and not env_file["tracked_by_git"])
    guard_ok = bool(
        guard["read_only_collection"] and guard["file_unchanged_after_read"] and guard["git_status_unchanged"]
    )
    parsing_ok = parsing["malformed_line_count"] == 0
    unresolved: list[dict[str, Any]] = []
    if guard_view["paths"] and not guard_view["all_paths_accepted"]:
        unresolved.append(
            {
                "issue": "the controller path guard rejects executor path(s)",
                "paths": [entry["path"] for entry in guard_view["paths"] if not entry["accepted"]],
                "reason": (
                    "the paths above match no pattern in .ai/agent_config.yaml#paths.executor_allowed after the "
                    "controller normalization (backslashes become '/', only exact leading './' prefixes are removed)"
                ),
                "impact": "the evidence manifest becomes insufficient for these artifacts",
                "executor_action": "the executor writes no path outside the GPT-approved allowed list",
                "owner": "controller/GPT plan owner (protected configuration); the executor does not edit controller code",
            }
        )
    report: dict[str, Any] = {
        "task_id": TASK_ID,
        "task_title": TASK_TITLE,
        "task_phase": TASK_PHASE,
        "artifact": "env_configuration_contract",
        "generated_at": facts["generated_at"],
        "generated_by": GENERATED_BY,
        "completion_authority": COMPLETION_AUTHORITY,
        "executor_payload_received": facts["executor_payload_received"],
        "payload_reconstruction": facts["payload_reconstruction"],
        "controller": facts["controller"],
        "git": facts["git"],
        "source_files": {
            "environment_file_label": env_file["path_label"],
            "policy_path": policy.get("path_label", POLICY_RELATIVE_PATH),
            "policy_section": policy.get("section", "environment.required_key_groups"),
            "policy_available": bool(policy.get("available")),
        },
        "environment_file": env_file,
        "read_only_guard": {
            "read_only_collection": guard["read_only_collection"],
            "file_unchanged_after_read": guard["file_unchanged_after_read"],
            "git_status_unchanged": guard["git_status_unchanged"],
            "values_recorded": guard["values_recorded"],
            "values_hashed": guard["values_hashed"],
            "assignment_lines_reproduced": guard["assignment_lines_reproduced"],
        },
        "key_inventory": {
            "key_count": parsing["key_count"],
            "unique_key_count": parsing["unique_key_count"],
            "configured_key_count": len(parsing["configured_key_names"]),
            "empty_value_key_count": len(parsing["empty_value_key_names"]),
            "malformed_line_count": parsing["malformed_line_count"],
            "comment_line_count": parsing["comment_line_count"],
            "blank_line_count": parsing["blank_line_count"],
            "key_names": names,
            "duplicate_key_names": parsing["duplicate_key_names"],
            "assignment_syntax": "single-line NAME with an optional export prefix, a separator and a value",
        },
        "groups": classification["groups"],
        "binding_map": binding_map,
        "unclassified_key_names": classification["unclassified_key_names"],
        "missing_key_names": classification["missing_key_names"],
        "empty_value_key_names": parsing["empty_value_key_names"],
        "policy_group_ids_unknown_to_this_tool": policy.get("unknown_group_ids", []),
        "binding_contract": {
            "convention": BINDING_CONVENTION,
            "statements": list(BINDING_STATEMENTS),
            "shared_database_with_newerp": True,
            "shared_oss_with_newerp": True,
            "second_master_data_store_created": False,
            "synchronization_service_added": False,
            "mobile_client_holds_platform_values": False,
            "mobile_client_direct_sql_server_connection": False,
            "key_names_renamed_or_overwritten": False,
            "sources": [
                "docs/NEWAPP_TASKS_V1.yaml#relationship_to_newerp",
                "docs/NEWAPP_TASKS_V1.yaml#environment.rules",
                ".ai/agent_config.yaml#project.shares_database_and_oss_with",
                ".ai/agent_config.yaml#human_gate.forbidden_even_with_approval",
            ],
            "note": (
                "Fixed contract statements for the shared NEWERP/NEWAPP platform; this task changes no code, "
                "database, OSS or NEWERP resource."
            ),
        },
        "artifacts": {
            "reports": list(facts.get("report_paths", [])),
            "documents": list(facts.get("document_paths", [])),
            "executor_paths": list(facts.get("executor_paths", [])),
        },
        "path_guard_compatibility": guard_view,
        "acceptance_evidence": [
            {
                "criterion": "Evidence contains key names only, with all values redacted.",
                "evidence": "self-check of the rendered JSON report and markdown document against the repository secret rules",
                "satisfied": False,
            },
            {
                "criterion": "No existing .env key is renamed or overwritten.",
                "evidence": "the environment file was opened read-only; Git status and file metadata stayed unchanged",
                "satisfied": guard_ok,
            },
            {
                "criterion": ".env remains present locally and untracked.",
                "evidence": "git check-ignore and git ls-files --error-unmatch evaluated on the path label only",
                "satisfied": env_ok,
            },
            {
                "criterion": "Every parsed key name is grouped or listed by name only.",
                "evidence": "groups, unclassified_key_names and the malformed-line count of the environment file",
                "satisfied": parsing_ok,
            },
        ],
        "value_free_check": {
            "status": "self_check_pending",
            "rules": [rule for rule, _ in VALUE_FREE_RULES],
            "violations_count": 0,
            "violations": [],
        },
        "reproduce": {
            "env_contract": "python tests/config/env_contract.py --write",
            "unit_tests": "python -m unittest discover -s tests -p \"test_*.py\"",
            "secret_scan": "python tests/baseline/secret_scan.py --json",
        },
        "limitations": list(LIMITATIONS),
        "unresolved_issues": unresolved,
        "secret_values_included": False,
    }
    report["status"] = (
        "evidence_collected" if all(item["satisfied"] for item in report["acceptance_evidence"]) else "attention_required"
    )
    return report



def _cell_names(names: Sequence[str]) -> str:
    return ", ".join(f"`{name}`" for name in names) if names else "none"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(cells) + " |" for cells in rows)
    return lines


def _yes_no(value: Any) -> str:
    return "yes" if value else "no"


def render_markdown(report: dict[str, Any]) -> str:
    """Render the human-readable contract; every key name is wrapped in backticks."""
    inventory = report["key_inventory"]
    guard = report["read_only_guard"]
    env_file = report["environment_file"]
    contract = report["binding_contract"]
    check = report["value_free_check"]
    lines: list[str] = []
    add = lines.append
    add("# NEWAPP configuration contract (value-free environment inspection)")
    add("")
    add(f"Task **{report['task_id']} — {report['task_title']}**, phase {report['task_phase']}, depends on `NEWAPP-001`.")
    add("")
    add("- Planning and final acceptance authority: GPT brain (Codex desktop / ChatGPT mobile Remote).")
    add("- Generator: `tests/config/env_contract.py --write`, run by newapp_executor (Cline/DeepSeek).")
    add(f"- Machine-readable artifact: `{report['artifacts']['reports'][0] if report['artifacts']['reports'] else REPORT_RELATIVE_PATH}`.")
    add(f"- Generated at: `{report['generated_at']}` — status: `{report['status']}`.")
    add("- This document and the JSON report are evidence only; GPT review decides completion.")
    add("")
    add("## 1. Scope and safety boundary")
    add("")
    add(
        "The contract records key **names**, group ids and configured/empty booleans from the local "
        f"environment file `{env_file['path_label']}`. No value is recorded and the file is never modified."
    )
    add("")
    lines.extend(
        _table(
            ("Property", "Observation"),
            (
                ("Environment file label", f"`{env_file['path_label']}`"),
                ("Present locally", _yes_no(env_file["exists_locally"])),
                ("Ignored by Git", _yes_no(env_file["ignored_by_git"])),
                ("Tracked by Git", _yes_no(env_file["tracked_by_git"])),
                ("Opened read-only", _yes_no(guard["read_only_collection"])),
                ("Unchanged after collection", _yes_no(guard["file_unchanged_after_read"])),
                ("Git status unchanged", _yes_no(guard["git_status_unchanged"])),
                ("Values recorded", "none"),
                ("Values hashed", "none"),
                ("Assignment lines reproduced", "none"),
                ("Key names recorded", str(inventory["unique_key_count"])),
                ("Parsed assignment lines", str(inventory["key_count"])),
                ("Malformed lines", str(inventory["malformed_line_count"])),
                ("Comment lines", str(inventory["comment_line_count"])),
                ("Blank lines", str(inventory["blank_line_count"])),
            ),
        )
    )
    add("")
    add("## 2. Binding rules for the shared NEWERP/NEWAPP platform")
    add("")
    lines.extend(f"- {statement}" for statement in contract["statements"])
    add("")
    add(contract["convention"])
    add("")
    add("## 3. Key groups")
    add("")
    for group in report["groups"]:
        add(f"### {group['id']} — {group['label']}")
        add("")
        add(f"Consumer: {group['consumer']}. Declared in the controller policy: {_yes_no(group['from_policy'])}.")
        add("")
        if group["present_names"]:
            add(f"Names expected by the policy: {_cell_names(group['expected_names'])}")
            add("")
            empty = set(group["empty_value_names"])
            rows = [
                (
                    f"`{name}`",
                    "empty value" if name in empty else "configured",
                    f"`{configuration_key_for(name)}`",
                    group["consumer"],
                )
                for name in group["present_names"]
            ]
            lines.extend(_table(("Name", "State", "Configuration key", "Consumer"), rows))
        else:
            add("No name in the current environment file belongs to this group.")
        add("")
        add(f"Missing from this group: {_cell_names(group['missing_names'])}")
        add("")
    add("## 4. Binding map")
    add("")
    lines.extend(
        _table(
            ("Name", "Group", "Configuration key", "Consumer"),
            [
                (f"`{entry['env_name']}`", entry["group"], f"`{entry['configuration_key']}`", entry["consumer"])
                for entry in report["binding_map"]
            ],
        )
    )
    add("")
    add("## 5. Missing, empty and unknown names (report only)")
    add("")
    add(f"- Missing names: {_cell_names(report['missing_key_names'])}")
    add(f"- Empty-value names: {_cell_names(report['empty_value_key_names'])}")
    add(f"- Names without a group match: {_cell_names(report['unclassified_key_names'])}")
    add(f"- Duplicate names: {_cell_names(inventory['duplicate_key_names'])}")
    add(f"- Malformed parsed lines: {inventory['malformed_line_count']}")
    add("")
    add(
        "Nothing in this section is written back: no name is added, renamed, normalized or removed by "
        "automation, and a repair stays a GPT/human decision."
    )
    add("")
    add("## 6. Value-free guarantees")
    add("")
    add(f"Self-check status: `{check['status']}` — findings: {check['violations_count']}.")
    add("")
    add(f"Rules applied: {', '.join(f'`{rule}`' for rule in check['rules'])}.")
    add("")
    lines.extend(f"- {item}" for item in report["limitations"])
    add("")
    add("## 7. Reproduce")
    add("")
    add("```powershell")
    lines.extend(report["reproduce"].values())
    add("```")
    add("")
    add("## 8. Controller path guard compatibility")
    add("")
    guard_view = report["path_guard_compatibility"]
    lines.extend(
        _table(
            ("Executor path", "Accepted by the policy"),
            [(f"`{entry['path']}`", _yes_no(entry["accepted"])) for entry in guard_view["paths"]],
        )
    )
    add("")
    add(f"All paths accepted: {_yes_no(guard_view['all_paths_accepted'])}.")
    add("")
    if report["unresolved_issues"]:
        add("Open items for the controller/GPT plan owner:")
        add("")
        lines.extend(f"- {item['issue']} — {', '.join(item['paths'])}" for item in report["unresolved_issues"])
        add("")
    return "\n".join(lines) + "\n"



def collect_facts(
    root: Path,
    *,
    generated_at: str,
    env_relative: str = ENV_FILE,
    policy_relative: str = POLICY_RELATIVE_PATH,
    executor_payload_received: bool = False,
    payload_sources: Sequence[str] = (),
    executor_paths: Sequence[str] = (),
    report_paths: Sequence[str] = (),
    document_paths: Sequence[str] = (),
) -> dict[str, Any]:
    """Collect the value-free facts for the configuration contract (read-only)."""
    policy = policy_facts(root, policy_relative)
    guard = read_environment_facts(root, env_relative)
    classification = build_groups(guard["parsing"], policy)
    allowed = policy.get("executor_allowed_paths", []) if policy.get("available") else []
    return {
        "generated_at": generated_at,
        "executor_payload_received": executor_payload_received,
        "executor_paths": list(executor_paths),
        "report_paths": list(report_paths),
        "document_paths": list(document_paths),
        "payload_reconstruction": {
            "controller_payload_section_present": executor_payload_received,
            "sources": list(payload_sources),
            "note": (
                "Task identity, GPT plan and allowed paths were read from the controller-owned records listed in "
                "sources. No queue, approval, branch or state file was written by the executor."
            ),
        },
        "controller": controller_facts(root),
        "git": git_facts(root),
        "environment_file": environment_file_facts(root, env_relative),
        "read_only_guard": guard,
        "policy": policy,
        "classification": classification,
        "binding_map": build_binding_map(guard["parsing"], classification),
        "path_guard_compatibility": path_guard_compatibility(executor_paths, allowed),
    }


def render_artifacts(
    report: dict[str, Any],
    key_names: Sequence[str],
    json_label: str,
    document_label: str,
) -> tuple[str, str, list[dict[str, Any]]]:
    """Render both artifacts and re-check them for value leaks before anything is written."""
    json_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    document_text = render_markdown(report)
    violations = find_value_free_violations(json_text, key_names, json_label)
    violations.extend(find_value_free_violations(document_text, key_names, document_label))
    return json_text, document_text, violations



def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record the NEWAPP-002 value-free environment configuration contract")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--env-file", default=ENV_FILE, help="environment file label, read-only")
    parser.add_argument("--policy", default=POLICY_RELATIVE_PATH, help="controller configuration file, read-only")
    parser.add_argument("--report", action="append", default=None, help=f"JSON report path, repeatable, default <root>/{REPORT_RELATIVE_PATH}")
    parser.add_argument("--markdown", default=DOCUMENT_RELATIVE_PATH, help="markdown contract document path")
    parser.add_argument("--write", action="store_true", help="write the report and the document")
    parser.add_argument("--executor-file", action="append", default=[], help="path produced or changed by the executor for this task")
    parser.add_argument("--payload-received", action="store_true", help="the controller payload section reached the executor")
    parser.add_argument("--payload-source", action="append", default=[], help="controller-owned record used to reconstruct the task")
    parser.add_argument("--json", action="store_true", help="print the whole value-free report")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    report_targets = [relative_target(root, item) for item in (args.report or [REPORT_RELATIVE_PATH])]
    document_target = relative_target(root, args.markdown)
    executor_paths = [relative for relative, _ in report_targets] + [document_target[0]]
    for item in args.executor_file:
        relative, _absolute = relative_target(root, item)
        if relative not in executor_paths:
            executor_paths.append(relative)
    sources = args.payload_source or [
        "docs/NEWAPP_TASKS_V1.yaml#NEWAPP-002",
        ".ai/brain/decisions/NEWAPP-002-plan.json",
        ".ai/agent_config.yaml#paths.executor_allowed",
    ]
    facts = collect_facts(
        root,
        generated_at=utc_now(),
        env_relative=args.env_file,
        policy_relative=args.policy,
        executor_payload_received=args.payload_received,
        payload_sources=sources,
        executor_paths=executor_paths,
        report_paths=[relative for relative, _ in report_targets],
        document_paths=[document_target[0]],
    )
    report = build_report(facts)
    key_names = report["key_inventory"]["key_names"]
    json_label, _json_path = report_targets[0]
    # First pass: check the artifacts before the verdict itself is published inside them.
    _json_text, _document_text, violations = render_artifacts(report, key_names, json_label, document_target[0])
    report["value_free_check"] = {
        "status": "passed" if not violations else "failed",
        "rules": [rule for rule, _ in VALUE_FREE_RULES],
        "violations_count": len(violations),
        "violations": violations[:20],
    }
    report["acceptance_evidence"][0]["satisfied"] = not violations
    report["status"] = (
        "evidence_collected" if all(item["satisfied"] for item in report["acceptance_evidence"]) else "attention_required"
    )
    json_text, document_text, final_violations = render_artifacts(report, key_names, json_label, document_target[0])
    # Second pass: the final artifacts (including the check verdict) must still be clean, otherwise nothing is written.
    if violations or final_violations:
        for item in (violations or final_violations)[:20]:
            print(f"  value_free_violation {item['rule']} {item['artifact']} line={item['line']}")
        print("value_free_check failed: no artifact was written")
        return 1

    written: list[str] = []
    if args.write:
        for relative, absolute in report_targets:
            atomic_write_json(absolute, report)
            written.append(relative)
        atomic_write_text(document_target[1], document_text)
        written.append(document_target[0])
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "evidence_collected" else 1

    inventory = report["key_inventory"]
    env_file = report["environment_file"]
    print(f"task={report['task_id']} status={report['status']} generated_at={report['generated_at']}")
    print(
        f"env_file={env_file['path_label']} present={env_file['exists_locally']} "
        f"ignored={env_file['ignored_by_git']} tracked={env_file['tracked_by_git']}"
    )
    print(
        "key_names={unique_key_count} configured={configured_key_count} empty={empty_value_key_count} "
        "malformed={malformed_line_count}".format(**inventory)
    )
    print(
        "groups="
        + ", ".join(f"{group['id']}:{group['present_count']}/{group['expected_count']}" for group in report["groups"])
    )
    print(f"unclassified={len(report['unclassified_key_names'])} missing={len(report['missing_key_names'])}")
    print(f"value_free_check={report['value_free_check']['status']} findings={report['value_free_check']['violations_count']}")
    for entry in report["path_guard_compatibility"]["paths"]:
        mark = "accepted" if entry["accepted"] else "NOT_ACCEPTED"
        print(f"path_guard {mark} {entry['path']}")
    if written:
        print("artifacts_written=" + ", ".join(written))
    else:
        print("artifacts_not_written (use --write)")
    return 0 if report["status"] == "evidence_collected" else 1


if __name__ == "__main__":
    raise SystemExit(main())

