# 数据库迁移与回滚

在 `services/api` 运行，先 `uv sync --frozen`，并显式设置目标
`FRONTIER_DATABASE_URL`。应用不会自动创建表。

```sh
uv run alembic upgrade head
uv run alembic current
uv run alembic check
```

回滚前先备份目标数据库，停止写入并确认目标环境。开发环境的初始迁移可用：

```sh
uv run alembic downgrade base
```

此命令会删除 `users` 表及其中的数据；不能对真实用户数据库未经授权执行。
`0002_foundation` 新增来源、会话、任务与审计表；可用
`alembic downgrade 0001_users` 仅回退基础阶段，但也会删除这些新增表的数据。
`0003_knowledge`，新增版本文档、引用块、概念、证据和知识状态，
以及来源文件夹范围和同步归属。`alembic downgrade 0002_foundation` 会删除这些知识表，
保留原基础来源/用户等表；同样须先备份并停止写入，不能未经授权回滚真实用户数据。
`0004_planning` 新增目标、计划、只追加修订、任务投影和每日完成记录。
`alembic downgrade 0003_knowledge` 删除本阶段的目标和计划历史，保留独立来源及知识证据。
同样需要备份和停止写入；回滚不能恢复被删除的学习计划。
`0005_tutoring` 新增经用户确认的页面快照和导学轮次。
`alembic downgrade 0004_planning` 删除本阶段的会话、原文片段、追问及关联 TUTOR_GUIDE
任务元数据，保留既有知识源/画像/目标/计划。停止 API 和 Worker 并备份后才可执行。
`0006_conversation`，新增个人对话导入、解析快照和候选选择。
`alembic downgrade 0005_tutoring` 删除本阶段材料及 CONVERSATION_IMPORT 任务；同时从
已有计划修订 JSON 的任务中移除 `conversation_ref` 字段，以兼容上一版本的 strict 契约。
任务本身、顺序、修订与独立知识证据保留，原对话来源将不可用，删除的材料/引用元数据不能
靠再次升级恢复。须先停止 API/Worker、备份并确认目标环境；禁止对真实用户数据擅自回滚。
`tests/test_share_import.py` 额外用有数据的计划验证本回滚与再升级，而非仅检查空表。
升级后再次 `alembic check` 检查 ORM 与数据库差异。
新增迁移：`uv run alembic revision --autogenerate -m description`，人工审核
upgrade/downgrade 后提交；不将自动生成脚本视为已经验证。

`tests/test_migrations.py` 只在显式提供 `FRONTIER_TEST_DATABASE_URL` 时运行，
并拒绝对有业务表的数据库清理。测试执行 upgrade → check → downgrade → upgrade →
downgrade，必须使用单独的可丢弃数据库，禁止指定开发/生产数据库。


当前 head：`0009_real_connections`。`0007_assessment_artifacts` 新增短测、Markdown 草稿、
审核 Diff/PR 状态与独立加密写凭据。回退到 `0006_conversation` 会删除本阶段短测、草稿、
GITHUB_WRITEBACK 任务和 SOURCE_COMPREHENSION 证据，并撤销写目录；对已失去全部证据的
状态恢复 UNKNOWN（保留用户自报覆盖，标 LOW）。外部 GitHub 分支/PR 无法由回滚撤回。
会话、独立来源/证据和历史计划保留；已删除的短测/草稿无法通过再升级恢复。
`0008_ownership` 增加默认拒绝的模型处理偏好和设置版本；回退至 `0007_assessment_artifacts`
会丢失这些偏好。先停止 API/Worker，再备份和回滚，必须同时恢复与目标 schema 匹配的应用版本。
禁止将当前 ORM/API 运行于旧 schema；有数据回滚测试直接校验保留记录，再升级后验证当前 API。

`0009_real_connections` 新增密码/恢复摘要、正式会话方法、GitHub App 连接/OAuth 状态、
UTC 每日模型预算/调用记录和逐轮云处理授权。已有会话方法回填 DEVELOPMENT；已有导学轮次
回填 cloud_processing_allowed=false，不会因部署启用云模型自动上传旧材料。
用户授权 generation 用于拒绝断开/恢复之后的迟到 OAuth 回调。

回退到 `0008_ownership` 会撤销 PASSWORD 会话、断开所有 App 来源并撤销写目录、删除
密码/恢复摘要、连接凭据、OAuth 状态及模型计量。原用户/学习材料与正式账号 `account:`
内部命名空间保留，旧 Mock 的允许字符不能匹配这些账号。再升级不能恢复已删凭据，
正式账号需从备份恢复；不得通过改用户名或开启 Mock 绕过认证。
`tests/security/test_password_auth.py` 验证有学习记录的回滚、命名空间隔离与再升级。
这些测试只使用可丢弃库；部署数据库仍需另做备份恢复演练。

实际备份恢复工具：`FRONTIER_TEST_DATABASE_URL=... uv run python -m tests.acceptance.backup_restore`。
仅允许根 README 所列本机 Compose 测试连接，创建两个新库执行 pg_dump/pg_restore，验证
学习导出/原密码/加密凭据后清理新库；不覆盖现有库。它不作为生产恢复命令。
实测证据与正式恢复边界见 `docs/evidence/release-verification/README.md`。
