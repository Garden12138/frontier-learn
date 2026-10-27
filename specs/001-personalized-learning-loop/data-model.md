# Data Model: Personalized Learning Loop

> 设计草案。主存储 PostgreSQL；所有面向用户的数据必须具备 user_id 边界。主键建议 UUIDv7 / UUID，采用一致策略；时间统一 UTC 存储，前端本地化展示。

当前已实现 Phase 1–8 的开发态闭环，使用 UUIDv4、async SQLAlchemy/PostgreSQL。实际 API DTO 以
`contracts/openapi.runtime.json` 和生成 TS 类型为准；下文通用实体描述与实现映射有区别，实际字段以 runtime 契约为准。
详见 [ADR-0004](../../docs/adr/0004-github-evidence-import.md)。

Phase 3 的具体映射：SourceScope 包含 repository 和 path_prefixes；KnowledgeSource
增加 version / active_job_id。SourceDocument 使用 `(source_id,path,blob_sha)` 唯一保存版本，
另有 revision（提交 SHA）、is_current、deleted_at、renamed_from（候选）；内容不变时保留
原始有效提交引用。SourceChunk 也带 user_id，locator 保存行号与文本偏移；KnowledgeEvidence
记录 ACTIVE/RETRACTED、method 和 excerpt。KnowledgeState 的 evidence_fingerprint 和 version
用于校验并发修正；用户级事务锁协调来源同步与修正。FILE_TITLE 仅是文件名线索，不能冒充正文结论。

Phase 4 的实际映射见 [ADR-0005](../../docs/adr/0005-goals-and-planning.md)：
LearningGoal 保存 version、每日分钟、IANA 时区、优先方向、用户先修及可选自报；
LearningPlan 每目标唯一，active_revision 指向只追加的 LearningPlanRevision.document JSON。
LearningTask 以稳定 UUID 保存当前投影，历史任务不删除；完整历史仍由不可变 JSON 提供。
TaskCompletion 按 `(user_id,task_id,local_day)` 去重，只累计建议分钟，不写掌握证据。
计划来源保存 evidence ID 并在读取时解析当前有效引用，不在历史快照复制私密原文。

Phase 5 的实际映射见 [ADR-0006](../../docs/adr/0006-guided-reading.md)：
LearningSession 按用户和 creation_key 幂等保存经确认的 PageSnapshot（文本块、URL、解析范围、
选区及截断标记），附 content_hash、goal_id/task_id 和乐观锁 version；目标删除后引用 SET NULL。
TutorTurn 将用户 question/mode/selection 与规则或模型 Guide 分开储存，关联有界 Job；
Job payload 只含 turn ID，不复制私人材料。会话删除级联轮次并撤销/删除关联任务。
引用只允许服务器根据快照校验 SNAPSHOT_MATCH；手工材料或不匹配的引用标 UNVERIFIED。
快照匹配不是在线独立核验，也不会产生 KnowledgeEvidence。历史消息设计在本阶段映射为 TutorTurn。

Phase 6 的实际映射见 [ADR-0007](../../docs/adr/0007-conversation-import.md)：
ConversationImport 按用户/creation_key 幂等保存 SHARE URL 或 PASTED 原文、解析 document、
候选 candidates、Job ID 和乐观锁 version。解析快照保留 USER/ASSISTANT/UNKNOWN、
TEXT/CODE、message ID 和 part index；候选逐条引用快照片段，不创建掌握证据。
候选 PROPOSED → ADDED / DISMISSED，只在用户选择时修改；加入计划附计划版本检查与只追加修订。
PlanTask.conversation_ref 仅含 import_id/candidate_id，不复制私人标题、问题或原文；
读取原材料仍须用户授权，删除后显示不可用。失败/取消的手工原文仅对拥有者开放恢复编辑。
0006 回滚移除新表/任务及旧计划 JSON 中的 conversation_ref，以兼容之前的 strict DTO。

Phase 7–8 映射见 [ADR-0008](../../docs/adr/0008-assessment-writeback-ownership.md)：
Assessment 每用户/会话唯一，保存 question/rubric、answer、feedback、version、confirmed_at、
evidence_id 和 plan_revision。SOURCE_COMPREHENSION 证据只能 LOW，不提升理解等级。
LearningArtifact 每用户/短测唯一，保存 Markdown、version、经审核的 WritePreview（来源版本、
默认分支 SHA/文件 SHA/内容哈希/确定性分支/Diff）、write Job、PR、合并与重新索引时间。
通用设计中的 WritebackOperation 实际由 LearningArtifact 的审核/远端状态与 Job 的预算/幂等/lease 联合表达，没有另建同名表。
写凭据与读凭据分别加密，目录受 write_scope 与 path_prefixes 双重限制。只有独立的显式审批
才能发起写 Job；取消/失败可能已有远端结果，重试必须核对。PR 合并与重新索引都不证明掌握。
User 增加默认 False 的 cloud_processing_allowed 和 settings_version；当前仍使用 LOCAL_RULES。
导出是独立 REPEATABLE READ 事务快照，只包含当前 user_id 及其引用的概念标签，排除全部凭据。
删除会话同时删除派生短测/草稿/证据，删除账号级联内部记录；不会删除外部 GitHub 数据。
0007/0008 的升级、元数据校验、有数据回滚与再升级纳入测试。

## 1. Domain Entities

| Entity | Key fields | Invariants / Relationships |
|---|---|---|
| User | id, email_or_provider_id, created_at | 不能将 GitHub 账户作为唯一用户身份假设 |
| KnowledgeSource | id, user_id, provider, external_ref, read_scope, write_scope, status, last_sync_at | 来源授权与凭据分离；删除源支持级联处理派生证据 |
| SourceDocument | id, user_id, source_id, path_or_url, revision, content_hash, title, parse_status, deleted_at | 同 `source_id + external doc key + revision` 内容不重复 |
| SourceChunk | id, document_id, locator, text_checksum, snippet, content_type | locator 支持文件行号或 URL+selector+textQuote |
| KnowledgeConcept | id, canonical_name, aliases, topic, description | 系统概念可跨用户共享，但用户知识状态不可共享 |
| KnowledgeEvidence | id, user_id, concept_id, document_id?, chunk_id?, assessment_id?, kind, polarity, observed_at, reliability, status | 一个证据有明确来源；不能无来源推断熟练 |
| KnowledgeState | id, user_id, concept_id, level, confidence, verified_at, policy_version, user_override? | 唯一 `(user_id,concept_id)`；状态推断可追溯 |
| LearningGoal | id, user_id, title, priority, minutes_per_day, status, created_at | 用户可暂停、更改，目标不等于硬编码职业 |
| LearningPlan | id, user_id, goal_id, active_revision, status | 每个目标可以有多次规划版本 |
| LearningPlanRevision | id, plan_id, revision_no, rationale, source_snapshot, created_at | 只追加版本，支持计划恢复和比较 |
| LearningTask | id, revision_id, type, concept_ids, source_ids, prerequisites, estimate_minutes, status, rank | 任务可暂停/跳过/重排，保留推荐理由 |
| LearningSession | id, user_id, task_id?, source_document_id?, page_url?, mode, status, started_at, ended_at | 来源网页不一定属于 GitHub；同一学习任务可多次会话 |
| TutorMessage | id, session_id, role, content, citations, created_at | 模型内容与用户输入区分，敏感文本加密/保留策略 |
| ConversationImport | id, user_id, creation_key, source, source_url?, pasted_text?, job_id, document?, candidates, version | 个人材料；导入不证明掌握；候选选择与计划修订可追溯 |
| Assessment | id, user_id, session_id, concept_id, prompt, rubric, user_answer, feedback, result, evidence_status | AI 评价不等于真实掌握；可追加人工/代码验证 |
| LearningArtifact | id, user_id, session_id, format, content_md, target_source_id?, target_path?, status, base_revision | `draft → approved → pr_opened → merged/closed`；不自动推主分支 |
| SyncJob | id, user_id, source_id, kind, status, attempt_count, budget, result, started_at, finished_at | 幂等、超时、单任务重试、失败可重放 |
| WritebackOperation | id, user_id, artifact_id, idempotency_key, branch, pr_number?, revision, status | 重试不应重复创建 PR |
| AuditEvent | id, user_id, actor, operation, object_type, object_id, created_at, summary | 不记敏感正文和明文 token |

## 2. Evidence Kinds & Semantics

| kind | Example | Allowed inference |
|---|---|---|
| `VIEWED` | 打开/收藏页面 | 仅“接触过”，不表明理解 |
| `OBSERVED_NOTE` | 仓库出现术语/摘抄 | 有接触证据，可能是引用 |
| `EXPLAINED` | 原创解释笔记/用户口述 | 有理解线索，需验证 |
| `CODE_ARTIFACT` | 仓库代码/配置示例 | 有实现材料，但无法自动确认作者运行成功 |
| `ASSESSED` | 小测作答且有可检查标准 | 可确认部分理解，需记录题目和评价方法 |
| `PRACTICE_VERIFIED` | 有可重现实验及用户确认 | 有应用能力证据，仍需关注环境与迁移性 |
| `USER_SELF_REPORT` | 用户自报掌握 | 用于启动规划，但须标为自报 |
| `USER_CORRECTION` | 用户修正状态/指出错误 | 优先刷新推断并形成审计事件 |
| `AI_CLAIM` | AI 在聊天中解释某知识 | 仅导学资源，不增加用户掌握程度 |

## 3. Knowledge Level (derived state, not source data)

```text
UNKNOWN -> EXPOSED -> UNDERSTANDING -> APPLIED -> PROFICIENT
             ^                             |
             +---- REVISION / REVIEW_DUE <-+
```

- `UNKNOWN`：证据不足；`EXPOSED`：已接触/笔记提及；`UNDERSTANDING`：通过理解验证；`APPLIED`：通过实作或代码证据；`PROFICIENT`：多场景可迁移与近期验证。
- `REVIEW_DUE` **建议做附加 flag**，不要强行当作知识等级降级：例如 `level=APPLIED, review_due=true`；具体需在代码模型中保持一致。
- LLM 只能生成候选证据和评价建议；最终 level 由可解释的 Policy+人工标注影响。
- `confidence` 表示判断的可信程度而不是“掌握 85%”，UI 不展示伪精确的能力百分比。
- 用户强制修改 level 时保留 override 及来源，不丢失原 evidence。接到新证据时产生新的版本。

## 4. Source Locators

```json
{
  "provider": "github",
  "repository": "owner/repo",
  "commit_sha": "abc123...",
  "path": "ai/BPE algorithm analysis.md",
  "line_start": 15,
  "line_end": 42
}
```

```json
{
  "provider": "web",
  "canonical_url": "https://arxiv.org/abs/xxxx.xxxxx",
  "css_selector": "#abstract",
  "text_quote": "A short exact quote",
  "retrieved_at": "2026-10-24T09:00:00Z"
}
```

网页选择器可能失效，定位策略按照 URL+内容哈希、selector、textQuote 逐级回退；引用不可靠时标为“无法精确定位”。

## 5. Status Machines

- **SyncJob**: `PENDING → RUNNING → SUCCEEDED | PARTIAL | FAILED | CANCELLED`；仅 FAILED/PARTIAL 允许受限重试。
- **LearningTask**: `PROPOSED → ACCEPTED → IN_PROGRESS → COMPLETED | SKIPPED | PAUSED`。
- **Artifact**: `DRAFT → REVIEWED → APPROVED → PR_OPENED → MERGED | CLOSED`；用户可 `DISCARDED` 草稿；不能从 `DRAFT` 直接成为 `MERGED`。
- **KnowledgeSource**: `CONNECTED → REAUTH_REQUIRED | PAUSED | DISCONNECTED`；断开默认保留或清理选项必须明确。

## 6. Deduplication & Conflict Policies

- 同一 GitHub 文件：`source_id + external_id(path) + revision/hash` 唯一；移动文件优先按 blob hash 判定候选重命名，变更后追溯记录。
- 不同源重复知识：不合并 SourceDocument，只可以对同一 KnowledgeConcept 关联多条 evidence；用户明确删除某源仅移除该源 evidence。
- Writeback：`(user_id,artifact_id,idempotency_key)` 唯一；重复确认应返回既有 PR；避免同名分支冲突。
- 双向同步默认关闭；MVP 仅 GitHub 增量拉取 + 经审阅的 PR 提交，不实现无冲突实时协作编辑。

## 7. Privacy & Retention

- 授权令牌密文隔离与轮换；错误追踪不得包含密钥。
- 用户可导出自己学习记录/笔记的 Markdown + JSON；删除可选择撤销授权、删除内部已导入正文和派生 evidence，外部源需用户另行操作。
- 外部知识库中的用户可访问内容不等于用户同意传送给任意第三方模型；需要独立的内容处理授权与透明界面。


## 8. 正式接入映射（0009_real_connections）

- User.identity 为正式账号保存 `account:<规范化用户名>`，公开 DTO/导出去掉命名空间。
  不自动合并 Mock 资料，回滚保留该不可被旧 Mock 匹配的命名空间。
- PasswordCredential 按 user_id 唯一，保存 scrypt 编码哈希与高熵恢复码摘要；不导出。
  AuthSession.auth_method 区分 PASSWORD/DEVELOPMENT，关闭 Mock 或生产只接受 PASSWORD。AuthRateLimit
  保存匿名 HMAC 桶及 15 分钟窗口计数，不记录原密码、用户名或 IP 原文。
- TutorTurn.cloud_processing_allowed 是每次请求的最小片段授权，默认 false，独立于 User 全局授权。
  新增字段为 false 时不改变原幂等指纹，旧客户端和旧请求重试兼容。
- ModelBudget 保存 UTC 日、用户或匿名 GLOBAL scope、调用数和保守预留 tokens；GLOBAL 不关联用户。
  ModelCall 按 (job_id,attempt) 唯一，记录预留及供应商报告 tokens，无提示词/密钥。
  任务删除后计量保留但 job_id SET NULL；账号删除清除用户计量，保留无用户标识的部署级汇总。
- GitHubConnection 按用户唯一，加密 user/refresh token、GitHub ID/login、过期及连接状态。
  GitHubOAuthState 保存登录/浏览器/state 摘要、加密 PKCE verifier 和 10 分钟截止；只能消费一次。
  User.github_auth_version 与 State.auth_version 绑定，发起授权/断开/恢复递增；已消费 state
  正在换取 token 时也须重验 generation，阻止断开后的迟到回调恢复连接。
  KnowledgeSource 附 connection_id/installation_id/repository_id；读/写 installation token 仅临时内存，
  不存到 DOM、日志、提示词或导出。连接撤销后来源/作业失效，已确认独立学习证据可保留。
- 回滚 0009 撤销正式会话、断开 App 来源，删除凭据、OAuth 状态及计量；原用户与学习材料保留。
  回滚后无法用密码登录，再升级不能恢复凭据，必须从备份恢复；严禁用 Mock 开放真实私密数据。
