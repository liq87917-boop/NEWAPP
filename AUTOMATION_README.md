# NEWAPP automation control plane

This control plane keeps GPT in Codex desktop or ChatGPT mobile Remote as the planning and final-acceptance authority while Cline/DeepSeek is limited to implementing one approved task at a time. It does not call the OpenAI API and does not require `OPENAI_API_KEY`.

## Safety model

- `docs/NEWAPP_TASKS_V1.yaml` is the immutable task blueprint and dependency source.
- `.ai/project_state.json` is the only mutable queue/status source.
- Queue selection is local and dependency-safe, but no longer globally serialized by review waits. A task in `awaiting_review`, `awaiting_brain`, `awaiting_human`, `blocked`, or `failed` does not stop unrelated tasks whose declared dependencies are already `completed`; active execution states remain exclusive.
- Cline exit code 0 becomes `code_ready`, never `completed`.
- A task completes only after local validation, an evidence manifest, and a final file-backed decision from Codex desktop GPT all pass.
- `.env` is loaded only in memory. Logs and evidence are redacted and never contain secret values.
- Shared database writes, destructive SQL, production operations, releases, and signing are fail-closed behind Human Gates.
- NEWERP is read-only reference material for this control plane. The runner's working directory is always NEWAPP.

## Setup

```powershell
cd D:\VSCodeProject\NEWAPP
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-agent.txt
```

Configure DeepSeek inside Cline using Cline's own local provider settings. Keep that authentication outside the repository. No OpenAI API key is needed.

## Commands

```powershell
start_agent.bat
start_agent.bat status
start_agent.bat plan
start_agent.bat run-once
start_agent.bat run
start_agent.bat record-plan NEWAPP-001 --decision execute --rationale "Approved by desktop GPT" --validation-focus "Secret guard passes"
start_agent.bat record-review NEWAPP-001 RUN_ID --decision accept --rationale "All criteria have evidence"
start_agent.bat approve NEWAPP-009 --by "Name" --reason "Approved for disposable test database only"
start_agent.bat pause --reason "Maintenance"
start_agent.bat resume
start_agent.bat retry NEWAPP-001 --by "Name" --reason "Runtime issue corrected"
```

Running `start_agent.bat` with no arguments performs a safe preflight only. `run-once` executes at most one approved task. `run` is the normal unattended mode: it keeps a rolling queue alive, executes one Cline/DeepSeek task at a time, pushes each completed candidate to its own `agent/NEWAPP-*` branch, records `awaiting_review` on `main`, then immediately continues with another dependency-safe task. If nothing is runnable, the controller stays alive, polls GitHub every 60 seconds, and resumes automatically when GPT review or a dependency unlock changes `main`.


## Rolling GPT task pool

The target pool size is four GPT-planned tasks when the dependency graph allows it. GPT may pre-plan tasks before they become runnable; the local controller still enforces declared dependencies and Human Gates. ChatGPT performs an hourly GitHub review cycle: inspect all pending candidate branches, accept/reject them against evidence, merge accepted work, update task state on `main`, and replenish the plan pool. This means Cline does not wait for GPT after every individual task.

Expected unattended flow:

```text
GPT seeds multiple plans on main
        ↓
start_agent.bat run
        ↓
Cline executes one dependency-safe task
        ↓
validation + evidence
        ↓
push agent/NEWAPP-* candidate
        ↓
mark awaiting_review on main
        ↓
continue next independent task
        ↓
idle-poll GitHub when temporarily blocked
        ↓
hourly GPT review merges/rejects candidates and replenishes plans
        ↓
local agent pulls main and continues automatically
```

## Mobile Remote

Register `D:\VSCodeProject\NEWAPP` as a local Codex project on the Windows host. In the ChatGPT mobile app, open Remote, choose that connected Windows host and the NEWAPP workspace, then open or start the NEWAPP control task. The phone supplies planning, steering, approvals, and final review; Cline/DeepSeek and all builds/tests continue to run on the Windows host. Keep the host online and signed in. Desktop and mobile use the same `.ai/brain/requests/` and `.ai/brain/decisions/` handshake.

## GitHub relay

The private repository `liq87917-boop/NEWAPP` is the cross-device relay. GPT plan decisions are committed to `main`. Each DeepSeek/Cline attempt runs on an `agent/NEWAPP-*` branch and is pushed through the authenticated SSH Git remote together with a redacted evidence manifest and review request. Local automation does **not** require GitHub CLI (`gh`) authentication and does not require a Pull Request to exist. Codex GPT on desktop/mobile or through the connected GitHub integration reviews the task branch and records the final decision. Only `accept` triggers a local Git squash merge into `main` followed by an SSH push; rejection leaves the candidate branch intact for diagnosis or rework.

This mirrors the XAUUSD control pattern more closely: Git transport is the hard dependency, while GitHub CLI/UI features are optional rather than control-plane blockers.

Human approvals are local runtime records under `.ai/decisions/` and are ignored by Git by default. Approval never permits `DROP`, `TRUNCATE`, production deployment, production DML, or use of production data in tests.
