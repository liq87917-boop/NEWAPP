# NEWAPP app-schema DDL reconciliation against the actual NEWERP keys

Task: **NEWAPP-005 - Reconcile DDL with actual NEWERP keys** (phase P0, depends on NEWAPP-003).

This document is generated from the same value-free facts as `.ai/generated/NEWAPP-005-ddl-reconciliation.json` and the generated draft `database/NEWAPP_app_schema_reconciled_V1.sql`, so regenerate all three with `.venv\Scripts\python.exe tests\schema\ddl_reconciliation.py --write   (add --compile in an interpreter that can import the ODBC driver module)` instead of editing them by hand.

Generated at 2026-09-24T12:17:55.431555Z by newapp_executor (Cline/DeepSeek). Completion authority: the GPT brain (Codex desktop / ChatGPT mobile Remote) review, never the executor.

## 1. Authority of record

| Concern | Authoritative artifact |
| --- | --- |
| Planned app-schema DDL contract | `docs/NEWAPP_Database_DDL_V1.sql` |
| Actual shared keys and types | `.ai/generated/NEWAPP-003-newerp-schema-map.json` (accepted NEWAPP-003 map) |
| Machine-readable facts | `.ai/generated/NEWAPP-005-ddl-reconciliation.json` |
| Generated reconciled draft | `database/NEWAPP_app_schema_reconciled_V1.sql` |
| Controller allowed paths | `.ai/agent_config.yaml#paths.executor_allowed` |
| Task definition | `docs/NEWAPP_TASKS_V1.yaml#NEWAPP-005` |
| GPT plan for this task | `.ai/brain/decisions/NEWAPP-005-plan.json` |

## 2. Safety contract for this reconciliation

1. The planned DDL contract and the accepted NEWAPP-003 map are opened read-only. No shared object was created, altered, dropped or queried and no business row was read by this task.
2. The shared connection declaration stays in memory: it is only read to prove that the optional compile target is not the shared server, the shared catalog or a declared credential, and nothing about it is recorded, hashed or rendered.
3. Declared shared connection present: yes (source label `process_environment`), value recorded: no, shared connection used: no.
4. The environment file is opened read-only and never written. Write timestamp unchanged across the run: yes.
5. A neutral key is retyped only when the accepted map records a single authoritative target column with a recorded type; a key whose target needs review keeps its neutral declaration and becomes an explicit unresolved item.
6. The generated draft contains only additive, guarded app-schema objects: 20 tables, 18 indexes, no DDL that changes an existing object, no foreign key to a shared table and no duplicate customer or supplier master table.
7. The optional compile check runs the draft on a local disposable target inside one transaction that is always rolled back. Shared objects changed: no. Draft applied by this task: no.
8. Both generated artifacts and the draft are re-checked with the credential guard, the repository scanner and the path guard before publication.

## 3. Source contracts inspected

| Fact | Value |
| --- | --- |
| Planned DDL digest | `sha256:23211dfd77dc6f9b...` |
| Accepted map digest | `sha256:20e3730c31445f1c...` |
| Planned DDL objects | 20 tables, 18 indexes, 163 columns |
| Accepted map status | `evidence_collected` (task NEWAPP-003, inspection `inspected`) |
| Accepted map tables | 74 |
| Organization/tenant domain in the accepted map | `absent_from_catalog` |
| Neutral keys declared by the contract | `ChangedByUserKey`, `CorrectedByUserKey`, `CreatedByUserKey`, `CustomerKey`, `EntityKey`, `IdempotencyKey`, `ObjectKey`, `RequestedByUserKey`, `SalesGroupKey`, `SalesUserKey`, `SubmittedByUserKey`, `SupplierKey`, `TargetGroupKey`, `TemplateKey`, `TenantId`, `UpdatedByUserKey`, `UploadedByUserKey`, `UserKey` |

## 4. Neutral key reconciliation

Every neutral key declared by the contract is classified by the rules below. A key is only raised to a shared type when the accepted map records a single authoritative target column with a recorded type; anything else keeps its neutral declaration and is listed as an unresolved item in section 12.

| Resolution | Rule |
| --- | --- |
| `resolved_direct` | Exactly one authoritative target column is recorded for the neutral key in the accepted NEWAPP-003 map, with a recorded physical type. The app column is retyped to that type and a direct foreign key or repository join is the preferred mapping. |
| `type_resolved_target_needs_review` | Every recorded candidate target shares one physical type, so the storage type is unambiguous, but the authoritative table still needs GPT review. The app column is retyped and the choice is recorded as an open review item. |
| `app_local` | The identifier is owned by NEWAPP and has no NEWERP counterpart (OSS object key, idempotency key, change-log entity key). The neutral declaration is kept and no shared mapping is claimed. |
| `unresolved_human_gate` | No authoritative target, or no recorded type, exists in the accepted map. The neutral declaration is kept, the item is recorded as unresolved and the binding stays behind the Human Gate. A type or table name is never guessed. |

| Statistic | Value |
| --- | --- |
| Classified keys | 18 |
| Resolved with a direct target | 10 |
| Type resolved, target needs review | 1 |
| App-owned identifiers | 3 |
| Unresolved behind the Human Gate | 4 |

| Neutral key | Declared | Sites | Resolution | Shared target | Recorded type | Draft type |
| --- | --- | --- | --- | --- | --- | --- |
| `CustomerKey` | `NVARCHAR(80)` | 2 | `resolved_direct` | db_owner.BaseCustomers.Id | `bigint` | `BIGINT` |
| `SupplierKey` | `NVARCHAR(80)` | 2 | `resolved_direct` | db_owner.BaseSuppliers.Id | `bigint` | `BIGINT` |
| `UserKey` | `NVARCHAR(80)` | 5 | `resolved_direct` | db_owner.SysUsers.Id | `bigint` | `BIGINT` |
| `SalesUserKey` | `NVARCHAR(80)` | 1 | `type_resolved_target_needs_review` | db_owner.SysUsers.Id, db_owner.BaseEmployees.Id | - | `BIGINT` |
| `SalesGroupKey` | `NVARCHAR(80)` | 1 | `unresolved_human_gate` | - | - | `NVARCHAR(80) (kept)` |
| `TargetGroupKey` | `NVARCHAR(80)` | 1 | `unresolved_human_gate` | - | - | `NVARCHAR(80) (kept)` |
| `TemplateKey` | `NVARCHAR(80)` | 1 | `unresolved_human_gate` | - | - | `NVARCHAR(80) (kept)` |
| `TenantId` | `UNIQUEIDENTIFIER` | 18 | `unresolved_human_gate` | - | - | `UNIQUEIDENTIFIER (kept)` |
| `ObjectKey` | `NVARCHAR(600)` | 1 | `app_local` | - | - | `NVARCHAR(600) (kept)` |
| `IdempotencyKey` | `NVARCHAR(100)` | 1 | `app_local` | - | - | `NVARCHAR(100) (kept)` |
| `EntityKey` | `NVARCHAR(120)` | 1 | `app_local` | - | - | `NVARCHAR(120) (kept)` |
| `CreatedByUserKey` | `NVARCHAR(80)` | 4 | `resolved_direct` | db_owner.SysUsers.Id | `bigint` | `BIGINT` |
| `UpdatedByUserKey` | `NVARCHAR(80)` | 2 | `resolved_direct` | db_owner.SysUsers.Id | `bigint` | `BIGINT` |
| `UploadedByUserKey` | `NVARCHAR(80)` | 1 | `resolved_direct` | db_owner.SysUsers.Id | `bigint` | `BIGINT` |
| `SubmittedByUserKey` | `NVARCHAR(80)` | 1 | `resolved_direct` | db_owner.SysUsers.Id | `bigint` | `BIGINT` |
| `RequestedByUserKey` | `NVARCHAR(80)` | 1 | `resolved_direct` | db_owner.SysUsers.Id | `bigint` | `BIGINT` |
| `CorrectedByUserKey` | `NVARCHAR(80)` | 1 | `resolved_direct` | db_owner.SysUsers.Id | `bigint` | `BIGINT` |
| `ChangedByUserKey` | `NVARCHAR(80)` | 1 | `resolved_direct` | db_owner.SysUsers.Id | `bigint` | `BIGINT` |

## 5. Mapping policy

1. Preferred mapping for a resolved key is a direct foreign key to the shared master column, or a repository join when the constraint is not approved yet.
2. A view-backed read model is an acceptable alternative mapping for an app extension table, but creating a view over a shared table is a shared-structure change, so it is recorded as a proposal instead of a generated statement.
3. No duplicate customer, supplier, user or organization master table is created: the existing NEWERP tables stay the system of record and this draft only adds app extension tables that reference them by key.
4. A key that is not confirmed by the accepted map keeps its neutral declaration, so a later shared-structure decision can bind it without rewriting an unverified type.

## 6. Generated reconciled draft

| Fact | Value |
| --- | --- |
| Draft path | `database/NEWAPP_app_schema_reconciled_V1.sql` |
| Draft digest | `sha256:3d3c7c89d7d7fedd...` |
| Applied | no (review artifact only) |
| Batches | 23 |
| Guarded batches | 21 |
| Column declarations retyped | 21 |
| Static guard status | `passed` (15/15 checks) |

| Guard check | Result | Detail |
| --- | --- | --- |
| `every_create_batch_is_guarded` | yes | every batch that creates an object is wrapped in an OBJECT_ID / NOT EXISTS guard |
| `no_destructive_statement` | yes | no DROP, TRUNCATE, DELETE, UPDATE, INSERT, MERGE, ALTER or administrative token occurs in any statement |
| `no_external_schema_reference` | yes | no statement references a db_owner, dbo or NEWERP object, so no shared object is touched |
| `no_database_switch` | yes | the draft contains no USE statement |
| `begin_end_balanced` | yes | BEGIN and END counts match in every batch |
| `parentheses_balanced` | yes | parenthesis counts match in every batch |
| `every_batch_terminated` | yes | every batch ends with a terminated statement or an END block terminator |
| `table_set_unchanged` | yes | the draft declares exactly the app tables of the planned DDL contract |
| `column_set_unchanged` | yes | the draft declares exactly the columns of the planned DDL contract in the same order |
| `only_registered_columns_retyped` | yes | the rewritten declarations are exactly the registered resolved keys with their recorded shared type |
| `shared_type_applied_to_every_declaration_site` | yes | every declaration site of a resolved key carries the recorded shared key type |
| `unresolved_keys_kept_neutral` | yes | keys that are app-owned or still unresolved keep their planned declaration unchanged |
| `object_counts_unchanged` | yes | the draft adds no object beyond the planned DDL contract |
| `no_generated_view_or_foreign_key` | yes | view and foreign-key proposals stay documented review items instead of generated statements |
| `review_banner_present` | yes | the draft carries the generated review banner that states this task must not apply it |

| Line | Table | Column | From | To | Neutral key | Shared target |
| --- | --- | --- | --- | --- | --- | --- |
| 65 | `app.UserMobileProfile` | `UserKey` | `NVARCHAR(80)` | `BIGINT` | `UserKey` | `db_owner.SysUsers.Id` |
| 86 | `app.UserIdentity` | `UserKey` | `NVARCHAR(80)` | `BIGINT` | `UserKey` | `db_owner.SysUsers.Id` |
| 111 | `app.InviteCode` | `CreatedByUserKey` | `NVARCHAR(80)` | `BIGINT` | `CreatedByUserKey` | `db_owner.SysUsers.Id` |
| 134 | `app.FileAsset` | `UploadedByUserKey` | `NVARCHAR(80)` | `BIGINT` | `UploadedByUserKey` | `db_owner.SysUsers.Id` |
| 153 | `app.CustomerExt` | `CustomerKey` | `NVARCHAR(80)` | `BIGINT` | `CustomerKey` | `db_owner.BaseCustomers.Id` |
| 158 | `app.CustomerExt` | `UpdatedByUserKey` | `NVARCHAR(80)` | `BIGINT` | `UpdatedByUserKey` | `db_owner.SysUsers.Id` |
| 172 | `app.SupplierExt` | `SupplierKey` | `NVARCHAR(80)` | `BIGINT` | `SupplierKey` | `db_owner.BaseSuppliers.Id` |
| 177 | `app.SupplierExt` | `UpdatedByUserKey` | `NVARCHAR(80)` | `BIGINT` | `UpdatedByUserKey` | `db_owner.SysUsers.Id` |
| 194 | `app.InquiryTrip` | `CustomerKey` | `NVARCHAR(80)` | `BIGINT` | `CustomerKey` | `db_owner.BaseCustomers.Id` |
| 195 | `app.InquiryTrip` | `SalesUserKey` | `NVARCHAR(80)` | `BIGINT` | `SalesUserKey` | `db_owner.SysUsers.Id or db_owner.BaseEmployees.Id` |
| 220 | `app.SupplierVisit` | `SupplierKey` | `NVARCHAR(80)` | `BIGINT` | `SupplierKey` | `db_owner.BaseSuppliers.Id` |
| 228 | `app.SupplierVisit` | `CreatedByUserKey` | `NVARCHAR(80)` | `BIGINT` | `CreatedByUserKey` | `db_owner.SysUsers.Id` |
| 265 | `app.InquiryItem` | `CreatedByUserKey` | `NVARCHAR(80)` | `BIGINT` | `CreatedByUserKey` | `db_owner.SysUsers.Id` |
| 308 | `app.InquiryRevision` | `SubmittedByUserKey` | `NVARCHAR(80)` | `BIGINT` | `SubmittedByUserKey` | `db_owner.SysUsers.Id` |
| 354 | `app.AIJob` | `CreatedByUserKey` | `NVARCHAR(80)` | `BIGINT` | `CreatedByUserKey` | `db_owner.SysUsers.Id` |
| 376 | `app.AICorrection` | `CorrectedByUserKey` | `NVARCHAR(80)` | `BIGINT` | `CorrectedByUserKey` | `db_owner.SysUsers.Id` |
| 389 | `app.ExportJob` | `RequestedByUserKey` | `NVARCHAR(80)` | `BIGINT` | `RequestedByUserKey` | `db_owner.SysUsers.Id` |
| 412 | `app.ClientDevice` | `UserKey` | `NVARCHAR(80)` | `BIGINT` | `UserKey` | `db_owner.SysUsers.Id` |
| 428 | `app.IdempotencyRequest` | `UserKey` | `NVARCHAR(80)` | `BIGINT` | `UserKey` | `db_owner.SysUsers.Id` |
| 450 | `app.ChangeLog` | `ChangedByUserKey` | `NVARCHAR(80)` | `BIGINT` | `ChangedByUserKey` | `db_owner.SysUsers.Id` |
| 464 | `app.AgentAudit` | `UserKey` | `NVARCHAR(80)` | `BIGINT` | `UserKey` | `db_owner.SysUsers.Id` |

## 7. Migration plan

The plan is ordered so that every state-changing step is reviewable, reversible in a disposable database and gated before the shared database is touched.

| Step | Action | Verification | Gate |
| --- | --- | --- | --- |
| 1 | GPT review accepts this reconciliation and the generated draft digest `sha256:3d3c7c89d7d7fedd...`. | Every reconciliation row has a resolution and every unresolved item is acknowledged. | GPT review |
| 2 | Record the controller Human Gate approval for applying the app-schema draft. | The approval names the disposable database and forbids destructive statements. | Human Gate |
| 3 | Run the draft twice in a disposable database (owner: the migration task). | Both runs succeed, the second run changes nothing, and the app object inventory matches 20 tables and 18 indexes. | Human Gate |
| 4 | Compare the shared catalog metadata before and after to confirm that no NEWERP object changed. | No shared table, column, index or constraint differs and no duplicate master table exists. | Human Gate |
| 5 | Apply the same reviewed draft to the shared database inside an approved window, recording the applied digest. | The applied digest equals the reviewed digest and the verification of step 4 still passes. | Human Gate |
| 6 | Implement the server-side repository mappings with the now-recorded key types. | Queries read the existing shared master data and no app-only master copy is written. | dependency NEWAPP-008 |
| 7 | Raise the foreign key and view proposals as a separate change. | The proposal lists the exact constraint per resolved key and repeats the non-destructive verification. | Human Gate |

## 8. Rollback notes

1. The draft is additive: it only creates app-schema objects, so a rollback never has to restore a modified shared table.
2. Record the applied digest `sha256:3d3c7c89d7d7fedd...` and keep the pre-apply catalog metadata snapshot, so a rollback can prove which app objects were added.
3. Reversing the change means removing the app objects that this draft created, in reverse creation order, and that removal is itself a destructive operation: it is never executed by this module and requires a separate Human Gate approval.
4. If business rows were already written into the app tables, take a backup of those app tables before the removal and restore them only through the approved migration procedure.
5. Because every creation is guarded by an `OBJECT_ID` or `NOT EXISTS` check, re-running the draft after a partial failure is safe and converges to the same object inventory.
6. Keys that stay neutral keep their declarations across a rollback, so no key value is converted back and forth.
7. This task executed no rollback and generated no destructive statement; the rollback plan is documentation for the gated migration task.

## 9. Disposable compile check

| Fact | Value |
| --- | --- |
| Requested | yes |
| Status | `compiled_and_rolled_back` |
| Reason | every batch compiled twice inside one transaction that was rolled back, and no app object remained |
| Target instance | `(localdb)\MSSQLLocalDB` (localdb) |
| Target catalog | `tempdb` (scratch_database) |
| Selected driver | ODBC Driver 17 for SQL Server |
| Integrated security | yes |
| Shared connection used | no |
| Connection string recorded | no |
| Passes completed | 2 |
| Batches executed | 46 |
| App tables visible in the transaction | 20 |
| App tables after rollback | 0 |
| Rollback confirmed | yes |
| Commit issued | no |
| Target guard | `passed` | target is local, disposable and unrelated to the shared database |
| Statement guard | `passed` | evaluated 23 batches before execution |

The check never uses the shared server, its catalog or its credentials: a target that is not a local disposable LocalDB instance or a disposable catalog is refused before any statement runs. The transaction is rolled back and the post-rollback count proves that no app object remained.

## 10. Human Gate boundary

| Concern | State |
| --- | --- |
| Shared structure change required | yes |
| Applied by this task | no |
| Foreign key to a shared table generated | no |
| Duplicate master table created | no |
| Approval required before execution | yes |

Applying the draft, adding a constraint to a shared table or migrating the shared database is a shared-structure change that stays behind the controller Human Gate and the GPT review.

## 11. Known limits

1. The reconciliation reads the accepted NEWAPP-003 snapshot, so a shared table created after that inspection is not represented and the map is metadata rather than a live binding.
2. Raising a neutral key to the recorded shared key type aligns the column type; it does not create the foreign key, which stays a Human-Gated shared-structure change.
3. TenantId keeps its UNIQUEIDENTIFIER declaration because the accepted map reports the organization, tenant and company domain as absent from the inspected catalog.
4. Group and template pointers keep their neutral declarations because no authoritative table for them is recorded; they are review items, not resolved mappings.
5. The disposable compile check runs the draft inside one rolled-back transaction on a local disposable engine, so it proves compilation, guard coverage and idempotent re-run rather than behaviour against shared data.
6. When the ODBC driver module is not importable in the generating interpreter, the compile check is reported as engine_unavailable together with the regenerating command instead of an implicit pass.
7. Applying the draft to the shared NEWERP database, adding a foreign key to a shared table and migrating a shared database are outside this task and stay behind the Human Gate.
8. agent.env, secrets, signing material and the OSS credentials are never opened by this module.

## 12. Unresolved items

| Item | Reason | Next action |
| --- | --- | --- |
| authoritative table for SalesUserKey | the storage type is recorded but more than one candidate target exists: db_owner.SysUsers.Id, db_owner.BaseEmployees.Id | confirm which candidate owns the relationship during GPT review; the draft already carries the recorded shared key type |
| authoritative shared binding for SalesGroupKey | the accepted map records no authoritative target for this key | decide the binding during GPT review; the declaration stays neutral until then and any constraint stays behind the Human Gate |
| authoritative shared binding for TargetGroupKey | the accepted map records no authoritative target for this key | decide the binding during GPT review; the declaration stays neutral until then and any constraint stays behind the Human Gate |
| authoritative shared binding for TemplateKey | the accepted map records no authoritative target for this key | decide the binding during GPT review; the declaration stays neutral until then and any constraint stays behind the Human Gate |
| authoritative shared binding for TenantId | the accepted map reports the organization/tenant domain as absent_from_catalog and lists no binding table, so the partition key keeps its neutral declaration | decide the binding during GPT review; the declaration stays neutral until then and any constraint stays behind the Human Gate |
| shared schema application of the reconciled draft | applying the draft, adding a constraint to a shared table or migrating the shared database is a shared-structure change owned by the Human Gate | record the Human Gate approval through the controller and execute the migration in a disposable database first; this task only produces the reviewed draft |
| foreign key and view proposals | a direct foreign key to a shared master table and a view-backed read model are the preferred mapping, but both would change shared structures | raise them as a separate gated change after the migration review instead of generating them in this draft |

## 13. Acceptance evidence

| Criterion | Evidence | Satisfied |
| --- | --- | --- |
| Every neutral CustomerKey, SupplierKey, UserKey and TenantId reference is classified against the accepted NEWAPP-003 map; resolved keys carry the recorded shared key type and unresolved keys keep their neutral declaration. | declared neutral keys: 18; classified rows: 18; shared type applied: CustomerKey, SupplierKey, UserKey, SalesUserKey, CreatedByUserKey, UpdatedByUserKey, UploadedByUserKey, SubmittedByUserKey, RequestedByUserKey, CorrectedByUserKey, ChangedByUserKey; kept neutral: SalesGroupKey, TargetGroupKey, TemplateKey, TenantId, ObjectKey, IdempotencyKey, EntityKey | yes |
| The reconciled draft compiles and re-runs idempotently in a disposable database. | compile status: compiled_and_rolled_back; passes completed: 2; batches executed: 46; app tables visible in the transaction: 20; app tables after rollback: 0 | yes |
| No destructive change to an existing NEWERP table, no shared object touched and no duplicate customer or supplier master table created. | static guard status: passed; destructive batches: 0; external schema batches: 0; shared objects changed: no | yes |
| A migration plan and rollback notes exist, and every shared-structure change stops at the Human Gate. | documents: docs/NEWAPP_DDL_RECONCILIATION.md; applied by this task: no; approval required before execution: yes | yes |
| Generated artifacts stay inside the executor allowed paths and contain no credential material. | checked by the credential guard, the repository scanner and the path guard | yes |

Artifact guard status: report `passed`, document `passed`, draft `passed`, repository scanner `passed`; path guard accepted every recorded path: yes.

---

Regenerate with `.venv\Scripts\python.exe tests\schema\ddl_reconciliation.py --write   (add --compile in an interpreter that can import the ODBC driver module)`.

