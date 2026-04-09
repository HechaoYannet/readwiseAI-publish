"""LLM Logger – Markdown-format audit log for every LLM call.

Design principle: **minimal intrusion**.
- No changes to sub-agent signatures.
- Context (request_id, agent_name, task_id) is propagated via Python
  ``contextvars`` so callers deeper in the stack can write rich logs
  without receiving extra parameters.
- Log files are written to ``data/logs/llm/<request_id>.md``, one file
  per /api/attempt request.

Log format
----------
Each file starts with a **Request Started** section, then one
**LLM Call** section per ``llm_json_call`` invocation.

Usage
-----
1. In the attempt route: ``llm_logger.log_request_start(...)``
2. In the dispatcher (before executing a task):
   ``llm_logger.set_context(request_id, agent_name, task_id)``
3. In ``llm_service.llm_json_call``: ``llm_logger.log_llm_call(...)``
"""
from __future__ import annotations

import inspect
import logging
from functools import wraps
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Context variables – set by the dispatcher before each sub-task execution.
# ---------------------------------------------------------------------------
_ctx_request_id: ContextVar[str] = ContextVar("llm_log_request_id", default="")
_ctx_agent_name: ContextVar[str] = ContextVar("llm_log_agent_name", default="unknown")
_ctx_task_id: ContextVar[str] = ContextVar("llm_log_task_id", default="")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_LOG_DIR = Path("data/logs/llm")
_MAX_PROMPT_PREVIEW = 5000  # chars shown in log (full prompt may be very long)
_MAX_OUTPUT_PREVIEW = 5000  # chars shown in log (full response may be very long)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _log_path(request_id: str) -> Path:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR / f"{request_id}.md"


def _append(request_id: str, text: str) -> None:
    """Append *text* to the request's log file, ignoring I/O errors."""
    if not request_id:
        return
    try:
        with _log_path(request_id).open("a", encoding="utf-8") as fh:
            fh.write(text)
    except Exception as exc:  # pragma: no cover
        logger.warning("LLM logger write failed: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def set_context(request_id: str, agent_name: str, task_id: str) -> None:
    """Set per-task context for subsequent ``log_llm_call`` invocations.

    Must be called in the same async task context as the LLM call.
    """
    _ctx_request_id.set(request_id)
    _ctx_agent_name.set(agent_name)
    _ctx_task_id.set(task_id)


def with_context(request_id: str, agent_name: str, task_id: str):
    """Decorator to automatically set context for a function or coroutine.

    Usage:
        @with_context(request_id, agent_name, task_id)
        async def my_llm_function():
            # Context is automatically set when this function is called
            return await llm_json_call(...)
    """

    def decorator(func):
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                token1 = _ctx_request_id.set(request_id)
                token2 = _ctx_agent_name.set(agent_name)
                token3 = _ctx_task_id.set(task_id)
                try:
                    return await func(*args, **kwargs)
                finally:
                    _ctx_request_id.reset(token1)
                    _ctx_agent_name.reset(token2)
                    _ctx_task_id.reset(token3)

            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                token1 = _ctx_request_id.set(request_id)
                token2 = _ctx_agent_name.set(agent_name)
                token3 = _ctx_task_id.set(task_id)
                try:
                    return func(*args, **kwargs)
                finally:
                    _ctx_request_id.reset(token1)
                    _ctx_agent_name.reset(token2)
                    _ctx_task_id.reset(token3)

            return sync_wrapper

    return decorator


def get_request_id() -> str:
    """Return the request_id currently active in this context."""
    return _ctx_request_id.get()


def log_request_start(
        request_id: str,
        session_id: str,
        user_id: str,
        payload: Dict[str, Any],
) -> None:
    """Write the opening section of a request log file."""
    import json as _json

    payload_str = _json.dumps(payload, ensure_ascii=False, indent=2)
    text = (
        f"# LLM Request Log\n\n"
        f"| 字段 | 值 |\n"
        f"|------|----|\n"
        f"| **request_id** | `{request_id}` |\n"
        f"| **session_id** | `{session_id}` |\n"
        f"| **user_id** | `{user_id}` |\n"
        f"| **时间戳** | `{_now_str()}` |\n\n"
        f"## ▶ 请求开始\n\n"
        f"**记录点**: `REQUEST_RECEIVED`  \n"
        f"**时间**: `{_now_str()}`\n\n"
        f"```json\n{payload_str}\n```\n\n"
        f"---\n\n"
    )
    _append(request_id, text)


def log_llm_call(
        prompt: str,
        raw_response: str,
        parsed: Dict[str, Any],
        latency_ms: int,
        success: bool,
        error: str = "",
) -> None:
    """Write one LLM call record to the active request's log file.

    Reads ``request_id``, ``agent_name``, and ``task_id`` from context vars.
    """
    import json as _json

    request_id = _ctx_request_id.get()
    agent_name = _ctx_agent_name.get()
    task_id = _ctx_task_id.get()

    if not request_id:
        return  # No active request context – skip logging

    # Truncate very long prompts/responses to keep logs readable
    prompt_display = prompt + f"\n[共 {len(prompt)} 字符]" if len(prompt) <= _MAX_PROMPT_PREVIEW else (
            prompt[len(prompt) - _MAX_PROMPT_PREVIEW:] + f"\n… [前半截断, 共 {len(prompt)} 字符]"
    )
    response_display = raw_response + f"\n[共 {len(raw_response)} 字符]" if len(
        raw_response) <= _MAX_OUTPUT_PREVIEW else (
            raw_response[:_MAX_OUTPUT_PREVIEW] + f"\n… [后半截断, 共 {len(raw_response)} 字符]"
    )

    status_icon = "✅" if success else "❌"
    parsed_str = _json.dumps(parsed, ensure_ascii=False, indent=2)

    text = (
        f"## {status_icon} LLM Call – `{agent_name}` / `{task_id}`\n\n"
        f"**记录点**: `LLM_CALL`  \n"
        f"**时间**: `{_now_str()}`  \n"
        f"**耗时**: `{latency_ms} ms`\n\n"
        f"### 📥 输入 Prompt\n\n"
        f"```\n{prompt_display}\n```\n\n"
        f"### 📤 原始输出\n\n"
        f"```\n{response_display}\n```\n\n"
        f"### 🔍 解析结果\n\n"
        f"```json\n{parsed_str}\n```\n\n"
    )

    if not success and error:
        text += f"### ⚠️ 错误信息\n\n```\n{error}\n```\n\n"

    text += "---\n\n"
    _append(request_id, text)


def log_request_end(request_id: str, status: str, error_log: list) -> None:
    """Write the closing section of a request log file."""
    import json as _json

    error_str = _json.dumps(error_log, ensure_ascii=False, indent=2)
    text = (
        f"## 🏁 请求结束\n\n"
        f"**记录点**: `REQUEST_DONE`  \n"
        f"**时间**: `{_now_str()}`  \n"
        f"**最终状态**: `{status}`\n\n"
    )
    if error_log:
        text += f"### 错误日志\n\n```json\n{error_str}\n```\n\n"
    _append(request_id, text)
