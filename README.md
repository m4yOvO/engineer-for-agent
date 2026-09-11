# Engineer for Agent

为 Agent 后端提供按场景裁剪的工程规划、审查与构建约定。支持模型循环、LangGraph/状态图、持久工作流、插件式 Harness、多 Agent、事件驱动和本地嵌入式工具。

核心方法：**项目承诺 → 适用能力 → 已有或拟用机制 → 验证证据**。没有默认要求的接口、表数、编程语言、数据库、队列或部署平台。

## 使用

入口是 [SKILL.md](SKILL.md)。将整个目录交给支持 Agent Skills 的宿主加载，或放入该宿主实际支持的 skills 发现目录；不要只复制入口而丢掉 `references/`。本仓库本身不会自动修改宿主的技能设置。

在支持 `$skill-name` 的宿主中，可以这样使用：

```text
$engineer-for-agent /brainstorming
我想做一个基于 LangGraph 的研究助理，需要长任务恢复、人工确认后发布报告。
请结合用户规模和现有技术栈，规划接口、数据、执行、安全、部署和验收清单。
```

```text
$engineer-for-agent /check
检查当前项目的 Agent 后端工程，只做审查。
重点确认工具超时、图节点重入、多用户数据访问和预算是否有真实保护。
```

```text
$engineer-for-agent /build
在现有项目中实现报告发布节点，沿用已有认证、工作流存储和测试约定。
补齐必要的动作防重、未知结果处理和验证，不更换框架。
```

没有 `$skill` 语法时，可直接要求：“读取这个目录中的 SKILL.md，执行 /check，审查当前项目。”

`/brainstorming`、`/check`、`/build` 是 **Skill 内的模式参数**；本仓库不自动注册三个全局原生 slash command。显式指明 Skill 可避免与宿主已有的同名命令混淆。

| 模式 | 交付 | 边界 |
|---|---|---|
| `/brainstorming` | 工程计划、接口/数据契约、架构选择、实施与验收清单 | 规划不自动实现代码 |
| `/check` | 有代码/配置/测试证据的发现、覆盖矩阵、改进顺序 | 默认只读，不自动修复 |
| `/build` | 授权范围内的实现、必要测试和运行说明 | 不扩大为全库改造或自动发布 |
| `/help` | 用法说明 | 不操作项目 |

没有命令时按任务意图选择模式。构建 Agent 相关代码时可隐式采用工程约定，范围仅限本次改动。用户明确要求检查并修复时，会分 `/check → /build` 两阶段完成。

## 内容导航

- [14 个能力领域](references/capability-map.md)：把适用条件、设计问题和证据连接起来。
- [架构适配](references/architecture-adapters.md)：避免重复实现框架已有能力，覆盖图节点重入、工作流历史、会话分支和多 Agent 委派。
- [接口与数据](references/contracts-and-data.md)、[执行与恢复](references/execution-and-recovery.md)、[安全与资源](references/security-and-resources.md)、[交付与评测](references/delivery-and-evaluation.md)：按需读取的工程参考。
- [公开源码与提炼说明](references/sources.md)：DeepSeek Harness、Codex、Hermes、Pi、LangGraph 的固定版本参考，以及私有学习材料的泛化方法。
- [场景验收集](evals/scenarios.md)：检查模式边界与跨架构适用性。
- [承诺到交付证据](references/evidence-workflow.md)：衔接规划、审查、构建及失败窗口验收。
- [隔离行为验证](evals/behavior-protocol.md)：用模拟项目检查 Skill 的实际输出与代码行为，分别记录静态检查和运行证据；见[本次六项更新与实际结果](evals/validation-2026-09-11-update.md)。

Skill 能帮助形成设计与证据，但不能仅凭文档或静态检查认证生产就绪。具体框架 API、默认重试和持久化模式需要按项目版本核对。
