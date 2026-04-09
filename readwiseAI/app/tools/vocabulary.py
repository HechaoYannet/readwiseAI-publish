"""考纲词汇库 – CET/高考词汇分级查询."""
from __future__ import annotations

from typing import Dict, Optional

# 极简内置词汇分级表（实际项目中可从文件/数据库加载）
_VOCAB_LEVELS: Dict[str, str] = {
    # A1 / 初级
    "book": "A1", "school": "A1", "water": "A1",
    # A2
    "environment": "A2", "government": "A2",
    # B1 / 高中低年级
    "curriculum": "B1", "inevitable": "B1",
    # B2 / 高考主流
    "phenomenon": "B2", "acknowledge": "B2", "subsequent": "B2",
    # C1 / 高考压轴
    "ubiquitous": "C1", "paradigm": "C1", "exacerbate": "C1",
}

# Difficulty label mapping
_DIFFICULTY_MAP: Dict[str, str] = {
    "L1": "A1",
    "L2": "A2",
    "L3": "B1",
    "L4": "B2",
}


def get_word_level(word: str) -> Optional[str]:
    """Return CEFR level of a word, or None if unknown."""
    return _VOCAB_LEVELS.get(word.lower())


def is_within_difficulty(word: str, difficulty: str) -> bool:
    """Check whether a word is appropriate for the given difficulty level."""
    level = get_word_level(word)
    if level is None:
        return True  # unknown → assume fine
    cefr_order = ["A1", "A2", "B1", "B2", "C1", "C2"]
    target = _DIFFICULTY_MAP.get(difficulty, "B1")
    try:
        return cefr_order.index(level) <= cefr_order.index(target)
    except ValueError:
        return True
