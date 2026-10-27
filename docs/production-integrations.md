# 独立账号与外部服务接入

本页描述已实现的配置和验收步骤。自动测试使用离线 GitHub/OpenAI 响应，未调用付费模型，
也未创建真实仓库分支或 PR。真实服务验收仍见 [验收记录](evidence/mvp-acceptance.md)。
工程边界见 [ADR-0009](adr/0009-production-integrations.md)。

## 独立账号

`FRONTIER_PASSWORD_AUTH=true` 默认开启。Web 注册用户名/密码后下载恢复码，再继续使用；
插件使用相同用户名和密码登录。用户名规范化、密码长度 12–128，恢复码只保存摘要。
Web 使用 HttpOnly/SameSite Cookie；插件 bearer 只存受信任的临时扩展存储。
恢复时须提供用户名、恢复码和新密码，下载轮换后的恢复码；旧会话全部撤销，未完成作业取消。
遗失密码及恢复码时没有邮箱重置功能，也不冒充已验证邮箱或 SSO。

Mock 默认关闭，生产禁止开启；它与正式账号隔离，不会自动升级、迁移或合并学习数据。
关闭 Mock 后旧开发会话不能继续访问，独立密码会话不受影响。

## OpenAI 导学

API 与 Worker 使用相同的服务端环境变量，密钥只放本机受保护环境或部署密钥管理中：

| 变量 | 默认 / 用途 |
|---|---|
| `FRONTIER_LLM_PROVIDER` | `local_rules`；显式设为 `openai_responses` 才启用云适配器 |
| `FRONTIER_OPENAI_API_KEY` | 空；服务端密钥 |
| `FRONTIER_OPENAI_MODEL` | 空；显式指定支持 Responses 结构化输出的模型 |
| `FRONTIER_MODEL_USER_CALLS_PER_DAY` | `10` |
| `FRONTIER_MODEL_USER_TOKENS_PER_DAY` | `50000` |
| `FRONTIER_MODEL_GLOBAL_CALLS_PER_DAY` | `100` |
| `FRONTIER_MODEL_GLOBAL_TOKENS_PER_DAY` | `200000` |

用户先在“设置与数据”同意模型处理，再在每次网页导学或追问勾选向 OpenAI 发送本次片段。
两层同意默认关闭；未同意或预算用尽时用本地阅读方法。旧轮次迁移为未同意，不能因部署
开启云模型而自动上传。只发送有界目标、相关证据和当前片段，不发送整库、凭据或浏览历史。

固定调用 `api.openai.com/v1/responses`，`store=false`，无工具调用，输出最多 2048 tokens；
结构、大小和引用再由本地验证。这里只接入网页导学和追问；规划、对话候选和来源边界短测
仍用本地规则，不代表已提供可靠的主题理解测评。Provider 接口可替换，测试使用 Fake。

预算按 UTC 日预留调用次数及保守 tokens（包含上下文/Schema/系统文本字节和输出余量）。
失败或响应丢失不退回预留，阻止低估费用；没有自动付费重试。用户主动重试仍消耗新的额度。
设置页展示本用户预留量；这不是账单金额或供应商实际用量。实际用量可用时另存，不含提示词。
`FRONTIER_FAKE_PROVIDER` 仅为旧配置兼容，不能用它选择运行时云 Provider。

## GitHub App

部署者注册 App、配置回调并保管私钥；学习者只需在 Web 授权和选择仓库。完整配置组为：

| 变量 | 内容 |
|---|---|
| `FRONTIER_GITHUB_APP_ID` | 数字 App ID |
| `FRONTIER_GITHUB_CLIENT_ID` | App Client ID |
| `FRONTIER_GITHUB_CLIENT_SECRET` | 服务端 Client Secret |
| `FRONTIER_GITHUB_PRIVATE_KEY` | 完整 RSA PEM，含真实换行；至少 2048 bit |
| `FRONTIER_GITHUB_APP_SLUG` | 安装 URL 中的 App 名称 |
| `FRONTIER_ENCRYPTION_KEY` | 有效 Fernet 密钥；备份时一并安全保管 |
| `FRONTIER_PUBLIC_API_URL` | 浏览器可达的 API origin |
| `FRONTIER_PUBLIC_WEB_URL` | 浏览器可达的 Web origin，须在 allowed origins 内 |

GitHub App 的用户回调 URL 为 `${FRONTIER_PUBLIC_API_URL}/api/v1/github/callback`。
API/Web 必须同主机名、同协议，端口可以不同；本地请统一使用 `localhost` 或 `127.0.0.1`，
不要混用。若 API 用 18000，记得相应设置 public API URL 与 Web proxy。
外部部署必须 HTTPS。当前不接收安装 webhook；安装后在工作台刷新安装位置/仓库列表。

App 仓库权限：只做导入时 Contents read、Metadata read；若提供可选 PR 写回，则需
Contents read/write、Pull requests read/write（Metadata read）。安装时只选择必要仓库。
应用的安装可能允许写，但读取操作仍只签发单 repository_id 的只读短期 token。
写回另检查 GitHub 用户的 push 权限、单独写目录授权、source version 和逐份 Diff 审批。
GitHub token 的原生范围是仓库；目录限制由应用强制执行。

学习者操作：授权 GitHub 账号 → 安装/选择必要仓库 → 刷新安装位置 → 选择仓库与读取目录 →
确认只读连接。写回还须服务端 `FRONTIER_WRITEBACK_ENABLED=true`，再确认笔记目录，
审核草稿 Diff 后才创建专用新分支/PR；不更新已有分支，不自动合并。

OAuth 使用一次性 state、会话/浏览器绑定、PKCE；换发 token 在服务端进行，加密保存。
自动轮换 refresh token，失败可重新授权。登出、恢复、断开或开始新的授权会使相关旧流程
无法迟到重连。列表每页 100、最多 3 页，超过范围需在 GitHub 缩小 App 安装范围。
断开会清除应用内连接凭据、撤销来源权限并取消关联作业，保留已导入学习证据；它不会
卸载全局 App 或删除 GitHub 文件/分支/PR。外部安装权限由用户在 GitHub 另行管理。

## 部署与数据升级

仓库 Compose 仅供本地开发，固定开发环境及开发数据库凭据。正式部署须另行配置
`FRONTIER_ENV=production`、专用数据库凭据、加密密钥、HTTPS 和 HTTPS allowed origins，
保持 Mock 关闭。浏览器密码登录要求允许的 Origin；插件以显式密码登录获取 bearer。
认证/回调的 URL 参数、请求体、token 不应写入反向代理访问日志；应用关闭敏感 access 日志。

当前迁移为 `0009_real_connections`，先备份、停止 API/Worker，再升级并部署匹配代码。
回退至 0008 会删除密码、恢复摘要、App 凭据、OAuth 状态和计量，撤销正式会话并断开 App
来源；学习记录保留。内部正式用户名保留 `account:` 命名空间，旧 Mock 无法打开这些账号。
再升级不会找回已删凭据，须还原备份。迁移往返和带数据回滚已在可丢弃测试库验证，
这不替代部署环境备份恢复演练。详见 [迁移说明](../services/api/app/persistence/migrations/README.md)。

现已提供 [实际隔离恢复演练](evidence/release-verification/README.md)：真实 pg_dump/pg_restore
恢复合成学习记录、密码与加密连接，并验证导出一致性。脚本只允许专用本机测试数据库，
另建新库且不覆盖原库。正式环境仍须单独演练匹配密钥、供应商凭据轮换和外部作业核对。
