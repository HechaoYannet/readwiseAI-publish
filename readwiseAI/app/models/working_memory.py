"""WorkingMemory – 会话级工作记忆管理.

存储当前会话的上下文信息，包括当前文章、当前题目和对话历史。
数据持久化到 data/working/sessions/{user_id}/{session_id}.json。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai.types.beta.realtime import session
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_SESSIONS_DIR = Path(__file__).parent.parent.parent / "data" / "working" / "sessions"

# Maximum conversation messages to retain (20 turns × 2 messages per turn)
_MAX_CONVERSATION_MESSAGES = 40

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
    # if not user_dir.as_posix().startswith(resolved_base.as_posix() + "/") and user_dir != resolved_base:
    #     raise ValueError(f"Path traversal detected for user_id: {user_id!r}")
    # return user_dir


class WorkingMemory(BaseModel):
    """Session-level working memory.

    Attributes:
        session_id: Unique identifier for the session.
        user_id: The user this session belongs to.
        articles: Full metadata and content of the article being studied.
        question_queue: List of questions generated for the current article.
        conversation_history: Ordered list of user/assistant message pairs.
        created_at: ISO timestamp when the session was created.
        updated_at: ISO timestamp of the most recent modification.
    """

    session_id: str
    session_type: str = "training"  # "training" or "chatting"
    user_id: str
    articles: List[Dict[str, Any]] = Field(default_factory=list)
    question_queue: List[List[Dict[str, Any]]] = Field(default_factory=list)
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    agent_information: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist this working memory to disk."""
        user_dir = _safe_user_dir(_SESSIONS_DIR, self.user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now().isoformat()
        path = user_dir / f"{self.session_id}.json"
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

        self._pop_save(self.session_id, self.user_id, self.session_type)

    @classmethod
    def _pop_save(cls, session_id: str, user_id: str, session_type: str) -> None:
        """Helper to maintain a single most recent session ID in _session.json."""

        session_list = cls.load_session_list(session_type, user_id)
        if (not session_list) or (session_list[0] != session_id):
            if session_id in session_list:
                session_list.remove(session_id)  # 删除第一个匹配项
                session_list.insert(0, session_id)  # 插入到开头
            else:
                session_list.insert(0, session_id)  # 插入到开头
        if not session_list: session_list.append(session_id)
        path: Path = _safe_user_dir(_SESSIONS_DIR, user_id)
        if session_type == "training":
            path = _safe_user_dir(_SESSIONS_DIR, user_id) / f"_session.json"
        elif session_type == "chatting":
            path = _safe_user_dir(_SESSIONS_DIR, user_id) / f"_session_chat.json"
        path.write_text(json.dumps(session_list, indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, session_id: str, user_id: str = "default") -> Optional["WorkingMemory"]:
        """Load working memory from disk.  Returns None if not found."""
        user_dir = _safe_user_dir(_SESSIONS_DIR, user_id)
        path = user_dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(**data)
        except Exception as exc:
            logger.error("Failed to load working memory %s: %s", session_id, exc)
            return None

    @classmethod
    def load_session_list(cls, session_type: str, user_id: str = "default") -> List[str]:
        """List all session IDs for a given user."""
        path: Path = _safe_user_dir(_SESSIONS_DIR, user_id)
        if session_type == "training":
            path = _safe_user_dir(_SESSIONS_DIR, user_id) / f"_session.json"
        elif session_type == "chatting":
            path = _safe_user_dir(_SESSIONS_DIR, user_id) / f"_session_chat.json"
        if not path.exists():
            return []
        try:
            session_id = json.loads(path.read_text(encoding="utf-8"))
            if session_id:
                return session_id
            return []
        except Exception as exc:
            logger.error("Failed to load session list for user %s: %s", user_id, exc)
            return []

    @classmethod
    def get_or_create(cls, session_id: str, user_id: str) -> "WorkingMemory":
        """Load existing session or create a new one."""
        existing = cls.load(session_id, user_id)
        if existing is not None:
            return existing
        wm = cls(session_id=session_id, user_id=user_id)
        wm.save()
        return wm

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def set_article(self, article: Dict[str, Any]) -> None:
        """Replace the current article and clear stale question state."""
        self.articles.append(article)
        self.question_queue = []
        self.save()

    def set_questions(self, questions: List[Dict[str, Any]]) -> None:
        """Store generated questions for the current article."""
        self.question_queue.append(questions)
        self.save()

    def add_message(self, role: str, content: str) -> None:
        """Append a message to the conversation history.

        Args:
            role: "user" or "assistant".
            content: The message text.
        """
        self.conversation_history.append({"role": role, "content": content})
        # Keep only the most recent messages; oldest are dropped first (FIFO)
        if len(self.conversation_history) > _MAX_CONVERSATION_MESSAGES:
            self.conversation_history = self.conversation_history[-_MAX_CONVERSATION_MESSAGES:]
        self.save()

    def add_agent_information(self, info: Dict[str, Any]) -> None:
        """Append a piece of agent information to the history."""
        self.agent_information.append(info)
        self.save()

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_article_content(self, index: int = -1) -> str:
        """Return the full text of an article by index, or an empty string.

        Args:
            index: List index of the article (default -1 = most recent).
        """
        if not self.articles:
            return ""
        return self.articles[index].get("content", "")

    def get_article_title(self, index: int = -1) -> str:
        """Return the title of an article by index, or a placeholder.

        Args:
            index: List index of the article (default -1 = most recent).
        """
        if not self.articles:
            return "（无当前文章）"
        return self.articles[index].get("title", "（无当前文章）")
