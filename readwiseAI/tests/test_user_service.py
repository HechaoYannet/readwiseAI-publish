"""Additional tests for user service layer."""
from __future__ import annotations
import pytest


class TestInviteStore:
    def _setup_tmp(self, tmp_path):
        import app.models.invite as invite_module
        invite_module._INVITES_FILE = tmp_path / "invites.json"
        from app.models.invite import InviteStore
        return InviteStore()

    def test_create_and_get(self, tmp_path):
        store = self._setup_tmp(tmp_path)
        from app.models.invite import InviteCode
        inv = InviteCode(max_uses=3, note="batch1")
        store.create(inv)
        found = store.get_by_code(inv.code)
        assert found is not None
        assert found.note == "batch1"

    def test_revoke(self, tmp_path):
        store = self._setup_tmp(tmp_path)
        from app.models.invite import InviteCode
        inv = InviteCode()
        store.create(inv)
        store.revoke(inv.code)
        found = store.get_by_code(inv.code)
        assert found.revoked is True
        assert not found.is_valid()

    def test_record_use(self, tmp_path):
        store = self._setup_tmp(tmp_path)
        from app.models.invite import InviteCode
        inv = InviteCode(max_uses=2)
        store.create(inv)
        store.record_use(inv.code, "user_001")
        found = store.get_by_code(inv.code)
        assert found.used_count == 1
        assert "user_001" in found.used_by
        assert found.is_valid()  # still 1 use left

        store.record_use(inv.code, "user_002")
        found = store.get_by_code(inv.code)
        assert not found.is_valid()  # max_uses=2 reached


class TestUserStore:
    def _setup_tmp(self, tmp_path):
        import app.models.user as user_module
        user_module._USERS_FILE = tmp_path / "users.json"
        from app.models.user import UserStore
        return UserStore()

    def test_create_and_get(self, tmp_path):
        store = self._setup_tmp(tmp_path)
        from app.models.user import User
        user = User(username="测试用户", invite_code="TEST1234", exam_region="全国I卷")
        store.create(user)
        found = store.get_by_id(user.id)
        assert found is not None
        assert found.username == "测试用户"

    def test_get_by_username(self, tmp_path):
        store = self._setup_tmp(tmp_path)
        from app.models.user import User
        user = User(username="查找测试", invite_code="TEST5678", exam_region="北京")
        store.create(user)
        found = store.get_by_username("查找测试")
        assert found is not None

    def test_update(self, tmp_path):
        store = self._setup_tmp(tmp_path)
        from app.models.user import User
        user = User(username="更新测试", invite_code="UPD12345", exam_region="上海")
        store.create(user)
        updated = store.update(user.id, grade="高三")
        assert updated is not None
        assert updated.grade == "高三"

    def test_delete(self, tmp_path):
        store = self._setup_tmp(tmp_path)
        from app.models.user import User
        user = User(username="删除测试", invite_code="DEL12345", exam_region="广东")
        store.create(user)
        ok = store.delete(user.id)
        assert ok
        assert store.get_by_id(user.id) is None
