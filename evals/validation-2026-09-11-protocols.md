# 阶段协议整理与工具恢复验证

日期：2026-09-11。基于提交 `7e112ea1d6f19630d0374496ff4233d3ef48ee00`。本记录区分本次结果与[此前六项更新](validation-2026-09-11-update.md)，不会把旧版本测试当成新指令的行为证明。

## 改动与知识迁移

入口按“模式 → 当前工程阶段”加载。[工程阶段入口](../references/engineering-workflow.md) 连接九份协议，每份给出进入条件、设计/实现合同、应整理的产物和验收证据。阶段可合并、迭代及裁剪，不增加命令、不改变已有授权边界。

| 协议 | 本次具体整理 |
|---|---|
| [接口与身份](../references/stages/interfaces.md) | 调用者、受理/完成、身份映射、重复/冲突、错误与查询 |
| [数据与存储](../references/stages/data-and-storage.md) | 事实/关系 → 字段 → 键/约束 → 查询/索引 → 事务 → 迁移/保留；文件、对象、平台历史均可采用 |
| [状态与生命周期](../references/stages/state-and-lifecycle.md) | 状态/图位置、事件、可信操作者、守卫、共同提交事实、下一步、确认/资源与失败；含恢复矩阵 |
| [队列与执行权](../references/stages/queue-and-execution.md) | 受理、发布、领取、处理、ACK、重试/死信、停机/接管、容量与积压；优先复用平台职责 |
| [工具调用记录与恢复](../references/stages/tool-execution.md) | 决策、invocation、operation、attempt、结果、消费关联；六个提交边界、多工具部分成功、回填、防重和未知核实 |
| [模型与上下文](../references/stages/model-and-context.md) | 模型协议、完整/部分响应、消息投影、压缩、记忆和检索 |
| [安全与资源](../references/stages/security-and-resources.md) | 当前权限、网络/文件/凭据隔离、资源清理、时间与成本 |
| [事件与可观测](../references/stages/events-and-observability.md) | 结果/历史/快照、游标/水位、连接和撤权、背压、Trace 与告警 |
| [交付与运行](../references/stages/delivery-and-operations.md) | 验证、部署、版本、在途任务、手册、灾备、评测与改进 |

队列与状态机原本已包含，本次从综合参考中显式分出。四份旧综合文件保留原章节锚点导航，正文迁入阶段协议；架构适配、公开来源与证据工作流保持原内容。按旧正文逐项核对迁移，数据字段/状态部分改写为操作清单，恢复、时间、对账、事件和交付约定保留；核对中补回多主体隔离与对象引用两段，避免重组丢失已有内容。

SKILL.md、三个模式、能力地图和 README 直接指向阶段协议。没有默认表数量、统一状态枚举、强制 Broker、统一模型循环或额外建库要求。

## 独立评估与实际结果

两个独立执行者完成三个合成场景：S01/S02 共用一个规划执行者，T01 由另一个构建执行者完成。执行者获得 Skill、对应项目材料与请求，未提供作者验收器、评分标准或预期答案，不继承作者推导上下文。材料只用本地标准库和模拟服务。

| 场景 | 人工检查实际输出后的判定 |
|---|---|
| S01 本地 CLI 规划 | 通过本轮范围：同步调用、内存进度、文件原子交付与有界资源；未强建队列、数据库或跨进程恢复 |
| S02 托管工作流规划 | 通过本轮范围：具体给出逻辑数据/约束/查询/事务、转移与命令表、队列责任和工具恢复；复用平台调度/历史/版本路由，省略不存在的模型决策层，部署和下游期限标为未知 |
| T01 工具恢复构建 | 通过已测范围：实际入口持久接受决策、逐工具保存结果、核实未知、幂等回填消息并保存最终文本；模型/工具计数及关联可核验 |

完整输出：[两份规划](results/2026-09-11-protocols/stage-planning.md)、[构建报告](results/2026-09-11-protocols/tool-build.md)、[实现及恢复合同](results/2026-09-11-protocols/tool_recovery/RECOVERY.md)。规划中的验收均为待执行，不能计成业务测试通过。

工具构建执行者的 **14 项测试全部通过**，包含 11 次实际进程直接退出及 7 个异常钩子位置；覆盖结果事务失败、外部已生效后退出、部分完成、参数冲突和消息关联。首次自测一项日志计数预期错误，因为模拟器拒绝事务会回滚请求日志；修正该预期并检查引擎的持久拒绝事实，未修改模拟器，过程记录在构建报告中。

维护者另行编写、未提供给执行者的 [验收器](assess_tool_recovery.py) **10/10 通过**，包含保存决策、部分成功后进程退出、结果/消息保存后恢复、查询不可用不重发、同操作新 call ID、内容冲突和事务不跨外部工具调用。与执行者测试有覆盖重叠，不作为 24 个独立保证。

发布目录内重跑仍为 14/14、10/10：[执行者测试日志](results/2026-09-11-protocols/tool-executor-tests.txt)、[独立验收日志](results/2026-09-11-protocols/tool-independent-tests.txt)。[原始不完善夹具](fixtures/tool_recovery/README.md) 负向对照为 10 项中 8 失败、2 通过，证明验收器能区分这些缺陷；[负向结果](results/2026-09-11-protocols/tool-baseline-tests.txt) 不算 Skill 构建失败。

## 版本和产物完整性

- 初始指令快照见 [initial manifest](results/2026-09-11-protocols/instruction-manifest-initial.json)。评估开始后仅数据协议补回两段已有知识，通知两个执行者重读；两份报告均确认采用最终文件，工具协议未再改动。
- 最终 [instruction manifest](results/2026-09-11-protocols/instruction-manifest.json) 覆盖 SKILL.md、agents/openai.yaml 和全部 references。按路径排序的紧凑 JSON SHA256 为 `b2a3f4f2758f1a2995318bc2ce76a7634b2c58e3c7672af2aeea98a49ceb134a`。最终指令与该快照一致。
- 隔离规划材料、构建 README 与 fakes.py 摘要不变；只有 engine.py、新测试、恢复说明及项目外报告有授权改动。原输入摘要见 [execution manifest](results/2026-09-11-protocols/fixture-execution-manifest.json)。
- 发布时替换报告/日志中的临时路径并统一末尾换行与行尾空白，未改构建算法、测试断言或模拟器语义。[发布夹具摘要](results/2026-09-11-protocols/fixture-manifest.json) 与执行输入摘要分开保留；负向对照和发布后的正向检查已重跑。
- 元数据、Markdown 本地引用/锚点、围栏、Python 语法、公开内容和冻结摘要检查通过；没有私有课件链接、raw、截图、真实账户信息或生成的数据库/字节码。原有历史验证产物未修改。

## 复现与边界

在仓库根目录运行：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B evals/assess_tool_recovery.py evals/results/2026-09-11-protocols/tool_recovery
```

在 `evals/results/2026-09-11-protocols/tool_recovery` 目录运行 `python3 -B -m unittest -v test_engine.py` 可复现执行者测试。两者执行可信模拟代码，数据库在临时目录，无真实模型、网络或业务服务。隔离目录不等于经过验证的操作系统安全沙箱。

构建案例上层已保证单执行者，未证明集群执行权、真实队列/引擎、真实防重期限、远端查询一致性、断电或灾备。模型 finish 已完成但文本尚未落盘时仍可能再次生成，测试和记录明确保留该窗口；已完成工具不会因此重做。旧数据库缺少恢复依据时明确停止，没有伪造历史迁移。

本次证明阶段路由在这两个规划项目与一个本地构建中的表现；没有为全部九个阶段分别实现生产系统，也没有把 27 项文字场景集计为独立行为测试。
