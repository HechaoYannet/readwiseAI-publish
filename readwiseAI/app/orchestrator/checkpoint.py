"""Checkpoint Manager – persists OrchestratorState to the local filesystem."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from app.models.state import OrchestratorState

logger = logging.getLogger(__name__)

# Base directory for per-user data (checkpoints + results).
BASE_DIR = Path("data/users")
# Flat index: request_id → user_id mapping, kept for ownership lookups.
INDEX_DIR = Path("data/request_index")

# Validate user IDs to prevent path traversal – same pattern as mistakes.py.
_USER_ID_PATTERN = re.compile(r"^[\w\-]+$")


def _safe_user_dir(base_dir: Path, user_id: str) -> Path:
    """Return *base_dir/user_id* after validating against path traversal."""
    if not _USER_ID_PATTERN.match(user_id):
        raise ValueError(f"Invalid user_id: {user_id!r}")
    resolved_base = base_dir.resolve()
    user_dir = (base_dir / user_id).resolve()
    user_dir.relative_to(resolved_base)  # raises ValueError if outside base
    return user_dir


class CheckpointManager:
    def __init__(
        self,
        base_dir: Path = BASE_DIR,
        index_dir: Path = INDEX_DIR,
    ):
        self.base_dir = base_dir
        self.index_dir = index_dir
        self.index_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _checkpoint_dir(self, user_id: str) -> Path:
        d = _safe_user_dir(self.base_dir, user_id) / "checkpoints"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _results_dir(self, user_id: str) -> Path:
        d = _safe_user_dir(self.base_dir, user_id) / "results"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _index_path(self, request_id: str) -> Path:
        return self.index_dir / request_id

    def lookup_user_id(self, request_id: str) -> Optional[str]:
        """Return the user_id that owns *request_id*, or None if unknown."""
        p = self._index_path(request_id)
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8").strip()

    def _write_index(self, request_id: str, user_id: str) -> None:
        self._index_path(request_id).write_text(user_id, encoding="utf-8")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, state: OrchestratorState) -> None:
        """Persist state as JSON under the user's checkpoint directory."""
        path = self._checkpoint_dir(state.user_id) / f"{state.request_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
        self._write_index(state.request_id, state.user_id)
        logger.debug("Checkpoint saved for %s (user %s)", state.request_id, state.user_id)

    def load(self, request_id: str) -> Optional[OrchestratorState]:
        """Load state from JSON; returns None if not found."""
        user_id = self.lookup_user_id(request_id)
        if user_id is None:
            return None
        path = _safe_user_dir(self.base_dir, user_id) / "checkpoints" / f"{request_id}.json"
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return OrchestratorState(**data)

    def delete(self, request_id: str) -> None:
        """Remove checkpoint file after completion.

        The index entry is intentionally kept so that ownership can still be
        verified when the client polls for the final result.
        """
        user_id = self.lookup_user_id(request_id)
        if user_id is None:
            return
        path = _safe_user_dir(self.base_dir, user_id) / "checkpoints" / f"{request_id}.json"
        if path.exists():
            path.unlink()

    def save_result(self, request_id: str, user_id: str, result: dict) -> None:
        """Persist final result under the user's results directory."""
        path = self._results_dir(user_id) / f"{request_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    def load_result(self, request_id: str, user_id: str) -> Optional[dict]:
        """Load cached final result for the given user."""
        path = _safe_user_dir(self.base_dir, user_id) / "results" / f"{request_id}.json"
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)


# Singleton
_checkpoint_manager: Optional[CheckpointManager] = None


def get_checkpoint_manager() -> CheckpointManager:
    global _checkpoint_manager
    if _checkpoint_manager is None:
        _checkpoint_manager = CheckpointManager()
    return _checkpoint_manager
