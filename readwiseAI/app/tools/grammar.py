"""语法规则库 – simple rule-based grammar helpers."""
from __future__ import annotations

from typing import Dict, List

# Map of common grammar tags to brief explanations
_GRAMMAR_RULES: Dict[str, str] = {
    "定语从句": "由关系代词/副词引导，修饰名词或代词。例：the book that I read",
    "状语从句": "表示时间、原因、条件等。例：Although it rained, we went out.",
    "名词性从句": "充当主语、宾语或表语。例：What he said is true.",
    "虚拟语气": "表示假设、愿望等非真实情况。例：If I were you, I would study harder.",
    "被动语态": "主语是动作的承受者。例：The homework was finished by Tom.",
    "非谓语动词": "不充当谓语的动词形式，包括不定式、动名词和分词。",
    "倒装句": "谓语或助动词置于主语之前。例：Never have I seen such a sight.",
    "强调句": "It is/was ... that/who ... 结构。例：It was Tom who broke the window.",
}


def get_rule(grammar_point: str) -> str:
    """Return a brief explanation for a grammar point."""
    for key, val in _GRAMMAR_RULES.items():
        if key in grammar_point or grammar_point in key:
            return val
    return f"暂无关于'{grammar_point}'的内置规则，请查阅语法书。"


def list_rules() -> List[str]:
    return list(_GRAMMAR_RULES.keys())
