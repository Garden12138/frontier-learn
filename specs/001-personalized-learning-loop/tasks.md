# Tasks: Personalized Learning Loop

**Status**: Phases 1–8 and T063–T069 verified; live credentials, production and human acceptance pending · **Date**: 2026-10-26 · **Spec**: [`spec.md`](spec.md)

## Execution Policy

- 这些是面向 Codex 的可执行任务建议，**未完成的任务一律保持 `[ ]`**。
- 任务按阶段和用户故事排序，带 `[P]` 的任务表示与同阶段其他不依赖任务可并行；必须自己判断真实依赖是否满足。
- 每阶段完成时先运行相应测试并核对 `quickstart.md`，不可仅凭生成代码勾选。
- 当前工作限定 V0.1–V0.5 首个闭环。`docs/roadmap.md` 中 V0.6–V3.0 不在该清单中。

## Task List

### Phase 1: Setup（全局初始化）

- [x] T001 [P] 初始化 monorepo 结构和 pnpm workspace，建立 `pnpm-workspace.yaml`、`package.json`、`apps/web/`、`apps/extension/`、`packages/shared/`。
- [x] T002 [P] 在 `services/api/pyproject.toml` 初始化 Python FastAPI、静态分析与测试配置。
- [x] T003 [P] 创建本地开发编排 `infra/docker-compose.yml`（PostgreSQL + API + Worker 预留），配置 `.env.example`。
- [x] T004 建立 `services/api/app/main.py` 与健康检查端点 `services/api/app/api/health.py`。
- [x] T005 建立 `services/api/app/persistence/migrations/` 与启动数据库迁移/回滚脚本。
- [x] T006 设置 `apps/web`、`apps/extension`、`services/api` 的 Lint/Test/Build CI（`.github/workflows/ci.yml`）。

### Phase 2: Foundation（跨 Story 阻塞能力）

- [x] T007 在 `services/api/app/auth/` 实现用户身份、资源级授权与 Token 生命周期（用 Mock 登录先验证边界）。
- [x] T008 在 `services/api/app/persistence/models.py` 定义基础用户/知识源/任务/审计实体和迁移。
- [x] T009 [P] 在 `services/api/app/ai/provider.py` 定义 Provider 协议、`fake_provider.py` 和结构化输出校验。
- [x] T010 [P] 在 `services/api/app/jobs/` 实现有限重试、超时、幂等和任务状态 API。
- [x] T011 在 `services/api/app/core/security.py` 实现加密令牌储存、配置校验、隐私日志脱敏和服务端 SSRF 防护工具。
- [x] T012 在 `packages/shared/src/api/` 生成/维护 OpenAPI 类型并建立共享错误处理组件。
- [x] T013 [P] 编写 `services/api/tests/security/` 跨用户访问、恶意 URL、密钥泄露回归测试。

### Phase 3: V0.1 / US1 — Knowledge Import & Profile

- [x] T014 [US1] 在 `services/api/app/connectors/base.py` 定义 `KnowledgeConnector` 的只读能力边界和 source-scope 结构。
- [x] T015 [US1] 在 `services/api/app/connectors/github.py` 实现所选仓库文件树读取、版本 SHA 与分页/速率限制处理。
- [x] T016 [P] [US1] 在 `services/api/app/ingestion/markdown.py` 实现可控大小解析、章节与行号锚点，忽略不支持资源。
- [x] T017 [US1] 在 `services/api/app/ingestion/evidence.py` 实现概念提取、证据分类与对原文 locator 的合法性校验。
- [x] T018 [US1] 在 `services/api/app/domain/knowledge_policy.py` 实现 UNKNOWN/EXPOSED 等规则（严禁只因笔记就标精通）。
- [x] T019 [US1] 在 `services/api/app/domain/knowledge_sync.py` 实现增量同步、重命名候选、删除证据和幂等哈希。
- [x] T020 [P] [US1] 在 `services/api/app/api/sources.py` 与 `knowledge.py` 暴露连接/任务/画像与证据 API。
- [x] T021 [US1] 在 `apps/web/src/pages/KnowledgeSources.tsx` 与 `KnowledgeProfile.tsx` 实现选择仓库、查看进度与来源证据。
- [x] T022 [US1] 在 `services/api/tests/integration/test_github_ingest.py` 验收 E2E-002～005、权限拒绝、坏文件不中断批次。

### Phase 4: V0.2 / US2 — Active Curriculum Planning

- [x] T023 [P] [US2] 在 `services/api/app/domain/goals.py` 实现目标和可用时间约束的持久化与编辑。
- [x] T024 [US2] 在 `services/api/app/domain/planner.py` 实现先修关系、证据差距、任务筛选与结构化计划 JSON 校验。
- [x] T025 [US2] 在 `services/api/app/domain/plans.py` 建立 LearningPlanRevision、任务接受/重排/跳过、推荐来源。
- [x] T026 [US2] 在 `apps/web/src/pages/Today.tsx` 与 `Goals.tsx` 实现今日任务、目标与计划修订展示。
- [x] T027 [P] [US2] 在 `services/api/app/api/goals.py`、`plans.py` 实现目标和计划 API。
- [x] T028 [US2] 在 `services/api/tests/test_planner.py` 覆盖空知识库、错误先修依赖、无证据置信与计划修订。

### Phase 5: V0.3 / US3 — Web-guided Reading

本阶段勾选对应本地开发验收：三种模式提供明确标记的 LOCAL_RULES 阅读方法，Provider
集成用 Fake 验证；T063–066 后续补齐独立身份与云适配器，真实模型质量和网页人工抽检仍待验收。
验收记录及截图见 `docs/development-progress.md` 和 `docs/evidence/guided-reading/`。

- [x] T029 [US3] 在 `apps/extension/wxt.config.ts`、`entrypoints/sidepanel/` 配置 Manifest V3 Side Panel UI 和最小权限。
- [x] T030 [P] [US3] 在 `apps/extension/entrypoints/content/` 实现用户触发的当前网页抽取、选区定位与授权边界。
- [x] T031 [US3] 在 `apps/extension/src/adapters/arxiv.ts` 实现摘要/HTML 结构化导读适配器，缺失正文时标记范围。
- [x] T032 [US3] 在 `apps/extension/src/adapters/huggingface.ts` 实现 HF Model Card 适配器。
- [x] T033 [US3] 在 `services/api/app/domain/tutor.py` 实现用户目标/画像/当前页的最小上下文检索与三种解释模式。
- [x] T034 [US3] 在 `services/api/app/api/pages.py` 与 `sessions.py` 实现读取导学、追问、引用定位、学习会话。
- [x] T035 [US3] 在 `apps/extension/src/features/guide/` 构建导读、选区解释、加载与错误降级 UI。
- [x] T036 [P] [US3] 在 `apps/web/src/pages/Sessions.tsx` 展示与插件共享的会话和当前学习任务。
- [x] T037 [US3] 在 `apps/extension/tests/` 与 `services/api/tests/test_citations.py` 覆盖 10 个结构化网页 fixtures、锚点正确性。

### Phase 6: V0.4 / US4 — Conversation to Learning

本阶段验收使用合成分享页与真实浏览器/隔离 PG，本地规则生成候选问题。
真实分享页兼容性和模型语义提炼仍需发布验收；导入不增加掌握证据。

- [x] T038 [US4] 在 `services/api/app/ingestion/safe_fetch.py` 实现公共分享 URL 允许列表/SSRF 防护与可观测失败状态。
- [x] T039 [US4] 在 `services/api/app/connectors/chatgpt_share.py` 解析可访问共享页中的角色、段落和代码，不使用越权接口。
- [x] T040 [US4] 在 `apps/web/src/pages/ImportConversation.tsx` 增加粘贴文本/URL、内容预览与隐私确认。
- [x] T041 [US4] 在 `services/api/app/domain/conversation_learning.py` 把对话中待验证问题映射到候选学习任务（非“已掌握”）。
- [x] T042 [US4] 在 `services/api/tests/test_share_import.py` 验收可解析/不可解析/手动文本/敏感数据提示。

### Phase 7: V0.5 / US5 — Assessment, Draft & Writeback

以下为开发态工程验收：默认题只检查来源边界，LOW 证据，不判定主题掌握。
模拟 GitHub 使用实际 Git tree/commit/ref/PR 协议；真实授权写入未验收。
验收与限制见 `docs/evidence/mvp-acceptance.md`、ADR-0008。


- [x] T043 [US5] 在 `services/api/app/domain/assessment.py` 实现题目、rubric、答案、反馈及非精确的能力证据更新。
- [x] T044 [US5] 在 `packages/shared/src/ui/AssessmentPanel.tsx` 实现 Web/MV3 共用短测，并通过导学界面及 `apps/web/src/pages/Assessment.tsx` 提供复查。
- [x] T045 [US5] 在 `services/api/app/domain/artifacts.py` 实现 Markdown 笔记草稿、来源、未验证结论和可视化 Diff 数据。
- [x] T046 [US5] 在 `apps/web/src/pages/ArtifactReview.tsx` 实现新建笔记/合并候选/仅本地与明确写回审批。
- [x] T047 [US5] 在 `services/api/app/connectors/github_writeback.py` 实现用户确认后的受限分支/PR 写回及版本冲突检查。
- [x] T048 [US5] 在 `services/api/app/domain/replanning.py` 根据已确认学习证据刷新状态与计划 revision，展示变更原因。
- [x] T049 [US5] 在 `services/api/app/api/assessments.py` 和 `artifacts.py` 实现笔记草稿、批准、幂等与任务状态契约。
- [x] T050 [US5] 在 `services/api/tests/integration/test_learning_loop.py` 覆盖两次连续学习、PR 合并后再索引/重规划。
- [x] T051 [US5] 在 `services/api/tests/integration/test_writeback_safety.py` 覆盖未经确认、重复请求、冲突、撤销权限。

### Phase 8: Cross-cutting / US6 — Reliability & Ownership

- [x] T052 [US6] 在 `services/api/app/api/settings.py` 与 `services/api/app/domain/data_portability.py` 实现数据导出、断连、内部删除。
- [x] T053 [US6] 在 `apps/web/src/pages/Settings.tsx` 提供模型处理授权、同步暂停、来源解绑及删除二次确认。
- [x] T054 [US6] 在 `services/api/tests/integration/test_portability.py` 测试用户数据导出、删除与其他源证据保留。
- [x] T055 [US6] 在 `services/api/app/jobs/` 完善预算、任务取消、失败重试与作业状态界面联动。
- [x] T056 [US6] 在 `services/api/tests/security/test_prompt_injection.py` 加入恶意 Markdown/分享页/选区内容测试。

### Phase 9: Polish & MVP Release Gate

- [x] T057 [P] 在 `apps/web/tests/e2e/` 补齐首次使用、空画像、学习目标、草稿审核 E2E。
- [x] T058 [P] 在 `apps/extension/tests/e2e/` 验证 arXiv/HF 页面、当前页授权和登录失效状态。
- [ ] T059 执行 `specs/001-personalized-learning-loop/quickstart.md` 的 E2E-001～022，记录结果与截图（不包含隐私）。
- [x] T060 执行 `specs/001-personalized-learning-loop/checklists/requirements.md`，审核安全边界、数据删除与来源真实性。
- [x] T061 在 `docs/metrics-and-quality.md` 记录真实性能、来源准确率和用户测试结果，调整未验证指标表述。
- [x] T062 更新 `README.md` 的本地启动、测试、部署与回滚说明；提交 release note 和尚未解决问题。

## Dependency Graph

```mermaid
flowchart LR
  S[Setup + Foundation] --> U1[US1 GitHub Knowledge]
  U1 --> U2[US2 Learning Planner]
  U2 --> U3[US3 Guided Reading]
  U3 --> U4[US4 Chat Share]
  U3 --> U5[US5 Verified Feedback + PR]
  U5 --> U6[US6 Reliability & Portability]
  U6 --> R[Polish & Release Gate]
```

- 技术基础必须先可运行，跨用户权限和 Fake LLM 不能留到最后补。
- **首个可演示纵切**：US1 → US2 可生成个人计划；**首个完整 MVP**：US1 → US2 → US3 → US5；US4 可用实验功能标志独立完成，不影响主链路验收。
- 并行示例：US3 的 arXiv/HF Adapter 可在 `tutor.py` API 契约稳定后并行；US5 的前端 Diff 页面可在 Artifact DTO 固定后并行；不同任务同文件编辑不标记 `[P]`。

## Definition of Done per User Story

- US1：E2E-002～005；每条知识状态有证据路径，重复导入不重复。
- US2：E2E-001/006；无知识库也能生成解释性计划，历史 revision 存在。
- US3：E2E-007～010；侧边栏仅处理已授权页面，引用可定位。
- US4：E2E-011～012；访问失败可安全降级，AI 内容不增掌握度。
- US5：E2E-013～018；显式批准后 PR、失败草稿保留、下一次计划有变化依据。
- US6：E2E-019～022；跨用户不可访问，数据清理准确，恶意内容不可操控工具。

## Future Feature Policy

V0.6+ 的 Notion、Hexo 写回、桌面端、自动化发现/研究洞察、Coding Agent 远程执行等，必须先在新的 `specs/002-*`、`specs/003-*` 中定义独立规格和验收；不得以 `docs/roadmap.md` 为由提前写入本任务表。


## 发布门槛保留（2026-10-26）

T059 的本地 E2E-001～022 路径已逐项记录，身份/Provider/App 代码与离线接入已通过，
但真实模型质量、真实 GitHub 授权、网页人工抽检与真人连续学习尚未验收，因此保持未完成。
T060 已执行审核并明确
CHK020 未通过；T061 已记录真实的本地测试结果和 0 名真人研究，不代表目标指标达标。
T062 为本地 release note/启动回滚文档交付，未发布、推送或创建真实远端 PR。

## MVP 接入缺口补齐（与 T059 的真实服务验收分开）

- [x] T063 正式独立账号/密码/恢复与会话方法隔离、频率限制、Web/MV3 UI。
- [x] T064 OpenAI Responses Provider、有界结构化输出、授权与用户/部署每日预算。
- [x] T065 GitHub App OAuth/PKCE、选择已授权仓库、最小范围短期令牌、续期/撤销与写目录审批。
- [x] T066 正式接入离线协议/安全集成测试、真实浏览器、迁移/回滚/导出删除回归、文档与契约同步。

验收：后端全量 197 passed，认证最终补验 6 passed；Web 8、MV3 3、初始化 3 项通过，
客户端 23 项通过，Python/TS strict、lint/format/build/OpenAPI 漂移检查通过。
本机已备份并升级至 0009，迁移无漂移、API 健康/就绪、Worker 运行；未远程部署。
证据及限制见 `docs/evidence/integrations/README.md`；T059/CHK020 不因此勾选。

## 发布验收推进（ADR-0010）

- [x] T067 有界只读真实公开 arXiv/HF 页面兼容性检查与定位证据；自动检查不代替人工抽检。
- [x] T068 合成账号/学习数据的实际 pg_dump/pg_restore 隔离演练及恢复后校验，不覆盖既有库。
- [x] T069 生产构建的本机缓存页面 p50/p95 测量，记录环境/失败数及可解释边界。

验收：公开页面 10/10、20 个 DOM 锚点匹配；真实恢复 27 张表、学习导出一致且原密码/
加密凭据可用；30 次本机导航 p95 48.6 ms（缓存/304 已确认，错误 0）。
修复真实页面暴露的行内空格问题；客户端 26 项、MV3 3 项、引用相关后端 24 项通过。
报告见 `docs/evidence/release-verification/`；不替代真实密钥、生产环境或真人验收。

## 本地试用交付（2026-10-27）

- [x] T070 提供可重放的本地试用指南，包含固定端口、账号/恢复码、学习流程、插件安装、停止与重启；执行提交前检查。

入口：`docs/local-trial.md`，README 已链接。后端全量 197 passed（91.62s），客户端 26 项、
strict/lint/format、OpenAPI/TS 漂移和 Web/MV3 构建通过。试用插件已构建为本机 API 18000；
构建产物与依赖/密钥不进入版本控制，拉取代码后按指南重建。T059/CHK020 保持待办。
