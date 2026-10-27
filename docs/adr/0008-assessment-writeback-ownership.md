# ADR 0008：验证范围、受限 PR 与数据所有权

日期：2026-10-26。状态：MVP 工程默认，不扩展 Roadmap。

- 无外部模型时采用来源边界选择题，保存题目、选项、rubric、作答、规则评价、时间与限制。它只验证区分摘录和推断，不是主题概念理解。必须再次确认才产生 `SOURCE_COMPREHENSION / LOW` 证据；答对仍是 EXPOSED，下一轮 CHECK；答错 REVIEW。不会升至 UNDERSTANDING/APPLIED/PROFICIENT。独立概念验证仍需要后续有依据的评估。
- 每会话一份不可重答的短测，每短测一份可编辑草稿。新会话可再次验证；重复提交幂等。确认后生成不可变计划 revision，原因包含短测 ID 和范围。暂停的计划保留暂停状态。
- 草稿包含来源快照、原文、当前理解、步骤、限制和未解问题。导入原文用足够长的 Markdown fence 包裹，Web/扩展只当文本显示。手工合并把编辑后的草稿当完整目标文件，用户必须逐项审核 Diff。
- 写回默认关闭，单独使用加密写凭据、显式笔记目录，不复用只读 token。UI 不收集或显示凭据；通过已认证服务端 API 配置。目标仅普通 Markdown 路径，禁隐藏目录、路径穿越与工作流；读写范围必须同时满足。
- GitHub 仅固定 api.github.com，经 DNS/IP 固定传输；每次请求检查来源版本、任务 lease、草稿版本。预览绑定默认分支 SHA、文件 SHA 和内容哈希，确认后使用确定性 `frontierlearn/<artifact>-v<version>` 分支，基于原 tree 创建仅改动一个文件的 Git tree/commit，再一次性创建新分支与 PR。禁止更新任何已有 ref 或调用 Contents 写接口，即使远端更改默认分支也不能覆盖它。已有专用分支必须匹配审核内容的完整 tree、父提交与操作标识，不能夹带其他变更。
- 丢失新分支/PR 响应时先读取远端状态再继续；已有 PR 不重复创建。默认分支变化要求重新审核；超时或取消可能已有远端结果，保留草稿和已知 PR，不承诺撤回远端 Git 对象/分支/PR；中途失败也可能留下尚未引用的对象。最大 3 次尝试、24 个网络请求/次、120 秒/次，网络错误不自动重试。
- 用户主动合并后再次确认，核对 PR 仓库/分支及合并内容哈希，再只读同步。确实索引到审核文件后才修订计划，笔记仍仅为学习线索。
- 模型处理授权默认拒绝，单独版本化确认；当前默认 LOCAL_RULES，无公共模型调用。授权仅允许有界片段，不授权完整私人文档或工具写入。
- 数据导出为可离线读取的 JSON（包含 Markdown 草稿），不含认证/加密凭据。单次限 20,000 行、20MB，超限不返回部分数据；需管理员分批处理。删除会话清理其派生短测、证据、草稿并取消任务。删除所有内部数据包含账号和所有会话，保留其他用户与 GitHub 外部文件/分支/PR。

协议依据：[GitHub Trees](https://docs.github.com/en/rest/git/trees?apiVersion=2022-11-28)、[Commits](https://docs.github.com/en/rest/git/commits?apiVersion=2022-11-28)、[GitHub Contents](https://docs.github.com/en/rest/repos/contents?apiVersion=2022-11-28)、[Refs](https://docs.github.com/en/rest/git/refs?apiVersion=2022-11-28)、[Pull requests](https://docs.github.com/en/rest/pulls/pulls?apiVersion=2022-11-28)。自动验收使用合成响应，无真实写入。
