# ADR-0001 · 双入口产品形态

Status: Accepted for MVP design | 2026-10-24

## Context
FrontierLearn 需要持续的学习规划，同时在 arXiv、Hugging Face 和技术网页上实时导学。浏览器插件不能独自承担复杂的知识源配置与学习工作台，单纯 Web 页面又无法提供贴近原文的交互；桌面客户端会增加跨平台支持和维护成本。

## Decision
首发 **Web Workspace + Chrome Side Panel Extension** 双入口，共享一个 Learning Engine 与数据模型。Web 负责学习目标、知识画像、计划、知识来源和同步管理；扩展负责用户明确触发的当前网页理解、选区解释、来源定位和导学会话。未来桌面端可复用 Web UI 组件及同一 API，主要承载本地文件/IDE/实验运行。

## Consequences
- 需要统一登录状态与短期会话凭证，不在扩展 content script 中存储长效 Token。
- 导学 API 需与界面解耦；页面 DOM 提取由扩展适配器承担。
- Web MVP 可以先上线学习画像与计划，但 V0.5 前仍需浏览器扩展形成闭环。
- 暂不为桌面端设置发布日期，不允许为桌面端的假定需求拖慢首个可运行闭环。

## Alternatives rejected
- 仅浏览器扩展：知识库管理和计划工作台空间不足；
- 仅 Web：难以服务真实网页阅读中的高频互动；
- 首发三端：投资大而无法快速验证学习效果。
