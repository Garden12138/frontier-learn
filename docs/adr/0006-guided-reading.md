# ADR-0006 · 用户触发的网页导学

Status: Accepted for MVP implementation · 2026-10-25

## 决策

- 插件无自动 content script、无全部站点授权。`activeTab` 在用户调用扩展后提供临时权限，
  点击“分析当前页”才注入隔离世界的只读抽取函数，仅主 frame，不监听或读取其他标签页。
  换域后需要重新点击工具栏授权；权限不足给出恢复说明，不自动扩大权限。
- 工具栏使用普通 `action.onClicked` 后调用 `sidePanel.open`；禁用自动侧栏 action。
  Chromium 的 `RunAction` 在 `kToggleSidePanel` 路径明确跳过临时权限授予；
  直接 `setPanelBehavior({openPanelOnActionClick:true})` 不足以支持本边界。
  依据：[Chromium ExtensionActionRunner](https://github.com/chromium/chromium/blob/main/chrome/browser/extensions/extension_action_runner.cc)。
- 原理依据：[Chrome activeTab](https://developer.chrome.com/docs/extensions/develop/concepts/activeTab)、
  [scripting](https://developer.chrome.com/docs/extensions/reference/api/scripting)。固定 API 主机权限
  只用于本地后端；可选生产服务接入需另行配置，不接受网页消息指定 API 或执行任意脚本。
- 支持 arxiv.org 的 abs/html 与 huggingface.co 的模型主页；PDF、登录墙、gated 内容、
  非模型路径和结构缺失明确降级。摘要永远标明仅摘要。选区须在被抽取的正文内，无法匹配
  就显示未定位，不把网页控件、隐藏 DOM、脚本或密码字段当正文。无权限时可手工粘贴文本。
- 抽取有字符/块数/节点数上限，仅传文本与定位；不传 HTML、cookies、表单、storage 或密钥。
  所有文本均不可信，React 纯文本展示。模型和网页均不拥有工具执行权限。
- 引用必须是当前会话快照中的逐字文本；服务器只确认“与用户提供的快照匹配”，不冒称独立
  在线核验。回到原文时再次检查 URL 和可见文本，页面变更则标记无法精确定位。
- 会话属于用户，可跨 Web/插件读取。开启会话不增加掌握证据。版本与幂等键防重复和覆盖，
  保存失败/取消状态以供重试；导学上下文仅使用目标、最多三条相关证据及当前选定片段。
- 本地无模型时保留明确标记的规则式阅读步骤；Fake 仅用于自动化，不伪装事实解释。
  后续云模型接入须独立授权并限制上下文、时间及输出，不默认发送完整私人文档。
- 开发态插件只使用同名 Mock 身份验证共享边界；正式身份仍是发布门槛。凭据只保存在
  扩展的受信任 `storage.session`，从不写入 DOM/content script/localStorage/日志。
  [Chrome storage](https://developer.chrome.com/docs/extensions/reference/api/storage) 规定 session
  默认不对 content script 开放；实现同时显式限制为 TRUSTED_CONTEXTS。

## MVP 默认值与实现映射

- API 地址在构建时指定 `FRONTIER_EXTENSION_API_ORIGIN`，默认 `http://127.0.0.1:8000`。
  仅配置该服务的固定 host permission；本机允许 HTTP，远程要求 HTTPS。网页不能指定服务地址。
- 每快照最多 30,000 字符、40 块、每块 2,000 字符，选区最多 1,000 字符；遍历正文
  最多 1,000 个候选元素、10,000 文本节点，预算耗尽显示截断。跨段或超长选区不伪装精确引用。
- `LearningSession` 保存用户确认的快照、内容哈希、可选目标/当前任务和 version；
  `TutorTurn` 保存提问、模式、片段与结果，关联 `Job`。每会话最多 20 轮，每轮最多
  3 次尝试、30 秒、5 分钟截止时间。取消和删除撤销租约；失败保留材料，旧轮次不在新提问后重试。
- 当前 Worker 使用 `LOCAL_RULES` 阅读方法建议；自动测试通过同一 `LLMProvider`
  接口注入 Fake，真实云模型暂未配置。每次上下文只保留目标、当前任务标题、一条前问、
  当前片段及最多三条相关有效知识证据；不发送整页或浏览历史。结构化输出最多 4,096 字符。
  云端处理授权固定关闭，后续须经设置能力启用；没有以开发配置冒充模型授权。
- 相关知识检索为本地标签匹配，在用户最多 200 条候选中选三条，保留证据强度、方法和时间。
  这不是语义检索质量承诺。技术先修标待确认，页面主张不自动成为可信结论或知识证据。
- 会话状态通过通用任务查询；双端提供等待、取消、失败、受限重试、版本冲突恢复和确认删除。
  Web 历史每页 30 条，插件显示最近 30 条；插件刷新使用受信任临时存储恢复登录与历史。
- 数据库 `0005_tutoring` 仅新增会话/轮次；回滚删除本阶段会话和对应任务元数据，保留已有画像/计划。

## 验收限制

十份网页均为合成结构样本，真实 MV3 测试验证授权和定位，但不能替代真实站点兼容性、
人工引用抽检或 SC-003 的真人验收。正式身份、真实模型和云端隐私授权仍是发布缺口。
