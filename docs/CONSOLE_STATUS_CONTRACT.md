# NEWAPP status console contract

Task: **NEWAPP-006 — Establish automated status console** (phase P0, depends on NEWAPP-001).
This document records what the status console shows, which machine-readable sources it reads, and
which guarantees the tests in `tests/console/` prove. The GPT brain (Codex desktop / ChatGPT mobile
Remote) stays the planning and final-acceptance authority; the Cline/DeepSeek executor only
implements the single task the controller hands over.

Branch names, commit ids, file counts and hashes are deliberately **not** copied into this document.
`.ai/generated/NEWAPP-006-status-console.json` carries those values so this file cannot drift.

## 1. What the console is

The console is the protected control-plane entry point; NEWAPP-006 adds tests and documentation for
it and does not change it.

| Layer | Path | Protected | Role |
| --- | --- | --- | --- |
| Launcher | `start_agent.bat` | yes | Changes to the repository root, selects the local `.venv` interpreter, dispatches the controller and propagates its exit code |
| Controller | `.ai/controller/agent_loop.py` | yes | Implements the `preflight`, `status`, `plan`, `run-once` and `run` commands |
| Queue/status state | `.ai/project_state.json` | controller-owned | The only mutable source the console renders |
| Task blueprint | `docs/NEWAPP_TASKS_V1.yaml` | immutable | Task ids, titles and the dependency graph |
| Policy | `.ai/agent_config.yaml` | yes | Allowed/protected paths, Human Gates, rolling-queue policy |
| Audit trail | `.ai/audit.jsonl` | controller-owned | Append-only record of every control-plane decision |

Running `start_agent.bat` without arguments starts the unattended rolling mode; explicit commands are
forwarded unchanged, so `start_agent.bat status` and `start_agent.bat preflight` behave exactly like
the underlying controller commands.

## 2. What the console reports

| The operator needs | Where it comes from | Read-only |
| --- | --- | --- |
| Git facts (repository present, baseline commit, branch, clean tree, tracked files) | `preflight` (`git rev-parse`, `git status`, `git ls-files`) | yes |
| Current task, phase, blockers, last validation, last run | `status` (`.ai/project_state.json`) | yes |
| Rolling task pool (planned tasks, pending reviews, target size, poll interval) | `status` (blueprint + `.ai/brain/decisions/**` + policy) | yes |
| Queue head and the reason the queue is waiting | `status` (controller queue policy) | yes |
| Environment readiness by key **name** only (configured/missing counts) | `preflight` (`.env` key names, never values) | yes |
| GitHub relay reachability through the Git remote | `preflight` | yes |

Every console command prints one JSON document and exits `0` on success, so both the DOS window and
automation can consume the same output.

## 3. Guarantees proven by tests

`python -m unittest discover -s tests/console -p "test_*.py"` (26 tests) proves:

1. **Starts from the repository root** — the launcher changes to `%~dp0` before doing anything else
   and forwards explicit arguments (`%*`) to the controller with the exit code propagated.
2. **Machine-readable state** — `status` returns parseable JSON containing `project_state`,
   `queue_head`, `queue_reason`, `rolling_queue` and one row per blueprint task, and the embedded
   `project_state` is byte-equal to `.ai/project_state.json`.
3. **Read-only by default** — `preflight(write_state=False)` is the default signature, `status`
   leaves `.ai/project_state.json` and `.ai/audit.jsonl` unchanged, and the snapshot helper writes
   nothing into `.ai/generated/**`.
4. **Blockers are surfaced** — a synthetic state that is blocked, paused or holds a failed task
   produces matching blocker lines, the phase, the current task and the last-validation summary.
5. **Rolling-queue semantics** — a task in `awaiting_review` does not globally block an unrelated
   task whose declared dependencies are `completed`, while `executing`/`code_ready`/`validating`
   keep the queue exclusive, and a fully completed blueprint reports `queue_empty`.
6. **Secret safety** — the rendered status snapshot contains no value read from `.env` (checked
   against the local file in memory, reporting only variable *names*) and passes the reviewed
   NEWAPP-001 content rules.

## 4. Secret rules for console output

- `.env` stays local, ignored and untracked. Only key **names** and presence counts may be printed.
- The status snapshot does not read `.env` at all; preflight reports `missing_keys` as names.
- Generated evidence may contain task ids, statuses, counts, repository-relative paths and hashes —
  never a credential value, connection string, token or signing key.
- Console and evidence output is routed through the controller's redaction before being logged.

## 5. Rolling-queue rule displayed by the console

```text
completed dependency          -> the dependent task may run
awaiting_review / awaiting_brain / awaiting_human / blocked / failed
                              -> reported as a wait state, does not block unrelated work
executing / code_ready / validating
                              -> exclusive: no second executor starts
Human Gate task (high risk or shared database structure)
                              -> stops at the gate until a local approval record exists
```

GPT remains the only plan and completion authority: the console reports state, and only a final
file-backed GPT decision moves a task to `completed`.

## 6. Reproduce the checks

```powershell
cd D:\VSCodeProject\NEWAPP
.venv\Scripts\python.exe -m unittest discover -s tests\console -p "test_*.py"
.venv\Scripts\python.exe tests\console\status_snapshot.py
.venv\Scripts\python.exe tests\console\status_snapshot.py --json
.venv\Scripts\python.exe tests\baseline\secret_scan.py --json
start_agent.bat status
start_agent.bat preflight
```

`status_snapshot.py` writes nothing unless `--write --report <path>` is supplied; it then writes one
atomic JSON file and exits `0` only when every verification flag is `true`, `1` when a check or the
secret guard fails and `2` when a source cannot be read.

## 7. Machine-readable evidence

| Artifact | Content |
| --- | --- |
| `.ai/generated/NEWAPP-006-status-console.json` | Point-in-time status snapshot plus `verification`, `verification_summary`, `queue_semantics`, `unresolved_issues` and `limitations` |
| `docs/CONSOLE_STATUS_CONTRACT.md` | This contract (stable, value-free) |
| `tests/console/status_snapshot.py` | Read-only snapshot/report helper reused by the tests |
| `tests/console/test_status_console.py` | The 26 contract tests |

The generated artifact is evidence only. It never contains `.env` values, and its secret guard lists
offending variable **names**, never values.

## 8. Observations for the controller and GPT

These points need a protected-path change and are therefore reported, not edited, by the executor:

1. The `status` command prints phase, current task, blockers and last validation but not Git facts;
   Git facts are printed by `preflight`. Adding them to `status` requires editing
   `.ai/controller/agent_loop.py`. Until then the read-only helper in `tests/console/` renders the
   combined view for verification.
2. `.ai/agent_config.yaml` defines no `validation.task_commands` entry for NEWAPP-006, so controller
   `safe` validation runs `compileall` only. A controller/GPT decision could add
   `{python} -m unittest discover -s tests/console -p "test_*.py"` for this task id.
3. `.github/workflows/**` is a protected path, so the new console tests are not wired into the
   control-plane workflow by this task.

## 9. Limitations

- Facts are point-in-time: branch, head commit, tracked-file count and queue state change while the
  rolling controller keeps running.
- The secret check covers the generated snapshot text plus values present in the local `.env`; the
  whole-repository tracked-file scan remains `tests/baseline/secret_scan.py`.
- Behavioural checks are fixture based: they drive the controller's own queue policy with synthetic
  states and never start a second controller or executor.
- A shared database structure change still requires a recorded Human Gate approval; the console only
  reports that a gate is waiting.
