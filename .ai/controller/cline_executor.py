from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from common import ROOT, config, read_env, redact, runtime_env, utc_now


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
    log_path.parent.mkdir(parents=True, exist_ok=True)

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
    env = runtime_env()
    secret_env = read_env(ROOT / config()["environment"]["file"])
    timeout = int(settings["cline_timeout_seconds"]) + 30

    print(f"[Cline] Starting {task['id']} with provider={settings['cline_provider']}", flush=True)
    print(f"[Cline] Live log: {log_path.relative_to(ROOT)}", flush=True)

    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        shell=False,
    )

    output_queue: queue.Queue[str | None] = queue.Queue()

    def reader() -> None:
        assert process.stdout is not None
        try:
            for raw_line in process.stdout:
                output_queue.put(raw_line)
        finally:
            output_queue.put(None)

    thread = threading.Thread(target=reader, name=f"cline-output-{task['id']}", daemon=True)
    thread.start()

    timed_out = False
    reader_done = False
    deadline = time.monotonic() + timeout
    no_output = object()
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        while True:
            try:
                item = output_queue.get(timeout=0.2)
            except queue.Empty:
                item = no_output

            if item is None:
                reader_done = True
            elif item is not no_output:
                cleaned = redact(str(item).rstrip("\r\n"), secret_env)
                if cleaned:
                    print(cleaned, flush=True)
                    log.write(cleaned + "\n")
                    log.flush()

            if process.poll() is not None and reader_done:
                break

            if process.poll() is None and time.monotonic() >= deadline:
                timed_out = True
                process.kill()

        try:
            exit_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            exit_code = process.wait(timeout=5)

    if timed_out:
        print(f"[Cline] {task['id']} exceeded shutdown grace period and was terminated.", flush=True)

    print(f"[Cline] {task['id']} exited with code {exit_code}", flush=True)
    return {
        "started_at": started,
        "finished_at": utc_now(),
        "exit_code": exit_code,
        "log": str(log_path.relative_to(ROOT)).replace("\\", "/"),
    }
