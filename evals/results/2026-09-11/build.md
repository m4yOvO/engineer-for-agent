# /build 交付报告：持久人工等待模块

已完成 `evals/fixtures/build_wait/README.md` 要求的实现与本地验证。修改限于该副本中的 `service.py`、`test_service.py`、`README.md`，另按要求写入本报告。没有访问其他案例、先前报告或 `evals/`，没有网络、账户、依赖安装、Git 或子代理。

## 项目事实与范围

这是单用户本地 Python 同步函数模块。实际入口是 `service.open_db/create/pause/resume/cancel`，SQLite 拥有任务、命令、派工和历史事实；没有 HTTP 服务、模型、外部动作或现成 worker。本次适用的工程面是入口合同、持久状态、人工等待、原子受理、并发裁决和恢复验证。沿用原数据库的四张表及所有公开函数签名。

读取并应用了指定 `SKILL.md` 的 `/build` 流程，以及 build、capability-map、contracts-and-data、execution-and-recovery、evidence-workflow、delivery-and-evaluation 参考文件；没有扩展为整库改造。

## 实现与调用链证据

| 承诺 | 实现位置 | 实际验证 |
|---|---|---|
| 暂停不能留下半完成等待现场 | `service.py:73` 的 `pause` 通过 `service.py:32` 的 `_transaction` 持有 SQLite `BEGIN IMMEDIATE` 事务；active 条件判断、状态、等待 ID、快照和历史一起提交 | 注入保存异常；历史插入失败；子进程在等待状态更新后直接 `os._exit(23)`；重开后均核对完整回滚且可再次暂停 |
| 重复继续返回首次结果且只派工一次 | `service.py:90` 的 `resume` 在事务内先查询 `commands`；规范化 JSON 后匹配 task/wait/input；首次结果、命令、ready、job 和历史一起提交 | 重开后重放结果；调用者修改返回对象不影响持久结果；对象键顺序变化可重放；8 个独立连接同时重复继续均返回同一结果，仅有一个命令、一个 job 和一次 resume 历史 |
| 改内容复用命令 ID 必须拒绝 | 同一 `commands.message_id` 主键保留首次命令，比较任务、等待点与完整 JSON 输入 | 修改 input、bool/number、wait_id、task_id 均拒绝；不同任务竞争同一 message_id 只有一方受理，另一任务保持 waiting |
| 错误任务或等待 ID 无副作用 | `resume` 的条件更新同时匹配 task/state/wait_id；失败事务回滚 | 未知任务、错误等待 ID、另一个任务的等待点均不改变任一表，也不占用 message_id；随后正确请求可以接受 |
| 继续与取消只接受一个且不抹除历史 | `service.py:120` 的 `cancel` 使用同一事务入口；waiting 条件更新与历史一起提交 | 30 轮独立连接并发竞争，每轮一方成功、一方 ValueError；重开后状态、历史和命令/job 数量都与胜者一致；取消保留快照及等待 ID |
| 受理必须可靠留下可领取工作 | `resume` 将 ready、commands、jobs、history 放在一个 SQLite 事务；job 可关联到任务快照与已接受输入 | 插入 job 或最后的 history 时触发 SQLite 错误，全部事实回滚且可用原命令重试；成功并重开后查询 job 联接获得完整快照、输入和首次结果 |
| 实际入口使用本次实现 | `test_service.py` 直接 `import service` 并断言 `service.__file__` 指向该副本；检查所有公开签名；退出故障子进程也从此目录导入入口 | 签名断言和真实 SQLite 入口测试全部通过；没有 mock 替换核心实现 |

同一连接存在未提交的调用者事务时，写入口明确拒绝，并保留调用者事务，不擅自提交或回滚。JSON 参数拒绝非有限数字、非字符串对象键及非 JSON 类型。命令 ID 的幂等范围是整个数据库，记录不自动过期；对象键顺序不影响身份，数组顺序和数值编码保留，`1` 与 `1.0` 视为不同输入。这些调用约定已写入 README。

## 实际运行结果

工作目录：`evals/results/2026-09-11/build_wait`

运行命令：`python3 -m unittest -v`

运行环境：Python 3.12.6，SQLite 3.45.3。所有数据库均由 `tempfile.TemporaryDirectory` 创建并清理。独立连接竞争由标准库线程池驱动，退出恢复场景使用标准库子进程。

实际结果：**20 个测试通过，0 失败，测试报告耗时 0.200 秒，退出码 0**。其中一个测试包含 30 轮继续/取消竞争；还包含 8 路相同命令并发、两个不同命令并发，以及跨任务复用命令 ID 的竞争。

证据级别为本地真实 SQLite 隔离集成测试与进程退出恢复测试，不是生产观测，也没有声称真实 worker 执行验收。

## 限制与交接

- 未修改表结构，也不自动修复旧版本已经生成的半完成等待、重复 job 或缺少命令记录的历史。这类数据缺少可靠恢复依据，应先检查现场；新旧实现不能混写。
- 保证已接受继续操作对应一个持久 job；模块没有 worker 领取、执行或确认协议，未将可靠受理等同于业务执行完成。
- 并发保证针对同一本地 SQLite 数据库、每个调用者独立连接且通过这些公开入口写入。保留原 5 秒数据库锁等待超时；长时间外部占锁可能导致数据库异常，异常不会被当作受理成功。
- 已验证明确异常与进程直接退出，未验证断电、磁盘损坏、磁盘满、备份恢复、网络文件系统或多机部署。没有新增这些承诺。

交付代码、测试与 README 均已完成，不需要真实外部操作或额外授权。
