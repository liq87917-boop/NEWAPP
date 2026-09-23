"""Tracked-file secret scanner for the NEWAPP repository baseline (NEWAPP-001).

Run it directly against the current checkout::

    .venv\\Scripts\\python.exe tests\\baseline\\secret_scan.py --json

Safety contract
---------------
* A finding contains only a rule id, a repository-relative path and a line number.
* Matched text is never returned, printed, logged, stored or put into an exception message, so
  the scanner output can be published as evidence without leaking a credential.
* Credential files such as ``.env`` are reported by path name only; no code path in this module
  echoes their content.
* Scanning is read-only: no worktree, index or repository state is created or modified.

Documented limits (reviewed by GPT, not silently expanded)
----------------------------------------------------------
* Only files tracked by Git are scanned. Ignored local files such as ``.env`` are intentionally
  out of scope because they must never be committed.
* Binary files and files larger than ``DEFAULT_MAX_BYTES`` are skipped and reported by name.
* A high-entropy secret without a keyword, without a known prefix and without a credential-like
  file name cannot be detected by pattern scanning.
* Keyword assignments whose value is shorter than ``MIN_ASSIGNMENT_LENGTH`` characters, or whose
  value looks like a template/placeholder reference, are treated as non-secrets.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

DEFAULT_MAX_BYTES = 2_000_000
MIN_ASSIGNMENT_LENGTH = 8
BINARY_SNIFF_BYTES = 4096

CREDENTIAL_KEYWORDS = (
    r"(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|accesskey|"
    r"access[_-]?key[_-]?(?:id|secret)|client[_-]?secret|private[_-]?key|auth[_-]?token|"
    r"connection[_-]?string|authorization|credential|jwt[_-]?key|signing[_-]?key)"
)

ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b"
    + CREDENTIAL_KEYWORDS
    + r"\b[\"']?\s*[:=]\s*(?:\"([^\"\n]{4,})\"|'([^'\n]{4,})'|([^\s,;#\"'`]{4,}))"
)

PLACEHOLDER_VALUES = re.compile(
    r"""^(?:
        \$\{?[A-Za-z_][\w.]*\}?                 # ${VAR} or $VAR
      | %[A-Za-z_][\w.]*%                       # %VAR%
      | \{\{[^}]*\}\}                           # {{ template }}
      | \{[A-Za-z_][\w.\[\]"'()]*\}             # {name} / {obj.attr} format placeholder
      | <[^>]*>                                 # <placeholder>
      | \[[^\]]*\]                              # [placeholder]
      | \.{3,} | \*{3,} | x{3,}                 # masked values
      | (?:string|number|integer|boolean|object|array|null|true|false|value)
      | (?:placeholder|example|sample|dummy|test|demo|fake|todo|redacted)[\w.!@#$%^&*+-]*
      | (?:change[_-]?me|replace[_-]?me|not[_-]?set|undefined|empty|none)
      | (?:your|my|some|the)[_-][\w-]*
      | (?:os\.environ|process\.env|environment\.|getenv|env\.|config\.|settings\.)[\w(\["'.\]]*
    )$""",
    re.IGNORECASE | re.VERBOSE,
)

EXEMPT_PATH_PATTERNS: tuple[str, ...] = (".env.example", "*.env.example", ".env.sample", "*.env.sample")

TRACKED_CREDENTIAL_NAME_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "agent.env",
    "agent.env.*",
    "*.pfx",
    "*.p12",
    "*.jks",
    "*.keystore",
    "*.pem",
    "*.key",
    "*.ppk",
    "*.p8",
    "*.mobileprovision",
    "*id_rsa*",
    "*id_ed25519*",
    "*.npmrc",
    "*.netrc",
    "*.pgpass",
    "*secrets/*",
    "*secret/*",
    "*credential*.json",
    "*credentials*.txt",
)


@dataclass(frozen=True)
class ContentRule:
    """A pattern applied to the text content of a tracked file."""

    id: str
    description: str
    pattern: re.Pattern[str]
    value_groups: tuple[int, ...] = ()


CONTENT_RULES: tuple[ContentRule, ...] = (
    ContentRule(
        "private_key_block",
        "PEM private key block header",
        re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    ),
    ContentRule(
        "known_token_prefix",
        "Cloud or provider credential with a known literal prefix",
        re.compile(
            r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"
            r"|\bLTAI[0-9A-Za-z]{12,}\b"
            r"|\bsk-[A-Za-z0-9]{20,}\b"
            r"|\bghp_[A-Za-z0-9]{30,}\b"
            r"|\bgithub_pat_[A-Za-z0-9_]{30,}\b"
            r"|\bxox[baprs]-[A-Za-z0-9-]{10,}\b"
        ),
    ),
    ContentRule(
        "jwt_like_literal",
        "JWT-shaped literal",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ),
    ContentRule(
        "credential_assignment",
        "Credential keyword assigned a non-placeholder value",
        ASSIGNMENT_PATTERN,
        value_groups=(1, 2, 3),
    ),
)

def is_placeholder_value(value: str) -> bool:
    """Return True when a captured assignment value cannot be a real credential."""
    return bool(PLACEHOLDER_VALUES.match(value.strip().strip("\"'")))


def is_exempt_path(relative_path: str) -> bool:
    return any(fnmatch.fnmatch(relative_path, pattern) for pattern in EXEMPT_PATH_PATTERNS)


def path_rule_findings(relative_path: str) -> list[dict[str, Any]]:
    """Report credential-like file names, without reading the file."""
    if is_exempt_path(relative_path):
        return []
    if not any(fnmatch.fnmatch(relative_path, pattern) for pattern in TRACKED_CREDENTIAL_NAME_PATTERNS):
        return []
    return [{"rule": "tracked_credential_file", "path": relative_path, "line": None}]


def text_rule_findings(relative_path: str, text: str) -> list[dict[str, Any]]:
    """Report content rules per line; only rule id, path and line number are returned."""
    findings: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for rule in CONTENT_RULES:
            match = rule.pattern.search(line)
            if match is None:
                continue
            if rule.value_groups:
                value = next((group for group in (match.group(index) for index in rule.value_groups) if group), None)
                if value is None or len(value.strip()) < MIN_ASSIGNMENT_LENGTH or is_placeholder_value(value):
                    continue
            findings.append({"rule": rule.id, "path": relative_path, "line": number})
    return findings


def tracked_files(root: Path) -> list[str]:
    """List Git tracked files; raises when the directory is not a Git work tree."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git ls-files failed with exit code {result.returncode}")
    return [entry.replace("\\", "/") for entry in result.stdout.split("\0") if entry]


def scan_repository(
    root: Path | str,
    *,
    tracked: Sequence[str] | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Scan the given tracked files and return a value-free summary."""
    root_path = Path(root)
    paths = list(tracked) if tracked is not None else tracked_files(root_path)
    findings: list[dict[str, Any]] = []
    scanned: list[str] = []
    skipped_binary: list[str] = []
    skipped_large: list[str] = []
    missing: list[str] = []
    for relative in sorted(paths):
        findings.extend(path_rule_findings(relative))
        target = root_path / relative
        if not target.is_file():
            missing.append(relative)
            continue
        if target.stat().st_size > max_bytes:
            skipped_large.append(relative)
            continue
        raw = target.read_bytes()
        if b"\x00" in raw[:BINARY_SNIFF_BYTES]:
            skipped_binary.append(relative)
            continue
        scanned.append(relative)
        findings.extend(text_rule_findings(relative, raw.decode("utf-8", errors="replace")))
    return {
        "scope": "git_tracked_files",
        "tracked_file_count": len(paths),
        "files_scanned": len(scanned),
        "scanned_paths": scanned,
        "files_skipped_binary": skipped_binary,
        "files_skipped_large": skipped_large,
        "files_missing_on_disk": missing,
        "content_rules": [{"id": rule.id, "description": rule.description} for rule in CONTENT_RULES],
        "path_rules": list(TRACKED_CREDENTIAL_NAME_PATTERNS),
        "findings_count": len(findings),
        "findings": findings,
        "values_recorded": False,
        "status": "passed" if not findings else "failed",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan Git tracked files for credential material without echoing it")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--json", action="store_true", help="print the full value-free summary as JSON")
    args = parser.parse_args(argv)
    try:
        summary = scan_repository(Path(args.root), max_bytes=args.max_bytes)
    except Exception as exc:  # fail closed on an unexpected scanner failure
        print(json.dumps({"status": "error", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            "tracked={tracked_file_count} scanned={files_scanned} findings={findings_count} status={status}".format(**summary)
        )
        for finding in summary["findings"]:
            print(f"  {finding['rule']} {finding['path']} line={finding['line']}")
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
