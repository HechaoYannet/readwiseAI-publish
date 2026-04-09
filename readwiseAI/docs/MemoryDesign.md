# ReadWise AI - 记忆管理模块构建任务书

> 本文档用于指导开发人员构建记忆管理模块，包含需求说明、技术路线、改动提纲和验收标准。

---

## 一、任务概述

### 1.1 目标

为ReadWise AI构建完整的记忆管理系统，使：
- **出题专家**能参考结构化语料库进行风格化出题
- **问答专家**能通过LangChain工具自主访问各种记忆（当前文章、错题本、语料库等）
- **单篇文章可连续出3-4道题**

### 1.2 核心能力

| 能力 | 说明 | 优先级 |
|------|------|--------|
| 系统提示词管理 | 各Sub-agent的提示词独立存储，可热更新 | P0 |
| 结构化语料库 | 真题/模拟题转Markdown，供出题参考 | P0 |
| 连续出题 | 给定一篇文章，一次性生成3-4道不同题型 | P0 |
| 问答专家记忆访问 | 通过LangChain工具自主调用记忆 | P0 |
| 工作记忆 | 当前文章、当前题目、会话历史 | P1 |
| 长期记忆 | 错题本、遗忘曲线、战力值历史 | P1 |

---

## 二、现有代码分析

### 2.1 当前架构

```
app/
├── sub_agents/
│   ├── base.py          # Sub-agent基类
│   ├── diagnosis.py     # 诊断专家
│   ├── corpus.py        # 语料专家
│   ├── question.py      # 出题专家
│   └── qa.py            # 问答专家
├── orchestrator/
│   └── dispatcher.py    # 任务分发器
├── models/
│   └── state.py         # 状态定义
└── tools/
    └── dictionary.py    # 有道词典工具
```

### 2.2 现有能力

| 模块 | 已有能力 | 缺失能力 |
|------|---------|---------|
| 问答专家 | 可处理word/sentence/grammar/translate请求 | 无法访问当前文章、错题本等 |
| 出题专家 | 可生成单题 | 无法参考语料库风格，无法连续出题 |
| 语料库 | 无 | 完全缺失 |
| 提示词 | 硬编码在代码中 | 无独立管理 |
| 工作记忆 | 无 | 完全缺失 |
| 长期记忆 | 无 | 完全缺失 |

### 2.3 关键问题

1. **问答专家无法访问记忆**：`context`中只有`user_id`和`completed_results`
2. **没有LangChain工具集成**：问答专家使用硬编码的`if-else`逻辑
3. **语料库不存在**：没有结构化的真题数据供参考
4. **提示词硬编码**：修改提示词需要改代码

---

## 三、需求详细说明

### 3.1 需求一：系统提示词管理

**目标**：将各Sub-agent的提示词从代码中抽离，独立存储为`.txt`文件。

**涉及Sub-agent**：
- 出题专家（`question_prompt.txt`）
- 语料专家（`corpus_prompt.txt`）
- 诊断专家（`diagnosis_prompt.txt`）
- 问答专家（`qa_prompt.txt`）

**文件位置**：`data/prompts/`

**示例**（出题专家提示词）：
```markdown
# Role: 高考英语出题专家

## 身份定位
你是一位经验丰富的高考英语命题专家...

## 命题规范
1. 题干长度控制在15-25词
2. 选项长度控制在5-15词
...

## 输出格式
```json
{
  "questions": [
    {
      "question_text": "...",
      "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
      "correct_answer": "C",
      "explanation": "..."
    }
  ]
}
```
```

### 3.2 需求二：结构化语料库

**目标**：将真题/模拟题转换为结构化的Markdown格式，供出题专家参考风格。

**存储位置**：`data/corpus/articles/`

**单篇文章格式**：

```markdown
---
id: gk_2024_001
source: 2024全国I卷
type: 真题
difficulty: L3
genre: 议论文
word_count: 342
---

# 2024全国I卷阅读C篇

## 原文

The rapid development of artificial intelligence...

## 题目

### 题1
**题干**: What is the main concern of educators regarding AI?
**选项**: 
- A. The cost of implementing AI systems
- B. The potential threat to traditional teaching
- C. The lack of trained AI teachers
- D. The complexity of AI technology
**答案**: B
**类型**: detail
**解析**: 原文"others fear it may undermine traditional pedagogy"...

## 生词表
| 单词 | 词性 | 释义 | CEFR |
|------|------|------|------|
| spark | v. | 引发 | B2 |
| pedagogy | n. | 教学法 | C1 |

## 长难句
> "While some embrace its potential, others fear it may undermine traditional pedagogy."
**结构**: While引导对比状语从句...
**翻译**: 虽然一些人接受其潜力，但其他人担心它可能破坏传统教学法...
```

**语料库索引**：`data/corpus/index.json`

```json
{
  "articles": {
    "gk_2024_001": {
      "metadata": {...},
      "path": "gk_2024_001.md"
    }
  },
  "indexes": {
    "by_difficulty": {"L1": [...], "L2": [...], ...},
    "by_genre": {"argumentative": [...], ...}
  }
}
```

### 3.3 需求三：连续出题

**目标**：出题专家接收一篇文章后，一次性生成3-4道题，题型可配置。

**输入**：
```json
{
  "article": "完整文章内容",
  "difficulty": "L3",
  "question_types": ["detail", "inference", "vocabulary", "main_idea"],
  "count": 4
}
```

**输出**：
```json
{
  "questions": [
    {"question_text": "...", "options": {...}, "correct_answer": "...", "type": "detail"},
    {"question_text": "...", "options": {...}, "correct_answer": "...", "type": "inference"},
    ...
  ]
}
```

**实现方式**：修改`question.py`，在Prompt中要求LLM一次性输出多道题。

### 3.4 需求四：问答专家LangChain工具化

**目标**：问答专家不再使用硬编码的`if-else`，而是通过LangChain工具自主决定调用哪些记忆。

**需要实现的工具**（`app/tools/memory_tools.py`）：

| 工具名 | 功能 | 数据来源 |
|--------|------|---------|
| `get_current_article` | 获取当前阅读文章 | 工作记忆 |
| `get_current_questions` | 获取当前题目 | 工作记忆 |
| `search_mistakes` | 搜索错题本 | 长期记忆 |
| `search_corpus` | 搜索语料库 | 语料库 |
| `lookup_word` | 查词典 | 有道API |
| `get_grammar_rule` | 获取语法规则 | 语法库 |

**问答专家新流程**：
```
用户问题 → 构造Prompt → LLM决定调用哪些工具 → 执行工具 → 整合回答
```

### 3.5 需求五：工作记忆

**目标**：维护当前会话的上下文。

**存储位置**：`data/working/sessions/{session_id}.json`

**数据结构**：
```json
{
  "session_id": "sess_xxx",
  "current_article": {...},
  "current_questions": [...],
  "conversation_history": [...]
}
```

### 3.6 需求六：长期记忆

**目标**：维护用户的持久化数据。

**存储位置**：`data/long_term/{user_id}/`

**文件结构**：
```
data/long_term/{user_id}/
├── mistakes.json      # 错题本
├── forgetting.json    # 遗忘曲线状态
├── power_history.json # 战力值历史
└── training.json      # 训练记录
```

---

## 四、技术路线

### 4.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                     记忆管理层                               │
├─────────────────────────────────────────────────────────────┤
│ L1: 系统提示词    → data/prompts/*.txt                      │
│ L2: 结构化语料库  → data/corpus/                            │
│ L3: 工作记忆      → data/working/sessions/                  │
│ L4: 长期记忆      → data/long_term/{user_id}/               │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    LangChain工具层                           │
│  @tool def get_current_article() → str                      │
│  @tool def search_mistakes(keyword) → str                   │
│  @tool def lookup_word(word, context) → str                 │
│  ...                                                         │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                     问答专家                                 │
│  llm.bind_tools([工具列表]) → 自主调用                       │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 LangChain工具集成

**核心代码模式**：

```python
from langchain.tools import tool


@tool
def get_current_article() -> str:
    """获取学生当前正在阅读的文章全文。当学生问及文章内容时使用。"""
    # 从工作记忆中获取
    return working_memory.articles.content


# 问答专家中使用
qa_llm = llm.bind_tools([get_current_article, search_mistakes, lookup_word])
response = qa_llm.invoke(user_question)
```

### 4.3 记忆注入

Dispatcher需要将记忆注入Sub-agent：

```python
context = {
    "user_id": state.user_id,
    "working_memory": state.working_memory,
    "long_term_memory": state.long_term_memory,
    "corpus_repo": corpus_repository
}
```

---

## 五、改动提纲

### 5.1 第一阶段：基础设施（优先级P0）

| 序号 | 任务 | 文件 | 说明 |
|------|------|------|------|
| 1 | 添加依赖 | `requirements.txt` | 添加`langchain-core`, `langchain-openai` |
| 2 | 创建提示词目录 | `data/prompts/` | 创建4个提示词文件 |
| 3 | 修改BaseSubAgent | `sub_agents/base.py` | 添加`load_prompt()`方法 |
| 4 | 修改各Sub-agent | `sub_agents/*.py` | 从文件加载提示词 |

### 5.2 第二阶段：语料库（优先级P0）

| 序号 | 任务 | 文件 | 说明 |
|------|------|------|------|
| 5 | 创建语料库目录 | `data/corpus/` | 创建articles/和index.json |
| 6 | 实现语料库检索 | `tools/corpus_repo.py` | 实现`search()`, `get_random_examples()` |
| 7 | 修改出题专家 | `sub_agents/question.py` | 支持连续出题，参考语料库风格 |
| 8 | 语料导入脚本 | `scripts/import_corpus.py` | 将原始真题转Markdown并导入 |

### 5.3 第三阶段：LangChain工具（优先级P0）

| 序号 | 任务 | 文件 | 说明 |
|------|------|------|------|
| 9 | 创建记忆工具 | `tools/memory_tools.py` | 实现7个@tool函数 |
| 10 | 修改问答专家 | `sub_agents/qa.py` | 重写为工具调用模式 |
| 11 | 修改Dispatcher | `orchestrator/dispatcher.py` | 注入工作记忆和长期记忆 |
| 12 | 修改状态定义 | `models/state.py` | 添加working_memory和long_term_memory字段 |

### 5.4 第四阶段：记忆存储（优先级P1）

| 序号 | 任务 | 文件 | 说明 |
|------|------|------|------|
| 13 | 实现工作记忆 | `models/working_memory.py` | 会话级记忆管理 |
| 14 | 实现长期记忆 | `models/long_term_memory.py` | 用户级记忆管理 |
| 15 | 实现错题本 | `models/mistakes.py` | 错题存储和检索 |
| 16 | 实现遗忘曲线 | `models/forgetting.py` | SM-2算法 |

---

## 六、文件清单

### 6.1 新增文件

```
data/
├── prompts/
│   ├── diagnosis_prompt.txt
│   ├── corpus_prompt.txt
│   ├── question_prompt.txt
│   └── qa_prompt.txt
├── corpus/
│   ├── articles/
│   │   └── gk_2024_001.md
│   └── index.json
├── working/
│   └── sessions/
│       └── {session_id}.json
└── long_term/
    └── {user_id}/
        ├── mistakes.json
        ├── forgetting.json
        ├── power_history.json
        └── training.json

app/
├── tools/
│   ├── corpus_repo.py          # 新增：语料库检索
│   └── memory_tools.py         # 新增：LangChain记忆工具
├── models/
│   ├── working_memory.py       # 新增：工作记忆
│   ├── long_term_memory.py     # 新增：长期记忆
│   └── mistakes.py             # 新增：错题本
└── scripts/
    └── import_corpus.py        # 新增：语料导入脚本
```

### 6.2 修改文件

| 文件 | 改动程度 | 说明 |
|------|---------|------|
| `requirements.txt` | 轻度 | 添加依赖 |
| `sub_agents/base.py` | 中度 | 添加提示词加载 |
| `sub_agents/question.py` | 中度 | 连续出题 + 语料库参考 |
| `sub_agents/qa.py` | 重度 | 重写为工具调用 |
| `orchestrator/dispatcher.py` | 中度 | 注入记忆 |
| `models/state.py` | 中度 | 添加记忆字段 |

---

## 七、验收标准

### 7.1 功能验收

| 测试场景 | 预期结果 |
|---------|---------|
| 出题专家接收文章，要求出4道题 | 返回4道不同题型的题目，格式正确 |
| 出题专家参考语料库风格 | 生成的文章/题目风格与真题相似 |
| 问答专家问"这篇文章里的X词什么意思" | 自动获取当前文章，结合上下文回答 |
| 问答专家问"我之前错过哪些类似的题" | 从错题本检索并返回 |
| 问答专家问"这个语法点我经常错，帮我讲解" | 结合错题本和语法库回答 |
| 修改提示词文件 | 无需重启服务，下次调用生效 |

### 7.2 代码质量验收

- [ ] 所有工具函数有完整的docstring（LLM会读取）
- [ ] 提示词独立存储在`.txt`文件中
- [ ] 语料库文章遵循规定的Markdown格式
- [ ] 无硬编码的API密钥
- [ ] 工具调用有超时和重试机制

### 7.3 测试验收

- [ ] 单元测试：每个工具函数
- [ ] 集成测试：问答专家端到端
- [ ] 手动测试：4个典型问答场景

---

## 八、注意事项

### 8.1 技术风险

| 风险 | 应对 |
|------|------|
| 工具调用循环失控 | 设置`max_tool_calls=5`限制 |
| 工具返回内容过长 | 截断或摘要后再返回 |
| 记忆未正确注入 | 添加空值检查，返回友好提示 |
| 语料库版权问题 | 内测使用，不公开分发 |

### 8.2 开发顺序建议

1. **先做提示词抽离**（风险最低，收益明显）
2. **再做语料库和连续出题**（核心功能）
3. **最后做LangChain工具化**（复杂度最高）

### 8.3 依赖确认

开始前确认以下已安装：
```bash
pip install langchain-core langchain-openai
```

---

## 九、附录

### 附录A：LangChain工具代码模板

```python
from langchain.tools import tool

@tool
def example_tool(param: str) -> str:
    """工具描述：说明什么情况下使用此工具"""
    # 实现逻辑
    return result
```

### 附录B：提示词加载代码模板

```python
from pathlib import Path

PROMPT_DIR = Path("../data/prompts")


def load_prompt(name: str) -> str:
    path = PROMPT_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8")
```

---

**任务书结束，请开发人员按此执行。**
