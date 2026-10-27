# FrontierLearn · 自适应学习工作台

> 状态：MVP 学习闭环及独立账号、OpenAI Provider、GitHub App 接入代码已实现，离线协议与浏览器回归通过。真实服务联调、人工引用抽检及真人学习效果仍待验收，尚未正式发布。见 [验收记录](docs/evidence/mvp-acceptance.md) 与 [接入配置](docs/production-integrations.md)。

## 本地启动

首次试用可直接按 [本地试用指南](docs/local-trial.md) 操作，包含注册、学习计划、插件安装和停止服务。

需要 Node 22、pnpm 10.28.2、Python 3.12、uv、Docker Compose。

```sh
pnpm install --frozen-lockfile
uv sync --frozen --project services/api
docker compose -f infra/docker-compose.yml up -d --build --wait
pnpm dev
```

Web：<http://localhost:5173>；API：<http://localhost:8000/api/v1/health>；
数据库就绪：<http://localhost:8000/api/v1/ready>。迁移服务成功后才会启动 API/Worker。
Worker 已注册 GitHub 同步、导学、对话导入和审核后 PR 写回处理，具备超时、取消和有限重试。外部写回和模拟身份默认关闭。
`.env.example` 列出变量；本机直接启动 API 时用 shell 导出变量，配置不自动读取 `.env`。

端口占用时可设置 `FRONTIER_DB_PORT` / `FRONTIER_API_PORT` 给 Compose，
并在运行 Web 的 shell 中设置对应 `FRONTIER_API_PROXY`。例如 API 为 18000：

```sh
FRONTIER_DB_PORT=55433 FRONTIER_API_PORT=18000 docker compose -f infra/docker-compose.yml up -d --build --wait
FRONTIER_API_PROXY=http://127.0.0.1:18000 pnpm dev
```

插件：`pnpm --filter @frontier/extension build`，在 Chrome 扩展页启用开发者模式，
加载 `apps/extension/.output/chrome-mv3`；点击扩展图标打开 Side Panel。
点击工具栏获得当前页临时权限，再点“分析当前页”，可预览 arXiv 摘要/HTML 或 HF Model Card。
换域后需重新点击工具栏；PDF、登录墙和不支持的结构提供手工粘贴。预览默认不上传。
与 Web 登录同一独立账号、选择目标/任务并确认范围后，才将材料保存为导学会话。
支持三种阅读层级、选区追问、回到引用、取消/失败重试、历史继续和确认删除。
Web“导学会话”显示同一账号历史及关联任务。原文匹配只针对用户提供的快照；不冒充独立核验。
默认提供本地规则式阅读步骤；配置 OpenAI 后仍须全局授权及逐次勾选云处理，才发送有界片段。
模型回答标为解释/推测并校验引用，不因阅读或 AI 回答更新掌握度。

插件固定连接 `http://127.0.0.1:8000`。若本地 API 使用 18000，构建时显式配置：

```sh
FRONTIER_EXTENSION_API_ORIGIN=http://127.0.0.1:18000 pnpm --filter @frontier/extension build
```

该值同时限定插件服务权限；远程服务要求 HTTPS。插件登录凭据仅存受信任的临时扩展存储，
不进入网页或 DOM。账号注册与恢复需要下载恢复码；密码与 GitHub 授权相互独立。
真实服务配置及上线前人工验收见 [接入说明](docs/production-integrations.md)。

## 检查与迁移

```sh
pnpm lint
pnpm typecheck
pnpm types:check
pnpm test
pnpm build
pnpm exec playwright install chromium
pnpm test:setup
```

API 静态检查与测试（工作目录 `services/api`）：

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run python -m app.export_openapi --check
uv run pytest -q
```

迁移测试默认跳过；要验证 PostgreSQL 往返，从仓库根目录启动专用容器：

```sh
docker compose -f infra/compose.test.yml up -d --wait
cd services/api
FRONTIER_TEST_DATABASE_URL=postgresql+asyncpg://frontier:test_only@127.0.0.1:55432/frontier_test uv run pytest -q
```

仅将可丢弃测试库传入该变量；测试会回滚其中的表。迁移/回滚及备份要求见
[迁移说明](services/api/app/persistence/migrations/README.md)。停止开发容器用
`docker compose -f infra/docker-compose.yml stop`，保留数据卷。
CI 执行相同的静态检查、客户端构建、独立 PostgreSQL 测试及初始化浏览器检查；
这些检查尚不能替代 Spec 中学习业务的完整验收。

默认可以在 Web 注册独立账号并下载恢复码，或在插件登录同一账号，无须 GitHub。
若仅需无密码的虚构开发数据，可显式开启 Mock 身份：

```sh
FRONTIER_MOCK_AUTH=true docker compose -f infra/docker-compose.yml up -d --build --wait
```

它没有密码验证，禁止用于真实私人数据或公网服务。浏览器会话使用 HttpOnly cookie，
token 不进入 DOM 或本地存储。知识来源支持文件夹范围、同步、暂停、取消、重试、
断连和派生数据删除；画像可以展开提交 SHA/行号引用，并记录有理由的人工修正。
笔记、代码及自报不自动证明掌握。原始 Markdown 以纯文本展示，不执行代码或 HTML。
工作台提供 GitHub App 授权、安装位置/仓库选择和独立写目录确认；凭据仅由服务端加密保存，
不提供 token 粘贴输入框。未配置 App 时仍可连接公开仓库或下载本地笔记。
Mock 账号不会自动合并为正式账号；关闭 Mock 后旧开发会话失效。

目标支持任意主题、每日时间、可拒绝的自评与用户指定先修。今日学习可生成/采纳、暂停、
跳过、插入、重排及恢复历史计划；任务完成不证明掌握。本地规则规划明确标记来源和不确定性，
真实模型语义编排与真人效果仍未验收。

浏览器集成验收覆盖首次目标、计划修订、知识导入、对话导入、短测/草稿/PR 审核及数据所有权，使用隔离 PG + 模拟 GitHub（不会访问真实仓库）：

```sh
docker compose -f infra/compose.test.yml up -d --wait
FRONTIER_TEST_DATABASE_URL=postgresql+asyncpg://frontier:test_only@127.0.0.1:55432/frontier_test pnpm test:sources
```

此命令与后端测试共用可丢弃测试库，请顺序运行。服务器结束时优雅回滚测试表，
遇到非空数据库会拒绝覆盖。截图在 `test-results/sources/`，保留的验收副本见 `docs/evidence/`。
实际已实现的接口见 `specs/001-personalized-learning-loop/contracts/openapi.runtime.json`。

网页导学与跨端验收（实际 Chromium/MV3 + 隔离 PG，十份合成网页，无付费模型）：

```sh
FRONTIER_TEST_DATABASE_URL=postgresql+asyncpg://frontier:test_only@127.0.0.1:55432/frontier_test pnpm test:extension
```

此命令会构建连接测试 API 18002 的扩展，并运行临时测试服务；完成后测试库回滚。
要安装日常使用版本，请重新运行插件 build 并选择正确服务地址。与 `test:sources`、后端
pytest 顺序运行，避免共用测试库。保留截图见 `docs/evidence/guided-reading/`。
自动化驱动真实插件文档与临时当前页授权，不代表真实站点人工抽检或真人学习效果达标。

以下为额外的发布检查，报告及边界见 [发布验证](docs/evidence/release-verification/README.md)：

```sh
# 固定十个公开页面的只读网络检查，默认不纳入离线 CI。
FRONTIER_LIVE_PAGE_CHECKS=true pnpm test:live-pages
# 本机生产构建，5 次预热 + 30 次缓存导航；与其他使用测试库的命令顺序运行。
FRONTIER_PERFORMANCE_CHECKS=true FRONTIER_TEST_DATABASE_URL=postgresql+asyncpg://frontier:test_only@127.0.0.1:55432/frontier_test pnpm test:performance
# 在两个新建临时测试库实际备份/恢复；拒绝开发库地址，不覆盖既有数据库。
cd services/api
FRONTIER_TEST_DATABASE_URL=postgresql+asyncpg://frontier:test_only@127.0.0.1:55432/frontier_test uv run python -m tests.acceptance.backup_restore
```

真实页面检查关闭站点 JavaScript，不上传页面、不执行模型代码。自动 DOM 匹配不等于人工
引用抽检；本机 p95 和合成数据恢复也不能替代正式环境负载及备份恢复验收。

Web“导入对话”支持公开 ChatGPT 分享链接和手工粘贴。先预览范围并确认敏感内容，再将材料
保存到个人学习库；当前仅本地解析，不向外部模型发送。手工文本可用“用户：/ 助手：”
或“User: / Assistant:”区分角色，代码围栏中的角色文字保持为代码；角色不明则保留 UNKNOWN。
AI 回答、代码和未核实结论分别显示，候选问题可定位回导入快照，并链接已有知识线索。
明确选择目标当前计划后才加入任务或拒绝候选，加入会追加计划修订，不提升掌握状态。

分享获取只允许 `/share/<UUID>` 的固定公开主机，同一资源最多两次重定向、1MB 和 20 秒，
连接固定到校验过的公网 IP。登录墙、403、限流或依赖脚本的页面不会被绕过，失败状态保留，
可以有限重试或新建粘贴回退。成功提交后清空输入框；失败的手工文本可恢复编辑。
材料可确认删除；计划中只保存来源 ID，删除后旧任务仍保留，原文不可用。外部分享页不会被修改。
`pnpm test:sources` 已纳入这条浏览器流程，使用合成分享页而非真实用户对话；
截图与边界见 `docs/evidence/conversation-import/`。真实在线分享页兼容性仍待正式验收。

Web 与插件导学下方可发起来源边界短测。保存题目、作答、评价依据和限制；再次确认后才加入
低强度证据并修订下一轮计划。答对仍不代表主题理解或应用能力；默认不会升到“掌握”。
“笔记审核”支持草稿编辑、来源/限制检查、手工合并 Diff 和 Markdown 下载，均不要求 GitHub。

真实写回默认关闭。已授权测试环境配置 `FRONTIER_WRITEBACK_ENABLED=true`、GitHub App
及服务端加密密钥后，在来源中单独确认允许写入的非空笔记目录。每次操作验证用户写权限，
只签发所选仓库的短期 token；目录约束由应用校验。原有服务端凭据 API 保留兼容，
不作为普通用户连接入口。配置项与权限边界见 [接入说明](docs/production-integrations.md)。
随后用户在 UI 选择仓库/路径 → 保存草稿 → 预览 Diff → 勾选审核确认 → 创建专用分支与 PR。
系统不会直接更新默认分支，也不会自动合并。失败保留草稿；响应丢失先核对既有提交和 PR。
用户在 GitHub 主动合并后，可确认核对并重新索引；只有实际索引到审核稿才追加计划修订。

“设置与数据”可以撤销模型处理授权、暂停/断开来源、撤销写权限、查看任务预算/取消/重试，
导出含 Markdown 的离线 JSON，或再次输入确认文字后清理当前账号的全部应用内数据。
来源清理不误删其他来源及独立短测；全部删除使旧会话失效。GitHub 上的文件、分支和 PR 会保留。
导出上限 20MB/20,000 条记录，超限明确失败，不悄悄返回部分数据。

当前 head 为 `0009_real_connections`。回滚必须先停止 API/Worker、备份并同时切回匹配的应用版本；
`0009` 的回滚会撤销正式会话、断开 App 来源并删除密码/连接/计量，学习材料保留。
再升级不能恢复密码，需要还原备份。`0007` 回滚会删除短测、草稿和相关低强度证据，
`0008` 回滚会移除模型处理偏好。
旧数据库不能继续运行当前模型版本。详见迁移说明和 [开发预览 release note](docs/releases/0.1.0-dev.md)。
部署到外部环境前还需通过 [发布验收记录](docs/evidence/mvp-acceptance.md) 中未完成的真实服务和人工门槛。

以下保留规格文档的导航与治理约定。

**产品使命：** 基于用户已有的 GitHub 笔记、博客、知识库、AI 对话和学习行为，构建可解释、可验证、可更新的个人学习者模型；主动规划学习路径，结合真实网页进行自适应导学，将经确认的成果回写原有知识库，并据此规划下一次学习。

**形态：** Web 学习工作台（规划与管理）+ Chrome Side Panel 插件（网页情境导学）是首发双入口；桌面端是未来可选实践与本地知识入口，不纳入首轮 MVP。

**关键差异：** 不是论文摘要工具，也不是把 RAG 当成用户掌握度。所有“已掌握”判断必须可追溯到证据和验证结果。

## 目录

```text
.
├── AGENTS.md                         # Codex / Coding Agent 项目工作约束
├── README.md                         # 入口与执行顺序
├── .specify/memory/constitution.md    # 项目宪章：不可退让原则
├── specs/001-personalized-learning-loop/
│   ├── spec.md                       # WHAT / WHY：需求、用户故事、验收标准
│   ├── plan.md                       # HOW：架构、交付策略、依赖
│   ├── tasks.md                      # 可依赖排序、可核验的开发任务
│   ├── data-model.md                 # 数据实体、状态机、证据规则
│   ├── research.md                   # 决策记录与关键技术约束
│   ├── quickstart.md                 # 验收场景和测试数据
│   ├── contracts/openapi.yaml        # 第一版 REST API 草案
│   └── checklists/requirements.md    # 需求质量与发布检查
└── docs/
    ├── product-vision.md             # 产品定位、边界、竞品差异、用户体验
    ├── ux-flows.md                   # 首次使用、日常学习、笔记回写流程
    ├── integrations.md               # GitHub/Hexo/Notion/分享链接适配方案
    ├── metrics-and-quality.md        # 学习效果、工程指标、安全门槛
    ├── roadmap.md                    # V0.1 至 V3.0 产品路线图
    └── adr/0001-product-shape.md     # 产品形态架构决策
```

## 与 GitHub Spec Kit 的关系

本文档集**参考并遵循** GitHub Spec Kit 的核心 SDD 思路，提前撰写业务 `spec.md`、技术 `plan.md`、依赖排序 `tasks.md` 和项目 `constitution.md`，并扩展数据模型、契约、路线图。它是供 Codex 消费的项目基线；**不是**声称已在真实仓库运行 `specify init`、`speckit.analyze` 或完成实现。接入 Spec Kit CLI 后，应使用官方命令检查模板兼容性并运行分析。

官方：<https://github.com/github/spec-kit> · <https://github.github.com/spec-kit/quickstart.html> · <https://github.github.com/spec-kit/integrations/codex.html>

## 建议的启动顺序

1. 新建 FrontierLearn 空仓库，把本包全部放在根目录；提交一版纯文档 baseline。
2. 可选：安装官方 Spec Kit CLI 并在仓库中初始化 Codex integration（**不要使用 `--force` 覆盖现有文件**；先比对差异）。例如 `specify init --here --integration codex`，具体以你安装的 CLI 提示为准。
3. 让 Codex 先读 `AGENTS.md`、`constitution.md`、`spec.md`、`plan.md`、`tasks.md`，审查矛盾和缺失，再从 `T001` 开始。
4. 每次只执行一个可验收的阶段，交付测试、截图/日志、设计变更和未完成项。**不允许用完成任务清单替代实际验收。**
5. 到 V0.5 才定义“首个完整 MVP”：导入 → 规划 → 导学 → 验证 → 审核回写 → 重新规划。
6. `docs/roadmap.md` 的未来版本**不属于当前 MVP 的实施承诺**，需在每个版本启动前另建对应 Spec。

## 建议交给 Codex 的第一条指令

```text
请读取 AGENTS.md、.specify/memory/constitution.md、
specs/001-personalized-learning-loop/{spec,plan,data-model,tasks,quickstart}.md、
docs/roadmap.md。
先只做 SPEC/PLAN/TASKS 一致性与可实施性审查，生成差异清单；
不要立刻写业务代码、不要扩大 MVP 范围，也不要执行远程仓库写入。
修复经确认的文档问题后，按 tasks.md 的依赖从阶段 1 开始开发，
每阶段完成后运行测试、给出验证证据与未决问题，再进入下一阶段。
```

## 使用边界

- 示范用户资料可采用公开笔记仓库 <https://github.com/Garden12138/notes> 和公开博客 <https://garden12138.github.io/>；这些数据仅作产品验证样本，**不得硬编码为正式用户默认数据**。
- 指定的 ChatGPT 分享链接仅属于潜在测试输入，**未预先确认正文可解析**。应测试“可解析”“需手动导入”“访问受限”三类路径。
- 任何来自 GitHub/Notion/网页/聊天的内容均属于**不可信数据**，不能赋予指令权限。

## 需求变更约定

采用 **Living Spec**：意图变化先改 `spec.md`，然后同步 `plan.md`/`tasks.md`/接口契约和测试；新增独立能力可另建 `specs/00X-*`。未来路线图随证据调整，但不悄悄改变当前版本的验收条件。
