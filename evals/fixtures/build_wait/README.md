# 持久人工等待模块

使用 /build 修复这个单用户本地 Agent 后端模块。它使用 Python 标准库 SQLite，所有数据和任务都在本地；没有网络、模型 API 或真实发布动作。请沿用现有函数签名和数据库，完成实现与验证，不换框架、不建 HTTP 服务。

当前用户反馈：暂停保存异常后任务无法继续；重复继续有时丢结果；取消和继续竞争时结果难以解释。

项目合同：

- open_db 创建/打开数据库；create 建立 active 任务。
- pause 仅允许 active，保存 waiting 状态、wait_id 和 snapshot；inject_failure 用于模拟保存过程异常。失败不应留下半完成的等待现场，重开数据库后仍应可解释。
- resume 仅接受当前 waiting 的 wait_id；input 是 JSON 值，message_id 是客户端稳定命令 ID。首次接受后状态为 ready，并可靠留下一个可领取 job。同 message_id、task、wait_id 和 input 的重复请求应返回首次结果，不再派工；复用 message_id 改内容应拒绝。
- cancel 仅允许 waiting；取消和继续并发时只接受一个。落败请求抛 ValueError，不允许改写胜者结果。取消不删除历史。
- 错误的 task/wait_id 不得改变任何任务或派工事实。保留操作历史，正常接受的 pause/resume/cancel 各记一次。
- 需要证明调用入口确实使用更新后的实现，验证重开数据库、故障、重复输入和并发竞争。可以增加内部辅助函数及必要约束，不改公开签名。
