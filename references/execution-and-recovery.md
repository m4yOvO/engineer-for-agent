# 执行、恢复与外部动作：阶段导航

正文已按工程阶段整理到 [工程阶段入口](engineering-workflow.md)。本页保留旧链接；请从下面对应协议读取设计、实现和验收要求。

## 操作一致性契约

见 [操作一致性契约](stages/state-and-lifecycle.md#操作一致性契约)。

## 1. 受理到执行的交接

见 [1. 受理到执行的交接](stages/queue-and-execution.md#受理到执行的交接)。

## 2. 执行权、并发与重试

见 [2. 执行权、并发与重试](stages/queue-and-execution.md#执行权与故障拥有者)。

## 3. 持久边界与恢复算法

见 [3. 持久边界与恢复算法](stages/state-and-lifecycle.md#恢复矩阵)。

## 4. 同一业务意图与合法新动作

见 [4. 同一业务意图与合法新动作](stages/tool-execution.md#同一业务意图与合法新动作)。

## 5. 未决结果、业务完成与持续对账

见 [5. 未决结果、业务完成与持续对账](stages/tool-execution.md#未决结果业务完成与持续对账)。

## 6. 等待、批准、取消与委派

见 [6. 等待、批准、取消与委派](stages/state-and-lifecycle.md#人工等待与取消)。

## 7. 四种易混行为

见 [7. 四种易混行为](stages/state-and-lifecycle.md#重放与重开)。

## 8. 进度事件与观察器

见 [8. 进度事件与观察器](stages/events-and-observability.md#进度事件与观察器)。

### 长连接、授权与保留期

见 [长连接、授权与保留期](stages/events-and-observability.md#长连接授权与保留期)。
