"""LongTermMemory – 用户级长期记忆管理.

聚合一个用户所有长期记忆相关模型：错题本、遗忘曲线、战力值历史和训练记录。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.models.forgetting import ForgettingCurve
from app.models.mistakes import MistakeBook, MistakeEntry

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




class LongTermMemory:
    """Aggregates all long-term memory stores for a single user.

    Attributes:
        user_id: The user this memory belongs to.
        mistake_book: Persistent mistake history.
        forgetting_curve: SM-2 scheduling state.
    """

    def __init__(self, user_id: str) -> None:
        self._dir = _safe_user_dir(_LONG_TERM_DIR, user_id)
        self.user_id = user_id
        self._dir.mkdir(parents=True, exist_ok=True)

        self.mistake_book = MistakeBook(user_id)
        self.forgetting_curve = ForgettingCurve(user_id)

    # ------------------------------------------------------------------
    # Power history
    # ------------------------------------------------------------------

    @property
    def _power_path(self) -> Path:
        return self._dir / "power_history.json"

    def get_power_history(self) -> List[Dict[str, Any]]:
        """Load the user's power (战力值) history."""
        if not self._power_path.exists():
            return []
        try:
            return json.loads(self._power_path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def append_power_record(self, score: float, reason: str = "") -> None:
        """Add a new power score entry.

        Args:
            score: The new power score value.
            reason: Optional description of what drove the change.
        """
        history = self.get_power_history()
        history.append({
            "score": score,
            "reason": reason,
            "recorded_at": datetime.now().isoformat(),
        })
        self._power_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # Training records
    # ------------------------------------------------------------------

    @property
    def _training_path(self) -> Path:
        return self._dir / "training.json"

    def get_training_records(self) -> List[Dict[str, Any]]:
        if not self._training_path.exists():
            return []
        try:
            return json.loads(self._training_path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def append_training_record(self, record: Dict[str, Any]) -> None:
        """Add a training session record.

        Args:
            record: Arbitrary dict describing the training session.
        """
        records = self.get_training_records()
        record.setdefault("recorded_at", datetime.now().isoformat())
        records.append(record)
        self._training_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # Convenience: add mistake and schedule review
    # ------------------------------------------------------------------

    def record_mistake(self, entry: MistakeEntry) -> None:
        """Add a mistake to the mistake book and register it with the forgetting curve.

        Args:
            entry: The MistakeEntry to record.
        """
        self.mistake_book.add(entry)
        self.forgetting_curve.register(entry.mistake_id)

    # ------------------------------------------------------------------
    # Search helper for QA agent
    # ------------------------------------------------------------------

    def search_mistakes_formatted(
        self,
        keyword: Optional[str] = None,
        error_category: Optional[str] = None,
        question_type: Optional[str] = None,
        limit: int = 5,
    ) -> str:
        """Search mistakes and return a formatted string for LLM consumption.

        Args:
            keyword: Search term.
            error_category: Filter by error type.
            question_type: Filter by question type.
            limit: Maximum results.

        Returns:
            Human-readable summary of matching mistakes.
        """
        entries = self.mistake_book.search(
            keyword=keyword,
            error_category=error_category,
            question_type=question_type,
            limit=limit,
        )
        return self.mistake_book.format_for_prompt(entries)
