"""ForgettingCurve – SM-2遗忘曲线算法实现.

基于SM-2（SuperMemo 2）间隔重复算法，计算每道错题的下次复习时间。
状态持久化到 data/long_term/{user_id}/forgetting.json。

SM-2 参考: https://www.supermemo.com/en/blog/application-of-a-computer-to-improve-the-results-obtained-in-working-with-the-super-memo-method
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_LONG_TERM_DIR = Path(__file__).parent.parent.parent / "data" / "long_term"

# Only allow alphanumeric characters, hyphens, and underscores in user IDs
# to prevent path traversal attacks.
_USER_ID_PATTERN = re.compile(r"^[\w\-]+$")


def _safe_user_dir(base_dir: Path, user_id: str) -> Path:
    """Return a path for user_id inside base_dir, with traversal checks.

    Raises ValueError if user_id is invalid or resolves outside base_dir.
    """
    if not _USER_ID_PATTERN.match(user_id):
        raise ValueError(f"Invalid user_id: {user_id!r}")
    resolved_base = base_dir.resolve()
    user_dir = (base_dir / user_id).resolve()
    try:
        user_dir.relative_to(resolved_base)
    except ValueError:
        raise ValueError(f"Path traversal detected for user_id: {user_id!r}")
    return user_dir
    # if not str(user_dir).startswith(str(resolved_base) + "/") and user_dir != resolved_base:
    #     raise ValueError(f"Path traversal detected for user_id: {user_id!r}")
    # return user_dir



# Quality values expected by SM-2 (0-5)
# 5: perfect recall, 4: correct with hesitation, 3: correct with difficulty,
# 2: incorrect but remembered on hint, 1: incorrect, 0: complete blackout
_MIN_QUALITY_FOR_PASS = 3


class SM2Item(BaseModel):
    """SM-2 scheduling state for a single item (mistake entry).

    Attributes:
        item_id: Typically the mistake_id.
        easiness: Easiness factor (E-Factor), starts at 2.5.
        interval_days: Days until next review.
        repetitions: Number of successful repetitions.
        next_review_at: ISO timestamp for the next scheduled review.
        last_reviewed_at: ISO timestamp of the most recent review.
    """

    item_id: str
    easiness: float = 2.5
    interval_days: int = 1
    repetitions: int = 0
    next_review_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    last_reviewed_at: Optional[str] = None

    def review(self, quality: int) -> None:
        """Update SM-2 state based on response quality (0-5).

        Args:
            quality: Recall quality from 0 (complete blackout) to 5 (perfect).
        """
        quality = max(0, min(5, quality))

        if quality >= _MIN_QUALITY_FOR_PASS:
            if self.repetitions == 0:
                self.interval_days = 1
            elif self.repetitions == 1:
                self.interval_days = 6
            else:
                self.interval_days = int(round(self.interval_days * self.easiness))
            self.repetitions += 1
        else:
            # Reset on failure
            self.repetitions = 0
            self.interval_days = 1

        # Update easiness factor (min 1.3)
        self.easiness = max(
            1.3,
            self.easiness + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02),
        )

        self.last_reviewed_at = datetime.now().isoformat()
        self.next_review_at = (
            datetime.now() + timedelta(days=self.interval_days)
        ).isoformat()


class ForgettingCurve:
    """Manages SM-2 scheduling for a user's mistake entries."""

    def __init__(self, user_id: str) -> None:
        user_dir = _safe_user_dir(_LONG_TERM_DIR, user_id)
        self.user_id = user_id
        self._path = user_dir / "forgetting.json"
        self._items: Dict[str, SM2Item] = self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> Dict[str, SM2Item]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return {k: SM2Item(**v) for k, v in raw.items()}
        except Exception as exc:
            logger.error("Failed to load forgetting curve for %s: %s", self.user_id, exc)
            return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v.model_dump() for k, v in self._items.items()}
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, item_id: str) -> SM2Item:
        """Register a new item (e.g. a newly added mistake).

        If it already exists, the existing state is returned unchanged.
        """
        if item_id not in self._items:
            self._items[item_id] = SM2Item(item_id=item_id)
            self._save()
        return self._items[item_id]

    def record_review(self, item_id: str, quality: int) -> SM2Item:
        """Record a review result and update the schedule.

        Args:
            item_id: The mistake/item ID.
            quality: Recall quality from 0 (blackout) to 5 (perfect).

        Returns:
            The updated SM2Item.
        """
        item = self._items.get(item_id) or self.register(item_id)
        item.review(quality)
        self._save()
        return item

    def get_due_items(self, limit: int = 10) -> List[SM2Item]:
        """Return items that are due for review (next_review_at ≤ now)."""
        now = datetime.now().isoformat()
        due = [item for item in self._items.values() if item.next_review_at <= now]
        due.sort(key=lambda i: i.next_review_at)
        return due[:limit]

    def get_item(self, item_id: str) -> Optional[SM2Item]:
        return self._items.get(item_id)

    @property
    def total_items(self) -> int:
        return len(self._items)
