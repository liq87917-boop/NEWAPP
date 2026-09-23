# NEWAPP automation control plane

This control plane keeps GPT in Codex desktop or ChatGPT mobile Remote as the planning and final-acceptance authority while Cline/DeepSeek is limited to implementing one approved task at a time. It does not call the OpenAI API and does not require `OPENAI_API_KEY`.

## Safety model

- `docs/NEWAPP_TASKS_V1.yaml` is the immutable task blueprint and dependency source.
- `.ai/project_state.json` is the only mutable queue/status source.
- Queue selection is local and deterministic: the first unfinished task blocks all later tasks until its dependencies and gates are satisfied.
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

Running `start_agent.bat` with no arguments performs a safe preflight only. It does not start a business task. `plan` writes a request under `.ai/brain/requests/` and pauses. Codex GPT on desktop or mobile Remote reads that request and records a decision. `run-once` then lets DeepSeek/Cline execute at most one approved task, validates it, writes the evidence review request, and pauses again for Codex GPT final acceptance. The queue never advances while either Codex decision is missing.

## Mobile Remote

Register `D:\VSCodeProject\NEWAPP` as a local Codex project on the Windows host. In the ChatGPT mobile app, open Remote, choose that connected Windows host and the NEWAPP workspace, then open or start the NEWAPP control task. The phone supplies planning, steering, approvals, and final review; Cline/DeepSeek and all builds/tests continue to run on the Windows host. Keep the host online and signed in. Desktop and mobile use the same `.ai/brain/requests/` and `.ai/brain/decisions/` handshake.

## GitHub relay

The private repository `liq87917-boop/NEWAPP` is the cross-device relay. GPT plan decisions are committed to `main`. Each DeepSeek/Cline attempt runs on an `agent/NEWAPP-*` branch and is published as a Pull Request with a redacted evidence manifest. The PR is never merged merely because Cline exits successfully. Codex GPT on desktop or mobile Remote records the final decision; only `accept` triggers a squash merge. Rejections stay on the PR with the reason and required fixes.

Human approvals are local runtime records under `.ai/decisions/` and are ignored by Git by default. Approval never permits `DROP`, `TRUNCATE`, production deployment, production DML, or use of production data in tests.
