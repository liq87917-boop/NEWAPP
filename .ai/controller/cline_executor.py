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


_NOISY_AGENT_EVENTS = {"content_start", "content_delta", "content_end"}


def console_message(line: str) -> str | None:
    """Return a compact human-facing message for one Cline JSON-stream line.

    The full redacted line is still written to the audit log. Low-level
    reasoning/content token events are intentionally hidden from the DOS
    console so unattended runs stay readable.
    """
    text = line.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text

    if not isinstance(payload, dict):
        return None

    message_type = str(payload.get("type", ""))
    if message_type == "agent_event":
        event = payload.get("event")
        if not isinstance(event, dict):
            return None
        event_type = str(event.get("type", ""))
        if event_type in _NOISY_AGENT_EVENTS:
            return None
        if event_type in {"error", "failed", "failure"}:
            detail = event.get("message") or event.get("error") or event.get("reason") or "unknown error"
            return f"[Cline] ERROR: {detail}"
        if event_type in {"tool_start", "tool_use", "tool_call"}:
            name = event.get("name") or event.get("tool") or event.get("toolName") or "tool"
            return f"[Cline] tool: {name}"
        if event_type in {"tool_end", "tool_result", "tool_complete"}:
            name = event.get("name") or event.get("tool") or event.get("toolName") or "tool"
            return f"[Cline] tool complete: {name}"
        if event_type in {"task_start", "task_started"}:
            return "[Cline] task started"
        if event_type in {"task_end", "task_completed", "completed"}:
            return "[Cline] task completed"
        return None

    if message_type in {"error", "fatal"}:
        detail = payload.get("message") or payload.get("error") or text
        return f"[Cline] ERROR: {detail}"

    # Some CLI versions emit a compact final message outside agent_event.
    if message_type in {"result", "completion", "final"}:
        message = payload.get("message") or payload.get("text") or payload.get("content")
        if isinstance(message, str) and message.strip():
            one_line = " ".join(message.split())
            return f"[Cline] {one_line[:500]}"

    return None


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
    last_console_heartbeat = time.monotonic()
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
                    log.write(cleaned + "\n")
                    log.flush()
                    compact = console_message(cleaned)
                    if compact:
                        print(compact, flush=True)
                        last_console_heartbeat = time.monotonic()

            if process.poll() is not None and reader_done:
                break

            now = time.monotonic()
            if process.poll() is None and now - last_console_heartbeat >= 30:
                elapsed_seconds = int(now - (deadline - timeout))
                print(f"[Cline] {task['id']} running... {elapsed_seconds}s", flush=True)
                last_console_heartbeat = now

            if process.poll() is None and now >= deadline:
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
