"""Dispatcher – routes sub-tasks to the appropriate sub-agent and executes them."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.models.state import OrchestratorState, SubTask, SubTaskStatus

logger = logging.getLogger(__name__)


def _get_sub_agent(name: str) -> Optional[Any]:
    """Lazy-import sub-agents to avoid circular imports."""
    if name == "diagnosis_expert":
        from app.sub_agents.diagnosis import DiagnosisExpert

        return DiagnosisExpert()
    if name == "corpus_expert":
        from app.sub_agents.corpus import CorpusExpert

        return CorpusExpert()
    if name == "question_expert":
        from app.sub_agents.question import QuestionExpert

        return QuestionExpert()
    if name == "qa_expert":
        from app.sub_agents.qa import QAExpert

        return QAExpert()
    return None


def _build_memory_context(state: OrchestratorState) -> Dict[str, Any]:
    """Load working memory and long-term memory objects for the current request.

    Returns a context dict ready to be merged into the agent execution context.
    Errors are caught and logged so they never block task execution.
    """
    ctx: Dict[str, Any] = {}

    # Working memory
    session_id = state.session_id or ""
    try:
        from app.models.working_memory import WorkingMemory

        ctx["working_memory"] = WorkingMemory.get_or_create(
            session_id=session_id, user_id=state.user_id
        )
    except Exception as exc:
        logger.warning("Could not load working memory: %s", exc)

    # Long-term memory
    try:
        from app.models.long_term_memory import LongTermMemory

        ctx["long_term_memory"] = LongTermMemory(user_id=state.user_id)
    except Exception as exc:
        logger.warning("Could not load long-term memory: %s", exc)

    # Corpus repository
    try:
        from app.tools.corpus_repo import get_corpus_repo

        ctx["corpus_repo"] = get_corpus_repo()
    except Exception as exc:
        logger.warning("Could not load corpus repo: %s", exc)

    return ctx


def _resolve_task_inputs(task: SubTask, state: OrchestratorState) -> None:
    """Resolve cross-task input placeholders before execution.

    When a task input contains ``article_task_id``, that sibling task's
    article content is injected into ``input["article"]`` at dispatch time.
    This lets question tasks depend on corpus tasks without knowing the
    article text at planning time.
    """
    article_task_id: Optional[str] = task.input.pop("article_task_id", None)
    if not article_task_id:
        return
    sibling_result = state.completed_results.get(article_task_id, {})
    article_content = sibling_result.get("article", {}).get("content", "")
    if article_content:
        task.input.setdefault("article", article_content)
    else:
        logger.warning(
            "Could not resolve article from task %s for %s",
            article_task_id,
            task.sub_task_id,
        )


class Dispatcher:
    async def execute_single(
            self, task: SubTask, state: OrchestratorState
    ) -> OrchestratorState:
        """Execute a single sub-task and return the updated state.

        The task must already have its dependencies satisfied.  After execution
        the task status will be COMPLETED (on success) or FAILED (on error).
        """
        return await self._execute_task(task, state)

    async def dispatch_all_pending(
            self, state: OrchestratorState
    ) -> OrchestratorState:
        """Execute all PENDING sub-tasks whose dependencies are satisfied.

        .. deprecated::
            Prefer ``execute_single`` called from the Orchestrator loop so that
            each task is verified immediately after completion.  This method is
            retained for backward compatibility with tests and external callers.
        """
        for task in state.sub_tasks:
            if task.status != SubTaskStatus.PENDING:
                continue
            if not self._deps_satisfied(task, state):
                continue
            state = await self._execute_task(task, state)
        return state

    def _deps_satisfied(self, task: SubTask, state: OrchestratorState) -> bool:
        for dep_id in task.depends_on:
            dep = next((t for t in state.sub_tasks if t.sub_task_id == dep_id), None)
            if dep is None or dep.status != SubTaskStatus.COMPLETED:
                return False
        return True

    async def _execute_task(
            self, task: SubTask, state: OrchestratorState
    ) -> OrchestratorState:
        agent = _get_sub_agent(task.assigned_to)
        if agent is None:
            task.status = SubTaskStatus.FAILED
            task.error_message = f"Unknown agent: {task.assigned_to}"
            state.error_log.append(task.error_message)
            return state

        # Resolve cross-task input references before execution
        _resolve_task_inputs(task, state)

        task.status = SubTaskStatus.RUNNING
        # Set LLM logger context so llm_json_call can emit structured logs.
        try:
            from app.services import llm_logger
            llm_logger.set_context(
                request_id=state.request_id,
                agent_name=task.assigned_to,
                task_id=task.sub_task_id,
            )
        except Exception as exp:  # pragma: no cover
            print(f"Failed to set LLM logger context for task {task.sub_task_id}: {exp}")
            pass

        try:
            context: Dict[str, Any] = {
                "user_id": state.user_id,
                "completed_results": state.completed_results,
            }
            # Inject memory context
            context.update(_build_memory_context(state))

            result = await agent.execute(task.input, context, state)
            task.result = result
            # Mark as completed here so verifier can inspect it
            task.status = SubTaskStatus.COMPLETED
            logger.info("Task %s completed by %s", task.sub_task_id, task.assigned_to)
        except Exception as exc:
            task.status = SubTaskStatus.FAILED
            task.error_message = str(exc)
            state.error_log.append(
                f"Task {task.sub_task_id} raised exception: {exc}"
            )
            logger.error("Task %s failed: %s", task.sub_task_id, exc)

        return state
