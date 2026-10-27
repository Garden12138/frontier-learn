# Phase 5 · 网页导学验收证据

2026-10-25。本目录截图来自真实 Chromium 中加载的 MV3 构建、隔离 PostgreSQL 和本地
API/Worker/Web，材料、账号、目标均为合成测试数据，不含真实私人文档或 API token。

- `guided-preview.png`：HF 可见 Model Card、解析范围与已定位选区。
- `manual-fallback.png`：不支持的页面安全降级到手工材料，来源标未核验。
- `saved-extension-session.png`：关联目标/任务、快照引用及插件内追问。
- `shared-web-session.png`：同账号在 Web 继续相同会话，保留层级、来源与任务关联。

复现命令见仓库 README 的 `pnpm test:extension`；后端场景见
`services/api/tests/test_citations.py`。本次 2 项浏览器场景通过，第一项逐一操作十份合成网页，
第二项验证双端会话、刷新、注销和服务端撤销。

自动化以真实浏览器级 CDP 工具栏动作授予 activeTab，驱动与 Side Panel 相同的扩展文档。
测试中禁用重复打开的原生侧栏，避免与作为测试标签页打开的同一文档并存；没有给测试扩展
注入全部站点权限或跳过授权。原生侧栏容器的手工体验仍应作为发布前检查。

当前导学输出为明确标记的 LOCAL_RULES 阅读方法；Provider 集成通过 Fake 测试。
十份样本均为合成结构，自动定位匹配不代表 SC-003 真实网页人工准确率或真人学习效果。
