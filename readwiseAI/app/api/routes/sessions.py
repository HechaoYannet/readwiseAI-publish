"""工作记忆会话 API 路由 – 查看、管理会话上下文."""
from __future__ import annotations

import re
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.dependencies import get_current_user
from app.auth.models import TokenData
from app.models import working_memory as wm_module
from app.models.working_memory import WorkingMemory

router = APIRouter(prefix="/sessions", tags=["sessions"])

# Only allow safe characters in session IDs (alphanumeric, hyphens, underscores)
_SESSION_ID_PATTERN = re.compile(r"^[\w\-]+$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_session_id(session_id: str) -> None:
    """Raise 400 if session_id contains unsafe characters."""
    if not _SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_id 包含非法字符",
        )


def _load_session(session_id: str, user_id: str) -> WorkingMemory:
    """Validate session_id, then load WorkingMemory; raises 400/404 on failure."""
    _validate_session_id(session_id)
    wm = WorkingMemory.load(session_id=session_id, user_id=user_id)
    if wm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"会话 '{session_id}' 不存在",
        )
    return wm


# ===========================================================================
# Session list & detail
# ===========================================================================

@router.get("", summary="获取会话列表")
async def list_sessions(
    session_type: str = Query(default="training", description="会话类型：training | chatting"),
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """返回当前用户指定类型的所有会话 ID 列表。"""
    ids = WorkingMemory.load_session_list(session_type=session_type, user_id=token_data.user_id)
    return {
        "user_id": token_data.user_id,
        "session_type": session_type,
        "session_ids": ids,
        "count": len(ids),
    }


@router.get("/current", summary="获取最近一次训练会话")
async def get_current_training_session(
    session_type: str = Query(default="training", description="会话类型：training | chatting"),
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """返回最近一次活跃会话的完整内容。会话不存在时返回 404。"""
    ids = WorkingMemory.load_session_list(session_type=session_type, user_id=token_data.user_id)
    if not ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="没有找到正在进行中的会话",
        )
    wm = _load_session(ids[0], token_data.user_id)
    return wm.model_dump()


@router.get("/{session_id}", summary="获取指定会话详情")
async def get_session(
    session_id: str,
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """返回指定会话的完整上下文（文章列表、题目队列、对话历史等）。"""
    wm = _load_session(session_id, token_data.user_id)
    return wm.model_dump()


@router.get("/{session_id}/articles", summary="获取会话文章列表")
async def get_session_articles(
    session_id: str,
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """返回指定会话中加载过的所有文章（标题、内容、难度等）。"""
    wm = _load_session(session_id, token_data.user_id)
    return {
        "session_id": session_id,
        "article_count": len(wm.articles),
        "articles": wm.articles,
    }


@router.get("/{session_id}/questions", summary="获取会话题目队列")
async def get_session_questions(
    session_id: str,
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """返回指定会话中生成的所有题目集合。"""
    wm = _load_session(session_id, token_data.user_id)
    return {
        "session_id": session_id,
        "question_sets": len(wm.question_queue),
        "questions": wm.question_queue,
    }


@router.get("/{session_id}/history", summary="获取会话对话历史")
async def get_session_history(
    session_id: str,
    limit: int = Query(default=40, ge=1, le=200, description="返回的最近消息条数"),
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """返回指定会话的对话历史（用户与助手的消息交替记录）。"""
    wm = _load_session(session_id, token_data.user_id)
    history = wm.conversation_history
    recent = history[-limit:] if len(history) > limit else history
    return {
        "session_id": session_id,
        "total_messages": len(history),
        "returned": len(recent),
        "history": recent,
    }


@router.get("/{session_id}/agent-info", summary="获取会话 Agent 信息")
async def get_session_agent_info(
    session_id: str,
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """返回各 Sub-Agent 在会话中记录的运行信息（诊断结果、规划结果等）。"""
    wm = _load_session(session_id, token_data.user_id)
    return {
        "session_id": session_id,
        "agent_info_count": len(wm.agent_information),
        "agent_information": wm.agent_information,
    }


@router.delete("/{session_id}", summary="删除指定会话")
async def delete_session(
    session_id: str,
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """删除指定的工作记忆会话文件（不可恢复）。"""
    # _load_session already validates session_id characters and existence
    _load_session(session_id, token_data.user_id)

    user_id = token_data.user_id
    try:
        user_dir = wm_module._safe_user_dir(wm_module._SESSIONS_DIR, user_id)
        session_file = user_dir / f"{session_id}.json"
        if session_file.exists():
            session_file.unlink()
        return {"message": "会话已删除", "session_id": session_id}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除会话失败: {exc}",
        )
