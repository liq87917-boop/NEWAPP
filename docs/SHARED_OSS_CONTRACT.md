# NEWAPP shared OSS contract

Task: **NEWAPP-004 - Inspect shared OSS contract** (phase P0, depends on NEWAPP-002).

This document is generated from the same value-free facts as `.ai/generated/NEWAPP-004-oss-contract.json`, so regenerate it with `tests/oss/oss_contract.py` instead of editing it by hand.

Generated at 2026-09-24T12:06:31.636168Z UTC by newapp_executor (Cline/DeepSeek). Completion authority: the GPT brain (Codex desktop / ChatGPT mobile Remote) review, never the executor.

## 1. Authority of record

| Concern | Authoritative artifact |
| --- | --- |
| Shared OSS declaration names | `.env` (ignored, untracked, never committed) |
| Controller-required OSS names | `.ai/agent_config.yaml#environment.required_key_groups` |
| Shared asset metadata | `docs/NEWAPP_Database_DDL_V1.sql` (declared, not applied by this task) |
| Client file-access boundary | `docs/NEWAPP_OpenAPI_V1.yaml` |
| Machine-readable facts | `.ai/generated/NEWAPP-004-oss-contract.json` |
| Controller allowed paths | `.ai/agent_config.yaml#paths.executor_allowed` |
| Task definition | `docs/NEWAPP_TASKS_V1.yaml#NEWAPP-004` |

## 2. Safety contract for this report

1. Only OSS key names, presence booleans, declaration line numbers, counts, one provider family label and endpoint/bucket shape flags are recorded.
2. The endpoint text is inspected inside one function to derive those shape flags and the family label, then discarded. The bucket name and the credential material are never returned, stored, compared with another file or key, hashed, printed, logged nor copied into evidence.
3. `.env` is opened read-only. Environment file written: no. Write timestamp unchanged across the run: yes.
4. No OSS, database, AI-provider or network call is made: the shared bucket is never contacted, and an object is never uploaded, listed or deleted by this task.
5. Both artifacts are re-checked with the reused NEWAPP-002 value guard and with the project scanner `tests/baseline/secret_scan.py` before they are written, and they are written only while the report status stays `evidence_collected`.

## 3. Provider and endpoint configuration

| Fact | Value |
| --- | --- |
| Declared OSS key names | 4 |
| Provider identification method | endpoint host suffix compared with the documented provider suffix list of this module; only the family label and a boolean are recorded, never the endpoint text |
| Documented provider suffix families | 6 |
| Provider family label | aliyun_oss |
| Provider suffix matched | yes |
| Endpoint declared | yes |
| Endpoint configured | yes |
| Endpoint uses a scheme | no |
| Endpoint uses a secure scheme | no |
| Endpoint has an explicit port | no |
| Endpoint host label count | 3 |
| Endpoint looks like an IPv4 literal | no |
| Endpoint text recorded | no |
| Bucket name recorded | no |
| Credential material read | no |

Provider family of an endpoint whose host suffix is not in the documented list: `unrecognised`.

| Key name | Line | Configured | Quoted | Duplicate | Export prefixed |
| --- | --- | --- | --- | --- | --- |
| `ERP_Oss__AccessKeyId` | 12 | yes | no | no | no |
| `ERP_Oss__AccessKeySecret` | 13 | yes | no | no | no |
| `ERP_Oss__Bucket` | 14 | yes | no | no | no |
| `ERP_Oss__Endpoint` | 15 | yes | no | no | no |

Declared OSS declarations: 4.
Duplicate OSS declaration names: none.
Controller-required OSS names: ERP_Oss__Endpoint, ERP_Oss__Bucket, ERP_Oss__AccessKeyId, ERP_Oss__AccessKeySecret.
Present: ERP_Oss__Endpoint, ERP_Oss__Bucket, ERP_Oss__AccessKeyId, ERP_Oss__AccessKeySecret. Missing: none. Declared but empty: none.
Every expected OSS name present and non-empty: yes.

## 4. Shared bucket policy

| Fact | Value |
| --- | --- |
| Shared bucket count | 1 |
| Second bucket created | no |
| Synchronisation service created | no |
| Bucket column optional in the asset table | yes |
| Configured bucket is the default | yes |

Boundary summary: NEWAPP reuses the single shared bucket, so there is no second NEWAPP bucket, no NEWAPP-only object store and no NEWAPP/NEWERP object synchronisation service. The rules of that boundary are listed in section 7.

## 5. Discovered object-key evidence in this checkout

### 5.1 Declared shared asset metadata

| Fact | Value |
| --- | --- |
| DDL path | `docs/NEWAPP_Database_DDL_V1.sql` |
| DDL available | yes |
| DDL line count | 476 |
| Asset table | `app.FileAsset` |
| Asset table definition lines | 104 to 129 |
| Declared table count in the DDL | 20 |
| Any DDL executed by this task | no |
| Applying the DDL still needs a Human Gate | yes |

| Column | Declared type | Length | Nullability | Line |
| --- | --- | --- | --- | --- |
| `Purpose` | NVARCHAR | 32 | NOT NULL | 109 |
| `ObjectKey` | NVARCHAR | 600 | NOT NULL | 110 |
| `Bucket` | NVARCHAR | 160 | NULL | 111 |
| `UploadStatus` | TINYINT | unspecified | NOT NULL | 119 |

| Unique constraint | Table | Columns | Line |
| --- | --- | --- | --- |
| `UQ_app_FileAsset_Object` | `app.FileAsset` | TenantId, ObjectKey | 125 |

| Foreign key | Owning table | Columns | References | Line |
| --- | --- | --- | --- | --- |
| `FK_app_CustomerExt_Photo` | `app.CustomerExt` | PhotoAssetId | `app.FileAsset` | 146 |
| `FK_app_SupplierExt_Card` | `app.SupplierExt` | BusinessCardAssetId | `app.FileAsset` | 165 |
| `FK_app_InquiryItemImage_Asset` | `app.InquiryItemImage` | AssetId | `app.FileAsset` | 277 |
| `FK_app_AIJob_Asset` | `app.AIJob` | AssetId | `app.FileAsset` | 342 |
| `FK_app_ExportJob_Asset` | `app.ExportJob` | ResultAssetId | `app.FileAsset` | 383 |

Declared upload status tokens: pending, ready, failed, deleted.

### 5.2 Declared client file-access boundary

| Fact | Value |
| --- | --- |
| API contract path | `docs/NEWAPP_OpenAPI_V1.yaml` |
| API contract available | yes |
| Upload ticket path | `/files/upload-ticket` |
| Upload ticket line | 434 |
| Upload request required fields | purpose, fileName, contentType, sha256 |
| Declared asset purpose tokens | product, customer_photo, business_card, export_attachment, diagnostic_log |
| Asset purpose line | 447 |
| Ticket schema name | `UploadTicket` |
| Ticket required fields | assetId, uploadUrl, expiresAt |
| Ticket property names | assetId, uploadUrl, method, headers, objectKey, expiresAt |
| Ticket credential fields | none |
| Any request sent by this task | no |

Declared file paths of the contract: /files/upload-ticket, /files/{assetId}/complete.

Declared download paths: none. Until a download path is declared, a client reads an asset back through the API rather than through a bucket URL of its own.

A ticket that carried a credential field would be reported in the credential fields row above instead of being discovered at runtime. The ticket hands the client a server-side signed, short-lived upload ticket only, so the client never receives the OSS credential material.

## 6. Convention search results and reference-tree discovery

| Fact | Value |
| --- | --- |
| Searched file suffixes | .md, .yaml, .yml, .json, .sql, .py, .cs, .ts, .dart, .txt |
| Excluded directory prefixes | .git/, .venv/, .ai/logs/, .ai/evidence/, .ai/brain/, .ai/decisions/, .ai/locks/, .ai/controller/, __pycache__/, node_modules/, bin/, obj/ |
| Excluded paths owned by this task | .ai/generated/NEWAPP-004-oss-contract.json, docs/SHARED_OSS_CONTRACT.md |
| Search size limit | 2000000 |
| Files searched | 39 |
| Files skipped | 2 |
| Matched text recorded | no |

| Pattern | Meaning | Matches | Files |
| --- | --- | --- | --- |
| `object_key_field` | declared object-key column or field | 26 | .ai/generated/NEWAPP-003-newerp-schema-map.json, docs/NEWAPP_Database_DDL_V1.sql, docs/NEWAPP_OpenAPI_V1.yaml, docs/NEWERP_SCHEMA_MAP.md, tests/oss/oss_contract.py, tests/oss/test_oss_contract.py |
| `bucket_field` | declared bucket column or field | 91 | .ai/generated/NEWAPP-002-env-contract.json, docs/CONFIGURATION_CONTRACT.md, docs/NEWAPP_Database_DDL_V1.sql, docs/NEWAPP_TASKS_V1.yaml, tests/baseline/test_secret_scan.py, tests/config/env_contract.py, tests/config/test_env_contract.py, tests/oss/oss_contract.py, tests/oss/test_oss_contract.py, tests/schema/newerp_schema.py, tests/schema/test_newerp_schema.py |
| `purpose_field` | declared asset purpose or classification field | 26 | docs/NEWAPP_Database_DDL_V1.sql, docs/NEWAPP_OpenAPI_V1.yaml, tests/oss/oss_contract.py, tests/oss/test_oss_contract.py |
| `tenant_scope_field` | tenant scoping used on asset rows | 60 | .ai/generated/NEWAPP-003-newerp-schema-map.json, docs/NEWAPP_Database_DDL_V1.sql, docs/NEWAPP_OpenAPI_V1.yaml, docs/NEWAPP_TASKS_V1.yaml, docs/NEWERP_SCHEMA_MAP.md, tests/oss/oss_contract.py, tests/oss/test_oss_contract.py, tests/schema/newerp_schema.py, tests/schema/test_newerp_schema.py |
| `upload_ticket_boundary` | short-lived signed upload boundary | 23 | docs/NEWAPP_OpenAPI_V1.yaml, tests/oss/oss_contract.py, tests/oss/test_oss_contract.py |
| `credential_name` | long-lived credential key names | 51 | .ai/agent_config.yaml, .ai/generated/NEWAPP-002-env-contract.json, .ai/generated/NEWAPP-006-status-console.json, docs/CONFIGURATION_CONTRACT.md, docs/NEWAPP_TASKS_V1.yaml, docs/README_交付与启动说明.md, tests/baseline/secret_scan.py, tests/baseline/test_secret_scan.py, tests/config/env_contract.py, tests/config/test_env_contract.py, tests/oss/oss_contract.py, tests/oss/test_oss_contract.py |
| `key_prefix_token` | explicit object-key prefix token | 7 | .ai/generated/NEWAPP-002-env-contract.json, docs/CONFIGURATION_CONTRACT.md, docs/NEWAPP_TASKS_V1.yaml, tests/config/env_contract.py, tests/oss/oss_contract.py |

Total matches: 284. Files with a match: 50.

Matched text, matched key names and matched bucket names are never recorded; only pattern identifiers, counts, file paths and line numbers are.

### 6.1 Reference tree discovery

| Fact | Value |
| --- | --- |
| Mode | not_provided |
| Reason | no read-only reference tree was supplied, so an external object-key convention stays unresolved in this report |
| Reference tree label | none |
| Files searched there | 0 |
| Matches there | 0 |
| Any file written there | no |

The key convention of existing NEWERP objects is therefore an explicit unresolved item of this report, not an invented convention. When the controller supplies a read-only reference path, the same pattern set is searched there and the result is recorded by path, line number and count.

## 7. Recorded shared-OSS rules

- NEWAPP and NEWERP share one OSS bucket and one object namespace. NEWAPP never creates a second bucket, a NEWAPP-only bucket or a parallel object store.
- No NEWAPP/NEWERP object synchronisation service exists. Both applications read and write the shared bucket through this contract, and shared asset metadata lives in the shared database.
- Long-lived OSS credentials stay server side. A mobile client never receives the OSS credential material and never uploads with a long-lived key.
- The mobile client uploads with a server-side signed, short-lived upload ticket and confirms the asset afterwards, so the server remains the only issuer of object access.
- The object key is generated and owned by the server. A client-supplied file name or path is never used as the stored object key.
- app.FileAsset is the single asset record per object: the unique constraint on the tenant and the object key means one object key exists once per tenant, and the bucket column is optional so the configured shared bucket is the default.
- An existing key name is never renamed or overwritten. Rotating the shared credential is a server-side deployment action for a later task, not part of this report.
- The executor reports this contract; it does not edit queue state, approvals, controller code, the task blueprint or any OSS object.

## 8. Proposed key strategy awaiting a GPT decision

Status: `proposed_for_gpt_review_not_established_by_this_task`.

Candidate pattern label: `<purpose>/<tenantId>/<opaque-id>[.<extension>]`

Segments of the candidate:

- the declared asset purpose token as the leading classification segment
- the tenant scope
- an opaque server-generated identifier
- an optional extension token derived from the declared content type

Derived from:

- the declared asset purpose field of the shared asset table
- the tenant-scoped uniqueness of the object key
- the optional bucket column, so the configured shared bucket is the default
- the server-owned short-lived upload ticket

Rules of the candidate:

- the server builds the key; a client-supplied file name is never used as the key
- the key stays stable after upload, so an existing object is never moved or rewritten
- the key is unique per tenant, matching the declared unique constraint
- no NEWERP-written object is renamed, moved or deleted by NEWAPP

Confirmations needed before it becomes normative:

- GPT accepts this candidate layout, or replaces it with the actual NEWERP convention
- NEWAPP-010 implements the ticket issuer against the accepted layout
- a read-only inspection of an existing object namespace confirms the leading segment

Displayed as a recorded convention: no.

Notes:

- This task records the declared contract. It does not establish a new key layout and it does not change any existing object key.
- The candidate layout below is derived only from declared facts of this checkout: the asset purpose field, the tenant-scoped uniqueness of the object key, the optional bucket column and the server-owned upload ticket.
- The layout becomes normative only after GPT accepts it and NEWAPP-010 implements the ticket issuer against it. Until then NEWAPP must not rewrite, move or relocate an object written by NEWERP.
- The key convention of existing NEWERP objects is not discoverable from this checkout. If a later read-only inspection provides it, that evidence replaces this candidate layout.

## 9. Client and mobile boundary

- A mobile client calls the HTTPS API only. It never connects to SQL Server and never receives a database connection string.
- A mobile client never receives the OSS credential key or material, and never receives a ticket for another tenant or any listing permission on the shared bucket.
- Asset references travel between client and server as asset identifiers, so the client never needs the object key to read an asset back.
- Diagnostic evidence, logs and screenshots never include credential material from the environment file.

| External call | Count |
| --- | --- |
| OSS calls | 0 |
| Database connections | 0 |
| Network requests | 0 |

This task inspects this checkout only; no OSS, database or network call is made by this module or by its tests.

## 10. Artifact checks

| Check | Result |
| --- | --- |
| Report status | evidence_collected |
| Report value guard | passed |
| Documentation value guard | passed |
| Assignment characters in the report | 0 |
| Key names checked against the name character set | 6 |
| Repository scanner findings | 0 |
| Documented strategy statements | passed (11 checked, missing none) |
| Artifact checks verified | yes |

## 11. Generated artifact path guard

Allowed pattern source: `.ai/agent_config.yaml#paths.executor_allowed`.

| Executor path | Accepted | Matched allowed patterns |
| --- | --- | --- |
| `.ai/generated/NEWAPP-004-oss-contract.json` | yes | .ai/generated/** |
| `docs/SHARED_OSS_CONTRACT.md` | yes | docs/**, *.md |
| `tests/oss/__init__.py` | yes | tests/** |
| `tests/oss/oss_contract.py` | yes | tests/** |
| `tests/oss/test_oss_contract.py` | yes | tests/** |

Every recorded executor path accepted: yes.
Protected paths touched: none.
Protected patterns compared: 19.

## 12. Acceptance evidence

| Acceptance criterion | Satisfied | Evidence |
| --- | --- | --- |
| The declared OSS configuration and the declared asset/ticket contract were readable. | yes | every controller-required OSS name is present and non-empty in the environment file, and the declared app-schema DDL and API contract were found and parsed read-only |
| Shared bucket/key-prefix strategy is documented. | yes | the recorded shared-OSS rules, the shared bucket policy, the candidate key strategy marked as a proposal for GPT, and the declared asset-table and ticket facts with file and line numbers |
| No secret is printed. | yes | the reused value guard over both rendered artifacts (no assignment character, no declared key name followed by an assignment delimiter, every recorded name matching the key-name character set), the repository scanner content rules, and the explicit false flags for the endpoint text, the bucket name and the credential material |
| One shared bucket is reused and no second bucket or synchronisation layer appears. | yes | the recorded rules state one shared bucket and no synchronisation service, the configured bucket count is one, and no bucket creation or object copy is performed by this task |
| No OSS object is uploaded, listed, copied or deleted by this task. | yes | the environment file is opened read-only and its write timestamp is unchanged across the run, and no OSS client, connection or request exists in this module or its tests |
| Generated artifacts stay inside the executor allowed paths. | yes | the reused controller path-guard mirror over every executor path recorded by this report, plus the protected pattern list read from the controller configuration |

## 13. Regeneration

```
python tests/oss/oss_contract.py --write --report .ai/generated/NEWAPP-004-oss-contract.json --markdown docs/SHARED_OSS_CONTRACT.md --executor-file tests/oss/__init__.py --executor-file tests/oss/oss_contract.py --executor-file tests/oss/test_oss_contract.py
```

Both artifacts are written atomically and are re-checked before writing; the JSON report and this document are rendered from the same facts, so they cannot drift apart.

Executor paths recorded for this task: .ai/generated/NEWAPP-004-oss-contract.json, docs/SHARED_OSS_CONTRACT.md, tests/oss/__init__.py, tests/oss/oss_contract.py, tests/oss/test_oss_contract.py.

## 14. Known limits

- The provider family is inferred from the endpoint host suffix list documented in this module, so a custom domain, a masked value or an unlisted provider is reported as unrecognised rather than guessed.
- The endpoint text, the bucket name and the credential material are never recorded, so this report cannot verify which physical bucket is bound at runtime or whether it is the bucket NEWERP uses.
- The object-key convention of existing NEWERP objects is not discoverable from this checkout, so the candidate key layout stays a proposal for GPT rather than a recorded convention.
- No OSS API call is made, so bucket policy, region, lifecycle rules and object counts stay unverified.
- The environment file is read on a single local checkout, so another developer machine may declare additional or missing names.
- agent.env, secrets, signing files and cloud credential files are never opened by this module.

