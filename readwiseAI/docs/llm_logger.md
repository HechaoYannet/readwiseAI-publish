# LLM 日志系统设计文档

## 1. 概述

本文档描述了 ReadWise AI 项目中大模型（LLM）日志系统的设计与实现。

**核心目标**：以**最小侵入**的方式，记录每次 `/api/attempt` 请求中大模型接收到了什么、做了什么、输出了什么，用于调试和分析。

---

## 2. 工作列表

- [x] 创建 `app/services/llm_logger.py`：Markdown 日志写入模块，基于 `contextvars` 传递上下文
- [x] 修改 `app/services/llm_service.py`：在 `llm_json_call` 中注入日志钩子（`finally` 块）
- [x] 修改 `app/orchestrator/dispatcher.py`：每个子任务执行前调用 `llm_logger.set_context()`
- [x] 修改 `app/api/routes/attempts.py`：请求到达时调用 `llm_logger.log_request_start()`
- [x] 修改 `app/orchestrator/agent.py`：请求完成时调用 `llm_logger.log_request_end()`
- [x] 创建本文档 `docs/llm_logger.md`

---

## 3. 最小侵入设计

### 3.1 `contextvars` 上下文传播

LLM 调用链路较深（`attempts.py → orchestrator → dispatcher → sub_agent → llm_service`），若通过参数传递会改变多处函数签名。

解决方案：使用 Python 标准库 `contextvars.ContextVar`，在 dispatcher 执行每个子任务前设置上下文变量，`llm_json_call` 读取这些变量，无需修改任何中间层接口。

```python
# dispatcher.py（新增约 6 行）
from app.services import llm_logger
llm_logger.set_context(
    request_id=state.request_id,
    agent_name=task.assigned_to,
    task_id=task.sub_task_id,
)
```

### 3.2 `finally` 块保证日志完整性

`llm_json_call` 在 `finally` 块中写日志，保证无论调用成功还是失败（JSON 解析错误、网络异常等）都会留下记录。

### 3.3 异常隔离

所有日志写入操作用 `try/except` 包裹，日志系统的任何错误不会影响主业务流程。

---

## 4. 日志文件格式

### 位置

```
data/logs/llm/<request_id>.md
```

每次 `/api/attempt` 请求生成一个独立文件，文件名为 `request_id`（如 `req_a1b2c3d4e5f6.md`）。

### 结构

```
# LLM Request Log

| 字段         | 值                      |
|-------------|------------------------|
| request_id  | `req_xxxxxxxxxxxx`     |
| session_id  | `session_xxxxxxxxxxxx` |
| user_id     | `user123`              |
| 时间戳       | `2026-04-05 16:30:00 UTC` |

## ▶ 请求开始

**记录点**: `REQUEST_RECEIVED`
**时间**: `2026-04-05 16:30:00 UTC`

```json
{ ...请求体 payload... }
```

---

## ✅ LLM Call – `diagnosis_expert` / `task_001`

**记录点**: `LLM_CALL`
**时间**: `2026-04-05 16:30:01 UTC`
**耗时**: `1234 ms`

### 📥 输入 Prompt

```
<发送给大模型的完整 prompt>
```

### 📤 原始输出

```
<大模型返回的原始字符串>
```

### 🔍 解析结果

```json
{ ...解析后的 JSON... }
```

---

## 🏁 请求结束

**记录点**: `REQUEST_DONE`
**时间**: `2026-04-05 16:30:05 UTC`
**最终状态**: `RequestStatus.COMPLETED`
```

### 记录点说明

| 记录点             | 含义              |
|--------------------|-----------------|
| `REQUEST_RECEIVED` | 请求到达 API 层   |
| `LLM_CALL`         | 一次 LLM 调用完成 |
| `REQUEST_DONE`     | 请求全部处理完成   |

---

## 5. 关键文件变更

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `app/services/llm_logger.py` | **新增** | 日志写入模块（约 180 行） |
| `app/services/llm_service.py` | 微修改 | `llm_json_call` 增加 `finally` 日志钩子 |
| `app/orchestrator/dispatcher.py` | 微修改 | `_execute_task` 执行前设置 context vars |
| `app/api/routes/attempts.py` | 微修改 | 请求到达时写 request-start 日志 |
| `app/orchestrator/agent.py` | 微修改 | `_finalize` 写 request-end 日志 |
| `docs/llm_logger.md` | **新增** | 本文档 |

---

## 6. 配置参数

在 `app/services/llm_logger.py` 顶部可调整：

| 常量                  | 默认值         | 说明 |
|-----------------------|--------------|------|
| `_LOG_DIR`            | `data/logs/llm` | 日志目录 |
| `_MAX_PROMPT_PREVIEW` | `2000`         | Prompt 最大展示字符数 |
| `_MAX_OUTPUT_PREVIEW` | `2000`         | 原始输出最大展示字符数 |

---

## 7. 使用示例

发送一次 `/api/attempt` 请求后，在 `data/logs/llm/` 目录下可找到对应的 Markdown 文件：

```bash
cat data/logs/llm/req_a1b2c3d4e5f6.md
```

文件内容按时间顺序包含：请求信息 → 各 LLM 调用详情 → 请求结束状态，便于排查大模型输入/输出异常。
