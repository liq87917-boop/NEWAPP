# NEWAPP V4.0 项目规划文件

此目录用于保存 2026-10-14 确认的 NEWAPP V2.0—V4.0 总体规划、功能清单、业务流程和商业模式。

## 文件

- `NEWAPP_V4_Plan.md`：完整规划文本，GitHub 在线可直接阅读。
- `NEWAPP_V4_Flowcharts.md`：Mermaid 架构与业务流程图源码。
- `NEWAPP_V4_Plan.docx`：可编辑 Word 文档。
- `NEWAPP_V4_Plan.pdf`：PDF 阅读版。
- `NEWAPP_V4_Package.zip`：上述四份文件的压缩包。

## 文件版本说明

由于本次 GitHub 接口不能直接接收当前会话已有的二进制附件，仓库中的 Word、PDF 和 ZIP 是**根据原规划全文重新生成的文字版**，不是原始下载文件的字节复制。核心文字需求保留，但原始文档中的图片、图表排版和视觉设计不会完全一致。流程图请使用 `NEWAPP_V4_Flowcharts.md` 读取和编辑。

此文档是规划基线，尚未代表 NEWAPP 的实际代码与数据库开发状态。商业价格、收入测算和设备数量等均属于待验证或待实施方案。

## Windows 本地同步

```powershell
Set-Location D:\VSCodeProject\NEWAPP
git status --short
git pull --ff-only origin main
```

如果 Git 提示存在未提交改动或无法 fast-forward，请先处理本地分支状态，不要直接执行 `git reset --hard` 或 `git stash` 以免丢失当前项目工作。
