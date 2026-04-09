"""import_corpus.py – 语料导入脚本.

将原始高考真题/模拟题转换为规范的 Markdown 格式并更新语料库索引。

用法:
    # 导入单个文件
    python -m app.scripts.import_corpus --input path/to/raw_article.json

    # 批量导入目录下所有JSON文件
    python -m app.scripts.import_corpus --input-dir path/to/json/directory

    # 批量导入并重建索引（清空现有数据）
    python -m app.scripts.import_corpus --input-dir path/to/json/directory --rebuild

原始JSON格式示例:
{
  "id": "gk_2023_002",
  "source": "2023全国II卷",
  "topic": "人工智能与社会发展",
  "type": "真题",
  "difficulty": "L3",
  "genre": "expository",
  "word_count": 310,
  "title": "B",
  "content": "Article body text...",
  "questions": [...],
  "vocabulary": [...],
  "complex_sentences": [...]
}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

_ROOT = Path(__file__).parent.parent.parent
_CORPUS_DIR = _ROOT / "data" / "corpus"
_ARTICLES_DIR = _CORPUS_DIR / "articles"
_INDEX_PATH = _CORPUS_DIR / "index.json"

_QUESTION_TYPE_NAMES = {
    "detail": "细节题",
    "inference": "推理题",
    "vocabulary": "词义题",
    "main_idea": "主旨题",
}

# 在文件开头的常量定义区域，添加 SECTION 验证
_VALID_SECTIONS = {"A", "B", "C", "D"}


def _load_index() -> Dict[str, Any]:
    """Load the corpus index, initializing all necessary indexes if missing."""
    if not _INDEX_PATH.exists():
        return {
            "articles": {},
            "indexes": {
                "by_difficulty": {"L1": [], "L2": [], "L3": [], "L4": []},
                "by_genre": {"argumentative": [], "expository": [], "narrative": []},
                "by_type": {"真题": [], "模拟题": []},
                "by_section": {"A": [], "B": [], "C": [], "D": []},
                "by_topic": {},  # Dynamic topic index
            },
            "metadata": {
                "last_updated": None,
                "total_articles": 0,
                "version": "1.0"
            }
        }
    return json.loads(_INDEX_PATH.read_text(encoding="utf-8"))


def _save_index(index: Dict[str, Any]) -> None:
    """Save the corpus index to disk."""
    _INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _validate_section(title: str) -> Optional[str]:
    """Extract and validate section code from title field.

    Args:
        title: The title field which should contain section code (A/B/C/D)

    Returns:
        Valid section code or None if invalid/missing
    """
    if title and title.strip() in _VALID_SECTIONS:
        return title.strip()
    return None


def _build_markdown(raw: Dict[str, Any]) -> str:
    """Convert a raw article dict to the canonical Markdown format."""
    article_id = raw["id"]
    source = raw.get("source", "未知来源")
    article_type = raw.get("type", "模拟题")
    difficulty = raw.get("difficulty", "L2")
    genre = raw.get("genre", "expository")
    word_count = raw.get("word_count", 0)

    # 修改这里：分别获取 title 和 section
    title = raw.get("title", "")  # 文章标题（实际标题文字）
    section = raw.get("section", "")  # 题号（A/B/C/D）
    topic = raw.get("topic", "")  # 主题

    content = raw.get("content", "")

    lines = [
        "---",
        f"**📚 嵌入语料: [{source} - {section}篇]**",
        f"id: {article_id}",
        f"source: {source}",
        f"type: {article_type}",
        f"difficulty: {difficulty}",
        f"genre: {genre}",
        f"word_count: {word_count}",
        f"section: {section}",  # 存储题号
        f"title: {title}",  # 存储文章标题
        f"topic: {topic}",  # 存储主题
        "---",
        "",
        f"# {title if title else 'Untitled'}",  # 使用实际标题
        "",
        "## 原文",
        "",
        content,
        "",
        "## 题目",
        "",
    ]

    for i, q in enumerate(raw.get("questions", []), 1):
        qt = q.get("question_type", "detail")
        qt_name = _QUESTION_TYPE_NAMES.get(qt, qt)
        lines += [
            f"### 题{i}",
            f"**题干**: {q.get('question_text', '')}",
            "**选项**: ",
        ]
        for opt_key, opt_val in q.get("options", {}).items():
            lines.append(f"- {opt_key}. {opt_val}")
        lines += [
            f"**答案**: {q.get('correct_answer', '')}",
            f"**类型**: {qt}（{qt_name}）",
            f"**解析**: {q.get('explanation', '')}",
            "",
        ]

    vocabulary = raw.get("vocabulary", [])
    if vocabulary:
        lines += [
            "## 生词表",
            "| 单词 | 词性 | 释义 | CEFR |",
            "|------|------|------|------|",
        ]
        for v in vocabulary:
            lines.append(
                f"| {v.get('word', '')} | {v.get('pos', '')} | {v.get('definition', '')} | {v.get('cefr', '')} |"
            )
        lines.append("")

    complex_sentences = raw.get("complex_sentences", [])
    if complex_sentences:
        lines += ["## 长难句", ""]
        for cs in complex_sentences:
            lines += [
                f"> \"{cs.get('sentence', '')}\"",
                f"**结构**: {cs.get('structure', '')}",
                f"**翻译**: {cs.get('translation', '')}",
                "",
            ]
    lines += [
        "---",
        "**📚 嵌入语料结束**",
        "---"
    ]

    return "\n".join(lines)


def _register_in_index(index: Dict[str, Any], raw: Dict[str, Any], filename: str) -> None:
    """Add or update an article entry in the corpus index."""
    article_id = raw["id"]
    difficulty = raw.get("difficulty", "L2")
    genre = raw.get("genre", "expository")
    article_type = raw.get("type", "模拟题")

    # 修改这里：分别获取 title 和 section
    title = raw.get("title", "")  # 文章标题
    section = raw.get("section", "")  # 题号（A/B/C/D）
    topic = raw.get("topic", "")

    # 验证 section 格式
    if section and section not in _VALID_SECTIONS:
        print(f"Warning: Invalid section code '{section}' for article {article_id}. "
              f"Expected A/B/C/D. Setting to None.", file=sys.stderr)
        section = None  # 或者保持原值，但不会建立索引

    metadata = {
        "id": article_id,
        "source": raw.get("source", ""),
        "type": article_type,
        "difficulty": difficulty,
        "genre": genre,
        "word_count": raw.get("word_count", 0),
        "section": section,  # 题号
        "title": title,  # 文章标题
        "topic": topic,  # 主题
    }
    index["articles"][article_id] = {"metadata": metadata, "path": filename}

    indexes = index.setdefault("indexes", {})

    # 更新难度索引
    by_diff = indexes.setdefault("by_difficulty", {})
    if article_id not in by_diff.setdefault(difficulty, []):
        by_diff[difficulty].append(article_id)

    # 更新体裁索引
    by_genre = indexes.setdefault("by_genre", {})
    if article_id not in by_genre.setdefault(genre, []):
        by_genre[genre].append(article_id)

    # 更新类型索引
    by_type = indexes.setdefault("by_type", {})
    if article_id not in by_type.setdefault(article_type, []):
        by_type[article_type].append(article_id)

    # 更新题号索引（使用 section 字段）
    if section and section in _VALID_SECTIONS:
        by_section = indexes.setdefault("by_section", {})
        if article_id not in by_section.setdefault(section, []):
            by_section[section].append(article_id)

    # 更新主题索引
    if topic:
        by_topic = indexes.setdefault("by_topic", {})
        if article_id not in by_topic.setdefault(topic, []):
            by_topic[topic].append(article_id)


def import_article(raw_path: Path, index: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """Import a single raw article JSON file into the corpus."""
    # ... 前面的代码保持不变 ...

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    article_id = raw.get("id")
    if not article_id:
        return False, f"Missing 'id' field in {raw_path.name}"

    # 修改这里：分别验证 title 和 section
    title = raw.get("title", "")
    section = raw.get("section", "")

    # 验证 section（如果提供）
    if section and section not in _VALID_SECTIONS:
        print(f"  ⚠ Warning: Section code '{section}' is not A/B/C/D in {article_id}")

    # 验证 title（可选，可以为空）
    if not title:
        print(f"  ⚠ Warning: No title provided for {article_id}")

    # 创建 articles 目录
    _ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    # 写入 Markdown 文件
    filename = f"{article_id}.md"
    md_content = _build_markdown(raw)
    md_path = _ARTICLES_DIR / filename
    md_path.write_text(md_content, encoding="utf-8")

    # 更新索引
    if index is None:
        index = _load_index()

    _register_in_index(index, raw, filename)

    # 修改返回消息
    topic = raw.get("topic", "")
    return True, f"✓ Imported {article_id} (Section: {section or 'N/A'}, Title: {title[:30] if title else 'N/A'})"


def rebuild_index_from_directory(directory: Path) -> Dict[str, Any]:
    """Rebuild the entire index from a directory of JSON files.

    Args:
        directory: Directory containing JSON article files

    Returns:
        New index dictionary
    """
    # Create fresh index
    new_index = {
        "articles": {},
        "indexes": {
            "by_difficulty": {"L1": [], "L2": [], "L3": [], "L4": []},
            "by_genre": {"argumentative": [], "expository": [], "narrative": []},
            "by_type": {"真题": [], "模拟题": []},
            "by_section": {"A": [], "B": [], "C": [], "D": []},
            "by_topic": {},
        },
        "metadata": {
            "last_updated": datetime.now().isoformat(),
            "total_articles": 0,
            "version": "1.0"
        }
    }

    # Find all JSON files
    json_files = list(directory.glob("*.json"))
    if not json_files:
        print(f"Error: No JSON files found in {directory}", file=sys.stderr)
        return new_index

    print(f"Found {len(json_files)} JSON files to process...")

    success_count = 0
    for json_file in sorted(json_files):
        try:
            raw = json.loads(json_file.read_text(encoding="utf-8"))
            article_id = raw.get("id")
            if not article_id:
                print(f"  ✗ Skipping {json_file.name}: missing 'id' field")
                continue

            # Create markdown file
            filename = f"{article_id}.md"
            md_content = _build_markdown(raw)
            md_path = _ARTICLES_DIR / filename
            md_path.write_text(md_content, encoding="utf-8")

            # Register in index
            _register_in_index(new_index, raw, filename)
            success_count += 1

            topic = raw.get("topic", "")
            section = raw.get("title", "")
            print(f"  ✓ {article_id} (Section {section}, Topic: {topic[:30] if topic else 'N/A'})")

        except Exception as e:
            print(f"  ✗ Error processing {json_file.name}: {e}")

    new_index["metadata"]["total_articles"] = success_count
    new_index["metadata"]["last_updated"] = datetime.now().isoformat()

    return new_index


def import_directory(directory: Path, rebuild: bool = False) -> None:
    """Import all JSON files from a directory.

    Args:
        directory: Path to directory containing JSON article files
        rebuild: If True, rebuild index from scratch (overwrites existing)
    """
    if not directory.exists():
        print(f"Error: Directory not found: {directory}", file=sys.stderr)
        sys.exit(1)

    if not directory.is_dir():
        print(f"Error: Not a directory: {directory}", file=sys.stderr)
        sys.exit(1)

    # Load or create index
    if rebuild:
        print("Rebuilding index from scratch...")
        index = rebuild_index_from_directory(directory)
        _save_index(index)
        print(f"\n✅ Import complete! Total articles: {index['metadata']['total_articles']}")
        print(f"   Index saved to: {_INDEX_PATH}")

        # Print statistics
        print("\n📊 Import Statistics:")
        print(f"   Total articles: {index['metadata']['total_articles']}")

        by_section = index['indexes']['by_section']
        print(f"   By section: A:{len(by_section['A'])} B:{len(by_section['B'])} "
              f"C:{len(by_section['C'])} D:{len(by_section['D'])}")

        by_type = index['indexes']['by_type']
        print(f"   By type: 真题:{len(by_type['真题'])} 模拟题:{len(by_type['模拟题'])}")

        by_topic = index['indexes']['by_topic']
        if by_topic:
            print(f"   Topics: {len(by_topic)} unique topics")
        return

    # Incremental import mode
    index = _load_index()
    json_files = list(directory.glob("*.json"))

    if not json_files:
        print(f"Error: No JSON files found in {directory}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(json_files)} JSON files to process...")
    print(f"Mode: Incremental (will update existing articles)\n")

    success_count = 0
    skip_count = 0
    error_count = 0

    for json_file in sorted(json_files):
        success, message = import_article(json_file, index)
        if success:
            print(f"  {message}")
            success_count += 1
        else:
            if "missing 'id'" in message:
                print(f"  ✗ {message}")
                error_count += 1
            else:
                print(f"  ⚠ {message}")
                skip_count += 1

    # Update metadata
    index["metadata"]["last_updated"] = datetime.now().isoformat()
    index["metadata"]["total_articles"] = len(index["articles"])

    _save_index(index)

    print(f"\n✅ Import complete!")
    print(f"   Success: {success_count}")
    print(f"   Skipped: {skip_count}")
    print(f"   Errors: {error_count}")
    print(f"   Total articles in index: {index['metadata']['total_articles']}")
    print(f"   Index saved to: {_INDEX_PATH}")


def import_single_file(input_path: Path) -> None:
    """Import a single JSON file."""
    success, message = import_article(input_path)
    if success:
        print(message)
        # Load and save to update metadata
        index = _load_index()
        index["metadata"]["last_updated"] = datetime.now().isoformat()
        index["metadata"]["total_articles"] = len(index["articles"])
        _save_index(index)
        print(f"✓ Index updated: {_INDEX_PATH}")
    else:
        print(f"Error: {message}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import corpus articles into data/corpus/",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Import single file
  python -m app.scripts.import_corpus --input data/raw/gk_2024_001.json
  
  # Import all JSON files from directory
  python -m app.scripts.import_corpus --input-dir data/raw/articles
  
  # Rebuild index from directory (clears existing data)
  python -m app.scripts.import_corpus --input-dir data/raw/articles --rebuild
        """
    )

    # Create mutually exclusive group for input sources
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", help="Path to single raw article JSON file")
    input_group.add_argument("--input-dir", help="Path to directory containing JSON files")

    parser.add_argument("--rebuild", action="store_true",
                        help="Rebuild entire index from scratch (only valid with --input-dir)")

    args = parser.parse_args()

    if args.input:
        import_single_file(Path(args.input))
    elif args.input_dir:
        if args.rebuild:
            import_directory(Path(args.input_dir), rebuild=True)
        else:
            import_directory(Path(args.input_dir), rebuild=False)


if __name__ == "__main__":
    main()
