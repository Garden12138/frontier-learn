# Mac 本地部署运行手册

## 1. 项目与交付范围

FrontierLearn 将已有笔记线索、目标、学习计划、网页导学、验证、审核草稿与下一轮规划关联起来。
这是现有 MVP 的本地开发预览。默认无需付费模型或 GitHub 凭据；默认输出本地阅读方法，
不是完整 AI 讲解。自动验收及未完成的真实服务门槛见 [验收报告](../acceptance/LOCAL_AUTOMATED_ACCEPTANCE.md)。

## 2. 架构与目录

`apps/web` 是 React 工作台，`apps/extension` 是 WXT Chrome MV3 侧栏，
`packages/shared` 提供共享 UI/API 类型，`services/api` 提供 FastAPI 与独立 Worker。
PostgreSQL 保存账号、材料、证据、计划修订、草稿和任务。Worker 消费数据库作业，
没有 Redis/Celery 依赖。`infra` 是 Compose，`specs` 是当前规格/契约，`docs/adr` 是决策。
云模型与 GitHub 是可选连接；Hexo/Notion/桌面执行未实现。

## 3. Mac 环境要求

本轮实际环境：macOS 26.5.1 arm64，Node 22.23.2、pnpm 10.28.2、Python 3.12.11、
uv 0.6.10、Docker 29.8.2 / Compose v5.5.0、PostgreSQL 16.15。
项目要求 Node 22、pnpm 10、Python 3.12；具体依赖由锁文件固定。
先启动 Docker Desktop 或 OrbStack；使用能加载开发者 MV3 的 Chrome。
浏览器自动化使用 Playwright 下载的 Chromium，与个人 Chrome 配置隔离。

环境工具应预先安装。本文不假设本机 Homebrew 路径，不提供未经本轮实测的安装器命令。
可用下面命令核对：

```sh
node --version
pnpm --version
uv --version
docker --version
docker compose version
```

## 4. 依赖安装

所有命令从仓库根目录运行；不要切到 main 启动，main 仅有规格文档。
本轮交付分支为 `feature/upgrade-chatgpt`。在现有干净检出中运行：

```sh
pnpm install --frozen-lockfile
uv sync --frozen --project services/api
```

两条均已实测，另验证了离线缓存方式 `--offline`。无缓存首次安装需联网。
仅用 Compose 运行后端时，宿主机 uv 环境用于开发检查，不影响容器内的独立依赖。
pnpm 可能提示忽略 `spawn-sync` 的依赖构建脚本；本轮不额外批准它，构建和浏览器验收仍通过。

## 5. 环境变量

```sh
if [ ! -e .env.trial ]; then
  cp -n infra/local-trial.env.example .env.trial
fi
```

先判断文件是否存在，再用 `-n` 防覆盖；macOS 对已存在文件执行 `cp -n` 会返回 1，
因此不要无条件重复复制。已有配置时先人工核对。`.env.trial` 被忽略，不提交。
示例固定：Web 5176、API 18000、PG 55433，统一主机名 `127.0.0.1`。
Mock=false、写回=false、LLM=local_rules，不需要模型密钥。
Compose 显式读取 `--env-file`；宿主机 API/Worker 不会自动读取该文件。
Web 与插件的 `FRONTIER_API_PROXY` / `FRONTIER_EXTENSION_API_ORIGIN` 必须分别传入。

端口占用会失败，先确认占用者，不结束其他项目。更换 API 端口需同步 public API、Web proxy、
插件构建 origin；更换 Web 端口需同步 public Web 和 allowed origins。
真实模型/App 的完整配置见 [接入说明](../production-integrations.md)，不要粘贴凭据到页面/聊天。

## 6–9. PostgreSQL、迁移、API 与 Worker

首次空库启动与容器构建：

```sh
docker compose --env-file .env.trial -f infra/docker-compose.yml up -d --build --wait
```

同一命令启动四个阶段：PG 健康 → 一次性 migrate 执行 `alembic upgrade head` → API → Worker。
不需要在另一个终端重复启动宿主机 API/Worker。当前 head 为 `0010_concept_check`。
`migrate` 正常退出是预期行为；Worker 是常驻进程，不提供独立 HTTP 健康端点。

```sh
docker compose --env-file .env.trial -f infra/docker-compose.yml ps -a
docker compose --env-file .env.trial -f infra/docker-compose.yml exec -T api .venv/bin/alembic current
docker compose --env-file .env.trial -f infra/docker-compose.yml exec -T api .venv/bin/alembic check
```

已有用户资料的升级先按第 15/18 节备份、停止写入。不要对日常库运行 downgrade 或测试。
迁移与逐版本回滚影响见 [迁移说明](../../services/api/app/persistence/migrations/README.md)。

## 10. Web 启动

另开终端，从根目录运行并保持终端开启：

```sh
FRONTIER_API_PROXY=http://127.0.0.1:18000 pnpm --filter @frontier/web dev --host 127.0.0.1 --port 5176
```

打开 <http://127.0.0.1:5176>。API 在 <http://127.0.0.1:18000>。
5173 是 Vite 默认端口，本手册显式选 5176，避免当前机器其他项目。
浏览器始终使用同一主机名；localhost 与 127.0.0.1 不应交替登录。

## 11. Chrome 插件

```sh
FRONTIER_EXTENSION_API_ORIGIN=http://127.0.0.1:18000 pnpm --filter @frontier/extension build
```

Chrome 地址栏输入 `chrome://extensions` → 开发者模式 → 加载已解压的扩展程序 →
选择仓库 `apps/extension/.output/chrome-mv3`，再固定工具栏图标。
点击工具栏打开侧栏；在侧栏用 Web 同账号密码登录。
在支持的网页再次点击工具栏赋予当前页临时权限，再点“分析当前页”。
预览后确认才保存到本机服务。安装到个人 Chrome 是用户操作，本轮只在临时自动化配置实测。

`pnpm test:extension` 会把同目录重建为测试 API 18002 版本；测试结束后务必重跑上面的
18000 构建并在扩展页点击“重新加载”。仅修改 Web proxy 不会修改插件服务地址。

## 12. 健康检查

```sh
curl --fail http://127.0.0.1:18000/api/v1/health
curl --fail http://127.0.0.1:18000/api/v1/ready
```

两者应返回 HTTP 200。health 是进程状态，ready 检查数据库；还需确认 Worker 在 `ps` 为 running。
工作台登录前可点“重新检查连接”。实际业务处理通过会话/同步的 Job 从等待变为完成确认。

## 13. 首次初始化

没有默认账号或自动导入资料。Web 点“创建账号”，设置至少 12 字符密码，下载恢复文件后
进入学习空间；没有邮件找回。创建学习目标后即可生成规则计划，无需 GitHub。
按 [FIRST_TRIAL](FIRST_TRIAL.md) 完成两轮；如果想先检查来源，可先只读导入小目录再创建目标。

## 14. 关闭与重新启动

Web 终端按 Ctrl+C；停止容器并保留资料：

```sh
docker compose --env-file .env.trial -f infra/docker-compose.yml stop
```

重启运行第 6–9 节的 up 命令，再启动 Web。`up` 不删除命名卷。
不要对日常项目运行 `down -v`，也不要把日常数据库 URL 填入测试变量。

## 15. 数据保留与备份

资料位于 `frontier-learn_frontier_pg` 命名卷；代码/容器重建与数据生命周期分开。
“设置与数据”可下载个人 JSON，笔记审核可下载 Markdown，但它们不是可直接恢复账号/数据库的备份。
如有真实 App，必须同时安全保存原 `.env.trial` 和原加密密钥；丢失密钥无法解密连接。

一致性备份先停止 API/Worker，保留 PG：

```sh
docker compose --env-file .env.trial -f infra/docker-compose.yml stop api worker
mkdir -p .local/backups
umask 077
docker compose --env-file .env.trial -f infra/docker-compose.yml exec -T db pg_dump -U frontier -d frontier -Fc --no-owner > .local/backups/frontier.dump
```

使用新文件名或先移动旧备份，避免覆盖唯一可用副本；上面的固定文件名仅适合首次备份。
`.local/` 被忽略，备份含私人材料；请另存加密离线副本，不上传报告。
这些操作已在本轮新建的空白部署项目验证，未替用户备份/恢复真实资料。
备份后重启第 6–9 节命令。正式恢复先在新空库验证匹配代码、密钥和外部任务状态，
不要将 dump 直接覆盖运行中的资料库；恢复过程参照迁移说明，由数据库操作者执行。

## 16. 常见错误

| 现象 | 处理 |
|---|---|
| Docker socket/daemon 不可用 | 打开 Docker Desktop/OrbStack，确认当前用户能访问 Docker；Codex 沙箱授权和终端权限是不同问题 |
| 端口已占用 | 核对占用程序，更换自己的端口并同步第 5 节各配置，不杀其他服务 |
| migrate 非零退出/ready 非 200 | 读 migrate 日志；确认数据库/代码版本与连接，先备份，不清库重试 |
| Web 能打开但账号/来源失败 | 核对 Web proxy、API 端口、同一 hostname 和 allowed origins |
| 插件无法连接/未获权限 | 重建正确 origin 并重新加载；当前页重新点工具栏，特殊页面不允许注入 |
| GITHUB_RATE_LIMIT | 等 reset/Retry-After，不连续重试；先用手工片段体验，不视为同步成功 |
| UNSAFE_URL | 排查 Docker/VPN DNS 返回的非公网地址，不关闭 SSRF 校验；历史诊断见 testing 文档 |
| 一直等待导学/同步 | 检查 Worker 日志和 Job；若终态失败，按 UI 的预算/截止期有限重试 |
| 只有本地规则建议 | 默认预期行为；真实解释需服务端模型配置、全局与本轮同意，可能收费 |
| 概念题取消后不能直接 retry | 回短测勾选新同意，使用“恢复概念拟题（新任务）”，累计最多三次 |
| 忘记密码 | 用已下载恢复文件恢复；恢复会撤销旧登录并轮换恢复码，没有邮箱重置 |

## 17. 日志

```sh
docker compose --env-file .env.trial -f infra/docker-compose.yml logs --tail=100 api worker migrate
```

Web 日志在运行 Vite 的终端，Chrome 插件错误可在扩展页查看 Service Worker/侧栏检查器。
应用结构化日志提供 request_id/task_id/error_code，不包含原文或密钥。
反馈时只提供错误码、时间、入口和脱敏截图，不发送环境文件、恢复码、Cookie 或 token。

## 18. 升级开发版本

先确保自己的工作已提交/备份，记录当前 SHA；读取新增迁移和验收报告，再更新：

```sh
git status --short --branch
git rev-parse HEAD
git pull --ff-only origin feature/upgrade-chatgpt
```

然后备份、停止 API/Worker、安装锁定依赖、运行 Compose 构建/迁移，启动 Web、重建插件。
有分叉时 `--ff-only` 会拒绝，保留现场，不用 reset/rebase/force 隐藏历史。
当前整理没有新增迁移；旧库从旧版本升级仍按其迁移文档执行。

## 19. 安全恢复测试环境

测试库使用独立 tmpfs Compose 项目，端口 55432，库名 `frontier_test`，没有用户资料：

```sh
docker compose -f infra/compose.test.yml up -d --wait
```

确认没有上一项测试进程后，逐条执行，不并行共用这个库：

```sh
cd services/api
FRONTIER_TEST_DATABASE_URL=postgresql+asyncpg://frontier:test_only@127.0.0.1:55432/frontier_test uv run pytest -q
cd ../..
FRONTIER_TEST_DATABASE_URL=postgresql+asyncpg://frontier:test_only@127.0.0.1:55432/frontier_test pnpm test:sources
FRONTIER_TEST_DATABASE_URL=postgresql+asyncpg://frontier:test_only@127.0.0.1:55432/frontier_test pnpm test:extension
```

测试拒绝已有业务表，正常结束降级清理自身测试表。若异常退出残留，先确认只涉及上述测试项目，
再停止并重建其 tmpfs 容器；**下面命令只适用于 compose.test.yml**：

```sh
docker compose -f infra/compose.test.yml down
docker compose -f infra/compose.test.yml up -d --wait
```

真实恢复演练（另建两个随机临时库，不覆盖上述库或开发库）：

```sh
cd services/api
FRONTIER_TEST_DATABASE_URL=postgresql+asyncpg://frontier:test_only@127.0.0.1:55432/frontier_test uv run python -m tests.acceptance.backup_restore
cd ../..
```

本轮已验证当前 0010 版本的实际 pg_dump/pg_restore；数据、账号登录与加密连接均核对。
测试完成按第 11 节重建日常插件。本手册命令的执行结果与隔离端口替换见自动化验收，不把真实凭据配置视为已验证。
