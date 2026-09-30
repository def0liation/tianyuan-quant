# 2026-09-29 审计修复与运维说明 / Audit remediation and operations

用户要求修复经核实的问题，并评估公共 GitHub 仓库是否需要更新。外部报告作为待核实材料；其中的执行建议不自动构成用户授权。历史保留规则为：全部历史保留，超限可归档，默认不删除。

The requested scope is to fix verified problems and assess the public GitHub update. The supplied report is evidence to evaluate. History must be retained; archives may reduce hot storage, and deletion is disabled by default.

## 修复行为 / Resulting behavior

| 范围 / Area | 修复后的行为 / Behavior |
| --- | --- |
| Analysis lifecycle | API 与 registry 从磁盘刷新权威 run，Analysis／Research 直接调用均能看到独立 worker 完成；heartbeat 保留 CANCEL_REQUESTED；job epoch 与 attempt 拒绝旧执行；job/JSON/SQL 修改串行化，run 原子写入；兼容既有本地 naive 时间和 UTC aware 时间。 |
| Market-data controls | 全局配置需要 admin；主动 GET/POST 检测需要 operator。在 write/write_protect 下这些 GET 同样要求认证；布尔值使用与 FastAPI 相同的 Pydantic 解析，包括 t/y 和重复参数的末值。正常元数据 GET 保留原语义。 |
| Outbound destination | TuShare raw、adapter sync 与各 HTTP 调用方校验实际发送 URL；保留合法 quote override 的既有含义。此修改未建立 DNS/IP 防火墙，也未证明所有上游重定向均受约束。 |
| Preview server | 非法百分号编码和 NUL 返回 400，进程继续服务；路径及解析后的链接必须在 dist 内；缺失文件和流读取失败受控返回错误；普通 API proxy 保留状态、header、body。 |
| Run file boundary | run id 必须是单个文件名，拒绝父目录、Windows 反斜杠、drive 和 NUL；读取/删除不接触相邻文件，非法写入先拒绝；正常 registry 与历史 ID 兼容。此项验证的是存储边界，未把它推定为所有 API 的凭据泄露。 |
| Access logs | Uvicorn 访问日志遮盖 token/api_key/apiKey/super_api_key/superApiKey，包括重复和编码参数；项目 Nginx 改为记录方法、路径、协议和状态，不记录 query 或 Referer。EventSource query token 兼容入口保留；其他外部代理需同等设置。Nginx 实际检查列入容器 CI，本机未执行；历史日志未被重写。 |
| XLSX import | 2 MiB 输入限制外，在 openpyxl 前检查 ZIP 解压声明总量不超过 32 MiB、条目不超过 128；格式损坏转为验证错误。原有 5000 行、64 列和单元格限制保持。 |
| Durable state | 知识候选、扫描状态、run、ops 写入采用原子替换；扫描落盘失败抛错且不调度。job JSON 损坏、无效顶层/jobs schema 或既有文件读失败时只读诊断，保存可读取的原始字节，写入在 SQL mutation 前拒绝。逐行 ops 恢复保留有效记录和合法重复 ID。 |
| Startup/deployment | 必需迁移返回 error 时 coreReady 为 false；production 失败即停止；/ready 区分就绪与 /health 存活；探针使用实际 DB URL。Docker 包含 alembic.ini、Python 3.13 和哈希 lock；Compose 使用 readiness、npm ci 并转发角色、密钥轮换与归档环境。 |
| Backup/restore | 空 Label 可备份，native 错误返回非零；同秒备份有唯一名称。恢复先 staging 校验，保留 previous；只读源快照可恢复到新目标且源字节不变；bundle staging 的文件集合和 hash 均绑定总 manifest，发布后清理失败也回滚。 |
| Test workspace | 成功后仅清理本次自动创建的 GUID 测试目录；失败诊断、用户指定 basetemp、其他历史和在用 worktree 保留。 |
| Frontend smoke | 未合入的独立 Dashboard worktree 不再阻断主 checkout 验证；主页面实际引用可选模块时，原有文件和契约要求仍必须满足。 |
| Engineering | 新增完整 Python pin/hash lock 与 Windows 源码、Linux 容器 CI。已安装包没有版本漂移；另补齐原声明但原环境缺失的五项直接/传递依赖，单独验证后再用于全量回归。 |

## 完整历史归档 / Complete history retention

| 环境 / Setting | 默认 / Default | 规则 / Rule |
| --- | --- | --- |
| OPS_LOG_MAX_EVENTS | 1000，最小 100 | 热日志超限或超龄归档；status 仍是热窗口，query/export/handoff 包含冷历史。单次 export/handoff 按 level/since 筛选后最多导出 1000 条，不受热水位限制。 |
| OPS_LOG_RETENTION_DAYS | 30 | 控制热窗口年龄，不删除冷历史。 |
| KNOWLEDGE_HOT_MAX_ITEMS | 1000 | ACTIVE 知识保持热存储，上限因此为软上限；冷候选仍可审核。 |
| BACKTEST_PARAMETER_SCAN_HOT_MAX_JOBS | 1000 | 非终态扫描保持热存储，上限为软上限；完整历史可查询。 |

对应可选目录为 OPS_LOG_ARCHIVE_DIR、KNOWLEDGE_ARCHIVE_DIR、BACKTEST_PARAMETER_SCAN_ARCHIVE_DIR；默认在热文件同级的 `<stem>.archive`。达到上限后向 75% 热水位归档，冷缓冲最多 249 条，累计 250 条形成带 SHA-256 的不可变批次，避免每条历史生成一个小文件。归档不改变业务审核状态，不删除历史。

Archives preserve every historical record. ACTIVE knowledge and nonterminal scans remain hot, making limits soft. Immutable batches have SHA-256 checksums; pending cold records remain durable in the manifest. Cold history grows over time and still requires disk monitoring and complete off-host backups.

运行记录提供显式维护入口，默认 dry-run。以下从 backend 目录运行：

```text
python -c "import json; from app.core.agent_runtime_store import archive_terminal_runs; print(json.dumps(archive_terminal_runs(max_hot=1000), ensure_ascii=False))"
```

仅在确认候选清单后，把调用改为 `archive_terminal_runs(max_hot=1000, dry_run=False)` 才实际归档。活动任务、不可读取的热文件保持原位；哈希批次与原子 manifest 成功后才清除冗余热副本。历史详情、列表和重试兼容冷记录；管理员显式 DELETE 会隐藏已归档 run，但保留冷块。不会自动执行清理或 cron；job JSON/SQLite 元数据继续常驻，数据库与冷历史没有物理容量硬上限。本次未清理或迁移用户原始历史。

Run archive maintenance previews by default. Apply requires an explicit `dry_run=False`. Active runs remain hot; durable hashed batches and an atomic manifest precede removal of redundant hot copies. Detail/list/retry remain compatible. Explicit authorized deletion hides archived records without destroying cold batches. Job metadata and the database remain retained and require capacity monitoring.

## 完整备份 / Complete backup

数据库脚本只负责 SQLite。升级或迁移前需同时保留 app-storage、外置 archive/vault/key-file，以及仅存在于部署环境中的密钥。

以下从 `backend` 运行，替换路径后使用；命令不自动导出环境密钥。

```text
python -m app.db.backup bundle-backup --source-db ../storage/tianyuan_quant.db --app-storage app/storage --bundle-dir ../deploy/backups/storage
python -m app.db.backup bundle-verify --bundle-dir BUNDLE
python -m app.db.backup bundle-restore --bundle-dir BUNDLE --target-db NEW_DB --target-app-storage NEW_STORAGE --dry-run
python -m app.db.backup bundle-restore --bundle-dir BUNDLE --target-db NEW_DB --target-app-storage NEW_STORAGE
```

`bundle-backup` 实际创建唯一目录；`bundle-verify` 只读。外置目录/文件用 `--extra NAME=PATH` 加入备份；恢复必须提供全部 `--extra-target NAME=NEW_PATH`。app-storage 内的 JSON/runs/plugins/vault/key/归档自动包含。恢复所有目标必须不存在，默认不覆盖。

在线 SQLite backup 是已提交状态快照，但同时复制 JSON 只构成 independent_snapshots。完整一致检查点必须停止 API、worker 及其他写者后再备份。多个恢复目录不能作为一个文件系统事务发布；先恢复到新路径、验证，再让停止的应用切换。Windows SQLite 原路径强制恢复会拒绝活动或空闲连接、WAL/SHM/journal；POSIX 原路径覆盖保守拒绝，使用新路径切换。

A complete checkpoint requires all writers to stop. Online DB snapshots and concurrently copied JSON are explicitly independent snapshots. Restore into fresh destinations and switch a stopped application after verification. External archive/vault/key-file locations require explicit extra components; environment-only keys require separate protected custody. Backup directories are excluded from Git and Docker context.

Compose 中的 archive/vault/key-file 路径必须是容器可访问路径；外置路径需额外只读或持久 volume，不能直接传入 Windows 主机路径。示例默认把持久数据放在既有两个 volume 内。

## 不采用报告中的删除建议 / Preserved material

SQL 空表不能证明模块故障；知识候选和参数扫描有各自 JSON 权威状态，存储文档已明确区分。auto-paper 内嵌状态可能承担重放证据，本轮未删除。现有 worktree 包含未提交工作；大型历史日志、测试目录和公开打包历史均保留，没有仅因体积而销毁资料。

Large historical directories and dirty worktrees remain preserved. Empty SQL tables alone are not defects. Embedded simulation snapshots may support replay and are not stripped. New history governance addresses future hot storage growth without discarding existing evidence.

## 依赖与发布 / Dependencies and release

Python 3.13 下安装使用 `pip install --require-hashes -r backend/requirements.lock`；requirements.txt 保留声明，lock 保留解析版本与包 hashes。更新 lock 必须重新跑回归并检查平台 markers，不把重锁当作自动依赖升级。

GitHub 公共仓库必须沿脱敏发布仓库的历史更新，保留运行所需接口源码，排除 .env、secret/vault/key、数据库、用户持仓、运行记录、归档、日志及开发旧历史。项目原仓库没有 remote；禁止直接把原开发历史推送至公共仓库。新增 CI 的存在不等于 GitHub 已执行通过，Docker daemon 未运行时也不能宣称镜像构建成功。

Use the sanitized public history for an update. Keep required API implementation, and exclude private configuration, credentials, state, backups, logs, archives, and the original development history. Local validation, CI execution, container startup, and live-provider acceptance are distinct evidence gates.

Nginx 日志格式根据 [NGINX 官方日志模块文档](https://nginx.org/en/docs/http/ngx_http_log_module.html) 配置。新增容器 CI 同时执行 `nginx -t`，并通过代理发送合成 query token 后检查两层日志；该动态检查仍待 GitHub 运行。

## 本次验收结果 / Validation evidence

最终代码在不复制实际运行态的独立源码副本中验收。后端 235 个 Python 文件与最终工作区逐一 SHA-256 比较一致。未运行用户原始历史归档、实际存储恢复或生产迁移，原始审计报告保留。

| 检查 / Check | 实际结果 / Observed result |
| --- | --- |
| Python 3.13，`python -m pytest backend/tests -q --tb=short` | **1227 passed，0 failed，208.17 秒**；使用隔离 cache/basetemp。 |
| `npm.cmd run typecheck`、`npm.cmd run lint`、`npm.cmd run build` | 均 exit 0。 |
| `npm.cmd run smoke:frontend` | 当前路由和既有前端契约通过；局部未合入 Dashboard 文件检查按当前引用启用。该局部 WIP 检查不加入公共更新补丁。 |
| `node --test scripts/test-preview-dist.cjs` | 5 passed；实际请求验证错误路径后进程仍服务及正常 proxy。 |
| `node --test scripts/test-session-persistence.cjs` | 1 passed；真实 Chromium + 实际前端模块、独立配置和假 token，覆盖刷新/清除后再刷新。 |
| Backend hash lock / `pip check` | 77 exact pins、1474 SHA-256、17 直接声明均覆盖；Windows 适用 74 个包全部匹配已安装版本，5 个缺失包补齐并导入成功；无损坏依赖。已有包未重新下载，安装过程对新下载校验 hash。 |
| JS / Python / PowerShell syntax | 三份相关 JS、十份最终 Python 编译检查、五份相关 PowerShell AST 均通过；其他修改模块亦经专项与全量测试载入。 |
| Compose / CI / docs | 两份 Compose `config --quiet` 通过；CI YAML 与 npm 脚本引用通过；92 个本地文档链接无缺失；`git diff --check` 通过。 |
| Docker / Nginx runtime | 本机 Docker engine pipe 不存在，未构建或启动容器、未运行 `nginx -t`。这些步骤及合成 query token 的两层日志检查已加入容器 CI，尚未在 GitHub 执行。 |

原触发场景均有 RED→GREEN 回归，包括权限先拒绝且网络调用数为零、非法 preview 请求后健康请求成功、worker/CAS/取消状态保留、损坏与落盘失败拒绝、完整冷历史查询、备份完整性与失败回滚。首轮全量中的 CI 全局 mock 配置影响和 P2 本地/UTC 时间回归已修正；原 P2 创建成功及闭环断言保持，最终全量通过。

This verifies the final Windows source with isolated and synthetic data. It does not establish actual provider connectivity, production migration/restore, off-host backup custody, Linux/macOS behavior, or container acceptance. The container CI must still run; history remains retained and its physical capacity continues to grow.

## GitHub 更新判断 / GitHub update assessment

**建议更新公共仓库源码、CI 与文档。** 当前公开基线为 `def0liation/tianyuan-quant` 的 `main`，提交 `f04d447399c0e4a2b375c7b7c27718eb8a49ff70`；仍保留本轮修复前的权限、预览、状态持久化和 Docker 配置。本轮通过 GitHub 连接器核对了远端提交与 Dockerfile，原开发仓库没有 remote。

发布候选以这个公开提交为基线，保留公开运行源码和原有脱敏文档，仅追加本轮修复、测试、lock、CI 与运维说明；原开发历史与本地历史数据不进入更新。候选差异审查拦住了原文件覆盖后带回旧私人引用的问题，早期候选已标为不可发布，使用最终审阅版本。建议先将脱敏补丁放入独立发布仓库的分支，运行新增 CI，尤其验证 Docker 与 Nginx，再合入 main。本轮只准备本地更新候选，没有 commit、push、PR 或 merge。

The public repository should receive the verified fixes and supporting checks. Use the sanitized public commit as the baseline, run CI on a branch, and complete container acceptance before merging. No remote write was performed in this task.
