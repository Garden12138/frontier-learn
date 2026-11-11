# 本地试用入口

当前 Mac 部署命令统一到 [本地部署运行手册](manuals/LOCAL_DEPLOYMENT.md)。

- 第一次实际使用：[两轮试用与反馈模板](manuals/FIRST_TRIAL.md)，默认不使用付费模型。
- 按页面查操作：[产品使用手册](manuals/USER_GUIDE.md)。
- 自动检查的真实结果与边界：[本轮验收报告](acceptance/LOCAL_AUTOMATED_ACCEPTANCE.md)。
- 真实模型、GitHub App 与写回配置：[接入说明](production-integrations.md)。

日常配置为 Web `127.0.0.1:5176`、API `127.0.0.1:18000`、PG `127.0.0.1:55433`；
复用 `.env.trial`，勿覆盖既有配置。停止服务保留数据卷，不运行 `down -v`。
真实服务/真人验收仍待完成；历史观察见 [V0.1.1 记录](evidence/v0.1.1-acceptance.md)。
