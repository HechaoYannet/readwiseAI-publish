"""Tests for JWT auth and invite code flow."""
from __future__ import annotations
import pytest
import jwt as pyjwt


# ===================================================================
# JWT Handler
# ===================================================================

class TestJWTHandler:
    def test_create_and_decode(self):
        from app.auth.jwt_handler import create_access_token, decode_token
        token = create_access_token("user_123", role="user")
        payload = decode_token(token)
        assert payload["sub"] == "user_123"
        assert payload["role"] == "user"

    def test_expired_token_raises(self):
        from app.auth.jwt_handler import _SECRET_KEY, _ALGORITHM
        from datetime import datetime, timezone, timedelta
        expired_payload = {
            "sub": "user_expired",
            "role": "user",
            "iat": datetime.now(timezone.utc) - timedelta(days=10),
            "exp": datetime.now(timezone.utc) - timedelta(days=1),
        }
        token = pyjwt.encode(expired_payload, _SECRET_KEY, algorithm=_ALGORITHM)
        with pytest.raises(pyjwt.ExpiredSignatureError):
            from app.auth.jwt_handler import decode_token
            decode_token(token)

    def test_invalid_token_raises(self):
        from app.auth.jwt_handler import decode_token
        with pytest.raises(pyjwt.PyJWTError):
            decode_token("invalid.token.here")

    def test_should_refresh_far_future(self):
        from app.auth.jwt_handler import create_access_token, should_refresh
        token = create_access_token("u1")
        assert should_refresh(token) is False

    def test_should_refresh_near_expiry(self):
        from app.auth.jwt_handler import _SECRET_KEY, _ALGORITHM, should_refresh
        from datetime import datetime, timezone, timedelta
        payload = {
            "sub": "u1",
            "role": "user",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=12),
        }
        token = pyjwt.encode(payload, _SECRET_KEY, algorithm=_ALGORITHM)
        assert should_refresh(token) is True


# ===================================================================
# User Service - register and verify invite
# ===================================================================

class TestUserService:
    def setup_method(self):
        """Point stores to tmp paths before each test."""
        import app.models.user as user_module
        import app.models.invite as invite_module
        self._orig_users_file = user_module._USERS_FILE
        self._orig_invites_file = invite_module._INVITES_FILE

    def teardown_method(self):
        import app.models.user as user_module
        import app.models.invite as invite_module
        user_module._USERS_FILE = self._orig_users_file
        invite_module._INVITES_FILE = self._orig_invites_file
        # Reset singletons in user_service
        import app.services.user_service as svc
        svc._user_store = user_module.UserStore()
        svc._invite_store = invite_module.InviteStore()

    def _setup_tmp(self, tmp_path):
        import app.models.user as user_module
        import app.models.invite as invite_module
        import app.services.user_service as svc
        user_module._USERS_FILE = tmp_path / "users.json"
        invite_module._INVITES_FILE = tmp_path / "invites.json"
        svc._user_store = user_module.UserStore()
        svc._invite_store = invite_module.InviteStore()

    def test_verify_nonexistent_invite(self, tmp_path):
        self._setup_tmp(tmp_path)
        from app.services.user_service import verify_invite_code
        valid, msg = verify_invite_code("BADCODE1")
        assert not valid
        assert "不存在" in msg

    def test_register_with_valid_invite(self, tmp_path):
        self._setup_tmp(tmp_path)
        from app.services.user_service import create_invite, register_user, verify_invite_code
        invite = create_invite(max_uses=2, note="test")
        valid, msg = verify_invite_code(invite.code)
        assert valid

        user, err = register_user(
            invite_code=invite.code,
            username="张三",
            exam_region="全国I卷",
            password="password123",
            confirm_password="password123",
        )
        assert user is not None
        assert err == ""
        assert user.username == "张三"

    def test_register_with_used_up_invite(self, tmp_path):
        self._setup_tmp(tmp_path)
        from app.services.user_service import create_invite, register_user
        invite = create_invite(max_uses=1)
        # First use
        register_user(invite.code, "用户A", "全国I卷", "password123", "password123")
        # Second use should fail
        user, err = register_user(invite.code, "用户B", "全国I卷", "password123", "password123")
        assert user is None
        assert "次数" in err or "撤销" in err or err != ""

    def test_register_duplicate_username(self, tmp_path):
        self._setup_tmp(tmp_path)
        from app.services.user_service import create_invite, register_user
        invite1 = create_invite(max_uses=5)
        register_user(invite1.code, "重复用户", "全国I卷", "password123", "password123")
        user2, err = register_user(invite1.code, "重复用户", "全国I卷", "password123", "password123")
        assert user2 is None
        assert "用户名" in err

    def test_get_user(self, tmp_path):
        self._setup_tmp(tmp_path)
        from app.services.user_service import create_invite, register_user, get_user
        invite = create_invite(max_uses=1)
        user, _ = register_user(invite.code, "李四", "北京", "password123", "password123")
        found = get_user(user.id)
        assert found is not None
        assert found.username == "李四"

    def test_update_user(self, tmp_path):
        self._setup_tmp(tmp_path)
        from app.services.user_service import create_invite, register_user, update_user
        invite = create_invite(max_uses=1)
        user, _ = register_user(invite.code, "王五", "上海", "password123", "password123")
        updated = update_user(user.id, grade="高三", school="示范中学")
        assert updated is not None
        assert updated.grade == "高三"
        assert updated.school == "示范中学"


# ===================================================================
# Password utilities
# ===================================================================

class TestPassword:
    def test_hash_and_verify(self):
        from app.auth.password import hash_password, verify_password
        hashed = hash_password("secret123")
        assert hashed != "secret123"
        assert verify_password("secret123", hashed)

    def test_wrong_password_fails(self):
        from app.auth.password import hash_password, verify_password
        hashed = hash_password("correct")
        assert not verify_password("wrong", hashed)


# ===================================================================
# Password validation in register_user
# ===================================================================

class TestPasswordValidation:
    def setup_method(self):
        import app.models.user as user_module
        import app.models.invite as invite_module
        self._orig_users_file = user_module._USERS_FILE
        self._orig_invites_file = invite_module._INVITES_FILE

    def teardown_method(self):
        import app.models.user as user_module
        import app.models.invite as invite_module
        user_module._USERS_FILE = self._orig_users_file
        invite_module._INVITES_FILE = self._orig_invites_file
        import app.services.user_service as svc
        svc._user_store = user_module.UserStore()
        svc._invite_store = invite_module.InviteStore()

    def _setup_tmp(self, tmp_path):
        import app.models.user as user_module
        import app.models.invite as invite_module
        import app.services.user_service as svc
        user_module._USERS_FILE = tmp_path / "users.json"
        invite_module._INVITES_FILE = tmp_path / "invites.json"
        svc._user_store = user_module.UserStore()
        svc._invite_store = invite_module.InviteStore()

    def test_password_too_short(self, tmp_path):
        self._setup_tmp(tmp_path)
        from app.services.user_service import create_invite, register_user
        invite = create_invite(max_uses=1)
        user, err = register_user(invite.code, "测试", "全国", "short", "short")
        assert user is None
        assert "长度" in err or "密码" in err

    def test_passwords_mismatch(self, tmp_path):
        self._setup_tmp(tmp_path)
        from app.services.user_service import create_invite, register_user
        invite = create_invite(max_uses=1)
        user, err = register_user(invite.code, "测试", "全国", "password123", "password456")
        assert user is None
        assert "不一致" in err

    def test_register_stores_password_hash(self, tmp_path):
        self._setup_tmp(tmp_path)
        from app.services.user_service import create_invite, register_user, get_user
        invite = create_invite(max_uses=1)
        user, err = register_user(invite.code, "哈希测试", "全国I卷", "password123", "password123")
        assert user is not None and err == ""
        assert user.password_hash != ""
        assert user.password_hash != "password123"


# ===================================================================
# Login
# ===================================================================

class TestLoginUser:
    def setup_method(self):
        import app.models.user as user_module
        import app.models.invite as invite_module
        self._orig_users_file = user_module._USERS_FILE
        self._orig_invites_file = invite_module._INVITES_FILE

    def teardown_method(self):
        import app.models.user as user_module
        import app.models.invite as invite_module
        user_module._USERS_FILE = self._orig_users_file
        invite_module._INVITES_FILE = self._orig_invites_file
        import app.services.user_service as svc
        svc._user_store = user_module.UserStore()
        svc._invite_store = invite_module.InviteStore()

    def _setup_tmp(self, tmp_path):
        import app.models.user as user_module
        import app.models.invite as invite_module
        import app.services.user_service as svc
        user_module._USERS_FILE = tmp_path / "users.json"
        invite_module._INVITES_FILE = tmp_path / "invites.json"
        svc._user_store = user_module.UserStore()
        svc._invite_store = invite_module.InviteStore()

    def test_login_success(self, tmp_path):
        self._setup_tmp(tmp_path)
        from app.services.user_service import create_invite, register_user, login_user
        invite = create_invite(max_uses=1)
        register_user(invite.code, "登录用户", "全国I卷", "password123", "password123")
        user, err = login_user("登录用户", "password123")
        assert user is not None
        assert err == ""
        assert user.username == "登录用户"

    def test_login_wrong_password(self, tmp_path):
        self._setup_tmp(tmp_path)
        from app.services.user_service import create_invite, register_user, login_user
        invite = create_invite(max_uses=1)
        register_user(invite.code, "密码错误", "全国I卷", "password123", "password123")
        user, err = login_user("密码错误", "wrongpassword")
        assert user is None
        assert "密码" in err

    def test_login_nonexistent_user(self, tmp_path):
        self._setup_tmp(tmp_path)
        from app.services.user_service import login_user
        user, err = login_user("不存在的用户", "password123")
        assert user is None
        assert err != ""


# ===================================================================
# Change password
# ===================================================================

class TestChangePassword:
    def setup_method(self):
        import app.models.user as user_module
        import app.models.invite as invite_module
        self._orig_users_file = user_module._USERS_FILE
        self._orig_invites_file = invite_module._INVITES_FILE

    def teardown_method(self):
        import app.models.user as user_module
        import app.models.invite as invite_module
        user_module._USERS_FILE = self._orig_users_file
        invite_module._INVITES_FILE = self._orig_invites_file
        import app.services.user_service as svc
        svc._user_store = user_module.UserStore()
        svc._invite_store = invite_module.InviteStore()

    def _setup_tmp(self, tmp_path):
        import app.models.user as user_module
        import app.models.invite as invite_module
        import app.services.user_service as svc
        user_module._USERS_FILE = tmp_path / "users.json"
        invite_module._INVITES_FILE = tmp_path / "invites.json"
        svc._user_store = user_module.UserStore()
        svc._invite_store = invite_module.InviteStore()

    def test_change_password_success(self, tmp_path):
        self._setup_tmp(tmp_path)
        from app.services.user_service import create_invite, register_user, change_password, login_user
        invite = create_invite(max_uses=1)
        user, _ = register_user(invite.code, "改密用户", "全国I卷", "oldPass12", "oldPass12")
        ok, err, _ = change_password(user.id, "oldPass12", "newPass12", "newPass12")
        assert ok, err
        # New password works
        logged, _ = login_user("改密用户", "newPass12")
        assert logged is not None
        # Old password no longer works
        logged2, _ = login_user("改密用户", "oldPass12")
        assert logged2 is None

    def test_change_password_wrong_old(self, tmp_path):
        self._setup_tmp(tmp_path)
        from app.services.user_service import create_invite, register_user, change_password
        invite = create_invite(max_uses=1)
        user, _ = register_user(invite.code, "改密2", "全国I卷", "oldPass12", "oldPass12")
        ok, err, _ = change_password(user.id, "wrongOld12", "newPass12", "newPass12")
        assert not ok
        assert "旧密码" in err

    def test_change_password_mismatch(self, tmp_path):
        self._setup_tmp(tmp_path)
        from app.services.user_service import create_invite, register_user, change_password
        invite = create_invite(max_uses=1)
        user, _ = register_user(invite.code, "改密3", "全国I卷", "oldPass12", "oldPass12")
        ok, err, _ = change_password(user.id, "oldPass12", "newPass12", "newPass99")
        assert not ok
        assert "不一致" in err
