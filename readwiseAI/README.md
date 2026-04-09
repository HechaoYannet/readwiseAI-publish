# ReadWise AI

> 基于 FastAPI + 多 Agent 架构的智能高考英语学习系统

ReadWise AI 通过 AI 驱动的多个专家 Sub-Agent，为高中生提供**错题诊断、文章生成、题目生成、问答辅导、遗忘曲线复习**等全流程智能备考服务。

---

## 目录

1. [核心功能](#1-核心功能)
2. [系统架构](#2-系统架构)
3. [项目结构](#3-项目结构)
4. [快速开始](#4-快速开始)
5. [API 总览](#5-api-总览)
   - [认证 API](#51-认证-api)
   - [用户 API](#52-用户-api)
   - [答题 API](#53-答题-api)
   - [长期记忆 API](#54-长期记忆-api)
   - [会话 API](#55-会话-api)
   - [内部 API](#56-内部-api)
6. [request_type 说明](#6-request_type-说明)
7. [Sub-Agent 说明](#7-sub-agent-说明)
8. [记忆系统设计](#8-记忆系统设计)
9. [管理员 CLI](#9-管理员-cli)
10. [外部依赖](#10-外部依赖)
11. [配置与环境变量](#11-配置与环境变量)
12. [测试](#12-测试)
13. [OrchestratorState 数据结构](#13-orchestratorstate-数据结构)
14. [POST /api/attempt 代码分析与结果值流动](#14-post-apiattempt-代码分析与结果值流动)
15. [傻瓜式任务操作指南](#15-傻瓜式任务操作指南)

---

## 1. 核心功能

| 功能 | 说明 |
|------|------|
| **错题诊断** | 分析学生答题错误的根本原因，给出证据句、建议和同类题 |
| **文章生成** | 按难度 L1–L4 × 体裁（议论/说明/记叙）生成高考风格英文文章 |
| **完整训练题组** | 主控 LLM 规划 4 篇文章方案 → 动态注入子任务 → 生成文章+题目全套 |
| **题目生成** | 为指定文章生成细节题/推理题/词义题/主旨题，含答案解析 |
| **智能问答** | 查词、长难句拆解、语法解释、翻译，支持 LangChain 工具调用访问记忆 |
| **错题本** | 持久化存储所有错题，支持关键词/题型/难度筛选 |
| **遗忘曲线** | SM-2 间隔重复算法，自动调度下次复习时间 |
| **训练记录** | 记录每次学习的文章数、正确率、用时、得分等 |
| **战力值历史** | 跟踪学生综合学习能力评分曲线 |
| **用户管理** | 邀请码注册、JWT 认证、密码修改、用户信息管理 |

---

## 2. 系统架构

```
用户请求
   │
   ▼
POST /api/attempt（异步）
   │
   ▼
Orchestrator（主控循环）
   ├── Planner：LLM 任务分解 → 生成 SubTask 列表
   ├── Dispatcher：按依赖顺序逐一分发任务，注入记忆上下文
   │       ├── diagnosis_expert  → 错因分析 + 同类题生成
   │       ├── corpus_expert     → 文章生成（普通/规划/风格化）
   │       ├── question_expert   → 题目生成
   │       └── qa_expert         → 问答（LangChain 工具调用）
   └── Verifier：每个任务执行后立即验证 → 通过则写入 completed_results，失败则立即 Replan

GET /api/result/{request_id}  （轮询结果）
```

**任务调度策略（重构后）：**

| 策略 | 说明 |
|------|------|
| **逐任务调度** | Orchestrator 每次只派发一个满足依赖条件的 PENDING 任务 |
| **立即验证** | 任务执行完成后由 Verifier 立即验收，验收通过才写入 `completed_results` |
| **即时重试** | 验收失败后立即调用 Planner.replan，任务重置为 PENDING 并在下一次迭代重试，无队列末尾排队 |
| **依赖解析** | 任务的依赖项必须在 `completed_results` 中存在才被调度，保证跨任务数据准确注入 |

**记忆层（每次请求前 Dispatcher 自动注入）：**

```
WorkingMemory         ← 会话级（文章、题目、对话）
LongTermMemory        ← 用户级（错题本、遗忘曲线、训练记录、战力值）
CorpusRepo            ← 语料库（真题文章索引）
```

---

## 3. 项目结构

```
readwiseAI/
├── app/
│   ├── main.py                    # FastAPI 入口 (v0.2.0)
│   ├── auth/
│   │   ├── jwt_handler.py         # JWT 生成/验证（7天有效期）
│   │   ├── dependencies.py        # get_current_user / get_admin_user
│   │   ├── models.py              # 请求/响应 Pydantic 模型
│   │   └── password.py            # bcrypt 密码哈希
│   ├── api/routes/
│   │   ├── auth.py                # /api/auth/* 认证接口
│   │   ├── users.py               # /api/users/* 用户接口
│   │   ├── attempts.py            # POST /api/attempt
│   │   ├── results.py             # GET  /api/result/{id}
│   │   ├── memory.py              # /api/memory/* 长期记忆接口
│   │   ├── sessions.py            # /api/sessions/* 工作记忆接口
│   │   └── callback.py            # POST /internal/callback/{id}
│   ├── models/
│   │   ├── state.py               # OrchestratorState / SubTask / AttemptRequest
│   │   ├── user.py                # User + UserStore（JSON 文件存储）
│   │   ├── invite.py              # InviteCode + InviteStore
│   │   ├── working_memory.py      # WorkingMemory（会话级）
│   │   ├── long_term_memory.py    # LongTermMemory 聚合类
│   │   ├── mistakes.py            # MistakeEntry + MistakeBook
│   │   └── forgetting.py          # SM2Item + ForgettingCurve
│   ├── orchestrator/
│   │   ├── agent.py               # Orchestrator 主控循环 + 动态子任务注入
│   │   ├── planner.py             # Planner（LLM分解 + 规则fallback）
│   │   ├── verifier.py            # Verifier（结果验证）
│   │   ├── dispatcher.py          # Dispatcher（记忆注入 + 跨任务引用解析）
│   │   └── checkpoint.py          # 状态持久化（按用户隔离）
│   ├── services/
│   │   ├── llm_service.py         # LLM 调用封装（OpenAI/DeepSeek）
│   │   └── user_service.py        # 用户业务逻辑层
│   ├── sub_agents/
│   │   ├── base.py                # BaseSubAgent（含 load_prompt / _call_llm）
│   │   ├── diagnosis.py           # 错因分析 + 同类题生成
│   │   ├── corpus.py              # 文章生成（普通/规划/风格化）
│   │   ├── question.py            # 题目生成
│   │   └── qa.py                  # 问答（LangChain 工具调用）
│   └── tools/
│       ├── dictionary.py          # 有道词典 API
│       ├── grammar.py             # 语法规则库
│       ├── vocabulary.py          # 词汇等级
│       ├── constraints.py         # 难度约束
│       ├── corpus_repo.py         # 语料库检索
│       └── memory_tools.py        # LangChain @tool 集（6个工具）
├── admin_cli/                     # 管理员 CLI
│   └── commands/
│       ├── invite.py              # 邀请码管理
│       ├── user.py                # 用户管理
│       ├── memory.py              # 记忆管理
│       └── system.py              # 系统状态/备份/健康检查
├── admin.py                       # CLI 入口
├── tests/                         # 测试（pytest）
├── data/
│   ├── prompts/                   # Sub-agent 提示词文件（.txt，热更新）
│   ├── corpus/                    # 语料库（文章 + index.json）
│   ├── working/sessions/{user_id}/ # 工作记忆（按用户隔离）
│   ├── long_term/{user_id}/        # 长期记忆（按用户隔离）
│   │   ├── mistakes.json           # 错题本
│   │   ├── forgetting.json         # SM-2 遗忘曲线状态
│   │   ├── training.json           # 训练记录
│   │   └── power_history.json      # 战力值历史
│   ├── users/users.json            # 用户数据
│   ├── invites/invites.json        # 邀请码
│   └── request_index/              # request_id → user_id 映射
├── docs/
│   └── frontend_follow.md         # 前端开发文档（含所有 API 详情）
├── requirements.txt
└── pytest.ini
```

---

## 4. 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量（开发时可跳过，使用默认值）
export JWT_SECRET_KEY="your-strong-secret-key"   # 生产必须设置
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://api.openai.com/v1"  # 可选，支持代理

# 3. 创建管理员邀请码
python admin.py invite create --max-uses 10

# 4. 启动服务
uvicorn app.main:app --reload --port 8000
```

**访问 API 文档：**
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

## 5. API 总览

> 🔐 = 需要 Bearer JWT Token（`Authorization: Bearer <token>`）

### 5.1 认证 API

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/api/auth/verify-invite` | 无 | 验证邀请码有效性 |
| POST | `/api/auth/register` | 无 | 用邀请码注册，返回 Token |
| POST | `/api/auth/login` | 无 | 用户名/手机/邮箱 + 密码登录 |
| POST | `/api/auth/logout` | 无 | 登出（客户端清除 Token） |
| POST | `/api/auth/refresh` | 🔐 | 刷新 Token（有效期内可刷新） |

### 5.2 用户 API

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET  | `/api/users/me` | 🔐 | 获取当前用户信息 |
| PUT  | `/api/users/me` | 🔐 | 更新用户名/地区/年级/学校 |
| PUT  | `/api/users/password` | 🔐 | 修改密码 |
| GET  | `/api/users/stats` | 🔐 | 获取统计（错题数、战力值等） |

### 5.3 答题 API

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/api/attempt` | 🔐 | 提交请求（异步），返回 request_id |
| GET  | `/api/result/{request_id}` | 🔐 | 轮询处理结果 |

### 5.4 长期记忆 API

#### 训练记录

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET  | `/api/memory/training` | 🔐 | 获取训练记录列表 |
| POST | `/api/memory/training` | 🔐 | 添加训练记录 |

#### 错题本

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET  | `/api/memory/mistakes` | 🔐 | 获取错题列表（支持筛选） |
| GET  | `/api/memory/mistakes/due` | 🔐 | 获取待复习错题 |
| GET  | `/api/memory/mistakes/{id}` | 🔐 | 获取单条错题详情 |
| POST | `/api/memory/mistakes` | 🔐 | 添加错题 |
| PUT  | `/api/memory/mistakes/{id}` | 🔐 | 更新错题字段 |
| DELETE | `/api/memory/mistakes/{id}` | 🔐 | 删除错题 |

#### 遗忘曲线（SM-2）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET  | `/api/memory/curve` | 🔐 | 获取遗忘曲线概况 |
| GET  | `/api/memory/curve/due` | 🔐 | 获取待复习条目 |
| GET  | `/api/memory/curve/{item_id}` | 🔐 | 获取单条 SM-2 状态 |
| POST | `/api/memory/curve/{item_id}/review` | 🔐 | 提交复习质量（0-5） |

#### 战力值历史

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET  | `/api/memory/power` | 🔐 | 获取战力值历史 |
| POST | `/api/memory/power` | 🔐 | 添加战力值记录 |

### 5.5 会话 API

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET  | `/api/sessions` | 🔐 | 获取会话 ID 列表 |
| GET  | `/api/sessions/current` | 🔐 | 获取最近一次会话 |
| GET  | `/api/sessions/{id}` | 🔐 | 获取会话完整数据 |
| GET  | `/api/sessions/{id}/articles` | 🔐 | 获取会话中的文章 |
| GET  | `/api/sessions/{id}/questions` | 🔐 | 获取会话中的题目 |
| GET  | `/api/sessions/{id}/history` | 🔐 | 获取对话历史 |
| GET  | `/api/sessions/{id}/agent-info` | 🔐 | 获取 Agent 运行信息 |
| DELETE | `/api/sessions/{id}` | 🔐 | 删除会话 |

### 5.6 内部 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/internal/callback/{request_id}` | Sub-agent 完成回调（内部使用） |

---

## 6. request_type 说明

`POST /api/attempt` 的 `request_type` 字段决定 AI 执行何种任务：

> **关于 `session_id`：** JSON body 中**必须包含该字段**（`str` 无默认值，不传则 HTTP 422）。传空字符串 `""` 时服务端自动生成随机 ID，建议传有意义的固定字符串便于通过 Session API 查询会话内容。

| request_type | 功能 | 主要输入字段 |
|-------------|------|------------|
| `attempt` | 错题诊断 + 同类题 | `paragraph`, `question_text`, `options`, `user_answer`, `correct_answer`, `time_spent` |
| `corpus` | 生成单篇文章 | `difficulty`(L1-L4), `genre`, `topic`, `word_count`, `reference_id` |
| `question` | 为文章出题 | `article`, `question_type`(单题型), `difficulty`, `count` |
| `qa` | 问答辅导 | `query_type`(word/sentence/grammar/translate/free), `content`, `context_sentence` |
| `training_set` | 完整训练题组（4篇文章+题目） | `user_level` |

> **注意（question 类型）：** 规则 Planner 只转发 `question_type`（单值）给 QuestionExpert，AttemptRequest 中的 `question_types`（列表）不会被规则 fallback Planner 转发。建议使用 `question_type` + `count` 组合。

**示例 – 提交错题分析：**

```json
POST /api/attempt
{
  "request_type": "attempt",
  "session_id": "session_001",
  "paragraph": "Scientists have found that...",
  "question_text": "What is the main idea of the passage?",
  "options": { "A": "...", "B": "...", "C": "...", "D": "..." },
  "user_answer": "A",
  "correct_answer": "C",
  "time_spent": 45,
  "question_number": "A1"
}
```

**示例 – 生成完整训练题组：**

```json
POST /api/attempt
{
  "request_type": "training_set",
  "session_id": "session_train_001",
  "user_level": "L2"
}
```

> 详细字段说明及所有场景示例参见 [`docs/frontend_follow.md`](docs/frontend_follow.md)。

---

## 7. Sub-Agent 说明

### DiagnosisExpert（错因分析专家）

- **输入**：paragraph、question_text、options、user_answer、correct_answer、time_spent
- **输出**：error_category（错误类型）、explanation（错因分析）、evidence_sentence（证据句）、suggestion（学习建议）+ similar_question（同类题）
- **错误类型**：词汇理解 / 推理判断 / 细节查找 / 主旨理解 / 其他

### CorpusExpert（语料生成专家）

三种工作模式：

1. **普通模式**：按 difficulty/genre/topic 生成文章
2. **规划模式**（`enable_planning=True`）：读取语料库 + 用户错题/战力值，规划4篇文章方案，自动注入子任务
3. **风格化模式**（`reference_id` 指定）：以真题为风格参考生成文章

生成文章后自动同步到 WorkingMemory。

### QuestionExpert（出题专家）

- 支持批量出题（一次请求生成多道题）
- 题型：detail（细节题）/ inference（推理题）/ vocabulary（词义题）/ main_idea（主旨题）
- 支持跨任务引用：`article_task_id` 自动从 CorpusExpert 结果中读取文章

### QAExpert（问答专家）

- 结构化模式：word / sentence / grammar / translate
- 自由模式（`free`）：通过 LangChain 工具调用自主访问工作记忆、错题本、语料库

---

## 8. 记忆系统设计

### 工作记忆（WorkingMemory）

- 存储位置：`data/working/sessions/{user_id}/{session_id}.json`
- 会话类型：`training`（学习）/ `chatting`（聊天）
- 内容：articles（文章列表）、question_queue（题目队列）、conversation_history（对话历史）、agent_information（Agent 运行信息）
- 每次 Dispatcher 执行任务前自动加载注入

### 长期记忆（LongTermMemory）

存储位置：`data/long_term/{user_id}/`

| 文件 | 内容 |
|------|------|
| `mistakes.json` | 错题本（MistakeEntry 数组） |
| `forgetting.json` | SM-2 遗忘曲线状态（item_id → SM2Item） |
| `training.json` | 训练记录历史 |
| `power_history.json` | 战力值历史 |

**SM-2 算法说明：**

quality 0–5 对应复习质量（5=完美，0=完全遗忘），算法自动调整：
- `easiness`（难度因子，初始 2.5，最小 1.3）
- `interval_days`（下次复习间隔天数，连续成功后指数增长）
- `next_review_at`（下次复习时间戳）

### 安全设计

所有用户数据路径经过 `_safe_user_dir()` 验证：
- user_id 只允许字母数字、连字符、下划线
- 路径解析后校验在 base_dir 内，防止路径穿越攻击

---

## 9. 管理员 CLI

```bash
# 邀请码管理
python admin.py invite create --max-uses 5 --note "测试用"
python admin.py invite list
python admin.py invite revoke <code>

# 用户管理
python admin.py user list
python admin.py user disable <user_id>
python admin.py user enable <user_id>

# 记忆管理
python admin.py memory stats <user_id>

# 系统
python admin.py system health
python admin.py system stats
python admin.py system backup
```

---

## 10. 外部依赖

### LLM（OpenAI/DeepSeek）

- **使用场景**：所有 Sub-Agent 的推理输出、Planner 任务分解、Verifier 结果验证
- **调用方式**：`app/services/llm_service.py`，支持 `OPENAI_BASE_URL` 自定义（可接入 DeepSeek 等）
- **输出格式**：所有 LLM 调用均要求返回严格 JSON，异常自动捕获并 fallback

### 有道词典 API

- **使用场景**：QAExpert 查词（query_type=word）
- **封装**：`app/tools/dictionary.py`
- **说明**：不需要配置 Key，使用公开接口；LLM 作为补充释义

---

## 11. 配置与环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `JWT_SECRET_KEY` | JWT 签名密钥（生产环境**必须**设置为强随机字符串） | 内置 dev 默认值（不安全） |
| `OPENAI_API_KEY` | OpenAI/DeepSeek API Key | 无（LLM 调用将失败） |
| `OPENAI_BASE_URL` | API 地址（支持代理/国内节点） | OpenAI 官方 URL |
| `OPENAI_MODEL` | 使用的模型名 | `gpt-4o` |

---

## 12. 测试

```bash
# 运行全部测试
python -m pytest tests/ -q

# 运行特定测试模块
python -m pytest tests/test_auth.py -v
python -m pytest tests/test_memory.py -v
python -m pytest tests/test_agent.py -v
```

测试框架：`pytest` + `pytest-asyncio`（`asyncio_mode=auto`）

测试覆盖：JWT 认证、用户注册/登录/密码、错题本、遗忘曲线、工作记忆、Sub-Agent 集成。

---

## 前端开发

详细的接口文档（含所有字段说明、请求/响应示例、典型场景代码）请参见：

📄 **[docs/frontend_follow.md](docs/frontend_follow.md)**

---

---

## 13. OrchestratorState 数据结构

> `app/models/state.py` 中定义的核心状态对象，贯穿整个任务生命周期。

### 13.1 OrchestratorState

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `request_id` | `str` | 必填 | 请求唯一标识，格式 `req_<hex>` |
| `user_id` | `str` | 必填 | 所属用户 ID |
| `session_id` | `Optional[str]` | `None` | 会话 ID，用于关联 WorkingMemory；API 层自动生成 |
| `status` | `RequestStatus` | `PENDING` | 请求整体状态，见下表 |
| `status_history` | `List[str]` | `[]` | 状态变更日志，供前端轮询展示进度 |
| `original_request` | `Dict` | `{}` | 原始请求体（AttemptRequest.model_dump()）|
| `current_plan` | `Dict` | `{}` | Planner 生成的子任务规划（含 overall_goal）|
| `sub_tasks` | `List[SubTask]` | `[]` | 所有子任务列表（含已完成、失败） |
| `completed_results` | `Dict[str, Any]` | `{}` | 已通过验证的子任务结果，key=sub_task_id |
| `retry_count` | `int` | `0` | 全局重试次数（Verifier 累加） |
| `error_log` | `List[str]` | `[]` | 错误和失败原因记录 |
| `created_at` | `datetime` | `now()` | 请求创建时间 |
| `updated_at` | `datetime` | `now()` | 最近更新时间 |
| `working_memory` | `Optional[Dict]` | `None` | 会话级工作记忆（保留字段，由 Dispatcher 注入） |
| `long_term_memory` | `Optional[Dict]` | `None` | 用户级长期记忆（保留字段） |

### 13.2 RequestStatus 枚举

| 值 | 说明 |
|----|------|
| `PENDING` | 初始状态，等待 Planner 规划 |
| `PLANNING` | Planner 正在分解任务 |
| `WAITING` | 等待 Dispatcher 调度任务 |
| `RETRY` | 保留状态（兼容性）；新调度逻辑中重试在 WAITING 内联完成 |
| `COMPLETED` | 所有子任务完成且验收通过 |
| `FAILED` | 存在不可恢复的子任务失败 |

### 13.3 SubTask

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `sub_task_id` | `str` | 必填 | 子任务 ID，如 `sub_001` |
| `assigned_to` | `str` | 必填 | 执行 agent 名称 |
| `description` | `str` | 必填 | 任务描述（Verifier 使用） |
| `input` | `Dict` | `{}` | 传入 agent.execute() 的输入参数 |
| `acceptance_criteria` | `List[str]` | `[]` | 验收标准列表 |
| `depends_on` | `List[str]` | `[]` | 前置依赖的 sub_task_id 列表 |
| `status` | `SubTaskStatus` | `PENDING` | 子任务状态 |
| `result` | `Dict` | `{}` | agent 返回的原始结果 |
| `retry_count` | `int` | `0` | 本任务重试次数 |
| `error_message` | `str` | `""` | 错误信息 |

### 13.4 SubTaskStatus 枚举

| 值 | 说明 |
|----|------|
| `PENDING` | 等待调度 |
| `RUNNING` | 正在执行 |
| `COMPLETED` | 执行完成且验收通过，结果写入 `completed_results` |
| `RETRY` | 验收失败，Planner.replan 后立即重置为 PENDING |
| `FAILED` | 超过最大重试次数，最终失败 |

### 13.5 调度流程说明（重构后）

```
_run() 迭代循环（最多 20 次）：

  PENDING  → Planner.plan()         → WAITING
  WAITING  → 查找下一个满足依赖的 PENDING 任务
             │ 有 → Dispatcher.execute_single()
             │       ├── 成功(COMPLETED) → Verifier.verify()
             │       │     ├── 验收通过 → 写入 completed_results → 注入新子任务
             │       │     └── 验收失败 → Planner.replan() → 任务回到 PENDING（即时重试）
             │       └── 异常(FAILED)  → 继续（等待其他任务）
             └── 无  → _all_tasks_done() ?
                         ├── 有失败 → FAILED
                         └── 全通过 → COMPLETED
  COMPLETED / FAILED → _finalize()
```

**关键改进（相较于旧版本）：**

1. **立即验证**：任务完成后立即调用 Verifier，而非批量等待全队列完成。
2. **依赖正确解析**：`_deps_satisfied` 检查 `completed_results`（已验证的结果），保证 `article_task_id` 等跨任务依赖的数据完整性。
3. **即时重试**：验收失败后立即 replan，任务不再排到队列末尾。

---

## 14. POST /api/attempt 代码分析与结果值流动

> 本节对 `POST /api/attempt` 涉及的全部代码进行逐层分析，梳理各参数情况下的值流动，并给出所有情况下 `GET /api/result` 的 JSON 结构。

---

### 13.1 入口：路由层（app/api/routes/attempts.py）

```
路径：app/api/routes/attempts.py
注册：app/main.py → app.include_router(attempts.router, prefix="/api")
最终路径：POST /api/attempt
```

**逐行执行步骤：**

| 步骤 | 说明 |
|------|------|
| 1 | JWT Bearer Token 验证 → 提取 `user_id`（前端不传，从 Token 解析） |
| 2 | 生成 `request_id`（格式：`req_` + 12位随机 hex，如 `req_a3f7c9b12d4e`） |
| 3 | `session_id = attempt.session_id or "session_" + uuid[:12]`（传空字符串则自动生成） |
| 4 | 创建 `OrchestratorState(status=PENDING)` 并持久化到 `data/users/{user_id}/checkpoints/{request_id}.json` |
| 5 | 将 `orchestrator.process_request` 注册为 FastAPI BackgroundTasks |
| 6 | **立即返回** `{request_id, session_id, status:"processing", result_url}` |

**注意：** `session_id` 在 Pydantic 模型中声明为 `str`（无默认值），是**必填字段**。传空字符串 `""` 时服务端自动生成。

---

### 13.2 AttemptRequest 字段映射（app/models/state.py）

| 字段 | 类型 | 默认值 | 传递给哪个 Sub-Agent |
|------|------|--------|---------------------|
| `request_type` | str | `"attempt"` | Planner 路由判断 |
| `session_id` | str | *(必填)* | WorkingMemory 键 |
| `paragraph` | str | `""` | diagnosis_expert |
| `question_text` | str | `""` | diagnosis_expert |
| `options` | dict | `{}` | diagnosis_expert |
| `user_answer` | str | `""` | diagnosis_expert |
| `correct_answer` | str | `""` | diagnosis_expert |
| `time_spent` | int | `0` | diagnosis_expert |
| `question_number` | str | None | WorkingMemory key suffix（`diagnosis_{question_number}`） |
| `difficulty` | str | None | corpus_expert / question_expert |
| `genre` | str | None | corpus_expert |
| `topic` | str | None | corpus_expert |
| `word_count` | int | None | corpus_expert |
| `reference_id` | str | None | corpus_expert（触发风格化模式） |
| `article` | str | None | question_expert |
| `question_type` | str | None | question_expert（单题型，规则 Planner 转发） |
| `question_types` | list | None | question_expert（多题型，**规则 Planner 不转发**，仅 LLM Planner 可能识别） |
| `count` | int | None | question_expert（默认 3） |
| `query_type` | str | None | qa_expert（word/sentence/grammar/translate/free） |
| `content` | str | None | qa_expert |
| `context_sentence` | str | None | qa_expert（word 模式下补充上下文含义） |
| `user_level` | str | None | corpus_expert 规划模式（L1-L4 整体水平） |
| `enable_planning` | bool | None | corpus_expert（触发规划模式，training_set 时由 Planner 注入） |

---

### 13.3 Orchestrator 主控流程（app/orchestrator/agent.py）

```
process_request()
  → _run(state)，最多迭代 20 次

PENDING → PLANNING:
  Planner.plan(state)
    1. LLM 优先（llm_json_call(PLANNING_PROMPT)）
    2. fallback: _make_rule_based_plan(user_request)
       → 按 request_type 生成 SubTask 列表
  → WAITING

WAITING:
  Dispatcher.dispatch_all_pending(state)
    → 解析 article_task_id 跨任务引用
    → 注入 WorkingMemory + LongTermMemory + CorpusRepo
    → 调用 SubAgent.execute()
  Verifier.verify(state, completed_task)
    → passed=true: completed_results[task_id] = result
    → passed=false + retry_count<2: RETRY
    → passed=false + retry_count>=2: task.status=FAILED
  _inject_new_tasks(state, completed_task)
    → 追加 new_sub_tasks 到 state.sub_tasks（training_set 场景）
  → 所有任务完成: COMPLETED / FAILED

→ _finalize(state):
    _assemble_result() → {request_id, session_id, status, results, error_log}
    checkpoint.save_result() → data/users/{user_id}/results/{request_id}.json
    checkpoint.delete()      → 清理 checkpoints 文件
```

---

### 13.4 各 request_type 的 SubTask 生成规则

| request_type | 规则 Planner 生成的 SubTask | 备注 |
|---|---|---|
| `attempt` | `sub_001` → `diagnosis_expert`，input 包含 paragraph/question_text/options/user_answer/correct_answer/time_spent/need_similar=True | need_similar 始终为 True |
| `corpus` | `sub_001` → `corpus_expert`，input 包含 difficulty/genre/topic/word_count/reference_id/description | reference_id 触发风格化模式 |
| `question` | `sub_001` → `question_expert`，input 包含 article/question_type/difficulty/count | **只转发 question_type，不转发 question_types** |
| `qa` | `sub_001` → `qa_expert`，input 包含 query_type/content/context_sentence | |
| `training_set` | `sub_000` → `corpus_expert(enable_planning=True)` + 动态注入 dyn_c1~c4 / dyn_q1~q4 | sub_000 完成后注入 8 个子任务 |

---

### 13.5 GET /api/result 完整 JSON 结构（所有情况）

**通用外壳（_assemble_result 固定格式）：**

```json
// 处理中
{ "request_id": "req_...", "status": "processing" }

// 完成（error_log 始终存在，成功时为 []）
{
  "request_id": "req_...",
  "session_id": "session_...",
  "status": "completed",
  "results": { /* 见下方 */ },
  "error_log": []
}

// 失败
{
  "request_id": "req_...",
  "status": "failed",
  "results": {},
  "error_log": ["任务sub_001验收失败: [...]"]
}

// 未找到
{ "status": "not_found" }
```

**request_type=attempt 的 results：**
```json
{
  "sub_001": {
    "diagnosis": {
      "error_category": "词汇理解 | 推理判断 | 细节查找 | 主旨理解 | 无错误 | 未知",
      "explanation": "...",
      "evidence_sentence": "...",
      "suggestion": "...",
      "confidence": 0.92
    },
    "similar_question": {
      "paragraph": "...", "question": "...",
      "options": {"A":"...","B":"...","C":"...","D":"..."},
      "correct_answer": "B", "explanation": "..."
    },
    "metadata": { "latency_ms": 2100, "agent": "diagnosis_expert" }
  }
}
```

**request_type=corpus 的 results：**
```json
{
  "sub_001": {
    "article": {
      "title": "...", "content": "...", "word_count": 312,
      "difficulty_actual": "L2", "genre_actual": "expository",
      "key_vocabulary": ["word1","word2"],
      "grammar_highlights": ["定语从句","状语从句"]
    },
    "validation": { "passed": true, "issues": [] },
    "metadata": { "attempts": 1, "latency_ms": 3200, "agent": "corpus_expert", "reference_id": null }
  }
}
```

**request_type=question 的 results：**
```json
{
  "sub_001": {
    "questions": [
      {
        "question_text": "...", "options": {"A":"...","B":"...","C":"...","D":"..."},
        "correct_answer": "C", "explanation": "...", "evidence": "...",
        "type": "detail | inference | vocabulary | main_idea"
      }
    ],
    "metadata": { "latency_ms": 1800, "agent": "question_expert", "count": 3 }
  }
}
```

**request_type=qa 各 query_type 的 results：**

`word`（无 context_sentence）：
```json
{ "sub_001": { "word": "...", "basic_meaning": {"word":"...","translation":"...","success":true}, "metadata": {...} } }
```

`word`（有 context_sentence）：
```json
{ "sub_001": { "word": "...", "basic_meaning": {...}, "context_meaning": "...", "usage_notes": "...", "metadata": {...} } }
```

`sentence`：
```json
{ "sub_001": { "main_clause": "...", "subordinate_clauses": ["..."], "translation": "...", "structure_analysis": "...", "key_grammar_points": ["..."], "metadata": {...} } }
```

`grammar`：
```json
{ "sub_001": { "grammar_point": "...", "explanation": "...", "examples": ["..."], "common_mistakes": ["..."], "metadata": {...} } }
```

`translate`：
```json
{ "sub_001": { "translation": "...", "notes": "...", "metadata": {...} } }
```

`free`（有记忆）：
```json
{ "sub_001": { "answer": "...", "references": ["[工具名]: 结果..."], "tool_calls_made": 2, "metadata": {...} } }
```

`free`（无记忆）：
```json
{ "sub_001": { "answer": "...", "references": [], "follow_up": "...", "metadata": {...} } }
```

**request_type=training_set 的 results（9个键）：**
```json
{
  "sub_000": {
    "training_plan": [
      { "idx": 1, "topic": "...", "reference_id": "gk_2024_001", "grammar_points": ["定语从句"], "difficulty": "L2", "word_count": 280, "genre": "expository", "description": "..." },
      { "idx": 2, ... }, { "idx": 3, ... }, { "idx": 4, ... }
    ],
    "new_sub_tasks": [ /* SubTask dict 列表，前端可忽略 */ ],
    "metadata": { "latency_ms": 3000, "agent": "corpus_expert", "mode": "planning" }
  },
  "dyn_c1": { "article": {...}, "validation": {...}, "metadata": { "agent": "corpus_expert", "reference_id": "..." } },
  "dyn_q1": { "questions": [{...},{...},{...},{...}], "metadata": { "agent": "question_expert", "count": 4 } },
  "dyn_c2": { ... }, "dyn_q2": { ... },
  "dyn_c3": { ... }, "dyn_q3": { ... },
  "dyn_c4": { ... }, "dyn_q4": { ... }
}
```

---

### 13.6 已知问题与注意事项

| 问题 | 位置 | 说明 |
|------|------|------|
| 无用 import | `attempts.py` line 8 | `from pip._internal.network import session` 为无效导入，不影响功能但需清理 |
| pydantic.json 用法 | `diagnosis.py` line 9 | `from pydantic import json` 在 Pydantic v2 中已弃用，应改用 `import json` |
| session_id 必填 | `AttemptRequest` | `session_id` 声明为 `str`（无默认值），Pydantic 校验会拒绝未传该字段的请求（HTTP 422） |
| question_types 未转发 | `planner.py` 规则路径 | 前端传 `question_types` 列表，规则 Planner 只读取 `question_type`（单值），列表被忽略 |
| LLM 降级无告警 | `verifier.py` | LLM 调用失败时默认 passed=true，静默通过，可能导致低质量结果流出 |
| Checkpoint 索引不清理 | `checkpoint.py` | `data/request_index/{request_id}` 文件在 `delete()` 后不会删除，长期运行会积累 |

---

## 15. 傻瓜式任务操作指南

> 详细 JSON 结构示例和通用轮询代码请参见 [docs/frontend_follow.md §13-§14](docs/frontend_follow.md)。

### 任务速查表

| 你想做什么 | request_type | 必填字段 | 结果在哪里 |
|-----------|-------------|---------|-----------|
| 分析做错的题 | `attempt` | `paragraph`, `question_text`, `options`, `user_answer`, `correct_answer` | `results.sub_001.diagnosis` |
| 生成一篇文章 | `corpus` | *(可选填 difficulty/genre/topic)* | `results.sub_001.article` |
| 为文章出题 | `question` | `article` | `results.sub_001.questions` |
| 查单词 | `qa` + `query_type:"word"` | `content`=单词 | `results.sub_001.basic_meaning` |
| 拆解长难句 | `qa` + `query_type:"sentence"` | `content`=句子 | `results.sub_001.main_clause` |
| 语法解释 | `qa` + `query_type:"grammar"` | `content`=问题 | `results.sub_001.grammar_point` |
| 翻译英文 | `qa` + `query_type:"translate"` | `content`=英文 | `results.sub_001.translation` |
| 自由提问 | `qa` + `query_type:"free"` | `content`=问题 | `results.sub_001.answer` |
| 生成完整训练题组 | `training_set` | *(可选填 user_level)* | `results.dyn_c1~c4.article` + `results.dyn_q1~q4.questions` |

所有 request_type 都要传 `session_id`（必填），同一学习任务建议使用同一个 session_id。
