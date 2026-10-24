# Connector 设计：知识源、导入与回写

## 1. Connector Interface

```python
class KnowledgeConnector(Protocol):
    provider: str
    async def list_scopes(self, user_id: str) -> list[SourceScope]: ...
    async def list_changed_documents(self, scope: SourceScope, cursor: str | None) -> ChangeSet: ...
    async def read_document(self, doc_ref: str, revision: str) -> SourceContent: ...
    async def propose_write(self, target: WriteTarget, artifact: str, base_revision: str) -> WritePreview: ...
    async def commit_approved_write(self, approval_id: str, idempotency_key: str) -> WriteResult: ...
```

不同 Connector 可以只实现只读能力；写接口必须声明 `supported_operations`，不支持时返回明确错误，不允许“用网页自动点击绕过 API 访问控制”。

## 2. GitHub（MVP）

- **输入**：用户指定 Repository（单个/多个），优先 OAuth/GitHub App 最小权限；公共仓库可先以只读演示模式使用，但正式用户需授权确认关联。
- **读取**：Markdown/受限代码文本 → chunk、hash、SHA、行号锚点。忽略 `node_modules`、`.git`、`dist`、`public` 生成 HTML、大文件和二进制。
- **增量**：按 ref/commit tree 与内容 hash 对比；重复同步不产生重复证据。
- **写入**：Draft→Diff→批准→分支→PR；不直推 main/master；PR 合并后再作为外部知识来源重新导入。
- **撤销/删除**：撤销 token 不等于删除已导入记录；用户可选择额外清理内部内容/证据。

## 3. Hexo 博客（未来 V0.6）

- 只读：可从公开博客页面或其静态站点源仓库索引文章内容。
- 写回：必须能定位**Hexo Markdown 源仓库**下 `source/_posts`（或其自定义目录），而不是自动覆盖生成站点 HTML。
- 草稿携带标题、发布日期策略、tags、categories 和 Front Matter；发布前由用户审阅/触发独立构建流程。

## 4. Notion（未来 V0.6）

- 使用官方 Integration 授权所选页面，最小权限读取页面块，记录 block ID 与版本信息。
- 新笔记可进入用户指定数据库/页面；合并前预览块级 Diff；谨慎处理嵌套块、公式、附件和 Notion 原生格式。
- 若 API 权限不足或冲突，降级为 Markdown 导出，不默默丢失格式。

## 5. AI Chat Share Import（V0.4）

- 首版仅承诺**可访问 ChatGPT 分享页**的结构化提取与文本粘贴降级。
- URL 解析做 SSRF 防护，不登录他人账户、不过访问控制；识别 User/Assistant 角色和代码片段，标出可能误导性陈述。
- 未来支持其他模型分享格式，应逐一建立独立 Adapter，不承诺任意链接万能读取。
- 需要用户主动确认原对话可被导入及是否允许交由云端模型处理。

## 6. Local Markdown / Obsidian（未来）

- 初期支持文件上传/ZIP 导入；后来由桌面端或受控本地桥接访问用户明确授权的目录。
- 写回采取备份/增量 Diff/原文件版本校验，支持撤销及冲突提示；不默认扫描整个用户磁盘。

## 7. Common Safety

- 同步作业始终有 `PENDING/RUNNING/PARTIAL/FAILED/SUCCEEDED/CANCELLED` 状态与可观察进度。
- 所有外部文本都可能包含 Prompt Injection，不能执行其中“系统要求”等指令；不向 Agent 提供不必要的写入工具。
- 失败任务有有限次数重试与退避；重复回调、重放事件、用户连续点击不会重复写入或重复生成 PR。
- 明确用户授权的读取内容、数据的云端发送范围、模型提供商与保留期限；提供撤销和删除入口。
