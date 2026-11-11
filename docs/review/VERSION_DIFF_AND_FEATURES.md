# 版本差异与现有功能

## 对比基线

本地/远程 `main` 均为 `4f7fce219b0284ca596cc5699e7140ee3325c92d`，只有 17 个文档文件。
2026-11-11 读取全部远程 heads/tags 及 GitHub Releases：只有 main、codex/local-trial，
没有 Tag、Release。`docs/releases/0.1.0-dev.md` 是开发预览说明，不是已发布稳定版。
使用 main 为唯一真实对比基线，不人为创造旧产品版本。

**当前差异主要是从规格基线到 MVP 工程实现，不是两个成熟产品版本之间的升级。**

当前已提交开发 HEAD `bdf9a8f9823916365545dc1387e86bbafe36db0c`，其前序依次为
`84b4837`（可运行闭环）、`ce64ece`（概念题）、`bdf9a8f`（V0.1.1 修复）。
本轮开始时另有注销修复和试用证据未提交，已经保留并纳入同一工程验收。

## Git 与架构核对

通过 `git ls-tree -r main`、`git diff --name-status/--numstat main HEAD`、逐提交历史，
以及实际路由、领域函数、UI、迁移和测试核对。main 到上述已提交 HEAD：267 新增、9 修改、
0 删除，共 276 个路径；文本 67,120 行新增、517 行删除，包含锁文件、生成类型及契约，
不能将行数当业务规模。本轮文档/清理差异另见 [清理报告](REPOSITORY_CLEANUP.md)。

| 目录 | 当前实际结构 | 与基线相比 |
|---|---|---|
| apps/web | React + Vite + TanStack Query；App.tsx 切换 9 个工作台入口 | 47 个 apps 路径中包含 Web/MV3；main 无客户端 |
| apps/extension | WXT/React/MV3；background 打开 Side Panel；content/extract.ts 在用户授权当前页抽取 | activeTab、scripting、storage、sidePanel 与构建时单一 API origin；没有全站后台采集 |
| packages/shared | API Client、OpenAPI 生成类型、账号/导学/短测 UI | 两端复用类型与操作，TS strict |
| services/api/app/api | FastAPI REST，账号/来源/画像/目标/计划/会话/测验/草稿/数据 API | 服务端按 user_id 隔离，标准错误/request_id |
| app/domain、jobs | 同步、规则规划、导学、评估、写回、可移植性；DB Job + 独立 Worker | 受限重试、超时、lease、取消；非分布式队列 |
| persistence | async SQLAlchemy + PostgreSQL，10 份 Alembic 迁移，head=0010_concept_check | 学习证据/计划修订/账号/模型计量/连接均持久化；没有向量库 |
| ai、connectors、ingestion | LLMProvider Protocol/Fake/OpenAI Responses；GitHub/App/PR、分享解析、固定 IP HTTP 读取 | 默认 local_rules；GitHub 默认只读，云与外部写回需独立授权 |
| infra、.github、tests | 开发 Compose、专用 tmpfs PG、CI、pytest/Vitest/Playwright | CI 分 API 与客户端 job；无自动部署或自动发布 |
| specs、docs、.specify | Living Spec、契约同源生成、ADR、使用与验收资料 | 宪章为恢复草案，仍待人工审阅；Roadmap 不是当前待办 |

## 功能盘点

以下“已实现且自动化验证”表示隔离环境的工程路径；最新执行数量见
[本轮验收报告](../acceptance/LOCAL_AUTOMATED_ACCEPTANCE.md)。所有功能在 main 都只有规格或规划，
没有业务代码，故不重复把同一基线写在每行。路径相对于仓库根目录。

| 功能 | 当前状态 | 实际实现位置 | 使用入口与自动化依据 | 当前限制 |
|---|---|---|---|---|
| 注册/登录/恢复/注销 | 已实现且自动化验证 | api/auth.py、auth/passwords.py；shared/ui/AccountForm.tsx | Web 注册下载恢复码，插件同账号登录；security/test_password_auth.py、real-connections.spec.ts | 无邮箱重置；Web Cookie/MV3 临时 bearer；插件退出只撤销本端 |
| GitHub 只读导入 | 已实现且自动化验证；真实网络需人工试用 | connectors/github.py、domain/knowledge_sync.py、api/sources.py；KnowledgeSources.tsx | 知识来源→范围→同步；test_github_ingest.py、test_ingest_boundaries.py、sources.spec.ts | 每源 200 份/10MB，单文件/网络有界；同账号同仓库仅一来源；不能累积分区绕过范围 |
| GitHub App 授权 | 已实现但需要真实人工试用 | connectors/github_app.py、api/github_app.py；GitHubConnect.tsx | 知识来源→授权/安装/仓库；test_github_app.py、real-connections.spec.ts | 自动化为合成 OAuth/App 协议；真实 App/密钥未配置，连接的 ChatGPT GitHub 工具不转交凭据 |
| Markdown/代码证据与画像 | 已实现且自动化验证，语义提取部分实现 | ingestion/markdown.py、evidence.py、knowledge_policy.py、api/knowledge.py；KnowledgeProfile.tsx | 知识画像→来源/行号/修正；导入与 Attention 固定快照集成测试 | 标题/大写词/文件名规则，不自动对齐中英同义词；代码不执行；笔记只能 LOW/EXPOSED |
| 学习目标 | 已实现且自动化验证 | domain/goals.py、api/goals.py；Goals.tsx | 学习目标→时间/方向/自评/指定先修；test_planner.py、planning.spec.ts | 自评可拒绝；先修为用户声明，未经独立技术核验 |
| 动态计划/今日学习/历史 | 已实现且自动化验证；智能语义编排部分实现 | planner.py、plans.py、replanning.py；Today.tsx | 生成/采纳/重排/跳过/暂停/插入/历史恢复；test_planner.py、planning.spec.ts | 当前为明确标记的规则规划，不调用 LLM 生成课程；完成任务不证明掌握 |
| arXiv/HF 网页分析 | 已实现且自动化验证；真实引用需人工抽检 | extension/adapters、content/extract.ts、PagePreview.tsx | 点击工具栏→分析→预览→确认保存；adapters.test.ts、current-page.spec.ts、live/*.spec.ts | 支持摘要/HTML/Model Card；PDF、登录墙、变更结构需手工粘贴；图表公式可能缺失 |
| 三种模式、追问、跨端历史 | 已实现且自动化验证 | domain/tutor.py、api/pages.py、sessions.py；GuideSession.tsx、Sessions.tsx | 插件选择目标任务/模式，Web 继续；test_citations.py、current-page.spec.ts | 无模型时只有规则阅读方法；最多 20 轮；精确定位需插件当前页权限；快照匹配非独立事实核查 |
| 可选 AI 解释 | 适配代码已实现；真实服务待人工验收 | ai/provider.py、openai_provider.py、budget.py、domain/tutor.py | 设置全局同意 + 每轮同意；test_openai_provider.py、test_model_budget.py | 仅现有 OpenAI Responses 适配；需要服务端 key/model，可能收费；本轮调用 0 |
| 对话导入与候选任务 | 已实现且自动化验证；真实分享兼容性待验收 | connectors/chatgpt_share.py、safe_fetch.py、conversation_learning.py；ImportConversation.tsx | 导入对话→预览/确认→加入或拒绝；test_share_import.py、conversation.spec.ts | 公开固定主机分享或手工文本，1MB/20 秒/2 次同资源重定向；不绕登录墙；模型回答不证明掌握 |
| 来源边界短测 | 已实现且自动化验证 | domain/assessment.py、api/assessments.py；AssessmentPanel.tsx | 会话→开始短测→作答→另行确认证据；test_learning_loop.py、Web/MV3 E2E | 检查原文与推断边界，不是概念理解或实践能力评价 |
| 模型概念选择题 | 已实现且自动化验证；语义可靠性部分实现 | concept_assessment.py、assessment_types.py；AssessmentPanel.tsx | 同意后拟题、取消/新任务恢复、结果复查；test_concept_check.py、test_concept_quality.py、concept-check.spec.ts | Fake 只验证机制；作答前隐藏答案键，最多 3 次拟题；结构/引用匹配不证明模型答案正确，仍 LOW |
| 学习证据与下一轮 | 已实现且自动化验证 | assessment.py、knowledge_policy.py、replanning.py、planner.py | 确认评价→历史/证据 ID→重新规划；test_learning_loop.py、test_attention_trial.py | 正向继续独立检查，负向复习；不会自动升为掌握；真人两轮效果未验证 |
| Markdown 草稿、编辑、下载 | 已实现且自动化验证 | domain/artifacts.py、api/artifacts.py；ArtifactReview.tsx | 会话生成草稿→笔记审核→保存/下载；test_learning_loop.py、learning-loop.spec.ts | 不是任意文档编辑器；草稿有来源、限制和未解疑问，50KB 编辑上限 |
| Diff/受限分支/PR/合并后索引 | 已实现且自动化验证；真实 PR 待人工验收 | domain/writeback.py、connectors/github_writeback.py；ArtifactReview.tsx | 独立写目录授权→Diff→审核确认→PR；test_writeback_safety.py、learning-loop.spec.ts | 默认关闭，真实 App/写权限必需；不更新默认分支、不自动合并；PR 打开不代表知识已入库 |
| 权限/安全/任务恢复 | 已实现且自动化验证 | auth/dependencies.py、core/security.py、safe_fetch.py、jobs/service.py | 页面错误/取消/有限重试；security/、各集成测试 | SSRF/XSS/注入/跨用户/预算/lease 均有回归；生产部署仍需 TLS、负载及人工审阅 |
| 导出/撤销/删除 | 已实现且自动化验证 | api/settings.py、data_portability.py、sources.py；Settings.tsx | 设置与数据、断开来源；test_portability.py、learning-loop.spec.ts | JSON 含 Markdown，20MB/20,000 条上限；删除仅应用内，外部文件/PR 保留 |
| 可运行部署/备份恢复/CI | 已实现且自动化验证 | infra/、migrations/、.github/workflows/ci.yml、tests/acceptance/backup_restore.py | 见部署手册、test_migrations.py、隔离恢复演练 | 本机环境可用不等于生产发布；不提供自动公网部署 |

## 尚未实现与范围外

在当前实现中没有找到：可靠的开放式概念/实践自动评分、任意主题语义知识图谱与同义对齐、
真实模型驱动的完整课程编排、完整 PDF/图表/公式阅读、任意分享站点/登录后内容读取。
它们不能因 Spec 中的愿景文字被标为已交付。

Notion 写回、Hexo 发布、桌面实践执行、跨平台同步、多 Agent 教师等属于未来 Roadmap，
不纳入当前版本，也不在本轮补齐。真实服务授权联调、真人效果和生产运维是现有能力的验收缺口，
与这些未来功能分别记录。
