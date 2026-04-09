"""POST /api/attempt – submit an answer attempt for processing."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends
from pip._internal.network import session

from app.auth.dependencies import get_current_user
from app.auth.models import TokenData
from app.models.state import AttemptRequest, OrchestratorState, RequestStatus
from app.orchestrator.agent import get_orchestrator
from app.orchestrator.checkpoint import get_checkpoint_manager

router = APIRouter()


def _generate_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:12]


@router.post("/attempt")
async def submit_attempt(
        attempt: AttemptRequest,
        background_tasks: BackgroundTasks,
        token_data: TokenData = Depends(get_current_user),
):
    """Submit a user attempt; returns a request_id for later polling.

    The caller must provide a valid JWT Bearer token.  The user_id is taken
    from the token and must NOT be supplied in the request body.
    """
    user_id = token_data.user_id
    request_id = _generate_request_id()
    now = datetime.now()
    session_id = attempt.session_id or "session_" + uuid.uuid4().hex[:12]
    state = OrchestratorState(
        request_id=request_id,
        session_id=session_id,
        user_id=user_id,
        status=RequestStatus.PENDING,
        original_request=attempt.model_dump(),
        created_at=now,
        updated_at=now,
    )

    checkpoint_manager = get_checkpoint_manager()
    checkpoint_manager.save(state)

    # Log request start to LLM audit log (non-blocking).
    try:
        from app.services import llm_logger
        llm_logger.log_request_start(
            request_id=request_id,
            session_id=session_id,
            user_id=user_id,
            payload=attempt.model_dump(),
        )
    except Exception:
        pass

    orchestrator = get_orchestrator()
    background_tasks.add_task(
        orchestrator.process_request,
        request_id,
        attempt.model_dump(),
    )

    return {
        "request_id": request_id,
        "session_id": session_id,
        "status": "processing",
        "result_url": f"/api/result/{request_id}",
    }
