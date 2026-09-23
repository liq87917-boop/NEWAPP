# NEWAPP Blueprint V1.1

本目录是 GPT 作为项目大脑、Cline/其他执行器按任务执行时的初始基线。

## 关键架构
- NEWERP：PC 端 ERP。
- NEWAPP：移动端工作台。
- 两者共用同一个 SQL Server 数据库、同一个 OSS、同一套主数据。
- NEWAPP 不建立第二套客户/供应商主数据，不做无意义双向同步。
- 移动客户端不能直接连接 SQL Server，也不能内置 OSS AccessKeySecret。
- NEWAPP 服务端/Worker 从 `D:\VSCodeProject\NEWAPP\.env` 读取已有配置。自动化流程不得覆盖 `.env`，不得输出其中 Secret。

## 文件
- `义乌小商品外贸智能询价APP_产品技术规划方案_V1.1.docx`：总体产品/技术蓝图。
- `NEWAPP_UI页面原型与交互说明_V1.0.docx`：30 个页面与关键交互。
- `NEWAPP_OpenAPI_V1.yaml`：移动端/API 合同初稿。
- `NEWAPP_Database_DDL_V1.sql`：仅新增 app schema 与移动专属/扩展表；执行前必须先完成实际 NEWERP Schema Mapping。
- `NEWAPP_TASKS_V1.yaml`：68 个自动开发任务，GPT 负责规划/验收，执行模型逐项实施。

## 第一批执行顺序
`NEWAPP-001 → 002 → 003/004 → 005 → 006 → 007...`

尤其不能跳过 `NEWAPP-003`：必须先读取当前 NEWERP 数据库元数据，确认客户、供应商、用户、组织、字典等真实表与主键，再把 DDL 中的中性 `*Key` 映射成真实结构。
