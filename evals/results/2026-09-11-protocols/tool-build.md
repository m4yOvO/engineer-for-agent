# /build：工具恢复模块交付

已完成当前项目 README 的本地恢复修复，公开签名保持 `resume(db_path, model, tools, fault=None)`。范围仅为 `tool_recovery/engine.py`、新增 `tool_recovery/test_engine.py` 和 `tool_recovery/RECOVERY.md`。本文件为独立构建报告。

使用了指定 Skill 的 `/build`，按其路由读取 build、engineering-workflow、interfaces、data-and-storage、state-and-lifecycle、tool-execution、model-and-context、delivery-and-operations 和 evidence-workflow；已重新读取并采用最终版 data-and-storage（包含多主体隔离和对象引用补回段落）。本案例单用户且结果全部在 SQLite 内，不引入多主体机制或对象存储。

## 实现与证据

| 用户承诺 | 实际入口和机制 | 已运行证据 |
|---|---|---|
| 接受决策后跨进程恢复，不重新计划 | resume → _accept_decision；完整决策、调用、操作一个事务接受 | 钩子提交后重开；子进程 os._exit 后换模型候选仍恢复原决策；plan 始终 1 次 |
| 部分完成独立保留 | 每个操作保存结果、每个调用独立就绪 | 3 个不同调用，在第一/第二/第三结果与消息保存后中断；各工具实际 execute 请求仍各 1 次 |
| 外部已成功但响应未知可核实 | execute 前持久 attempt；未知调用进入 lookup；结果和来源尝试共同保存 | lose_once 注入、外部生效后进程退出、结果写入事务被 SQLite trigger 拒绝；恢复 lookup，不重发原 execute |
| 查询不可用保留现场并报告 | unavailable 尝试 + RecoveryUnavailableError | 连续 2 次入口查询失败，模型不 finish，已完成 A 保留，B 不重发，C 不先执行；查询恢复后原任务完成 |
| call_id 精确配对、按原顺序、结果全齐后 finish | messages 主键 call_id，按 calls.position 投影，finish 前完整性屏障 | 用非字典序 call_id 和不同参数断言完整消息内容；每条消息恰好一次 |
| 相同业务操作新 call_id 可复用；内容改变拒绝 | operation_key 与规范参数分离，别名调用共用可靠结果；完整决策预检、下游拒绝持久化、核实回显校验 | 4 调用/3 操作只执行 3 次；同 key 改参数和重复 call_id 在派发前拒绝；既有下游不同参数拒绝，包括本地拒绝记录前退出 |
| 最终输出稳定、记录可关联消费 | run、calls、operations、attempts、messages、finish_attempts；最终文本/消费标记同事务 | 重复 resume 使用禁止访问的适配器仍返回原文本；join 检查请求→操作→结果来源，foreign_key_check 无错误 |
| 钩子对应已可靠保存事实 | 三个指定钩子均在 commit 后 | 7 个钩子位置由另一连接读取提交事实，再抛异常；恢复不重复触发已提交钩子 |
| 升级遇到不可恢复旧记录时明确失败 | user_version=1；旧有 outputs、未来版本拒绝 | 旧 final 保留原样；NeverCalled 适配器证明没有盲目重执行 |

运行命令（工作目录为本案例目录）：

```sh
python3 -B -m unittest -v test_engine.py
```

最终结果：**14 tests，0 failures，0 errors，OK**，测试运行报告耗时 0.620 秒。包含 11 次实际子进程 `os._exit(47)`，每次都检查退出码并用独立打开的数据库恢复；另含 7 个钩子异常位置的 subtest。测试用 Python 标准库、原始本地模拟器和临时 SQLite 文件，无真实 provider。初次测试有一条请求日志计数预期失败：模拟器拒绝参数冲突时会回滚同事务中的请求日志；已依据其实际事务行为修正断言，并以引擎持久 rejected 尝试验证没有再次执行。没有修改模拟器以通过测试。

`fakes.py` 前后 SHA256 一致：
`65d9c4ccab9acaebef304762ae1cb27f2bb1dff9e3149937db86e99c9eb0b155`。

## 限制与交接

- 单用户、单 `db_path` 活跃执行者由上层保证；未添加队列、HTTP、多机调度或新执行 API。去重历史和已完成结果的本地复用范围为该数据库中的已接受决策。
- finish 已在模型侧完成、但最终文本还未在本地提交的窗口，当前模型合同无 lookup/幂等能力，恢复可重复 finish。已实际验证两条 finish 历史和两条尝试、工具仍仅执行一次；未声称模型调用恰好一次。plan 未持久接受前也可能重调。
- 查询 None 表示确定未执行、ValueError 表示参数冲突、结果回显 key/arguments，均来自给定模拟器合同；真实服务需另验适配器、查询一致性及防重期限。
- 已有 outputs 非空的旧数据库缺少调用与决策历史，明确停止自动恢复，保留数据；没有伪造迁移或声称可恢复已丢失的旧现场。
- 未验证物理断电、存储损坏/丢失、真实 provider、网络时间预算、真实费用、集群竞争。SQLite FULL 配置不等同这些场景已通过。
- 未读取 evals、其他行为案例、旧报告或作者验收器；没有联网、浏览器、真实账号/模型服务、安装依赖、Git 操作或创建子代理。

详细恢复矩阵、字段关系、错误处理和运行方式见本案例 `RECOVERY.md`。
