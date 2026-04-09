"""Admin CLI: user management commands."""
from __future__ import annotations
import argparse

from admin_cli.utils import confirm, print_table


def _get_store():
    from app.models.user import UserStore
    return UserStore()


def cmd_user_list(args: argparse.Namespace) -> None:
    store = _get_store()
    users = store.get_all()
    if hasattr(args, "status") and args.status:
        users = [u for u in users if u.status == args.status]
    if hasattr(args, "limit") and args.limit:
        users = users[:args.limit]
    if not users:
        print("暂无用户")
        return
    rows = [[u.id[:8], u.username, u.exam_region, u.grade, u.status, u.created_at[:10]] for u in users]
    print_table(["ID(前8)", "用户名", "考区", "年级", "状态", "注册时间"], rows)


def cmd_user_show(args: argparse.Namespace) -> None:
    store = _get_store()
    user = store.get_by_id(args.user_id)
    if user is None:
        print(f"用户 {args.user_id} 不存在")
        return
    import json
    print(json.dumps(user.model_dump(exclude={"invite_code"}), ensure_ascii=False, indent=2))


def cmd_user_disable(args: argparse.Namespace) -> None:
    store = _get_store()
    ok = store.update(args.user_id, status="disabled")
    if ok:
        print(f"用户 {args.user_id} 已禁用")
    else:
        print(f"用户 {args.user_id} 不存在")


def cmd_user_enable(args: argparse.Namespace) -> None:
    store = _get_store()
    ok = store.update(args.user_id, status="active")
    if ok:
        print(f"用户 {args.user_id} 已启用")
    else:
        print(f"用户 {args.user_id} 不存在")


def cmd_user_delete(args: argparse.Namespace) -> None:
    if not hasattr(args, "force") or not args.force:
        if not confirm(f"确定要删除用户 {args.user_id} 吗？此操作不可逆"):
            print("已取消")
            return
    store = _get_store()
    ok = store.delete(args.user_id)
    if ok:
        print(f"用户 {args.user_id} 已删除")
    else:
        print(f"用户 {args.user_id} 不存在")


def cmd_user_update(args: argparse.Namespace) -> None:
    store = _get_store()
    updates = {}
    if args.grade:
        updates["grade"] = args.grade
    if args.school:
        updates["school"] = args.school
    if args.exam_region:
        updates["exam_region"] = args.exam_region
    if not updates:
        print("请提供要修改的字段（--grade/--school/--exam-region）")
        return
    ok = store.update(args.user_id, **updates)
    if ok:
        print(f"用户 {args.user_id} 已更新")
    else:
        print(f"用户 {args.user_id} 不存在")


def register_parser(subparsers: argparse._SubParsersAction) -> None:
    user_parser = subparsers.add_parser("user", help="用户管理")
    user_sub = user_parser.add_subparsers(dest="user_cmd")

    # list
    p_list = user_sub.add_parser("list", help="列出所有用户")
    p_list.add_argument("--limit", type=int, default=50, help="最多显示数量")
    p_list.add_argument("--status", type=str, choices=["active", "disabled"], help="按状态过滤")
    p_list.set_defaults(func=cmd_user_list)

    # show
    p_show = user_sub.add_parser("show", help="查看用户详情")
    p_show.add_argument("user_id", type=str)
    p_show.set_defaults(func=cmd_user_show)

    # disable
    p_disable = user_sub.add_parser("disable", help="禁用用户")
    p_disable.add_argument("user_id", type=str)
    p_disable.set_defaults(func=cmd_user_disable)

    # enable
    p_enable = user_sub.add_parser("enable", help="启用用户")
    p_enable.add_argument("user_id", type=str)
    p_enable.set_defaults(func=cmd_user_enable)

    # delete
    p_delete = user_sub.add_parser("delete", help="删除用户（谨慎）")
    p_delete.add_argument("user_id", type=str)
    p_delete.add_argument("--force", action="store_true", help="跳过确认")
    p_delete.set_defaults(func=cmd_user_delete)

    # update
    p_update = user_sub.add_parser("update", help="修改用户信息")
    p_update.add_argument("user_id", type=str)
    p_update.add_argument("--grade", type=str, default="", help="年级")
    p_update.add_argument("--school", type=str, default="", help="学校")
    p_update.add_argument("--exam-region", type=str, default="", dest="exam_region", help="考区")
    p_update.set_defaults(func=cmd_user_update)

    user_parser.set_defaults(func=lambda args: user_parser.print_help())
