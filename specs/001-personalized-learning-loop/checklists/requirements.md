# Requirements Quality Checklist

> 本清单默认**未打勾**。每个方框需由项目实现者依据实际检查/测试结果确认，不因为文档生成就自动视为完成。

## Clarity & Traceability
- [ ] CHK001 每个 P1 Story 有独立验证场景及可用测试数据。
- [ ] CHK002 产品术语（KnowledgeEvidence、KnowledgeState、LearningPlanRevision 等）与 data-model 一致。
- [ ] CHK003 每一项画像的“掌握程度”有证据和不确定性，不存在凭 AI 聊天直接判定掌握的暗示。
- [ ] CHK004 所有来源声明可追踪，网页不支持或解析失败不会生成伪引用。
- [ ] CHK005 P1 当前目标与未来 Roadmap 清楚分离，不混入桌面端、全自动发布等功能。

## Architecture & Security
- [ ] CHK006 API 接口与技术方案一致，身份/授权边界明确。
- [ ] CHK007 支持最小权限与数据源级撤销，令牌不在日志/DOM/Prompt 出现。
- [ ] CHK008 服务端 URL 导入有 SSRF（含 DNS/重定向）防护方案和测试。
- [ ] CHK009 不可信文档/聊天内容不能要求模型调用可写工具。
- [ ] CHK010 GitHub 写入只能用户审批并创建 PR，冲突后不会改动默认分支。
- [ ] CHK011 所有跨用户敏感对象均由 API 执行 user_id 范围授权。

## Testability & Delivery
- [ ] CHK012 tasks.md 含完整依赖序列、正确的 Story ID、文件路径和验收/测试任务。
- [ ] CHK013 导入和写回具备重复请求的幂等条件与可回放测试。
- [ ] CHK014 Web 和 Chrome Side Panel 共用一个 Learning Engine，不分叉个人画像与计划。
- [ ] CHK015 无 GitHub/无 API/分享页无法解析均有安全降级。
- [ ] CHK016 有至少两次连续学习的闭环验收案例，第二次计划理由可追溯。
- [ ] CHK017 知识导出、内部删除和外部数据保留区别有 UI/文档说明。
- [ ] CHK018 性能/可靠性门槛是待验证的目标，非未经测试的已达指标。
- [ ] CHK019 代码生成前运行 spec/plan/tasks/contract 一致性分析，解决阻断项。
- [ ] CHK020 发布前运行测试/演示并提供证据，不以“已写代码”代替验收。
