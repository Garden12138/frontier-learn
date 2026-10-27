# Requirements Quality Checklist

> 本清单默认**未打勾**。每个方框需由项目实现者依据实际检查/测试结果确认，不因为文档生成就自动视为完成。

## Clarity & Traceability
- [x] CHK001 每个 P1 Story 有独立验证场景及可用测试数据。
- [x] CHK002 产品术语（KnowledgeEvidence、KnowledgeState、LearningPlanRevision 等）与 data-model 一致。
- [x] CHK003 每一项画像的“掌握程度”有证据和不确定性，不存在凭 AI 聊天直接判定掌握的暗示。
- [x] CHK004 所有来源声明可追踪，网页不支持或解析失败不会生成伪引用。
- [x] CHK005 P1 当前目标与未来 Roadmap 清楚分离，不混入桌面端、全自动发布等功能。

## Architecture & Security
- [x] CHK006 API 接口与技术方案一致，身份/授权边界明确。
- [x] CHK007 支持最小权限与数据源级撤销，令牌不在日志/DOM/Prompt 出现。
- [x] CHK008 服务端 URL 导入有 SSRF（含 DNS/重定向）防护方案和测试。
- [x] CHK009 不可信文档/聊天内容不能要求模型调用可写工具。
- [x] CHK010 GitHub 写入只能用户审批并创建 PR，冲突后不会改动默认分支。
- [x] CHK011 所有跨用户敏感对象均由 API 执行 user_id 范围授权。

## Testability & Delivery
- [x] CHK012 tasks.md 含完整依赖序列、正确的 Story ID、文件路径和验收/测试任务。
- [x] CHK013 导入和写回具备重复请求的幂等条件与可回放测试。
- [x] CHK014 Web 和 Chrome Side Panel 共用一个 Learning Engine，不分叉个人画像与计划。
- [x] CHK015 无 GitHub/无 API/分享页无法解析均有安全降级。
- [x] CHK016 有至少两次连续学习的闭环验收案例，第二次计划理由可追溯。
- [x] CHK017 知识导出、内部删除和外部数据保留区别有 UI/文档说明。
- [x] CHK018 性能/可靠性门槛是待验证的目标，非未经测试的已达指标。
- [x] CHK019 代码生成前运行 spec/plan/tasks/contract 一致性分析，解决阻断项。
- [ ] CHK020 发布前运行测试/演示并提供证据，不以“已写代码”代替验收。


## 审核依据（2026-10-26）

CHK001–005：`spec.md`、实际模型/契约、各 Story 集成测试及来源边界题的 LOW/EXPOSED 规则。
CHK006–011：`auth/dependencies.py`、`security/`、HTTP 目标/IP 固定、独立目录写授权和
`test_writeback_safety.py`。默认分支无法通过写回接口更新，已有专用分支不能夹带额外变更。
CHK012–016：tasks 依赖、共享 Client/Guide/Assessment、两次连续会话和丢失响应恢复测试。
CHK017–019：设置页、portability 测试、指标未测说明、首轮 specification-review 与 ADR-0008/0009。
T063–066 追加独立密码/恢复、Mock 隔离、OpenAI 双预算、App OAuth/PKCE/单仓库令牌及撤销回归。
上述为独立账号及开发身份/合成网络下的检查；外部适配器已实现，但不代表真实服务联调通过。
CHK016 为合成的两次学习状态机证据，不替代 SC-005 真人案例。

T067–069 补充十个真实公开页面/20 个 DOM 锚点、实际合成数据恢复及本机缓存 p95；
修复行内引用空格并通过 MV3/单元/后端引用回归。仍不替代真实密钥、生产环境和真人验收。

CHK020 保持未完成：工程测试/截图已提供，但真实服务和人工发布门槛尚缺。
完整差异与后续输入见 `docs/evidence/mvp-acceptance.md`；不据此宣称已可生产发布。
