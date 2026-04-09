"""QAExpert – 问答专家（基于LangChain工具调用）.

支持：查词、长难句拆解、语法解释、翻译，以及通过工具自主访问
当前文章、错题本、语料库等记忆。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List
from string import Template

from app.models import working_memory
from app.models.state import OrchestratorState
from app.services import llm_logger
from app.sub_agents.base import BaseSubAgent
from app.tools.dictionary import lookup_word

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fallback inline prompts (used when prompt file absent or for direct calls)
# ---------------------------------------------------------------------------

SENTENCE_PARSE_PROMPT = """
你是英语语言学专家。请拆解以下英语长难句的句子结构。

## 句子
$sentence

## 输出格式（严格JSON，只输出JSON）
{{
  "main_clause": "主句",
  "subordinate_clauses": ["从句1", "从句2"],
  "translation": "中文翻译",
  "structure_analysis": "句子结构分析",
  "key_grammar_points": ["语法点1", "语法点2"]
}}
"""

GRAMMAR_PROMPT = """
你是英语语法专家。请解释以下语法现象。

## 语法问题
$grammar_query

## 输出格式（严格JSON，只输出JSON）
{{
  "grammar_point": "语法要点名称",
  "explanation": "详细解释",
  "examples": ["例句1", "例句2"],
  "common_mistakes": ["常见错误1"]
}}
"""

TRANSLATE_PROMPT = """
请将以下英文翻译成地道的中文。

## 原文
$content

## 输出格式（严格JSON，只输出JSON）
{{
  "translation": "中文翻译",
  "notes": "翻译说明（可选）"
}}
"""

# Maximum number of tool call iterations to prevent runaway loops
_MAX_TOOL_CALLS = 5


class QAExpert(BaseSubAgent):
    name = "qa_expert"
    description = "查词、长难句拆解、语法解释、翻译，支持通过工具访问文章和错题本"

    async def execute(
            self, input: Dict[str, Any], context: Dict[str, Any], state: "OrchestratorState | None" = None
    ) -> Dict[str, Any]:
        start = time.time()
        query_type = input.get("query_type", "free")
        content = input.get("content", "")
        context_sentence = input.get("context_sentence", "")

        # Check if we have memory context – if so, use tool-calling for free-form questions
        has_memory = bool(
            context.get("working_memory") or context.get("long_term_memory")
        )
        if state is not None:
            wm = working_memory.WorkingMemory(session_id=state.session_id or "", user_id=state.user_id)
            wm.add_message(role="user", content=content)

        if state is not None:
            state.status_history.append(f"# 大模型正在分析")
        if query_type == "word":
            result = await self._handle_word(content, context_sentence)
        elif query_type == "sentence":
            result = await self._handle_sentence(content)
        elif query_type == "grammar":
            result = await self._handle_grammar(content)
        elif query_type == "translate":
            result = await self._handle_translate(content)
        elif query_type == "free" and has_memory:
            result = await self._handle_free_with_tools(content, context)
        elif query_type == "free":
            result = await self._handle_free_simple(content)
        else:
            result = {"error": f"Unknown query_type: {query_type}"}

        result["metadata"] = {"latency_ms": self._timed(start), "agent": self.name}

        if state is not None:
            state.status_history.append(f"# 大模型分析完成")
            wm.add_message(role="assistant", content=str(result))
        return result

    # ------------------------------------------------------------------
    # Structured query handlers
    # ------------------------------------------------------------------

    async def _handle_word(self, word: str, ctx: str) -> Dict[str, Any]:
        basic = await lookup_word(word)
        if ctx:
            extra = await self._call_llm(
                f"单词'{word}'在以下上下文中的具体含义是什么？\n上下文：{ctx}\n基础释义：{basic}\n"
                f"输出JSON：{{\"context_meaning\": \"...\", \"usage_notes\": \"...\"}}"
            )
            return {
                "word": word,
                "basic_meaning": basic,
                "context_meaning": extra.get("context_meaning", ""),
                "usage_notes": extra.get("usage_notes", ""),
            }
        return {"word": word, "basic_meaning": basic}

    async def _handle_sentence(self, sentence: str) -> Dict[str, Any]:
        prompt = Template(SENTENCE_PARSE_PROMPT).substitute(sentence=sentence)
        result = await self._call_llm(prompt)
        return result or {"error": "解析失败"}

    async def _handle_grammar(self, query: str) -> Dict[str, Any]:
        prompt = Template(GRAMMAR_PROMPT).substitute(grammar_query=query)
        result = await self._call_llm(prompt)
        return result or {"error": "解释失败"}

    async def _handle_translate(self, content: str) -> Dict[str, Any]:
        prompt = Template(TRANSLATE_PROMPT).substitute(content=content)
        result = await self._call_llm(prompt)
        return result or {"error": "翻译失败"}

    # ------------------------------------------------------------------
    # Free-form query with LangChain tool-calling
    # ------------------------------------------------------------------

    async def _handle_free_with_tools(
            self, user_question: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Use LangChain tool-calling to answer a free-form question.

        Configures the memory tools with the current context and invokes
        the LLM with tool-use capability, iterating up to _MAX_TOOL_CALLS times.
        """
        try:
            from app.tools.memory_tools import configure_tools, ALL_TOOLS
            from app.services.llm_service import get_llm
            from langchain_core.messages import HumanMessage, ToolMessage

            configure_tools(
                working_memory=context.get("working_memory"),
                long_term_memory=context.get("long_term_memory"),
                corpus_repo=context.get("corpus_repo"),
            )

            llm = get_llm()
            try:
                llm_with_tools = llm.bind_tools(ALL_TOOLS)
            except (AttributeError, NotImplementedError):
                logger.warning("LLM does not support tool binding; falling back to simple call")
                return await self._handle_free_simple(user_question)

            messages: List[Any] = [HumanMessage(content=user_question)]
            tool_calls_made = 0
            tool_results: List[str] = []
            response: Any = None

            for _ in range(_MAX_TOOL_CALLS):
                start_time = time.monotonic()
                raw_content = ""
                tc_success = False
                tc_error = ""
                response = None
                try:
                    response = await llm_with_tools.ainvoke(messages)
                    raw_content = response.content if hasattr(response, "content") else str(response)
                    tc_success = True
                except Exception as exc:
                    tc_error = str(exc)
                    raise
                finally:
                    latency_ms = int((time.monotonic() - start_time) * 1000)
                    tool_calls_info: Dict[str, Any] = {}
                    if response is not None and hasattr(response, "tool_calls") and response.tool_calls:
                        tool_calls_info = {"tool_calls": [tc.get("name", "") for tc in response.tool_calls]}
                    llm_logger.log_llm_call(
                        prompt=user_question,
                        raw_response=raw_content,
                        parsed=tool_calls_info,
                        latency_ms=latency_ms,
                        success=tc_success,
                        error=tc_error,
                    )
                messages.append(response)

                if not hasattr(response, "tool_calls") or not response.tool_calls:
                    break

                for tc in response.tool_calls:
                    tool_name = tc.get("name", "")
                    tool_args = tc.get("args", {})
                    tool_id = tc.get("id", tool_name)

                    tool_result = self._invoke_tool(tool_name, tool_args)
                    tool_results.append(f"[{tool_name}]: {tool_result}")
                    messages.append(
                        ToolMessage(content=tool_result, tool_call_id=tool_id)
                    )
                    tool_calls_made += 1

            final_content = (
                response.content
                if response is not None and hasattr(response, "content") and response.content
                else "（无法生成回答）"
            )
            res = {
                "answer": final_content,
                "references": tool_results,
                "tool_calls_made": tool_calls_made,
            }
            return res

        except Exception as exc:
            logger.error("Tool-calling QA failed: %s", exc)
            return await self._handle_free_simple(user_question)

    def _invoke_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Synchronously invoke a named tool and return its string result."""
        from app.tools import memory_tools as mt
        tool_map = {t.name: t for t in mt.ALL_TOOLS}
        tool_fn = tool_map.get(tool_name)
        if tool_fn is None:
            return f"（未知工具: {tool_name}）"
        try:
            result = tool_fn.invoke(args)
            return str(result)[:1500]  # Cap output to avoid context overflow
        except Exception as exc:
            logger.warning("Tool %s raised an error: %s", tool_name, exc)
            return f"（工具调用失败: {exc}）"

    async def _handle_free_simple(self, user_question: str) -> Dict[str, Any]:
        """Simple free-form QA without tools, used as fallback."""
        prompt = (
            f"你是高考英语学习助手。请简洁、准确地回答以下问题。\n\n"
            f"问题：{user_question}\n\n"
            f'输出JSON：{{"answer": "...", "references": [], "follow_up": "..."}}'
        )
        result = await self._call_llm(prompt)
        return result or {"answer": "（暂时无法回答，请重试）", "references": []}
