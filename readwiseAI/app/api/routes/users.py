"""User management API routes."""
from __future__ import annotations
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.auth.models import ChangePasswordRequest, TokenData
from app.services import user_service
from app.models import working_memory

router = APIRouter(prefix="/users", tags=["users"])


class UpdateUserRequest(BaseModel):
    username: str = ""
    exam_region: str = ""
    grade: str = ""
    school: str = ""


@router.get("/me")
async def get_me(token_data: TokenData = Depends(get_current_user)) -> Dict[str, Any]:
    """Get current user's profile."""
    user = user_service.get_user(token_data.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return user.model_dump(exclude={"invite_code"})


@router.put("/me")
async def update_me(
        body: UpdateUserRequest,
        token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """Update current user's profile."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = user_service.update_user(token_data.user_id, **updates)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="更新失败（用户名可能已被占用）",
        )
    return updated.model_dump(exclude={"invite_code"})


@router.get("/stats")
async def get_stats(token_data: TokenData = Depends(get_current_user)) -> Dict[str, Any]:
    """Get user statistics (power history, mistake count, etc.)."""
    user_id = token_data.user_id
    try:
        from app.models.long_term_memory import LongTermMemory
        ltm = LongTermMemory(user_id=user_id)
        power_history = ltm.get_power_history()
        mistake_count = ltm.mistake_book.total
        due_count = len(ltm.mistake_book.get_due_for_review())
        return {
            "user_id": user_id,
            "mistake_count": mistake_count,
            "due_for_review": due_count,
            "latest_power": power_history[-1]["score"] if power_history else None,
            "power_records": len(power_history),
        }
    except Exception:
        return {"user_id": user_id, "error": "Failed to retrieve stats"}


@router.put("/password")
async def change_password(
        body: ChangePasswordRequest,
        token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """Change the current user's password."""
    ok, err, err_code = user_service.change_password(
        user_id=token_data.user_id,
        old_password=body.old_password,
        new_password=body.new_password,
        confirm_password=body.confirm_password,
    )
    if not ok:
        http_status = (
            status.HTTP_401_UNAUTHORIZED
            if err_code == "OLD_PASSWORD_INCORRECT"
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=http_status, detail=err)
    return {"message": "密码修改成功，请重新登录"}


@router.get("/train/currSession")
async def get_current_training_session(token_data: TokenData = Depends(get_current_user)) -> Dict[str, Any]:
    """Get the current training session for the user."""
    session = working_memory.WorkingMemory.load_session_list(
        "training", token_data.user_id
    )[0]
    session = working_memory.WorkingMemory.load(session_id=session, user_id=token_data.user_id).model_dump()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有正在进行的训练")
    return session
