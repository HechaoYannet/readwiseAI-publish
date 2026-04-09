"""Base class for all Sub-agents."""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict

from app.models.state import OrchestratorState
from app.services.llm_service import llm_json_call

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).parent.parent.parent / "data" / "prompts"


class BaseSubAgent(ABC):
    name: str = "base"
    description: str = ""

    @abstractmethod
    async def execute(self, input: Dict[str, Any], context: Dict[str, Any], state: "OrchestratorState | None" = None) -> Dict[str, Any]:
        """Execute the sub-task and return a result dict."""

    async def _call_llm(self, prompt: str) -> Dict[str, Any]:
        """Convenience wrapper around the shared LLM service."""
        return await llm_json_call(prompt)

    def _timed(self, start: float) -> int:
        return int((time.time() - start) * 1000)

    @staticmethod
    def load_prompt(name: str) -> str:
        """Load a prompt template from data/prompts/<name>.txt.

        Falls back to an empty string if the file does not exist.
        Prompts are re-read on every call so updates take effect without restart.
        """
        path = _PROMPT_DIR / f"{name}.txt"
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("Prompt file not found: %s", path)
            return ""
