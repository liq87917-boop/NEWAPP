# NEWAPP configuration contract (value-free environment inspection)

Task **NEWAPP-002 — Inspect existing .env configuration contract safely**, phase P0, depends on `NEWAPP-001`.

- Planning and final acceptance authority: GPT brain (Codex desktop / ChatGPT mobile Remote).
- Generator: `tests/config/env_contract.py --write`, run by newapp_executor (Cline/DeepSeek).
- Machine-readable artifact: `.ai/generated/NEWAPP-002-env-contract.json`.
- Generated at: `2026-09-23T11:48:40.848175Z` — status: `evidence_collected`.
- This document and the JSON report are evidence only; GPT review decides completion.

## 1. Scope and safety boundary

The contract records key **names**, group ids and configured/empty booleans from the local environment file `.env`. No value is recorded and the file is never modified.

| Property | Observation |
| --- | --- |
| Environment file label | `.env` |
| Present locally | yes |
| Ignored by Git | yes |
| Tracked by Git | no |
| Opened read-only | yes |
| Unchanged after collection | yes |
| Git status unchanged | yes |
| Values recorded | none |
| Values hashed | none |
| Assignment lines reproduced | none |
| Key names recorded | 6 |
| Parsed assignment lines | 6 |
| Malformed lines | 0 |
| Comment lines | 6 |
| Blank lines | 4 |

## 2. Binding rules for the shared NEWERP/NEWAPP platform

- NEWAPP and NEWERP share one SQL Server database, one OSS and one master-data set; NEWAPP adds no second customer/supplier master-data store.
- No NEWAPP/NEWERP synchronization service is introduced by this task or by the configuration contract.
- Database and OSS access stays behind the NEWAPP server API/worker: no mobile client (Flutter or ArkTS) holds those names' values and no mobile client connects directly to SQL Server.
- Existing key names are neither renamed nor overwritten by automation; where a name differs from a code default, a ConfigMapping layer is added instead of renaming a user secret.

Observed ASP.NET Core environment-variable convention: the application prefix 'ERP_' is removed and the '__' hierarchy separator becomes ':'.

## 3. Key groups

### database — Shared SQL Server database

Consumer: NEWAPP server API / worker only. Declared in the controller policy: yes.

Names expected by the policy: `ERP_ConnectionStrings__Default`

| Name | State | Configuration key | Consumer |
| --- | --- | --- | --- |
| `ERP_ConnectionStrings__Default` | configured | `ConnectionStrings:Default` | NEWAPP server API / worker only |

Missing from this group: none

### oss — Shared OSS object storage

Consumer: NEWAPP server API / worker only. Declared in the controller policy: yes.

Names expected by the policy: `ERP_Oss__Endpoint`, `ERP_Oss__Bucket`, `ERP_Oss__AccessKeyId`, `ERP_Oss__AccessKeySecret`

| Name | State | Configuration key | Consumer |
| --- | --- | --- | --- |
| `ERP_Oss__AccessKeyId` | configured | `Oss:AccessKeyId` | NEWAPP server API / worker only |
| `ERP_Oss__AccessKeySecret` | configured | `Oss:AccessKeySecret` | NEWAPP server API / worker only |
| `ERP_Oss__Bucket` | configured | `Oss:Bucket` | NEWAPP server API / worker only |
| `ERP_Oss__Endpoint` | configured | `Oss:Endpoint` | NEWAPP server API / worker only |

Missing from this group: none

### auth — Authentication and token signing

Consumer: NEWAPP server API / worker only. Declared in the controller policy: yes.

Names expected by the policy: `ERP_Jwt__Key`

| Name | State | Configuration key | Consumer |
| --- | --- | --- | --- |
| `ERP_Jwt__Key` | configured | `Jwt:Key` | NEWAPP server API / worker only |

Missing from this group: none

### ai_provider — AI provider

Consumer: NEWAPP server API / AI worker only. Declared in the controller policy: no.

No name in the current environment file belongs to this group.

Missing from this group: none

### application — Application settings (not credentials)

Consumer: NEWAPP server configuration. Declared in the controller policy: no.

No name in the current environment file belongs to this group.

Missing from this group: none

## 4. Binding map

| Name | Group | Configuration key | Consumer |
| --- | --- | --- | --- |
| `ERP_ConnectionStrings__Default` | database | `ConnectionStrings:Default` | NEWAPP server API / worker only |
| `ERP_Jwt__Key` | auth | `Jwt:Key` | NEWAPP server API / worker only |
| `ERP_Oss__AccessKeyId` | oss | `Oss:AccessKeyId` | NEWAPP server API / worker only |
| `ERP_Oss__AccessKeySecret` | oss | `Oss:AccessKeySecret` | NEWAPP server API / worker only |
| `ERP_Oss__Bucket` | oss | `Oss:Bucket` | NEWAPP server API / worker only |
| `ERP_Oss__Endpoint` | oss | `Oss:Endpoint` | NEWAPP server API / worker only |

## 5. Missing, empty and unknown names (report only)

- Missing names: none
- Empty-value names: none
- Names without a group match: none
- Duplicate names: none
- Malformed parsed lines: 0

Nothing in this section is written back: no name is added, renamed, normalized or removed by automation, and a repair stays a GPT/human decision.

## 6. Value-free guarantees

Self-check status: `passed` — findings: 0.

Rules applied: `key_name_assignment`, `keyword_assignment`.

- Only key names, group ids, booleans and counts are recorded; a value is read in memory solely to decide between configured and empty and is then discarded.
- No value, quote, prefix, suffix, length or hash of a value is recorded, printed, logged, stored in an exception message or compared.
- The contract describes the local environment file observed at generation time; a name added later appears only after the next run.
- A name that matches no group rule is listed by name only and is not renamed, reclassified or written back automatically.
- This document and the JSON report are evidence only; GPT review decides completion.

## 7. Reproduce

```powershell
python tests/config/env_contract.py --write
python -m unittest discover -s tests -p "test_*.py"
python tests/baseline/secret_scan.py --json
```

## 8. Controller path guard compatibility

| Executor path | Accepted by the policy |
| --- | --- |
| `.ai/generated/NEWAPP-002-env-contract.json` | yes |
| `docs/CONFIGURATION_CONTRACT.md` | yes |
| `tests/__init__.py` | yes |
| `tests/config/__init__.py` | yes |
| `tests/config/env_contract.py` | yes |
| `tests/config/test_env_contract.py` | yes |

All paths accepted: yes.

