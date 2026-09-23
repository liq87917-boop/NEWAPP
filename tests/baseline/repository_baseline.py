"""Repository baseline report for NEWAPP-001 ("Freeze repository baseline and secret rules").

Generates the machine-readable, value-free evidence required by the GPT plan for NEWAPP-001::

    .venv\\Scripts\\python.exe tests\\baseline\\repository_baseline.py --write \\
        --report .ai/generated/NEWAPP-001-baseline-report.json \\
        --report docs/NEWAPP-001-baseline-report.json \\
        --executor-file tests/baseline/secret_scan.py --executor-file tests/baseline/repository_baseline.py

The report contains booleans, counts and repository-relative path names only. No credential value,
no environment value and no controller state is written or echoed. Collection is read-only; only
``--write`` adds the report files. ``--report`` is repeatable: the GPT plan artifact lives under
``.ai/generated/`` and an identical mirror under ``docs/``. Both locations are accepted by the
controller path guard, which removes only exact leading ``./`` prefixes before matching
(:func:`normalize_for_path_guard` mirrors that normalization, see :func:`path_guard_compatibility`).
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

BASELINE_DIR = Path(__file__).resolve().parent
if str(BASELINE_DIR) not in sys.path:
    sys.path.insert(0, str(BASELINE_DIR))

from secret_scan import scan_repository  # noqa: E402

TASK_ID = "NEWAPP-001"
TASK_TITLE = "Freeze repository baseline and secret rules"
TASK_PHASE = "P0"
REPORT_RELATIVE_PATH = ".ai/generated/NEWAPP-001-baseline-report.json"
ENV_FILE = ".env"
GITIGNORE = ".gitignore"

GITIGNORE_REQUIRED_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "agent.env",
    "agent.env.*",
    "*.pfx",
    "*.p12",
    "*.jks",
    "*.keystore",
    "*.mobileprovision",
    "*.pem",
    "*.key",
    "secrets/",
    "exports/",
    "temp/",
)

REPOSITORY_RULE_FILES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (".clinerules", ("executor", "controller", "gpt")),
    (".ai/EXECUTOR_RULES.md", ("executor", "controller", "gpt")),
    (".ai/BRAIN_RULES.md", ("gpt", "executor", "controller")),
    (".github/workflows/control-plane.yml", ("git ls-files",)),
)

LIMITATIONS: tuple[str, ...] = (
    "The scanner covers Git tracked files only; ignored local files such as .env are out of scope "
    "because they must never be committed.",
    "Binary files and files larger than the scanner limit are reported by name and not parsed.",
    "A high-entropy secret with no keyword, no known prefix and no credential-like file name cannot "
    "be detected by pattern scanning.",
    "Documentation placeholders and template references are intentionally not reported as credentials.",
    ".env is verified by path and Git status only: this report never reads, hashes or echoes .env.",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
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


def normalize_for_path_guard(path: str) -> str:
    """Mirror the normalization used by the controller path guard (``common.path_matches``).

    Separators are unified to ``/``, only *exact* leading ``./`` prefixes are removed (one prefix at
    a time, exactly like the controller loop) and the result is lower-cased for ``fnmatch``. The
    leading dot of a real dot-directory such as ``.ai/`` or ``.github/`` is preserved, so
    ``.ai/generated/report.json`` matches ``.ai/generated/**``.
    """
    normalized = str(path).replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lower()


def path_guard_compatibility(paths: Sequence[str], allowed_patterns: Sequence[str]) -> dict[str, Any]:
    """Show which executor paths the controller path guard accepts.

    ``common.path_matches`` normalizes with ``path.replace("\\\\", "/")`` and removes only exact
    leading ``./`` prefixes before ``fnmatch``, so dot-directory patterns such as ``.ai/generated/**``
    match. :func:`normalize_for_path_guard` mirrors that behavior, and
    ``tests/baseline/test_repository_baseline.py`` compares the mirror with the controller module, so
    the report stays aligned without the executor editing protected controller code.
    """
    entries: list[dict[str, Any]] = []
    for path in paths:
        normalized = normalize_for_path_guard(path)
        matched = [
            str(pattern)
            for pattern in allowed_patterns
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
    return {
        "allowed_patterns_source": ".ai/agent_config.yaml#paths.executor_allowed",
        "normalization": (
            "common.path_matches applies path.replace('\\\\','/') and removes only exact leading './' "
            "prefixes before fnmatch, so dot-directory patterns are preserved"
        ),
        "paths": entries,
        "all_paths_accepted": all(entry["accepted"] for entry in entries),
    }


def git_facts(root: Path) -> dict[str, Any]:
    inside_code, _ = run_git(root, ["rev-parse", "--is-inside-work-tree"])
    head_code, head_commit = run_git(root, ["rev-parse", "--verify", "HEAD"])
    branch_code, branch = run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    tracked_code, tracked = run_git(root, ["ls-files"])
    return {
        "repository_present": inside_code == 0,
        "baseline_commit_present": head_code == 0,
        "head_commit": head_commit.splitlines()[0] if head_code == 0 and head_commit else None,
        "branch": branch if branch_code == 0 else None,
        "tracked_file_count": len(tracked.splitlines()) if tracked_code == 0 else 0,
    }


def environment_file_facts(root: Path) -> dict[str, Any]:
    """Describe .env by path and Git status only; content is never read."""
    ignored_code, _ = run_git(root, ["check-ignore", "-q", ENV_FILE])
    tracked_code, _ = run_git(root, ["ls-files", "--error-unmatch", ENV_FILE])
    return {
        "path_label": ENV_FILE,
        "exists_locally": (root / ENV_FILE).is_file(),
        "ignored_by_git": ignored_code == 0,
        "tracked_by_git": tracked_code == 0,
        "content_read": False,
    }


def gitignore_facts(root: Path, required: Sequence[str] = GITIGNORE_REQUIRED_PATTERNS) -> dict[str, Any]:
    path = root / GITIGNORE
    if not path.is_file():
        return {
            "gitignore_present": False,
            "required_patterns": list(required),
            "missing_patterns": list(required),
            "covered_count": 0,
            "required_count": len(required),
        }
    entries = {
        line.strip().lower()
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    missing = [pattern for pattern in required if pattern.lower() not in entries]
    return {
        "gitignore_present": True,
        "required_patterns": list(required),
        "missing_patterns": missing,
        "covered_count": len(required) - len(missing),
        "required_count": len(required),
    }


def repository_rule_facts(
    root: Path,
    rules: Sequence[tuple[str, Sequence[str]]] = REPOSITORY_RULE_FILES,
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for relative, markers in rules:
        path = root / relative
        if not path.is_file():
            facts.append(
                {"path": relative, "exists": False, "missing_markers": list(markers), "separation_confirmed": False}
            )
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace").lower()
        missing = [marker for marker in markers if marker not in text]
        facts.append(
            {
                "path": relative,
                "exists": True,
                "sha256": sha256_file(path),
                "missing_markers": missing,
                "separation_confirmed": not missing,
            }
        )
    return facts


def policy_facts(root: Path) -> dict[str, Any]:
    path = root / ".ai" / "agent_config.yaml"
    if not path.is_file():
        return {"available": False}
    try:
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {"available": False}
    paths = settings.get("paths", {})
    human_gate = settings.get("human_gate", {})
    return {
        "available": True,
        "protected_path_pattern_count": len(paths.get("protected", [])),
        "executor_allowed_paths": list(paths.get("executor_allowed", [])),
        "human_gate_task_ids": list(human_gate.get("task_ids", [])),
        "forbidden_even_with_approval": list(human_gate.get("forbidden_even_with_approval", [])),
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
    """Assemble the value-free NEWAPP-001 baseline report from collected facts."""
    scan = facts["secret_scan"]
    env = facts["environment_file"]
    ignore = facts["gitignore_coverage"]
    rules = facts["repository_rules"]
    env_ok = bool(env["exists_locally"] and env["ignored_by_git"] and not env["tracked_by_git"])
    rules_ok = all(item["separation_confirmed"] for item in rules)
    policy_paths = facts["policy"].get("executor_allowed_paths", []) if facts["policy"].get("available") else []
    guard_view = path_guard_compatibility(facts.get("executor_paths", []), policy_paths)
    unresolved: list[dict[str, Any]] = []
    if guard_view["paths"] and not guard_view["all_paths_accepted"]:
        unresolved.append(
            {
                "issue": "controller path guard rejects executor path(s)",
                "paths": [entry["path"] for entry in guard_view["paths"] if not entry["accepted"]],
                "reason": (
                    "the paths above match no pattern in .ai/agent_config.yaml#paths.executor_allowed after the "
                    "controller normalization (backslashes become '/', only exact leading './' prefixes are removed)"
                ),
                "impact": "guard_changes reports these paths under outside_allowed_paths and the evidence manifest becomes insufficient",
                "executor_action": (
                    "the executor writes no path outside the GPT-approved allowed list; changing the allowed list is a "
                    "GPT plan decision, not an executor edit"
                ),
                "owner": "controller/GPT plan owner (protected configuration); the executor does not edit controller code",
            }
        )
    report: dict[str, Any] = {
        "task_id": TASK_ID,
        "task_title": TASK_TITLE,
        "task_phase": TASK_PHASE,
        "artifact": "repository_baseline_report",
        "generated_at": facts["generated_at"],
        "generated_by": "newapp_executor (Cline/DeepSeek)",
        "completion_authority": "GPT brain final review; this artifact is evidence only",
        "executor_payload_received": facts["executor_payload_received"],
        "payload_reconstruction": facts["payload_reconstruction"],
        "controller": facts["controller"],
        "git": facts["git"],
        "environment_file": env,
        "gitignore_coverage": ignore,
        "repository_rules": {"files": rules, "all_separation_confirmed": rules_ok},
        "secret_scan": scan,
        "policy": facts["policy"],
        "artifacts": {"reports": list(facts.get("report_paths", [])), "executor_paths": list(facts.get("executor_paths", []))},
        "path_guard_compatibility": guard_view,
        "unresolved_issues": unresolved,
        "acceptance_evidence": [
            {
                "criterion": ".env remains present locally and untracked.",
                "evidence": "git check-ignore and git ls-files --error-unmatch evaluated on the path label only",
                "satisfied": env_ok,
            },
            {
                "criterion": "Secret scanner on tracked files reports no credentials.",
                "evidence": f"tests/baseline/secret_scan.py over {scan['tracked_file_count']} tracked files",
                "satisfied": scan["status"] == "passed",
            },
            {
                "criterion": "Repository rules state the GPT brain / executor separation.",
                "evidence": "repository_rules.files markers per rule file",
                "satisfied": rules_ok,
            },
        ],
        "reproduce": {
            "secret_scan": "python tests/baseline/secret_scan.py --json",
            "baseline_report": "python tests/baseline/repository_baseline.py --write",
            "unit_tests": "python -m unittest discover -s tests -p \"test_*.py\"",
        },
        "limitations": list(LIMITATIONS),
        "secret_values_included": False,
    }
    report["status"] = (
        "evidence_collected" if all(item["satisfied"] for item in report["acceptance_evidence"]) else "attention_required"
    )
    return report


def secret_scan_facts(root: Path) -> dict[str, Any]:
    """Run the tracked-file scan, failing closed with a value-free placeholder when unavailable."""
    try:
        return scan_repository(root)
    except Exception:
        return {
            "scope": "git_tracked_files",
            "tracked_file_count": 0,
            "files_scanned": 0,
            "scanned_paths": [],
            "files_skipped_binary": [],
            "files_skipped_large": [],
            "files_missing_on_disk": [],
            "content_rules": [],
            "path_rules": [],
            "findings_count": 0,
            "findings": [],
            "values_recorded": False,
            "status": "not_scanned",
            "reason": "tracked file enumeration failed; the root is not a Git work tree or git is unavailable",
        }


def collect_facts(
    root: Path,
    *,
    generated_at: str,
    executor_payload_received: bool = False,
    payload_sources: Sequence[str] = (),
    executor_paths: Sequence[str] = (),
    report_paths: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "generated_at": generated_at,
        "executor_payload_received": executor_payload_received,
        "executor_paths": list(executor_paths),
        "report_paths": list(report_paths),
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
        "environment_file": environment_file_facts(root),
        "gitignore_coverage": gitignore_facts(root),
        "repository_rules": repository_rule_facts(root),
        "secret_scan": secret_scan_facts(root),
        "policy": policy_facts(root),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect the NEWAPP-001 repository baseline and secret-rule evidence")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--report", action="append", default=None, help=f"report path, repeatable, default <root>/{REPORT_RELATIVE_PATH}")
    parser.add_argument("--write", action="store_true", help="write the report under .ai/generated/")
    parser.add_argument("--executor-file", action="append", default=[], help="path produced or changed by the executor for this task")
    parser.add_argument("--payload-received", action="store_true", help="the controller payload section reached the executor")
    parser.add_argument("--payload-source", action="append", default=[], help="controller-owned record used to reconstruct the task")
    parser.add_argument("--json", action="store_true", help="print the whole value-free report")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    sources = args.payload_source or [
        "docs/NEWAPP_TASKS_V1.yaml#NEWAPP-001",
        ".ai/brain/decisions/NEWAPP-001-plan.json",
        ".ai/agent_config.yaml#paths.executor_allowed",
    ]
    targets: list[tuple[str, Path]] = []
    for item in args.report or [REPORT_RELATIVE_PATH]:
        candidate = Path(item)
        absolute = candidate if candidate.is_absolute() else root / candidate
        try:
            relative = str(absolute.resolve().relative_to(root)).replace("\\", "/")
        except ValueError:
            relative = str(candidate).replace("\\", "/")
        targets.append((relative, absolute))
    executor_paths = [relative for relative, _ in targets]
    for item in args.executor_file:
        candidate = Path(item)
        absolute = candidate if candidate.is_absolute() else root / candidate
        try:
            relative = str(absolute.resolve().relative_to(root)).replace("\\", "/")
        except ValueError:
            relative = str(candidate).replace("\\", "/")
        if relative not in executor_paths:
            executor_paths.append(relative)
    facts = collect_facts(
        root,
        generated_at=generated_at,
        executor_payload_received=args.payload_received,
        payload_sources=sources,
        executor_paths=executor_paths,
        report_paths=[relative for relative, _ in targets],
    )
    report = build_report(facts)
    written: list[str] = []
    if args.write:
        for relative, absolute in targets:
            atomic_write_json(absolute, report)
            written.append(relative)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    scan = report["secret_scan"]
    env = report["environment_file"]
    print(f"task={report['task_id']} status={report['status']} generated_at={report['generated_at']}")
    print(f"branch={report['git']['branch']} head={report['git']['head_commit']} tracked={report['git']['tracked_file_count']}")
    print(
        "env exists={exists_locally} ignored={ignored_by_git} tracked={tracked_by_git}".format(**env)
    )
    print(
        "gitignore covered={covered_count}/{required_count} missing={missing_patterns}".format(
            **report["gitignore_coverage"]
        )
    )
    print(
        "secret_scan tracked={tracked_file_count} scanned={files_scanned} findings={findings_count} status={status}".format(
            **scan
        )
    )
    for finding in scan["findings"]:
        print(f"  finding {finding['rule']} {finding['path']} line={finding['line']}")
    guard = report["path_guard_compatibility"]
    for entry in guard["paths"]:
        mark = "accepted" if entry["accepted"] else "NOT_ACCEPTED"
        print(f"path_guard {mark} {entry['path']} normalized={entry['normalized_for_guard']}")
    if not guard["all_paths_accepted"]:
        print("warning: the controller path guard rejects the paths above; see unresolved_issues in the report")
    if written:
        print("reports_written=" + ",".join(written))
    else:
        print("report_not_written (use --write)")
    return 0 if report["status"] == "evidence_collected" else 1


if __name__ == "__main__":
    raise SystemExit(main())
