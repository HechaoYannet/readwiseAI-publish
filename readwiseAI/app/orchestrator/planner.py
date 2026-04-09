"""Planner – uses an LLM to decompose a user request into a list of sub-tasks."""
from __future__ import annotations

import json
from string import Template
import logging
from typing import Any, Dict, List

from app.models.state import OrchestratorState, SubTask, SubTaskStatus
from app.services.llm_service import llm_json_call
from app.services import llm_logger

logger = logging.getLogger(__name__)

ROUTER_DECIDER_PROMPT = """
你是ReadWise AI的主控Agent。请根据用户请求和上下文，决定这个请求使用Rule-based planning还是LLM-based planning。
## 规则基于规划（Rule-based planning）适用于常见、简单的请求类型，避免不必要的LLM调用。以下是规则定义的 request_type:
    1. **attempt**（错题分析与同类题生成）
    2. **corpus**（文章生成）
    3. **question**（给定上下文出题）
    4. **qa**（问答）
        - query_type 参数指定子类型：word/sentence/grammar/translate/free
        - 注意：如果 query_type 是 free，说明这是一个灵活、独立、开放的LLM请求，适合复杂需求或无关英语的请求，
            这种情况下，你应该判断任务复杂程度，如果涉及多环节、多操作任务，应该使用LLM-based planning；
            如果任务较简单，请使用 Rule-based planning.
    5. training_set（训练题组生成，包括总体规划、语料生成、出题）
## LLM基于规划（LLM-based planning）适用于复杂、模糊、多步骤或需要创造性分解的请求，允许LLM根据具体情况灵活生成子任务和分配子代理。
    LLM-based planning没有固定的 request_type，可以处理各种类型的请求，特别是那些不符合上述规则的请求，或者虽然符合但任务复杂度较高的请求。

## 输出格式（严格JSON） 
{
  "planning_strategy": "rule-based" or "llm-based",
  "reasoning": "选择该策略的原因，简要说明为什么这个请求适合规则基于规划或LLM基于规划"
}

## 用户请求
$user_request

请根据以下用户请求和上下文，输出JSON格式的规划策略选择：
"""
PLANNING_PROMPT = """
你是ReadWise AI的主控Agent。你的职责是将用户请求拆解为可执行的子任务。

## 可用的Sub-agent
1. **diagnosis_expert**: 错因分析专家
   - 能力：分析错题原因、定位证据句、生成修复建议、生成同类题
   - 适用场景：学生做错了题需要分析、需要同类题训练
   - "input"参数：
    {
        "paragraph": "原文段落",
        "question_text": "题干文本",
        "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
        "user_answer": "用户选项",
        "correct_answer": "标准答案选项",
        "time_spent": 60,  // 学生做题用时（秒）
        "need_similar": False, // 是否需要生成同类题
    }

2. **corpus_expert**: 语料专家
   - 能力：
     a) 普通模式：按难度(L1-L4)、体裁(议论文/说明文/记叙文)、主题生成高考风格文章
     b) 总体规划模式（enable_planning=true）：读取整个语料库 + 学生错题/战力值，
        规划一组4篇文章的训练方案，返回 training_plan 并自动生成后续子任务
     c) 风格化模式（reference_id 指定真题ID）：以真题为参考风格生成文章
   - 适用场景：需要生成新文章、需要难度适配的阅读材料、需要生成完整训练题组
   - 警告：总体规划模式会自动生成出题子任务，请勿重复调用**question_expert**生成题目。
   - "input"参数:
    {
        "enable_planning": True,
        "difficulty": "L1/L2/L3/L4",
        "genre": "expository", // argumentative/expository/narrative
        "topic": "", // 文章主题关键词，普通模式填写
        "reference_id": "", // 由"总体规划模式"生成，你不要填这个参数
        "description": "",
    }

3. **question_expert**: 出题专家
   - 能力：基于文章生成题目、设计选项、生成答案
   - 适用场景：需要为文章配题、需要专项题型训练
   - 警告：若调用了**corpus_expert**的总体规划模式，请勿重复调用**question_expert**生成题目，因为总体规划模式会自动生成出题子任务。
   - "input"参数:
    {
        "article": "",
        "question_type": "",
        "difficulty": "",
        "count": "",
    },

4. **qa_expert**: 问答专家
   - 能力：通用专家、查词释义、长难句拆解、语法解释、翻译
     请求类型由"query_type"参数指定，分别是：word/sentence/grammar/translate/free
     **free**模式是灵活、独立、开放的LLM，掌握记忆管理和复杂工具调用能力，适合复杂需求或无关英语的请求。
   - 适用场景：学生提问单词/句子/语法
   - "input"参数： 
    {
        "query_type": "", // word/sentence/grammar/translate/free
        "content": "",
        "context_sentence": "", // 可选，提供上下文有助于更准确的解释
    },

## 输出格式（严格JSON）
{
  "overall_goal": "任务总体目标",
  "sub_tasks": [
    {
      "sub_task_id": "sub_001", // 子任务ID，编号从001开始
      "assigned_to": "diagnosis_expert", // 分配给哪个Sub-agent
      "description": "具体要做什么",
      "input": {},
      "acceptance_criteria": ["验收标准1", "验收标准2"],
      "depends_on": []
    }
  ]
}

## 用户请求
$user_request

## 上下文
$context

## 额外注意
1. 采用尽可能小的调度策略，避免任务过多导致请求超时，这将直接导致任务失败！
2. 如果不确定用户意图，优先使用 **qa_expert**问答专家 分析用户需求，而不是直接生成大量子任务。
3. 简单任务可以无需验收标准。
4. 如果任务与英语无关，优先使用 **qa_expert**问答专家 **free**模式。


请输出JSON格式的规划结果（只输出JSON，不要其他内容）：
"""


def _make_rule_based_plan(user_request: Dict[str, Any]) -> Dict[str, Any]:
    """Fast rule-based planning for well-known request types."""
    request_type = user_request.get("request_type", "attempt")

    if request_type == "attempt":
        return {
            "overall_goal": "分析错题并提供诊断与同类题",
            "sub_tasks": [
                {
                    "sub_task_id": "sub_001",
                    "assigned_to": "diagnosis_expert",
                    "description": "分析学生做错的题目，给出错因分析和同类题",
                    "input": {
                        "paragraph": user_request.get("paragraph", ""),
                        "question_text": user_request.get("question_text", ""),
                        "options": user_request.get("options", {}),
                        "user_answer": user_request.get("user_answer", ""),
                        "correct_answer": user_request.get("correct_answer", ""),
                        "time_spent": user_request.get("time_spent", 0),
                        "need_similar": user_request.get("need_similar", False),
                    },
                    "acceptance_criteria": [
                        "包含 error_category 字段",
                        "包含 explanation 字段",
                    ],
                    "depends_on": [],
                }
            ],
        }

    if request_type == "corpus":
        return {
            "overall_goal": "生成指定难度和体裁的高考风格文章",
            "sub_tasks": [
                {
                    "sub_task_id": "sub_001",
                    "assigned_to": "corpus_expert",
                    "description": "生成文章",
                    "input": {
                        "difficulty": user_request.get("difficulty", "L2"),
                        "genre": user_request.get("genre", "expository"),
                        "topic": user_request.get("topic", ""),
                        "word_count": user_request.get("word_count", 300),
                        "reference_id": user_request.get("reference_id"),
                        "description": user_request.get("description", ""),
                    },
                    "acceptance_criteria": ["文章字数在目标范围内", "体裁符合要求"],
                    "depends_on": [],
                }
            ],
        }

    if request_type == "question":
        return {
            "overall_goal": "为给定文章生成题目",
            "sub_tasks": [
                {
                    "sub_task_id": "sub_001",
                    "assigned_to": "question_expert",
                    "description": "出题",
                    "input": {
                        "article": user_request.get("article", ""),
                        "question_type": user_request.get("question_type", "detail"),
                        "difficulty": user_request.get("difficulty", "L2"),
                        "count": user_request.get("count", 3),
                    },
                    "acceptance_criteria": ["题目数量符合要求", "答案在原文中有依据"],
                    "depends_on": [],
                }
            ],
        }

    if request_type == "qa":
        return {
            "overall_goal": "回答学生的问题",
            "sub_tasks": [
                {
                    "sub_task_id": "sub_001",
                    "assigned_to": "qa_expert",
                    "description": "解答问题",
                    "input": {
                        "query_type": user_request.get("query_type", "free"),
                        "content": user_request.get("content", ""),
                        "context_sentence": user_request.get("context_sentence", ""),
                    },
                    "acceptance_criteria": [],
                    "depends_on": [],
                }
            ],
        }

    if request_type == "training_set":
        return {
            "overall_goal": "生成完整训练题组（总体规划 → 语料生成 → 出题）",
            "sub_tasks": [
                {
                    "sub_task_id": "sub_000",
                    "assigned_to": "corpus_expert",
                    "description": (
                        "读取语料库和学生学情，规划本次训练4篇文章（主题、"
                        "参考真题、语法点、难度、字数等），返回训练计划并"
                        "生成语料+出题子任务"
                    ),
                    "input": {
                        "enable_planning": True,
                        "user_level": user_request.get("user_level", "L2"),
                    },
                    "acceptance_criteria": [
                        "包含 training_plan 字段",
                        "training_plan 包含文章规划",
                    ],
                    "depends_on": [],
                }
            ],
        }

    return {}


class Planner:
    async def plan(self, state: OrchestratorState) -> OrchestratorState:
        """Generate a task plan and store sub_tasks in state."""
        user_request = state.original_request

        # Set LLM logger context so llm_json_call can emit structured logs.
        # LLM决定使用Rule-based planning还是LLM-based planning。
        prompt = Template(ROUTER_DECIDER_PROMPT).substitute(
            user_request=json.dumps(user_request)
        )
        state.status_history.append("# 智能体正在决策")
        llm_logger.set_context(state.request_id, "planner", "head")
        route_decision = await llm_json_call(prompt)
        planning_strategy = route_decision.get("planning_strategy", "llm-based")

        plan = None
        if planning_strategy == "rule-based":
            logger.info("Planner chose rule-based planning for %s", state.request_id)
            plan = _make_rule_based_plan(user_request)
        elif planning_strategy == "llm-based":
            logger.info("Planner chose LLM-based planning for %s", state.request_id)

            # Set LLM logger context so llm_json_call can emit structured logs.
            prompt = Template(PLANNING_PROMPT).substitute(
                user_request=json.dumps(user_request),
                context="",
            )
            llm_logger.set_context(state.request_id, "planner", "head")
            plan = await llm_json_call(prompt)
            if not plan:
                logger.warning(
                    "LLM-based planner failed to generate a plan for %s, falling back to RULE",
                    state.request_id,
                )
                plan = _make_rule_based_plan(user_request)


        if not plan or "sub_tasks" not in plan:
            logger.error("Planner returned empty plan for %s", state.request_id)
            state.error_log.append("Planner failed to generate a plan")
            return state

        state.current_plan = plan
        state.sub_tasks = [SubTask(**st) for st in plan["sub_tasks"]]
        logger.info(
            "Planned %d sub-tasks for %s", len(state.sub_tasks), state.request_id
        )
        state.status_history.append(f"# 智能体决策完成,已规划{len(state.sub_tasks)}个子任务")
        return state

    async def replan(
            self, state: OrchestratorState, failed_task: "SubTask"  # noqa: F821
    ) -> OrchestratorState:
        """Adjust input for a failed task and mark it for retry."""
        feedback = state.error_log[-1] if state.error_log else "unknown error"

        prompt = f"""
之前的任务失败了，需要调整输入后重试。

## 原任务
{failed_task.description}

## 原输入
{failed_task.input}

## 失败原因
{feedback}

## 请输出调整后的输入（严格JSON格式，只输出JSON）
"""
        state.status_history.append(f"# 智能体正在优化任务 {failed_task.sub_task_id}")
        llm_logger.set_context(state.request_id, "planner", failed_task.sub_task_id)
        adjusted = await llm_json_call(prompt)
        if adjusted:
            failed_task.input = adjusted
        failed_task.status = SubTaskStatus.PENDING
        failed_task.retry_count += 1
        state.status_history.append(f"# {failed_task.sub_task_id}优化结束")
        return state
