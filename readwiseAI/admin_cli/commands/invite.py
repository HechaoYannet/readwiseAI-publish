"""Admin CLI: invite code management commands."""
from __future__ import annotations
import argparse
from typing import List

from admin_cli.utils import print_table


def _get_store():
    from app.models.invite import InviteStore
    return InviteStore()


def cmd_invite_create(args: argparse.Namespace) -> None:
    from app.models.invite import InviteCode
    store = _get_store()
    invite = InviteCode(
        max_uses=args.max_uses,
        note=args.note or "",
        expires_at=args.expires_at or None,
        created_by="admin",
    )
    store.create(invite)
    print(f"邀请码已生成: {invite.code}")
    if invite.note:
        print(f"  备注: {invite.note}")
    print(f"  最大使用次数: {invite.max_uses}")


def cmd_invite_list(args: argparse.Namespace) -> None:
    store = _get_store()
    invites = store.get_all()
    if not invites:
        print("暂无邀请码")
        return
    rows = []
    for inv in invites:
        status = "已撤销" if inv.revoked else ("有效" if inv.is_valid() else "已用完")
        rows.append([inv.code, status, f"{inv.used_count}/{inv.max_uses}", inv.note, inv.created_at[:10]])
    print_table(["邀请码", "状态", "使用量", "备注", "创建时间"], rows)


def cmd_invite_show(args: argparse.Namespace) -> None:
    store = _get_store()
    inv = store.get_by_code(args.code)
    if inv is None:
        print(f"邀请码 {args.code} 不存在")
        return
    import json
    print(json.dumps(inv.model_dump(), ensure_ascii=False, indent=2))


def cmd_invite_revoke(args: argparse.Namespace) -> None:
    store = _get_store()
    ok = store.revoke(args.code)
    if ok:
        print(f"邀请码 {args.code} 已撤销")
    else:
        print(f"邀请码 {args.code} 不存在")


def register_parser(subparsers: argparse._SubParsersAction) -> None:
    invite_parser = subparsers.add_parser("invite", help="邀请码管理")
    invite_sub = invite_parser.add_subparsers(dest="invite_cmd")

    # create
    p_create = invite_sub.add_parser("create", help="生成邀请码")
    p_create.add_argument("--max-uses", type=int, default=1, help="最大使用次数")
    p_create.add_argument("--note", type=str, default="", help="备注")
    p_create.add_argument("--expires-at", type=str, default=None, help="过期时间 (ISO格式)")
    p_create.set_defaults(func=cmd_invite_create)

    # list
    p_list = invite_sub.add_parser("list", help="列出所有邀请码")
    p_list.set_defaults(func=cmd_invite_list)

    # show
    p_show = invite_sub.add_parser("show", help="查看邀请码详情")
    p_show.add_argument("code", type=str, help="邀请码")
    p_show.set_defaults(func=cmd_invite_show)

    # revoke
    p_revoke = invite_sub.add_parser("revoke", help="撤销邀请码")
    p_revoke.add_argument("code", type=str, help="邀请码")
    p_revoke.set_defaults(func=cmd_invite_revoke)

    invite_parser.set_defaults(func=lambda args: invite_parser.print_help())
