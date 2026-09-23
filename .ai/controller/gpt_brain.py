from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from common import ROOT, config, runtime_env


class PlanDecision(BaseModel):
    task_id: str
    decision: Literal["execute", "human_gate", "block"]
    rationale: str
    validation_focus: list[str]
    risks: list[str]


class ReviewDecision(BaseModel):
    task_id: str
    decision: Literal["accept", "reject", "human_gate"]
    rationale: str
    criteria_results: list[str]
    required_fixes: list[str]


def _client():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("The openai package is not installed; install requirements-agent.txt") from exc
    env = runtime_env()
    if not env.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=env["OPENAI_API_KEY"]), env


def _rules() -> str:
    return (ROOT / config()["sources"]["brain_rules"]).read_text(encoding="utf-8")


def _model(env: dict[str, str]) -> str:
    settings = config()["runtime"]
    return env.get(settings["openai_model_env"], settings["openai_default_model"])


def plan(task: dict[str, Any]) -> PlanDecision:
    client, env = _client()
    prompt = {
        "purpose": "Authorize or block exactly one NEWAPP queue-head task before Cline runs.",
        "task": task,
        "constraints": "Do not change task id/order/scope. Missing safety evidence means human_gate or block."
    }
    response = client.responses.parse(
        model=_model(env),
        instructions=_rules(),
        input=json.dumps(prompt, ensure_ascii=False),
        text_format=PlanDecision,
        store=False,
    )
    decision = response.output_parsed
    if decision is None or decision.task_id != task["id"]:
        raise RuntimeError("GPT returned no valid decision or changed the task id")
    return decision


def review(task: dict[str, Any], evidence: dict[str, Any]) -> ReviewDecision:
    client, env = _client()
    prompt = {
        "purpose": "Perform final acceptance. Cline success alone is never completion.",
        "task": task,
        "evidence": evidence,
    }
    response = client.responses.parse(
        model=_model(env),
        instructions=_rules(),
        input=json.dumps(prompt, ensure_ascii=False),
        text_format=ReviewDecision,
        store=False,
    )
    decision = response.output_parsed
    if decision is None or decision.task_id != task["id"]:
        raise RuntimeError("GPT returned no valid review or changed the task id")
    return decision

