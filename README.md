# FrontierLearn

FrontierLearn 是 Web 学习工作台与 Chrome 网页导学插件：从已有笔记线索和个人目标出发，
安排学习、对照原文、保存验证证据与笔记草稿，再修订下一次计划。
笔记、阅读、AI 回答和完成任务都不直接等于掌握。

当前交付是可在 Mac 运行的 MVP 开发预览，尚未正式发布。
已实现独立账号、GitHub 只读导入/画像、目标与版本化规则计划、arXiv/HF 导学/追问、
对话导入、短测、Markdown 草稿/下载、经审核的可选 PR 写回，以及数据导出/撤销/删除。
默认使用本地规则，不调用付费模型；真实 AI 与 GitHub App 需要独立配置和授权。

## 快速启动

需要 Node 22、pnpm 10.28.2、Python 3.12/uv、已启动的 Docker Compose 和 Chrome。
从 `feature/upgrade-chatgpt` 仓库根目录运行；已有 `.env.trial` 时保留并核对配置。

```sh
pnpm install --frozen-lockfile
uv sync --frozen --project services/api
if [ ! -e .env.trial ]; then
  cp -n infra/local-trial.env.example .env.trial
fi
docker compose --env-file .env.trial -f infra/docker-compose.yml up -d --build --wait
FRONTIER_API_PROXY=http://127.0.0.1:18000 pnpm --filter @frontier/web dev --host 127.0.0.1 --port 5176
```

打开 <http://127.0.0.1:5176>，注册并下载恢复文件。API/数据库就绪检查：
<http://127.0.0.1:18000/api/v1/ready>。默认 PG 端口 55433。
另开终端构建插件，在 `chrome://extensions` 加载 `apps/extension/.output/chrome-mv3`：

```sh
FRONTIER_EXTENSION_API_ORIGIN=http://127.0.0.1:18000 pnpm --filter @frontier/extension build
```

Web 按 Ctrl+C 关闭，保留数据停止后端：

```sh
docker compose --env-file .env.trial -f infra/docker-compose.yml stop
```

## 使用与工程入口

- [Mac 部署、备份与故障排查](docs/manuals/LOCAL_DEPLOYMENT.md)
- [按页面使用全部现有功能](docs/manuals/USER_GUIDE.md)
- [Self-Attention → GQA 两轮首次试用及反馈](docs/manuals/FIRST_TRIAL.md)
- [本轮自动化验收与真实服务边界](docs/acceptance/LOCAL_AUTOMATED_ACCEPTANCE.md)
- [基线差异和功能盘点](docs/review/VERSION_DIFF_AND_FEATURES.md)
- [仓库清理记录](docs/review/REPOSITORY_CLEANUP.md) · [交付总结](docs/review/UPGRADE_CHATGPT_SUMMARY.md)
- [真实模型与 GitHub App 配置](docs/production-integrations.md) · [迁移/回滚](services/api/app/persistence/migrations/README.md)
- [当前 Spec](specs/001-personalized-learning-loop/spec.md) · [任务清单](specs/001-personalized-learning-loop/tasks.md) · [ADR](docs/adr/0001-product-shape.md)

## 当前限制

画像提取与计划主要是保守规则，不能自动可靠合并中英概念或生成完整语义课程。
无模型时导学仅给阅读方法；来源边界题不是概念理解证明，模型选择题也只产生低强度证据。
大仓库需选小目录，公开 GitHub 受网络/DNS/限额影响；PDF、图表与受限分享页需手工回退。
真实模型质量、真实 App/PR、人工引用核对、真人两轮学习和生产运维仍待验收。

本轮不开发下一版本。Notion/Hexo/桌面执行等仅属 [未来路线](docs/roadmap.md)。
工程约束见 [AGENTS.md](AGENTS.md)，完整历史验收材料保留在 [证据索引](docs/evidence/mvp-acceptance.md)。
