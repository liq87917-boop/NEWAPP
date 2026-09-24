from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from common import ROOT, atomic_json, config, sha256, utc_now


def screenshot_requirement(task: dict[str, Any]) -> bool:
    terms = [str(term).lower() for term in config()["validation"].get("require_screenshot_when_terms", [])]
    text = json.dumps(task, ensure_ascii=False).lower()
    return any(re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", text) for term in terms)


def build(task: dict[str, Any], run_id: str, executor: dict[str, Any], validation: dict[str, Any], guard: dict[str, Any], browser: dict[str, Any]) -> dict[str, Any]:
    cfg = config()["evidence"]
    evidence_dir = ROOT / cfg["evidence_dir"] / task["id"] / run_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    screenshots_root = ROOT / cfg["screenshots_dir"] / task["id"] / run_id
    screenshots = sorted(path for path in screenshots_root.glob("**/*") if path.is_file()) if screenshots_root.exists() else []
    required = screenshot_requirement(task)
    browser_blocks = bool(config()["browser_acceptance"].get("blocking", True))
    artifacts: list[dict[str, Any]] = []
    for relative in [executor.get("log"), validation.get("log")]:
        if not relative:
            continue
        path = ROOT / relative
        if path.exists():
            artifacts.append({"path": relative, "sha256": sha256(path), "bytes": path.stat().st_size})
    for path in screenshots:
        artifacts.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(path), "bytes": path.stat().st_size})
    accepted_browser_statuses = {"passed", "not_required"}
    if not browser_blocks:
        accepted_browser_statuses.add("deferred_nonblocking")
    passed = executor.get("exit_code") == 0 and validation.get("status") == "passed" and guard.get("status") == "passed" and browser.get("status") in accepted_browser_statuses and (not required or not browser_blocks or bool(screenshots))
    manifest = {
        "task_id": task["id"],
        "run_id": run_id,
        "created_at": utc_now(),
        "status": "ready_for_gpt_review" if passed else "insufficient",
        "executor": executor,
        "validation": validation,
        "path_guard": guard,
        "browser_acceptance": browser,
        "screenshots": {"required": required, "blocking": required and browser_blocks, "count": len(screenshots)},
        "artifacts": artifacts,
        "note": "Cline success is code_ready only; GPT final review is still required."
    }
    atomic_json(evidence_dir / "manifest.json", manifest)
    manifest["manifest_path"] = str((evidence_dir / "manifest.json").relative_to(ROOT)).replace("\\", "/")
    return manifest
