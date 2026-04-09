#!/usr/bin/env python3
"""ReadWise AI - 管理员命令行工具.

用法:
  python admin.py invite create --max-uses 5 --note "内测"
  python admin.py user list
  python admin.py memory list <user_id>
  python admin.py stats
  python admin.py health
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path so 'app' and 'admin_cli' imports work.
_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from admin_cli.commands import invite, user, memory, system


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python admin.py",
        description="ReadWise AI 管理员命令行工具",
    )
    subparsers = parser.add_subparsers(dest="command")
    invite.register_parser(subparsers)
    user.register_parser(subparsers)
    memory.register_parser(subparsers)
    system.register_parser(subparsers)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
