# 开发变更记录

本文件整合重复的逐次执行日志。当前部署与使用以 [本地部署](manuals/LOCAL_DEPLOYMENT.md)、
[使用手册](manuals/USER_GUIDE.md) 为准；本轮结果见 [自动化验收](acceptance/LOCAL_AUTOMATED_ACCEPTANCE.md)。
历史记录中的端口、网络观察和测试数量只代表当时环境，不是当前服务保证。

| 检查点 | 交付内容 | 验收与限制 |
|---|---|---|
| `4f7fce2` | 初始 Spec、Plan、Tasks、产品与路线文档 | 规格基线，尚无业务工程；宪章原文缺失，恢复草案仍待审阅 |
| `84b4837` | Web、MV3、API/Worker、0010 之前迁移、导入到审核写回的开发态闭环、独立账号、OpenAI/GitHub App 适配、本地部署 | [MVP 场景矩阵](evidence/mvp-acceptance.md)、[运维/公开页面证据](evidence/release-verification/README.md)；Fake/合成数据不代表真实服务和学习效果 |
| `ce64ece` | 可选模型概念题、0010 迁移、低强度证据与重规划 | [ADR-0011](adr/0011-concept-check.md)；双重同意，未调用付费服务 |
| `bdf9a8f` | V0.1.1：作答前评分键隐藏、选材修正、有限新任务恢复、取消后迟到结果拒绝、结构质量筛查 | [修复矩阵](evidence/v0.1.1-acceptance.md)、[已推送提交的 CI 终态](evidence/v0.1.1/remote-ci-final.json)；原始公开快照字节及 Git blob SHA 固定 |
| 2026-11-08–11 未提交续验 | 修复插件退出清除同主机 Web Cookie；Spec、ADR-0013、契约/类型及回归同步 | [失败复现](evidence/v0.1.1/preparation-runtime-red.json)、[修复后检查](evidence/v0.1.1/preparation-runtime.json)、[检查输入摘要](evidence/v0.1.1/preparation-checks.json)；这些内容在本轮开始时已存在，已完整保留 |
| 2026-11-11 本轮工程整理 | 清理可再生产物和初始化截图；整合过程文档；重新执行工程验收；交付 Mac 手册及独立整合分支 | [清理记录](review/REPOSITORY_CLEANUP.md)、[功能盘点](review/VERSION_DIFF_AND_FEATURES.md)、[交付总结](review/UPGRADE_CHATGPT_SUMMARY.md)；不启动下一版本 |

## 持续保留的验收缺口

- T073：完整真实目标目录同步未通过。历史无凭据 API 两次限流；Mac 小目录曾成功，
  Docker Worker 的 DNS 曾解析出非公网 IPv6，安全校验拒绝。具体观察保留在结构化 JSON。
- T059 / CHK020：真实模型质量与费用、真实 App/PR/撤销、人工引文核验、真人连续学习、
  正式部署 TLS/负载/恢复和宪章恢复草案审阅均不能由本地 Fake 自动化替代。
- 画像是保守规则提取，不能自动识别任意概念同义词；笔记、阅读、AI 回答和 LOW 测验均不证明掌握。

## 历史可追溯性

早期逐阶段执行数量、临时失败、提交前暂存及 CI 轮询过程已从此入口整合；
具有故障复现/验收价值的 JSON、业务截图、ADR、迁移和安全测试继续保留。
旧已提交全文可由 Git 历史读取；本轮开始时未提交的文档原文也已备份在本机
`/private/tmp/frontier-upgrade-20261111/working-tree-before.tar.gz`（临时恢复材料，勿视为永久备份）。
