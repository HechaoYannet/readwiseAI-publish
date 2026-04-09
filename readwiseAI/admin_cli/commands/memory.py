"""Admin CLI: memory management commands."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from admin_cli.utils import confirm


def cmd_memory_list(args: argparse.Namespace) -> None:
    from app.models.long_term_memory import LongTermMemory
    ltm = LongTermMemory(user_id=args.user_id)
    mistakes = ltm.mistake_book.total
    forgetting_items = ltm.forgetting_curve.total_items
    power_records = len(ltm.get_power_history())
    training_records = len(ltm.get_training_records())
    print(f"用户 {args.user_id} 记忆数据:")
    print(f"  错题本: {mistakes}条")
    print(f"  遗忘曲线: {forgetting_items}个知识点")
    print(f"  战力值历史: {power_records}条记录")
    print(f"  训练记录: {training_records}条")


def cmd_memory_export(args: argparse.Namespace) -> None:
    from app.models.long_term_memory import LongTermMemory
    ltm = LongTermMemory(user_id=args.user_id)
    data = {
        "user_id": args.user_id,
        "mistakes": [e.model_dump() for e in ltm.mistake_book._entries],
        "forgetting": {k: v.model_dump() for k, v in ltm.forgetting_curve._items.items()},
        "power_history": ltm.get_power_history(),
        "training_records": ltm.get_training_records(),
    }
    output_path = Path(args.output) if args.output else Path(f"{args.user_id}_memory_export.json")
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"记忆数据已导出到: {output_path}")


def cmd_memory_import(args: argparse.Namespace) -> None:
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"文件不存在: {file_path}")
        return
    data = json.loads(file_path.read_text(encoding="utf-8"))
    from app.models.long_term_memory import LongTermMemory
    from app.models.mistakes import MistakeEntry
    from app.models.forgetting import SM2Item
    ltm = LongTermMemory(user_id=args.user_id)
    # Import mistakes
    for m in data.get("mistakes", []):
        try:
            entry = MistakeEntry(**m)
            ltm.mistake_book._entries.append(entry)
        except Exception:
            pass
    ltm.mistake_book._save()
    # Import forgetting curve
    for k, v in data.get("forgetting", {}).items():
        try:
            ltm.forgetting_curve._items[k] = SM2Item(**v)
        except Exception:
            pass
    ltm.forgetting_curve._save()
    print(f"记忆数据已导入到用户 {args.user_id}")


def cmd_memory_clear(args: argparse.Namespace) -> None:
    if not hasattr(args, "confirm_flag") or not args.confirm_flag:
        if not confirm(f"确定要清空用户 {args.user_id} 的全部记忆数据？"):
            print("已取消")
            return
    from pathlib import Path
    import shutil
    data_dir = Path(__file__).parent.parent.parent / "data" / "long_term" / args.user_id
    if data_dir.exists():
        shutil.rmtree(data_dir)
        print(f"用户 {args.user_id} 的记忆数据已清空")
    else:
        print(f"用户 {args.user_id} 暂无记忆数据")


def register_parser(subparsers: argparse._SubParsersAction) -> None:
    memory_parser = subparsers.add_parser("memory", help="记忆管理")
    memory_sub = memory_parser.add_subparsers(dest="memory_cmd")

    # list
    p_list = memory_sub.add_parser("list", help="查看用户记忆")
    p_list.add_argument("user_id", type=str)
    p_list.set_defaults(func=cmd_memory_list)

    # export
    p_export = memory_sub.add_parser("export", help="导出用户记忆")
    p_export.add_argument("user_id", type=str)
    p_export.add_argument("--output", type=str, default="", help="输出文件路径")
    p_export.set_defaults(func=cmd_memory_export)

    # import
    p_import = memory_sub.add_parser("import", help="导入用户记忆")
    p_import.add_argument("user_id", type=str)
    p_import.add_argument("--file", type=str, required=True, help="导入文件路径")
    p_import.set_defaults(func=cmd_memory_import)

    # clear
    p_clear = memory_sub.add_parser("clear", help="清空用户记忆")
    p_clear.add_argument("user_id", type=str)
    p_clear.add_argument("--confirm", action="store_true", dest="confirm_flag", help="跳过确认")
    p_clear.set_defaults(func=cmd_memory_clear)

    memory_parser.set_defaults(func=lambda args: memory_parser.print_help())
