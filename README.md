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

先读 [SKILL.md](SKILL.md)，用模式确定工作范围，再通过 [工程阶段入口](references/engineering-workflow.md) 找到当前需要的协议。

| 阶段 | 设计、实现与验收 |
|---|---|
| 接口与身份 | [调用合同、受理、错误和身份关联](references/stages/interfaces.md) |
| 数据与表 | [实体、字段、键、索引、事务、迁移和保留](references/stages/data-and-storage.md) |
| 状态机与图 | [转移/路由、等待、取消、原子提交与恢复](references/stages/state-and-lifecycle.md) |
| 队列与执行 | [受理、派工、领取、ACK、重试、租约和积压](references/stages/queue-and-execution.md) |
| 工具调用 | [决策、调用、动作、尝试、结果和上下文回填](references/stages/tool-execution.md) |
| 模型与上下文 | [provider、消息、压缩、记忆与 RAG](references/stages/model-and-context.md) |
| 安全与资源 | [权限、隔离、截止、并发与预算](references/stages/security-and-resources.md) |
| 事件与观测 | [快照、历史、订阅、撤权、Trace 与告警](references/stages/events-and-observability.md) |
| 交付与运行 | [测试、升级、在途兼容、运行手册与评测](references/stages/delivery-and-operations.md) |

横向参考：[14 个能力领域](references/capability-map.md)、[架构适配](references/architecture-adapters.md)、[承诺到交付证据](references/evidence-workflow.md)、[公开源码与来源](references/sources.md)。

阶段内部也按 [逐条适配规则](references/engineering-workflow.md#逐条适配与项目记录) 选择采用、等价替代、合并简化、暂缓或不适用，并补充项目特有要求。规划、审查和构建接续同一份项目适配记录；审查会按当前需求重新核验旧选择。阶段可以合并和迭代，已有平台能力可直接承担合同。队列和状态机有明确协议，但不会强制本地 CLI 引入 Broker，或为已有工作流再造一套状态机。原综合参考页保留旧链接导航，正文集中在阶段协议中。

维护验证：[场景集](evals/scenarios.md)、[隔离行为协议](evals/behavior-protocol.md)、[六项更新记录](evals/validation-2026-09-11-update.md)、[阶段协议与工具恢复验证](evals/validation-2026-09-11-protocols.md)、[逐条适配验证](evals/validation-2026-09-11-adaptation.md)。

Skill 能帮助形成设计与证据，但不能仅凭文档或静态检查认证生产就绪。具体框架 API、默认重试和持久化模式需要按项目版本核对。
