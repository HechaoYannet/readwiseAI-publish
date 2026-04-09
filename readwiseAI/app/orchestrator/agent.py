"""Orchestrator – main control loop that coordinates Planner, Dispatcher, and Verifier."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.models.state import OrchestratorState, RequestStatus, SubTask, SubTaskStatus
from app.orchestrator.checkpoint import get_checkpoint_manager
from app.orchestrator.dispatcher import Dispatcher
from app.orchestrator.planner import Planner
from app.orchestrator.verifier import Verifier

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self):
        self.planner = Planner()
        self.verifier = Verifier()
        self.dispatcher = Dispatcher()
        self.checkpoint = get_checkpoint_manager()

    async def process_request(
        self, request_id: str, user_request: Dict[str, Any]
    ) -> None:
        """Entry point called by BackgroundTasks."""
        state = self.checkpoint.load(request_id)
        if state is None:
            logger.error("No checkpoint found for %s", request_id)
            return

        await self._run(state)

    async def resume_processing(self, request_id: str) -> None:
        """Resume after a sub-agent callback."""
        state = self.checkpoint.load(request_id)
        if state is None:
            return
        await self._run(state)

    async def _run(self, state: OrchestratorState) -> None:
        for _iteration in range(20):  # guard against infinite loops

            # 计划器
            if state.status == RequestStatus.PENDING:
                state.status = RequestStatus.PLANNING
                state = await self.planner.plan(state)
                if not state.sub_tasks:
                    state.status = RequestStatus.FAILED
                    break
                state.status = RequestStatus.WAITING

            # 调度器和验收器：每次只执行一个任务，立即验收
            elif state.status == RequestStatus.WAITING:
                # Find the next pending task whose dependencies are all satisfied
                next_task = next(
                    (
                        t
                        for t in state.sub_tasks
                        if t.status == SubTaskStatus.PENDING
                        and self._deps_satisfied(t, state)
                    ),
                    None,
                )

                if next_task is not None:
                    # Execute the single task
                    state = await self.dispatcher.execute_single(next_task, state)

                    # Immediately verify if execution succeeded
                    if next_task.status == SubTaskStatus.COMPLETED:
                        state = await self.verifier.verify(state, next_task)

                        if next_task.status == SubTaskStatus.COMPLETED:
                            # Verified OK – inject any new sub-tasks emitted by this task
                            state = self._inject_new_tasks(state, next_task)
                        elif next_task.status == SubTaskStatus.RETRY:
                            # Verification failed – immediately replan so the task
                            # is PENDING again and will be dispatched next iteration
                            state = await self.planner.replan(state, next_task)
                    # If execution itself raised an exception, task.status is FAILED –
                    # fall through and let the all-done check handle it.

                else:
                    # No pending task with satisfied deps available right now
                    if self._all_tasks_done(state):
                        state.status = (
                            RequestStatus.COMPLETED
                            if not self._any_failed(state)
                            else RequestStatus.FAILED
                        )
                    else:
                        # Some tasks are still running (async callbacks) or waiting
                        # for deps that haven't completed yet – save and exit.
                        self.checkpoint.save(state)
                        return

            elif state.status in (RequestStatus.COMPLETED, RequestStatus.FAILED):
                break

        self._finalize(state)

    # ------------------------------------------------------------------
    # Dynamic task injection (Plan A – LangChain-style flexibility)
    # 动态添加任务（Plan A – 类似 LangChain 的灵活性）
    # ------------------------------------------------------------------

    def _deps_satisfied(self, task: SubTask, state: OrchestratorState) -> bool:
        """Return True if all dependencies of *task* are verified and in completed_results."""
        for dep_id in task.depends_on:
            if dep_id not in state.completed_results:
                return False
        return True

    def _inject_new_tasks(
        self, state: OrchestratorState, completed_task: SubTask
    ) -> OrchestratorState:
        """Inject sub-tasks emitted by a completed task into the state.

        When a corpus_expert planning task returns ``new_sub_tasks`` in its
        result, those tasks are appended to ``state.sub_tasks`` so the
        Dispatcher will pick them up on the next iteration.  This implements
        the Plan A "high-flexibility main LLM" behaviour without requiring an
        upfront full plan.
        """
        new_tasks_data: List[Dict[str, Any]] = completed_task.result.get(
            "new_sub_tasks", []
        )
        if not new_tasks_data:
            return state

        existing_ids = {t.sub_task_id for t in state.sub_tasks}
        injected = 0
        for task_data in new_tasks_data:
            tid = task_data.get("sub_task_id", "")
            if not tid or tid in existing_ids:
                continue
            try:
                state.sub_tasks.append(SubTask(**task_data))
                existing_ids.add(tid)
                injected += 1
            except Exception as exc:
                logger.warning("Could not inject task %s: %s", tid, exc)

        if injected:
            logger.info(
                "Injected %d new sub-tasks from %s", injected, completed_task.sub_task_id
            )
        state.status_history.append("# 准备就绪")
        return state

    # ------------------------------------------------------------------
    def _all_tasks_done(self, state: OrchestratorState) -> bool:
        terminal = {SubTaskStatus.COMPLETED, SubTaskStatus.FAILED}
        return all(t.status in terminal for t in state.sub_tasks)

    def _any_failed(self, state: OrchestratorState) -> bool:
        return any(t.status == SubTaskStatus.FAILED for t in state.sub_tasks)

    def _any_retryable(self, state: OrchestratorState) -> bool:
        return state.retry_count < 2

    def _finalize(self, state: OrchestratorState) -> None:
        result = self._assemble_result(state)
        self.checkpoint.save_result(state.request_id, state.user_id, result)
        self.checkpoint.delete(state.request_id)
        logger.info(
            "Request %s finalized with status %s", state.request_id, state.status
        )
        # Write request-end entry to LLM audit log.
        try:
            from app.services import llm_logger
            llm_logger.log_request_end(
                request_id=state.request_id,
                status=str(state.status),
                error_log=state.error_log,
            )
        except Exception:  # pragma: no cover
            pass

    def _assemble_result(self, state: OrchestratorState) -> dict:
        return {
            "request_id": state.request_id,
            "session_id": state.session_id,
            "status": state.status,
            "results": state.completed_results,
            "error_log": state.error_log,
        }


# Singleton
_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator
