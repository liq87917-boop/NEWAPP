from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
AI_DIR = ROOT / ".ai"
CONFIG_PATH = AI_DIR / "agent_config.yaml"
STATE_PATH = AI_DIR / "project_state.json"
AUDIT_PATH = AI_DIR / "audit.jsonl"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_yaml(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError(f"PyYAML is required to read {path}") from exc
        value = yaml.safe_load(raw)
    if not isinstance(value, dict):
        raise ValueError(f"Expected an object in {path}")
    return value


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected an object in {path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    handle, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def config() -> dict[str, Any]:
    return load_yaml(CONFIG_PATH)


def state() -> dict[str, Any]:
    return load_json(STATE_PATH)


def save_state(value: dict[str, Any], **changes: Any) -> dict[str, Any]:
    value.update(changes)
    value["updated_at"] = utc_now()
    atomic_json(STATE_PATH, value)
    return value


def audit(event: str, **details: Any) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": utc_now(), "event": event, **details}
    with AUDIT_PATH.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    pattern = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = pattern.match(line)
        if not match or line.lstrip().startswith("#"):
            continue
        raw = match.group(2).strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
            raw = raw[1:-1]
        values[match.group(1)] = raw
    return values


def runtime_env() -> dict[str, str]:
    merged = os.environ.copy()
    env_file = ROOT / config()["environment"]["file"]
    for key, value in read_env(env_file).items():
        merged.setdefault(key, value)
    return merged


def redact(text: str, env: dict[str, str] | None = None) -> str:
    cleaned = text
    candidates = (env or read_env(ROOT / config()["environment"]["file"])).values()
    for value in sorted((v for v in candidates if len(v) >= 4), key=len, reverse=True):
        cleaned = cleaned.replace(value, "[REDACTED]")
    cleaned = re.sub(r"(?i)(password|secret|token|access[_-]?key|connection[_-]?string)(\s*[:=]\s*)([^\s,;]+)", r"\1\2[REDACTED]", cleaned)
    return cleaned


def run(command: list[str], *, timeout: int | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=timeout, shell=False)


def git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return run(["git", *args])


def path_matches(path: str, patterns: Iterable[str]) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    return any(fnmatch.fnmatch(normalized.lower(), pattern.replace("\\", "/").lower()) for pattern in patterns)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
