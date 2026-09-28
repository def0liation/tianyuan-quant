# 开源范围 / Open-source scope

[中文 README](../README.md) · [English README](../README.en.md) · [文档索引 / Documentation](README.md)

## 中文

公开版本为当前主应用的源码快照，包含 React 前端、FastAPI 后端、测试、启动与验证脚本、通用配置示例，以及运行时需要的 Agent 提示词文档。保留后端 API 路由源码；这些路由定义属于程序实现，不包含使用者的接口凭证。

首次公开版本不导入本地 Git 历史、其他工作树或尚未完成的轻量版实现。`lightweight-stock-analysis/` 仅保留规划文档；`docs/superpowers/` 中的设计和计划是历史背景，不代表功能已经验收。

以下内容不属于公开文件：

- 真实 API Key、Token、密码、密钥文件，以及使用者的私有接口地址。
- `.env` 与个人配置，仅保留字段为空的 `.env.example`。
- 持仓、数据库、行情缓存、分析历史、运行产物和运行日志。
- `storage/`、`backend/app/storage/`、`backend/storage/` 中的本地数据。
- `.agents/`、`.claude/`、`.codex/`、`.superpowers/`、`.worktrees/` 等本地工具状态。
- 虚拟环境、依赖安装目录、编译产物、测试缓存和临时文件。

源码中的本机回环地址、公开数据源地址，以及测试中使用的 `example.com`、`.test`、`.invalid` 等示例地址不是使用者的私有配置。示例密钥仅限明显的测试占位值，不能替换为真实凭证后提交。

`.gitignore` 不会自动移除已提交的秘密。后续发布应检查待提交文件、Git 暂存内容和历史；不要以忽略规则或一次模式扫描代替人工复核。发现泄露时，应先在提供方撤销或轮换凭证，再处理公开历史；不要在 Issue 中粘贴泄露内容。

MIT 许可证适用于本仓库源码和文档。第三方依赖保留各自许可证；行情服务、LLM 服务与数据集的使用权限由其提供方决定，本仓库不附带相关服务账号或数据授权。

## English

The public version is a source snapshot of the main application: the React frontend, FastAPI backend, tests, launch and validation scripts, generic configuration examples, and Agent prompt documents required at runtime. Backend API route definitions remain public because they are part of the application implementation; users' API credentials are excluded.

The initial publication does not import local Git history, other worktrees, or the unfinished lightweight implementation. `lightweight-stock-analysis/` contains planning documents only. Designs and plans under `docs/superpowers/` provide historical context, not evidence of completed features.

The following are excluded:

- Real API keys, tokens, passwords, key files, and users' private endpoint addresses.
- `.env` and personal configuration; only the blank credential fields in `.env.example` are included.
- Portfolios, databases, market caches, analysis history, runtime artifacts, and logs.
- Local data under `storage/`, `backend/app/storage/`, and `backend/storage/`.
- Local tool state such as `.agents/`, `.claude/`, `.codex/`, `.superpowers/`, and `.worktrees/`.
- Virtual environments, installed dependencies, build output, test caches, and temporary files.

Loopback URLs, public provider URLs, and reserved example domains such as `example.com`, `.test`, and `.invalid` are generic implementation or test references. Test credentials must remain obvious dummy values; never replace them with real credentials in a commit.

`.gitignore` does not remove secrets already committed. Review candidate files, the Git index, and history before subsequent releases. Ignore rules and pattern scans are not substitutes for human review. If credentials leak, revoke or rotate them with the provider before addressing the published history; do not paste them into an issue.

The MIT license covers repository code and documents. Dependencies retain their own licenses. Market-data services, LLM services, and datasets remain subject to their providers' terms; no service accounts or data licenses are included.
