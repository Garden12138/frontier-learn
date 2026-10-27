# 发布验证推进 · 2026-10-26

本轮在 MVP 范围内补充实际公开网络、隔离数据库恢复及本机页面性能证据。
默认不运行付费服务或写入真实仓库。边界见 [ADR-0010](../../adr/0010-release-verification.md)。

## 公开页面

[public-pages.json](public-pages.json) 记录十个真实 arXiv/HF 页面：URL、观察时间、抽取内容
哈希、范围、块数、截断标记与 DOM 定位数量。页面全文和真实账号凭据没有复制到证据目录。
检查只读 GET、每页最多 30 个请求，禁止站点脚本、第三方、表单和模型下载；保留 CSS 以检查
可见性。测试自身的抽取函数由浏览器自动化执行，页面无需运行脚本。在线检查显式 opt-in，
不纳入离线 CI，不将可访问性变化静默跳过。

首次 9/10 通过，发现 HF 模型卡行内标记之间被加入空格，导致抽取引用不等于原文。
修复抽取与回定位的空白规则：保留行内单词/标识符/标点，显式换行作为空白，隐藏内容排除。
新增 3 项单元回归，真实 MV3 样本加入行内链接与换行。
旧快照不重写，旧引用无法匹配时保留“无法精确定位”的降级。

最终十页、20 个抽样锚点匹配。只抽取当前可读摘要/模型卡/HTML 范围，HTML 长文可能截断；
未阅读完整论文或执行模型。自动匹配及代理核对不能计作 SC-003 的真人人工抽检。

重放：根目录 `FRONTIER_LIVE_PAGE_CHECKS=true pnpm test:live-pages`。
逐例数据在 `test-results/live-pages/report.json` 的 `compatibility.json` attachments；
公开证据仅收录去除 Playwright 本机路径等运行信息后的汇总。

## 实际备份恢复

[backup-restore.json](backup-restore.json)：真实 PostgreSQL 16 pg_dump/pg_restore，恢复 27 张表。
合成独立账号 → 目标/计划 → 导学/短测/确认 → Markdown 草稿，加一个合成加密 GitHub 凭据。
完整导出（仅去掉本次导出时间）逐字一致，原密码可登录，原服务端密钥可解密连接。
无远程请求、无付费模型、无外部写入。dump 84,160 字节，导出比较 23,132 字节。
dump/restore/校验耗时 0.642 秒，仅适用于这个小型合成数据集，不作为生产 RTO。

脚本硬性要求本机 Compose 测试端口/用户/数据库，另建两个随机临时库，恢复到其中的新空库；
既有测试、开发及生产库不被覆盖。临时 dump 权限 0600，最后删除 dump 和新建库。
已额外验证传入开发库地址在任何数据库操作前失败，响应不输出地址、凭据或驱动异常。

从 `services/api` 运行：

```sh
FRONTIER_TEST_DATABASE_URL=postgresql+asyncpg://frontier:test_only@127.0.0.1:55432/frontier_test uv run python -m tests.acceptance.backup_restore
```

正式恢复需停止 API/Worker、确认备份与匹配代码/密钥，在新隔离库恢复并校验后再切换。
恢复时先保持云 Provider/写回关闭，核对未完成任务及外部 token/PR 的实际状态，再恢复 Worker。
数据库备份不能恢复已轮换的供应商 token，也不能撤销备份之后的外部操作；这仍需真实环境演练。

## 页面耗时

[local-web.json](local-web.json)：生产 Vite 构建/preview，实际 Chromium + HTTP + PostgreSQL，
独立密码账号与已持久化学习计划。macOS arm64，本机 loopback，单用户串行、无 CPU/网络限速。
5 次预热后测 30 次，从导航开始到学习任务按钮可见且可操作。每次都记录浏览器 CDP 缓存/
304 证据，本轮静态资源通过 HTTP 304 校验后复用，不假设“预热过”等于命中缓存。

| p50 | p95 | 最大值 | HTTP/传输/页面错误 |
|---|---|---|---|
| 44.0 ms | 48.6 ms | 50.6 ms | 0 / 0 / 0 |

测量值与测试套件总耗时分开记录。它是小数据、本机串行的基线，不能作为标准网络/并发负载下
达到 Spec 首屏 p95 <3 秒的发布证据，也不代表云模型延迟、在线费用或真人学习效果。
独立注册和密码哈希在测量前完成，未计入重复导航耗时。

根目录重放（需空的专用测试库，与 pytest/业务/MV3 浏览器测试顺序运行）：

```sh
FRONTIER_PERFORMANCE_CHECKS=true FRONTIER_TEST_DATABASE_URL=postgresql+asyncpg://frontier:test_only@127.0.0.1:55432/frontier_test pnpm test:performance
```

真实服务及人工验收仍见 [剩余发布门槛](../mvp-acceptance.md)，T059/CHK020 保持未完成。
