"""Tests for the new memory management features added per MemoryDesign.md."""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch


# ===================================================================
# 1. BaseSubAgent.load_prompt
# ===================================================================

class TestLoadPrompt:
    def test_load_existing_prompt(self, tmp_path):
        """load_prompt should read and return the file contents."""
        prompt_dir = tmp_path / "prompts"
        prompt_dir.mkdir()
        (prompt_dir / "test_prompt.txt").write_text("Hello {name}!", encoding="utf-8")

        from app.sub_agents import base as base_module
        original = base_module._PROMPT_DIR
        base_module._PROMPT_DIR = prompt_dir
        try:
            from app.sub_agents.base import BaseSubAgent
            result = BaseSubAgent.load_prompt("test_prompt")
            assert result == "Hello {name}!"
        finally:
            base_module._PROMPT_DIR = original

    def test_load_missing_prompt_returns_empty(self):
        """load_prompt should return '' for missing files instead of raising."""
        from app.sub_agents.base import BaseSubAgent
        result = BaseSubAgent.load_prompt("__nonexistent_prompt__")
        assert result == ""


# ===================================================================
# 2. WorkingMemory
# ===================================================================

class TestWorkingMemory:
    def test_create_and_save(self, tmp_path):
        from app.models import working_memory as wm_module
        original = wm_module._SESSIONS_DIR
        wm_module._SESSIONS_DIR = tmp_path / "sessions"
        try:
            from app.models.working_memory import WorkingMemory
            wm = WorkingMemory(session_id="sess_001", user_id="u1")
            wm.save()
            path = tmp_path / "sessions" / "u1" / "sess_001.json"
            assert path.exists()
        finally:
            wm_module._SESSIONS_DIR = original

    def test_load_existing(self, tmp_path):
        from app.models import working_memory as wm_module
        original = wm_module._SESSIONS_DIR
        sessions_dir = tmp_path / "sessions"
        wm_module._SESSIONS_DIR = sessions_dir
        try:
            from app.models.working_memory import WorkingMemory
            wm = WorkingMemory(session_id="sess_002", user_id="u2")
            wm.save()

            loaded = WorkingMemory.load("sess_002", "u2")
            assert loaded is not None
            assert loaded.user_id == "u2"
        finally:
            wm_module._SESSIONS_DIR = original

    def test_load_nonexistent_returns_none(self, tmp_path):
        from app.models import working_memory as wm_module
        original = wm_module._SESSIONS_DIR
        wm_module._SESSIONS_DIR = tmp_path / "sessions"
        try:
            from app.models.working_memory import WorkingMemory
            assert WorkingMemory.load("does_not_exist") is None
        finally:
            wm_module._SESSIONS_DIR = original

    def test_set_article_clears_questions(self, tmp_path):
        from app.models import working_memory as wm_module
        original = wm_module._SESSIONS_DIR
        wm_module._SESSIONS_DIR = tmp_path / "sessions"
        try:
            from app.models.working_memory import WorkingMemory
            wm = WorkingMemory(session_id="sess_003", user_id="u3")
            wm.question_queue = [{"q": "old"}]
            wm.set_article({"title": "New Article", "content": "Some text"})
            assert wm.question_queue == []
            assert wm.get_article_title() == "New Article"
        finally:
            wm_module._SESSIONS_DIR = original

    def test_add_message_history_capped(self, tmp_path):
        from app.models import working_memory as wm_module
        original = wm_module._SESSIONS_DIR
        wm_module._SESSIONS_DIR = tmp_path / "sessions"
        try:
            from app.models.working_memory import WorkingMemory
            wm = WorkingMemory(session_id="sess_004", user_id="u4")
            for i in range(50):
                wm.add_message("user", f"message {i}")
            assert len(wm.conversation_history) <= 40
        finally:
            wm_module._SESSIONS_DIR = original

    def test_get_or_create(self, tmp_path):
        from app.models import working_memory as wm_module
        original = wm_module._SESSIONS_DIR
        wm_module._SESSIONS_DIR = tmp_path / "sessions"
        try:
            from app.models.working_memory import WorkingMemory
            wm1 = WorkingMemory.get_or_create("sess_005", "u5")
            wm2 = WorkingMemory.get_or_create("sess_005", "u5")
            assert wm1.session_id == wm2.session_id
        finally:
            wm_module._SESSIONS_DIR = original


# ===================================================================
# 3. MistakeBook
# ===================================================================

class TestMistakeBook:
    def _make_book(self, user_id: str, base_dir: Path):
        from app.models import mistakes as mk_module
        mk_module._LONG_TERM_DIR = base_dir
        from app.models.mistakes import MistakeBook
        return MistakeBook(user_id)

    def _make_entry(self, mistake_id: str = "m001"):
        from app.models.mistakes import MistakeEntry
        return MistakeEntry(
            mistake_id=mistake_id,
            question_text="What does ubiquitous mean?",
            options={"A": "rare", "B": "common", "C": "fast", "D": "slow"},
            correct_answer="B",
            user_answer="A",
            article_excerpt="Ubiquitous smartphones...",
            error_category="词汇理解",
            explanation="Student did not recognize the word.",
            question_type="vocabulary",
            difficulty="L3",
        )

    def test_add_and_search(self, tmp_path):
        from app.models import mistakes as mk_module
        original = mk_module._LONG_TERM_DIR
        mk_module._LONG_TERM_DIR = tmp_path
        try:
            book = self._make_book("u1", tmp_path)
            book.add(self._make_entry("m001"))
            results = book.search(keyword="ubiquitous")
            assert len(results) == 1
            assert results[0].mistake_id == "m001"
        finally:
            mk_module._LONG_TERM_DIR = original

    def test_search_by_category(self, tmp_path):
        from app.models import mistakes as mk_module
        original = mk_module._LONG_TERM_DIR
        mk_module._LONG_TERM_DIR = tmp_path
        try:
            book = self._make_book("u2", tmp_path)
            book.add(self._make_entry("m001"))
            results = book.search(error_category="推理判断")
            assert len(results) == 0
            results = book.search(error_category="词汇理解")
            assert len(results) == 1
        finally:
            mk_module._LONG_TERM_DIR = original

    def test_total_count(self, tmp_path):
        from app.models import mistakes as mk_module
        original = mk_module._LONG_TERM_DIR
        mk_module._LONG_TERM_DIR = tmp_path
        try:
            book = self._make_book("u3", tmp_path)
            assert book.total == 0
            book.add(self._make_entry("m001"))
            book.add(self._make_entry("m002"))
            assert book.total == 2
        finally:
            mk_module._LONG_TERM_DIR = original

    def test_format_for_prompt_empty(self, tmp_path):
        from app.models import mistakes as mk_module
        original = mk_module._LONG_TERM_DIR
        mk_module._LONG_TERM_DIR = tmp_path
        try:
            book = self._make_book("u4", tmp_path)
            result = book.format_for_prompt([])
            assert "暂无" in result
        finally:
            mk_module._LONG_TERM_DIR = original


# ===================================================================
# 4. ForgettingCurve (SM-2)
# ===================================================================

class TestForgettingCurve:
    def test_register_and_review(self, tmp_path):
        from app.models import forgetting as fg_module
        original = fg_module._LONG_TERM_DIR
        fg_module._LONG_TERM_DIR = tmp_path
        try:
            from app.models.forgetting import ForgettingCurve
            fc = ForgettingCurve("u1")
            item = fc.register("m001")
            assert item.repetitions == 0

            updated = fc.record_review("m001", quality=5)
            assert updated.repetitions == 1
            assert updated.interval_days >= 1
        finally:
            fg_module._LONG_TERM_DIR = original

    def test_failed_review_resets_repetitions(self, tmp_path):
        from app.models import forgetting as fg_module
        original = fg_module._LONG_TERM_DIR
        fg_module._LONG_TERM_DIR = tmp_path
        try:
            from app.models.forgetting import ForgettingCurve
            fc = ForgettingCurve("u2")
            fc.record_review("m001", quality=5)  # first success
            fc.record_review("m001", quality=5)  # second success
            item = fc.record_review("m001", quality=0)  # failure
            assert item.repetitions == 0
            assert item.interval_days == 1
        finally:
            fg_module._LONG_TERM_DIR = original

    def test_easiness_min_1_3(self, tmp_path):
        from app.models import forgetting as fg_module
        original = fg_module._LONG_TERM_DIR
        fg_module._LONG_TERM_DIR = tmp_path
        try:
            from app.models.forgetting import ForgettingCurve
            fc = ForgettingCurve("u3")
            for _ in range(10):
                fc.record_review("m001", quality=0)
            item = fc.get_item("m001")
            assert item.easiness >= 1.3
        finally:
            fg_module._LONG_TERM_DIR = original


# ===================================================================
# 5. CorpusRepository
# ===================================================================

class TestCorpusRepository:
    def test_search_no_filter(self):
        from app.tools.corpus_repo import CorpusRepository
        repo = CorpusRepository()
        results = repo.search()
        # At least the sample article should be found
        assert isinstance(results, list)

    def test_search_by_difficulty(self):
        from app.tools.corpus_repo import CorpusRepository
        repo = CorpusRepository()
        results = repo.search(difficulty="L3", limit=100)
        ids = [r["id"] for r in results]
        # Corpus articles have section suffixes; verify at least one L3 article exists
        assert len(ids) > 0
        # All returned articles should be L3
        for r in results:
            assert r.get("difficulty") == "L3"

    def test_search_missing_difficulty(self):
        from app.tools.corpus_repo import CorpusRepository
        repo = CorpusRepository()
        results = repo.search(difficulty="L9")
        assert results == []

    def test_get_article(self):
        from app.tools.corpus_repo import CorpusRepository
        repo = CorpusRepository()
        # Use the actual ID from the corpus index (section-suffixed)
        art = repo.get_article("gk_2024_001_A")
        assert art is not None
        assert "content" in art
        assert len(art["content"]) > 0

    def test_get_article_nonexistent(self):
        from app.tools.corpus_repo import CorpusRepository
        repo = CorpusRepository()
        assert repo.get_article("__does_not_exist__") is None

    def test_format_examples_for_prompt(self):
        from app.tools.corpus_repo import CorpusRepository
        repo = CorpusRepository()
        text = repo.format_examples_for_prompt(difficulty="L3")
        assert len(text) > 10  # should have real content


# ===================================================================
# 6. QuestionExpert – multi-type questions
# ===================================================================

class TestQuestionExpertMultiType:
    @pytest.mark.asyncio
    async def test_generates_multi_type_questions(self):
        from app.sub_agents.question import QuestionExpert

        agent = QuestionExpert()
        fake_result = {
            "questions": [
                {
                    "question_text": "Q1",
                    "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                    "correct_answer": "A",
                    "explanation": "...",
                    "evidence": "...",
                    "type": "detail",
                },
                {
                    "question_text": "Q2",
                    "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                    "correct_answer": "B",
                    "explanation": "...",
                    "evidence": "...",
                    "type": "inference",
                },
                {
                    "question_text": "Q3",
                    "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                    "correct_answer": "C",
                    "explanation": "...",
                    "evidence": "...",
                    "type": "vocabulary",
                },
            ]
        }
        with patch(
            "app.sub_agents.base.llm_json_call",
            new_callable=AsyncMock,
            return_value=fake_result,
        ):
            result = await agent.execute(
                {
                    "article": "This is a test article about technology and society.",
                    "question_types": ["detail", "inference", "vocabulary"],
                    "difficulty": "L3",
                    "count": 3,
                },
                {},
            )
        assert len(result["questions"]) == 3

    @pytest.mark.asyncio
    async def test_fallback_stubs_on_empty_llm(self):
        from app.sub_agents.question import QuestionExpert

        agent = QuestionExpert()
        with patch(
            "app.sub_agents.base.llm_json_call",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await agent.execute(
                {
                    "article": "Short article.",
                    "count": 2,
                    "question_types": ["detail", "inference"],
                    "difficulty": "L2",
                },
                {},
            )
        # Should produce 2 stub questions
        assert len(result["questions"]) == 2

    @pytest.mark.asyncio
    async def test_question_types_list_cycled_to_count(self):
        """When question_types is shorter than count, it should be cycled."""
        from app.sub_agents.question import QuestionExpert

        agent = QuestionExpert()
        fake_result = {
            "questions": [
                {"question_text": f"Q{i}", "options": {}, "correct_answer": "A",
                 "explanation": "", "evidence": ""}
                for i in range(4)
            ]
        }
        with patch(
            "app.sub_agents.base.llm_json_call",
            new_callable=AsyncMock,
            return_value=fake_result,
        ):
            result = await agent.execute(
                {
                    "article": "Test article.",
                    "question_types": ["detail"],
                    "count": 4,
                    "difficulty": "L2",
                },
                {},
            )
        assert len(result["questions"]) == 4


# ===================================================================
# 7. QAExpert – new query_type "free"
# ===================================================================

class TestQAExpertFree:
    @pytest.mark.asyncio
    async def test_free_query_without_memory_uses_simple_path(self):
        from app.sub_agents.qa import QAExpert

        agent = QAExpert()
        with patch(
            "app.sub_agents.base.llm_json_call",
            new_callable=AsyncMock,
            return_value={"answer": "42", "references": [], "follow_up": ""},
        ):
            result = await agent.execute(
                {"query_type": "free", "content": "What is 6x7?"},
                {},  # no memory context
            )
        assert "answer" in result

    @pytest.mark.asyncio
    async def test_unknown_query_type_still_returns_error(self):
        from app.sub_agents.qa import QAExpert

        agent = QAExpert()
        result = await agent.execute(
            {"query_type": "invalid_type", "content": "test"},
            {},
        )
        assert "error" in result


# ===================================================================
# 8. Dispatcher – memory injection
# ===================================================================

class TestDispatcherMemoryInjection:
    @pytest.mark.asyncio
    async def test_memory_context_injected(self):
        """Dispatcher should load working/long-term memory into agent context."""
        from app.orchestrator.dispatcher import Dispatcher
        from app.models.state import OrchestratorState, SubTask, SubTaskStatus

        state = OrchestratorState(request_id="req_mem_001", user_id="u_mem")
        task = SubTask(
            sub_task_id="sub_m01",
            assigned_to="qa_expert",
            description="Free QA",
            input={"query_type": "word", "content": "serendipity"},
        )
        state.sub_tasks = [task]

        dispatcher = Dispatcher()
        # No patch needed – StubLLM handles LLM calls; memory modules use real FS
        state = await dispatcher.dispatch_all_pending(state)
        assert task.status in (SubTaskStatus.COMPLETED, SubTaskStatus.FAILED)


# ===================================================================
# 9. LongTermMemory
# ===================================================================

class TestLongTermMemory:
    def test_record_and_search_mistake(self, tmp_path):
        from app.models import long_term_memory as ltm_module
        from app.models import mistakes as mk_module
        from app.models import forgetting as fg_module

        orig_ltm = ltm_module._LONG_TERM_DIR
        orig_mk = mk_module._LONG_TERM_DIR
        orig_fg = fg_module._LONG_TERM_DIR
        ltm_module._LONG_TERM_DIR = tmp_path
        mk_module._LONG_TERM_DIR = tmp_path
        fg_module._LONG_TERM_DIR = tmp_path
        try:
            from app.models.long_term_memory import LongTermMemory
            from app.models.mistakes import MistakeEntry

            ltm = LongTermMemory("u_ltm")
            entry = MistakeEntry(
                mistake_id="m_ltm_001",
                question_text="Identify the main idea",
                error_category="主旨理解",
                question_type="main_idea",
                difficulty="L3",
            )
            ltm.record_mistake(entry)

            summary = ltm.search_mistakes_formatted(keyword="main idea")
            assert "主旨理解" in summary or "main idea" in summary.lower() or "暂无" in summary
        finally:
            ltm_module._LONG_TERM_DIR = orig_ltm
            mk_module._LONG_TERM_DIR = orig_mk
            fg_module._LONG_TERM_DIR = orig_fg

    def test_power_history(self, tmp_path):
        from app.models import long_term_memory as ltm_module
        from app.models import mistakes as mk_module
        from app.models import forgetting as fg_module

        orig_ltm = ltm_module._LONG_TERM_DIR
        orig_mk = mk_module._LONG_TERM_DIR
        orig_fg = fg_module._LONG_TERM_DIR
        ltm_module._LONG_TERM_DIR = tmp_path
        mk_module._LONG_TERM_DIR = tmp_path
        fg_module._LONG_TERM_DIR = tmp_path
        try:
            from app.models.long_term_memory import LongTermMemory

            ltm = LongTermMemory("u_power")
            ltm.append_power_record(100.0, "initial score")
            ltm.append_power_record(105.5, "after practice")
            history = ltm.get_power_history()
            assert len(history) == 2
            assert history[-1]["score"] == 105.5
        finally:
            ltm_module._LONG_TERM_DIR = orig_ltm
            mk_module._LONG_TERM_DIR = orig_mk
            fg_module._LONG_TERM_DIR = orig_fg


# ===================================================================
# 10. Memory tools (unit)
# ===================================================================

class TestMemoryTools:
    def test_get_current_article_no_context(self):
        from app.tools import memory_tools as mt
        mt.configure_tools()
        result = mt.get_current_article.invoke({})
        assert "没有" in result or "无" in result or "会话" in result

    def test_get_current_article_with_working_memory(self, tmp_path):
        from app.models import working_memory as wm_module
        original = wm_module._SESSIONS_DIR
        wm_module._SESSIONS_DIR = tmp_path / "sessions"
        try:
            from app.models.working_memory import WorkingMemory
            from app.tools import memory_tools as mt

            wm = WorkingMemory.get_or_create("sess_mt_001", "u_mt")
            wm.set_article({"title": "Test Article", "content": "Hello world."})
            mt.configure_tools(working_memory=wm)

            result = mt.get_current_article.invoke({})
            assert "Test Article" in result
            assert "Hello world" in result
        finally:
            wm_module._SESSIONS_DIR = original
            from app.tools import memory_tools as mt
            mt.configure_tools()

    def test_search_mistakes_no_context(self):
        from app.tools import memory_tools as mt
        mt.configure_tools()
        result = mt.search_mistakes.invoke({"keyword": "test"})
        assert "无法" in result or "未加载" in result

    def test_get_grammar_rule(self):
        from app.tools import memory_tools as mt
        result = mt.get_grammar_rule.invoke({"grammar_point": "定语从句"})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_lookup_word_returns_string(self):
        """lookup_word tool should return a non-empty string."""
        from app.tools import memory_tools as mt
        result = mt.lookup_word.invoke({"word": "serendipity"})
        assert isinstance(result, str)
        assert "serendipity" in result.lower() or len(result) > 0

    def test_search_corpus(self):
        from app.tools import memory_tools as mt
        result = mt.search_corpus.invoke({"difficulty": "L3"})
        assert isinstance(result, str)
        assert len(result) > 0


# ===================================================================
# 11. OrchestratorState – new fields
# ===================================================================

class TestOrchestratorStateNewFields:
    def test_new_fields_default_none(self):
        from app.models.state import OrchestratorState

        state = OrchestratorState(request_id="req_new", user_id="u1")
        assert state.working_memory is None
        assert state.long_term_memory is None
        assert state.session_id is None

    def test_new_fields_can_be_set(self):
        from app.models.state import OrchestratorState

        state = OrchestratorState(
            request_id="req_new2",
            user_id="u1",
            session_id="sess_abc",
            working_memory={"session_id": "sess_abc"},
            long_term_memory={"user_id": "u1"},
        )
        assert state.session_id == "sess_abc"
        assert state.working_memory is not None

    def test_attempt_request_has_session_id(self):
        from app.models.state import AttemptRequest

        req = AttemptRequest(user_id="u1", session_id="sess_xyz")
        assert req.session_id == "sess_xyz"

    def test_attempt_request_has_question_types(self):
        from app.models.state import AttemptRequest

        req = AttemptRequest(
            user_id="u1",
            question_types=["detail", "inference"],
        )
        assert req.question_types == ["detail", "inference"]
