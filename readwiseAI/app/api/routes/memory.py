"""长期记忆 API 路由 – 训练记录、错题本、记忆曲线、战力值历史."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.auth.models import TokenData

router = APIRouter(prefix="/memory", tags=["memory"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_ltm(user_id: str):
    """Load LongTermMemory for a user, raising 500 on failure."""
    try:
        from app.models.long_term_memory import LongTermMemory
        return LongTermMemory(user_id=user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"无法加载长期记忆: {exc}",
        )


# ===========================================================================
# 训练记录 Training Records
# ===========================================================================

class TrainingRecordIn(BaseModel):
    """Request body for adding a training record."""
    session_id: str = ""
    article_count: int = 0
    question_count: int = 0
    correct_count: int = 0
    total_time_seconds: int = 0
    difficulty: str = ""
    score: Optional[float] = None
    note: str = ""


@router.get("/training", summary="获取训练记录列表")
async def list_training_records(
    limit: int = Query(default=20, ge=1, le=100, description="返回条数"),
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """返回当前用户的所有训练记录（最新在前）。"""
    ltm = _get_ltm(token_data.user_id)
    records = ltm.get_training_records()
    records_sorted = sorted(records, key=lambda r: r.get("recorded_at", ""), reverse=True)
    return {
        "user_id": token_data.user_id,
        "total": len(records_sorted),
        "records": records_sorted[:limit],
    }


@router.post("/training", status_code=status.HTTP_201_CREATED, summary="添加训练记录")
async def add_training_record(
    body: TrainingRecordIn,
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """追加一条训练记录到长期记忆。"""
    ltm = _get_ltm(token_data.user_id)
    record = body.model_dump(exclude_none=True)
    ltm.append_training_record(record)
    return {"message": "训练记录已保存", "record": record}


# ===========================================================================
# 错题本 Mistake Book
# ===========================================================================

class MistakeIn(BaseModel):
    """Request body for adding a mistake entry."""
    mistake_id: str
    question_text: str
    options: Dict[str, str] = {}
    correct_answer: str = ""
    user_answer: str = ""
    article_excerpt: str = ""
    error_category: str = ""
    explanation: str = ""
    question_type: str = "detail"
    difficulty: str = "L2"


class MistakeUpdateIn(BaseModel):
    """Request body for updating a mistake entry (all fields optional)."""
    review_count: Optional[int] = None
    next_review_at: Optional[str] = None
    error_category: Optional[str] = None
    explanation: Optional[str] = None


@router.get("/mistakes", summary="获取错题列表")
async def list_mistakes(
    keyword: Optional[str] = Query(default=None, description="关键词搜索（题目/文章摘要）"),
    error_category: Optional[str] = Query(default=None, description="按错误类型筛选"),
    question_type: Optional[str] = Query(default=None, description="按题型筛选"),
    difficulty: Optional[str] = Query(default=None, description="按难度筛选（L1-L4）"),
    limit: int = Query(default=20, ge=1, le=100, description="返回条数"),
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """搜索/筛选错题本，支持关键词、错误类型、题型、难度过滤。"""
    ltm = _get_ltm(token_data.user_id)
    entries = ltm.mistake_book.search(
        keyword=keyword,
        error_category=error_category,
        question_type=question_type,
        difficulty=difficulty,
        limit=limit,
    )
    return {
        "user_id": token_data.user_id,
        "total": ltm.mistake_book.total,
        "returned": len(entries),
        "mistakes": [e.model_dump() for e in entries],
    }


@router.get("/mistakes/due", summary="获取待复习错题")
async def get_due_mistakes(
    limit: int = Query(default=10, ge=1, le=50, description="最多返回条数"),
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """返回按 SM-2 算法判定当前应复习的错题列表。"""
    ltm = _get_ltm(token_data.user_id)
    due = ltm.mistake_book.get_due_for_review(limit=limit)
    return {
        "user_id": token_data.user_id,
        "due_count": len(due),
        "mistakes": [e.model_dump() for e in due],
    }


@router.get("/mistakes/{mistake_id}", summary="获取单条错题详情")
async def get_mistake(
    mistake_id: str,
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """按 mistake_id 获取错题详细信息。"""
    ltm = _get_ltm(token_data.user_id)
    entries = ltm.mistake_book.search(limit=9999)
    entry = next((e for e in entries if e.mistake_id == mistake_id), None)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="错题不存在")
    return entry.model_dump()


@router.post("/mistakes", status_code=status.HTTP_201_CREATED, summary="添加错题")
async def add_mistake(
    body: MistakeIn,
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """向错题本添加一条新记录，并同步注册到遗忘曲线调度。"""
    from app.models.mistakes import MistakeEntry
    ltm = _get_ltm(token_data.user_id)
    entry = MistakeEntry(**body.model_dump())
    ltm.record_mistake(entry)
    return {"message": "错题已记录", "mistake_id": entry.mistake_id}


@router.put("/mistakes/{mistake_id}", summary="更新错题信息")
async def update_mistake(
    mistake_id: str,
    body: MistakeUpdateIn,
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """更新指定错题的字段（review_count、next_review_at 等）。"""
    ltm = _get_ltm(token_data.user_id)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="没有提供任何更新字段"
        )
    ok = ltm.mistake_book.update(mistake_id, **updates)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="错题不存在")
    return {"message": "错题已更新", "mistake_id": mistake_id}


@router.delete("/mistakes/{mistake_id}", summary="删除错题")
async def delete_mistake(
    mistake_id: str,
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """从错题本中删除指定记录。"""
    ltm = _get_ltm(token_data.user_id)
    ok = ltm.mistake_book.delete(mistake_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="错题不存在")
    return {"message": "错题已删除", "mistake_id": mistake_id}


# ===========================================================================
# 遗忘曲线 Forgetting Curve (SM-2)
# ===========================================================================

class ReviewIn(BaseModel):
    """Request body for recording a review result."""
    quality: int  # 0-5: recall quality per SM-2


# SM-2 quality bounds
_SM2_QUALITY_MIN = 0
_SM2_QUALITY_MAX = 5


@router.get("/curve", summary="获取遗忘曲线总览")
async def get_curve_overview(
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """返回当前用户遗忘曲线的统计概况（总条目数、待复习数等）。"""
    ltm = _get_ltm(token_data.user_id)
    fc = ltm.forgetting_curve
    due = fc.get_due_items(limit=9999)
    return {
        "user_id": token_data.user_id,
        "total_items": fc.total_items,
        "due_count": len(due),
    }


@router.get("/curve/due", summary="获取遗忘曲线待复习条目")
async def get_due_curve_items(
    limit: int = Query(default=10, ge=1, le=50, description="最多返回条数"),
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """返回 SM-2 算法判定应复习的条目（next_review_at ≤ 现在）。"""
    ltm = _get_ltm(token_data.user_id)
    items = ltm.forgetting_curve.get_due_items(limit=limit)
    return {
        "user_id": token_data.user_id,
        "due_count": len(items),
        "items": [i.model_dump() for i in items],
    }


@router.get("/curve/{item_id}", summary="获取单条遗忘曲线状态")
async def get_curve_item(
    item_id: str,
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取某条错题（item_id 即 mistake_id）的 SM-2 调度状态。"""
    ltm = _get_ltm(token_data.user_id)
    item = ltm.forgetting_curve.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="条目不存在")
    return item.model_dump()


@router.post("/curve/{item_id}/review", summary="提交复习结果")
async def record_review(
    item_id: str,
    body: ReviewIn,
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """按 SM-2 算法记录复习结果并更新下次复习时间。quality 取值 0-5。"""
    if not (_SM2_QUALITY_MIN <= body.quality <= _SM2_QUALITY_MAX):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"quality 必须在 {_SM2_QUALITY_MIN}-{_SM2_QUALITY_MAX} 之间",
        )
    ltm = _get_ltm(token_data.user_id)
    item = ltm.forgetting_curve.record_review(item_id, body.quality)
    # Also update mistake_book's next_review_at to stay in sync
    ltm.mistake_book.update(item_id, next_review_at=item.next_review_at)
    return {
        "message": "复习结果已记录",
        "item_id": item_id,
        "next_review_at": item.next_review_at,
        "interval_days": item.interval_days,
        "repetitions": item.repetitions,
        "easiness": item.easiness,
    }


# ===========================================================================
# 战力值历史 Power History
# ===========================================================================

class PowerRecordIn(BaseModel):
    """Request body for adding a power score record."""
    score: float
    reason: str = ""


@router.get("/power", summary="获取战力值历史")
async def get_power_history(
    limit: int = Query(default=30, ge=1, le=200, description="返回条数"),
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """返回当前用户的战力值（学习能力评分）历史记录。"""
    ltm = _get_ltm(token_data.user_id)
    history = ltm.get_power_history()
    recent = history[-limit:] if len(history) > limit else history
    return {
        "user_id": token_data.user_id,
        "total_records": len(history),
        "latest_score": history[-1]["score"] if history else None,
        "history": recent,
    }


@router.post("/power", status_code=status.HTTP_201_CREATED, summary="添加战力值记录")
async def add_power_record(
    body: PowerRecordIn,
    token_data: TokenData = Depends(get_current_user),
) -> Dict[str, Any]:
    """追加一条战力值记录。"""
    ltm = _get_ltm(token_data.user_id)
    ltm.append_power_record(score=body.score, reason=body.reason)
    return {"message": "战力值已记录", "score": body.score}
