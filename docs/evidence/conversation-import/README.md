# Phase 6 · 对话导入验收证据

2026-10-25。截图来自实际 Chromium、隔离 PostgreSQL、本地 API/Worker/Web。
分享页通过测试专用 ShareFixtureReader 模拟，账号、问题和代码均为合成材料，不含真实 API token。

- `conversation-candidates.png`：手工文本角色/代码分离、已有知识线索、明确加入/拒绝候选及计划修订。
- `shared-conversation.png`：合成公开分享页解析、源 URL、快照定位和待验证问题。
- `share-access-denied.png`：访问受限、保留失败状态、有限重试与手工粘贴入口。
- `pasted-fallback-history.png`：分享失败后新建粘贴回退，原失败记录和成功材料刷新后均保留。

复现：提供专用 `FRONTIER_TEST_DATABASE_URL` 后运行 `pnpm test:sources`。
该命令现在含来源、规划和对话导入共 5 项浏览器场景；详情在
`apps/web/tests/e2e/conversation.spec.ts`。后端 `tests/test_share_import.py` 另覆盖安全抓取、
幂等、并发、取消/删除、权限隔离、失败原文恢复及有数据的回滚兼容。

本次全部浏览器回归共 10 项通过（业务 5、MV3 2、初始化 3），全量后端 147 项无跳过，
客户端 22 项通过。合成网络不能证明真实在线分享页兼容性或真人学习效果；
本地规则候选不代表模型语义提炼、事实核验或掌握证据。
