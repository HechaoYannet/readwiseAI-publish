"""Tests for the admin CLI."""
from __future__ import annotations
import pytest
import sys
from pathlib import Path

# Ensure the project root is on sys.path so admin_cli imports work
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


class TestAdminCLI:
    def _setup_tmp(self, tmp_path):
        import app.models.user as user_module
        import app.models.invite as invite_module
        import app.services.user_service as svc
        user_module._USERS_FILE = tmp_path / "users.json"
        invite_module._INVITES_FILE = tmp_path / "invites.json"
        svc._user_store = user_module.UserStore()
        svc._invite_store = invite_module.InviteStore()

    def test_build_parser(self):
        from admin import build_parser
        parser = build_parser()
        assert parser is not None

    def test_invite_create(self, tmp_path):
        self._setup_tmp(tmp_path)
        from admin_cli.commands.invite import cmd_invite_create
        import argparse
        args = argparse.Namespace(max_uses=3, note="测试", expires_at=None)
        # Should not raise
        cmd_invite_create(args)

    def test_invite_list_empty(self, tmp_path, capsys):
        self._setup_tmp(tmp_path)
        from admin_cli.commands.invite import cmd_invite_list
        import argparse
        cmd_invite_list(argparse.Namespace())
        captured = capsys.readouterr()
        assert "暂无" in captured.out

    def test_user_list_empty(self, tmp_path, capsys):
        self._setup_tmp(tmp_path)
        from admin_cli.commands.user import cmd_user_list
        import argparse
        cmd_user_list(argparse.Namespace(status=None, limit=50))
        captured = capsys.readouterr()
        assert "暂无" in captured.out

    def test_stats_command(self, tmp_path, capsys):
        self._setup_tmp(tmp_path)
        from admin_cli.commands.system import cmd_stats
        import argparse
        cmd_stats(argparse.Namespace())
        captured = capsys.readouterr()
        assert "用户总数" in captured.out

    def test_health_command(self, tmp_path, capsys):
        from admin_cli.commands.system import cmd_health
        import argparse
        cmd_health(argparse.Namespace())
        captured = capsys.readouterr()
        assert "健康状态" in captured.out
