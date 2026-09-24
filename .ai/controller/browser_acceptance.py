from __future__ import annotations

from typing import Any

from common import ROOT, config, redact, run, utc_now
from evidence import screenshot_requirement


def evaluate(task: dict[str, Any], run_id: str) -> dict[str, Any]:
    if not screenshot_requirement(task):
        return {"status": "not_required", "real_browser": False, "screenshots": 0}
    settings = config()["browser_acceptance"]
    commands = settings.get("commands", [])
    if not commands:
        return {
            "status": "blocked" if settings.get("blocking", True) else "deferred_nonblocking",
            "real_browser": bool(settings.get("require_real_browser", True)),
            "screenshots": 0,
            "reason": "No real-browser acceptance command is configured for the current app scaffold",
            "blocking": bool(settings.get("blocking", True)),
        }
    log_path = ROOT / config()["evidence"]["logs_dir"] / f"{run_id}-browser.log"
    outputs: list[str] = []
    steps: list[dict[str, Any]] = []
    overall = 0
    for template in commands:
        command = [str(part).replace("{task_id}", task["id"]).replace("{run_id}", run_id) for part in template]
        started = utc_now()
        result = run(command)
        outputs.append(redact((result.stdout or "") + ("\n" + result.stderr if result.stderr else "")))
        steps.append({"command": command, "started_at": started, "finished_at": utc_now(), "exit_code": result.returncode})
        if result.returncode != 0:
            overall = result.returncode
            break
    log_path.write_text("\n\n".join(outputs), encoding="utf-8", newline="\n")
    screenshot_root = ROOT / config()["evidence"]["screenshots_dir"] / task["id"] / run_id
    screenshot_count = len([path for path in screenshot_root.glob("**/*") if path.is_file()]) if screenshot_root.exists() else 0
    minimum = int(settings.get("minimum_screenshots", 1))
    passed = overall == 0 and screenshot_count >= minimum
    return {
        "status": "passed" if passed else "failed",
        "real_browser": bool(settings.get("require_real_browser", True)),
        "screenshots": screenshot_count,
        "minimum_screenshots": minimum,
        "steps": steps,
        "log": str(log_path.relative_to(ROOT)).replace("\\", "/")
    }
