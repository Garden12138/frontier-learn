# ADR 0009：MVP 正式接入默认值

2026-10-26，补齐现有 US1/US3/US6，不增加 Roadmap 能力。

- 正式身份采用独立用户名/密码，不要求邮箱服务或 GitHub。密码采用 scrypt N=2^17,r=8,p=1，
  每密码随机盐；哈希离线线程执行并限并发，认证按来源与账号限制频率。注册/恢复仅一次返回
  高熵恢复码，用户主动下载保管，数据库仅保存摘要；不发送邮箱、不冒充已验证邮箱。
  恢复码轮换，恢复后旧会话全部撤销。Mock 不可进入有正式凭据的账号，生产拒绝开发会话。
- 云 Provider 使用固定 api.openai.com 的 Responses/结构化输出，服务端配置模型与密钥，默认关闭。
  仅有界片段、有独立用户同意、无工具、store=false；错误内容不进日志/响应。
  每日先保守预留输入 UTF-8/Schema 字节与输出 token 上限，按用户/部署双重限制；失败保留预留，
  防止响应丢失后低估费用。每用户默认 10 次/50000 token，部署 100 次/200000 token；无自动付费重试。
- GitHub App 使用服务端私钥换取单仓库、短期且权限最小的 installation token；用户 OAuth
  状态绑定发起会话与浏览器，使用 PKCE，连接凭据加密、不可进入 DOM/日志/提示词。
  只读连接与显式写目录授权分开；撤销连接使所有关联来源/作业失效。API/Worker 均校验拥有者。
- 自动测试全部离线合成，不调用收费模型，不创建真实 PR。部署需配置真实应用回调、HTTPS、
  App 私钥及模型密钥后另做授权验收；未配置时 UI 明确显示不可用并保留本地路径。

依据：[OWASP Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)、
[OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)、
[GitHub App 回调](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/about-the-user-authorization-callback-url)。


实现补充：预算日为 UTC，不随学习目标时区变化。每日预算在发请求前事务性预留，未授权/
未选择本次云处理不收费；用户删除账号不清除部署级匿名累计额度，避免重注册绕过费用上限。
每条导学/追问独立保存 cloud_processing_allowed（默认 false），与当前全局授权同时满足才发云请求；
旧会话迁移默认 false，避免部署开启模型后自动发送旧材料。取消/撤销使 lease 失效，迟到答案不落库。
GitHub OAuth 使用同 host/scheme 的 API/Web，允许不同本机端口；state 同时绑定登录摘要、
HttpOnly/Lax 浏览器 nonce 与 PKCE，登出/恢复后的旧登录不能完成回调。回调只重定向受信任的 Web。
GitHub refresh token 轮换在独立事务提交，后续仓库检查失败不回滚已换发的凭据。
App token 仅存本次操作内存，限定单 repository_id，读取要求用户 pull，写入另要求 push。
断开为当前学习账号撤销应用内凭据及作业；GitHub 外部安装权限可由用户在 GitHub 管理，
不会卸载影响其他学习账号的 App 安装，也不会删外部文件/PR。列表每页 100、至多 3 页。
所有 HTTP 客户端与 uvicorn access 日志关闭敏感 URL/请求体输出；普通结构化状态日志保留。

生产密码登录只允许配置 HTTPS Web origins，浏览器登录/注册/恢复必须提供已允许的 Origin；
扩展使用显式密码换取临时 bearer，不依赖跨站 Cookie。缺少 Origin 的生产 Cookie 登录拒绝。

正式用户内部 identity 使用 `account:<规范化用户名>`，公开 DTO/导出仍显示普通用户名。
冒号不在旧 Mock 登录允许字符内，回滚后也不能用旧无密码入口进入原正式账号；
新代码还会主动拒绝与正式用户名同名的 Mock 登录。Mock 数据不自动升级或合并到正式账号。

并发补充：预算预留先锁作业，再锁预算，设置撤销先锁对应作业再锁用户，与删除顺序一致。
登录/恢复/回调按用户父行再凭据/连接子行加锁。恢复会取消未完成作业并撤销旧会话。
OAuth 另保存用户授权 generation，开始新流程、断开或恢复账号都会递增；即使旧 state 已消费
且正在交换令牌，后续断开也能阻止迟到回调重新建立连接。回滚保留正式 identity 命名空间。

关闭 Mock 后旧 DEVELOPMENT 会话也拒绝访问；正式 PASSWORD 会话保持独立。独立账号
恢复、模型授权与 App 连接都不依赖 Mock。已经发起的模型请求可能保留预算，但迟到结果不能
在撤销或删除后重新落库；云模型接收方在每次确认界面明确标为 OpenAI。
