# NEWAPP repository baseline and repository rules

Task: **NEWAPP-001 — Freeze repository baseline and secret rules** (phase P0, no dependencies).
This document and the artifacts it points at are the frozen baseline other NEWAPP tasks build on.
The GPT brain (Codex desktop / ChatGPT mobile Remote) remains the planning and final-acceptance
authority; the Cline/DeepSeek executor only implements the single task the controller hands over.

## 1. Authority of record

| Concern | Authoritative artifact |
| --- | --- |
| Task queue and dependency graph | `docs/NEWAPP_TASKS_V1.yaml` (immutable blueprint) |
| Mutable queue status, run ids, approvals | `.ai/project_state.json`, `.ai/decisions/**`, `.ai/brain/**` |
| Controller policy, allowed/protected paths, gates | `.ai/agent_config.yaml` |
| API contract | `docs/NEWAPP_OpenAPI_V1.yaml` |
| Database contract | `docs/NEWAPP_Database_DDL_V1.sql` |
| UI contract | `docs/NEWAPP_UI页面原型与交互说明_V1.0.docx` |
| Baseline evidence for this task | `.ai/generated/NEWAPP-001-baseline-report.json` with the byte-identical mirror `docs/NEWAPP-001-baseline-report.json` |

Branch names, commit ids, file counts and hashes are deliberately **not** copied into this document;
the generated report carries those values so this file cannot drift from the repository state.

## 2. Secret rules (required for every task)

1. `.env`, `agent.env`, connection strings, tokens, signing files and cloud credentials are secrets.
   Never print, copy, hash, diff, screenshot, log or commit their values.
2. `.env` stays present locally, ignored and untracked. Only key **names** and presence may be
   reported; values stay in the local file and in process memory.
3. Generated signing material (`*.pfx`, `*.p12`, `*.jks`, `*.keystore`, `*.pem`, `*.key`,
   `*.mobileprovision`, `*.ppk`, `*.p8`) never enters the repository.
4. Temporary exports stay untracked (`exports/`, `temp/`, `secrets/`).
5. Evidence, reports and logs may contain booleans, counts, hashes and repository-relative paths,
   never credential material.
6. No mobile client may hold database or OSS credentials or connect directly to SQL Server. Database
   and OSS access belongs behind the NEWAPP server API.
7. NEWAPP and NEWERP share one SQL Server database, one OSS and one master-data set. Do not create a
   second customer/supplier master store and do not build a NEWAPP/NEWERP synchronization bridge.
8. `DROP`, `TRUNCATE`, destructive migrations, production DDL/DML, deployments, releases, signing and
   production-data tests are out of scope even with an approval. Shared database structure changes
   stop at the Human Gate declared by the controller.

## 3. Repository rules: GPT brain / executor separation

These rules are normative for the repository and are enforced by the files in the same table.

| Rule | Enforced or recorded in |
| --- | --- |
| GPT is the only planning and final-acceptance brain; the local controller never calls an OpenAI API | `.ai/BRAIN_RULES.md`, `.ai/agent_config.yaml` (`brain.mode`) |
| The executor implements exactly one controller-approved task and never selects, skips, reorders or completes tasks | `.clinerules`, `.ai/EXECUTOR_RULES.md`, `.ai/controller/**` |
| A successful executor process means `code_ready` only; validation, evidence and GPT review decide completion | `.ai/EXECUTOR_RULES.md`, `.ai/project_state.json` |
| The executor must not modify the blueprint, controller, configuration, queue state, approvals or `.clinerules` | `.clinerules`, `.ai/agent_config.yaml` (`paths.protected`) |
| Commits, pushes, merges and checkpoints are controller-owned; the executor reports and stops | `.ai/EXECUTOR_RULES.md`, `.ai/controller/git_manager.py` |
| CI compiles the controller, runs the controller contract tests and rejects tracked secret files | `.github/workflows/control-plane.yml` |

## 4. Repeatable secret guard

| Check | Command | Meaning of the result |
| --- | --- | --- |
| Tracked-file secret scan | `python tests/baseline/secret_scan.py` | exit code 0 = no credential-like finding; exit code 1 = findings listed as rule, path and line only; exit code 2 = scanner error |
| Baseline report | `python tests/baseline/repository_baseline.py --write --report .ai/generated/NEWAPP-001-baseline-report.json --report docs/NEWAPP-001-baseline-report.json ...` | refreshes both artifacts and exits non-zero when an acceptance criterion is unmet |
| Baseline unit tests | `python -m unittest discover -s tests -p "test_*.py"` | disposable temporary directories only; no network, database, OSS or `.env` access |

The exact regeneration command for this task, including the candidate paths that are checked against the
controller allowed-path patterns, is:

```
python tests/baseline/repository_baseline.py --write \
    --report .ai/generated/NEWAPP-001-baseline-report.json \
    --report docs/NEWAPP-001-baseline-report.json \
    --executor-file docs/REPOSITORY_BASELINE.md \
    --executor-file tests/__init__.py \
    --executor-file tests/baseline/__init__.py \
    --executor-file tests/baseline/secret_scan.py \
    --executor-file tests/baseline/repository_baseline.py \
    --executor-file tests/baseline/test_secret_scan.py \
    --executor-file tests/baseline/test_repository_baseline.py
```

The scanner reads Git tracked files only, reports nothing but rule id, repository-relative path and
line number, and never echoes a matched value. Ignored local files such as `.env` are out of scope
because they must never be committed; a tracked credential file is reported by path name instead.

## 5. Controller path guard compatibility (resolved)

The GPT plan for NEWAPP-001 requires the baseline artifact under `.ai/generated/`, and
`.ai/generated/**` is listed in `paths.executor_allowed`. The controller path guard accepts
dot-directory paths, so the plan-required artifact validates:

* `common.path_matches` normalizes with `path.replace("\\", "/")` and removes only **exact** leading
  `./` prefixes, one prefix at a time, before `fnmatch`. The leading dot of `.ai/`, `.github/` and
  `.gitignore` is preserved, so `.ai/generated/NEWAPP-001-baseline-report.json` matches
  `.ai/generated/**`, `.github/workflows/control-plane.yml` matches `.github/**`, and `./docs/x.md`
  matches `docs/**` and `*.md`.
* An earlier controller revision normalized with `lstrip("./")`, which also removed the leading dot of
  dot-directories. That revision reported the artifact under `outside_allowed_paths` and left a
  controller-owner entry in `unresolved_issues`. The controller replaced the normalization, and this
  revision removed that stale entry and its wording from both reports.
* The regenerated reports record `path_guard_compatibility.all_paths_accepted = true` with
  `unresolved_issues = []`, covering the artifact itself, this document and every file under
  `tests/`.

`tests/baseline/repository_baseline.py` mirrors the corrected normalization in
`normalize_for_path_guard`; `tests/baseline/test_repository_baseline.py` loads
`.ai/controller/common.py` read-only and asserts that the mirror and `common.path_matches` return the
same verdict for dot-directory, `./`-prefixed, backslash-separated and out-of-pattern paths. The
executor never edits controller code. Both report targets receive identical bytes: the GPT plan
artifact at `.ai/generated/NEWAPP-001-baseline-report.json` and the mirror at
`docs/NEWAPP-001-baseline-report.json`.

## 6. Known limits of the guard

* Pattern scanning cannot detect a high-entropy secret that has no keyword, no known credential
  prefix and no credential-like file name.
* Binary files and files above the scanner size limit are reported by name and not parsed.
* Template references and documentation placeholders (`${VAR}`, `{{ name }}`, `{name}`,
  `<placeholder>`, `string`, `change-me`, `example-*`) are intentionally not reported as credentials.
* Keyword assignments shorter than eight characters are treated as placeholders, not secrets.
