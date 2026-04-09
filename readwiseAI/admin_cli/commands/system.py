"""Admin CLI: system management commands."""
from __future__ import annotations
import argparse
import json
import zipfile
from datetime import datetime
from pathlib import Path


def cmd_stats(args: argparse.Namespace) -> None:
    """Show system statistics."""
    from app.models.user import UserStore
    from app.models.invite import InviteStore
    users = UserStore().get_all()
    invites = InviteStore().get_all()
    active_users = [u for u in users if u.status == "active"]
    valid_invites = [i for i in invites if i.is_valid()]
    print("=== ReadWise AI 系统统计 ===")
    print(f"用户总数:    {len(users)}")
    print(f"  活跃用户:  {len(active_users)}")
    print(f"  禁用用户:  {len(users) - len(active_users)}")
    print(f"邀请码总数:  {len(invites)}")
    print(f"  可用邀请码: {len(valid_invites)}")

    data_dir = Path(__file__).parent.parent.parent / "data"
    results_dir = data_dir / "results"
    result_count = len(list(results_dir.glob("*.json"))) if results_dir.exists() else 0
    print(f"结果文件数:  {result_count}")


def cmd_backup(args: argparse.Namespace) -> None:
    """Backup all data to a zip file."""
    data_dir = Path(__file__).parent.parent.parent / "data"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = args.output or f"backup_{timestamp}.zip"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in data_dir.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(data_dir.parent))
    print(f"数据已备份到: {output}")


def cmd_health(args: argparse.Namespace) -> None:
    """Health check."""
    data_dir = Path(__file__).parent.parent.parent / "data"
    checks = {
        "data/prompts/": (data_dir / "prompts").exists(),
        "data/corpus/": (data_dir / "corpus").exists(),
        "data/users/": (data_dir / "users").exists(),
        "data/invites/": (data_dir / "invites").exists(),
    }
    all_ok = True
    for name, ok in checks.items():
        status = "✅" if ok else "❌"
        print(f"  {status} {name}")
        if not ok:
            all_ok = False
    if all_ok:
        print("系统健康状态: 正常")
    else:
        print("系统健康状态: 有问题，请检查上述路径")


def register_parser(subparsers: argparse._SubParsersAction) -> None:
    # stats
    p_stats = subparsers.add_parser("stats", help="系统统计")
    p_stats.set_defaults(func=cmd_stats)

    # backup
    p_backup = subparsers.add_parser("backup", help="备份所有数据")
    p_backup.add_argument("--output", type=str, default="", help="输出zip文件路径")
    p_backup.set_defaults(func=cmd_backup)

    # health
    p_health = subparsers.add_parser("health", help="健康检查")
    p_health.set_defaults(func=cmd_health)
