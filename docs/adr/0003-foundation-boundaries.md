# ADR-0003 · 基础鉴权、任务与模型边界

Status: Accepted for development foundation · 2026-10-25

## 决策

- T007 按 Tasks 要求先实现 Mock 登录以验证 user_id 隔离：默认关闭，必须显式设置
  `FRONTIER_MOCK_AUTH=true`；production 模式启动时禁止 Mock。它没有密码验证，
  不能用于真实账号或暴露到公网。正式独立身份仍须在 MVP 发布前补齐并验收。
- 会话 token 使用 32 随机字节，仅保存 SHA-256 摘要；60 分钟到期；注销立即撤销当前会话。
  API 返回短期凭证，客户端只在授权的 UI 上下文/内存或扩展 session 存储使用，
  不写 DOM、content script、日志或模型上下文。GitHub 凭据另以 Fernet 加密，
  密钥必须配置在服务端；密钥缺失则拒绝保存凭据，不使用临时密钥伪装持久化。
- 任务最多尝试 3 次、每次最多 120 秒、总截止 5 分钟，重试等待 `2^attempt` 秒。
  初始预算 unit 是一次 handler 尝试（不是计费 token），每次领取先扣预算。
  T055 与实际 Connector/Provider 实现时补充各外部操作和模型使用的独立计量限制。
  失败任务由用户显式重试，取消不可重试；新操作须新 idempotency key。
- 幂等唯一键为 user + kind + key，并校验 source + payload 的 hash，冲突返回 409。
  Worker 通过 PG `FOR UPDATE SKIP LOCKED` 领取，lease 防止取消后被迟到结果覆盖。
  崩溃租约到期变为可观察失败，不隐式无限重跑。
- 模型接口不暴露写入工具，只接收目标、最多 3 条各 1000 字的证据摘录和
  4000 字的不可信材料；Fake 的 usage unit 为字符，用于确定性测试，不能当真实账单。
  Cloud Provider 必须有独立内容处理授权。真实付费 Provider 不在测试中调用。
- URL 工具仅接受调用方固定的 HTTPS host allowlist，禁止用户信息/特殊端口/私网及
  混合 DNS 结果；返回已检查 IP，实际 Fetcher 必须固定连接 IP 并对重定向重复检查。
  校验后用普通 HTTP 客户端重新解析 DNS 不足以防重绑定；T038 前不得宣称网络获取已安全实现。
- API 请求体上限 1,000,000 bytes，逐块计数，不信任 Content-Length；读取请求体最多
  10 秒。导入文件/批次有独立限制，不通过扩大 Web API 请求上限绕过。
- `contracts/openapi.runtime.json` 由应用导出，生成共享 TypeScript 类型；原
  `openapi.yaml` 仍是未完整实现的规划草案，发布前应统一为完整实际契约。

## 结果

先验证真实 PostgreSQL 用户隔离、token 撤销、任务并发与故障边界，再接入知识源。
保留正式身份与真实 Provider 的验收缺口，不能把本阶段模拟能力当作完整 MVP。
