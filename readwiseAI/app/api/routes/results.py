"""GET /api/result/{request_id} – poll for processing results."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.auth.dependencies import get_current_user
from app.auth.models import TokenData
from app.models.state import RequestStatus
from app.orchestrator.checkpoint import get_checkpoint_manager

router = APIRouter()


@router.get("/result/{request_id}")
async def get_result(
        request_id: str,
        token_data: TokenData = Depends(get_current_user),
):
    """Poll for the result of a previously submitted request.

    Requires a valid JWT Bearer token.  Returns 403 if the request belongs to
    a different user, or ``{"status": "not_found"}`` if the request_id is
    unknown (to avoid leaking whether a request exists).
    """
    user_id = token_data.user_id
    checkpoint_manager = get_checkpoint_manager()

    # Ownership check: verify that the request belongs to the authenticated user.
    stored_user_id = checkpoint_manager.lookup_user_id(request_id)
    if stored_user_id is None:
        return JSONResponse(status_code=200, content={"status": "not_found"})
    if stored_user_id != user_id:
        return JSONResponse(status_code=403, content={"error": "Forbidden"})

    # Check for a saved final result first.
    saved = checkpoint_manager.load_result(request_id, user_id)
    if saved is not None:
        return saved

    # Fall back to live checkpoint.
    state = checkpoint_manager.load(request_id)
    if state is None:
        return JSONResponse(status_code=200, content={"status": "not_found"})

    if state.status == RequestStatus.COMPLETED:
        result = {
            "request_id": request_id,
            "session_id": state.session_id,
            "status": "completed",
            "status_history": state.status_history,
            "results": state.completed_results,
            "error_log": state.error_log,
        }
        checkpoint_manager.save_result(request_id, user_id, result)
        checkpoint_manager.delete(request_id)
        return result

    if state.status == RequestStatus.FAILED:
        return {
            "request_id": request_id,
            "status": "failed",
            "status_history": state.status_history,
            "error_log": state.error_log,
        }

    return {"request_id": request_id, "status": state.status, "status_history": state.status_history}
