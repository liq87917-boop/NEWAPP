from __future__ import annotations

import shutil
import sys
from typing import Any

from common import ROOT, config, redact, run, utc_now


def validate(task: dict[str, Any], run_id: str, profile: str = "safe") -> dict[str, Any]:
    settings = config()["validation"]
    commands = settings["profiles"].get(profile)
    if not commands:
        raise RuntimeError(f"Unknown validation profile: {profile}")
    commands = [list(command) for command in commands]
    task_commands = settings.get("task_commands", {}).get(task.get("id"), [])
    commands.extend(list(command) for command in task_commands)
    forbidden = {str(token).lower() for token in settings.get("dangerous_command_tokens", [])}
    steps: list[dict[str, Any]] = []
    log_path = ROOT / config()["evidence"]["logs_dir"] / f"{run_id}-validation.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    all_output: list[str] = []
    overall = 0
    for template in commands:
        command = [str(part).replace("{python}", sys.executable) for part in template]
        tokens = {part.lower() for part in command}
        if tokens & forbidden:
            raise RuntimeError(f"Validation command blocked by safety policy: {command[0]}")
        started = utc_now()
        result = run(command)
        output = redact((result.stdout or "") + ("\n" + result.stderr if result.stderr else ""))
        all_output.append("$ " + " ".join(command) + "\n" + output)
        steps.append({"command": command, "started_at": started, "finished_at": utc_now(), "exit_code": result.returncode})
        if result.returncode != 0:
            overall = result.returncode
            break
    log_path.write_text("\n\n".join(all_output), encoding="utf-8", newline="\n")
    return {"status": "passed" if overall == 0 else "failed", "exit_code": overall, "profile": profile, "steps": steps, "log": str(log_path.relative_to(ROOT)).replace("\\", "/")}


def runtime_checks() -> dict[str, Any]:
    cfg = config()
    return {
        "python": sys.version.split()[0],
        "git": shutil.which("git") is not None,
        "cline": shutil.which(cfg["runtime"]["cline_command"]) is not None,
    }

