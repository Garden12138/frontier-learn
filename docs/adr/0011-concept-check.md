# ADR-0011 · 原文支持的概念选择题

Status: Accepted for MVP implementation · 2026-10-28

- 补齐 Spec FR-013，不把固定来源边界题视为主题理解。沿用每会话一份短测的边界，
  用户可选原边界题或新概念题；已保存题目不能静默替换。
- 新题由 ASSESSMENT_QUESTION 有界后台任务生成；用户全局与本次授权均需开启，
  复用模型预算预留、超时、有限手动重试和撤销/取消的 lease 防护。没有自动付费重试。
- 只发送本次主题及最多 1800 字符的一个来源块；不发送用户作答、全库或凭据。
  选定的来源块与模式可复查；模型必须提供该块内至少 12 字符的逐字依据，不匹配即失败。
- Responses 使用既有结构化输出和无工具边界；规范见
  [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)。
  结构有效与引文存在均不保证语义正确，界面明确标为“模型拟题/答案依据，待复查”。
- 正确答案键保存在私有 grading 字段，不进入作答前 API 响应。提交后按保存的键比较，
  返回依据供用户复查；不是另一次模型自评，不显示掌握百分数。
- 结果使用 MODEL_CONCEPT_CHECK/LOW；确认前不写证据。正向结果仍需独立解释，负向进入
  REVIEW，不从一道题推断熟练。导出保留题目/依据，删除会话同时删除相关任务和记录。
- 自动测试使用 Fake/离线响应；真实收费调用和远端写入仍须单独授权。
