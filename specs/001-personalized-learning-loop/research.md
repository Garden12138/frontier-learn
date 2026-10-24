# Research & Decisions (pre-implementation)

## R-001 Spec Driven Development
采用 GitHub Spec Kit 的 `constitution/spec/plan/tasks` 核心结构，适合给 Codex 提供稳定上下文；用户故事与需求放在 spec，技术栈放在 plan，任务按阶段和用户故事拆分。参考：<https://github.github.com/spec-kit/quickstart.html>、<https://github.github.com/spec-kit/integrations/codex.html>。集成命令应以本地版本文档为准，本包未实际执行 CLI 工作流。

## R-002 产品形态
首发 Web + Chrome Side Panel。Side Panel API 官方：<https://developer.chrome.com/docs/extensions/reference/api/sidePanel>。Chrome MV3 的扩展权限与 CSP 需要遵循浏览器要求，避免无授权“读取全部网页”。

## R-003 GitHub 笔记作为首要源
示例仓库 `Garden12138/notes` 包含 Markdown 笔记、代码和部署实践，证明必须区分“内容存在”与“用户真正掌握”。读取时采用 Git tree/Contents API + commit SHA；写入时采用受控分支与 PR 审核。公开仓库示例不构成正式用户权限绑定。参考：<https://docs.github.com/en/rest/repos/contents>。

## R-004 公开博客不等于可写的 Hexo 源
`Garden12138.github.io` 当前可见目录以生成后的 HTML 为主，能做只读索引；Hexo 写回需用户连接 `source/_posts` 所在源码仓库，不能直接覆盖 Pages 发布产物。

## R-005 AI 分享内容不等于可信知识
分享页可能只包含一次分享快照、访问权限可能受限，页面结构可能变化。只做显式导入与解析，失败降级文本粘贴/导出文件；解析后保留说话者与来源，AI 输出标记为“待验证资料”。参考：<https://help.openai.com/en/articles/7925741-chatgpt-shared-links-faq>。

## R-006 Notion 延后为 Connector 插件
Notion 官方 API 支持连接授权的页面和数据；不同内容块结构与富文本同步冲突需单独 Spec，不属于 V0.1-0.5。参考：<https://developers.notion.com/>。

## R-007 不滥用知识图谱/多 Agent
首先以 PostgreSQL、显式关系和来源证据满足 1–数千文档的验证规模；必要时使用 `pgvector` 辅助召回。只有当真实召回/关系查询瓶颈出现，才评估外部向量库和图数据库。学习计划可先由规则 + 结构化 LLM 生成，不强制拆多 Agent。

## R-008 学习验证的局限
单次 AI 小测不能精确衡量现实能力。需要保留评分标准与用户答复，并对技术实践引入外部可检查信号；画像展示“有证据/待验证”，而不是精确能力百分数。

## R-009 Open Questions
| Issue | Default | Decision Trigger |
|---|---|---|
| 登录 | 优先支持 GitHub 登录/独立账号，具体方案工程评估 | V0.1 实施前 |
| LLM 账单 | 开发 Fake + 用户配置 Provider/开发受控密钥 | V0.2 实施前 |
| 任务队列 | 受控 DB Job + Worker | 持续并发压力和可靠性测试后 |
| 页面来源锚点 | Git commit+line / Web selector+textQuote | V0.3 页面样本抽检结果 |
| AI 对话获取 | 公开可访问页面 + 手工文本回退 | V0.4 实际可访问样本测试 |
