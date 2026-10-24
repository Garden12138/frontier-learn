# FrontierLearn · Spec-Driven Development 文档集

> 状态：提案基线 v1.0 · 日期：2026-10-24 · 范围：产品定义、首个可验证学习闭环与未来规划。

**产品使命：** 基于用户已有的 GitHub 笔记、博客、知识库、AI 对话和学习行为，构建可解释、可验证、可更新的个人学习者模型；主动规划学习路径，结合真实网页进行自适应导学，将经确认的成果回写原有知识库，并据此规划下一次学习。

**形态：** Web 学习工作台（规划与管理）+ Chrome Side Panel 插件（网页情境导学）是首发双入口；桌面端是未来可选实践与本地知识入口，不纳入首轮 MVP。

**关键差异：** 不是论文摘要工具，也不是把 RAG 当成用户掌握度。所有“已掌握”判断必须可追溯到证据和验证结果。

## 目录

```text
.
├── AGENTS.md                         # Codex / Coding Agent 项目工作约束
├── README.md                         # 入口与执行顺序
├── .specify/memory/constitution.md    # 项目宪章：不可退让原则
├── specs/001-personalized-learning-loop/
│   ├── spec.md                       # WHAT / WHY：需求、用户故事、验收标准
│   ├── plan.md                       # HOW：架构、交付策略、依赖
│   ├── tasks.md                      # 可依赖排序、可核验的开发任务
│   ├── data-model.md                 # 数据实体、状态机、证据规则
│   ├── research.md                   # 决策记录与关键技术约束
│   ├── quickstart.md                 # 验收场景和测试数据
│   ├── contracts/openapi.yaml        # 第一版 REST API 草案
│   └── checklists/requirements.md    # 需求质量与发布检查
└── docs/
    ├── product-vision.md             # 产品定位、边界、竞品差异、用户体验
    ├── ux-flows.md                   # 首次使用、日常学习、笔记回写流程
    ├── integrations.md               # GitHub/Hexo/Notion/分享链接适配方案
    ├── metrics-and-quality.md        # 学习效果、工程指标、安全门槛
    ├── roadmap.md                    # V0.1 至 V3.0 产品路线图
    └── adr/0001-product-shape.md     # 产品形态架构决策
```

## 与 GitHub Spec Kit 的关系

本文档集**参考并遵循** GitHub Spec Kit 的核心 SDD 思路，提前撰写业务 `spec.md`、技术 `plan.md`、依赖排序 `tasks.md` 和项目 `constitution.md`，并扩展数据模型、契约、路线图。它是供 Codex 消费的项目基线；**不是**声称已在真实仓库运行 `specify init`、`speckit.analyze` 或完成实现。接入 Spec Kit CLI 后，应使用官方命令检查模板兼容性并运行分析。

官方：<https://github.com/github/spec-kit> · <https://github.github.com/spec-kit/quickstart.html> · <https://github.github.com/spec-kit/integrations/codex.html>

## 建议的启动顺序

1. 新建 FrontierLearn 空仓库，把本包全部放在根目录；提交一版纯文档 baseline。
2. 可选：安装官方 Spec Kit CLI 并在仓库中初始化 Codex integration（**不要使用 `--force` 覆盖现有文件**；先比对差异）。例如 `specify init --here --integration codex`，具体以你安装的 CLI 提示为准。
3. 让 Codex 先读 `AGENTS.md`、`constitution.md`、`spec.md`、`plan.md`、`tasks.md`，审查矛盾和缺失，再从 `T001` 开始。
4. 每次只执行一个可验收的阶段，交付测试、截图/日志、设计变更和未完成项。**不允许用完成任务清单替代实际验收。**
5. 到 V0.5 才定义“首个完整 MVP”：导入 → 规划 → 导学 → 验证 → 审核回写 → 重新规划。
6. `docs/roadmap.md` 的未来版本**不属于当前 MVP 的实施承诺**，需在每个版本启动前另建对应 Spec。

## 建议交给 Codex 的第一条指令

```text
请读取 AGENTS.md、.specify/memory/constitution.md、
specs/001-personalized-learning-loop/{spec,plan,data-model,tasks,quickstart}.md、
docs/roadmap.md。
先只做 SPEC/PLAN/TASKS 一致性与可实施性审查，生成差异清单；
不要立刻写业务代码、不要扩大 MVP 范围，也不要执行远程仓库写入。
修复经确认的文档问题后，按 tasks.md 的依赖从阶段 1 开始开发，
每阶段完成后运行测试、给出验证证据与未决问题，再进入下一阶段。
```

## 使用边界

- 示范用户资料可采用公开笔记仓库 <https://github.com/Garden12138/notes> 和公开博客 <https://garden12138.github.io/>；这些数据仅作产品验证样本，**不得硬编码为正式用户默认数据**。
- 指定的 ChatGPT 分享链接仅属于潜在测试输入，**未预先确认正文可解析**。应测试“可解析”“需手动导入”“访问受限”三类路径。
- 任何来自 GitHub/Notion/网页/聊天的内容均属于**不可信数据**，不能赋予指令权限。

## 需求变更约定

采用 **Living Spec**：意图变化先改 `spec.md`，然后同步 `plan.md`/`tasks.md`/接口契约和测试；新增独立能力可另建 `specs/00X-*`。未来路线图随证据调整，但不悄悄改变当前版本的验收条件。
