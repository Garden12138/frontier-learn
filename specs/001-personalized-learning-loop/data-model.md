# Data Model: Personalized Learning Loop

> 设计草案。主存储 PostgreSQL；所有面向用户的数据必须具备 user_id 边界。主键建议 UUIDv7 / UUID，采用一致策略；时间统一 UTC 存储，前端本地化展示。

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
