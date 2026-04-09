"""User data model."""
from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_USERS_FILE = Path(__file__).parent.parent.parent / "data" / "users" / "users.json"


class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"


class UserStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: str
    password_hash: str = ""
    phone: str = ""
    email: str = ""
    invite_code: str
    exam_region: str
    grade: str = ""
    school: str = ""
    role: UserRole = UserRole.USER
    status: UserStatus = UserStatus.ACTIVE
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_login_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_login_ip: str = ""


class UserStore:
    """Simple JSON-file-backed user store."""

    def __init__(self) -> None:
        self._path = _USERS_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _load_all(self) -> List[Dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to load users: %s", exc)
            return []

    def _save_all(self, users: List[Dict[str, Any]]) -> None:
        self._path.write_text(
            json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get_all(self) -> List[User]:
        return [User(**u) for u in self._load_all()]

    def get_by_id(self, user_id: str) -> Optional[User]:
        for u in self._load_all():
            if u.get("id") == user_id:
                return User(**u)
        return None

    def get_by_username(self, username: str) -> Optional[User]:
        for u in self._load_all():
            if u.get("username") == username:
                return User(**u)
        return None

    def get_by_phone(self, phone: str) -> Optional[User]:
        if not phone:
            return None
        for u in self._load_all():
            if u.get("phone") == phone:
                return User(**u)
        return None

    def get_by_email(self, email: str) -> Optional[User]:
        if not email:
            return None
        for u in self._load_all():
            if u.get("email") == email:
                return User(**u)
        return None

    def create(self, user: User) -> User:
        users = self._load_all()
        users.append(user.model_dump())
        self._save_all(users)
        return user

    def update(self, user_id: str, **kwargs: Any) -> Optional[User]:
        users = self._load_all()
        for i, u in enumerate(users):
            if u.get("id") == user_id:
                u.update(kwargs)
                users[i] = u
                self._save_all(users)
                return User(**u)
        return None

    def delete(self, user_id: str) -> bool:
        users = self._load_all()
        new_users = [u for u in users if u.get("id") != user_id]
        if len(new_users) == len(users):
            return False
        self._save_all(new_users)
        return True
