# MVP 验收记录 · 2026-10-26

范围：单机隔离 PostgreSQL、实际 Chromium/MV3、独立密码及开发身份、本地规则与云适配器
离线协议、合成 GitHub/分享/网页。
这是可重放的工程验收；未进行真实远端写入或付费模型调用，不作为正式发布或真人学习效果结论。

| 场景 | 本地证据 | 结果与限制 |
|---|---|---|
| E2E-001 | `test_planner.py`、`planning.spec.ts` | 无来源、拒绝自评仍有有界计划 |
| E2E-002–005 | `test_github_ingest.py`、`test_ingest_boundaries.py`、`sources.spec.ts` | 合成导入、版本去重、局部删除/移动、坏文件；仅术语不推断熟练 |
| E2E-006 | `test_planner.py`、`planning.spec.ts` | 目标/时间预算、阶段/任务/理由和修订；真实语义编排未验收 |
| E2E-007–010 | `test_citations.py`、`current-page.spec.ts`、十份网页 fixtures | 实际 MV3 临时授权、摘要/HF、引用和降级；默认 LOCAL_RULES，真实模型用途解释与真实站点人工抽检未验收 |
| E2E-011–012 | `test_share_import.py`、`conversation.spec.ts` | 合成分享/粘贴、角色/代码、拒绝/加入、403 和文本回退；真实在线分享兼容性未验收 |
| E2E-013 | `test_learning_loop.py`、Web/MV3 短测场景 | 保存来源边界选择题、作答、rubric、理由、限制和时间；确认前无证据；答对仍 LOW/EXPOSED，非主题掌握 |
| E2E-014 | `test_writeback_safety.py`、`learning-loop.spec.ts` | 未审核/未确认不发生外部修改；预览只读 |
| E2E-015–016 | `test_writeback_safety.py`、`learning-loop.spec.ts` | 合成 Git tree/commit → 新分支 → PR；响应丢失核对已有分支/PR；无更新既有分支接口 |
| E2E-017 | `test_writeback_safety.py` | SHA/默认分支变化、Token 失效、重新授权、取消、专用分支夹带更改均保留草稿，拒绝覆盖 |
| E2E-018 | `test_merged_pr_reindexes_and_replans_once` | 合成 PR 合并证明 + 内容哈希核对 + 实际 PG 再索引 + 只追加计划修订；不将笔记当掌握 |
| E2E-019 | `security/`、各 Story 越权测试 | 统一 user_id 授权，其他用户请求返回拒绝；导出无其他用户内容 |
| E2E-020 | `test_portability.py`、`sources.spec.ts` | 来源派生内容删除，独立来源/短测保留；会话删除清理其派生短测/草稿/证据 |
| E2E-021 | `test_prompt_injection.py`、`learning-loop.spec.ts` | 文档/选区/模型输出不能授权工具；脚本作为文本、Markdown 围栏隔离，真实浏览器无脚本执行 |
| E2E-022 | `test_portability.py`、`learning-loop.spec.ts` | 离线 JSON 含 Markdown/记录、无认证/加密凭据；20MB/20000 行上限明确失败，删除后二次确认和旧会话失效 |

两次学习因果案例：`test_two_sessions_confirmed_evidence_replans_without_mastery`。
第一次确认来源边界答对 → revision 2 / CHECK；第二次答错 → revision 3 / REVIEW。
两版原因均含对应短测 ID，画像仍 EXPOSED/LOW。它证明状态机和因果溯源，不证明真人学习有效。

可 review 截图：[草稿 Diff](learning-loop/draft-diff-review.png)、[PR 状态](learning-loop/pr-created.png)、
[导出与删除确认](ownership/confirmation.png)。全部使用虚构账号、合成原文和模拟 PR。
既有来源、规划、网页/对话截图位于相邻目录。

## 正式接入代码验收（T063–T066）

| 能力 | 验收证据 | 结论 |
|---|---|---|
| 独立账号/恢复 | `security/test_password_auth.py`、`real-connections.spec.ts`、MV3 密码登录场景 | 实际 scrypt/PG、Web Cookie、扩展 bearer、恢复码轮换、旧会话/未完成作业撤销；不依赖 GitHub |
| 认证边界 | 正式/Mock 隔离、生产拒绝开发会话、Origin/限流/带数据回滚测试 | 私密账号不由 Mock 打开；备份恢复和正式域名部署仍需环境验收 |
| OpenAI Responses | `test_openai_provider.py`、`integration/test_model_budget.py`、Web 云导学场景 | 真实适配器解析离线协议；结构/拒绝/超限、逐轮授权、用户/全局预算、撤销后迟到结果阻断 |
| GitHub App | `integration/test_github_app.py`、`real-connections.spec.ts` | OAuth/PKCE/浏览器与会话绑定、仓库选择、单仓库短期令牌、refresh 轮换、写权限分离、断开后迟到回调拒绝 |
| 所有权/回写 | App 路径全程模拟 PR、现有 portability/writeback 回归 | 读写令牌分离，目录/Diff/lease 校验继续生效；导出无凭据，内部删除不动外部仓库 |
| 迁移/契约 | 0009 往返及带学习记录回滚、OpenAPI/TS 漂移检查 | 正式 identity 命名空间保留；旧导学默认不同意云处理；回滚删除凭据需备份恢复 |

本轮后端全量 197 项通过，客户端单元测试 23 项通过。浏览器及本机部署证据与边界见
[接入截图说明](integrations/README.md) 和 [质量记录](../metrics-and-quality.md)。
离线协议验证不证明真实 token、当前供应商权限、网络可用性或模型教学质量。

## 发布验证增量（T067–T069）

- 真实公开网络：10 个 arXiv/HF 页面、20 个抽样 DOM 锚点匹配，站点脚本关闭。
  发现并修复行内标记额外空格；仍不计作 SC-003 真人抽检。
- 实际隔离 pg_dump/pg_restore：27 张表、学习导出一致，原密码及原密钥解密验证通过；
  仅合成数据/新建临时库，不替代生产恢复演练。
- 生产构建本机缓存导航：5 次预热、30 个样本，p50 44.0 / p95 48.6 / max 50.6 ms，
  缓存/304 有浏览器证据、错误 0；仅 loopback 串行，不作为标准网络或生产并发指标。
- 相关回归：客户端增至 26 项，实际 MV3 3 项、后端引用/会话 24 项通过，静态检查通过。
  原后端全量 197 项结果保留，本轮只重跑受影响引用集，未重复计数。

原始结构化报告与重放步骤见 [发布验证](release-verification/README.md)。

## 正式发布仍缺少的证据

- 正式域名上独立登录/恢复的部署验收；恢复码需用户妥善保管，当前没有邮箱重置。
- 使用真实 GitHub App、真实用户授权及 token 的最小权限/撤销验收；连接体验已用离线响应验证。
- 真实模型解释质量、费用和引用抽检；适配器已实现，默认仍是本地规则且逐次云处理默认关闭。
- 主题理解/应用评价的可靠性；当前短测只验证来源边界，LOW/EXPOSED，不证明掌握。
- 已授权真实测试仓库的导入、撤销、PR、冲突及合并验收。自动化不触碰真实用户仓库。
- 真实 arXiv/HF 引用真人抽检（自动公开页面验证已完成）、在线分享兼容性、SC-002/SC-005 真人研究（当前 0 名）。
- 标准网络/并发负载下的 p95 和运营成本；已补本机串行基线，不能代替生产响应性能。
- Constitution 恢复草案的用户审阅，以及正式部署域名、TLS、备份/恢复演练。

结论：开发态工程闭环可审核；完整产品/真实服务发布验收尚未完成，T059 保持待办。
