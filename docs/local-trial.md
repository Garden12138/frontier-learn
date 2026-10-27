# 本地试用

本指南启动 Web 工作台、PostgreSQL、API 和 Worker，并构建 Chrome 网页导学插件。
默认使用本地规则导学，无须 GitHub 账号或模型密钥。真实 AI 解释、私有仓库连接及 PR 写回
需要另行配置，见 [外部服务接入](production-integrations.md)。

## 启动服务

准备 Node 22、pnpm 10.28.2 和已启动的 Docker Desktop/OrbStack，在仓库根目录运行：

```sh
pnpm install --frozen-lockfile
FRONTIER_DB_PORT=55433 FRONTIER_API_PORT=18000 docker compose -f infra/docker-compose.yml up -d --build --wait
FRONTIER_API_PROXY=http://127.0.0.1:18000 pnpm dev
```

保持最后一个命令运行，打开 <http://127.0.0.1:5173/>。数据库使用命名数据卷，重新启动后
保留学习数据。端口 5173、55433 和 18000 需要可用。健康检查：

- <http://127.0.0.1:18000/api/v1/health>：API 正常。
- <http://127.0.0.1:18000/api/v1/ready>：数据库就绪。
- <http://127.0.0.1:5173/api/v1/ready>：Web 已正确代理到后端。

本地后端在 Docker 内安装 Python 依赖；只有直接运行后端测试时才需要本机 Python 3.12 和 uv。
默认关闭无密码 Mock 身份、云模型和外部写回。不要为试用开启 Mock。

## 在工作台试用

1. 注册独立账号，密码至少 12 位，下载并妥善保存恢复码后继续。
2. 进入“学习目标”，例如创建“理解 Transformer”，设置每天 20 分钟；也可以选择其他主题。
3. 进入“今日学习”，生成计划，体验采纳、调整、暂停与历史修订。
4. 在“导入对话”粘贴一段学习对话，预览范围后确认保存，再选择将候选问题加入计划。
5. 使用下述插件保存导学会话后，可体验来源边界短测、确认低强度证据、草稿审核和笔记下载。

当前短测只检查原文与推断的边界，不证明主题理解或掌握。默认导学是本地规则阅读方法，
真实模型解释需要服务端配置和用户全局、逐次授权。完整学习记录可在“设置与数据”导出。

## 安装网页导学插件

另开一个终端，在仓库根目录运行：

```sh
FRONTIER_EXTENSION_API_ORIGIN=http://127.0.0.1:18000 pnpm --filter @frontier/extension build
```

1. Chrome 打开 `chrome://extensions`，开启“开发者模式”。
2. 点击“加载已解压的扩展程序”，选择仓库中的 `apps/extension/.output/chrome-mv3`。
3. 打开 arXiv 摘要/HTML 页或 Hugging Face 模型主页，再点击扩展工具栏图标。
4. 在侧栏登录与 Web 相同的账号，点击“分析当前页”。
5. 检查预览范围、选择目标/任务并确认后，保存导学会话；可继续选区追问、回到原文和短测。

换域后需重新点击工具栏授权。PDF、登录墙和不支持的网页可以手工粘贴，预览不会自动上传。
Web 的“导学会话”可继续查看同一账号保存的材料。重新构建后，在扩展管理页点击“重新加载”。
插件服务地址在构建时固定；后端换端口时，需以对应 origin 重建并重新加载插件。

## 停止与再次启动

Web 终端按 `Ctrl+C`，然后在仓库根目录停止后端：

```sh
docker compose -f infra/docker-compose.yml stop
```

再次启动使用上方相同命令，数据卷保留。若显示服务无法连接，先检查 Docker 和三个就绪
链接，再确认 Web 启动命令设置了 `FRONTIER_API_PROXY=http://127.0.0.1:18000`。
停止服务不需要删除数据卷。

试用范围和未完成发布项见 [验收记录](evidence/mvp-acceptance.md)。
