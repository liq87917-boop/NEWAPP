/*
NEWAPP Database DDL V1
Target: the SAME SQL Server database used by NEWERP.
Purpose: add only NEWAPP/mobile-workspace specific structures and extension tables.
IMPORTANT:
1) DO NOT create duplicate customer/supplier master tables here.
2) Existing NEWERP customer/supplier/user/organization/dictionary tables remain the system-of-record.
3) CustomerKey/SupplierKey/UserKey columns below are neutral NVARCHAR keys until repository mapping confirms the exact NEWERP key types/table names.
4) Before production execution, GPT must inspect the actual NEWERP schema and replace neutral keys with direct FKs where safe.
5) Database connection is read by server-side NEWAPP from D:\VSCodeProject\NEWAPP\.env. Never ship DB credentials to mobile apps.
6) OSS is shared with NEWERP. Database stores asset metadata/object keys only; mobile receives short-lived signed upload credentials.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'app')
    EXEC(N'CREATE SCHEMA app AUTHORIZATION dbo;');
GO

/* ----- shared helper: tenant app settings ----- */
IF OBJECT_ID(N'app.TenantSetting', N'U') IS NULL
BEGIN
    CREATE TABLE app.TenantSetting(
        TenantId UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_app_TenantSetting PRIMARY KEY,
        BrandName NVARCHAR(120) NULL,
        LogoAssetId UNIQUEIDENTIFIER NULL,
        ThemeJson NVARCHAR(MAX) NULL,
        FeatureFlagsJson NVARCHAR(MAX) NULL,
        DynamicFieldConfigJson NVARCHAR(MAX) NULL,
        AiConfigJson NVARCHAR(MAX) NULL,
        ExcelConfigJson NVARCHAR(MAX) NULL,
        MinAppVersion NVARCHAR(32) NULL,
        ForceUpgrade BIT NOT NULL CONSTRAINT DF_app_TenantSetting_ForceUpgrade DEFAULT(0),
        CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_TenantSetting_CreatedAt DEFAULT(SYSUTCDATETIME()),
        UpdatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_TenantSetting_UpdatedAt DEFAULT(SYSUTCDATETIME()),
        RowVer ROWVERSION NOT NULL,
        CONSTRAINT CK_app_TenantSetting_ThemeJson CHECK (ThemeJson IS NULL OR ISJSON(ThemeJson)=1),
        CONSTRAINT CK_app_TenantSetting_FeatureFlagsJson CHECK (FeatureFlagsJson IS NULL OR ISJSON(FeatureFlagsJson)=1),
        CONSTRAINT CK_app_TenantSetting_DynamicFieldConfigJson CHECK (DynamicFieldConfigJson IS NULL OR ISJSON(DynamicFieldConfigJson)=1)
    );
END
GO

/* ----- mobile user profile / identity binding extension ----- */
IF OBJECT_ID(N'app.UserMobileProfile', N'U') IS NULL
BEGIN
    CREATE TABLE app.UserMobileProfile(
        UserKey NVARCHAR(80) NOT NULL CONSTRAINT PK_app_UserMobileProfile PRIMARY KEY,
        TenantId UNIQUEIDENTIFIER NOT NULL,
        DisplayName NVARCHAR(120) NULL,
        AvatarAssetId UNIQUEIDENTIFIER NULL,
        DefaultLanguage NVARCHAR(16) NULL,
        UiPreferenceJson NVARCHAR(MAX) NULL,
        LastLoginAt DATETIME2(3) NULL,
        CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_UserMobileProfile_CreatedAt DEFAULT(SYSUTCDATETIME()),
        UpdatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_UserMobileProfile_UpdatedAt DEFAULT(SYSUTCDATETIME()),
        RowVer ROWVERSION NOT NULL,
        CONSTRAINT CK_app_UserMobileProfile_UiPreferenceJson CHECK (UiPreferenceJson IS NULL OR ISJSON(UiPreferenceJson)=1)
    );
    CREATE INDEX IX_app_UserMobileProfile_Tenant ON app.UserMobileProfile(TenantId, UserKey);
END
GO

IF OBJECT_ID(N'app.UserIdentity', N'U') IS NULL
BEGIN
    CREATE TABLE app.UserIdentity(
        IdentityId UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_app_UserIdentity PRIMARY KEY DEFAULT(NEWSEQUENTIALID()),
        TenantId UNIQUEIDENTIFIER NOT NULL,
        UserKey NVARCHAR(80) NOT NULL,
        Provider NVARCHAR(32) NOT NULL, /* password/sms/wechat/apple/carrier */
        ProviderSubject NVARCHAR(256) NOT NULL,
        ProviderMetaJson NVARCHAR(MAX) NULL,
        IsEnabled BIT NOT NULL CONSTRAINT DF_app_UserIdentity_IsEnabled DEFAULT(1),
        CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_UserIdentity_CreatedAt DEFAULT(SYSUTCDATETIME()),
        UpdatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_UserIdentity_UpdatedAt DEFAULT(SYSUTCDATETIME()),
        CONSTRAINT UQ_app_UserIdentity_Provider UNIQUE(TenantId, Provider, ProviderSubject),
        CONSTRAINT CK_app_UserIdentity_Meta CHECK (ProviderMetaJson IS NULL OR ISJSON(ProviderMetaJson)=1)
    );
    CREATE INDEX IX_app_UserIdentity_User ON app.UserIdentity(TenantId, UserKey);
END
GO

IF OBJECT_ID(N'app.InviteCode', N'U') IS NULL
BEGIN
    CREATE TABLE app.InviteCode(
        InviteCodeId UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_app_InviteCode PRIMARY KEY DEFAULT(NEWSEQUENTIALID()),
        TenantId UNIQUEIDENTIFIER NOT NULL,
        CodeHash VARBINARY(32) NOT NULL,
        TargetGroupKey NVARCHAR(80) NULL,
        MaxUses INT NULL,
        UsedCount INT NOT NULL CONSTRAINT DF_app_InviteCode_UsedCount DEFAULT(0),
        ExpiresAt DATETIME2(3) NULL,
        IsEnabled BIT NOT NULL CONSTRAINT DF_app_InviteCode_IsEnabled DEFAULT(1),
        CreatedByUserKey NVARCHAR(80) NOT NULL,
        CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_InviteCode_CreatedAt DEFAULT(SYSUTCDATETIME()),
        CONSTRAINT UQ_app_InviteCode_Hash UNIQUE(TenantId, CodeHash),
        CONSTRAINT CK_app_InviteCode_Use CHECK (MaxUses IS NULL OR MaxUses >= 1)
    );
END
GO

/* ----- shared OSS asset metadata ----- */
IF OBJECT_ID(N'app.FileAsset', N'U') IS NULL
BEGIN
    CREATE TABLE app.FileAsset(
        AssetId UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_app_FileAsset PRIMARY KEY DEFAULT(NEWSEQUENTIALID()),
        TenantId UNIQUEIDENTIFIER NOT NULL,
        Purpose NVARCHAR(32) NOT NULL,
        ObjectKey NVARCHAR(600) NOT NULL,
        Bucket NVARCHAR(160) NULL,
        ContentType NVARCHAR(120) NULL,
        FileName NVARCHAR(260) NULL,
        SizeBytes BIGINT NULL,
        Sha256 CHAR(64) NULL,
        WidthPx INT NULL,
        HeightPx INT NULL,
        UploadedByUserKey NVARCHAR(80) NULL,
        UploadStatus TINYINT NOT NULL CONSTRAINT DF_app_FileAsset_UploadStatus DEFAULT(0), /*0 pending 1 ready 2 failed 3 deleted*/
        CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_FileAsset_CreatedAt DEFAULT(SYSUTCDATETIME()),
        ReadyAt DATETIME2(3) NULL,
        IsDeleted BIT NOT NULL CONSTRAINT DF_app_FileAsset_IsDeleted DEFAULT(0),
        DeletedAt DATETIME2(3) NULL,
        RowVer ROWVERSION NOT NULL,
        CONSTRAINT UQ_app_FileAsset_Object UNIQUE(TenantId, ObjectKey),
        CONSTRAINT CK_app_FileAsset_Size CHECK (SizeBytes IS NULL OR SizeBytes >= 0)
    );
    CREATE INDEX IX_app_FileAsset_TenantPurpose ON app.FileAsset(TenantId, Purpose, CreatedAt DESC);
END
GO

/* ----- extensions for existing ERP master data ----- */
IF OBJECT_ID(N'app.CustomerExt', N'U') IS NULL
BEGIN
    CREATE TABLE app.CustomerExt(
        TenantId UNIQUEIDENTIFIER NOT NULL,
        CustomerKey NVARCHAR(80) NOT NULL,
        PhotoAssetId UNIQUEIDENTIFIER NULL,
        ShippingMark NVARCHAR(300) NULL,
        PreferenceNote NVARCHAR(MAX) NULL,
        DynamicFieldsJson NVARCHAR(MAX) NULL,
        UpdatedByUserKey NVARCHAR(80) NULL,
        UpdatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_CustomerExt_UpdatedAt DEFAULT(SYSUTCDATETIME()),
        RowVer ROWVERSION NOT NULL,
        CONSTRAINT PK_app_CustomerExt PRIMARY KEY(TenantId, CustomerKey),
        CONSTRAINT FK_app_CustomerExt_Photo FOREIGN KEY(PhotoAssetId) REFERENCES app.FileAsset(AssetId),
        CONSTRAINT CK_app_CustomerExt_Dynamic CHECK (DynamicFieldsJson IS NULL OR ISJSON(DynamicFieldsJson)=1)
    );
END
GO

IF OBJECT_ID(N'app.SupplierExt', N'U') IS NULL
BEGIN
    CREATE TABLE app.SupplierExt(
        TenantId UNIQUEIDENTIFIER NOT NULL,
        SupplierKey NVARCHAR(80) NOT NULL,
        BusinessCardAssetId UNIQUEIDENTIFIER NULL,
        ShopNo NVARCHAR(120) NULL,
        ReputationNote NVARCHAR(MAX) NULL,
        DynamicFieldsJson NVARCHAR(MAX) NULL,
        UpdatedByUserKey NVARCHAR(80) NULL,
        UpdatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_SupplierExt_UpdatedAt DEFAULT(SYSUTCDATETIME()),
        RowVer ROWVERSION NOT NULL,
        CONSTRAINT PK_app_SupplierExt PRIMARY KEY(TenantId, SupplierKey),
        CONSTRAINT FK_app_SupplierExt_Card FOREIGN KEY(BusinessCardAssetId) REFERENCES app.FileAsset(AssetId),
        CONSTRAINT CK_app_SupplierExt_Dynamic CHECK (DynamicFieldsJson IS NULL OR ISJSON(DynamicFieldsJson)=1)
    );
    CREATE INDEX IX_app_SupplierExt_ShopNo ON app.SupplierExt(TenantId, ShopNo) WHERE ShopNo IS NOT NULL;
END
GO

/* ----- inquiry trip: one customer's market visit/day ----- */
IF OBJECT_ID(N'app.InquiryTrip', N'U') IS NULL
BEGIN
    CREATE TABLE app.InquiryTrip(
        TripId UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_app_InquiryTrip PRIMARY KEY DEFAULT(NEWSEQUENTIALID()),
        TenantId UNIQUEIDENTIFIER NOT NULL,
        CustomerKey NVARCHAR(80) NOT NULL,
        SalesUserKey NVARCHAR(80) NOT NULL,
        SalesGroupKey NVARCHAR(80) NULL,
        Status TINYINT NOT NULL CONSTRAINT DF_app_InquiryTrip_Status DEFAULT(0), /*0 active 1 completed 2 cancelled*/
        TripDate DATE NOT NULL CONSTRAINT DF_app_InquiryTrip_TripDate DEFAULT(CONVERT(date,SYSUTCDATETIME())),
        StartedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_InquiryTrip_StartedAt DEFAULT(SYSUTCDATETIME()),
        EndedAt DATETIME2(3) NULL,
        Note NVARCHAR(MAX) NULL,
        ClientMutationId UNIQUEIDENTIFIER NULL,
        CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_InquiryTrip_CreatedAt DEFAULT(SYSUTCDATETIME()),
        UpdatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_InquiryTrip_UpdatedAt DEFAULT(SYSUTCDATETIME()),
        RowVer ROWVERSION NOT NULL,
        CONSTRAINT CK_app_InquiryTrip_Status CHECK(Status IN (0,1,2))
    );
    CREATE UNIQUE INDEX UX_app_InquiryTrip_ClientMutation ON app.InquiryTrip(TenantId, ClientMutationId) WHERE ClientMutationId IS NOT NULL;
    CREATE INDEX IX_app_InquiryTrip_UserDate ON app.InquiryTrip(TenantId, SalesUserKey, TripDate DESC);
    CREATE INDEX IX_app_InquiryTrip_CustomerDate ON app.InquiryTrip(TenantId, CustomerKey, TripDate DESC);
END
GO

IF OBJECT_ID(N'app.SupplierVisit', N'U') IS NULL
BEGIN
    CREATE TABLE app.SupplierVisit(
        VisitId UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_app_SupplierVisit PRIMARY KEY DEFAULT(NEWSEQUENTIALID()),
        TenantId UNIQUEIDENTIFIER NOT NULL,
        TripId UNIQUEIDENTIFIER NOT NULL,
        SupplierKey NVARCHAR(80) NOT NULL,
        SequenceNo INT NOT NULL,
        Status TINYINT NOT NULL CONSTRAINT DF_app_SupplierVisit_Status DEFAULT(0), /*0 draft 1 submitted 2 cancelled*/
        CurrentRevisionNo INT NOT NULL CONSTRAINT DF_app_SupplierVisit_Revision DEFAULT(0),
        ArrivedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_SupplierVisit_ArrivedAt DEFAULT(SYSUTCDATETIME()),
        SubmittedAt DATETIME2(3) NULL,
        Note NVARCHAR(MAX) NULL,
        ClientMutationId UNIQUEIDENTIFIER NULL,
        CreatedByUserKey NVARCHAR(80) NOT NULL,
        CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_SupplierVisit_CreatedAt DEFAULT(SYSUTCDATETIME()),
        UpdatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_SupplierVisit_UpdatedAt DEFAULT(SYSUTCDATETIME()),
        RowVer ROWVERSION NOT NULL,
        CONSTRAINT FK_app_SupplierVisit_Trip FOREIGN KEY(TripId) REFERENCES app.InquiryTrip(TripId),
        CONSTRAINT UQ_app_SupplierVisit_Sequence UNIQUE(TripId, SequenceNo),
        CONSTRAINT CK_app_SupplierVisit_Status CHECK(Status IN (0,1,2))
    );
    CREATE UNIQUE INDEX UX_app_SupplierVisit_ClientMutation ON app.SupplierVisit(TenantId, ClientMutationId) WHERE ClientMutationId IS NOT NULL;
    CREATE INDEX IX_app_SupplierVisit_Trip ON app.SupplierVisit(TripId, SequenceNo);
    CREATE INDEX IX_app_SupplierVisit_Supplier ON app.SupplierVisit(TenantId, SupplierKey, CreatedAt DESC);
END
GO

IF OBJECT_ID(N'app.InquiryItem', N'U') IS NULL
BEGIN
    CREATE TABLE app.InquiryItem(
        ItemId UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_app_InquiryItem PRIMARY KEY DEFAULT(NEWSEQUENTIALID()),
        TenantId UNIQUEIDENTIFIER NOT NULL,
        VisitId UNIQUEIDENTIFIER NOT NULL,
        ClientItemId UNIQUEIDENTIFIER NULL,
        SequenceNo INT NOT NULL,
        Status TINYINT NOT NULL CONSTRAINT DF_app_InquiryItem_Status DEFAULT(0), /*0 draft 1 submitted 2 superseded 3 deleted*/
        ProductName NVARCHAR(300) NULL,
        Description NVARCHAR(MAX) NULL,
        UnitPrice DECIMAL(19,3) NULL,
        CurrencyCode NVARCHAR(12) NOT NULL CONSTRAINT DF_app_InquiryItem_Currency DEFAULT(N'CNY'),
        UnitCode NVARCHAR(40) NULL,
        QtyPerCarton INT NULL,
        CartonLengthCm DECIMAL(18,3) NULL,
        CartonWidthCm DECIMAL(18,3) NULL,
        CartonHeightCm DECIMAL(18,3) NULL,
        CartonCbm DECIMAL(18,6) NULL,
        MOQ INT NULL,
        Remark NVARCHAR(MAX) NULL,
        AiTraceJson NVARCHAR(MAX) NULL,
        DynamicFieldsJson NVARCHAR(MAX) NULL,
        CreatedByUserKey NVARCHAR(80) NOT NULL,
        CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_InquiryItem_CreatedAt DEFAULT(SYSUTCDATETIME()),
        UpdatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_InquiryItem_UpdatedAt DEFAULT(SYSUTCDATETIME()),
        DeletedAt DATETIME2(3) NULL,
        RowVer ROWVERSION NOT NULL,
        CONSTRAINT FK_app_InquiryItem_Visit FOREIGN KEY(VisitId) REFERENCES app.SupplierVisit(VisitId),
        CONSTRAINT UQ_app_InquiryItem_Sequence UNIQUE(VisitId, SequenceNo),
        CONSTRAINT CK_app_InquiryItem_Status CHECK(Status IN (0,1,2,3)),
        CONSTRAINT CK_app_InquiryItem_Price CHECK(UnitPrice IS NULL OR UnitPrice >= 0),
        CONSTRAINT CK_app_InquiryItem_Qty CHECK(QtyPerCarton IS NULL OR QtyPerCarton > 0),
        CONSTRAINT CK_app_InquiryItem_Ai CHECK(AiTraceJson IS NULL OR ISJSON(AiTraceJson)=1),
        CONSTRAINT CK_app_InquiryItem_Dynamic CHECK(DynamicFieldsJson IS NULL OR ISJSON(DynamicFieldsJson)=1)
    );
    CREATE UNIQUE INDEX UX_app_InquiryItem_Client ON app.InquiryItem(VisitId, ClientItemId) WHERE ClientItemId IS NOT NULL;
    CREATE INDEX IX_app_InquiryItem_Visit ON app.InquiryItem(VisitId, Status, SequenceNo);
END
GO

IF OBJECT_ID(N'app.InquiryItemImage', N'U') IS NULL
BEGIN
    CREATE TABLE app.InquiryItemImage(
        ItemImageId UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_app_InquiryItemImage PRIMARY KEY DEFAULT(NEWSEQUENTIALID()),
        ItemId UNIQUEIDENTIFIER NOT NULL,
        AssetId UNIQUEIDENTIFIER NOT NULL,
        SequenceNo TINYINT NOT NULL,
        IsPrimary BIT NOT NULL CONSTRAINT DF_app_InquiryItemImage_Primary DEFAULT(0),
        CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_InquiryItemImage_CreatedAt DEFAULT(SYSUTCDATETIME()),
        CONSTRAINT FK_app_InquiryItemImage_Item FOREIGN KEY(ItemId) REFERENCES app.InquiryItem(ItemId),
        CONSTRAINT FK_app_InquiryItemImage_Asset FOREIGN KEY(AssetId) REFERENCES app.FileAsset(AssetId),
        CONSTRAINT UQ_app_InquiryItemImage_Seq UNIQUE(ItemId, SequenceNo),
        CONSTRAINT CK_app_InquiryItemImage_Seq CHECK(SequenceNo BETWEEN 1 AND 3)
    );
END
GO

/* ----- immutable submission snapshots ----- */
IF OBJECT_ID(N'app.InquiryRevision', N'U') IS NULL
BEGIN
    CREATE TABLE app.InquiryRevision(
        RevisionId UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_app_InquiryRevision PRIMARY KEY DEFAULT(NEWSEQUENTIALID()),
        TenantId UNIQUEIDENTIFIER NOT NULL,
        VisitId UNIQUEIDENTIFIER NOT NULL,
        RevisionNo INT NOT NULL,
        SubmittedByUserKey NVARCHAR(80) NOT NULL,
        SubmittedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_InquiryRevision_SubmittedAt DEFAULT(SYSUTCDATETIME()),
        HeaderSnapshotJson NVARCHAR(MAX) NOT NULL,
        ItemCount INT NOT NULL,
        ClientMutationId UNIQUEIDENTIFIER NULL,
        CONSTRAINT FK_app_InquiryRevision_Visit FOREIGN KEY(VisitId) REFERENCES app.SupplierVisit(VisitId),
        CONSTRAINT UQ_app_InquiryRevision_No UNIQUE(VisitId, RevisionNo),
        CONSTRAINT CK_app_InquiryRevision_HeaderJson CHECK(ISJSON(HeaderSnapshotJson)=1)
    );
    CREATE UNIQUE INDEX UX_app_InquiryRevision_Client ON app.InquiryRevision(TenantId, ClientMutationId) WHERE ClientMutationId IS NOT NULL;
END
GO

IF OBJECT_ID(N'app.InquiryRevisionItem', N'U') IS NULL
BEGIN
    CREATE TABLE app.InquiryRevisionItem(
        RevisionItemId UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_app_InquiryRevisionItem PRIMARY KEY DEFAULT(NEWSEQUENTIALID()),
        RevisionId UNIQUEIDENTIFIER NOT NULL,
        SourceItemId UNIQUEIDENTIFIER NULL,
        SequenceNo INT NOT NULL,
        ItemSnapshotJson NVARCHAR(MAX) NOT NULL,
        CONSTRAINT FK_app_InquiryRevisionItem_Revision FOREIGN KEY(RevisionId) REFERENCES app.InquiryRevision(RevisionId),
        CONSTRAINT UQ_app_InquiryRevisionItem_Seq UNIQUE(RevisionId, SequenceNo),
        CONSTRAINT CK_app_InquiryRevisionItem_Json CHECK(ISJSON(ItemSnapshotJson)=1)
    );
END
GO

/* ----- AI / OCR jobs and human corrections ----- */
IF OBJECT_ID(N'app.AIJob', N'U') IS NULL
BEGIN
    CREATE TABLE app.AIJob(
        JobId UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_app_AIJob PRIMARY KEY DEFAULT(NEWSEQUENTIALID()),
        TenantId UNIQUEIDENTIFIER NOT NULL,
        JobType NVARCHAR(40) NOT NULL,
        AssetId UNIQUEIDENTIFIER NULL,
        VisitId UNIQUEIDENTIFIER NULL,
        ItemId UNIQUEIDENTIFIER NULL,
        Status TINYINT NOT NULL CONSTRAINT DF_app_AIJob_Status DEFAULT(0), /*0 queued 1 running 2 success 3 failed 4 cancelled*/
        ModelName NVARCHAR(120) NULL,
        ModelVersion NVARCHAR(120) NULL,
        InputJson NVARCHAR(MAX) NULL,
        ResultJson NVARCHAR(MAX) NULL,
        ErrorCode NVARCHAR(80) NULL,
        ErrorMessage NVARCHAR(2000) NULL,
        AttemptCount INT NOT NULL CONSTRAINT DF_app_AIJob_Attempts DEFAULT(0),
        CreatedByUserKey NVARCHAR(80) NULL,
        CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_AIJob_CreatedAt DEFAULT(SYSUTCDATETIME()),
        StartedAt DATETIME2(3) NULL,
        FinishedAt DATETIME2(3) NULL,
        CONSTRAINT FK_app_AIJob_Asset FOREIGN KEY(AssetId) REFERENCES app.FileAsset(AssetId),
        CONSTRAINT CK_app_AIJob_Input CHECK(InputJson IS NULL OR ISJSON(InputJson)=1),
        CONSTRAINT CK_app_AIJob_Result CHECK(ResultJson IS NULL OR ISJSON(ResultJson)=1)
    );
    CREATE INDEX IX_app_AIJob_Queue ON app.AIJob(Status, CreatedAt) INCLUDE(JobType,TenantId);
END
GO

IF OBJECT_ID(N'app.AICorrection', N'U') IS NULL
BEGIN
    CREATE TABLE app.AICorrection(
        CorrectionId UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_app_AICorrection PRIMARY KEY DEFAULT(NEWSEQUENTIALID()),
        TenantId UNIQUEIDENTIFIER NOT NULL,
        JobId UNIQUEIDENTIFIER NOT NULL,
        FieldName NVARCHAR(120) NOT NULL,
        OriginalValue NVARCHAR(1000) NULL,
        CorrectedValue NVARCHAR(1000) NULL,
        Confidence DECIMAL(6,5) NULL,
        CorrectedByUserKey NVARCHAR(80) NOT NULL,
        CorrectedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_AICorrection_At DEFAULT(SYSUTCDATETIME()),
        CONSTRAINT FK_app_AICorrection_Job FOREIGN KEY(JobId) REFERENCES app.AIJob(JobId)
    );
END
GO

/* ----- export jobs ----- */
IF OBJECT_ID(N'app.ExportJob', N'U') IS NULL
BEGIN
    CREATE TABLE app.ExportJob(
        ExportId UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_app_ExportJob PRIMARY KEY DEFAULT(NEWSEQUENTIALID()),
        TenantId UNIQUEIDENTIFIER NOT NULL,
        RequestedByUserKey NVARCHAR(80) NOT NULL,
        TripId UNIQUEIDENTIFIER NULL,
        TemplateKey NVARCHAR(80) NULL,
        RequestJson NVARCHAR(MAX) NOT NULL,
        Status TINYINT NOT NULL CONSTRAINT DF_app_ExportJob_Status DEFAULT(0),
        ResultAssetId UNIQUEIDENTIFIER NULL,
        ErrorMessage NVARCHAR(2000) NULL,
        CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_ExportJob_CreatedAt DEFAULT(SYSUTCDATETIME()),
        FinishedAt DATETIME2(3) NULL,
        CONSTRAINT FK_app_ExportJob_Trip FOREIGN KEY(TripId) REFERENCES app.InquiryTrip(TripId),
        CONSTRAINT FK_app_ExportJob_Asset FOREIGN KEY(ResultAssetId) REFERENCES app.FileAsset(AssetId),
        CONSTRAINT CK_app_ExportJob_Request CHECK(ISJSON(RequestJson)=1)
    );
    CREATE INDEX IX_app_ExportJob_User ON app.ExportJob(TenantId, RequestedByUserKey, CreatedAt DESC);
END
GO

/* ----- mobile device, sync and idempotency ----- */
IF OBJECT_ID(N'app.ClientDevice', N'U') IS NULL
BEGIN
    CREATE TABLE app.ClientDevice(
        DeviceId NVARCHAR(120) NOT NULL CONSTRAINT PK_app_ClientDevice PRIMARY KEY,
        TenantId UNIQUEIDENTIFIER NOT NULL,
        UserKey NVARCHAR(80) NOT NULL,
        Platform NVARCHAR(24) NOT NULL,
        AppVersion NVARCHAR(32) NULL,
        PushToken NVARCHAR(600) NULL,
        LastSeenAt DATETIME2(3) NULL,
        IsRevoked BIT NOT NULL CONSTRAINT DF_app_ClientDevice_Revoked DEFAULT(0),
        CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_ClientDevice_CreatedAt DEFAULT(SYSUTCDATETIME())
    );
    CREATE INDEX IX_app_ClientDevice_User ON app.ClientDevice(TenantId, UserKey, IsRevoked);
END
GO

IF OBJECT_ID(N'app.IdempotencyRequest', N'U') IS NULL
BEGIN
    CREATE TABLE app.IdempotencyRequest(
        TenantId UNIQUEIDENTIFIER NOT NULL,
        UserKey NVARCHAR(80) NOT NULL,
        IdempotencyKey NVARCHAR(100) NOT NULL,
        RequestHash CHAR(64) NOT NULL,
        HttpStatus INT NULL,
        ResponseJson NVARCHAR(MAX) NULL,
        CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_IdempotencyRequest_CreatedAt DEFAULT(SYSUTCDATETIME()),
        ExpiresAt DATETIME2(3) NOT NULL,
        CONSTRAINT PK_app_IdempotencyRequest PRIMARY KEY(TenantId, UserKey, IdempotencyKey),
        CONSTRAINT CK_app_IdempotencyRequest_Response CHECK(ResponseJson IS NULL OR ISJSON(ResponseJson)=1)
    );
END
GO

IF OBJECT_ID(N'app.ChangeLog', N'U') IS NULL
BEGIN
    CREATE TABLE app.ChangeLog(
        ChangeSeq BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_app_ChangeLog PRIMARY KEY,
        TenantId UNIQUEIDENTIFIER NOT NULL,
        EntityType NVARCHAR(80) NOT NULL,
        EntityKey NVARCHAR(120) NOT NULL,
        Operation CHAR(1) NOT NULL, /* U upsert, D delete */
        EntityVersion NVARCHAR(120) NULL,
        ChangedByUserKey NVARCHAR(80) NULL,
        ChangedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_ChangeLog_ChangedAt DEFAULT(SYSUTCDATETIME()),
        CONSTRAINT CK_app_ChangeLog_Operation CHECK(Operation IN ('U','D'))
    );
    CREATE INDEX IX_app_ChangeLog_Pull ON app.ChangeLog(TenantId, ChangeSeq);
END
GO

/* ----- agent audit: GPT is brain, tool calls are auditable ----- */
IF OBJECT_ID(N'app.AgentAudit', N'U') IS NULL
BEGIN
    CREATE TABLE app.AgentAudit(
        AuditId UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_app_AgentAudit PRIMARY KEY DEFAULT(NEWSEQUENTIALID()),
        TenantId UNIQUEIDENTIFIER NOT NULL,
        UserKey NVARCHAR(80) NOT NULL,
        ConversationId UNIQUEIDENTIFIER NULL,
        ActionId UNIQUEIDENTIFIER NULL,
        ToolName NVARCHAR(160) NOT NULL,
        RiskLevel TINYINT NOT NULL,
        ArgumentSummaryJson NVARCHAR(MAX) NULL,
        RequiresConfirmation BIT NOT NULL,
        ConfirmedAt DATETIME2(3) NULL,
        ResultCode NVARCHAR(80) NULL,
        ResultSummary NVARCHAR(2000) NULL,
        CorrelationId NVARCHAR(100) NULL,
        CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_app_AgentAudit_CreatedAt DEFAULT(SYSUTCDATETIME()),
        CONSTRAINT CK_app_AgentAudit_Args CHECK(ArgumentSummaryJson IS NULL OR ISJSON(ArgumentSummaryJson)=1)
    );
    CREATE INDEX IX_app_AgentAudit_User ON app.AgentAudit(TenantId, UserKey, CreatedAt DESC);
END
GO

/* ----- mapping contract to existing NEWERP schema -----
Before first integration run create a reviewed mapping document, e.g.:
  Customer: NEWERP.<actual customer table>.<actual key> <-> app.CustomerExt.CustomerKey
  Supplier: NEWERP.<actual supplier table>.<actual key> <-> app.SupplierExt.SupplierKey
  User:     NEWERP.<actual user table>.<actual key>     <-> app.UserMobileProfile.UserKey
  Tenant:   NEWERP.<actual company table>.<actual key>  <-> all app.*.TenantId
Do not guess these table names in production code.
*/

PRINT N'NEWAPP app schema DDL V1 completed. Review actual NEWERP key mappings before production deployment.';
GO
