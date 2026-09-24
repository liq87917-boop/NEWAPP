# NEWERP shared database schema map (read-only inspection)

Task: **NEWAPP-003 - Inspect NEWERP shared database schema** (phase P0, depends on NEWAPP-002).

This document is generated from the same value-free facts as `.ai/generated/NEWAPP-003-newerp-schema-map.json`, so regenerate it with `.venv\Scripts\python.exe tests\schema\newerp_schema.py --write` instead of editing it by hand.

Generated at 2026-09-24T01:13:34.443919Z by newapp_executor (Cline/DeepSeek). Completion authority: the GPT brain (Codex desktop / ChatGPT mobile Remote) review, never the executor.

## 1. Authority of record

| Concern | Authoritative artifact |
| --- | --- |
| Shared database structure | the live NEWERP SQL Server catalog, metadata only |
| Machine-readable facts | `.ai/generated/NEWAPP-003-newerp-schema-map.json` |
| Server-side connection reference | the declared setting name in the ignored and untracked environment file |
| Planned app-schema DDL | `docs/NEWAPP_Database_DDL_V1.sql` |
| Controller allowed paths | `.ai/agent_config.yaml#paths.executor_allowed` |
| Task definition | `docs/NEWAPP_TASKS_V1.yaml#NEWAPP-003` |

## 2. Safety contract for this inspection

1. Only catalog metadata is read: schemas, tables, columns, keys, indexes, foreign keys and concurrency columns. No business row value is selected, exported or recorded.
2. Every statement is produced by this module from one fixed catalog table and must pass the read-only statement guard: a single `SELECT` without batch separator, comment marker, DDL/DML, `EXEC`, `INTO`, `OPENROWSET` or administrative token.
3. Statements executed in this run: 8. Statements outside the fixed catalog table: 0. DDL or DML executed: no. Stored procedures executed: no. Shared objects changed: no.
4. The session is opened with autocommit: yes. The login timeout is 5 seconds and the connection is closed before the report is rendered (closed: yes), so no transaction or lock is left on the shared database.
5. The declared shared connection declaration stays in memory: it is translated into an ODBC target inside one call and dropped when that call returns. Nothing about its server, catalog, login or password is recorded, hashed, compared or rendered.
6. The environment file is opened read-only and never written. Environment file written: no. Write timestamp unchanged across the run: yes.
7. Both artifacts are re-checked with the credential guard and the repository scanner `tests/baseline/secret_scan.py` before publication; a credential needle blocks the write.

## 3. Inspection result

| Fact | Value |
| --- | --- |
| Inspection status | `inspected` |
| Declared setting found | yes (source label `.env`) |
| Connection attempted | yes |
| Driver module | `pyodbc` available: yes |
| Driver version | 5.2.0 |
| Interpreter | CPython 3.13.3 |
| Selected ODBC driver | ODBC Driver 17 for SQL Server |
| Inspected catalog | WMERP_Data |
| Engine version | 15.0.2000.5 |
| Engine edition | Developer Edition (64-bit) |
| Tables and columns | 74 tables, 1416 columns |
| Keys, indexes and foreign keys | 72 key constraints, 113 index entries, 7 foreign keys |
| Unavailable reasons | none |

## 4. Shared connection configuration (names and shape flags only)

| Fact | Value |
| --- | --- |
| Declared setting name | `ERP_ConnectionStrings__Default` |
| Declared keywords | 5 |
| Keyword names | Server, Database, User Id, Password, TrustServerCertificate |
| ODBC keyword names | Driver, Server, Database, UID, PWD, TrustServerCertificate, ApplicationIntent |
| Keywords a .NET client accepts but ODBC does not | none |
| Unparsed fragments | 0 |
| Declares an ODBC driver | no |
| Read-only application intent requested | yes |
| Uses integrated security | no |
| Shape flags | server yes, catalog yes, login yes, credential material yes |

The keyword names above tell the server-side binding work which declarations must be mapped to an ODBC provider and which .NET-only keywords have to be dropped or replaced. No declared value is recorded.

## 5. Domain master-table candidates

Candidates come from the inspected catalog. A strong candidate carries a core domain noun in its name; a weak candidate only shares a supporting token. Classification never asserts the authoritative mapping: NEWAPP-005 reconciles the planned DDL against this map.

| Domain | Monitored | Status | Strong candidates | Candidates |
| --- | --- | --- | --- | --- |
| Customer master data | yes | `resolved` | `db_owner.BaseCustomers`, `db_owner.CustomerFollowUps`, `db_owner.SysClientLimits` | 3 |
| Supplier master data | yes | `resolved` | `db_owner.BaseSuppliers` | 1 |
| User and account data | yes | `resolved` | `db_owner.BaseEmployees`, `db_owner.SysUserParameters`, `db_owner.SysUserRoles`, `db_owner.SysUsers` | 7 |
| Organization, tenant and company data | yes | `absent_from_catalog` | none | 0 |
| Shared dictionaries and code tables | no | `candidates_need_review` | none | 5 |
| Inquiry, quotation and revision data | no | `resolved` | `db_owner.Inquiries`, `db_owner.Inquiry`, `db_owner.InquiryDetails`, `db_owner.PurchaseQuotes`, `db_owner.QuotationDetails`, `db_owner.Quotations` | 7 |

- **Organization, tenant and company data** has no candidate at all in the inspected catalog and is therefore reported as absent from the shared schema rather than guessed.
- **Shared dictionaries and code tables** has candidate tables but no core name match, so the authoritative table stays unresolved for review: `db_owner.BaseTaxRefunds`, `db_owner.FinancePayment`, `db_owner.FinancePaymentApplies`, `db_owner.FinancePayments`, `db_owner.SysParameters`.

Master-data-shaped tables that no domain token matched, recorded so that review can assign them deliberately: `db_owner.BaseOtherInfos`, `db_owner.BaseWarehouses`.

## 6. Candidate table detail

Table detail is capped at 60 candidate tables and 150 columns per table; the JSON report carries the same bound. This document renders at most 25 candidate tables.

### db_owner.BaseCustomers

- Domain: customer (strong candidate: yes)
- Matched tokens: customer
- Columns: 35
- Primary key `PK_BaseCustomers` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `CustomerCode` | nvarchar(100) | no | no | no |
| `CustomerName` | nvarchar(400) | no | no | no |
| `EnglishName` | nvarchar(400) | no | no | no |
| `ContactPerson` | nvarchar(100) | no | no | no |
| `Phone` | nvarchar(100) | no | no | no |
| `Email` | nvarchar(200) | no | no | no |
| `Country` | nvarchar(200) | no | no | no |
| `Address` | nvarchar(1000) | no | no | no |
| `PaymentTerms` | nvarchar(400) | no | no | no |
| `CreditLimit` | decimal(18,2) | no | no | no |
| `TaxNumber` | nvarchar(200) | no | no | no |
| `Status` | int | no | no | no |
| `Remark` | nvarchar(1000) | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | yes | no | rowversion |
| `EmpId` | bigint | yes | no | no |
| `DepositRatio` | decimal(18,2) | no | no | no |
| `BusinessNature` | nvarchar(40) | no | no | no |
| `Currency` | nvarchar(40) | no | no | no |
| `SettlementMethod` | nvarchar(200) | no | no | no |
| `TradeTerms` | nvarchar(100) | no | no | no |
| `DestinationPort` | nvarchar(200) | no | no | no |
| `Consignee` | nvarchar(600) | no | no | no |
| `NotifyParty` | nvarchar(600) | no | no | no |
| `DefaultShippingMark` | nvarchar(600) | no | no | no |
| `CreditDays` | int | yes | no | no |
| `CommissionRatio` | decimal(18,4) | no | no | no |
| `CustomerLevel` | nvarchar(40) | no | no | no |
| `CreditStatus` | nvarchar(40) | no | no | no |
| `Source` | nvarchar(100) | no | no | no |

Indexes: `IX_BaseCustomers_CustomerCode` (NONCLUSTERED) on CustomerCode; `PK_BaseCustomers` (CLUSTERED) on Id

### db_owner.BaseEmployees

- Domain: user (strong candidate: yes)
- Matched tokens: user
- Columns: 16
- Primary key `PK_BaseEmployees` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `EmployeeCode` | nvarchar(100) | no | no | no |
| `EmployeeName` | nvarchar(100) | no | no | no |
| `Department` | nvarchar(200) | no | no | no |
| `Position` | nvarchar(200) | no | no | no |
| `Phone` | nvarchar(100) | no | no | no |
| `Email` | nvarchar(200) | no | no | no |
| `HireDate` | datetime2 | yes | no | no |
| `Status` | int | no | no | no |
| `IsSalesman` | bit | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | yes | no | rowversion |

Indexes: `IX_BaseEmployees_EmployeeCode` (NONCLUSTERED) on EmployeeCode; `PK_BaseEmployees` (CLUSTERED) on Id

### db_owner.BaseExpenseAccounts

- Domain: user (strong candidate: no)
- Matched tokens: user
- Columns: 13
- Primary key `PK_BaseExpenseAccounts` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `AccountCode` | nvarchar(100) | no | no | no |
| `AccountName` | nvarchar(200) | no | no | no |
| `AccountType` | int | no | no | no |
| `Description` | nvarchar(1000) | no | no | no |
| `Status` | int | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | yes | no | rowversion |
| `ParentId` | bigint | yes | no | no |

Indexes: `IX_BaseExpenseAccounts_AccountCode` (NONCLUSTERED) on AccountCode; `PK_BaseExpenseAccounts` (CLUSTERED) on Id

### db_owner.BaseOtherInfos

- Domain: unclassified (strong candidate: no)
- Matched tokens: none
- Columns: 15
- Primary key `PK_BaseOtherInfos` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `InfoType` | nvarchar(100) | no | no | no |
| `InfoCode` | nvarchar(100) | no | no | no |
| `InfoName` | nvarchar(200) | no | no | no |
| `EnglishName` | nvarchar(200) | no | no | no |
| `IsDefault` | bit | no | no | no |
| `SortOrder` | int | no | no | no |
| `Status` | int | no | no | no |
| `Remark` | nvarchar(1000) | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | yes | no | rowversion |

Indexes: `IX_BaseOtherInfos_InfoType_InfoCode` (NONCLUSTERED) on InfoType, InfoCode; `PK_BaseOtherInfos` (CLUSTERED) on Id

### db_owner.BaseProducts

- Domain: inquiry (strong candidate: no)
- Matched tokens: inquiry
- Columns: 46
- Primary key `PK_BaseProducts` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `ProductCode` | nvarchar(100) | no | no | no |
| `ProductName` | nvarchar(400) | no | no | no |
| `EnglishName` | nvarchar(400) | no | no | no |
| `Spec` | nvarchar(400) | no | no | no |
| `Unit` | nvarchar(40) | no | no | no |
| `Category` | nvarchar(200) | no | no | no |
| `HsCode` | nvarchar(100) | no | no | no |
| `Barcode` | nvarchar(200) | no | no | no |
| `PurchasePrice` | decimal(18,2) | no | no | no |
| `SalePrice` | decimal(18,2) | no | no | no |
| `CostPrice` | decimal(18,2) | no | no | no |
| `Weight` | decimal(18,2) | no | no | no |
| `Volume` | decimal(18,2) | no | no | no |
| `Length` | decimal(18,2) | no | no | no |
| `Width` | decimal(18,2) | no | no | no |
| `Height` | decimal(18,2) | no | no | no |
| `Status` | int | no | no | no |
| `Remark` | nvarchar(1000) | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | yes | no | rowversion |
| `Image1` | nvarchar(1000) | yes | no | no |
| `Image2` | nvarchar(1000) | yes | no | no |
| `Image3` | nvarchar(1000) | yes | no | no |
| `PackageUnit` | nvarchar(40) | no | no | no |
| `UnitsPerPackage` | int | no | no | no |
| `UnitConversion` | nvarchar(200) | no | no | no |
| `OuterLength` | decimal(18,4) | no | no | no |
| `OuterWidth` | decimal(18,4) | no | no | no |
| `OuterHeight` | decimal(18,4) | no | no | no |
| `OuterWeight` | decimal(18,4) | no | no | no |
| `VolumeWeight` | decimal(18,4) | no | no | no |
| `EnglishDeclareName` | nvarchar(400) | no | no | no |
| `RefundRate` | decimal(18,4) | no | no | no |
| `Brand` | nvarchar(200) | no | no | no |
| `Certification` | nvarchar(400) | no | no | no |
| `CustomerItemNo` | nvarchar(200) | no | no | no |
| `FactoryItemNo` | nvarchar(200) | no | no | no |
| `MinOrderQty` | int | no | no | no |
| `TaxIncluded` | bit | no | no | no |
| `MinStock` | decimal(18,4) | no | no | no |
| `MaxStock` | decimal(18,4) | no | no | no |

Indexes: `IX_BaseProducts_ProductCode` (NONCLUSTERED) on ProductCode; `PK_BaseProducts` (CLUSTERED) on Id

### db_owner.BaseSuppliers

- Domain: supplier (strong candidate: yes)
- Matched tokens: supplier
- Columns: 29
- Primary key `PK_BaseSuppliers` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `SupplierCode` | nvarchar(100) | no | no | no |
| `SupplierName` | nvarchar(400) | no | no | no |
| `EnglishName` | nvarchar(400) | no | no | no |
| `ContactPerson` | nvarchar(100) | no | no | no |
| `Phone` | nvarchar(100) | no | no | no |
| `Email` | nvarchar(200) | no | no | no |
| `Country` | nvarchar(200) | no | no | no |
| `Address` | nvarchar(1000) | no | no | no |
| `PaymentTerms` | nvarchar(400) | no | no | no |
| `BankName` | nvarchar(400) | no | no | no |
| `BankAccount` | nvarchar(200) | no | no | no |
| `Status` | int | no | no | no |
| `Remark` | nvarchar(1000) | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | yes | no | rowversion |
| `SupplierType` | nvarchar(40) | no | no | no |
| `BoothLocation` | nvarchar(200) | no | no | no |
| `MainCategory` | nvarchar(200) | no | no | no |
| `SettlementMethod` | nvarchar(100) | no | no | no |
| `InvoiceAbility` | nvarchar(40) | no | no | no |
| `TaxRate` | decimal(18,4) | no | no | no |
| `DeliveryDays` | int | no | no | no |
| `RebateRatio` | decimal(18,4) | no | no | no |
| `WeChat` | nvarchar(100) | no | no | no |

Indexes: `IX_BaseSuppliers_SupplierCode` (NONCLUSTERED) on SupplierCode; `PK_BaseSuppliers` (CLUSTERED) on Id

### db_owner.BaseTaxRefunds

- Domain: dictionary (strong candidate: no)
- Matched tokens: dictionary
- Columns: 24
- Primary key `PK__BaseTaxR__3214EC07365129E6` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `RefundNo` | nvarchar(100) | no | no | no |
| `RefundPeriod` | nvarchar(40) | no | no | no |
| `DeclareDate` | datetime2 | yes | no | no |
| `DeclareNo` | nvarchar(100) | no | no | no |
| `InvoiceNo` | nvarchar(100) | no | no | no |
| `SalesOrderNo` | nvarchar(100) | no | no | no |
| `CustomerId` | bigint | yes | no | no |
| `CustomerName` | nvarchar(400) | no | no | no |
| `ExportAmount` | decimal(18,4) | no | no | no |
| `Currency` | nvarchar(40) | no | no | no |
| `ExchangeRate` | decimal(18,6) | no | no | no |
| `RefundRate` | decimal(18,4) | no | no | no |
| `RefundableAmount` | decimal(18,4) | no | no | no |
| `RefundedAmount` | decimal(18,4) | no | no | no |
| `RefundDate` | datetime2 | yes | no | no |
| `Status` | nvarchar(40) | no | no | no |
| `Remark` | nvarchar(1000) | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | no | no | rowversion |

Indexes: `PK__BaseTaxR__3214EC07365129E6` (CLUSTERED) on Id

### db_owner.BaseWarehouses

- Domain: unclassified (strong candidate: no)
- Matched tokens: none
- Columns: 14
- Primary key `PK_BaseWarehouses` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `WarehouseCode` | nvarchar(100) | no | no | no |
| `WarehouseName` | nvarchar(200) | no | no | no |
| `Address` | nvarchar(1000) | no | no | no |
| `Manager` | nvarchar(100) | no | no | no |
| `Phone` | nvarchar(100) | no | no | no |
| `Status` | int | no | no | no |
| `Remark` | nvarchar(1000) | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | yes | no | rowversion |

Indexes: `IX_BaseWarehouses_WarehouseCode` (NONCLUSTERED) on WarehouseCode; `PK_BaseWarehouses` (CLUSTERED) on Id

### db_owner.CustomerFollowUps

- Domain: customer (strong candidate: yes)
- Matched tokens: customer
- Columns: 20
- Primary key `PK__Customer__3214EC0770E2CF47` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `FollowNo` | nvarchar(100) | no | no | no |
| `FollowDate` | datetime2 | no | no | no |
| `CustomerId` | bigint | yes | no | no |
| `CustomerName` | nvarchar(400) | no | no | no |
| `FollowType` | nvarchar(60) | no | no | no |
| `ContactPerson` | nvarchar(200) | no | no | no |
| `SalesmanId` | bigint | yes | no | no |
| `SalesmanName` | nvarchar(100) | no | no | no |
| `Subject` | nvarchar(200) | no | no | no |
| `Content` | nvarchar(2000) | no | no | no |
| `Result` | nvarchar(60) | no | no | no |
| `NextFollowDate` | datetime2 | yes | no | no |
| `Remark` | nvarchar(1000) | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | no | no | rowversion |

Indexes: `PK__Customer__3214EC0770E2CF47` (CLUSTERED) on Id

### db_owner.FinancePayment

- Domain: dictionary (strong candidate: no)
- Matched tokens: dictionary
- Columns: 16
- Primary key `PK__FinanceP__CB3E4F31AFBC2443` on Oid
- Concurrency columns: none

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Oid` | bigint | no | no | no |
| `BillID` | nvarchar(100) | no | no | no |
| `BillNo` | nvarchar(200) | yes | no | no |
| `PaymentDate` | datetime2 | no | no | no |
| `SupplierId` | bigint | no | no | no |
| `PaymentApplyId` | bigint | yes | no | no |
| `Amount` | decimal(18,2) | no | no | no |
| `Currency` | int | no | no | no |
| `PaymentMethod` | int | no | no | no |
| `BankAccount` | nvarchar(200) | yes | no | no |
| `Status` | int | no | no | no |
| `Remark` | nvarchar(1000) | yes | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |

Indexes: `PK__FinanceP__CB3E4F31AFBC2443` (CLUSTERED) on Oid

### db_owner.FinancePaymentApplies

- Domain: dictionary (strong candidate: no)
- Matched tokens: dictionary
- Columns: 19
- Primary key `PK_FinancePaymentApplies` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `ApplyNo` | nvarchar(100) | no | no | no |
| `ApplyDate` | datetime2 | no | no | no |
| `SalesOrderId` | bigint | yes | no | no |
| `CustomerId` | bigint | no | no | no |
| `Amount` | decimal(18,2) | no | no | no |
| `Currency` | int | no | no | no |
| `ExchangeRate` | decimal(18,2) | no | no | no |
| `BankAccount` | nvarchar(200) | no | no | no |
| `Payee` | nvarchar(400) | no | no | no |
| `Reason` | nvarchar(1000) | no | no | no |
| `Status` | int | no | no | no |
| `Remark` | nvarchar(1000) | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | yes | no | rowversion |

Indexes: `IX_FinancePaymentApplies_ApplyNo` (NONCLUSTERED) on ApplyNo; `PK_FinancePaymentApplies` (CLUSTERED) on Id

### db_owner.FinancePayments

- Domain: dictionary (strong candidate: no)
- Matched tokens: dictionary
- Columns: 17
- Primary key `PK_FinancePayments` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `PaymentNo` | nvarchar(100) | no | no | no |
| `PaymentDate` | datetime2 | no | no | no |
| `SupplierId` | bigint | no | no | no |
| `PaymentApplyId` | bigint | yes | no | no |
| `Amount` | decimal(18,2) | no | no | no |
| `Currency` | int | no | no | no |
| `PaymentMethod` | int | no | no | no |
| `BankAccount` | nvarchar(200) | no | no | no |
| `Status` | int | no | no | no |
| `Remark` | nvarchar(1000) | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | yes | no | rowversion |

Indexes: `IX_FinancePayments_PaymentNo` (NONCLUSTERED) on PaymentNo; `PK_FinancePayments` (CLUSTERED) on Id

### db_owner.Inquiries

- Domain: inquiry (strong candidate: yes)
- Matched tokens: inquiry
- Columns: 18
- Primary key `PK_Inquiries` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `InquiryNo` | nvarchar(100) | no | no | no |
| `InquiryDate` | datetime2 | no | no | no |
| `CustomerId` | bigint | no | no | no |
| `ContactPerson` | nvarchar(100) | no | no | no |
| `ContactPhone` | nvarchar(100) | no | no | no |
| `SalesmanId` | bigint | yes | no | no |
| `Currency` | int | no | no | no |
| `ExchangeRate` | decimal(18,2) | no | no | no |
| `ValidDays` | int | no | no | no |
| `Status` | int | no | no | no |
| `Remark` | nvarchar(1000) | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | yes | no | rowversion |

Indexes: `IX_Inquiries_InquiryNo` (NONCLUSTERED) on InquiryNo; `PK_Inquiries` (CLUSTERED) on Id

### db_owner.Inquiry

- Domain: inquiry (strong candidate: yes)
- Matched tokens: inquiry
- Columns: 17
- Primary key `PK__Inquiry__CB3E4F3173929022` on Oid
- Concurrency columns: none

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Oid` | bigint | no | no | no |
| `BillID` | nvarchar(100) | no | no | no |
| `BillNo` | nvarchar(200) | yes | no | no |
| `InquiryDate` | datetime2 | no | no | no |
| `CustomerId` | bigint | no | no | no |
| `ContactPerson` | nvarchar(100) | yes | no | no |
| `ContactPhone` | nvarchar(100) | yes | no | no |
| `EmpId` | bigint | yes | no | no |
| `Currency` | int | no | no | no |
| `ExchangeRate` | decimal(18,2) | no | no | no |
| `ValidDays` | int | no | no | no |
| `Status` | int | no | no | no |
| `Remark` | nvarchar(1000) | yes | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |

Indexes: `PK__Inquiry__CB3E4F3173929022` (CLUSTERED) on Oid

### db_owner.InquiryDetails

- Domain: inquiry (strong candidate: yes)
- Matched tokens: inquiry
- Columns: 18
- Primary key `PK_InquiryDetails` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `InquiryId` | bigint | no | no | no |
| `ProductId` | bigint | no | no | no |
| `ProductName` | nvarchar(400) | no | no | no |
| `Spec` | nvarchar(400) | no | no | no |
| `Quantity` | decimal(18,2) | no | no | no |
| `Unit` | nvarchar(40) | no | no | no |
| `UnitPrice` | decimal(18,2) | no | no | no |
| `Amount` | decimal(18,2) | no | no | no |
| `TargetPrice` | decimal(18,2) | no | no | no |
| `ExpectedDeliveryDate` | datetime2 | yes | no | no |
| `Remark` | nvarchar(1000) | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | yes | no | rowversion |

Foreign keys out: `FK_InquiryDetails_Inquiries_InquiryId` on InquiryId to `db_owner.Inquiries`

Indexes: `IX_InquiryDetails_InquiryId` (NONCLUSTERED) on InquiryId; `PK_InquiryDetails` (CLUSTERED) on Id

### db_owner.PurchaseQuotes

- Domain: inquiry (strong candidate: yes)
- Matched tokens: inquiry
- Columns: 30
- Primary key `PK__Purchase__3214EC0740C15E7A` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `QuoteNo` | nvarchar(100) | no | no | no |
| `QuoteDate` | datetime2 | no | no | no |
| `ProductId` | bigint | yes | no | no |
| `ProductName` | nvarchar(400) | no | no | no |
| `Spec` | nvarchar(400) | no | no | no |
| `Unit` | nvarchar(40) | no | no | no |
| `Quantity` | decimal(18,4) | no | no | no |
| `SupplierId` | bigint | yes | no | no |
| `SupplierName` | nvarchar(400) | no | no | no |
| `SupplierType` | nvarchar(40) | no | no | no |
| `QuotePrice` | decimal(18,4) | no | no | no |
| `TotalAmount` | decimal(18,4) | no | no | no |
| `Currency` | nvarchar(40) | no | no | no |
| `TaxIncluded` | bit | no | no | no |
| `DeliveryDays` | int | no | no | no |
| `MinOrderQty` | int | no | no | no |
| `PaymentTerms` | nvarchar(200) | no | no | no |
| `IsSelected` | bit | no | no | no |
| `Status` | nvarchar(40) | no | no | no |
| `CustomerId` | bigint | yes | no | no |
| `CustomerName` | nvarchar(400) | no | no | no |
| `RefOrderNo` | nvarchar(100) | no | no | no |
| `Remark` | nvarchar(1000) | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | no | no | rowversion |

Indexes: `PK__Purchase__3214EC0740C15E7A` (CLUSTERED) on Id

### db_owner.QuotationDetails

- Domain: inquiry (strong candidate: yes)
- Matched tokens: inquiry
- Columns: 20
- Primary key `PK__Quotatio__3214EC0737355300` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `QuotationId` | bigint | no | no | no |
| `QuotationNo` | nvarchar(100) | no | no | no |
| `SortNo` | int | no | no | no |
| `ProductId` | bigint | yes | no | no |
| `ProductCode` | nvarchar(100) | no | no | no |
| `ProductName` | nvarchar(400) | no | no | no |
| `Spec` | nvarchar(400) | no | no | no |
| `Unit` | nvarchar(40) | no | no | no |
| `Quantity` | decimal(18,4) | no | no | no |
| `UnitPrice` | decimal(18,4) | no | no | no |
| `Amount` | decimal(18,4) | no | no | no |
| `Moq` | nvarchar(200) | no | no | no |
| `Remark` | nvarchar(1000) | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | no | no | rowversion |

Indexes: `PK__Quotatio__3214EC0737355300` (CLUSTERED) on Id

### db_owner.Quotations

- Domain: inquiry (strong candidate: yes)
- Matched tokens: inquiry
- Columns: 30
- Primary key `PK__Quotatio__3214EC0732F33C45` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `QuotationNo` | nvarchar(100) | no | no | no |
| `QuotationDate` | datetime2 | no | no | no |
| `ValidUntil` | datetime2 | yes | no | no |
| `CustomerId` | bigint | yes | no | no |
| `CustomerName` | nvarchar(400) | no | no | no |
| `ContactPerson` | nvarchar(100) | no | no | no |
| `ContactPhone` | nvarchar(100) | no | no | no |
| `ContactEmail` | nvarchar(200) | no | no | no |
| `InquiryId` | bigint | yes | no | no |
| `InquiryNo` | nvarchar(100) | no | no | no |
| `TradeTerms` | nvarchar(100) | no | no | no |
| `PortOfLoading` | nvarchar(200) | no | no | no |
| `PortOfDestination` | nvarchar(200) | no | no | no |
| `PaymentTerms` | nvarchar(400) | no | no | no |
| `LeadTime` | nvarchar(200) | no | no | no |
| `Currency` | int | no | no | no |
| `ExchangeRate` | decimal(18,6) | no | no | no |
| `TotalAmount` | decimal(18,4) | no | no | no |
| `TotalAmountCny` | decimal(18,4) | no | no | no |
| `SalesmanId` | bigint | yes | no | no |
| `SalesmanName` | nvarchar(100) | no | no | no |
| `Status` | int | no | no | no |
| `Remark` | nvarchar(1000) | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | no | no | rowversion |

Indexes: `PK__Quotatio__3214EC0732F33C45` (CLUSTERED) on Id

### db_owner.SysClientLimits

- Domain: customer (strong candidate: yes)
- Matched tokens: customer
- Columns: 11
- Primary key `PK_SysClientLimits` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `LimitType` | int | no | no | no |
| `LimitValue` | nvarchar(400) | no | no | no |
| `IsEnabled` | bit | no | no | no |
| `Remark` | nvarchar(1000) | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | yes | no | rowversion |

Indexes: `PK_SysClientLimits` (CLUSTERED) on Id

### db_owner.SysParameters

- Domain: dictionary (strong candidate: no)
- Matched tokens: dictionary
- Columns: 12
- Primary key `PK_SysParameters` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `ParamKey` | nvarchar(200) | no | no | no |
| `ParamValue` | nvarchar(1000) | no | no | no |
| `ParamName` | nvarchar(200) | no | no | no |
| `Description` | nvarchar(1000) | no | no | no |
| `IsSystem` | bit | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | yes | no | rowversion |

Indexes: `IX_SysParameters_ParamKey` (NONCLUSTERED) on ParamKey; `PK_SysParameters` (CLUSTERED) on Id

### db_owner.SysRoleMenus

- Domain: user (strong candidate: no)
- Matched tokens: user
- Columns: 9
- Primary key `PK_SysRoleMenus` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `RoleId` | bigint | no | no | no |
| `MenuId` | bigint | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | yes | no | rowversion |

Indexes: `PK_SysRoleMenus` (CLUSTERED) on Id

### db_owner.SysRoles

- Domain: user (strong candidate: no)
- Matched tokens: user
- Columns: 11
- Primary key `PK_SysRoles` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `RoleName` | nvarchar(100) | no | no | no |
| `RoleCode` | nvarchar(100) | no | no | no |
| `Description` | nvarchar(400) | no | no | no |
| `IsSystem` | bit | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | yes | no | rowversion |

Indexes: `IX_SysRoles_RoleCode` (NONCLUSTERED) on RoleCode; `PK_SysRoles` (CLUSTERED) on Id

### db_owner.SysUserParameters

- Domain: user (strong candidate: yes)
- Matched tokens: dictionary, user
- Columns: 10
- Primary key `PK_SysUserParameters` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `UserId` | bigint | no | no | no |
| `ParamKey` | nvarchar(200) | no | no | no |
| `ParamValue` | nvarchar(1000) | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | yes | no | rowversion |

Indexes: `PK_SysUserParameters` (CLUSTERED) on Id

### db_owner.SysUserRoles

- Domain: user (strong candidate: yes)
- Matched tokens: user
- Columns: 9
- Primary key `PK_SysUserRoles` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `UserId` | bigint | no | no | no |
| `RoleId` | bigint | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | yes | no | rowversion |

Indexes: `PK_SysUserRoles` (CLUSTERED) on Id

### db_owner.SysUsers

- Domain: user (strong candidate: yes)
- Matched tokens: user
- Columns: 18
- Primary key `PK_SysUsers` on Id
- Concurrency columns: RowVersion (rowversion)

| Column | Type | Nullable | Identity | Concurrency |
| --- | --- | --- | --- | --- |
| `Id` | bigint | no | yes | no |
| `UserName` | nvarchar(100) | no | no | no |
| `PasswordHash` | nvarchar(512) | no | no | no |
| `PasswordSalt` | nvarchar(128) | no | no | no |
| `DisplayName` | nvarchar(100) | no | no | no |
| `Email` | nvarchar(200) | no | no | no |
| `Phone` | nvarchar(60) | no | no | no |
| `Avatar` | nvarchar(1000) | no | no | no |
| `Status` | int | no | no | no |
| `LastLoginTime` | datetime2 | yes | no | no |
| `LastLoginIp` | nvarchar(128) | no | no | no |
| `MustChangePassword` | bit | no | no | no |
| `CreatedAt` | datetime2 | no | no | no |
| `CreatedBy` | bigint | yes | no | no |
| `UpdatedAt` | datetime2 | yes | no | no |
| `UpdatedBy` | bigint | yes | no | no |
| `IsDeleted` | bit | no | no | no |
| `RowVersion` | timestamp | yes | no | rowversion |

Indexes: `IX_SysUsers_UserName` (NONCLUSTERED) on UserName; `PK_SysUsers` (CLUSTERED) on Id

## 7. Concurrency and rowversion columns

Tables with a rowversion column: 63. Tables without any concurrency column: 11.

### Tables with a rowversion column

db_owner.BaseCustomers, db_owner.BaseEmployees, db_owner.BaseExpenseAccounts, db_owner.BaseOtherInfos, db_owner.BaseProducts, db_owner.BaseSuppliers, db_owner.BaseTaxRefunds, db_owner.BaseWarehouses, db_owner.ContainerBookings, db_owner.ContainerLoadingDetails, db_owner.ContainerLoadingLists, db_owner.ContainerPreLoadingDetails, db_owner.ContainerPreLoadings, db_owner.ContainerReceivingPlans, db_owner.CustomerFollowUps, db_owner.FinanceBulkSettlements, db_owner.FinanceComplaints, db_owner.FinanceContainerSettlements, db_owner.FinanceDepositApplies, db_owner.FinanceExpenses, db_owner.FinancePaymentApplies, db_owner.FinancePayments, db_owner.FinanceReceipts, db_owner.Inquiries, db_owner.InquiryDetails, db_owner.ProformaInvoiceDetails, db_owner.ProformaInvoices, db_owner.PurchaseOrderDetails, db_owner.PurchaseOrders, db_owner.PurchaseQuotes, db_owner.PurchaseReturnDetails, db_owner.PurchaseReturns, db_owner.QuotationDetails, db_owner.Quotations, db_owner.SalesOrderDetails, db_owner.SalesOrders, db_owner.SalesReturnDetails, db_owner.SalesReturns, db_owner.Samples, db_owner.StockAdjustmentDetails, db_owner.StockAdjustments, db_owner.StockInDetails, db_owner.StockIns, db_owner.StockMovements, db_owner.StockOutDetails, db_owner.StockOuts, db_owner.StockTransferDetails, db_owner.StockTransfers, db_owner.Stocks, db_owner.SysClientLimits, db_owner.SysDingTalkLogs, db_owner.SysDocumentNumberRules, db_owner.SysMenus, db_owner.SysOperationLogs, db_owner.SysParameters, db_owner.SysPrintTemplate, db_owner.SysPrintTemplates, db_owner.SysRoleMenus, db_owner.SysRoles, db_owner.SysUserParameters, db_owner.SysUserRoles, db_owner.SysUsers, db_owner.TradeDocuments

### Tables without a concurrency column

db_owner.FinanceDepositApply, db_owner.FinancePayment, db_owner.FinanceReceipt, db_owner.Inquiry, db_owner.Plat_CurrentBillNo, db_owner.Plat_TableMaxID, db_owner.PurchaseOrder, db_owner.SalesOrder, db_owner.SalesOrderDetail, db_owner.StockIn, db_owner.StockOut

## 8. Neutral key references in the planned app schema

Source: `docs/NEWAPP_Database_DDL_V1.sql` read read-only, 86 references over 18 identifiers.

| Identifier | Occurrences | Source lines |
| --- | --- | --- |
| `ChangedByUserKey` | 1 | 434 |
| `CorrectedByUserKey` | 1 | 360 |
| `CreatedByUserKey` | 4 | 95, 212, 249, 338 |
| `CustomerKey` | 6 | 8, 137, 145, 178, 194, 468 |
| `EntityKey` | 1 | 431 |
| `IdempotencyKey` | 2 | 413, 419 |
| `ObjectKey` | 2 | 110, 125 |
| `RequestedByUserKey` | 2 | 373, 386 |
| `SalesGroupKey` | 1 | 180 |
| `SalesUserKey` | 2 | 179, 193 |
| `SubmittedByUserKey` | 1 | 292 |
| `SupplierKey` | 6 | 8, 156, 164, 204, 222, 469 |
| `TargetGroupKey` | 1 | 90 |
| `TemplateKey` | 1 | 375 |
| `TenantId` | 40 | 25, 50, 61, 69, 77, 80, 88, 97, 108, 125, 128, 136, 145, 155, 164, 168, 177, 192, 193, 194, 202, 220, 222, 230, 289, 301, 325, 346, 354, 372, 386, 395, 404, 411, 419, 429, 438, 447, 462, 471 |
| `UpdatedByUserKey` | 2 | 142, 161 |
| `UploadedByUserKey` | 1 | 118 |
| `UserKey` | 12 | 8, 49, 61, 70, 80, 396, 404, 412, 419, 448, 462, 470 |

These identifiers are the neutral references the planned DDL still uses. They are inventoried here only; NEWAPP-005 maps them onto the real keys recorded above and stops at the Human Gate before any shared structure change.

## 9. Acceptance evidence

| Criterion | Satisfied | Evidence |
| --- | --- | --- |
| Actual customer, supplier, user and tenant/company master tables are identified. | yes | every monitored master domain is inspected and either resolved by a strong catalog-name candidate or reported as absent from the catalog; the primary key, key constraints and concurrency columns of each candidate are recorded |
| Dictionary and inquiry-related tables plus keys, indexes and rowversion columns are identified. | yes | dictionary- and inquiry-related candidates (or their absence) are recorded with their columns, keys, indexes and concurrency columns, so the metadata is complete even where the authoritative table still needs GPT confirmation |
| No DDL/DML executed against production/shared DB. | yes | 8 statements executed, every one produced by this module from the fixed catalog table and accepted by the read-only statement guard; autocommit on, session closed, no shared object created, altered or dropped |
| Generated artifacts stay inside the executor allowed paths and contain no credential material. | yes | controller path guard mirror over every recorded path plus the credential guard and the repository scanner over both rendered artifacts |

## 10. Artifact checks

| Check | Status | Findings |
| --- | --- | --- |
| documentation_credential_guard | passed | 0 |
| report_credential_guard | passed | 0 |
| scanner_self_check | passed | 0 |

## 11. Executor path guard

| Path | Accepted by the controller pattern | Matched patterns |
| --- | --- | --- |
| `.ai/generated/NEWAPP-003-newerp-schema-map.json` | yes | .ai/generated/** |
| `docs/NEWERP_SCHEMA_MAP.md` | yes | docs/**, *.md |
| `tests/__init__.py` | yes | tests/** |
| `tests/schema/__init__.py` | yes | tests/** |
| `tests/schema/newerp_schema.py` | yes | tests/** |
| `tests/schema/test_newerp_schema.py` | yes | tests/** |
| `docs/README_交付与启动说明.md` | yes | docs/**, *.md |

Allowed pattern source: `.ai/agent_config.yaml#paths.executor_allowed`. Protected path touched: no.

## 12. Known limits

- Table classification uses catalog table names only, so a table whose name does not describe its domain is reported as a weak or unmatched candidate rather than being forced into a domain.
- Column, index and foreign-key detail is capped by the MAX_* constants and every truncation is recorded in the truncation section of the report.
- The keyword parser splits a declared connection string on ';' without interpreting quoted semicolons, which can only affect the reported keyword names, never a value.
- When the ODBC driver module or the shared server is unavailable, every domain is reported as an explicit unknown together with a value-free failure category; no table name is inferred from the planned DDL.
- Only the server-side connection declared for this workspace is inspected. A different shared server reached by another deployment is out of scope.
- The map is a read-only snapshot taken at one moment: objects created after this run are not represented, and no shared object was changed, locked or migrated.
- agent.env, secrets, signing material and the OSS credentials are never opened by this module.

## 13. Unresolved items

| Item | Reason | Next action |
| --- | --- | --- |
| organization authoritative table | no table in the inspected catalog carries a name candidate for this domain | treat the domain as absent from the shared schema and resolve the planned neutral key for it during GPT review before NEWAPP-005 changes any structure |
| dictionary authoritative table | candidate tables were recorded but none carries a core domain noun in its name, so the authoritative table still needs review | confirm during GPT review before NEWAPP-005 maps the planned keys; recorded candidates: db_owner.BaseTaxRefunds, db_owner.FinancePayment, db_owner.FinancePaymentApplies, db_owner.FinancePayments, db_owner.SysParameters |
| neutral *Key mapping to the real NEWERP key types | this task records the real keys and the planned DDL references only; the mapping is owned by NEWAPP-005 | NEWAPP-005 maps CustomerKey, SupplierKey, UserKey and TenantId against this map and stops at the Human Gate before any shared structure change |

