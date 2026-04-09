"""POST /internal/callback/{request_id} – sub-agent result callback."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from app.models.state import SubTaskStatus
from app.orchestrator.agent import get_orchestrator
from app.orchestrator.checkpoint import get_checkpoint_manager

router = APIRouter()


class CallbackPayload(BaseModel):
    task_id: str
    result: dict


@router.post("/callback/{request_id}")
async def subagent_callback(
    request_id: str,
    payload: CallbackPayload,
    background_tasks: BackgroundTasks,
):
    """Called by a sub-agent when it has finished a task."""
    checkpoint_manager = get_checkpoint_manager()
    state = checkpoint_manager.load(request_id)
    if state is None:
        return {"status": "not_found"}

    for sub_task in state.sub_tasks:
        if sub_task.sub_task_id == payload.task_id:
            sub_task.result = payload.result
            sub_task.status = SubTaskStatus.COMPLETED
            break

    checkpoint_manager.save(state)

    orchestrator = get_orchestrator()
    background_tasks.add_task(orchestrator.resume_processing, request_id)

    return {"status": "ok"}
