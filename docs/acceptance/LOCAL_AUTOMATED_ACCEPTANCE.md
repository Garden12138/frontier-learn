# 本地自动化验收

日期：2026-11-11（本机 Asia/Shanghai，结构化时间为 UTC）。
**结论：PARTIAL。现有本地工程验收通过；真实 GitHub 容器导入受 DNS 安全条件阻塞，
真实模型/App/PR、真人学习与生产发布不在通过结论内。**

## 输入、环境和隔离

开始 HEAD `bdf9a8f9823916365545dc1387e86bbafe36db0c`，分支 codex/local-trial。
初始 13 个已跟踪修改、11 个新文件，包含认证修复及其测试/契约，已备份并保留。
本轮仅修复恢复验收脚本的旧 schema 断言，新增回归；不增加产品功能或迁移。
精确的被测文件摘要与执行清单见 [checks.json](evidence/checks.json)。
整合后复核提交与分支见 [交付总结](../review/UPGRADE_CHATGPT_SUMMARY.md)。

| 环境 | 实际值 |
|---|---|
| Mac | macOS 26.5.1 (25F80)，arm64 |
| Git / Node / pnpm | 2.48.1 / 22.23.2 / 10.28.2 |
| Python / uv | 宿主 3.12.11 / 0.6.10；日常 API 容器 3.12.16 |
| Docker / Compose / PG | 29.8.2 / v5.5.0 / PostgreSQL 16.15 aarch64 |
| 浏览器 | Playwright 1.64.1 / Chrome for Testing 156.0.8078.4；实际 MV3 临时独立 profile |
| 开发配置 | LLM=local_rules，Mock=false，写回=false；真实 App/加密密钥未配置 |
| 日常端口 | Web 5176、API 18000、PG 55433，保留原命名卷 |
| 回归端口 | PG 55432 / frontier_test；浏览器 API 18002、Web 5175；setup API 18001 |
| 新部署演练 | Compose 项目 frontier-learn-upgrade-check，PG 55434、API 18003，独立新卷；无用户资料 |

所有使用 frontier_test 的套件顺序运行。开始仅有 alembic_version，无业务表；
fixture 拒绝已有业务表/非测试库，结束时回滚自身表。真实备份恢复另建两个随机临时测试库，
最后清理，不覆盖日常库。测试运行器移除外部模型/GitHub 密钥环境，使用显式 Fake。
没有调用付费模型，也没有修改 notes、真实外部分支/PR 或第三方资料。

## 实际命令与结果

下列从仓库根目录执行，标记 API 的在 services/api 执行。
`uv run` 与锁定 `.venv/bin` 是同一已验证环境；本轮静态/pytest 实际使用 `.venv/bin`，
避免隐式同步影响验收。命令、退出码、耗时、日志 SHA-256 原样保存在 checks.json。

| 检查 | 实际命令 | 结果 |
|---|---|---|
| 依赖 | pnpm install --frozen-lockfile；uv sync --frozen --project services/api | 通过；另验证 --offline 方式，锁文件未变 |
| TS lint | pnpm lint | 通过，无警告 |
| TS strict | pnpm typecheck | 通过，含 WXT prepare |
| 类型漂移 | pnpm types:check | 通过 |
| 客户端测试 | pnpm test | 26 passed / 0 failed / 0 skipped（shared 6、extension 19、web 1） |
| 构建 | pnpm build | Web/Vite 与 Chrome MV3 通过；Web JS 354.37KB，扩展总计约 273.6KB |
| Ruff（API） | .venv/bin/ruff check .；.venv/bin/ruff format --check . | 最终通过；121 文件格式符合 |
| mypy（API） | .venv/bin/mypy | 通过，120 个源码文件 strict |
| OpenAPI（API） | .venv/bin/python -m app.export_openapi --check | JSON/YAML 与运行时同源一致；未改 DTO |
| 后端全量（API） | .venv/bin/pytest -q --junitxml=临时日志路径 | 最终 217 passed / 0 failed / 0 skipped（117.68s）；初始 216 不重复累计 |
| 初始化浏览器 | pnpm test:setup | 3 passed / 0 failed / 0 skipped |
| Web 业务 E2E | FRONTIER_TEST_DATABASE_URL=专用测试URL pnpm test:sources | 8 passed / 0 failed / 0 skipped（30.8s） |
| 真实 MV3 业务 E2E | FRONTIER_TEST_DATABASE_URL=专用测试URL pnpm test:extension | 4 passed / 0 failed / 0 skipped（20.5s） |
| 真实公开页面 | FRONTIER_LIVE_PAGE_CHECKS=true pnpm test:live-pages | 11 passed / 0 failed / 0 skipped（40.3s），10 固定页 + 实际 MV3 三页场景 |
| 实际备份恢复（API） | FRONTIER_TEST_DATABASE_URL=专用测试URL .venv/bin/python -m tests.acceptance.backup_restore | 修复后通过，0010，27 表、23,386 bytes 导出一致、原密码和原密钥通过 |
| 完整部署 | docker compose -p frontier-learn-upgrade-check --env-file infra/local-trial.env.example -f infra/docker-compose.yml up -d --build --wait | 独立端口覆盖，首次空库构建/迁移/API/Worker 成功，73.35s |
| ORM 检查 | 上述项目 exec -T api .venv/bin/alembic current / check | 0010_concept_check (head)；No new upgrade operations detected |
| 备份命令 | 停止新部署 API/Worker 后 exec -T db pg_dump -U frontier -d frontier -Fc --no-owner | 空白演练 dump 75,680 bytes，0600，移出仓库；未备份用户资料 |
| 交付 Web | FRONTIER_API_PROXY=http://127.0.0.1:18000 pnpm --filter @frontier/web dev --host 127.0.0.1 --port 5176 | 启动，Web 代理 /api/v1/health 200；日常 health/ready 均 200 |
| 仓库检查 | node scripts/check-repository.mjs；git diff --check | 通过：305 文件、129 本地链接、2 原文 blob、6 忽略规则；未命中常见密钥模式 |

工程内容提交 `c59d11917d26c2c870ebdd8cdbeffbb652ae9f11` 已推送；原始 bdf9a8f + 被测摘要
与该提交的源码一致，后续仅收尾文档。整合分支另执行核心认证/学习/PR/数据与恢复 32 项通过，不与上述全量重复计数。
新部署停止保留卷后重启成功（23.67s），空白验收容器/卷已清理，日常服务继续运行。

完整测试 URL：`postgresql+asyncpg://frontier:test_only@127.0.0.1:55432/frontier_test`。
依赖安装的 pnpm 提示只忽略 spawn-sync 的依赖构建脚本；没有额外批准，现有测试/构建通过。
最终交付插件恢复为 API 18000 构建，避免把 test:extension 的 18002 产物交给用户。

## 数据库迁移和恢复

`test_migrations.py` 实际执行升级→元数据一致性→降级→再升级→清理。
包含边界题/概念题/账号等带数据回滚回归；`0010` 兼容处理保留旧边界题并移除概念题派生数据。
仅在可丢弃库实测，不对开发/用户库降级，不以回滚替代备份。
恢复演练在新建两库执行 pg_dump/pg_restore，原密码与原密钥解密验证通过，
结果见 [backup-restore.json](evidence/backup-restore.json)。

## 业务链路与真实组件

| 业务步骤 | 本轮实测依据 | 结果与边界 |
|---|---|---|
| 注册/登录/恢复/权限 | security/test_password_auth.py、test_authorization.py；real-connections.spec.ts、MV3 密码登录 | 真实 scrypt/Cookie/bearer、恢复与跨用户隔离；外部 GitHub App 是模拟协议 |
| 连接→导入→画像 | test_github_ingest.py、test_ingest_boundaries.py、sources.spec.ts | 实际 API/Worker/PG/UI；Mock GitHub；坏文件、限额、幂等、取消、撤销、安全失败保留 |
| 目标→计划→今日学习 | test_planner.py、planning.spec.ts | 空画像、自评拒绝、采纳/暂停/跳过/插入/历史恢复/重规划，完成不提升掌握 |
| 网页导学→追问→跨端 | test_citations.py、current-page.spec.ts、live-page 组 | 合成十页 + 真实公开页；实际 Chromium/MV3/临时授权/抽取定位/API/Worker；默认本地规则 |
| 理解验证→学习证据 | test_concept_check.py、test_learning_loop.py、concept-check.spec.ts | Fake 拟题、答案隐藏、作答/确认分离、失败/取消/新任务恢复、撤销迟到拒绝；LOW 证据 |
| 草稿→下载/审核→PR | learning-loop.spec.ts、test_writeback_safety.py | 实际前后端草稿/Diff/审批，模拟 Git tree/commit/ref/PR，不写真实仓库 |
| 合并→再索引→下一计划 | test_merged_pr_reindexes_and_replans_once；test_two_sessions_confirmed_evidence_replans_without_mastery | 模拟合并证明、实际 PG 再索引/计划修订；正向继续检查，负向复习 |
| Self-Attention 两轮 | test_attention_trial.py | 固定公开 SHA 原始笔记/代码 + Fake 模型；实际导入/引用/计划 API；不是在线同步或真人学习 |
| 对话→候选→计划 | test_share_import.py、conversation.spec.ts | 合成分享/403/粘贴回退、角色/代码/未知、确认/拒绝及内部删除 |
| 导出/撤销/删除 | test_portability.py、安全组、learning-loop.spec.ts | 实际所有权边界、导出含 Markdown 无凭据/未作答答案键、超限失败、删除使会话失效 |

链路由真实前后端套件及集成测试分段衔接，**不是一个真人从头学到尾的成功记录**。
结构化日志只有 request_id/task_id/状态/错误码等，不记录 token 或敏感正文。

## 失败、修复和保留日志

1. 恢复脚本初始运行退出 1：`ISOLATED_RESTORE_CHECK_FAILED`。
   新回归明确复现 `tests/acceptance/backup_restore.py` 将实际 0010 错判为
   `0009_real_connections`（AssertionError）。数据导出和密码核对已完成，根因是旧版本常量。
   最小修复读取 Alembic ScriptDirectory 的当前 head，断言与报告共同使用，未弱化校验。
   新测试同时要求当前 schema/原密码/密钥/完整导出成功，并拒绝被替换为 `{}` 的导出。
   红测试 1 failed →绿测试 1 passed →真实 dump/restore passed，证据见 checks.json。
2. 本轮修改后 Ruff 暂报单行 102>100 与 format 差异，格式化该脚本后均通过；没有关闭规则。
3. 仓库链接检查在验收/交付报告尚未生成时指出缺失入口；完成报告后复核，不跳过不存在文件。
4. 核对 Mac 命令发现已有 `.env.trial` 时 `cp -n` 返回 1；手册改为先判断不存在才复制，
   既有配置字节保持不变，避免用户误判为部署失败。
5. 初次受限环境无法读 Docker socket；本机验收授权后执行成功，属于执行环境限制。

原始执行日志、JUnit 与开始快照保留在本机 `/private/tmp/frontier-upgrade-20261111/`。
版本化证据保存命令、退出码、摘要和必要结构化结果，避免把整套可再生大日志塞入仓库。

## 真实网络和未完成验收

- 本轮 10 个固定公开 arXiv/HF 页及 MV3 三页只读通过，页面脚本/写请求受限，
  只记录抽取元数据/定位结果；不是人工准确率或事实正确性验证。
- GitHub 只读 CLI 核实了 notes 小目录及文件元数据；这不是应用容器同步。
  当前 Worker DNS 仍返回非公网 `2001:2::4`，安全策略拒绝，未放松 SSRF 或更改用户 DNS/VPN。
  31 文件真实完整导入未在本轮冒充通过；历史两次限流与宿主机小目录成功分别保留。
- 真实 App/PR/撤销联调、真实付费模型解释/概念题质量、真实分享页兼容性待验收。
- 真人样本 0；SC-002 首次计划可用时间、SC-003 人工引文抽检、SC-005 连续学习效果待填写。
- 生产 TLS/标准网络/负载/运维恢复、Constitution 恢复草案审阅尚缺；没有将本机可运行标为正式发布。
- 本轮未重跑性能测量；历史 p95 只证明当时本机串行小数据，不作当前生产结论。

工程自动化通过，基础本地记录/规划/导学工作流可试用；外部真实导入与 AI/PR 体验仍受上述条件限制。
T073、T059、CHK020 保持未完成。最终结论 **PARTIAL**。
