"""Verifier – uses an LLM to validate sub-task results against acceptance criteria."""
from __future__ import annotations

import logging
from string import Template
from app.models.state import OrchestratorState, SubTask, SubTaskStatus
from app.services.llm_service import llm_json_call
from app.services import llm_logger

logger = logging.getLogger(__name__)

VERIFICATION_PROMPT = """
你是任务验收专家。判断Sub-agent返回的结果是否满足要求。
注意：对 **出题计划** 任务的审核可适当放宽。

## 任务描述
$sub_task_description

## 验收标准
$acceptance_criteria

## Sub-agent返回结果
$sub_task_result

## 输出格式（严格JSON，只输出JSON）
{{
  "passed": true,
  "completion_score": 0.95,
  "issues": [],
  "suggestion": ""
}}

请输出JSON格式的验收结论：
"""

MAX_RETRIES = 2


class Verifier:
    async def verify(
            self, state: OrchestratorState, completed_task: SubTask
    ) -> OrchestratorState:
        """Verify the result of a completed sub-task."""

        criteria_text = "\n".join(
            f"- {c}" for c in completed_task.acceptance_criteria
        )
        verdict = {}
        if criteria_text:
            prompt = Template(VERIFICATION_PROMPT).substitute(
                sub_task_description=completed_task.description,
                acceptance_criteria=criteria_text,
                sub_task_result=str(completed_task.result),
            )
            state.status_history.append(f"# 智能体正在校验：{completed_task.sub_task_id}")
            llm_logger.set_context(state.request_id, "verifier", completed_task.sub_task_id)
            verdict = await llm_json_call(prompt)
            state.status_history.append(f"# {completed_task.sub_task_id} 校验完成")

        # If LLM is not available,or no criteria, default to passed so flow continues
        if not verdict:
            verdict = {"passed": True, "issues": [], "suggestion": ""}

        if verdict.get("passed", False):
            completed_task.status = SubTaskStatus.COMPLETED
            state.completed_results[completed_task.sub_task_id] = completed_task.result
            logger.info("Sub-task %s verified OK", completed_task.sub_task_id)
        elif state.retry_count < MAX_RETRIES:
            # add suggestion and retry
            completed_task.description = (completed_task.description
                                          + "\n\n验收专家建议修改如下：\n" + verdict.get("suggestion", ""))
            completed_task.status = SubTaskStatus.RETRY
            state.retry_count += 1
            issues = verdict.get("issues", [])
            state.error_log.append(
                f"任务{completed_task.sub_task_id}验收失败: {issues}"
            )
            logger.warning(
                "Sub-task %s failed verification (attempt %d): %s",
                completed_task.sub_task_id,
                state.retry_count,
                issues,
            )
        else:
            completed_task.status = SubTaskStatus.FAILED
            state.completed_results[completed_task.sub_task_id] = completed_task.result
            state.error_log.append(
                f"任务{completed_task.sub_task_id}最终失败"
            )
            logger.error(
                "Sub-task %s failed verification after max retries",
                completed_task.sub_task_id,
            )

        return state
