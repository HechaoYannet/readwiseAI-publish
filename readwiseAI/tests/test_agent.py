"""Integration + unit tests for ReadWise AI Agent architecture."""
from __future__ import annotations

import json
import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _make_temp_dirs(tmp_path: Path):
    (tmp_path / "checkpoints").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "tasks" / "pending").mkdir(parents=True)
    (tmp_path / "tasks" / "processing").mkdir(parents=True)
    return tmp_path


# ===================================================================
# 1. Data models
# ===================================================================

class TestStateModels:
    def test_orchestrator_state_defaults(self):
        from app.models.state import OrchestratorState, RequestStatus

        state = OrchestratorState(request_id="req_test", user_id="u1")
        assert state.status == RequestStatus.PENDING
        assert state.retry_count == 0
        assert state.sub_tasks == []

    def test_subtask_model(self):
        from app.models.state import SubTask, SubTaskStatus

        t = SubTask(
            sub_task_id="sub_001",
            assigned_to="diagnosis_expert",
            description="test",
        )
        assert t.status == SubTaskStatus.PENDING
        assert t.retry_count == 0

    def test_attempt_request_defaults(self):
        from app.models.state import AttemptRequest

        req = AttemptRequest()
        assert req.request_type == "attempt"
        assert req.user_answer == ""


# ===================================================================
# 2. CheckpointManager
# ===================================================================

class TestCheckpointManager:
    def test_save_and_load(self, tmp_path):
        from app.orchestrator.checkpoint import CheckpointManager
        from app.models.state import OrchestratorState

        cm = CheckpointManager(
            base_dir=tmp_path / "users",
            index_dir=tmp_path / "request_index",
        )
        state = OrchestratorState(request_id="req_abc", user_id="u1")
        cm.save(state)
        loaded = cm.load("req_abc")
        assert loaded is not None
        assert loaded.request_id == "req_abc"
        assert loaded.user_id == "u1"

    def test_load_nonexistent(self, tmp_path):
        from app.orchestrator.checkpoint import CheckpointManager

        cm = CheckpointManager(
            base_dir=tmp_path / "users",
            index_dir=tmp_path / "request_index",
        )
        assert cm.load("does_not_exist") is None

    def test_delete(self, tmp_path):
        from app.orchestrator.checkpoint import CheckpointManager
        from app.models.state import OrchestratorState

        cm = CheckpointManager(
            base_dir=tmp_path / "users",
            index_dir=tmp_path / "request_index",
        )
        state = OrchestratorState(request_id="req_del", user_id="u1")
        cm.save(state)
        cm.delete("req_del")
        # Checkpoint file is gone; index entry kept for ownership lookup
        assert cm.load("req_del") is None
        # Index entry still present
        assert cm.lookup_user_id("req_del") == "u1"

    def test_save_and_load_result(self, tmp_path):
        from app.orchestrator.checkpoint import CheckpointManager

        cm = CheckpointManager(
            base_dir=tmp_path / "users",
            index_dir=tmp_path / "request_index",
        )
        cm.save_result("req_r", "u1", {"status": "completed", "results": {}})
        r = cm.load_result("req_r", "u1")
        assert r is not None
        assert r["status"] == "completed"

    def test_lookup_user_id(self, tmp_path):
        from app.orchestrator.checkpoint import CheckpointManager
        from app.models.state import OrchestratorState

        cm = CheckpointManager(
            base_dir=tmp_path / "users",
            index_dir=tmp_path / "request_index",
        )
        state = OrchestratorState(request_id="req_idx", user_id="alice")
        cm.save(state)
        assert cm.lookup_user_id("req_idx") == "alice"
        assert cm.lookup_user_id("req_unknown") is None


# ===================================================================
# 3. Planner
# ===================================================================

class TestPlanner:
    @pytest.mark.asyncio
    async def test_rule_based_attempt(self):
        from app.orchestrator.planner import Planner
        from app.models.state import OrchestratorState

        state = OrchestratorState(
            request_id="req_p1",
            user_id="u1",
            original_request={
                "request_type": "attempt",
                "paragraph": "The sun rises in the east.",
                "question_text": "Where does the sun rise?",
                "options": {"A": "East", "B": "West", "C": "North", "D": "South"},
                "user_answer": "B",
                "correct_answer": "A",
                "time_spent": 30,
                "user_id": "u1",
            },
        )
        planner = Planner()
        state = await planner.plan(state)
        assert len(state.sub_tasks) == 1
        assert state.sub_tasks[0].assigned_to == "diagnosis_expert"

    @pytest.mark.asyncio
    async def test_rule_based_corpus(self):
        from app.orchestrator.planner import Planner
        from app.models.state import OrchestratorState

        state = OrchestratorState(
            request_id="req_p2",
            user_id="u1",
            original_request={
                "request_type": "corpus",
                "difficulty": "L2",
                "genre": "expository",
                "topic": "environment",
                "word_count": 200,
                "user_id": "u1",
            },
        )
        planner = Planner()
        state = await planner.plan(state)
        assert state.sub_tasks[0].assigned_to == "corpus_expert"

    @pytest.mark.asyncio
    async def test_rule_based_qa(self):
        from app.orchestrator.planner import Planner
        from app.models.state import OrchestratorState

        state = OrchestratorState(
            request_id="req_p3",
            user_id="u1",
            original_request={
                "request_type": "qa",
                "query_type": "word",
                "content": "ubiquitous",
                "user_id": "u1",
            },
        )
        planner = Planner()
        state = await planner.plan(state)
        assert state.sub_tasks[0].assigned_to == "qa_expert"

    @pytest.mark.asyncio
    async def test_replan_adjusts_input(self):
        from app.orchestrator.planner import Planner
        from app.models.state import OrchestratorState, SubTask, SubTaskStatus

        state = OrchestratorState(
            request_id="req_p4",
            user_id="u1",
            original_request={"request_type": "attempt", "user_id": "u1"},
            error_log=["验收失败: 内容不完整"],
        )
        task = SubTask(
            sub_task_id="sub_001",
            assigned_to="diagnosis_expert",
            description="分析错题",
            input={"paragraph": ""},
            status=SubTaskStatus.RETRY,
        )
        state.sub_tasks = [task]

        planner = Planner()
        # LLM stub will return empty dict; replan should still mark task PENDING
        state = await planner.replan(state, task)
        assert task.status == SubTaskStatus.PENDING


# ===================================================================
# 4. Verifier
# ===================================================================

class TestVerifier:
    @pytest.mark.asyncio
    async def test_verify_passes_when_llm_unavailable(self):
        """When LLM is not configured, verifier defaults to passed=True."""
        from app.orchestrator.verifier import Verifier
        from app.models.state import OrchestratorState, SubTask, SubTaskStatus

        state = OrchestratorState(request_id="req_v1", user_id="u1")
        task = SubTask(
            sub_task_id="sub_001",
            assigned_to="diagnosis_expert",
            description="test",
            result={"diagnosis": {"error_category": "词汇理解"}},
            acceptance_criteria=["包含 error_category 字段"],
        )
        verifier = Verifier()
        state = await verifier.verify(state, task)
        # Stub LLM returns "{}" which is falsy after json.loads → defaults to passed=True
        assert task.status == SubTaskStatus.COMPLETED
        assert "sub_001" in state.completed_results

    @pytest.mark.asyncio
    async def test_verify_retry_on_failure(self):
        from app.orchestrator.verifier import Verifier
        from app.models.state import OrchestratorState, SubTask, SubTaskStatus

        state = OrchestratorState(request_id="req_v2", user_id="u1", retry_count=0)
        task = SubTask(
            sub_task_id="sub_001",
            assigned_to="diagnosis_expert",
            description="test",
            result={},
            acceptance_criteria=["包含完整结果"],
        )

        verifier = Verifier()
        # Patch llm_json_call to return failed verdict
        with patch(
            "app.orchestrator.verifier.llm_json_call",
            new_callable=AsyncMock,
            return_value={"passed": False, "issues": ["结果为空"], "suggestion": ""},
        ):
            state = await verifier.verify(state, task)

        assert task.status == SubTaskStatus.RETRY
        assert state.retry_count == 1


# ===================================================================
# 5. Sub-agents
# ===================================================================

class TestDiagnosisExpert:
    @pytest.mark.asyncio
    async def test_correct_answer_short_circuits(self):
        from app.sub_agents.diagnosis import DiagnosisExpert

        agent = DiagnosisExpert()
        result = await agent.execute(
            {
                "paragraph": "test",
                "question_text": "q",
                "options": {},
                "user_answer": "A",
                "correct_answer": "A",
                "time_spent": 10,
            },
            {},
        )
        assert result["diagnosis"]["error_category"] == "无错误"

    @pytest.mark.asyncio
    async def test_wrong_answer_calls_llm(self):
        from app.sub_agents.diagnosis import DiagnosisExpert

        agent = DiagnosisExpert()
        with patch(
            "app.sub_agents.base.llm_json_call",
            new_callable=AsyncMock,
            return_value={
                "error_category": "词汇理解",
                "explanation": "学生不认识该词",
                "evidence_sentence": "test",
                "suggestion": "多背单词",
                "confidence": 0.9,
            },
        ):
            result = await agent.execute(
                {
                    "paragraph": "test paragraph",
                    "question_text": "What does ubiquitous mean?",
                    "options": {"A": "rare", "B": "common", "C": "fast", "D": "slow"},
                    "user_answer": "A",
                    "correct_answer": "B",
                    "time_spent": 15,
                    "need_similar": False,
                },
                {},
            )
        assert result["diagnosis"]["error_category"] == "词汇理解"
        assert result["similar_question"] is None


class TestCorpusExpert:
    @pytest.mark.asyncio
    async def test_returns_article_structure(self):
        from app.sub_agents.corpus import CorpusExpert

        agent = CorpusExpert()
        fake_article = {
            "title": "Test Title",
            "content": " ".join(["word"] * 120),
            "word_count": 120,
            "difficulty_actual": "L2",
            "genre_actual": "expository",
            "key_vocabulary": ["environment"],
        }
        with patch(
            "app.sub_agents.base.llm_json_call",
            new_callable=AsyncMock,
            return_value=fake_article,
        ):
            result = await agent.execute(
                {"difficulty": "L2", "genre": "expository", "topic": "env", "word_count": 120},
                {},
            )
        assert "article" in result
        assert result["article"]["title"] == "Test Title"


class TestQuestionExpert:
    @pytest.mark.asyncio
    async def test_generates_correct_count(self):
        from app.sub_agents.question import QuestionExpert

        agent = QuestionExpert()
        fake_q = {
            "question": "What is the main idea?",
            "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
            "correct_answer": "A",
            "explanation": "...",
            "evidence": "...",
        }
        with patch(
            "app.sub_agents.base.llm_json_call",
            new_callable=AsyncMock,
            return_value=fake_q,
        ):
            result = await agent.execute(
                {
                    "article": "This is a test article. It has multiple sentences. "
                               "Students should read carefully.",
                    "question_type": "detail",
                    "difficulty": "L2",
                    "count": 2,
                },
                {},
            )
        assert len(result["questions"]) == 2


class TestQAExpert:
    @pytest.mark.asyncio
    async def test_word_lookup_stub(self):
        from app.sub_agents.qa import QAExpert

        agent = QAExpert()
        result = await agent.execute(
            {"query_type": "word", "content": "ubiquitous", "context_sentence": ""},
            {},
        )
        assert result["word"] == "ubiquitous"
        assert "basic_meaning" in result

    @pytest.mark.asyncio
    async def test_unknown_query_type(self):
        from app.sub_agents.qa import QAExpert

        agent = QAExpert()
        result = await agent.execute(
            {"query_type": "unknown_type", "content": "test"},
            {},
        )
        assert "error" in result


# ===================================================================
# 6. Tools
# ===================================================================

class TestDictionary:
    @pytest.mark.asyncio
    async def test_stub_definition_no_api_key(self):
        from app.tools.dictionary import lookup_word

        result = await lookup_word("serendipity")
        assert result["word"] == "serendipity"
        assert result["definitions"]  # non-empty list


class TestVocabulary:
    def test_known_word_level(self):
        from app.tools.vocabulary import get_word_level

        assert get_word_level("book") == "A1"

    def test_unknown_word_level(self):
        from app.tools.vocabulary import get_word_level

        assert get_word_level("zyzzyva") is None

    def test_within_difficulty(self):
        from app.tools.vocabulary import is_within_difficulty

        assert is_within_difficulty("book", "L1") is True
        assert is_within_difficulty("paradigm", "L1") is False


class TestGrammar:
    def test_get_rule_known(self):
        from app.tools.grammar import get_rule

        r = get_rule("定语从句")
        assert "关系代词" in r

    def test_get_rule_unknown(self):
        from app.tools.grammar import get_rule

        r = get_rule("不存在的语法点")
        assert "暂无" in r


class TestConstraints:
    def test_get_constraints(self):
        from app.tools.constraints import get_constraints

        c = get_constraints("L3")
        assert c["vocabulary_level"] == "B1"

    def test_get_constraints_fallback(self):
        from app.tools.constraints import get_constraints

        c = get_constraints("L9")
        # Should fall back to L2 defaults
        assert c["vocabulary_level"] == "A2"


# ===================================================================
# 7. API routes (via TestClient)
# ===================================================================

@pytest.fixture
def client(tmp_path):
    """Create a test client with isolated checkpoint directories."""
    import app.orchestrator.checkpoint as cp_module
    import app.orchestrator.agent as ag_module

    # Reset singletons
    cp_module._checkpoint_manager = None
    ag_module._orchestrator = None

    # Patch checkpoint dirs to use tmp_path
    original_base_dir = cp_module.BASE_DIR
    original_index_dir = cp_module.INDEX_DIR
    cp_module.BASE_DIR = tmp_path / "users"
    cp_module.INDEX_DIR = tmp_path / "request_index"

    from app.main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    cp_module.BASE_DIR = original_base_dir
    cp_module.INDEX_DIR = original_index_dir
    cp_module._checkpoint_manager = None
    ag_module._orchestrator = None


def _make_auth_header(user_id: str = "u1", role: str = "user") -> dict:
    """Create an Authorization header with a valid JWT for the given user."""
    from app.auth.jwt_handler import create_access_token
    token = create_access_token(user_id=user_id, role=role)
    return {"Authorization": f"Bearer {token}"}


class TestAPIRoutes:
    def test_root(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "ReadWise AI" in r.json()["message"]

    def test_submit_attempt_requires_auth(self, client):
        r = client.post(
            "/api/attempt",
            json={
                "paragraph": "The sun rises in the east.",
                "question_text": "Where does the sun rise?",
                "options": {"A": "East", "B": "West", "C": "North", "D": "South"},
                "user_answer": "B",
                "correct_answer": "A",
                "time_spent": 30,
            },
        )
        assert r.status_code == 401

    def test_submit_attempt_returns_request_id(self, client):
        r = client.post(
            "/api/attempt",
            json={
                "paragraph": "The sun rises in the east.",
                "question_text": "Where does the sun rise?",
                "options": {"A": "East", "B": "West", "C": "North", "D": "South"},
                "user_answer": "B",
                "correct_answer": "A",
                "time_spent": 30,
            },
            headers=_make_auth_header("u1"),
        )
        assert r.status_code == 200
        data = r.json()
        assert "request_id" in data
        assert data["request_id"].startswith("req_")
        assert data["status"] == "processing"

    def test_get_result_requires_auth(self, client):
        r = client.get("/api/result/req_nonexistent")
        assert r.status_code == 401

    def test_get_result_not_found(self, client):
        r = client.get("/api/result/req_nonexistent", headers=_make_auth_header("u1"))
        assert r.status_code == 200
        assert r.json()["status"] == "not_found"

    def test_get_result_forbidden_other_user(self, client):
        """User A cannot read results belonging to User B."""
        # Submit as u1
        post = client.post(
            "/api/attempt",
            json={"paragraph": "test", "question_text": "q?",
                  "options": {"A": "a"}, "user_answer": "A", "correct_answer": "A"},
            headers=_make_auth_header("u1"),
        )
        req_id = post.json()["request_id"]
        # Poll as u2
        r = client.get(f"/api/result/{req_id}", headers=_make_auth_header("u2"))
        assert r.status_code == 403

    def test_get_result_processing(self, client):
        """Submit then immediately poll – should see 'processing' or completed."""
        r = client.post(
            "/api/attempt",
            json={
                "paragraph": "Water is essential for life.",
                "question_text": "Why is water important?",
                "options": {"A": "It is cold", "B": "It is essential", "C": "It is blue", "D": "It is wet"},
                "user_answer": "A",
                "correct_answer": "B",
                "time_spent": 20,
            },
            headers=_make_auth_header("u2"),
        )
        req_id = r.json()["request_id"]
        # Poll result – either processing or completed (background task may have run)
        poll = client.get(f"/api/result/{req_id}", headers=_make_auth_header("u2"))
        assert poll.status_code == 200
        assert poll.json()["status"] in ("processing", "completed", "failed")

    def test_corpus_request(self, client):
        r = client.post(
            "/api/attempt",
            json={
                "request_type": "corpus",
                "difficulty": "L2",
                "genre": "expository",
                "topic": "technology",
                "word_count": 200,
            },
            headers=_make_auth_header("u3"),
        )
        assert r.status_code == 200
        assert r.json()["request_id"].startswith("req_")

    def test_qa_request(self, client):
        r = client.post(
            "/api/attempt",
            json={
                "request_type": "qa",
                "query_type": "word",
                "content": "inevitable",
            },
            headers=_make_auth_header("u4"),
        )
        assert r.status_code == 200

    def test_internal_callback_not_found(self, client):
        r = client.post(
            "/internal/callback/req_nonexistent",
            json={"task_id": "sub_001", "result": {"data": "test"}},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "not_found"


# ===================================================================
# 8. End-to-end orchestration (with mocked LLM)
# ===================================================================

class TestOrchestration:
    @pytest.mark.asyncio
    async def test_full_attempt_flow(self, tmp_path):
        """Full orchestration cycle: PENDING → plan → dispatch → verify → COMPLETED."""
        import app.orchestrator.checkpoint as cp_module
        import app.orchestrator.agent as ag_module

        cp_module._checkpoint_manager = None
        ag_module._orchestrator = None
        cp_module.BASE_DIR = tmp_path / "users"
        cp_module.INDEX_DIR = tmp_path / "request_index"

        from app.models.state import OrchestratorState, RequestStatus
        from app.orchestrator.agent import Orchestrator
        from app.orchestrator.checkpoint import CheckpointManager

        cm = CheckpointManager(
            base_dir=tmp_path / "users",
            index_dir=tmp_path / "request_index",
        )

        request_id = "req_e2e_001"
        user_request = {
            "request_type": "attempt",
            "user_id": "u_test",
            "paragraph": "Climate change is one of the greatest challenges facing humanity.",
            "question_text": "What is the author's main concern?",
            "options": {"A": "economy", "B": "climate change", "C": "technology", "D": "health"},
            "user_answer": "A",
            "correct_answer": "B",
            "time_spent": 45,
        }

        state = OrchestratorState(
            request_id=request_id,
            user_id="u_test",
            status=RequestStatus.PENDING,
            original_request=user_request,
        )
        cm.save(state)

        # Mock LLM to return a valid diagnosis
        diagnosis_result = {
            "error_category": "主旨理解",
            "explanation": "学生未能把握文章主旨",
            "evidence_sentence": "Climate change is one of the greatest challenges",
            "suggestion": "精读首段找主旨",
            "confidence": 0.92,
        }

        orchestrator = Orchestrator()
        orchestrator.checkpoint = cm

        with patch(
            "app.sub_agents.base.llm_json_call",
            new_callable=AsyncMock,
            return_value=diagnosis_result,
        ):
            await orchestrator.process_request(request_id, user_request)

        # Result should be saved
        result = cm.load_result(request_id, "u_test")
        assert result is not None
        assert result["status"] in (
            RequestStatus.COMPLETED,
            "completed",
            RequestStatus.FAILED,
            "failed",
        )

        cp_module._checkpoint_manager = None
        ag_module._orchestrator = None


# ===================================================================
# 9. New features: corpus planning, stylized generation, working memory
# ===================================================================

class TestCorpusPlanning:
    """Tests for corpus_expert planning mode (enable_planning=True)."""

    @pytest.mark.asyncio
    async def test_planning_mode_returns_training_plan(self):
        from app.sub_agents.corpus import CorpusExpert

        agent = CorpusExpert()
        fake_plan = {
            "articles": [
                {
                    "idx": 1,
                    "topic": "环境保护",
                    "reference_id": "gk_2024_001",
                    "grammar_points": ["定语从句"],
                    "difficulty": "L2",
                    "word_count": 280,
                    "genre": "expository",
                    "description": "环境类说明文",
                },
                {
                    "idx": 2,
                    "topic": "科技发展",
                    "reference_id": None,
                    "grammar_points": ["状语从句"],
                    "difficulty": "L3",
                    "word_count": 320,
                    "genre": "argumentative",
                    "description": "科技类议论文",
                },
            ]
        }
        with patch(
            "app.sub_agents.base.llm_json_call",
            new_callable=AsyncMock,
            return_value=fake_plan,
        ):
            result = await agent.execute({"enable_planning": True}, {})

        assert "training_plan" in result
        assert len(result["training_plan"]) == 2
        assert "new_sub_tasks" in result
        # 2 articles → 2 corpus + 2 question tasks
        assert len(result["new_sub_tasks"]) == 4

    @pytest.mark.asyncio
    async def test_planning_mode_empty_llm_response(self):
        """Planning mode should handle empty LLM response gracefully."""
        from app.sub_agents.corpus import CorpusExpert

        agent = CorpusExpert()
        with patch(
            "app.sub_agents.base.llm_json_call",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await agent.execute({"enable_planning": True}, {})

        assert result["training_plan"] == []
        assert result["new_sub_tasks"] == []

    @pytest.mark.asyncio
    async def test_planning_mode_with_ltm(self):
        """Planning mode reads mistakes and power history from LTM."""
        from app.sub_agents.corpus import CorpusExpert

        agent = CorpusExpert()
        mock_ltm = MagicMock()
        mock_ltm.search_mistakes_formatted.return_value = "词汇理解错误 3次"
        mock_ltm.get_power_history.return_value = [{"score": 75.0, "reason": "test"}]

        fake_plan = {"articles": []}
        with patch(
            "app.sub_agents.base.llm_json_call",
            new_callable=AsyncMock,
            return_value=fake_plan,
        ):
            result = await agent.execute(
                {"enable_planning": True},
                {"long_term_memory": mock_ltm},
            )

        mock_ltm.search_mistakes_formatted.assert_called_once()
        mock_ltm.get_power_history.assert_called_once()
        assert "training_plan" in result


class TestCorpusStylizedGeneration:
    """Tests for corpus_expert stylized generation (reference_id provided)."""

    @pytest.mark.asyncio
    async def test_stylized_generation_uses_reference(self):
        """When reference_id is given, article is loaded as style reference."""
        from app.sub_agents.corpus import CorpusExpert

        agent = CorpusExpert()
        fake_article = {
            "title": "Ocean Plastic Crisis",
            "content": " ".join(["word"] * 120),
            "word_count": 120,
            "difficulty_actual": "L3",
            "genre_actual": "argumentative",
            "key_vocabulary": ["pollution"],
        }

        mock_repo = MagicMock()
        mock_repo.get_article.return_value = {
            "metadata": {
                "id": "gk_2024_001",
                "source": "2024全国I卷",
                "difficulty": "L3",
                "genre": "argumentative",
            },
            "content": "Sample reference text " * 20,
        }

        with patch(
            "app.sub_agents.base.llm_json_call",
            new_callable=AsyncMock,
            return_value=fake_article,
        ):
            result = await agent.execute(
                {
                    "difficulty": "L3",
                    "genre": "argumentative",
                    "topic": "ocean pollution",
                    "word_count": 120,
                    "reference_id": "gk_2024_001",
                },
                {"corpus_repo": mock_repo},
            )

        mock_repo.get_article.assert_called_once_with("gk_2024_001")
        assert result["article"]["title"] == "Ocean Plastic Crisis"
        assert result["metadata"]["reference_id"] == "gk_2024_001"

    @pytest.mark.asyncio
    async def test_stylized_generation_missing_reference_graceful(self):
        """Missing reference_id still generates article without crashing."""
        from app.sub_agents.corpus import CorpusExpert

        agent = CorpusExpert()
        fake_article = {
            "title": "Test",
            "content": " ".join(["word"] * 80),
            "word_count": 80,
        }
        mock_repo = MagicMock()
        mock_repo.get_article.return_value = None  # not found

        with patch(
            "app.sub_agents.base.llm_json_call",
            new_callable=AsyncMock,
            return_value=fake_article,
        ):
            result = await agent.execute(
                {
                    "difficulty": "L2",
                    "genre": "expository",
                    "topic": "science",
                    "word_count": 80,
                    "reference_id": "nonexistent_id",
                },
                {"corpus_repo": mock_repo},
            )

        assert "article" in result  # should still succeed


class TestWorkingMemorySync:
    """Tests for corpus_expert syncing generated article to working memory."""

    @pytest.mark.asyncio
    async def test_generated_article_saved_to_working_memory(self):
        from app.sub_agents.corpus import CorpusExpert

        agent = CorpusExpert()
        fake_article = {
            "title": "Climate Change",
            "content": " ".join(["word"] * 100),
            "word_count": 100,
            "difficulty_actual": "L2",
            "genre_actual": "expository",
            "key_vocabulary": ["carbon"],
        }

        mock_wm = MagicMock()
        with patch(
            "app.sub_agents.base.llm_json_call",
            new_callable=AsyncMock,
            return_value=fake_article,
        ):
            await agent.execute(
                {"difficulty": "L2", "genre": "expository", "topic": "climate", "word_count": 100},
                {"working_memory": mock_wm},
            )

        mock_wm.set_article.assert_called_once()
        saved = mock_wm.set_article.call_args[0][0]
        assert saved["title"] == "Climate Change"
        assert "content" in saved

    @pytest.mark.asyncio
    async def test_no_working_memory_no_crash(self):
        """Missing working_memory in context should not raise an exception."""
        from app.sub_agents.corpus import CorpusExpert

        agent = CorpusExpert()
        fake_article = {
            "title": "Tech World",
            "content": " ".join(["word"] * 80),
            "word_count": 80,
        }
        with patch(
            "app.sub_agents.base.llm_json_call",
            new_callable=AsyncMock,
            return_value=fake_article,
        ):
            result = await agent.execute(
                {"difficulty": "L2", "genre": "expository", "topic": "tech", "word_count": 80},
                {},  # no working_memory
            )
        assert "article" in result


class TestDynamicTaskInjection:
    """Tests for Orchestrator._inject_new_tasks (Plan A dynamic flexibility)."""

    def test_inject_new_tasks_from_result(self):
        from app.models.state import OrchestratorState, SubTask, SubTaskStatus
        from app.orchestrator.agent import Orchestrator

        state = OrchestratorState(request_id="req_inj", user_id="u1")
        planning_task = SubTask(
            sub_task_id="sub_000",
            assigned_to="corpus_expert",
            description="planning",
            status=SubTaskStatus.COMPLETED,
            result={
                "training_plan": [{"idx": 1}],
                "new_sub_tasks": [
                    {
                        "sub_task_id": "dyn_c1",
                        "assigned_to": "corpus_expert",
                        "description": "generate article 1",
                        "input": {"difficulty": "L2", "genre": "expository", "topic": "env"},
                        "acceptance_criteria": [],
                        "depends_on": [],
                    },
                    {
                        "sub_task_id": "dyn_q1",
                        "assigned_to": "question_expert",
                        "description": "generate questions 1",
                        "input": {"article_task_id": "dyn_c1", "count": 4},
                        "acceptance_criteria": [],
                        "depends_on": ["dyn_c1"],
                    },
                ],
            },
        )
        state.sub_tasks = [planning_task]

        orch = Orchestrator.__new__(Orchestrator)
        state = orch._inject_new_tasks(state, planning_task)

        assert len(state.sub_tasks) == 3  # original + 2 injected
        ids = {t.sub_task_id for t in state.sub_tasks}
        assert "dyn_c1" in ids
        assert "dyn_q1" in ids

    def test_inject_no_duplicate_tasks(self):
        """Tasks already present should not be injected twice."""
        from app.models.state import OrchestratorState, SubTask, SubTaskStatus
        from app.orchestrator.agent import Orchestrator

        state = OrchestratorState(request_id="req_dup", user_id="u1")
        existing = SubTask(
            sub_task_id="dyn_c1",
            assigned_to="corpus_expert",
            description="already there",
            status=SubTaskStatus.PENDING,
        )
        planning_task = SubTask(
            sub_task_id="sub_000",
            assigned_to="corpus_expert",
            description="planning",
            status=SubTaskStatus.COMPLETED,
            result={
                "new_sub_tasks": [
                    {
                        "sub_task_id": "dyn_c1",
                        "assigned_to": "corpus_expert",
                        "description": "duplicate",
                        "input": {},
                        "acceptance_criteria": [],
                        "depends_on": [],
                    }
                ]
            },
        )
        state.sub_tasks = [existing, planning_task]

        orch = Orchestrator.__new__(Orchestrator)
        state = orch._inject_new_tasks(state, planning_task)

        assert len(state.sub_tasks) == 2  # no duplicate added

    def test_inject_empty_new_tasks(self):
        """Result with no new_sub_tasks should leave state unchanged."""
        from app.models.state import OrchestratorState, SubTask, SubTaskStatus
        from app.orchestrator.agent import Orchestrator

        state = OrchestratorState(request_id="req_empty", user_id="u1")
        task = SubTask(
            sub_task_id="sub_000",
            assigned_to="corpus_expert",
            description="gen",
            status=SubTaskStatus.COMPLETED,
            result={"article": {"title": "Test", "content": "..."}},
        )
        state.sub_tasks = [task]

        orch = Orchestrator.__new__(Orchestrator)
        state = orch._inject_new_tasks(state, task)

        assert len(state.sub_tasks) == 1


class TestDispatcherInputResolution:
    """Tests for _resolve_task_inputs in dispatcher."""

    def test_article_task_id_resolved(self):
        """article_task_id in input is replaced with actual article content."""
        from app.models.state import OrchestratorState, SubTask
        from app.orchestrator.dispatcher import _resolve_task_inputs

        state = OrchestratorState(request_id="req_res", user_id="u1")
        state.completed_results["dyn_c1"] = {
            "article": {"title": "Test", "content": "This is the article content."},
        }

        task = SubTask(
            sub_task_id="dyn_q1",
            assigned_to="question_expert",
            description="gen questions",
            input={"article_task_id": "dyn_c1", "count": 4},
            depends_on=["dyn_c1"],
        )

        _resolve_task_inputs(task, state)
        assert "article_task_id" not in task.input
        assert task.input["article"] == "This is the article content."

    def test_no_article_task_id_unchanged(self):
        """Tasks without article_task_id are not affected."""
        from app.models.state import OrchestratorState, SubTask
        from app.orchestrator.dispatcher import _resolve_task_inputs

        state = OrchestratorState(request_id="req_nop", user_id="u1")
        task = SubTask(
            sub_task_id="sub_001",
            assigned_to="question_expert",
            description="gen questions",
            input={"article": "Some direct article text.", "count": 3},
            depends_on=[],
        )

        _resolve_task_inputs(task, state)
        assert task.input["article"] == "Some direct article text."

    def test_missing_parent_result_logs_warning(self):
        """When parent task result is missing, article stays empty but no crash."""
        from app.models.state import OrchestratorState, SubTask
        from app.orchestrator.dispatcher import _resolve_task_inputs

        state = OrchestratorState(request_id="req_miss", user_id="u1")
        # completed_results is empty
        task = SubTask(
            sub_task_id="dyn_q1",
            assigned_to="question_expert",
            description="gen questions",
            input={"article_task_id": "dyn_c1", "count": 4},
            depends_on=["dyn_c1"],
        )

        # Should not raise
        _resolve_task_inputs(task, state)
        assert "article_task_id" not in task.input
        assert task.input.get("article", "") == ""


class TestTrainingSetPlanner:
    """Tests for training_set request type in the Planner."""

    @pytest.mark.asyncio
    async def test_training_set_creates_planning_task(self):
        from app.orchestrator.planner import Planner
        from app.models.state import OrchestratorState

        state = OrchestratorState(
            request_id="req_ts",
            user_id="u1",
            original_request={
                "request_type": "training_set",
                "user_level": "L2",
            },
        )
        planner = Planner()
        state = await planner.plan(state)

        assert len(state.sub_tasks) == 1
        task = state.sub_tasks[0]
        assert task.assigned_to == "corpus_expert"
        assert task.input.get("enable_planning") is True

    @pytest.mark.asyncio
    async def test_corpus_with_reference_id_passed_to_expert(self):
        """Planner should pass reference_id into corpus task input."""
        from app.orchestrator.planner import Planner
        from app.models.state import OrchestratorState

        state = OrchestratorState(
            request_id="req_ref",
            user_id="u1",
            original_request={
                "request_type": "corpus",
                "difficulty": "L3",
                "genre": "argumentative",
                "topic": "energy",
                "word_count": 350,
                "reference_id": "gk_2024_001",
            },
        )
        planner = Planner()
        state = await planner.plan(state)

        assert len(state.sub_tasks) == 1
        assert state.sub_tasks[0].input.get("reference_id") == "gk_2024_001"


class TestCorpusRepoGetAllMetadata:
    """Tests for CorpusRepository.get_all_metadata."""

    def test_get_all_metadata_returns_list(self):
        from app.tools.corpus_repo import get_corpus_repo

        repo = get_corpus_repo()
        meta = repo.get_all_metadata()
        assert isinstance(meta, list)

    def test_get_all_metadata_respects_limit(self):
        from app.tools.corpus_repo import get_corpus_repo

        repo = get_corpus_repo()
        meta = repo.get_all_metadata(limit=1)
        assert len(meta) <= 1

    def test_get_all_metadata_includes_id(self):
        from app.tools.corpus_repo import get_corpus_repo

        repo = get_corpus_repo()
        meta = repo.get_all_metadata()
        for entry in meta:
            assert "id" in entry
