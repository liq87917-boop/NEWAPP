from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from common import ROOT, config, redact, run, runtime_env, utc_now


def build_prompt(task: dict[str, Any], plan: dict[str, Any], allowed_paths: list[str]) -> str:
    rules = (ROOT / config()["sources"]["executor_rules"]).read_text(encoding="utf-8")
    payload = {
        "task": task,
        "gpt_plan": plan,
        "allowed_paths": allowed_paths,
        "completion_contract": "Implement and report only. Do not mark complete, commit, push, or edit controller state."
    }
    return rules + "\n\nController payload:\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def execute(task: dict[str, Any], plan: dict[str, Any], run_id: str, allowed_paths: list[str]) -> dict[str, Any]:
    settings = config()["runtime"]
    executable = shutil.which(settings["cline_command"])
    if not executable:
        raise RuntimeError(f"Cline command not found: {settings['cline_command']}")
    log_path = ROOT / config()["evidence"]["logs_dir"] / f"{run_id}-cline.jsonl"
    prompt = build_prompt(task, plan, allowed_paths)
    command = [
        executable,
        "--json",
        "--auto-approve",
        "true",
        "--provider",
        settings["cline_provider"],
        "--cwd",
        str(ROOT),
        "--timeout",
        str(settings["cline_timeout_seconds"]),
        prompt,
    ]
    started = utc_now()
    result = run(command, timeout=int(settings["cline_timeout_seconds"]) + 30, env=runtime_env())
    output = redact((result.stdout or "") + ("\n" + result.stderr if result.stderr else ""))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output, encoding="utf-8", newline="\n")
    return {"started_at": started, "finished_at": utc_now(), "exit_code": result.returncode, "log": str(log_path.relative_to(ROOT)).replace("\\", "/")}
