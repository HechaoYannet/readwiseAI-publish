"""memory_tools – LangChain工具集，供问答专家自主调用各种记忆.

每个 @tool 函数都有完整的 docstring，LLM 会读取以决定何时调用。
工具通过模块级 _context 字典获取依赖（working_memory、long_term_memory、corpus_repo）。
调用方需先调用 configure_tools() 注入上下文，再将工具列表绑定到 LLM。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from langchain_core.tools import tool
from typing_extensions import Literal

logger = logging.getLogger(__name__)

# Module-level context injected by the QA agent before tool calls.
# Keys: "working_memory", "long_term_memory", "corpus_repo"
_context: Dict[str, Any] = {}


def configure_tools(
        working_memory: Optional[Any] = None,
        long_term_memory: Optional[Any] = None,
        corpus_repo: Optional[Any] = None,
) -> None:
    """Inject runtime dependencies into the tool module.

    This must be called before invoking any tool.

    Args:
        working_memory: A WorkingMemory instance for the current session.
        long_term_memory: A LongTermMemory instance for the current user.
        corpus_repo: A CorpusRepository instance.
    """
    global _context
    _context = {
        "working_memory": working_memory,
        "long_term_memory": long_term_memory,
        "corpus_repo": corpus_repo,
    }


# ---------------------------------------------------------------------------
# Tool: get_current_article
# ---------------------------------------------------------------------------

@tool
def get_current_article() -> str:
    """获取学生当前正在阅读的文章全文。

    当学生询问「这篇文章里…」「文章中提到…」「根据上文…」等问题时，
    请调用此工具获取文章内容，再结合内容回答。
    如果没有当前文章，返回提示信息。
    """
    wm = _context.get("working_memory")
    if wm is None:
        return "（当前没有活跃的学习会话，无法获取文章）"
    content = wm.get_article_content()
    title = wm.get_article_title()
    if not content:
        return "（当前会话尚未加载文章）"
    return f"# {title}\n\n{content}"


# ---------------------------------------------------------------------------
# Tool: get_current_questions
# ---------------------------------------------------------------------------

@tool
def get_current_questions() -> str:
    """获取当前文章已生成的题目列表。

    当学生询问「这道题的答案是…」「第几题考的是…」时使用。
    如果没有题目，返回提示信息。
    """
    wm = _context.get("working_memory")
    if wm is None:
        return "（当前没有活跃的学习会话）"
    questions = wm.current_questions
    if not questions:
        return "（当前文章尚未生成题目）"
    lines = []
    for i, q in enumerate(questions, 1):
        opts = q.get("options", {})
        opts_str = " / ".join(f"{k}: {v}" for k, v in opts.items())
        lines.append(
            f"题{i}（{q.get('type', '?')}）: {q.get('question_text', '')}\n"
            f"  选项: {opts_str}\n"
            f"  答案: {q.get('correct_answer', '?')}"
        )
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: search_mistakes
# ---------------------------------------------------------------------------

@tool
def search_mistakes(keyword: str = "", error_category: str = "", question_type: str = "") -> str:
    """搜索用户的错题本，返回相关错题摘要。

    当学生询问「我以前错过哪些…」「我在…类型的题上总是犯错」
    「帮我回顾一下我的错题」等问题时使用。
    支持按关键词、错误类型（词汇理解/推理判断/细节查找/主旨理解）、
    题目类型（detail/inference/vocabulary/main_idea）过滤。

    Args:
        keyword: 关键词搜索（匹配题干或文章摘录）。
        error_category: 错误类型过滤，如「词汇理解」。
        question_type: 题目类型过滤，如「inference」。
    """
    ltm = _context.get("long_term_memory")
    if ltm is None:
        return "（无法访问错题本：用户记忆未加载）"
    return ltm.search_mistakes_formatted(
        keyword=keyword or None,
        error_category=error_category or None,
        question_type=question_type or None,
    )


# ---------------------------------------------------------------------------
# Tool: search_corpus
# ---------------------------------------------------------------------------

@tool
def search_corpus(difficulty: str = "", genre: str = "", section: Literal["A", "B", "C", "D"] | None = None) -> str:
    """搜索高考真题语料库，返回相关文章摘要。

    当需要参考真题风格、举例说明高考阅读特点时使用。
    支持按难度（L1-L4）和体裁（argumentative/expository/narrative）和文章编号（A/B/C/D）过滤。
    注意：为保证获取信息全面性， **不建议** 指定任何过滤条件，除非明确需要特定文章。

    Args:
        difficulty: 难度等级，L1/L2/L3/L4
        genre: 文章体裁，argumentative议论文/expository说明文/narrative记叙文。
        section: 文章编号，A/B/C/D（可选，提供后返回对应文章，否则返回多篇相关摘要）。
    """
    repo = _context.get("corpus_repo")
    if repo is None:
        try:
            from app.tools.corpus_repo import get_corpus_repo
            repo = get_corpus_repo()
        except Exception as exc:
            return f"（无法加载语料库: {exc}）"
    return repo.format_examples_for_prompt(
        difficulty=difficulty or None,
        genre=genre or None,
        section=section or None,
        count=12,
    )


# ---------------------------------------------------------------------------
# Tool: lookup_word
# ---------------------------------------------------------------------------

@tool
def lookup_word(word: str, context_sentence: str = "") -> str:
    """查询英语单词的释义和用法。

    当学生询问某个单词的意思、词性、用法时使用。
    如果提供了上下文句子，会结合上下文给出更准确的释义。

    Args:
        word: 要查询的英语单词。
        context_sentence: 包含该单词的句子（可选，提供后给出语境释义）。
    """
    # Use a synchronous stub path when no API key is configured (test/offline mode)
    # and the real async call when running inside an event loop via a thread pool.
    try:
        from app.tools.dictionary import APP_KEY, APP_SECRET

        if not APP_KEY or not APP_SECRET:
            result = {
                "translation": [f"[模拟] {word}: 请配置 API 密钥"],
                "success": False
            }
        else:
            import asyncio
            from app.tools.dictionary import lookup_word as _dict_lookup
            result = asyncio.run(_dict_lookup(word))

        defs = result.get("translation", [])
        # phonetic = result.get("phonetic", "")
        output = f"**{word}**"
        # if phonetic:
        #     output += f" /{phonetic}/"
        output += "\n" + "\n".join(f"  - {d}" for d in defs)
        if context_sentence:
            output += f"\n\n（上下文：{context_sentence}）"
        return output
    except Exception as exc:
        return f"查词失败: {exc}"


# ---------------------------------------------------------------------------
# Tool: get_grammar_rule
# ---------------------------------------------------------------------------

@tool
def get_grammar_rule(grammar_point: str) -> str:
    """获取指定语法点的规则说明和例句。

    当学生询问特定语法现象（如「定语从句」「虚拟语气」「倒装句」）的用法时使用。

    Args:
        grammar_point: 语法点名称，如「定语从句」「状语从句」「非谓语动词」。
    """
    try:
        from app.tools.grammar import get_rule
        return get_rule(grammar_point)
    except Exception as exc:
        return f"（获取语法规则失败: {exc}）"


# ---------------------------------------------------------------------------
# Exported tool list
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    get_current_article,
    get_current_questions,
    search_mistakes,
    search_corpus,
    lookup_word,
    get_grammar_rule,
]
