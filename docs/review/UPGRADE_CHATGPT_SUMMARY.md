# 本地试用工程交付总结

## 状态与提交

本轮完成范围是现有工程整理、功能盘点、隔离自动验收及 Mac 本地试用资料；没有开发下一版本。
产品整体验收结论 **PARTIAL**：本地工程路径通过，真实外部连接与真人学习验收仍有缺口。

开始分支 `codex/local-trial`，提交 `bdf9a8f9823916365545dc1387e86bbafe36db0c`，
另有 13 份修改与 11 份新文件。已有认证修复、契约、试用证据全部保留并重新验证。
完整开始快照、Git bundle 和补丁保存在 `/private/tmp/frontier-upgrade-20261111/`。

已建立分支 `feature/upgrade-chatgpt`，从包含全部现有实现的开发 HEAD 创建，保持正常祖先历史。
最终完整 SHA 通过 `git rev-parse feature/upgrade-chatgpt` 或本文件提交历史获取；
本文件随收尾提交版本化，不能把其自身尚未产生的 SHA 伪写进文件。
整合提交和远程实际结果在操作后补记；最终 SHA 也在交付回复给出。

## 基线、清理与能力

基线为 `main@4f7fce219b0284ca596cc5699e7140ee3325c92d`；本地/远程无 Tag、无 Release。
**当前差异主要是从规格基线到 MVP 工程实现，不是两个成熟产品版本之间的升级。**
main 17 个文档，开发已提交差异 267 新增/9 修改，实际能力见
[版本差异与功能报告](VERSION_DIFF_AND_FEATURES.md)。

清理两份初始化截图，共 120,069 bytes；清理可再生缓存/旧浏览器报告，整合重复开发/验收/试用叙述。
保留产品源码、全部迁移/锁文件/契约、安全回归、原始快照及有审计价值的业务证据。
新增 `.local/` 忽略备份，交付可重复运行的仓库链接/敏感模式/原文 SHA 检查脚本。
统计、逐项原因与保留材料见 [清理报告](REPOSITORY_CLEANUP.md)。

现有能力：独立账号，GitHub 只读导入与证据画像，目标/规则计划，Web/MV3 导学与追问，
对话导入，来源边界/可选模型选择题，确认后证据与重规划，Markdown 草稿/下载/审核，
可选 GitHub PR，以及数据导出/删除/撤销。保守规则和 LOW 证据不能宣传成掌握判断。

唯一新增修复为恢复演练脚本读取实际 Alembic head，解决 0010 被旧 0009 常量拒绝；
新增集成回归先红后绿，并实际验证 pg_dump/pg_restore，没有新增产品功能或迁移。

## 验收与本地交付

- 最终后端 217、客户端 26、初始化 Chromium 3、Web E2E 8、真实 MV3 E2E 4、公开网页 11 项通过，均无跳过。
- TS strict、lint、Ruff/format、mypy strict、OpenAPI JSON/YAML/TS 漂移、Web/MV3 构建通过。
- 全新独立 Compose 部署，0010 升级/ORM 一致性、API/Worker 启动与健康检查通过。
- 实际隔离恢复 27 表，23,386 bytes 导出一致，原密码登录及原密钥解密通过。
- 日常 API 79 个 Python 源文件摘要与工作区一致，health/ready 200；Web 5176 已启动。
- 最终插件恢复为 API 18000；个人 Chrome 需使用者手工加载/重新加载。

[完整命令、失败、覆盖与边界](../acceptance/LOCAL_AUTOMATED_ACCEPTANCE.md)
和 [结构化证据](../acceptance/evidence/checks.json) 分别保存，不将 Fake 当作真人或真实服务验收。

本地启动入口：[LOCAL_DEPLOYMENT](../manuals/LOCAL_DEPLOYMENT.md)。
功能操作入口：[USER_GUIDE](../manuals/USER_GUIDE.md)。
两轮试用及反馈：[FIRST_TRIAL](../manuals/FIRST_TRIAL.md)，先 A、再按意愿配置 B/C。

## 未解决的问题

1. 当前 Docker Worker 的 GitHub DNS 含非公网 `2001:2::4`，安全检查拒绝；31 文件真实完整同步未通过。
   没有修改用户网络/VPN、降低 SSRF 或拿 ChatGPT 凭据绕过。公开网页/CLI 元数据成功不能代替应用导入。
2. 真实付费模型调用 0、真人样本 0、真实 GitHub PR 写回 0；App/加密密钥未配置。
3. 画像概念规则、计划语义深度、模型选择题语义质量和真人学习效果仍有限制；T073、T059/CHK020 保持待办。
4. 真实分享兼容性、人工引文抽检、生产 TLS/负载/恢复及宪章草案审阅尚未完成。

## 分支、Tag 与远程实际结果

开始只有 main 和 codex/local-trial（本地/远程同 SHA），没有其他未知分支或独立历史。
main 与全部已有 Tag 不重写，已有 Tag 数量为 0。
按“先验证→普通推送新分支→核对远程包含→删旧分支”的顺序执行，结果在下方补记。
网络/权限失败时保留旧远程，不会先删再推，不使用 force push、squash、rebase 或 reset。

## 新分支提交前复验

在 feature/upgrade-chatgpt 上实际重跑：核心后端 32 passed（43.27s）、客户端 26 项、
lint/TS strict/类型漂移、Ruff/format、OpenAPI、Web/MV3 构建和仓库检查均通过。
32 是全量 217 的子集，不另算独立用例。全部被测源码摘要一致；仅文档/审计结果继续收尾。
Git bundle 校验完整历史通过；main 和原始快照 SHA 不变。新建空白部署项目容器/卷已清理，
专用测试 PG 重建后健康；日常服务与资料卷保留，Web 5176 可打开。
