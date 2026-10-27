# ADR-0002 · MVP 工程默认值

Status: Accepted for MVP implementation under existing AGENTS.md and approved Spec · 2026-10-24

## 决策

- pnpm workspace，Node 22，Python 3.12，uv 管理 Python 依赖并提交 lockfile。
- Web 用 React、Vite、TanStack Query；插件用 WXT、React、MV3 Side Panel。
- PostgreSQL 16 为开发及集成测试主数据库；async SQLAlchemy 2 + asyncpg；
  Alembic 管理显式迁移，不在 API 启动时隐式 create_all。
- API 的存活检查 `/api/v1/health` 不依赖数据库；就绪检查额外探测数据库，失败返回 503。
- DB Job + 独立 Worker，不引入消息队列。初始化 Worker 是可终止的空轮询骨架，
  业务任务消费将在 T010 实现并验收，不能视为已支持同步或回写。
- 开发默认 Fake Provider、模拟身份关闭、外部写回关闭；不附带真实 token 或可用于生产的密钥。
- 正式身份、预算上限、同步大小限制及 Provider 网络策略在对应阶段继续记录决策，
  未实现部分不能通过配置开关伪装可用。

## 理由和验证

保持 Plan 已提出的栈和边界，避免未经验证的基础设施。
依赖及迁移通过实际安装、静态检查、单测和隔离 PostgreSQL 验证；
Web/插件均必须真实构建。用户研究指标仍由独立验收报告记录。
