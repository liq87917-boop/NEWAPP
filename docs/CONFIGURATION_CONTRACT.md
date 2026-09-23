# NEWAPP local configuration contract

Task: **NEWAPP-002 - Inspect existing .env configuration contract safely** (phase P0, depends on NEWAPP-001).

This document is generated from the same value-free facts as `.ai/generated/NEWAPP-002-env-contract.json`, so regenerate it with `tests/config/env_contract.py` instead of editing it by hand.

Generated at 2026-09-23T12:18:05.082505Z UTC by newapp_executor (Cline/DeepSeek). Completion authority: the GPT brain (Codex desktop / ChatGPT mobile Remote) review, never the executor.

## 1. Authority of record

| Concern | Authoritative artifact |
| --- | --- |
| Locally declared key names | `.env` (ignored, untracked, never committed) |
| Required key groups | `.ai/agent_config.yaml#environment.required_key_groups` |
| Machine-readable facts | `.ai/generated/NEWAPP-002-env-contract.json` |
| Controller allowed paths | `.ai/agent_config.yaml#paths.executor_allowed` |
| Task definition | `docs/NEWAPP_TASKS_V1.yaml#NEWAPP-002` |

## 2. Safety contract for this report

1. Only key names, declaration line numbers, counts and two value shape flags are recorded.
2. The right-hand side text never leaves the parser: it is not returned, stored, compared with another file or key, hashed, printed, logged nor copied into evidence.
3. `.env` is opened read-only. Environment file written: no. Write timestamp unchanged across the run: yes.
4. No database, OSS, AI-provider or network call is made by this report.
5. Both artifacts are re-checked with the project scanner `tests/baseline/secret_scan.py` before they are written, so flagged text is never produced.

## 3. Local environment file facts

| Fact | Value |
| --- | --- |
| Path label | `.env` |
| Present locally | yes |
| Read only | yes |
| Byte count | 669 |
| Line count | 16 |
| Declarations | 6 |
| Comment lines | 6 |
| Blank lines | 4 |
| Malformed line numbers | none |
| Duplicate declarations | none |
| Empty right-hand sides | none |
| Quoted right-hand sides | 0 |
| Export-prefixed names | none |
| Values recorded | no |

## 4. Declared key names

| Key name | Category | Line | Configured | Duplicate | Export prefixed |
| --- | --- | --- | --- | --- | --- |
| `ERP_ConnectionStrings__Default` | Database | 6 | yes | no | no |
| `ERP_Jwt__Key` | Authentication | 9 | yes | no | no |
| `ERP_Oss__AccessKeyId` | Shared OSS | 12 | yes | no | no |
| `ERP_Oss__AccessKeySecret` | Shared OSS | 13 | yes | no | no |
| `ERP_Oss__Bucket` | Shared OSS | 14 | yes | no | no |
| `ERP_Oss__Endpoint` | Shared OSS | 15 | yes | no | no |

## 5. Category summary

| Category | Count | Key names |
| --- | --- | --- |
| database | 1 | ERP_ConnectionStrings__Default |
| oss | 4 | ERP_Oss__AccessKeyId, ERP_Oss__AccessKeySecret, ERP_Oss__Bucket, ERP_Oss__Endpoint |
| auth | 1 | ERP_Jwt__Key |
| ai_provider | 0 | none |
| application | 0 | none |
| unknown | 0 | none |

## 6. Required key groups and missing-key report

Source: `.ai/agent_config.yaml#environment.required_key_groups`. Available: yes.

| Group | Required | Present | Missing | Empty | All present |
| --- | --- | --- | --- | --- | --- |
| auth | ERP_Jwt__Key | ERP_Jwt__Key | none | none | yes |
| database | ERP_ConnectionStrings__Default | ERP_ConnectionStrings__Default | none | none | yes |
| oss | ERP_Oss__Endpoint, ERP_Oss__Bucket, ERP_Oss__AccessKeyId, ERP_Oss__AccessKeySecret | ERP_Oss__Endpoint, ERP_Oss__Bucket, ERP_Oss__AccessKeyId, ERP_Oss__AccessKeySecret | none | none | yes |

Required names: 6. Present: 6. Missing: 0. Declared but empty: 0.
Every required name present and non-empty: yes.

## 7. Configuration binding map

| Key name | Category | Bound to | Consumed by | Client exposure | Present locally |
| --- | --- | --- | --- | --- | --- |
| `ERP_ConnectionStrings__Default` | database | NEWAPP server API data access layer, pointing at the shared NEWERP SQL Server database | server side only | forbidden | yes |
| `ERP_Oss__Endpoint` | oss | NEWAPP server object-storage client endpoint for the shared NEWERP bucket | server side only | forbidden | yes |
| `ERP_Oss__Bucket` | oss | the single shared NEWERP bucket used for inquiry attachments and generated exports | server side only | forbidden | yes |
| `ERP_Oss__AccessKeyId` | oss | server-side OSS credential identifier, identical to the NEWERP deployment | server side only | forbidden | yes |
| `ERP_Oss__AccessKeySecret` | oss | server-side OSS credential material, never issued to a mobile build | server side only | forbidden | yes |
| `ERP_Jwt__Key` | auth | NEWAPP server API token issuing and validation | server side only | forbidden | yes |

Declared names without a binding entry in this task: none.
Required names missing locally: none.

## 8. Platform binding rules for NEWAPP and NEWERP

1. NEWAPP and NEWERP share one SQL Server database, one OSS bucket and one master-data set. This task adds no second database, bucket or customer/supplier master store.
2. No NEWAPP/NEWERP data synchronisation service is introduced. Both applications use the shared database and the shared OSS directly on the server side.
3. A mobile client never connects to SQL Server and never embeds OSS credentials, a database connection string, token signing material or any other long-lived secret. All such access stays behind the NEWAPP server API.
4. An existing key is never renamed or overwritten. A rotated secret is introduced by adding a new key name, keeping the previous name until the server deployment has moved over, and removing the old name only through a GPT plan decision and any Human Gate the controller requires.
5. The executor reports this contract; it does not edit queue state, approvals, controller code or the task blueprint.

## 9. Generated artifact checks

| Check | Result |
| --- | --- |
| Report status | evidence_collected |
| Report value guard | passed |
| Documentation value guard | passed |
| Assignment characters in the report | 0 |
| Key names checked against the name character set | 6 |
| Repository scanner findings | 0 |
| Artifact checks verified | yes |

## 10. Generated artifact path guard

Allowed pattern source: `.ai/agent_config.yaml#paths.executor_allowed`.

| Executor path | Accepted | Matched allowed patterns |
| --- | --- | --- |
| `.ai/generated/NEWAPP-002-env-contract.json` | yes | .ai/generated/** |
| `docs/CONFIGURATION_CONTRACT.md` | yes | docs/**, *.md |
| `tests/config/__init__.py` | yes | tests/** |
| `tests/config/env_contract.py` | yes | tests/** |
| `tests/config/test_env_contract.py` | yes | tests/** |

Every recorded executor path accepted: yes.
Protected paths touched: none.
Protected patterns compared: 19.

## 11. Acceptance evidence

| Acceptance criterion | Satisfied | Evidence |
| --- | --- | --- |
| Evidence contains key names only, with all values redacted. | yes | the value guard over both rendered artifacts (no assignment character, no declared key name followed by an assignment delimiter, every recorded name matching the key name character set) plus the repository scanner content rules |
| No existing .env key is renamed or overwritten. | yes | the environment file is opened read-only, its write timestamp and byte count are unchanged across the run, tests/config/test_env_contract.py asserts byte-identical content around the parse on a disposable fixture, and the real local file is re-checked as ignored and untracked by git |
| A configured/missing key report exists for every controller required key group. | yes | required key groups from the controller configuration compared with declared names |
| Generated artifacts stay inside the executor allowed paths and no protected path is touched. | yes | controller path guard mirror over every executor path recorded by this report, plus the protected pattern list read from the controller configuration |

## 12. Regeneration

```
python tests/config/env_contract.py --write --report .ai/generated/NEWAPP-002-env-contract.json --markdown docs/CONFIGURATION_CONTRACT.md --executor-file tests/config/__init__.py --executor-file tests/config/env_contract.py --executor-file tests/config/test_env_contract.py
```

Both artifacts are written atomically and are re-checked before writing; the JSON report and this document are rendered from the same facts, so they cannot drift apart.

Local environment file inspected: `.env` with 6 declarations.

Executor paths recorded for this task: .ai/generated/NEWAPP-002-env-contract.json, docs/CONFIGURATION_CONTRACT.md, tests/config/__init__.py, tests/config/env_contract.py, tests/config/test_env_contract.py.

## 13. Known limits

- Only key names, declaration line numbers, counts and two value shape flags are recorded, so this report cannot prove that a configured value is valid, reachable or correctly scoped.
- Classification is derived from key-name shapes, so a name that does not describe its service is reported under application settings or unknown.
- The read side of the shared services is out of scope here: NEWAPP-003 owns read-only database metadata and NEWAPP-004 owns the OSS key-prefix contract.
- The environment file is read on a single local checkout, so another developer machine may declare additional or missing names.
- agent.env, secrets, signing files and cloud credential files are never opened by this module.

