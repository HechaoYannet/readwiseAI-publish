"""DiagnosisExpert – 错因分析 + 同类题生成."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional
from string import Template

import json

from app import orchestrator
from app.models import working_memory
from app.models.state import OrchestratorState

from app.sub_agents.base import BaseSubAgent

logger = logging.getLogger(__name__)

DIAGNOSIS_PROMPT = """
你是英语阅读错题诊断专家。请分析学生做错的原因并提供修复建议。

## 题目信息
原文段落：$paragraph
题目：$question_text
选项：$options
学生答案：$user_answer
正确答案：$correct_answer
用时（秒）：$time_spent

## 输出格式（严格JSON，只输出JSON）
{{
  "error_category": "词汇理解/推理判断/细节查找/主旨理解/其他",
  "explanation": "详细错因分析",
  "evidence_sentence": "原文中的关键证据句",
  "suggestion": "针对性学习建议",
  "confidence": 0.9
}}
"""

SIMILAR_QUESTION_PROMPT = """
你是英语出题专家。请根据以下信息生成一道同类型题目。

## 原题错因
错误类型：$error_category
原题主题：$paragraph_summary

## 输出格式（严格JSON，只输出JSON）
{{
  "paragraph": "新的阅读段落（英文，100-150词）",
  "question": "题目",
  "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
  "correct_answer": "A/B/C/D",
  "explanation": "答案解析"
}}
"""


class DiagnosisExpert(BaseSubAgent):
    name = "diagnosis_expert"
    description = "错因分析、同类题生成"

    async def execute(
            self, input: Dict[str, Any], context: Dict[str, Any], state: "OrchestratorState | None" = None
    ) -> Dict[str, Any]:
        start = time.time()

        diagnosis = await self._analyze_error(input, state)
        similar: Optional[Dict[str, Any]] = None
        if input.get("need_similar", True):
            similar = await self._generate_similar(input, diagnosis, state)

        return {
            "diagnosis": diagnosis,
            "similar_question": similar,
            "metadata": {
                "latency_ms": self._timed(start),
                "agent": self.name,
            },
        }

    async def _analyze_error(self, input: Dict[str, Any], state: OrchestratorState) -> Dict[str, Any]:
        # Quick rule-based shortcut: if user_answer == correct_answer it's not really wrong
        if input.get("user_answer") == input.get("correct_answer"):
            return {
                "error_category": "无错误",
                "explanation": "学生答案正确",
                "evidence_sentence": "",
                "suggestion": "",
                "confidence": 1.0,
            }

        # Try to load prompt from file; fall back to inline template
        template = self.load_prompt("diagnosis_prompt") or DIAGNOSIS_PROMPT
        prompt = Template(template).substitute(
            paragraph=input.get("paragraph", ""),
            question_text=input.get("question_text", ""),
            options=input.get("options", {}),
            user_answer=input.get("user_answer", ""),
            correct_answer=input.get("correct_answer", ""),
            time_spent=input.get("time_spent", 0),
        )
        if state is not None:
            state.status_history.append("# 正在分析错因")
        result = await self._call_llm(prompt)
        if not result:
            result = {
                "error_category": "未知",
                "explanation": "分析失败，请重试",
                "evidence_sentence": "",
                "suggestion": "",
                "confidence": 0.0,
            }
        if state is not None:
            wm = working_memory.WorkingMemory(session_id=state.session_id or "", user_id=state.user_id)
            wm.add_agent_information(
                {f"diagnosis_{state.original_request.get('question_number')}": json.dumps(result,
                                                                                          ensure_ascii=False,
                                                                                          indent=2)})
        return result

    async def _generate_similar(
            self, input: Dict[str, Any], diagnosis: Dict[str, Any], state: "OrchestratorState | None"
    ) -> Dict[str, Any]:
        paragraph = input.get("paragraph", "")
        summary = paragraph[:100] if paragraph else "英语阅读理解"
        prompt = Template(SIMILAR_QUESTION_PROMPT).substitute(
            error_category=diagnosis.get("error_category", ""),
            paragraph_summary=summary,
        )
        if state is not None:
            state.status_history.append("# 正在生成同类型题")
        result = await self._call_llm(prompt)
        if state is not None:
            wm = working_memory.WorkingMemory(session_id=state.session_id or "", user_id=state.user_id)
            wm.add_agent_information({"similar_question": json.dumps(result, ensure_ascii=False, indent=2)})
        return result or {}
