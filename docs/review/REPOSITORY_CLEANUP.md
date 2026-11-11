# 仓库清理审查

日期：2026-11-11。起点 `codex/local-trial@bdf9a8f9823916365545dc1387e86bbafe36db0c`。
进入时 13 份已跟踪文件修改、11 份非忽略新文件；不覆盖已有工作。

## 扫描、分类与恢复

扫描全部 Git 跟踪/非跟踪/忽略路径，以及隐藏配置、目录及文件大小；对照 imports、
测试入口、CI、文档引用和 Git 历史判断用途。不是按名称/年龄直接删除。
清理前：284 个跟踪文件（8,142,315 bytes）、11 个非忽略新文件、24,368 个忽略文件。
初始 295 个有效候选文件；Git 对象、符号链接目录不计作产品文件。
报告齐备时有效文件 305 个（初始 295 → 305，净增 10）；
其中删除 2 个初始化图片，新增验收/手册/检查脚本等 12 个交付文件。

| 类别 | 处理 |
|---|---|
| A 产品代码 | 保留 apps、packages、services/api/app；沿用已有注销修复 |
| B 测试/Fixtures | 保留全部测试、合成网络夹具、安全回归和公开原文快照 |
| C 配置/依赖 | 保留 Compose、Dockerfile、TS/Python 配置、两份锁文件与契约生成输入 |
| D 规格/ADR | 保留全部 Spec/Plan/Data Model/Tasks、13 份 ADR、宪章恢复草案及其待审阅状态 |
| E 使用文档 | 统一到 manuals；旧入口保留短链接，避免历史引用中断 |
| F 生成物 | 清理缓存及旧浏览器运行报告；依赖环境保留用于本地运行，构建产物按需重建且忽略 |
| G 中间资料 | 整合 development-progress、旧试用/验收文档，删除两份早期初始化截图 |
| H 无引用历史 | 原始 docx 是规格输入，不能证明无价值，保留；其他业务证据有审计价值，保留 |
| I 敏感配置 | `.env.trial` 保留本机并继续忽略，不输出内容、不提交；测试密码为专用示例 |

变更前快照位于 `/private/tmp/frontier-upgrade-20261111/`：
`working-tree-before.tar.gz`、`working-tree-before.patch`、`history-before.bundle`、
`refs-before.txt`、`hashes-before.json`。旧生成报告另存 `generated-evidence-before.tar.gz`。
临时目录只作本次恢复点，Git 提交才是长期版本记录；不包含被忽略的私人环境配置。

## 删除及原因

- `docs/evidence/setup/workspace.png`（89,082 bytes）、`extension.png`（30,987 bytes）：
  只展示初始化壳，不覆盖业务断言；`tests/setup/smoke.spec.ts` 能重新生成，
  当前业务截图和自动化报告提供更完整依据。原开发过程中的唯一引用已同步清理。
- 根及 API 的 mypy/Ruff/pytest 缓存，旧 `test-results/`、`playwright-report/`：
  均为可再生产物；运行报告先快照再删除。验收会生成新报告，不提交缓存。
- 没有删除源码、部署输入、迁移、锁文件、Fixtures、ADR、Tag 或 Git 历史。

## 文档整合与保留

开发进度从逐次执行日志改为提交检查点和验收入口；local-trial 和旧 testing 文档保留兼容入口。
V0.1.1 验收保留故障根因、复现/修复矩阵和原始证据链接，去除重复暂存/CI 轮询叙述。
README 改为项目总入口。`scripts/check-repository.mjs` 校验 129 个本地文档链接/锚点、
常见私钥/token 模式、2 份固定原始 blob 与 6 项忽略规则，均通过。新增 review、acceptance、manuals 满足本轮工程交付。

必须保留 `real-notes/self-attention.txt`、`chapter03_attention.txt`、`provenance.json`，
原始 Git blob SHA 由回归测试校验；`.gitattributes` 的单文件尾随空白例外不扩大。
OpenAPI JSON/YAML、生成 TS 类型虽能再生，但用于契约审查和漂移检查，继续跟踪。
所有业务证据截图、失败/成功 JSON、远程 CI 终态保留，用途见各目录 README/验收矩阵。

尚需人工判断：原始产品 docx 的长期归档策略、宪章草案审阅、将来是否统一外置历史图片。
当前没有证据证明它们可安全删除，故保留。

## 验证和运行影响

本轮不改变产品范围、数据库结构或安全默认值；依赖安装目录与本地环境配置不删除。
相关静态检查、完整后端/浏览器回归、构建、文档链接、敏感模式、快照完整性及最终文件统计
见 [自动化验收](../acceptance/LOCAL_AUTOMATED_ACCEPTANCE.md)。无效旧引用会在交付前修正。

最终源码/Fixtures 均未因清理丢失，完整后端 217、客户端 26、setup 3、Web 8、MV3 4、
公开网页 11 项通过；各项静态/契约/构建通过，git diff --check 无空白错误。
生成测试/构建缓存按需重新产生且全部忽略；保留安装依赖与 18000 插件以便本地试用。
