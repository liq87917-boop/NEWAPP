# NEWAPP automation control plane

This control plane keeps GPT as the planning and final-acceptance authority while Cline/DeepSeek is limited to implementing one approved task at a time.

## Safety model

- `docs/NEWAPP_TASKS_V1.yaml` is the immutable task blueprint and dependency source.
- `.ai/project_state.json` is the only mutable queue/status source.
- Queue selection is local and deterministic: the first unfinished task blocks all later tasks until its dependencies and gates are satisfied.
- Cline exit code 0 becomes `code_ready`, never `completed`.
- A task completes only after local validation, an evidence manifest, and a final structured GPT review all pass.
- `.env` is loaded only in memory. Logs and evidence are redacted and never contain secret values.
- Shared database writes, destructive SQL, production operations, releases, and signing are fail-closed behind Human Gates.
- NEWERP is read-only reference material for this control plane. The runner's working directory is always NEWAPP.

## Setup

```powershell
cd D:\VSCodeProject\NEWAPP
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-agent.txt
```

Add an `OPENAI_API_KEY` entry to the local `.env` when you are ready to use GPT review. Keep Cline authentication in Cline's own local configuration. Do not commit either credential.

## Commands

```powershell
start_agent.bat
start_agent.bat status
start_agent.bat plan
start_agent.bat run-once
start_agent.bat run
start_agent.bat approve NEWAPP-009 --by "Name" --reason "Approved for disposable test database only"
start_agent.bat pause --reason "Maintenance"
start_agent.bat resume
start_agent.bat retry NEWAPP-001 --by "Name" --reason "Runtime issue corrected"
```

Running `start_agent.bat` with no arguments performs a safe preflight only. It does not start a business task. `plan` asks GPT for a read-only execution decision. `run-once` executes at most one task; `run` continues until the queue ends or any gate/failure blocks it.

Human approvals are local runtime records under `.ai/decisions/` and are ignored by Git by default. Approval never permits `DROP`, `TRUNCATE`, production deployment, production DML, or use of production data in tests.
