"""Invite code data model."""
from __future__ import annotations
import json
import logging
import random
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_INVITES_FILE = Path(__file__).parent.parent.parent / "data" / "invites" / "invites.json"


def _generate_code() -> str:
    """Generate a random 8-character alphanumeric invite code."""
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=8))


class InviteCode(BaseModel):
    code: str = Field(default_factory=_generate_code)
    created_by: str = "admin"
    max_uses: int = 1
    used_count: int = 0
    used_by: List[str] = Field(default_factory=list)
    expires_at: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    note: str = ""
    revoked: bool = False

    def is_valid(self) -> bool:
        """Return True if the code can still be used."""
        if self.revoked:
            return False
        if self.used_count >= self.max_uses:
            return False
        if self.expires_at:
            try:
                expires = datetime.fromisoformat(self.expires_at)
                now = datetime.now(timezone.utc)
                # Normalize to UTC if naive
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires < now:
                    return False
            except ValueError:
                return False
        return True


class InviteStore:
    """Simple JSON-file-backed invite code store."""

    def __init__(self) -> None:
        self._path = _INVITES_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _load_all(self) -> List[Dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to load invites: %s", exc)
            return []

    def _save_all(self, invites: List[Dict[str, Any]]) -> None:
        self._path.write_text(
            json.dumps(invites, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get_all(self) -> List[InviteCode]:
        return [InviteCode(**i) for i in self._load_all()]

    def get_by_code(self, code: str) -> Optional[InviteCode]:
        for i in self._load_all():
            if i.get("code") == code:
                return InviteCode(**i)
        return None

    def create(self, invite: InviteCode) -> InviteCode:
        invites = self._load_all()
        invites.append(invite.model_dump())
        self._save_all(invites)
        return invite

    def record_use(self, code: str, user_id: str) -> Optional[InviteCode]:
        """Increment used_count and add user_id to used_by."""
        invites = self._load_all()
        for i, inv in enumerate(invites):
            if inv.get("code") == code:
                inv["used_count"] = inv.get("used_count", 0) + 1
                used_by = inv.get("used_by", [])
                used_by.append(user_id)
                inv["used_by"] = used_by
                invites[i] = inv
                self._save_all(invites)
                return InviteCode(**inv)
        return None

    def revoke(self, code: str) -> bool:
        invites = self._load_all()
        for i, inv in enumerate(invites):
            if inv.get("code") == code:
                inv["revoked"] = True
                invites[i] = inv
                self._save_all(invites)
                return True
        return False

    def update(self, code: str, **kwargs: Any) -> Optional[InviteCode]:
        invites = self._load_all()
        for i, inv in enumerate(invites):
            if inv.get("code") == code:
                inv.update(kwargs)
                invites[i] = inv
                self._save_all(invites)
                return InviteCode(**inv)
        return None
