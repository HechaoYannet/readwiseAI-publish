"""CorpusExpert – 高考风格文章生成（支持总体规划和风格化生成）.

三种工作模式：
1. 普通生成：按难度/体裁/主题生成文章。
2. 总体规划（enable_planning=True）：读取整个语料库 + 用户学情数据，
   规划本组训练 4 篇文章，返回 training_plan 和待注入的 new_sub_tasks。
3. 风格化生成（reference_id 提供时）：以语料库中指定真题为风格参考。
"""
from __future__ import annotations

import json
import logging
import time
from string import Template
from typing import Any, Dict, List, Optional

from app.models import working_memory
from app.models.state import OrchestratorState
from app.sub_agents.base import BaseSubAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

ARTICLE_PROMPT = """
你是高考英语阅读材料专家。请生成一篇符合高考风格的英语文章。

## 要求
难度等级：$difficulty（L1最简单，L4最难）
体裁：$genre（argumentative议论文/expository说明文/narrative记叙文）
主题：$topic
目标字数：$word_count 词

## 参考风格说明
$style_reference

## 难度对照
- L1：初中水平，词汇简单，句型短
- L2：高中低年级，词汇较丰富，含简单从句
- L3：高考主流难度，词汇多样，含复杂句型
- L4：高考压轴难度，词汇高级，句式复杂

## 出题描述
$description

## 输出格式（严格JSON，只输出JSON）
{{
  "title": "文章标题",
  "content": "文章正文（英文）",
  "word_count": 305,
  "difficulty_actual": "L2",
  "genre_actual": "expository",
  "key_vocabulary": ["word1", "word2"],
  "grammar_highlights": ["定语从句", "状语从句"]
}}
"""

PLANNING_PROMPT = """
你是高考英语训练规划专家。请根据语料库信息和学生学情数据，为本次训练规划4篇文章。

## 语料库中可参考的真题（按需引用 id）
$corpus_metadata

## 学生错题摘要
$mistake_summary

## 学生最近战力值记录
$power_summary

## 规划要求
- 规划恰好4篇文章，难度总体从易到难（可参考 L2→L2→L3→L3 或 L2→L3→L3→L4）
- 体裁多样化（尽量覆盖 argumentative / expository / narrative）
- 每篇文章引用语料库中的参考真题 id（若语料库为空则填 null）
- 根据学生错题薄弱点定向强化对应语法/题型

## 输出格式（严格JSON，只输出JSON）
{{
  "articles": [
    {{
      "idx": 1, //按顺序编号；与题库中"section"的对应关系：第1篇文章对应 Section A，第2篇对应 Section B，以此类推
      "topic": "", //根据高考真题常见主题决定，例如：科技与人文传承
      "reference_id": "gk_2024_001",
      "grammar_points": [], //可选：三大从句（尤其定语从句、名词性从句）、非谓语动词、时态语态、倒装强调句、动作逻辑
      "difficulty": "", //L1/L2/L3/L4
      "word_count": "", //根据难度、参考真题和学生情况灵活调整，通常在250-500词之间
      "genre": "", //argumentative/expository/narrative
      "description": "" //出题描述，例如：关于海洋塑料污染的说明文，重点考查细节题和推理题
    }}
  ]
}}
"""

DIFFICULTY_CONSTRAINTS = {
    "L1": {"max_sentence_len": 15, "avg_word_len": 5},
    "L2": {"max_sentence_len": 25, "avg_word_len": 6},
    "L3": {"max_sentence_len": 35, "avg_word_len": 7},
    "L4": {"max_sentence_len": 50, "avg_word_len": 8},
}

# Prefix for dynamically injected sub-task IDs (to avoid clashes)
_DYNAMIC_PREFIX = "dyn"


def _validate_article(article: Dict[str, Any], difficulty: str) -> Dict[str, Any]:
    """Basic validation of the generated article."""
    issues: List[str] = []
    content = article.get("content", "")
    wc = len(content.split())
    if wc < 50:
        issues.append(f"字数太少: {wc}")
    if not article.get("title"):
        issues.append("缺少标题")
    return {"passed": len(issues) == 0, "issues": issues}


def _build_training_sub_tasks(training_plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert a training plan into concrete corpus + question sub-tasks.

    Each article plan produces:
      - A corpus_expert task (``dyn_cN``) that generates the article.
      - A question_expert task (``dyn_qN``) that depends on ``dyn_cN``.

    The question task uses ``article_task_id`` so the dispatcher can resolve
    the article text from the completed corpus task at execution time.
    """
    sub_tasks: List[Dict[str, Any]] = []
    for spec in training_plan:
        n = spec.get("idx", len(sub_tasks) // 2 + 1)
        corpus_id = f"{_DYNAMIC_PREFIX}_c{n}"
        question_id = f"{_DYNAMIC_PREFIX}_q{n}"

        sub_tasks.append({
            "sub_task_id": corpus_id,
            "assigned_to": "corpus_expert",
            "description": f"生成训练文章{n}：{spec.get('topic', '')}",
            "input": {
                "difficulty": spec.get("difficulty", "L2"),
                "genre": spec.get("genre", "expository"),
                "topic": spec.get("topic", ""),
                "word_count": spec.get("word_count", 300),
                "reference_id": spec.get("reference_id"),
                "grammar_points": spec.get("grammar_points", []),
                "description": spec.get("description", ""),
            },
            "acceptance_criteria": ["文章字数在目标范围内", "体裁符合要求"],
            "depends_on": [],
        })

        sub_tasks.append({
            "sub_task_id": question_id,
            "assigned_to": "question_expert",
            "description": f"为训练文章{n}生成题目",
            "input": {
                "article_task_id": corpus_id,  # resolved by dispatcher at runtime
                "difficulty": spec.get("difficulty", "L2"),
                "count": 4, # 或根据语料调整题目数量
                "question_types": [], #自己决定
            },
            "acceptance_criteria": [],
            "depends_on": [corpus_id],
        })

    return sub_tasks


class CorpusExpert(BaseSubAgent):
    name = "corpus_expert"
    description = "高考风格文章生成（支持总体规划 / 风格化生成 / 工作记忆同步）"

    async def execute(
            self, input: Dict[str, Any], context: Dict[str, Any], state: "OrchestratorState | None" = None
    ) -> Dict[str, Any]:
        start = time.time()

        # ------------------------------------------------------------------
        # Mode 1: overall planning
        # ------------------------------------------------------------------
        if input.get("enable_planning"):
            return await self._run_planning_mode(context, start, state)

        # ------------------------------------------------------------------
        # Mode 2 / 3: article generation (with optional style reference)
        # ------------------------------------------------------------------
        difficulty = input.get("difficulty", "L2")
        genre = input.get("genre", "expository")
        topic = input.get("topic", "technology")
        word_count = input.get("word_count", 300)
        reference_id: Optional[str] = input.get("reference_id")
        description: str = input.get("description", "")
        grammar_points: List[str] = input.get("grammar_points", [])

        # Build style reference block
        style_reference = self._get_style_reference(reference_id, context)
        if grammar_points:
            style_reference += f"\n\n## 重点语法点：{', '.join(grammar_points)}"

        # Load prompt template from file; fall back to inline template
        template = self.load_prompt("corpus_prompt") or ARTICLE_PROMPT

        article: Dict[str, Any] = {}
        validation: Dict[str, Any] = {"passed": False, "issues": []}

        # 最多尝试3次生成，直到通过基本验证（字数/标题等），每次失败都记录问题并重试
        for attempt in range(3):
            prompt = Template(template).substitute(
                difficulty=difficulty,
                genre=genre,
                topic=topic,
                word_count=word_count,
                style_reference=style_reference or "（无特定风格参考）",
                description=(description or "（无特定出题描述）") + validation.get("issues", []).__str__()
            )
            if state is not None:
                state.status_history.append(f"# 正在撰写文章")
            article = await self._call_llm(prompt)
            if not article:
                article = {"title": "", "content": "", "word_count": 0}

            validation = _validate_article(article, difficulty)
            if validation["passed"]:
                # Sync to working memory
                self._sync_working_memory(article, context)
                return {
                    "article": article,
                    "validation": validation,
                    "metadata": {
                        "attempts": attempt + 1,
                        "latency_ms": self._timed(start),
                        "agent": self.name,
                        "reference_id": reference_id,
                    },
                }
            logger.warning(
                "CorpusExpert attempt %d failed validation: %s",
                attempt + 1,
                validation["issues"],
            )

        # Sync partial result to working memory anyway
        self._sync_working_memory(article, context)
        return {
            "article": article,
            "validation": validation,
            "metadata": {
                "attempts": 3,
                "partial": True,
                "latency_ms": self._timed(start),
                "agent": self.name,
                "reference_id": reference_id,
            },
        }

    # ------------------------------------------------------------------
    # Planning mode
    # ------------------------------------------------------------------

    async def _run_planning_mode(
            self, context: Dict[str, Any], start: float, state: OrchestratorState
    ) -> Dict[str, Any]:
        """Read corpus + user data, generate a 4-article training plan."""
        # 1. Corpus index
        corpus_repo = context.get("corpus_repo")
        if corpus_repo is None:
            try:
                from app.tools.corpus_repo import get_corpus_repo
                corpus_repo = get_corpus_repo()
            except Exception as exc:
                logger.warning("Could not load corpus repo in planning mode: %s", exc)
        corpus_metadata_str = "（语料库为空）"
        if corpus_repo:
            try:
                all_meta = corpus_repo.get_all_metadata()
                corpus_metadata_str = json.dumps(all_meta, ensure_ascii=False, indent=2)
            except Exception as exc:
                logger.warning("Failed to read corpus metadata: %s", exc)

        # 2. User long-term memory
        ltm = context.get("long_term_memory")
        mistake_summary = "（暂无错题记录）"
        power_summary = "（暂无战力值记录）"
        if ltm:
            try:
                mistake_summary = ltm.search_mistakes_formatted() or mistake_summary
            except Exception as exc:
                logger.warning("Failed to read mistakes in planning: %s", exc)
            try:
                power_hist = ltm.get_power_history()[-5:]
                if power_hist:
                    power_summary = json.dumps(power_hist, ensure_ascii=False)
            except Exception as exc:
                logger.warning("Failed to read power history in planning: %s", exc)

        prompt = Template(PLANNING_PROMPT).substitute(
            corpus_metadata=corpus_metadata_str,
            mistake_summary=mistake_summary,
            power_summary=power_summary,
        )

        if state is not None:
            state.status_history.append(f"# 正在规划训练方案")
        plan_result = await self._call_llm(prompt)
        training_plan: List[Dict[str, Any]] = []
        if plan_result and isinstance(plan_result.get("articles"), list):
            training_plan = plan_result["articles"]

        # Build new sub-tasks for dynamic injection by the Orchestrator
        new_sub_tasks = _build_training_sub_tasks(training_plan)

        res = {
            "training_plan": training_plan,
            "new_sub_tasks": new_sub_tasks,
            "metadata": {
                "latency_ms": self._timed(start),
                "agent": self.name,
                "mode": "planning",
            },
        }
        if state is not None:
            wm = working_memory.WorkingMemory(session_id=state.session_id or "", user_id=state.user_id)
            wm.add_agent_information({"corpus_expert_planning": res})
        return res

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_style_reference(
            self, reference_id: Optional[str], context: Dict[str, Any]
    ) -> str:
        """Load a reference article from the corpus for style guidance."""
        if not reference_id:
            return ""
        try:
            corpus_repo = context.get("corpus_repo")
            if corpus_repo is None:
                from app.tools.corpus_repo import get_corpus_repo
                corpus_repo = get_corpus_repo()
            entry = corpus_repo.get_article(reference_id)
            if not entry:
                logger.warning("Reference article not found: %s", reference_id)
                return ""
            meta = entry.get("metadata", {})
            content = entry.get("content", "")
            return (
                f"参考真题（{meta.get('source', reference_id)}，"
                f"难度 {meta.get('difficulty', '?')}，"
                f"体裁 {meta.get('genre', '?')}）：\n{content}"
            )
        except Exception as exc:
            logger.warning("Failed to load style reference %s: %s", reference_id, exc)
            return ""

    def _sync_working_memory(
            self, article: Dict[str, Any], context: Dict[str, Any]
    ) -> None:
        """Persist the generated article to the session's working memory."""
        wm = context.get("working_memory")
        if wm is None:
            return
        try:
            wm: working_memory.WorkingMemory
            wm.set_article({
                "title": article.get("title", ""),
                "content": article.get("content", ""),
                "difficulty": article.get("difficulty_actual", ""),
                "genre": article.get("genre_actual", ""),
                "key_vocabulary": article.get("key_vocabulary", []),
            })
        except Exception as exc:
            logger.warning("Failed to sync article to working memory: %s", exc)
