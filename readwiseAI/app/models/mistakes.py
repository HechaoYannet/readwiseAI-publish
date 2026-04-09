"""Mistakes – 错题本模型.

每道错题以 MistakeEntry 对象存储。MistakeBook 管理单个用户的错题集合，
持久化到 data/long_term/{user_id}/mistakes.json。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

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

class MistakeEntry(BaseModel):
    """A single wrong-answer record.

    Attributes:
        mistake_id: Unique identifier (typically timestamp-based).
        question_text: The original question stem.
        options: The answer choices.
        correct_answer: The correct option letter.
        user_answer: The user's chosen option.
        article_excerpt: A snippet of the source article for context.
        error_category: Diagnosis result (e.g. 词汇理解/推理判断).
        explanation: Detailed analysis of why the answer was wrong.
        question_type: One of detail/inference/vocabulary/main_idea.
        difficulty: L1-L4.
        review_count: How many times this entry has been reviewed.
        next_review_at: ISO timestamp for next SM-2 scheduled review.
        created_at: ISO timestamp when the mistake was recorded.
    """

    mistake_id: str
    question_text: str
    options: Dict[str, str] = Field(default_factory=dict)
    correct_answer: str = ""
    user_answer: str = ""
    article_excerpt: str = ""
    error_category: str = ""
    explanation: str = ""
    question_type: str = "detail"
    difficulty: str = "L2"
    review_count: int = 0
    next_review_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class MistakeBook:
    """Manages a user's mistake history."""

    def __init__(self, user_id: str) -> None:
        user_dir = _safe_user_dir(_LONG_TERM_DIR, user_id)
        self.user_id = user_id
        self._path = user_dir / "mistakes.json"
        self._entries: List[MistakeEntry] = self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> List[MistakeEntry]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return [MistakeEntry(**item) for item in raw]
        except Exception as exc:
            logger.error("Failed to load mistake book for %s: %s", self.user_id, exc)
            return []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [e.model_dump() for e in self._entries]
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add(self, entry: MistakeEntry) -> None:
        """Add a new mistake entry and persist immediately."""
        self._entries.append(entry)
        self._save()

    def update(self, mistake_id: str, **kwargs: Any) -> bool:
        """Update fields of an existing entry by its ID.

        Returns True if the entry was found and updated.
        """
        for entry in self._entries:
            if entry.mistake_id == mistake_id:
                for key, value in kwargs.items():
                    if hasattr(entry, key):
                        setattr(entry, key, value)
                self._save()
                return True
        return False

    # ------------------------------------------------------------------
    # Read / search
    # ------------------------------------------------------------------

    def search(
        self,
        keyword: Optional[str] = None,
        error_category: Optional[str] = None,
        question_type: Optional[str] = None,
        difficulty: Optional[str] = None,
        limit: int = 5,
    ) -> List[MistakeEntry]:
        """Search the mistake book with optional filters.

        Args:
            keyword: Match against question_text or article_excerpt (case-insensitive).
            error_category: Exact match on error_category.
            question_type: Filter by question type.
            difficulty: Filter by difficulty level.
            limit: Maximum number of results.

        Returns:
            A list of matching MistakeEntry objects (most recent first).
        """
        results = list(self._entries)

        if keyword:
            kw = keyword.lower()
            results = [
                e for e in results
                if kw in e.question_text.lower() or kw in e.article_excerpt.lower()
            ]
        if error_category:
            results = [e for e in results if e.error_category == error_category]
        if question_type:
            results = [e for e in results if e.question_type == question_type]
        if difficulty:
            results = [e for e in results if e.difficulty == difficulty]

        # Most recent first
        results.sort(key=lambda e: e.created_at, reverse=True)
        return results[:limit]

    def get_due_for_review(self, limit: int = 5) -> List[MistakeEntry]:
        """Return entries whose next_review_at is in the past or now."""
        now = datetime.now().isoformat()
        due = [e for e in self._entries if e.next_review_at <= now]
        due.sort(key=lambda e: e.next_review_at)
        return due[:limit]

    def format_for_prompt(self, entries: List[MistakeEntry]) -> str:
        """Format a list of entries into a readable string for LLM prompts."""
        if not entries:
            return "（暂无相关错题记录）"
        lines = []
        for e in entries:
            lines.append(
                f"- 【{e.error_category}】{e.question_text} "
                f"（错误答案: {e.user_answer}, 正确答案: {e.correct_answer}）"
                f" — {e.explanation[:80]}..."
            )
        return "\n".join(lines)

    def delete(self, mistake_id: str) -> bool:
        """Remove an entry by its ID.

        Returns True if the entry was found and removed.
        """
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.mistake_id != mistake_id]
        if len(self._entries) < before:
            self._save()
            return True
        return False

    @property
    def total(self) -> int:
        return len(self._entries)
