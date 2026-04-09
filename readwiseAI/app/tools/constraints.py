"""约束规则库 – difficulty and genre constraints for corpus generation."""
from __future__ import annotations

from typing import Any, Dict

CONSTRAINTS: Dict[str, Dict[str, Any]] = {
    "L1": {
        "avg_sentence_words": 12,
        "max_sentence_words": 18,
        "vocabulary_level": "A1",
        "complex_clause_ratio": 0.1,
        "description": "初中水平，句型简单",
    },
    "L2": {
        "avg_sentence_words": 18,
        "max_sentence_words": 28,
        "vocabulary_level": "A2",
        "complex_clause_ratio": 0.25,
        "description": "高中低年级，含简单从句",
    },
    "L3": {
        "avg_sentence_words": 26,
        "max_sentence_words": 40,
        "vocabulary_level": "B1",
        "complex_clause_ratio": 0.45,
        "description": "高考主流难度，含复杂句型",
    },
    "L4": {
        "avg_sentence_words": 35,
        "max_sentence_words": 60,
        "vocabulary_level": "B2",
        "complex_clause_ratio": 0.65,
        "description": "高考压轴难度，句式复杂",
    },
}

GENRE_REQUIREMENTS: Dict[str, str] = {
    "argumentative": "有明确论点，包含论证和例子，结尾有总结",
    "expository": "客观介绍一个话题，逻辑清晰，包含数据或事实",
    "narrative": "有时间线，包含人物和事件发展",
}


def get_constraints(difficulty: str) -> Dict[str, Any]:
    return CONSTRAINTS.get(difficulty, CONSTRAINTS["L2"])


def get_genre_requirement(genre: str) -> str:
    return GENRE_REQUIREMENTS.get(genre, "结构完整")


def tighten_constraints(
    constraints: Dict[str, Any], issues: list
) -> Dict[str, Any]:
    """Slightly relax/tighten constraints after a failed generation attempt."""
    result = dict(constraints)
    for issue in issues:
        if "字数太少" in str(issue):
            result["min_word_count"] = result.get("min_word_count", 50) + 50
    return result
