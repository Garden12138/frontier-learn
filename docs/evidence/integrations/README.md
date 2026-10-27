# 独立账号、模型与 GitHub App 验收

2026-10-26，实际 Chromium/MV3 + 隔离 PostgreSQL + 虚构独立账号。
GitHub OAuth/token/API 和 OpenAI Responses 使用离线响应，应用运行真实适配器；
没有付费 API 请求、真实用户仓库修改或远程发布。

- [GitHub 连接](github-app-connected.png)：虚构 `fixture-learner`、选择安装/私有仓库、
  同步、单独授权 `notes/` 写目录；界面明确逐稿审核与外部文件保留。
- [逐次云处理](cloud-guide-opt-in.png)：合成材料/模型输出、来源匹配及待验证标记，
  追问的 OpenAI 授权默认未选中；不会将解释当作掌握证据。

截图由 `apps/web/tests/e2e/real-connections.spec.ts` 生成并人工查看。
注册/恢复期间的下载文件没有复制到证据目录，截图不含密码、恢复码或 token。

| 检查 | 结果 | 证据范围 |
|---|---|---|
| 后端全量 | 197 passed / 0 skipped，93.66s | 隔离 PG，含旧业务、0009 往返/有数据回滚、并发撤销与成本边界 |
| 认证最终补验 | 6 passed，9.91s | 关闭 Mock 的开发/生产均拒绝旧开发会话；正式密码会话正常，恢复取消任务 |
| Web | 8 passed，29.7s | 来源/规划/对话/短测/审核/所有权及独立账号/App/云处理全流程 |
| MV3 | 3 passed，12.8s | 十份合成网页、跨端共享、真实密码登录及临时存储 |
| 初始化 | 3 passed，2.4s | API 断线恢复、Web、插件加载 |
| 客户端单元 | 23 passed | API Cookie 认证竞态、页面提取/定位、基础 UI |
| 静态/契约/构建 | 通过 | Ruff lint/format、mypy strict 109 文件、TS strict、ESLint、OpenAPI/TS 漂移、Web/MV3 构建 |
| 本地部署 | 0009 head、alembic check 无差异；health/ready 200 | 已备份既有开发库，PG/API 健康、Worker 运行；云 Provider/外部写回默认关闭 |

可重放命令见根 README。后端 pytest、`pnpm test:sources`、`pnpm test:extension` 共用
显式可丢弃测试库，必须顺序运行。插件测试会构建连接测试端口的版本，验收后已重新构建
默认 API 8000 版本；若日常 API 使用 18000，安装前需以对应 origin 重建。

测试时间是套件总时间，不代表请求 p95、生产可用性、真实账单或教学质量。
真实凭据/授权、网页人工抽检、真人两次连续学习、生产备份恢复仍见
[未完成发布门槛](../mvp-acceptance.md)。
