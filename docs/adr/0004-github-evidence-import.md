# ADR-0004 · GitHub 只读导入、证据与范围

Status: Accepted for MVP · 2026-10-25

## 决策与边界

- 逐用户连接指定仓库；默认只读，写入 scope 为空。支持最多 5 个文件夹前缀，
  大仓库可缩小导入范围。修改范围、暂停、恢复采用 source version，取消旧同步；
  下次同步撤回范围外的当前证据，历史内容由用户在断连时选择删除。
- 单来源每次快照最多 200 个支持的常规文件、10,000,000 bytes 可解析正文；
  Markdown 单文件 1,000,000 bytes，代码文件 128,000 bytes，最多 1000 个块/文件。
  symlink、submodule、二进制、构建目录不执行、不索引为已掌握。
- 首次读取固定提交的完整 tree；recursive tree 被截断时按目录遍历，最多 512 次
  HTTP 请求/尝试、40MB 响应正文，tree 单响应最多 8MB。获取不完整或批次超限时不推断删除。
  限流或权限失效停止继续拉取；单个坏文件只形成失败记录，其余文件继续。
- Blob 采用 Git 对象 SHA-1 验证完整性（非密码用途），正文另保存 SHA-256。
  每个 `source + path + blob_sha` 版本唯一；旧证据标 RETRACTED，保留提交锚点。
  同来源重复内容只保留一个当前证据位置；相同内容的移动仅是候选，不断言真实 Git rename。
  不同来源证据独立保存，删除某源不能删掉其他源或独立用户修正。
- 网络使用 HTTPCore 公共 Network Backend：每次请求检查 host allowlist 和所有 DNS IP，
  TCP 仅连接已验证的最多两个 IP，TLS/SNI/Host 保留原域名且验证证书；禁用隐式代理、
  自动重定向及压缩解码，防止 DNS 重绑定、凭据转发和压缩膨胀。
  依据：[HTTPCore Network Backends](https://www.encode.io/httpcore/network-backends/)、
  [GitHub Git Trees](https://docs.github.com/en/rest/git/trees)。
- 本地确定性提取标题、术语和代码线索，最多 32 个候选/文件，不调用云端模型。
  精确段落、行号、文本偏移、时间和方法随证据保存；笔记/代码仅产生 EXPOSED，
  AI_CLAIM 不提升等级。用户纠正需理由和版本，独立记录为 SELF_REPORT，不能伪称已验证。
- 知识状态更新用用户级 PG 事务锁，证据指纹变化递增版本；来源使用单个 active job，
  每次提交前重验用户、版本、状态、租约和截止时间，防止取消后迟到结果写入。
- Web 使用 HttpOnly / SameSite=Strict 会话 cookie（生产 Secure）支持刷新；
  cookie 授权的变更请求要求 Origin allowlist。短期 bearer 仅保留内存，不写 DOM/本地存储。
  开发 Mock 账号依然默认关闭且生产禁止；正式身份仍属发布前未完成项。
- 凭据只通过受保护的 API 接入并服务端加密，工作台不提供粘贴 token 的 DOM 输入框。
  私有仓库需要已有服务端授权；没有授权时明确失败。OAuth/App 接入体验尚未验收。

## 验证与限制

隔离 PG + Mock GitHub 做增量、删除、移动、重复、坏文件、取消与权限验收；
真实 Chromium 连接同一个 API/Worker 查看引用和断连。浏览器服务器只在 tests 中存在，
拒绝非空/未显式指定的测试库，结束时 SIGTERM 清理，不能放入生产镜像。
200 文件 / 10MB 负载使用合成文本与模拟网络，不代替真实网络性能或真人学习效果。
公共 GitHub API 的一次无凭据实际连接返回 403；已验证网络/TLS 可达，未据此声称真实仓库导入成功。
