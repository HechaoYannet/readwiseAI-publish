"""QuestionExpert – 题目生成（支持连续出题与语料库风格参考）."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List
from string import Template

from app.models.state import OrchestratorState
from app.sub_agents.base import BaseSubAgent

logger = logging.getLogger(__name__)

# Inline fallback prompt used when the prompt file is absent
_FALLBACK_PROMPT = """
你是高考英语出题专家。请根据以下文章，一次性生成 $count 道不同题型的阅读理解题。

## 文章
$article

## 题型要求
$question_types_str

## 难度
$difficulty（L1最简单，L4最难）

## 参考语料风格
$corpus_examples

## 输出格式（严格JSON，只输出JSON）
{{
  "questions": [
    {{
      "question_text": "题干内容",
      "options": {{"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"}},
      "correct_answer": "A",
      "explanation": "解析（说明答案依据在文章哪里）",
      "evidence": "原文中的依据句子",
      "type": "detail"
    }}
  ]
}}
"""

_DEFAULT_QUESTION_TYPES = ["detail", "inference", "vocabulary", "main_idea"]


class QuestionExpert(BaseSubAgent):
    name = "question_expert"
    description = "题目生成、选项设计（支持连续出题）"

    async def execute(
            self, input: Dict[str, Any], context: Dict[str, Any], state: "OrchestratorState | None" = None
    ) -> Dict[str, Any]:
        start = time.time()
        article = input.get("article", "")
        difficulty = input.get("difficulty", "L2")
        count = input.get("count", 3)

        # Accept either a list of question_types or a single question_type
        question_types: List[str] = input.get(
            "question_types",
            [input.get("question_type", "detail")] * count
            if input.get("question_type")
            else _DEFAULT_QUESTION_TYPES[:count],
        )
        # Ensure we have exactly `count` entries (cycle using modulo)
        # if len(question_types) < count:
        #     question_types = [question_types[i % len(question_types)] for i in range(count)]
        # question_types = question_types[:count]

        # Fetch corpus examples for style reference
        corpus_examples = self._get_corpus_examples(difficulty, context)
        if state is not None:
            state.status_history.append("# 正在生成题目")
        questions = await self._generate_questions(
            article=article,
            difficulty=difficulty,
            question_types=question_types,
            count=count,
            corpus_examples=corpus_examples,
        )

        return {
            "questions": questions,
            "metadata": {
                "latency_ms": self._timed(start),
                "agent": self.name,
                "count": len(questions),
            },
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_corpus_examples(self, difficulty: str, context: Dict[str, Any]) -> str:
        """Return formatted corpus examples for prompt injection."""
        try:
            corpus_repo = context.get("corpus_repo")
            if corpus_repo is None:
                from app.tools.corpus_repo import get_corpus_repo
                corpus_repo = get_corpus_repo()
            return corpus_repo.format_examples_for_prompt(difficulty=difficulty, count=1)
        except Exception as exc:
            logger.warning("Could not fetch corpus examples: %s", exc)
            return "（暂无语料库参考样例）"

    async def _generate_questions(
            self,
            article: str,
            difficulty: str,
            question_types: List[str],
            count: int,
            corpus_examples: str,
    ) -> List[Dict[str, Any]]:
        """Call LLM once to generate all questions in a single request."""
        _type_names = {
            "detail": "细节题",
            "inference": "推理题",
            "vocabulary": "词义题",
            "main_idea": "主旨题",
        }
        if question_types:
            question_types_str = "\n".join(
                f"{i + 1}. {qt}（{_type_names.get(qt, qt)}）"
                for i, qt in enumerate(question_types)
            )
        else:
            question_types_str = "根据 **参考语料** 的题目类型自由决定"

        template = self.load_prompt("question_prompt") or _FALLBACK_PROMPT
        prompt = Template(template).substitute(
            article=article,
            difficulty=difficulty,
            count=count,
            question_types_str=question_types_str,
            corpus_examples=corpus_examples,
        )

        result = await self._call_llm(prompt)
        questions: List[Dict[str, Any]] = result.get("questions", []) if result else []

        # Fallback: if LLM returned nothing or wrong format, build stubs
        if not questions:
            questions = [
                {
                    "question_text": "",
                    "options": {"A": "", "B": "", "C": "", "D": ""},
                    "correct_answer": "A",
                    "explanation": "",
                    "evidence": "",
                    "type": qt,
                }
                for qt in question_types
            ]
        else:
            # Annotate each question with its intended type if missing
            for i, q in enumerate(questions):
                if "type" not in q and i < len(question_types):
                    q["type"] = question_types[i]

        return questions
