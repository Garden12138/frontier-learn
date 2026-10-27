# 验证与笔记审核

2026-10-26，真实 Chromium + 隔离 PG；虚构账号、合成网页、模拟 GitHub。
`apps/web/tests/e2e/learning-loop.spec.ts` 覆盖选择题、明确证据确认、草稿编辑、
Markdown 下载、Diff 审核、创建 PR 和刷新恢复。后端测试补两次会话、合并再索引、
有限重试/取消、响应丢失、权限撤销/失效、重授权、SHA 冲突、默认分支变化和夹带更改拒绝。

- `draft-diff-review.png`：审核前 Diff，按钮须再次勾选确认。
- `pr-created.png`：模拟 PR 状态；不是真实 GitHub PR。
- `extension-assessment.png`：MV3 短测与确认（由插件验收生成）。

来源边界题只产生 LOW 证据，不等于主题概念理解或实践验证。
