# ReadWise AI - 用户与记忆管理模块构建任务书

> 本文档用于指导开发人员构建用户管理模块和记忆管理模块
>
> **路线选择**：完全邀请码登录制度 + 管理员命令行后台

---

## 一、任务概述

### 1.1 目标

1. **用户管理模块**：实现基于邀请码的登录注册系统，支持用户信息管理
2. **记忆管理模块**：实现按用户隔离的记忆存储（工作记忆+长期记忆）
3. **管理员后台**：命令行形式，管理用户、邀请码、记忆数据

### 1.2 核心要求

| 要求 | 说明 |
|------|------|
| 完全邀请码登录 | 无邀请码无法注册，内测用户通过邀请码加入 |
| 用户信息可填写 | 注册时填写用户名、考区等，后期可修改 |
| 管理员命令行 | 便捷管理用户、邀请码、记忆数据 |
| 记忆分用户隔离 | 每个用户的记忆数据独立存储 |

---

## 二、现有代码分析

### 2.1 当前状态

| 模块 | 状态 | 问题 |
|------|------|------|
| 用户认证 | ❌ 不存在 | 无用户登录机制 |
| 用户管理 | ❌ 不存在 | 无用户数据模型 |
| 记忆存储 | ⚠️ 部分存在 | 路径未按user_id隔离 |
| 管理员后台 | ❌ 不存在 | 无 |

### 2.2 已有基础

- `user_id`字段已存在于请求和状态中
- 记忆管理模块已设计但未完全实现按用户隔离
- 目录结构已预留`data/long_term/{user_id}/`等路径

---

## 三、数据模型设计

### 3.1 用户表

| 字段 | 类型 | 说明 | 必填 |
|------|------|------|------|
| `id` | UUID | 用户唯一标识，主键 | ✅ |
| `username` | string | 用户名（可修改） | ✅ |
| `invite_code` | string | 注册时使用的邀请码 | ✅ |
| `exam_region` | string | 考区（如：全国I卷） | ✅ |
| `grade` | string | 年级（高一/高二/高三） | 否 |
| `school` | string | 学校名称 | 否 |
| `role` | enum | `user` / `admin` | ✅ |
| `status` | enum | `active` / `disabled` | ✅ |
| `created_at` | datetime | 注册时间 | ✅ |
| `last_login_at` | datetime | 最后登录时间 | ✅ |
| `last_login_ip` | string | 最后登录IP | 否 |

### 3.2 邀请码表

| 字段 | 类型 | 说明 | 必填 |
|------|------|------|------|
| `code` | string | 8位邀请码，主键 | ✅ |
| `created_by` | UUID | 创建者ID（管理员） | ✅ |
| `max_uses` | int | 最大使用次数（默认1） | ✅ |
| `used_count` | int | 已使用次数 | ✅ |
| `used_by` | JSON | 使用过的用户ID列表 | 否 |
| `expires_at` | datetime | 过期时间（可空） | 否 |
| `created_at` | datetime | 创建时间 | ✅ |
| `note` | string | 备注 | 否 |

### 3.3 用户信息变更日志表（可选）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | |
| `user_id` | UUID | 用户ID |
| `field` | string | 修改的字段 |
| `old_value` | string | 旧值 |
| `new_value` | string | 新值 |
| `changed_at` | datetime | 修改时间 |

---

## 四、记忆管理模块改动

### 4.1 改动目标

确保所有记忆数据按`user_id`隔离存储。

### 4.2 存储路径规范

```
data/
├── long_term/
│   └── {user_id}/                    # 按用户隔离
│       ├── mistakes.json             # 错题本
│       ├── forgetting.json           # 遗忘曲线状态
│       ├── power_history.json        # 战力值历史
│       └── training_records.json     # 训练记录
│
├── working/
│   └── sessions/
│       └── {user_id}/                # 按用户隔离
│           ├── session_{id}.json
│           └── ...
│
├── corpus/                           # 公共语料库（不变）
│   └── ...
│
└── users/                            # 新增：用户信息存储
    └── users.json                    # 用户数据（或改用SQLite）
```

### 4.3 需要修改的文件

| 文件 | 改动 | 说明 |
|------|------|------|
| `models/long_term_memory.py` | 中度 | 所有方法增加`user_id`参数，路径加`{user_id}` |
| `models/working_memory.py` | 中度 | 会话路径加`{user_id}` |
| `models/mistakes.py` | 轻度 | 方法增加`user_id`参数 |
| `models/forgetting.py` | 轻度 | 方法增加`user_id`参数 |
| `orchestrator/dispatcher.py` | 轻度 | 确保`user_id`正确传递 |
| `sub_agents/qa.py` | 轻度 | 从context获取`user_id`传递给记忆工具 |

### 4.4 自动创建用户目录

```python
def ensure_user_dir(user_id: str) -> Path:
    """确保用户目录存在，首次访问时自动创建"""
    user_dir = Path(f"data/long_term/{user_id}/")
    if not user_dir.exists():
        user_dir.mkdir(parents=True)
        # 初始化空数据文件
        (user_dir / "mistakes.json").write_text("[]")
        (user_dir / "forgetting.json").write_text("{}")
        (user_dir / "power_history.json").write_text("[]")
    return user_dir
```

---

## 五、用户登录方案设计

### 5.1 完全邀请码登录流程

```
┌─────────────────────────────────────────────────────────────────┐
│ 步骤1：用户获取邀请码                                             │
│   - 管理员通过命令行生成邀请码                                     │
│   - 管理员将邀请码分发给内测用户                                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 步骤2：用户访问登录页                                             │
│   - 输入邀请码                                                    │
│   - 系统验证邀请码有效性（存在、未过期、未达上限）                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 步骤3：验证通过后，进入注册页面                                   │
│   - 填写用户名（必填）                                            │
│   - 选择考区（必填，如：全国I卷）                                  │
│   - 填写年级（可选）                                              │
│   - 填写学校（可选）                                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 步骤4：提交注册                                                   │
│   - 系统创建用户，生成UUID                                        │
│   - 更新邀请码的used_count和used_by                               │
│   - 生成JWT Token                                                │
│   - 自动创建用户记忆目录                                          │
│   - 返回Token，前端存储                                           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 步骤5：后续请求携带Token                                          │
│   - Header: Authorization: Bearer <token>                        │
│   - 认证中间件解析Token，获取user_id                              │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 登录态保持

| 配置项 | 值 | 说明 |
|--------|-----|------|
| JWT过期时间 | 7天 | 用户7天内免登录 |
| Token刷新 | 支持 | 过期前3天可刷新 |
| 存储位置 | localStorage | 前端存储 |

### 5.3 用户信息修改

| 操作 | 接口 | 说明 |
|------|------|------|
| 获取信息 | `GET /api/users/me` | 获取当前用户信息 |
| 修改信息 | `PUT /api/users/me` | 修改用户名、考区、年级、学校 |
| 修改密码 | `PUT /api/users/password` | 扩展用 |

---

## 六、API接口设计

### 6.1 认证接口

| 方法 | 路径 | 功能 | 说明 |
|------|------|------|------|
| POST | `/api/auth/verify-invite` | 验证邀请码 | 注册前验证邀请码是否有效 |
| POST | `/api/auth/register` | 注册 | 邀请码+用户信息 → 返回Token |
| POST | `/api/auth/logout` | 登出 | 前端清除Token |
| POST | `/api/auth/refresh` | 刷新Token | 获取新JWT |

### 6.2 用户信息接口

| 方法 | 路径 | 功能 | 认证 |
|------|------|------|------|
| GET | `/api/users/me` | 获取当前用户信息 | ✅ |
| PUT | `/api/users/me` | 更新用户信息 | ✅ |
| GET | `/api/users/stats` | 获取用户统计（战力值等） | ✅ |

### 6.3 现有接口改动

| 现有接口 | 改动 | 说明 |
|---------|------|------|
| `POST /api/attempt` | 增加认证 | 从JWT获取user_id，覆盖请求中的user_id |
| `GET /api/result/{id}` | 增加认证 | 验证请求者是否是该请求的创建者 |

---

## 七、管理员命令行后台设计

### 7.1 设计思路

- 独立命令行脚本，不依赖Web服务
- 直接操作数据库/文件系统
- 支持交互式模式和命令模式

### 7.2 命令清单

| 分类 | 命令 | 功能 | 示例 |
|------|------|------|------|
| **邀请码管理** | `invite create` | 生成邀请码 | `python admin.py invite create --max-uses 5 --note "高三内测"` |
| | `invite list` | 列出所有邀请码 | `python admin.py invite list` |
| | `invite show <code>` | 查看邀请码详情 | `python admin.py invite show ABC12345` |
| | `invite revoke <code>` | 撤销邀请码 | `python admin.py invite revoke ABC12345` |
| **用户管理** | `user list` | 列出所有用户 | `python admin.py user list` |
| | `user show <user_id>` | 查看用户详情 | `python admin.py user show user_001` |
| | `user disable <user_id>` | 禁用用户 | `python admin.py user disable user_001` |
| | `user enable <user_id>` | 启用用户 | `python admin.py user enable user_001` |
| | `user delete <user_id>` | 删除用户（谨慎） | `python admin.py user delete user_001 --force` |
| | `user update <user_id>` | 修改用户信息 | `python admin.py user update user_001 --grade 高三` |
| **记忆管理** | `memory list <user_id>` | 查看用户记忆 | `python admin.py memory list user_001` |
| | `memory export <user_id>` | 导出用户记忆 | `python admin.py memory export user_001 --output user_001.json` |
| | `memory import <user_id>` | 导入用户记忆 | `python admin.py memory import user_001 --file data.json` |
| | `memory clear <user_id>` | 清空用户记忆 | `python admin.py memory clear user_001 --confirm` |
| **系统管理** | `stats` | 系统统计 | `python admin.py stats` |
| | `backup` | 备份所有数据 | `python admin.py backup --output backup_20240404.zip` |
| | `health` | 健康检查 | `python admin.py health` |

### 7.3 命令行使用示例

```bash
# 交互式模式
python admin.py
> invite create --max-uses 10 --note "北京内测"
> 邀请码已生成: ABC12345

> user list
> 用户列表:
>   user_001 | 张三 | 全国I卷 | 高三 | 2024-04-01
>   user_002 | 李四 | 全国I卷 | 高二 | 2024-04-02

> memory list user_001
> 记忆数据:
>   错题本: 15条
>   遗忘曲线: 8个知识点
>   战力值历史: 12条记录

> exit

# 命令模式
python admin.py invite create --max-uses 5 --note "上海内测"
python admin.py user list --limit 10 --status active
python admin.py memory export user_001 --output ./backup/user_001.json
```

### 7.4 管理员认证

| 方式 | 说明 |
|------|------|
| 本地运行 | 脚本只能本地执行，无需认证 |
| 远程运行 | 可通过环境变量设置管理员密钥 |

---

## 八、目录结构变化

```
readwiseAI/
├── app/
│   ├── auth/                       # 新增：认证模块
│   │   ├── __init__.py
│   │   ├── dependencies.py         # 依赖注入（获取当前用户）
│   │   ├── jwt_handler.py          # JWT生成/验证
│   │   └── models.py               # 认证数据模型
│   │
│   ├── api/routes/
│   │   ├── auth.py                 # 新增：认证接口
│   │   └── users.py                # 新增：用户管理接口
│   │
│   ├── models/
│   │   ├── user.py                 # 新增：用户数据模型
│   │   ├── invite.py               # 新增：邀请码模型
│   │   ├── long_term_memory.py     # 修改：增加user_id隔离
│   │   └── working_memory.py       # 修改：增加user_id隔离
│   │
│   ├── services/
│   │   └── user_service.py         # 新增：用户服务层
│   │
│   └── main.py                     # 修改：添加认证中间件
│
├── admin.py                        # 新增：管理员命令行入口
├── admin_cli/                      # 新增：命令行模块
│   ├── __init__.py
│   ├── commands/
│   │   ├── invite.py
│   │   ├── user.py
│   │   ├── memory.py
│   │   └── system.py
│   └── utils.py
│
├── data/
│   ├── long_term/                  # 已有，按user_id隔离
│   │   └── {user_id}/
│   ├── working/
│   │   └── sessions/
│   │       └── {user_id}/          # 按user_id隔离
│   ├── users/                      # 新增：用户数据存储
│   │   └── users.json
│   └── invites/                    # 新增：邀请码存储
│       └── invites.json
│
└── tests/
    ├── test_auth.py                # 新增
    ├── test_user_service.py        # 新增
    └── test_admin_cli.py           # 新增
```

---

## 九、实施计划

### 9.1 阶段一：记忆分用户管理（1天）

| 任务 | 时间 |
|------|------|
| 修改长期记忆路径，增加user_id隔离 | 2h |
| 修改工作记忆路径，增加user_id隔离 | 1h |
| 实现用户目录自动创建 | 1h |
| 测试多用户数据隔离 | 1h |
| 更新现有调用代码 | 1h |

### 9.2 阶段二：用户认证模块（2天）

| 任务 | 时间 |
|------|------|
| 设计用户和邀请码数据模型 | 1h |
| 实现JWT生成和验证 | 1h |
| 实现认证中间件 | 1h |
| 实现邀请码验证接口 | 1h |
| 实现注册接口 | 2h |
| 实现用户信息接口 | 1h |
| 修改现有API适配认证 | 2h |
| 测试 | 1h |

### 9.3 阶段三：管理员命令行后台（1.5天）

| 任务 | 时间 |
|------|------|
| 搭建命令行框架 | 1h |
| 实现邀请码管理命令 | 2h |
| 实现用户管理命令 | 2h |
| 实现记忆管理命令 | 2h |
| 实现系统统计和备份 | 1h |
| 测试 | 1h |

### 9.4 阶段四：前端适配（1.5天）

| 任务 | 时间 |
|------|------|
| 登录/注册页面 | 2h |
| Token存储和携带 | 1h |
| 用户信息页面 | 2h |
| 用户信息修改功能 | 1h |
| 联调测试 | 2h |

---

## 十、验收标准

### 10.1 功能验收

| 测试场景 | 预期结果 |
|---------|---------|
| 无邀请码注册 | 被拒绝，提示无效邀请码 |
| 有效邀请码注册 | 成功创建用户，返回Token |
| 同一邀请码超限使用 | 超出max_uses后无法使用 |
| 用户修改信息 | 信息更新成功，下次查询返回新值 |
| 用户A无法访问用户B的记忆 | 记忆数据完全隔离 |
| 管理员命令行生成邀请码 | 生成8位邀请码，存储成功 |
| 管理员命令行查看用户 | 显示用户列表和详情 |
| 管理员命令行导出记忆 | 生成JSON文件 |

### 10.2 代码质量验收

- [ ] 所有记忆操作都有`user_id`参数
- [ ] 认证中间件拦截未认证请求
- [ ] JWT有过期时间和刷新机制
- [ ] 命令行有帮助信息（`--help`）
- [ ] 无硬编码的密钥

---

## 十一、风险与应对

| 风险 | 应对 |
|------|------|
| 邀请码泄露 | 邀请码单次使用，支持撤销 |
| 用户数据迁移 | 提供迁移脚本，将现有数据按user_id重新组织 |
| 命令行误操作 | 危险操作需要`--confirm`确认 |
| JWT泄露 | 设置短过期时间，支持黑名单 |

---

## 十二、总结

| 维度 | 说明 |
|------|------|
| **总工作量** | 约6天 |
| **新增文件** | 约15个 |
| **修改文件** | 约8个 |
| **核心依赖** | `python-jose`（JWT）、`bcrypt`（密码） |

**开发顺序建议**：
1. 先做记忆分用户管理（最基础）
2. 再做用户认证模块（核心）
3. 最后做管理员命令行（便利工具）
4. 前端适配并行进行

---

**任务书结束，请开发人员按此执行。**
