"""LLM service – thin wrapper around ChatOpenAI (or any compatible backend).

Set OPENAI_API_KEY (or DEEPSEEK_API_KEY + DEEPSEEK_BASE_URL) in environment.
If no key is set, a stub implementation is used so the rest of the system can
still be exercised in tests without real LLM calls.
"""
from __future__ import annotations

import json
import logging
import os
from dotenv import load_dotenv
from typing import Any, Dict, Optional

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM backend selection
# ---------------------------------------------------------------------------

OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_DEEPSEEK_BASE = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "1.3"))


class _StubLLM:
    """Stub LLM used when no API key is configured (useful for unit tests)."""

    async def ainvoke(self, prompt: str) -> "_StubMessage":
        logger.warning("StubLLM.ainvoke called – returning empty JSON object")
        return _StubMessage("{}")


class _StubMessage:
    def __init__(self, content: str):
        self.content = content


def _build_llm():
    if OPENAI_KEY:
        try:
            from langchain_openai import ChatOpenAI  # type: ignore

            return ChatOpenAI(model=MODEL, api_key=OPENAI_KEY)
        except Exception as exc:
            logger.warning("Failed to build ChatOpenAI: %s – falling back to stub", exc)
    elif DEEPSEEK_KEY:
        try:
            from langchain_openai import ChatOpenAI  # type: ignore

            return ChatOpenAI(
                model=MODEL,
                api_key=DEEPSEEK_KEY,
                base_url=DEEPSEEK_BASE_DEEPSEEK_BASE,
                temperature=TEMPERATURE
            )
        except Exception as exc:
            logger.warning("Failed to build DeepSeek LLM: %s – falling back to stub", exc)
    return _StubLLM()


# Singleton
_llm_instance: Optional[Any] = None


def get_llm() -> Any:
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = _build_llm()
    return _llm_instance


async def llm_json_call(prompt: str) -> Dict[str, Any]:
    """Call LLM and parse the response as JSON.

    Returns an empty dict on parse failure so callers can handle gracefully.
    Automatically writes a structured Markdown log entry via llm_logger when
    a request context is active (request_id set via contextvars).
    """
    import time as _time
    from app.services import llm_logger

    llm = get_llm()
    raw_content = ""
    parsed: Dict[str, Any] = {}
    error_msg = ""
    success = False
    t0 = _time.monotonic()

    try:
        response = await llm.ainvoke(prompt)
        raw_content = response.content if hasattr(response, "content") else str(response)
        # Strip Markdown code fences if present
        content = raw_content.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
        parsed = json.loads(content)
        success = True
        return parsed
    except json.JSONDecodeError as exc:
        error_msg = f"JSON parse error: {exc}"
        logger.error("LLM response is not valid JSON: %s", exc)
        return {}
    except Exception as exc:
        error_msg = str(exc)
        logger.error("LLM call failed: %s", exc)
        return {}
    finally:
        latency_ms = int((_time.monotonic() - t0) * 1000)
        try:
            llm_logger.log_llm_call(
                prompt=prompt,
                raw_response=raw_content,
                parsed=parsed,
                latency_ms=latency_ms,
                success=success,
                error=error_msg,
            )
        except Exception as log_exc:  # pragma: no cover
            logger.warning("LLM logger error: %s", log_exc)
