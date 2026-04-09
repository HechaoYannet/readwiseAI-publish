# ReadWise AI – 前端开发文档

> 本文档面向前端开发者，涵盖认证流程、所有 API 端点的请求/响应格式、错误规范及常见开发场景。

---

## 目录

1. [基础信息](#1-基础信息)
2. [认证机制](#2-认证机制)
3. [Auth API – 认证与注册](#3-auth-api--认证与注册)
4. [Users API – 用户管理](#4-users-api--用户管理)
5. [Attempt API – 提交答题](#5-attempt-api--提交答题)
6. [Result API – 轮询结果](#6-result-api--轮询结果)
7. [Memory API – 长期记忆](#7-memory-api--长期记忆)
   - [训练记录](#71-训练记录)
   - [错题本](#72-错题本)
   - [遗忘曲线（SM-2）](#73-遗忘曲线sm-2)
   - [战力值历史](#74-战力值历史)
8. [Sessions API – 工作记忆会话](#8-sessions-api--工作记忆会话)
9. [错误码规范](#9-错误码规范)
10. [典型开发场景示例](#10-典型开发场景示例)
11. [request_type 速查表](#11-request_type-速查表)
12. [环境变量与部署](#12-环境变量与部署)
13. [GET /api/result 所有情况的完整 JSON 结构](#13-get-apiresult-所有情况的完整-json-结构)
14. [傻瓜式任务操作指南](#14-傻瓜式任务操作指南)

---

## 1. 基础信息

| 项目       | 值                                  |
|-----------|-------------------------------------|
| 基础 URL   | `http://localhost:8000`             |
| API 前缀   | `/api`                              |
| 内部前缀   | `/internal`                         |
| 数据格式   | `application/json`                  |
| 认证方式   | Bearer JWT（Authorization Header）  |
| 字符集     | UTF-8                               |

---

## 2. 认证机制

所有需要登录的接口都需要在 HTTP Header 中携带 JWT Token：

```http
Authorization: Bearer <access_token>
```

### Token 生命周期

- 有效期：**7 天**
- 建议在剩余有效期 **< 3 天** 时调用 `/api/auth/refresh` 刷新 Token
- Token 中包含 `user_id` 和 `role`（`user` 或 `admin`），无需额外传递

---

## 3. Auth API – 认证与注册

### 3.1 验证邀请码

**POST** `/api/auth/verify-invite`

```json
// Request
{ "invite_code": "INV-XXXX" }

// Response 200
{ "valid": true, "message": "邀请码有效" }

// Response 200 (invalid)
{ "valid": false, "message": "邀请码已过期" }
```

### 3.2 注册

**POST** `/api/auth/register`

```json
// Request
{
  "invite_code": "INV-XXXX",
  "username": "张三",
  "password": "password123",
  "confirm_password": "password123",
  "exam_region": "全国I卷",
  "grade": "高三",
  "school": "示范中学"
}

// Response 201
{
  "user_id": "uuid-...",
  "username": "张三",
  "access_token": "eyJ...",
  "token_type": "bearer"
}

// Response 400（注册失败）
{ "detail": "用户名已被占用" }
```

**字段说明：**
- `grade`、`school`：可选
- `password` 长度须为 8–20 位
- 注册成功后 Token 直接返回，无需再次登录

### 3.3 登录

**POST** `/api/auth/login`

```json
// Request（支持用户名/手机/邮箱登录）
{ "login_id": "张三", "password": "password123" }

// Response 200
{
  "user_id": "uuid-...",
  "username": "张三",
  "access_token": "eyJ...",
  "token_type": "bearer"
}

// Response 401
{ "detail": "用户名或密码错误" }
```

### 3.4 登出

**POST** `/api/auth/logout`

> 客户端丢弃 Token 即可。服务端无状态。

```json
// Response 200
{ "message": "已退出登录" }
```

### 3.5 刷新 Token

**POST** `/api/auth/refresh` `🔐 需要 Token`

```json
// Response 200
{ "access_token": "eyJ...", "token_type": "bearer" }
```

---

## 4. Users API – 用户管理

### 4.1 获取当前用户信息

**GET** `/api/users/me` `🔐`

```json
// Response 200
{
  "id": "uuid-...",
  "username": "张三",
  "exam_region": "全国I卷",
  "grade": "高三",
  "school": "示范中学",
  "role": "user",
  "status": "active",
  "created_at": "2025-01-01T00:00:00+00:00",
  "last_login_at": "2025-04-01T12:00:00+00:00"
}
```

### 4.2 更新用户信息

**PUT** `/api/users/me` `🔐`

```json
// Request（所有字段可选，传空字符串则不更新）
{
  "username": "新名字",
  "exam_region": "北京卷",
  "grade": "高二",
  "school": "某中学"
}

// Response 200 – 同 GET /me 格式
```

### 4.3 修改密码

**PUT** `/api/users/password` `🔐`

```json
// Request
{
  "old_password": "oldPass123",
  "new_password": "newPass456",
  "confirm_password": "newPass456"
}

// Response 200
{ "message": "密码修改成功，请重新登录" }

// Response 401（旧密码错误）
{ "detail": "旧密码错误" }
```

### 4.4 获取用户统计

**GET** `/api/users/stats` `🔐`

```json
// Response 200
{
  "user_id": "uuid-...",
  "mistake_count": 42,
  "due_for_review": 5,
  "latest_power": 1280.5,
  "power_records": 15
}
```

### 4.5 获取当前训练会话（废弃，建议用 Sessions API）

**GET** `/api/users/train/currSession` `🔐`

> ⚠️ 此接口已有更完善的替代方案：`GET /api/sessions/current`，建议使用新接口。

---

## 5. Attempt API – 提交答题

核心接口。提交用户的作答，系统在后台异步处理（AI 分析、生成文章、出题等）。

**POST** `/api/attempt` `🔐`

```json
// Request 通用字段
{
  "session_id": "session_abc123",    // 必须包含此字段；传空字符串 "" 则服务端自动生成 ID
  "request_type": "attempt",         // 见 §11 request_type 速查表
  // ...各 request_type 专属字段
}

// Response 200（立即返回，异步处理中）
{
  "request_id": "req_abc123456789",
  "session_id": "session_abc123",
  "status": "processing",
  "result_url": "/api/result/req_abc123456789"
}
```

各 `request_type` 的专属字段请参见 [§11 request_type 速查表](#11-request_type-速查表)。

---

## 6. Result API – 轮询结果

**GET** `/api/result/{request_id}` `🔐`

> 建议每 **2–3 秒**轮询一次，处理时间通常为 3–15 秒（取决于 AI 响应速度）。

```json
// 处理中
{ "request_id": "req_...", "status": "processing" }

// 完成（always 包含 error_log，成功时为空数组）
{
  "request_id": "req_...",
  "session_id": "session_...",
  "status": "completed",
  "results": {
    "sub_001": {
      // 根据 request_type 不同，results 结构不同，详见各场景示例
    }
  },
  "error_log": []
}

// 失败
{
  "request_id": "req_...",
  "status": "failed",
  "results": {},
  "error_log": ["错误原因..."]
}

// 未找到（request_id 无效或已过期）
{ "status": "not_found" }
```

**HTTP 状态码：**
- `200` – 正常（包括 processing / not_found）
- `403` – 请求属于其他用户，禁止访问

---

## 7. Memory API – 长期记忆

所有接口均需 `🔐` Token，且只能访问当前用户自己的数据。

### 7.1 训练记录

#### 获取训练记录列表

**GET** `/api/memory/training?limit=20`

```json
// Response 200
{
  "user_id": "uuid-...",
  "total": 8,
  "records": [
    {
      "session_id": "session_xxx",
      "article_count": 4,
      "question_count": 16,
      "correct_count": 12,
      "total_time_seconds": 1800,
      "difficulty": "L2",
      "score": 75.0,
      "note": "第一次训练",
      "recorded_at": "2025-04-01T09:00:00"
    }
  ]
}
```

#### 添加训练记录

**POST** `/api/memory/training`

```json
// Request
{
  "session_id": "session_xxx",
  "article_count": 4,
  "question_count": 16,
  "correct_count": 12,
  "total_time_seconds": 1800,
  "difficulty": "L2",
  "score": 75.0,
  "note": "第一次正式训练"
}

// Response 201
{ "message": "训练记录已保存", "record": { ... } }
```

**字段说明（均可选）：**
| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | string | 关联的会话 ID |
| `article_count` | int | 本次训练文章数 |
| `question_count` | int | 总题目数 |
| `correct_count` | int | 答对题数 |
| `total_time_seconds` | int | 用时（秒） |
| `difficulty` | string | 难度级别 L1-L4 |
| `score` | float | 综合得分 |
| `note` | string | 备注 |

---

### 7.2 错题本

#### 获取错题列表

**GET** `/api/memory/mistakes`

| 查询参数 | 类型 | 说明 |
|---------|------|------|
| `keyword` | string | 关键词（搜索题目文本/文章摘要） |
| `error_category` | string | 错误类型（词汇理解/推理判断/细节查找/主旨理解） |
| `question_type` | string | 题型（detail/inference/vocabulary/main_idea） |
| `difficulty` | string | 难度（L1/L2/L3/L4） |
| `limit` | int | 返回条数，默认 20，最大 100 |

```json
// Response 200
{
  "user_id": "uuid-...",
  "total": 42,
  "returned": 20,
  "mistakes": [
    {
      "mistake_id": "mis_20250401_001",
      "question_text": "What is the main idea of the passage?",
      "options": { "A": "...", "B": "...", "C": "...", "D": "..." },
      "correct_answer": "B",
      "user_answer": "A",
      "article_excerpt": "...",
      "error_category": "主旨理解",
      "explanation": "...",
      "question_type": "main_idea",
      "difficulty": "L3",
      "review_count": 2,
      "next_review_at": "2025-04-08T09:00:00",
      "created_at": "2025-04-01T09:00:00"
    }
  ]
}
```

#### 获取待复习错题

**GET** `/api/memory/mistakes/due?limit=10`

```json
// Response 200
{
  "user_id": "uuid-...",
  "due_count": 5,
  "mistakes": [ { /* 同上格式 */ } ]
}
```

#### 获取单条错题

**GET** `/api/memory/mistakes/{mistake_id}`

```json
// Response 200 – 单条错题对象
// Response 404 – { "detail": "错题不存在" }
```

#### 添加错题

**POST** `/api/memory/mistakes`

```json
// Request
{
  "mistake_id": "mis_20250401_001",
  "question_text": "What is the author's attitude?",
  "options": { "A": "Positive", "B": "Negative", "C": "Neutral", "D": "Uncertain" },
  "correct_answer": "A",
  "user_answer": "C",
  "article_excerpt": "The author enthusiastically argues...",
  "error_category": "推理判断",
  "explanation": "文章第二段关键词 enthusiastically 表明作者态度积极",
  "question_type": "inference",
  "difficulty": "L3"
}

// Response 201
{ "message": "错题已记录", "mistake_id": "mis_20250401_001" }
```

#### 更新错题

**PUT** `/api/memory/mistakes/{mistake_id}`

```json
// Request（仅传需要更新的字段）
{
  "review_count": 3,
  "next_review_at": "2025-04-10T09:00:00",
  "explanation": "更新后的解析..."
}

// Response 200
{ "message": "错题已更新", "mistake_id": "..." }
```

#### 删除错题

**DELETE** `/api/memory/mistakes/{mistake_id}`

```json
// Response 200
{ "message": "错题已删除", "mistake_id": "..." }

// Response 404
{ "detail": "错题不存在" }
```

---

### 7.3 遗忘曲线（SM-2）

SM-2 算法根据复习质量自动计算下次复习时间，quality 参数含义：

| quality | 含义 |
|---------|------|
| 5 | 完美记忆，毫不犹豫 |
| 4 | 正确，但有少许犹豫 |
| 3 | 经努力后正确（通过阈值） |
| 2 | 错误，但提示后想起来了 |
| 1 | 错误，正确答案看起来很简单 |
| 0 | 完全不记得 |

#### 获取遗忘曲线概况

**GET** `/api/memory/curve`

```json
// Response 200
{
  "user_id": "uuid-...",
  "total_items": 42,
  "due_count": 7
}
```

#### 获取待复习条目

**GET** `/api/memory/curve/due?limit=10`

```json
// Response 200
{
  "user_id": "uuid-...",
  "due_count": 7,
  "items": [
    {
      "item_id": "mis_20250401_001",
      "easiness": 2.36,
      "interval_days": 6,
      "repetitions": 2,
      "next_review_at": "2025-04-07T09:00:00",
      "last_reviewed_at": "2025-04-01T09:00:00"
    }
  ]
}
```

#### 获取单个条目状态

**GET** `/api/memory/curve/{item_id}`

```json
// Response 200 – SM2Item 对象（同上格式）
// Response 404 – { "detail": "条目不存在" }
```

#### 提交复习结果

**POST** `/api/memory/curve/{item_id}/review`

```json
// Request
{ "quality": 4 }

// Response 200
{
  "message": "复习结果已记录",
  "item_id": "mis_20250401_001",
  "next_review_at": "2025-04-07T09:00:00",
  "interval_days": 6,
  "repetitions": 3,
  "easiness": 2.5
}
```

---

### 7.4 战力值历史

#### 获取战力值历史

**GET** `/api/memory/power?limit=30`

```json
// Response 200
{
  "user_id": "uuid-...",
  "total_records": 15,
  "latest_score": 1350.5,
  "history": [
    {
      "score": 1350.5,
      "reason": "完成第3组训练，正确率 87.5%",
      "recorded_at": "2025-04-01T09:30:00"
    }
  ]
}
```

#### 添加战力值记录

**POST** `/api/memory/power`

```json
// Request
{
  "score": 1350.5,
  "reason": "完成第3组训练，正确率 87.5%"
}

// Response 201
{ "message": "战力值已记录", "score": 1350.5 }
```

---

## 8. Sessions API – 工作记忆会话

工作记忆存储单次学习会话的上下文（文章、题目、对话）。

### 8.1 获取会话列表

**GET** `/api/sessions?session_type=training` `🔐`

| 参数 | 值 | 说明 |
|------|----|------|
| `session_type` | `training` \| `chatting` | 会话类型，默认 training |

```json
// Response 200
{
  "user_id": "uuid-...",
  "session_type": "training",
  "session_ids": ["session_abc123", "session_xyz456"],
  "count": 2
}
```

### 8.2 获取最近会话

**GET** `/api/sessions/current?session_type=training` `🔐`

```json
// Response 200 – 完整 WorkingMemory 对象
{
  "session_id": "session_abc123",
  "session_type": "training",
  "user_id": "uuid-...",
  "articles": [ { "title": "...", "content": "...", "difficulty": "L2" } ],
  "question_queue": [ [ { "question_text": "...", "options": {...}, "correct_answer": "A" } ] ],
  "conversation_history": [ { "role": "user", "content": "..." } ],
  "agent_information": [ { "corpus_expert_planning": {...} } ],
  "created_at": "2025-04-01T09:00:00",
  "updated_at": "2025-04-01T10:30:00"
}

// Response 404 – { "detail": "没有找到正在进行中的会话" }
```

### 8.3 获取指定会话详情

**GET** `/api/sessions/{session_id}` `🔐`

> 返回格式同 §8.2

### 8.4 获取会话文章列表

**GET** `/api/sessions/{session_id}/articles` `🔐`

```json
// Response 200
{
  "session_id": "session_abc123",
  "article_count": 4,
  "articles": [
    {
      "title": "Ocean Plastic Pollution",
      "content": "Every year...",
      "difficulty": "L2",
      "genre": "expository",
      "key_vocabulary": ["biodegradable", "microplastics"]
    }
  ]
}
```

### 8.5 获取会话题目队列

**GET** `/api/sessions/{session_id}/questions` `🔐`

```json
// Response 200
{
  "session_id": "session_abc123",
  "question_sets": 4,
  "questions": [
    [
      {
        "question_text": "What is the main problem described?",
        "options": { "A": "...", "B": "...", "C": "...", "D": "..." },
        "correct_answer": "B",
        "explanation": "...",
        "evidence": "...",
        "type": "main_idea"
      }
    ]
  ]
}
```

### 8.6 获取会话对话历史

**GET** `/api/sessions/{session_id}/history?limit=40` `🔐`

```json
// Response 200
{
  "session_id": "session_abc123",
  "total_messages": 10,
  "returned": 10,
  "history": [
    { "role": "user", "content": "这道题为什么选B？" },
    { "role": "assistant", "content": "根据原文第三段..." }
  ]
}
```

### 8.7 获取 Agent 运行信息

**GET** `/api/sessions/{session_id}/agent-info` `🔐`

```json
// Response 200
{
  "session_id": "session_abc123",
  "agent_info_count": 3,
  "agent_information": [
    { "corpus_expert_planning": { "training_plan": [...] } },
    { "diagnosis_A1": { "error_category": "推理判断", "explanation": "..." } }
  ]
}
```

### 8.8 删除会话

**DELETE** `/api/sessions/{session_id}` `🔐`

```json
// Response 200
{ "message": "会话已删除", "session_id": "session_abc123" }

// Response 404
{ "detail": "会话 'session_abc123' 不存在" }
```

---

## 9. 错误码规范

| HTTP 状态码 | 含义 | 常见场景 |
|------------|------|---------|
| `200` | 成功 | 查询、轮询 |
| `201` | 创建成功 | POST 添加数据 |
| `400` | 请求参数错误 | 字段格式不对、密码不符合规则 |
| `401` | 未认证 | 缺少/过期/无效 Token |
| `403` | 无权限 | 访问他人数据、需要 admin 角色 |
| `404` | 资源不存在 | 错题/会话/request_id 不存在 |
| `422` | 数据校验失败 | Pydantic 校验未通过（如 quality 超范围） |
| `500` | 服务器内部错误 | AI 调用失败、文件系统问题 |

所有错误响应格式：
```json
{ "detail": "错误原因描述" }
```

---

## 10. 典型开发场景示例

### 场景 A：用户提交答题并获取诊断

```javascript
// 1. 提交答题
const { request_id } = await post('/api/attempt', {
  request_type: 'attempt',
  session_id: 'session_abc',
  paragraph: '...原文...',
  question_text: '...题目...',
  options: { A: '...', B: '...', C: '...', D: '...' },
  user_answer: 'A',
  correct_answer: 'B',
  time_spent: 45,
  question_number: 'A1'
});

// 2. 轮询结果（每 2 秒）
let result;
while (true) {
  result = await get(`/api/result/${request_id}`);
  if (result.status !== 'processing') break;
  await sleep(2000);
}

// 3. 读取诊断结果
const diagnosis = result.results.sub_001.diagnosis;
// { error_category, explanation, evidence_sentence, suggestion }
```

### 场景 B：生成完整训练题组

```javascript
// 1. 触发 training_set 规划（异步）
const { request_id } = await post('/api/attempt', {
  request_type: 'training_set',
  session_id: 'session_train_001',
  user_level: 'L2'
});

// 2. 轮询（training_set 通常需要 15-60 秒）
let result;
while (true) {
  result = await get(`/api/result/${request_id}`);
  if (result.status !== 'processing') break;
  await sleep(3000);
}

// 3. 读取4篇文章和对应题目
// result.results 中包含：
// - sub_000: 训练规划（training_plan）
// - dyn_c1/c2/c3/c4: 4篇生成文章
// - dyn_q1/q2/q3/q4: 对应题目组
```

### 场景 C：复习错题流程

```javascript
// 1. 获取今日待复习错题（从 SM-2 曲线）
const { mistakes } = await get('/api/memory/mistakes/due?limit=10');

// 2. 用户答题后，记录复习质量（0-5）
await post(`/api/memory/curve/${mistake_id}/review`, { quality: 4 });

// 3. 可选：更新错题的 review_count
await put(`/api/memory/mistakes/${mistake_id}`, {
  review_count: mistake.review_count + 1
});
```

### 场景 D：问答（查词/长难句/语法）

```javascript
// 查词
await post('/api/attempt', {
  request_type: 'qa',
  session_id: 'session_chat_001',
  query_type: 'word',
  content: 'biodegradable',
  context_sentence: '...包含该词的句子...'
});

// 长难句拆解
await post('/api/attempt', {
  request_type: 'qa',
  session_id: 'session_chat_001',
  query_type: 'sentence',
  content: 'Not until the 20th century did scientists fully understand...'
});

// 语法解释
await post('/api/attempt', {
  request_type: 'qa',
  query_type: 'grammar',
  content: '倒装句的用法',
  session_id: 'session_chat_001'
});
```

---

## 11. request_type 速查表

| request_type | 用途 | 必填字段 | 可选字段 |
|-------------|------|---------|---------|
| `attempt` | 提交答题，触发错因分析 | `session_id`, `paragraph`, `question_text`, `options`, `user_answer`, `correct_answer` | `time_spent`, `question_number` |
| `corpus` | 生成单篇文章 | `session_id` | `difficulty`(L1-L4), `genre`, `topic`, `word_count`, `reference_id` |
| `question` | 为文章出题 | `session_id`, `article` | `question_type`(单题型), `difficulty`, `count` |
| `qa` | 问答（查词/句/语法/翻译/自由） | `session_id`, `query_type`, `content` | `context_sentence` |
| `training_set` | 生成完整训练题组（4篇文章+题目） | `session_id` | `user_level`(L1-L4) |

> **关于 `session_id`：** JSON body 中**必须包含该字段**（声明为 `str` 无默认值，不传则 HTTP 422）。传空字符串 `""` 时服务端自动生成随机 ID，但之后无法通过 Session API 找回该会话；建议传有意义的固定字符串。

> **⚠️ 关于 `question_types`（列表）：** 规则 Planner 只转发 `question_type`（单个字符串）给 QuestionExpert；`question_types`（字符串列表）**不会被规则 Planner 转发**，仅 LLM Planner 在线上可能识别。若需准确控制题型，请使用 `question_type` + `count` 组合。

### request_type = `qa` 的 query_type 说明

| query_type | 功能 | content 填什么 |
|-----------|------|--------------|
| `word` | 查词义 | 单词（如 `biodegradable`） |
| `sentence` | 长难句拆解 | 英语句子 |
| `grammar` | 语法解释 | 语法问题描述（中文或英文） |
| `translate` | 翻译英文 | 英文文本 |
| `free` | 自由问答（支持工具调用） | 任意问题 |

---

## 12. 环境变量与部署

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `JWT_SECRET_KEY` | JWT 签名密钥（**生产环境必须设置**） | dev 默认值（不安全）|
| `OPENAI_API_KEY` | OpenAI API Key | 无 |
| `OPENAI_BASE_URL` | 自定义 API 地址（如代理） | OpenAI 官方地址 |
| `OPENAI_MODEL` | 使用的模型名 | `gpt-4o` |

### 启动开发服务器

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 查看交互式 API 文档

启动后访问：
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

*本文档对应 ReadWise AI v0.2.0，如有 API 变更请同步更新此文档。*

---

## 13. GET /api/result 所有情况的完整 JSON 结构

> 本节根据源码逐行分析，给出 `GET /api/result/{request_id}` 在所有 `request_type` + `query_type` 组合下的精确返回结构。

---

### 13.0 通用外壳（所有情况）

**处理中（轮询未完成）：**
```json
{
  "request_id": "req_a3f7c9b12d4e",
  "status": "processing"
}
```

**完成（`_assemble_result` 固定格式，error_log 始终存在）：**
```json
{
  "request_id": "req_a3f7c9b12d4e",
  "session_id": "session_...",
  "status": "completed",
  "results": { /* 见下方各 request_type 的 results 结构 */ },
  "error_log": []
}
```

**失败：**
```json
{
  "request_id": "req_a3f7c9b12d4e",
  "status": "failed",
  "results": {},
  "error_log": ["任务sub_001验收失败: [...]", "任务sub_001最终失败"]
}
```

**未找到：**
```json
{ "status": "not_found" }
```

---

### 13.1 request_type = `attempt`（错题诊断）

**Planner 生成：** 1个子任务 `sub_001`，交给 `diagnosis_expert`

**情况 A：user_answer ≠ correct_answer（有错误）**
```json
{
  "results": {
    "sub_001": {
      "diagnosis": {
        "error_category": "词汇理解 | 推理判断 | 细节查找 | 主旨理解 | 其他",
        "explanation": "该题考查深层推理，学生选了细节答案...",
        "evidence_sentence": "Scientists have found that...",
        "suggestion": "建议加强推理题解题逻辑训练",
        "confidence": 0.92
      },
      "similar_question": {
        "paragraph": "新的阅读段落（英文，100-150词）",
        "question": "题目",
        "options": { "A": "...", "B": "...", "C": "...", "D": "..." },
        "correct_answer": "B",
        "explanation": "答案解析"
      },
      "metadata": {
        "latency_ms": 2100,
        "agent": "diagnosis_expert"
      }
    }
  },
  "error_log": []
}
```

**情况 B：user_answer == correct_answer（答对了，diagnosis 返回无错误，similar_question 仍会生成）**
```json
{
  "results": {
    "sub_001": {
      "diagnosis": {
        "error_category": "无错误",
        "explanation": "学生答案正确",
        "evidence_sentence": "",
        "suggestion": "",
        "confidence": 1.0
      },
      "similar_question": {
        "paragraph": "...",
        "question": "...",
        "options": { "A": "...", "B": "...", "C": "...", "D": "..." },
        "correct_answer": "A",
        "explanation": "..."
      },
      "metadata": { "latency_ms": 1800, "agent": "diagnosis_expert" }
    }
  },
  "error_log": []
}
```

**情况 C：LLM 不可用（fallback）**
```json
{
  "results": {
    "sub_001": {
      "diagnosis": {
        "error_category": "未知",
        "explanation": "分析失败，请重试",
        "evidence_sentence": "",
        "suggestion": "",
        "confidence": 0.0
      },
      "similar_question": {},
      "metadata": { "latency_ms": 500, "agent": "diagnosis_expert" }
    }
  },
  "error_log": []
}
```

---

### 13.2 request_type = `corpus`（文章生成）

**Planner 生成：** 1个子任务 `sub_001`，交给 `corpus_expert`

**情况 A：生成成功（validation.passed = true）**
```json
{
  "results": {
    "sub_001": {
      "article": {
        "title": "The Future of Renewable Energy",
        "content": "As the world faces pressing environmental challenges...",
        "word_count": 312,
        "difficulty_actual": "L2",
        "genre_actual": "expository",
        "key_vocabulary": ["renewable", "sustainable", "emission"],
        "grammar_highlights": ["被动语态", "定语从句"]
      },
      "validation": { "passed": true, "issues": [] },
      "metadata": {
        "attempts": 1,
        "latency_ms": 3200,
        "agent": "corpus_expert",
        "reference_id": null
      }
    }
  },
  "error_log": []
}
```

**情况 B：风格化模式（传入 reference_id）- 成功**
```json
{
  "results": {
    "sub_001": {
      "article": { "title": "...", "content": "...", "word_count": 305, ... },
      "validation": { "passed": true, "issues": [] },
      "metadata": {
        "attempts": 1,
        "latency_ms": 3800,
        "agent": "corpus_expert",
        "reference_id": "gk_2024_001"
      }
    }
  },
  "error_log": []
}
```

**情况 C：验证失败（词数不足/无标题，3次尝试后仍失败）**
```json
{
  "results": {
    "sub_001": {
      "article": { "title": "", "content": "Short text...", "word_count": 30 },
      "validation": { "passed": false, "issues": ["字数太少: 30"] },
      "metadata": {
        "attempts": 3,
        "partial": true,
        "latency_ms": 9500,
        "agent": "corpus_expert",
        "reference_id": null
      }
    }
  },
  "error_log": []
}
```

---

### 13.3 request_type = `question`（出题）

**Planner 生成：** 1个子任务 `sub_001`，交给 `question_expert`

> **注意：** 规则 Planner 将 AttemptRequest 中的 `question_type`（单值）转发给 QuestionExpert；`question_types`（列表）不会被规则 Planner 转发。QuestionExpert 的 `count` 默认为 3，默认题型顺序为 `["detail", "inference", "vocabulary", "main_idea"]` 截取前 count 个。

**情况 A：成功**
```json
{
  "results": {
    "sub_001": {
      "questions": [
        {
          "question_text": "What is the main idea of the passage?",
          "options": { "A": "...", "B": "...", "C": "...", "D": "..." },
          "correct_answer": "C",
          "explanation": "文章第一段明确指出...",
          "evidence": "The primary goal of the program is...",
          "type": "detail"
        },
        {
          "question_text": "What can be inferred from paragraph 2?",
          "options": { "A": "...", "B": "...", "C": "...", "D": "..." },
          "correct_answer": "A",
          "explanation": "根据推断...",
          "evidence": "Despite the challenges...",
          "type": "inference"
        },
        {
          "question_text": "The word 'sustainable' in line 3 most nearly means...",
          "options": { "A": "...", "B": "...", "C": "...", "D": "..." },
          "correct_answer": "B",
          "explanation": "结合上下文...",
          "evidence": "sustainable development goals...",
          "type": "vocabulary"
        }
      ],
      "metadata": {
        "latency_ms": 1800,
        "agent": "question_expert",
        "count": 3
      }
    }
  },
  "error_log": []
}
```

**情况 B：LLM 失败（fallback，生成空题目 stub）**
```json
{
  "results": {
    "sub_001": {
      "questions": [
        {
          "question_text": "",
          "options": { "A": "", "B": "", "C": "", "D": "" },
          "correct_answer": "A",
          "explanation": "",
          "evidence": "",
          "type": "detail"
        }
      ],
      "metadata": { "latency_ms": 500, "agent": "question_expert", "count": 1 }
    }
  },
  "error_log": []
}
```

---

### 13.4 request_type = `qa`（问答）

**Planner 生成：** 1个子任务 `sub_001`，交给 `qa_expert`

所有 qa 结果都在顶层包含 `metadata: {latency_ms, agent: "qa_expert"}`。

#### query_type = `word`（查词）

**无 context_sentence（仅基础释义）：**
```json
{
  "results": {
    "sub_001": {
      "word": "biodegradable",
      "basic_meaning": {
        "word": "biodegradable",
        "translation": "可生物降解的",
        "success": true
      },
      "metadata": { "latency_ms": 800, "agent": "qa_expert" }
    }
  },
  "error_log": []
}
```

**有 context_sentence（基础释义 + 上下文含义）：**
```json
{
  "results": {
    "sub_001": {
      "word": "biodegradable",
      "basic_meaning": {
        "word": "biodegradable",
        "translation": "可生物降解的",
        "success": true
      },
      "context_meaning": "在文中指能被自然环境中的微生物分解的材料",
      "usage_notes": "常用于环保议题，强调对自然无害",
      "metadata": { "latency_ms": 1200, "agent": "qa_expert" }
    }
  },
  "error_log": []
}
```

**无 API Key（stub 模式）：**
```json
{
  "results": {
    "sub_001": {
      "word": "biodegradable",
      "basic_meaning": {
        "word": "biodegradable",
        "definitions": ["[模拟] biodegradable: 请配置 API 密钥"],
        "success": false
      },
      "metadata": { "latency_ms": 300, "agent": "qa_expert" }
    }
  },
  "error_log": []
}
```

#### query_type = `sentence`（长难句拆解）

```json
{
  "results": {
    "sub_001": {
      "main_clause": "scientists could not understand the mechanism",
      "subordinate_clauses": [
        "Not until the 20th century（时间状语从句）",
        "that governs memory formation（定语从句）"
      ],
      "translation": "直到20世纪，科学家才完全理解支配记忆形成的机制。",
      "structure_analysis": "倒装句型：否定状语提前导致主谓倒装",
      "key_grammar_points": ["否定副词引导的完全倒装", "定语从句"],
      "metadata": { "latency_ms": 1500, "agent": "qa_expert" }
    }
  },
  "error_log": []
}
```

#### query_type = `grammar`（语法解释）

```json
{
  "results": {
    "sub_001": {
      "grammar_point": "倒装句（Inversion）",
      "explanation": "否定副词（never, not until, seldom 等）置于句首时，后接倒装语序...",
      "examples": [
        "Never have I seen such a beautiful sunset.",
        "Not until he arrived did we start the meeting."
      ],
      "common_mistakes": [
        "将 did 遗漏：Not until he arrived we started...",
        "忽略倒装：Never I have seen..."
      ],
      "metadata": { "latency_ms": 1300, "agent": "qa_expert" }
    }
  },
  "error_log": []
}
```

#### query_type = `translate`（翻译）

```json
{
  "results": {
    "sub_001": {
      "translation": "尽管面临重重挑战，科研人员仍坚定地推进可再生能源领域的探索。",
      "notes": "despite 引导让步状语，persevered 译为"坚定推进"更符合中文表达习惯",
      "metadata": { "latency_ms": 1100, "agent": "qa_expert" }
    }
  },
  "error_log": []
}
```

#### query_type = `free`（自由问答）

**有记忆上下文（LangChain 工具调用）：**
```json
{
  "results": {
    "sub_001": {
      "answer": "根据你当前阅读的文章，第三段主要讲述了...你之前在主旨题上的错误率较高，建议...",
      "references": [
        "[get_current_article]: {\"title\": \"Ocean Plastic...\", \"content\": \"...\"}",
        "[get_mistake_summary]: 主旨理解类错题共5道..."
      ],
      "tool_calls_made": 2,
      "metadata": { "latency_ms": 4500, "agent": "qa_expert" }
    }
  },
  "error_log": []
}
```

**无记忆上下文（简单 LLM 调用）：**
```json
{
  "results": {
    "sub_001": {
      "answer": "高考英语阅读理解主旨题的解题技巧是...",
      "references": [],
      "follow_up": "你想了解具体的题型练习方法吗？",
      "metadata": { "latency_ms": 2000, "agent": "qa_expert" }
    }
  },
  "error_log": []
}
```

---

### 13.5 request_type = `training_set`（完整训练题组）

**Planner 生成：** 1个种子任务 `sub_000`（corpus_expert 规划模式），完成后动态注入 8个子任务

**results 中包含的键：**
- `sub_000`：规划任务结果
- `dyn_c1` ~ `dyn_c4`：4篇文章（corpus_expert）
- `dyn_q1` ~ `dyn_q4`：4组题目（question_expert，每组4题）

```json
{
  "results": {
    "sub_000": {
      "training_plan": [
        {
          "idx": 1,
          "topic": "海洋塑料污染",
          "reference_id": "gk_2024_001",
          "grammar_points": ["定语从句", "状语从句"],
          "difficulty": "L2",
          "word_count": 280,
          "genre": "expository",
          "description": "关于海洋塑料污染的说明文，重点考查细节题和推理题"
        },
        {
          "idx": 2,
          "topic": "人工智能与教育",
          "reference_id": null,
          "grammar_points": ["虚拟语气", "非谓语动词"],
          "difficulty": "L2",
          "word_count": 300,
          "genre": "argumentative",
          "description": "议论AI对教育影响，重点考查主旨题"
        },
        {
          "idx": 3,
          "topic": "古代丝绸之路",
          "reference_id": "gk_2023_007",
          "grammar_points": ["被动语态", "时态"],
          "difficulty": "L3",
          "word_count": 320,
          "genre": "narrative",
          "description": "记叙文，考查词义题和推理题"
        },
        {
          "idx": 4,
          "topic": "基因编辑技术",
          "reference_id": null,
          "grammar_points": ["倒装句", "强调句"],
          "difficulty": "L3",
          "word_count": 340,
          "genre": "expository",
          "description": "说明文，全题型覆盖"
        }
      ],
      "new_sub_tasks": [
        { "sub_task_id": "dyn_c1", "assigned_to": "corpus_expert", "depends_on": [], "..." : "..." },
        { "sub_task_id": "dyn_q1", "assigned_to": "question_expert", "depends_on": ["dyn_c1"], "..." : "..." }
      ],
      "metadata": {
        "latency_ms": 3000,
        "agent": "corpus_expert",
        "mode": "planning"
      }
    },
    "dyn_c1": {
      "article": {
        "title": "The Ocean's Silent Crisis",
        "content": "Every year, millions of tons of plastic...",
        "word_count": 285,
        "difficulty_actual": "L2",
        "genre_actual": "expository",
        "key_vocabulary": ["microplastics", "biodegradable", "contamination"],
        "grammar_highlights": ["定语从句", "状语从句"]
      },
      "validation": { "passed": true, "issues": [] },
      "metadata": { "attempts": 1, "latency_ms": 2800, "agent": "corpus_expert", "reference_id": "gk_2024_001" }
    },
    "dyn_q1": {
      "questions": [
        { "question_text": "...", "options": {"A":"...","B":"...","C":"...","D":"..."}, "correct_answer": "B", "explanation": "...", "evidence": "...", "type": "detail" },
        { "question_text": "...", "options": {"A":"...","B":"...","C":"...","D":"..."}, "correct_answer": "C", "explanation": "...", "evidence": "...", "type": "inference" },
        { "question_text": "...", "options": {"A":"...","B":"...","C":"...","D":"..."}, "correct_answer": "A", "explanation": "...", "evidence": "...", "type": "vocabulary" },
        { "question_text": "...", "options": {"A":"...","B":"...","C":"...","D":"..."}, "correct_answer": "D", "explanation": "...", "evidence": "...", "type": "main_idea" }
      ],
      "metadata": { "latency_ms": 1900, "agent": "question_expert", "count": 4 }
    },
    "dyn_c2": { "article": { "..." : "..." }, "validation": {"..."}, "metadata": {"..."} },
    "dyn_q2": { "questions": ["..."], "metadata": {"..."} },
    "dyn_c3": { "article": { "..." : "..." }, "validation": {"..."}, "metadata": {"..."} },
    "dyn_q3": { "questions": ["..."], "metadata": {"..."} },
    "dyn_c4": { "article": { "..." : "..." }, "validation": {"..."}, "metadata": {"..."} },
    "dyn_q4": { "questions": ["..."], "metadata": {"..."} }
  },
  "error_log": []
}
```

> **注意：** `sub_000.new_sub_tasks` 字段包含 Orchestrator 注入的 8 个子任务的完整 SubTask dict 列表，前端通常不需要读取这个字段（已由后端自动处理），但它确实存在于 results 中。

---

## 14. 傻瓜式任务操作指南

> 这里按任务类型，给出最简单的"复制-改改-用"模板。

---

### 任务一：提交一道答错的题，获取错因分析和同类题

**第一步：发送请求**
```http
POST /api/attempt
Authorization: Bearer <你的 token>
Content-Type: application/json

{
  "request_type": "attempt",
  "session_id": "我的学习会话001",
  "paragraph": "Scientists have discovered that regular exercise...",
  "question_text": "What is the main purpose of the passage?",
  "options": {
    "A": "To prove that exercise is harmful",
    "B": "To explain the benefits of regular exercise",
    "C": "To compare different sports",
    "D": "To describe a scientific experiment"
  },
  "user_answer": "A",
  "correct_answer": "B",
  "time_spent": 45,
  "question_number": "A1"
}
```

**第二步：拿到 request_id，开始轮询**
```http
GET /api/result/req_xxxxxxxxx
Authorization: Bearer <你的 token>
```

每隔 2-3 秒轮询一次，直到 status 不是 "processing"。

**第三步：读取结果**
```
result.results.sub_001.diagnosis.error_category   → 错误类型
result.results.sub_001.diagnosis.explanation      → 错因分析
result.results.sub_001.diagnosis.evidence_sentence → 原文证据
result.results.sub_001.diagnosis.suggestion       → 学习建议
result.results.sub_001.similar_question           → 同类练习题
```

---

### 任务二：生成一篇文章

**第一步：发送请求**
```http
POST /api/attempt
Authorization: Bearer <你的 token>
Content-Type: application/json

{
  "request_type": "corpus",
  "session_id": "我的训练会话002",
  "difficulty": "L2",
  "genre": "expository",
  "topic": "人工智能在医疗领域的应用",
  "word_count": 300
}
```

**第三步：读取结果**
```
result.results.sub_001.article.title     → 文章标题
result.results.sub_001.article.content   → 文章正文
result.results.sub_001.article.word_count → 实际字数
result.results.sub_001.validation.passed  → 是否通过验证
```

---

### 任务三：为一篇文章出题

**第一步：发送请求**
```http
POST /api/attempt
Authorization: Bearer <你的 token>
Content-Type: application/json

{
  "request_type": "question",
  "session_id": "我的训练会话002",
  "article": "Scientists have discovered that...",
  "difficulty": "L2",
  "question_type": "inference",
  "count": 3
}
```

**第三步：读取结果**
```
result.results.sub_001.questions          → 题目数组
result.results.sub_001.questions[0].question_text → 题干
result.results.sub_001.questions[0].options       → 选项 A/B/C/D
result.results.sub_001.questions[0].correct_answer → 正确答案
result.results.sub_001.questions[0].explanation   → 解析
```

---

### 任务四：查一个单词

**第一步：发送请求**
```http
POST /api/attempt
Authorization: Bearer <你的 token>
Content-Type: application/json

{
  "request_type": "qa",
  "session_id": "我的聊天会话003",
  "query_type": "word",
  "content": "biodegradable",
  "context_sentence": "Companies are developing biodegradable packaging materials."
}
```

**第三步：读取结果**
```
result.results.sub_001.word          → 查的单词
result.results.sub_001.basic_meaning → 词典释义
result.results.sub_001.context_meaning → 在句子中的具体含义（有传 context_sentence 时才有）
result.results.sub_001.usage_notes   → 用法注意事项（有传 context_sentence 时才有）
```

---

### 任务五：拆解一个长难句

```http
{
  "request_type": "qa",
  "session_id": "我的聊天会话003",
  "query_type": "sentence",
  "content": "Not until the 20th century did scientists fully understand the mechanism that governs memory formation."
}
```

**读取结果：**
```
result.results.sub_001.main_clause           → 主句
result.results.sub_001.subordinate_clauses   → 从句列表
result.results.sub_001.translation           → 中文翻译
result.results.sub_001.structure_analysis    → 句子结构分析
result.results.sub_001.key_grammar_points    → 语法点列表
```

---

### 任务六：解释一个语法现象

```http
{
  "request_type": "qa",
  "session_id": "我的聊天会话003",
  "query_type": "grammar",
  "content": "倒装句的分类和使用场景"
}
```

**读取结果：**
```
result.results.sub_001.grammar_point    → 语法点名称
result.results.sub_001.explanation      → 详细解释
result.results.sub_001.examples         → 例句列表
result.results.sub_001.common_mistakes  → 常见错误
```

---

### 任务七：翻译一段英文

```http
{
  "request_type": "qa",
  "session_id": "我的聊天会话003",
  "query_type": "translate",
  "content": "Despite numerous setbacks, the researchers persevered in their pursuit of renewable energy solutions."
}
```

**读取结果：**
```
result.results.sub_001.translation → 中文翻译
result.results.sub_001.notes       → 翻译说明（可能为空）
```

---

### 任务八：自由提问（AI 会自动查阅记忆）

```http
{
  "request_type": "qa",
  "session_id": "我的聊天会话003",
  "query_type": "free",
  "content": "我最近在主旨题上老是出错，能帮我分析一下原因并给出改进建议吗？"
}
```

**读取结果：**
```
result.results.sub_001.answer          → AI 回答
result.results.sub_001.references      → AI 查阅了哪些记忆（列表）
result.results.sub_001.tool_calls_made → 调用了几次工具
```

---

### 任务九：生成完整训练题组（4篇文章+16道题）

> 耗时最长，通常需要 30-90 秒，请耐心等待。

**第一步：发送请求**
```http
POST /api/attempt
Authorization: Bearer <你的 token>
Content-Type: application/json

{
  "request_type": "training_set",
  "session_id": "我的训练会话004",
  "user_level": "L2"
}
```

**第三步：读取结果**
```
result.results.sub_000.training_plan    → 4篇文章的规划（topic/difficulty/genre/...）
result.results.dyn_c1.article           → 第1篇文章
result.results.dyn_q1.questions         → 第1篇文章的4道题
result.results.dyn_c2.article           → 第2篇文章
result.results.dyn_q2.questions         → 第2篇文章的4道题
result.results.dyn_c3.article           → 第3篇文章
result.results.dyn_q3.questions         → 第3篇文章的4道题
result.results.dyn_c4.article           → 第4篇文章
result.results.dyn_q4.questions         → 第4篇文章的4道题
```

---

### 通用轮询代码模板（JavaScript）

```javascript
async function submitAndPoll(requestBody, token, maxWaitSeconds = 120) {
  // 第一步：提交请求
  const submitRes = await fetch('/api/attempt', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(requestBody)
  });
  const { request_id } = await submitRes.json();

  // 第二步：轮询（最多等 maxWaitSeconds 秒）
  const maxAttempts = Math.ceil(maxWaitSeconds / 3);
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise(r => setTimeout(r, 3000)); // 每 3s 轮询一次
    const pollRes = await fetch(`/api/result/${request_id}`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await pollRes.json();

    if (data.status === 'completed') return data;     // 成功
    if (data.status === 'failed') throw new Error(`AI 处理失败: ${data.error_log?.join(', ')}`);
    if (data.status === 'not_found') throw new Error('请求已过期，请重新提交');
    // 'processing' → 继续等待
  }
  throw new Error(`等待超时（>${maxWaitSeconds}s），请稍后再试`);
}

// 使用示例
const result = await submitAndPoll({
  request_type: 'attempt',
  session_id: 'my_session',
  paragraph: '...',
  question_text: '...',
  options: { A: '...', B: '...', C: '...', D: '...' },
  user_answer: 'A',
  correct_answer: 'B',
  time_spent: 45
}, myToken);

const diagnosis = result.results.sub_001.diagnosis;
console.log('错误类型:', diagnosis.error_category);
console.log('错因分析:', diagnosis.explanation);
```
