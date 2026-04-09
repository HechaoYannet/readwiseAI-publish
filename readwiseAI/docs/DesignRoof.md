ReadWise AI - 完整Agent架构设计（异步+Sub-agent）

基于确认：异步+Checkpoint | 4个粗粒度Sub-agent | DeepSeek做Planner | 重试2次+调整输入 | 够用主义持久化

---

一、架构全景图

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                   用户请求                                       │
│                        POST /api/attempt, GET /api/generate                     │
└─────────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              API Layer (FastAPI)                                │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │  立即返回: {"request_id": "req_xxx", "status": "processing"}            │   │
│  │  后续通过 GET /api/result/{request_id} 轮询获取结果                       │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          主控Agent (Orchestrator)                               │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         Planner (LLM驱动)                               │   │
│  │  - 理解用户意图                                                         │   │
│  │  - 拆解为子任务清单（最多5个子任务）                                      │   │
│  │  - 定义验收标准                                                         │   │
│  │  - 处理重试时的输入调整                                                   │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                          │                                      │
│                                          ▼                                      │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                    Dispatcher + Checkpoint Manager                      │   │
│  │  - 异步派发任务给Sub-agent                                               │   │
│  │  - 序列化状态到持久化存储                                                 │   │
│  │  - 注册回调，主控释放资源                                                 │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                          │                                      │
│                                          ▼                                      │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         Verifier (LLM驱动)                              │   │
│  │  - 验收Sub-agent返回结果                                                 │   │
│  │  - 判断完成度 → 通过/重试/失败                                            │   │
│  │  - 生成下一轮规划所需的上下文                                              │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
        │                       │                       │                       │
        ▼                       ▼                       ▼                       ▼
┌───────────────┐       ┌───────────────┐       ┌───────────────┐       ┌───────────────┐
│  诊断专家      │       │  语料专家      │       │  出题专家      │       │  问答专家      │
│  (Diagnosis)  │       │  (Corpus)     │       │ (Question)    │       │   (QA)        │
├───────────────┤       ├───────────────┤       ├───────────────┤       ├───────────────┤
│ • 错因分析     │       │ • 文章生成     │       │ • 题目生成     │       │ • 查词         │
│ • 同类题生成   │       │ • 难度控制     │       │ • 选项设计     │       │ • 长难句拆解   │
│ • 修复建议     │       │ • 体裁适配     │       │ • 答案生成     │       │ • 语法解释     │
│ • 证据定位     │       │ • 约束验证     │       │ • 干扰项设计   │       │ • 翻译         │
└───────────────┘       └───────────────┘       └───────────────┘       └───────────────┘
        │                       │                       │                       │
        └───────────────────────┼───────────────────────┼───────────────────────┘
                                │                       │
                                ▼                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              共享工具层                                          │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐          │
│  │ 有道词典API   │ │ 考纲词汇库   │ │ 语法规则库   │ │ 题型模板库   │          │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘          │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                           │
│  │ Few-shot库   │ │ 约束规则库   │ │ 战力值DB     │                           │
│  └──────────────┘ └──────────────┘ └──────────────┘                           │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

二、数据模型设计

2.1 核心数据结构

```python
# 请求状态
class RequestStatus:
    PENDING = "pending"      # 刚收到，等待规划
    PLANNING = "planning"    # 正在规划
    WAITING = "waiting"      # 等待Sub-agent返回
    COMPLETED = "completed"  # 完成
    FAILED = "failed"        # 失败

# 子任务状态
class SubTaskStatus:
    PENDING = "pending"      # 等待派发
    RUNNING = "running"      # 执行中
    COMPLETED = "completed"  # 完成
    RETRY = "retry"          # 需要重试
    FAILED = "failed"        # 失败

# 主控状态（持久化）
class OrchestratorState:
    request_id: str
    user_id: str
    status: RequestStatus
    original_request: dict           # 原始用户请求
    current_plan: dict               # 当前任务规划
    sub_tasks: List[SubTask]         # 子任务列表
    completed_results: dict          # 已完成任务的结果
    retry_count: int                 # 当前重试次数
    error_log: List[str]             # 错误记录
    created_at: datetime
    updated_at: datetime

# 子任务
class SubTask:
    sub_task_id: str
    assigned_to: str                 # diagnosis/corpus/question/qa
    description: str
    input: dict
    acceptance_criteria: List[str]
    depends_on: List[str]            # 依赖的子任务ID
    status: SubTaskStatus
    result: dict                     # 执行结果
    retry_count: int
    error_message: str
```

2.2 持久化存储（够用主义）

```python
# 内测期使用 SQLite + 本地文件，不引入Redis

存储方案：
├── data/
│   ├── checkpoints/                 # 主控状态Checkpoint
│   │   ├── req_xxx.json
│   │   └── req_yyy.json
│   ├── results/                     # 最终结果缓存
│   │   └── req_xxx.json
│   └── tasks/                       # 任务队列（文件系统模拟）
│       ├── pending/                 # 待处理任务
│       │   └── task_xxx.json
│       └── processing/              # 处理中任务
│           └── task_xxx.json

优点：简单、无额外依赖、内测够用
缺点：不适合高并发（内测<5人，完全够用）
```

---

三、主控Agent详细设计

3.1 主控工作流

```python
class Orchestrator:
    """主控Agent - 异步+Checkpoint"""
    
    async def process_request(self, request_id: str, user_request: dict):
        """处理用户请求的入口"""
        
        # 1. 加载或创建状态
        state = self._load_state(request_id)
        if not state:
            state = self._create_state(request_id, user_request)
        
        # 2. 根据当前状态决定动作
        while True:
            if state.status == RequestStatus.PENDING:
                # 首次处理：需要规划
                state = await self._plan(state)
                state.status = RequestStatus.WAITING
            
            elif state.status == RequestStatus.WAITING:
                # 检查是否有子任务完成
                completed = self._check_completed_subtasks(state)
                if completed:
                    # 有任务完成，需要验收
                    state = await self._verify(state, completed)
                    if state.status == RequestStatus.COMPLETED:
                        break
                else:
                    # 没有完成的任务，派发待处理的子任务
                    self._dispatch_pending(state)
                    # 保存Checkpoint，主控下线
                    self._save_checkpoint(state)
                    return  # 主控释放，等待回调
            
            elif state.status == RequestStatus.RETRY:
                # 重试：调整输入，重新规划
                state = await self._replan(state)
                state.status = RequestStatus.WAITING
            
            elif state.status == RequestStatus.FAILED:
                break
        
        # 3. 完成：保存结果
        self._save_result(state)
    
    async def _plan(self, state: OrchestratorState) -> OrchestratorState:
        """Planner: LLM生成任务规划"""
        
        prompt = self._build_planning_prompt(state)
        response = await self.llm.ainvoke(prompt)
        plan = self._parse_plan(response)
        
        # 更新状态
        state.current_plan = plan
        state.sub_tasks = plan["sub_tasks"]
        state.status = RequestStatus.WAITING
        
        return state
    
    async def _verify(self, state: OrchestratorState, completed_task: SubTask) -> OrchestratorState:
        """Verifier: LLM验收任务结果"""
        
        prompt = self._build_verification_prompt(completed_task)
        response = await self.llm.ainvoke(prompt)
        verdict = self._parse_verdict(response)
        
        if verdict["passed"]:
            # 验收通过
            completed_task.status = SubTaskStatus.COMPLETED
            state.completed_results[completed_task.sub_task_id] = completed_task.result
            
            # 检查是否所有任务都完成
            if self._all_tasks_completed(state):
                state.status = RequestStatus.COMPLETED
        
        elif state.retry_count < 2:
            # 需要重试
            completed_task.status = SubTaskStatus.RETRY
            state.retry_count += 1
            state.status = RequestStatus.RETRY
            state.error_log.append(f"任务{completed_task.sub_task_id}验收失败: {verdict['issues']}")
        
        else:
            # 重试次数用尽
            completed_task.status = SubTaskStatus.FAILED
            state.status = RequestStatus.FAILED
            state.error_log.append(f"任务{completed_task.sub_task_id}最终失败")
        
        return state
```

3.2 Planner的LLM Prompt设计

```python
PLANNING_PROMPT = """
你是ReadWise AI的主控Agent。你的职责是将用户请求拆解为可执行的子任务。

## 可用的Sub-agent
1. **diagnosis_expert**: 错因分析专家
   - 能力：分析错题原因、定位证据句、生成修复建议、生成同类题
   - 适用场景：学生做错了题需要分析、需要同类题训练

2. **corpus_expert**: 语料专家
   - 能力：生成高考风格文章、控制难度(L1-L4)、控制体裁(议论文/说明文/记叙文)
   - 适用场景：需要生成新文章、需要难度适配的阅读材料

3. **question_expert**: 出题专家
   - 能力：基于文章生成题目、设计选项、生成答案
   - 适用场景：需要为文章配题、需要专项题型训练

4. **qa_expert**: 问答专家
   - 能力：查词释义、长难句拆解、语法解释、翻译
   - 适用场景：学生提问单词/句子/语法

## 输出格式（严格JSON）
{
  "overall_goal": "任务总体目标",
  "sub_tasks": [
    {
      "sub_task_id": "sub_001",
      "assigned_to": "diagnosis_expert",
      "description": "具体要做什么",
      "input": {
        // 传给Sub-agent的参数
      },
      "acceptance_criteria": [
        "验收标准1",
        "验收标准2"
      ],
      "depends_on": []  // 依赖的其他sub_task_id
    }
  ]
}

## 用户请求
{user_request}

## 上下文
{context}

请输出JSON格式的规划结果：
"""
```

3.3 Verifier的LLM Prompt设计

```python
VERIFICATION_PROMPT = """
你是任务验收专家。判断Sub-agent返回的结果是否满足要求。

## 任务描述
{sub_task_description}

## 验收标准
{acceptance_criteria}

## Sub-agent返回结果
{sub_task_result}

## 输出格式（严格JSON）
{
  "passed": true/false,
  "completion_score": 0.95,
  "issues": ["如果未通过，说明具体问题"],
  "suggestion": "如果未通过，建议如何调整输入参数"
}

请输出JSON格式的验收结论：
"""
```

---

四、Sub-agent设计

4.1 统一接口规范

```python
class BaseSubAgent:
    """Sub-agent基类"""
    
    name: str
    description: str
    
    async def execute(self, input: dict, context: dict) -> dict:
        """
        执行任务
        
        Args:
            input: 任务输入参数
            context: 上下文（用户信息、依赖任务结果等）
        
        Returns:
            {
                "result": {...},      # 任务结果
                "metadata": {         # 元数据
                    "llm_calls": 2,
                    "total_tokens": 1500,
                    "latency_ms": 3200
                },
                "confidence": 0.92    # 自信度（可选）
            }
        """
        raise NotImplementedError
    
    def _call_llm(self, prompt: str):
        """调用LLM（共享）"""
        pass
    
    def _lookup_word(self, word: str, context: str):
        """查词典（共享工具）"""
        pass
```

4.2 诊断专家内部设计

```python
class DiagnosisExpert(BaseSubAgent):
    """诊断专家"""
    
    name = "diagnosis_expert"
    description = "错因分析、同类题生成"
    
    async def execute(self, input: dict, context: dict) -> dict:
        """
        input 包含:
            paragraph: 原文段落
            question_text: 题目
            options: 选项
            user_answer: 学生答案
            correct_answer: 正确答案
            time_spent: 用时
        """
        
        # 步骤1: 错因分析
        diagnosis = await self._analyze_error(input)
        
        # 步骤2: 如果需要生成同类题
        if input.get("need_similar", True):
            similar = await self._generate_similar(input, diagnosis)
        else:
            similar = None
        
        return {
            "diagnosis": diagnosis,
            "similar_question": similar
        }
    
    async def _analyze_error(self, input: dict) -> dict:
        """错因分析内部实现"""
        
        # 1. 先尝试规则匹配（快速）
        rule_result = self._rule_based_analysis(input)
        if rule_result["confidence"] > 0.8:
            return rule_result
        
        # 2. 调用LLM深度分析
        prompt = self._build_diagnosis_prompt(input)
        response = await self._call_llm(prompt)
        
        # 3. 用词典验证关键词
        if "vocabulary" in response.get("error_category", ""):
            # 验证生词确实在原文中
            pass
        
        return response
```

4.3 语料专家内部设计

```python
class CorpusExpert(BaseSubAgent):
    """语料专家"""
    
    name = "corpus_expert"
    description = "文章生成、难度控制"
    
    async def execute(self, input: dict, context: dict) -> dict:
        """
        input 包含:
            difficulty: L1/L2/L3/L4
            genre: argumentative/expository/narrative
            topic: 可选主题
            word_count: 目标字数
        """
        
        # 步骤1: 加载约束
        constraints = self._load_constraints(input["difficulty"])
        
        # 步骤2: 选择Few-shot示例
        examples = self._select_examples(input["genre"], input["difficulty"])
        
        # 步骤3: 生成文章（带重试）
        for attempt in range(3):
            article = await self._generate_article(input, constraints, examples)
            
            # 验证
            validation = self._validate_article(article, constraints)
            if validation["passed"]:
                return {
                    "article": article,
                    "validation": validation,
                    "metadata": {"attempts": attempt + 1}
                }
            
            # 调整输入（收紧约束）
            constraints = self._tighten_constraints(constraints, validation["issues"])
        
        # 最终返回（即使未完全通过）
        return {
            "article": article,
            "validation": validation,
            "metadata": {"attempts": 3, "partial": True}
        }
```

4.4 出题专家内部设计

```python
class QuestionExpert(BaseSubAgent):
    """出题专家"""
    
    name = "question_expert"
    description = "题目生成、选项设计"
    
    async def execute(self, input: dict, context: dict) -> dict:
        """
        input 包含:
            article: 文章内容
            question_type: detail/inference/vocabulary
            difficulty: L1/L2/L3/L4
            count: 题目数量
        """
        
        questions = []
        
        for i in range(input.get("count", 3)):
            # 逐个生成题目
            q = await self._generate_single_question(input, context)
            questions.append(q)
        
        return {"questions": questions}
    
    async def _generate_single_question(self, input: dict, context: dict) -> dict:
        """生成单题"""
        
        # 1. 从文章中选择锚点句子
        anchor = self._select_anchor(input["article"], input["question_type"])
        
        # 2. 生成题目
        prompt = self._build_question_prompt(anchor, input)
        response = await self._call_llm(prompt)
        
        # 3. 验证答案在原文中有依据
        if not self._verify_answer_in_article(response["answer"], input["article"]):
            # 重新生成
            response = await self._regenerate_with_feedback(prompt, "答案必须在原文中有依据")
        
        return response
```

4.5 问答专家内部设计

```python
class QAExpert(BaseSubAgent):
    """问答专家"""
    
    name = "qa_expert"
    description = "查词、长难句拆解、语法解释、翻译"
    
    async def execute(self, input: dict, context: dict) -> dict:
        """
        input 包含:
            query_type: word/sentence/grammar/translate
            content: 查询内容
            context_sentence: 上下文句子（查词时需要）
        """
        
        if input["query_type"] == "word":
            return await self._lookup_word(input["content"], input.get("context_sentence"))
        
        elif input["query_type"] == "sentence":
            return await self._parse_sentence(input["content"])
        
        elif input["query_type"] == "grammar":
            return await self._explain_grammar(input["content"])
        
        elif input["query_type"] == "translate":
            return await self._translate(input["content"])
    
    async def _lookup_word(self, word: str, context: str) -> dict:
        """查词 - 可能调用多个工具"""
        
        # 1. 调用有道API获取基础释义
        basic = await self._call_youdao(word)
        
        # 2. 如果提供了上下文，用LLM判断具体义项
        if context:
            llm_result = await self._call_llm(
                f"单词'{word}'在以下上下文中的具体含义是什么？\n上下文：{context}\n基础释义：{basic}"
            )
            return {
                "word": word,
                "basic_meaning": basic,
                "context_meaning": llm_result,
                "cefr_level": self._get_cefr_level(word)
            }
        
        return {"word": word, "meaning": basic}
```

---

五、异步+Checkpoint实现

5.1 状态持久化

```python
class CheckpointManager:
    """Checkpoint管理器（文件系统实现）"""
    
    def __init__(self, checkpoint_dir: str = "data/checkpoints"):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    
    def save(self, state: OrchestratorState):
        """保存状态"""
        path = self.checkpoint_dir / f"{state.request_id}.json"
        with open(path, "w") as f:
            json.dump(state.dict(), f, default=str)
    
    def load(self, request_id: str) -> Optional[OrchestratorState]:
        """加载状态"""
        path = self.checkpoint_dir / f"{request_id}.json"
        if not path.exists():
            return None
        with open(path, "r") as f:
            data = json.load(f)
        return OrchestratorState(**data)
    
    def delete(self, request_id: str):
        """删除状态（完成后清理）"""
        path = self.checkpoint_dir / f"{request_id}.json"
        if path.exists():
            path.unlink()
```

5.2 任务队列（文件系统模拟）

```python
class TaskQueue:
    """简单任务队列（文件系统模拟）"""
    
    def __init__(self, queue_dir: str = "data/tasks"):
        self.pending_dir = Path(queue_dir) / "pending"
        self.processing_dir = Path(queue_dir) / "processing"
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self.processing_dir.mkdir(parents=True, exist_ok=True)
    
    def enqueue(self, task: dict):
        """入队"""
        task_id = task["task_id"]
        path = self.pending_dir / f"{task_id}.json"
        with open(path, "w") as f:
            json.dump(task, f)
    
    def dequeue(self) -> Optional[dict]:
        """出队（取一个待处理任务）"""
        pending = list(self.pending_dir.glob("*.json"))
        if not pending:
            return None
        
        # 取第一个
        path = pending[0]
        with open(path, "r") as f:
            task = json.load(f)
        
        # 移动到processing
        path.rename(self.processing_dir / path.name)
        
        return task
    
    def complete(self, task_id: str, result: dict):
        """完成任务"""
        path = self.processing_dir / f"{task_id}.json"
        if path.exists():
            with open(path, "r") as f:
                task = json.load(f)
            task["result"] = result
            task["completed_at"] = datetime.now().isoformat()
            path.unlink()  # 删除
            return task
        
        return None
```

5.3 API层集成

```python
# FastAPI路由
from fastapi import FastAPI, BackgroundTasks

app = FastAPI()

# 内存中存储结果（简单）
results_cache = {}

@app.post("/api/attempt")
async def submit_attempt(
    attempt: AttemptRequest,
    background_tasks: BackgroundTasks
):
    """提交答案 - 立即返回request_id"""
    
    request_id = generate_request_id()
    
    # 初始化状态
    state = OrchestratorState(
        request_id=request_id,
        user_id=attempt.user_id,
        status=RequestStatus.PENDING,
        original_request=attempt.dict(),
        created_at=datetime.now()
    )
    
    # 保存初始Checkpoint
    checkpoint_manager.save(state)
    
    # 异步处理
    background_tasks.add_task(
        orchestrator.process_request,
        request_id,
        attempt.dict()
    )
    
    return {
        "request_id": request_id,
        "status": "processing",
        "result_url": f"/api/result/{request_id}"
    }

@app.get("/api/result/{request_id}")
async def get_result(request_id: str):
    """轮询获取结果"""
    
    # 先查缓存
    if request_id in results_cache:
        return results_cache[request_id]
    
    # 查Checkpoint
    state = checkpoint_manager.load(request_id)
    if not state:
        return {"status": "not_found"}
    
    if state.status == RequestStatus.COMPLETED:
        # 组装结果
        result = assemble_result(state)
        results_cache[request_id] = result
        # 清理Checkpoint
        checkpoint_manager.delete(request_id)
        return result
    
    elif state.status == RequestStatus.FAILED:
        return {"status": "failed", "error": state.error_log}
    
    else:
        return {"status": "processing"}
```

5.4 Sub-agent回调

```python
# Sub-agent完成任务后调用主控回调
@app.post("/internal/callback/{request_id}")
async def subagent_callback(request_id: str, callback_data: dict):
    """Sub-agent完成任务后的回调"""
    
    # 加载状态
    state = checkpoint_manager.load(request_id)
    if not state:
        return {"status": "not_found"}
    
    # 更新子任务结果
    task_id = callback_data["task_id"]
    for sub_task in state.sub_tasks:
        if sub_task.sub_task_id == task_id:
            sub_task.result = callback_data["result"]
            sub_task.status = SubTaskStatus.COMPLETED
            break
    
    # 保存状态
    checkpoint_manager.save(state)
    
    # 唤醒主控继续处理
    # 这里可以触发一个后台任务继续处理
    background_tasks.add_task(
        orchestrator.resume_processing,
        request_id
    )
    
    return {"status": "ok"}
```

---

六、重试与调整输入机制

6.1 重试流程

```python
async def _replan(self, state: OrchestratorState) -> OrchestratorState:
    """重试：基于验收反馈调整输入"""
    
    # 获取失败的任务
    failed_task = next(
        t for t in state.sub_tasks 
        if t.status == SubTaskStatus.RETRY
    )
    
    # 获取验收反馈
    feedback = state.error_log[-1]
    
    # 让LLM调整输入参数
    prompt = f"""
之前的任务失败了，需要调整输入后重试。

## 原任务
{failed_task.description}

## 原输入
{failed_task.input}

## 失败原因
{feedback}

## 请输出调整后的输入（JSON格式）
调整策略：
- 如果是信息不足，补充缺失信息
- 如果是格式问题，修正格式
- 如果是内容问题，简化或调整
"""
    
    response = await self.llm.ainvoke(prompt)
    adjusted_input = json.loads(response.content)
    
    # 更新任务输入
    failed_task.input = adjusted_input
    failed_task.status = SubTaskStatus.PENDING
    
    return state
```

6.2 重试限制

重试次数 行为
第1次 调整输入，重新派发
第2次 调整输入，重新派发
第3次 放弃，标记FAILED，返回部分结果

---

七、目录结构（最终版）

```
backend/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── routes/
│   │   │   ├── attempts.py      # POST /api/attempt
│   │   │   ├── results.py       # GET /api/result/{id}
│   │   │   └── callback.py      # POST /internal/callback/{id}
│   │   └── deps.py
│   │
│   ├── orchestrator/             # 主控Agent
│   │   ├── __init__.py
│   │   ├── agent.py              # Orchestrator主类
│   │   ├── planner.py            # Planner (LLM)
│   │   ├── verifier.py           # Verifier (LLM)
│   │   ├── dispatcher.py         # 任务派发
│   │   ├── checkpoint.py         # Checkpoint管理
│   │   └── state.py              # 状态定义
│   │
│   ├── sub_agents/               # Sub-agent
│   │   ├── __init__.py
│   │   ├── base.py               # 基类
│   │   ├── diagnosis.py          # 诊断专家
│   │   ├── corpus.py             # 语料专家
│   │   ├── question.py           # 出题专家
│   │   └── qa.py                 # 问答专家
│   │
│   ├── tools/                    # 共享工具
│   │   ├── __init__.py
│   │   ├── dictionary.py         # 有道词典
│   │   ├── vocabulary.py         # 考纲词汇库
│   │   ├── grammar.py            # 语法规则库
│   │   └── constraints.py        # 约束规则库
│   │
│   ├── services/
│   │   └── llm_service.py        # LLM统一调用
│   │
│   └── models/                   # 数据模型
│       ├── database.py
│       ├── attempt.py
│       └── ...
│
├── data/                         # 数据目录
│   ├── checkpoints/              # 状态Checkpoint
│   ├── results/                  # 结果缓存
│   ├── tasks/                    # 任务队列
│   │   ├── pending/
│   │   └── processing/
│   └── sqlite/                   # SQLite数据库
│
└── tests/
    └── ...
```

---

八、关键文件清单

文件 职责 代码量估算
orchestrator/agent.py 主控主循环 ~200行
orchestrator/planner.py LLM规划 ~80行
orchestrator/verifier.py LLM验收 ~80行
orchestrator/checkpoint.py 状态持久化 ~60行
sub_agents/base.py Sub-agent基类 ~40行
sub_agents/diagnosis.py 诊断专家 ~150行
sub_agents/corpus.py 语料专家 ~120行
sub_agents/question.py 出题专家 ~100行
sub_agents/qa.py 问答专家 ~80行
tools/dictionary.py 有道词典封装 ~50行
api/routes/attempts.py API入口 ~60行
api/routes/results.py 结果轮询 ~40行
总计  ~1060行

---

九、内测验证清单

场景 验证点
错因分析 提交错题 → 返回诊断结果 → 验收通过 → 返回前端
文章生成 请求L2议论文 → 语料专家生成 → 验证通过 → 返回
题目生成 基于文章生成3道题 → 出题专家生成 → 验证通过
查词 点击单词 → 问答专家 → 返回释义+上下文义项
重试场景 故意给错误输入 → 验收失败 → 重试2次 → 最终返回
并发 5个用户同时请求 → 各自独立处理 → 不互相干扰

---

以上是完整的异步+Sub-agent架构设计。确认后，我可以继续生成：

· 核心代码实现（按文件逐个生成）
· LLM Prompt完整版本（Planner/Verifier及各Sub-agent）
· 测试用例设计（单元测试+集成测试）
