"""State definitions for the Orchestrator and Sub-agents."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RequestStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    WAITING = "waiting"
    RETRY = "retry"
    COMPLETED = "completed"
    FAILED = "failed"


class SubTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    RETRY = "retry"
    FAILED = "failed"


class SubTask(BaseModel):
    sub_task_id: str
    assigned_to: str  # diagnosis_expert / corpus_expert / question_expert / qa_expert
    description: str
    input: Dict[str, Any] = Field(default_factory=dict)
    acceptance_criteria: List[str] = Field(default_factory=list)
    depends_on: List[str] = Field(default_factory=list)
    status: SubTaskStatus = SubTaskStatus.PENDING
    result: Dict[str, Any] = Field(default_factory=dict)
    retry_count: int = 0
    error_message: str = ""


class OrchestratorState(BaseModel):
    request_id: str
    user_id: str
    session_id: Optional[str] = None
    status: RequestStatus = RequestStatus.PENDING
    status_history: List[str] = Field(default_factory=list)
    original_request: Dict[str, Any] = Field(default_factory=dict)
    current_plan: Dict[str, Any] = Field(default_factory=dict)
    sub_tasks: List[SubTask] = Field(default_factory=list)
    completed_results: Dict[str, Any] = Field(default_factory=dict)
    retry_count: int = 0
    error_log: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    # Memory context – populated by the Dispatcher before agent execution
    working_memory: Optional[Dict[str, Any]] = None
    long_term_memory: Optional[Dict[str, Any]] = None


class AttemptRequest(BaseModel):
    paragraph: str = ""
    question_text: str = ""
    options: Dict[str, str] = Field(default_factory=dict)
    user_answer: str = ""
    correct_answer: str = ""
    time_spent: int = 0
    # Optional overrides for corpus / question / qa requests
    request_type: str = "attempt"  # attempt | corpus | question | qa | training_set
    query_type: Optional[str] = None  # for qa: word/sentence/grammar/translate/free
    content: Optional[str] = None  # for qa queries
    context_sentence: Optional[str] = None
    difficulty: Optional[str] = None  # L1/L2/L3/L4
    genre: Optional[str] = None  # argumentative/expository/narrative
    topic: Optional[str] = None
    word_count: Optional[int] = None
    article: Optional[str] = None
    question_type: Optional[str] = None  # detail/inference/vocabulary/main_idea
    question_types: Optional[List[str]] = None  # list of question types for multi-question
    count: Optional[int] = None
    session_id: str = ""  # session identifier for working memory
    # Corpus expert extended options
    enable_planning: Optional[bool] = None  # training_set: trigger corpus planning mode
    reference_id: Optional[str] = None  # corpus article ID for stylized generation
    user_level: Optional[str] = None  # overall user level hint for planning
    question_number: Optional[str] = None  # for conveniently managing and recording questions, e.g. "A1", "C4", etc.
