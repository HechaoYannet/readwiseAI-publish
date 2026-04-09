# ReadWise AI - 用户登录模块改动方案

> 本文档用于指导开发人员实现用户登录模块
>
> **核心改动**：在现有邀请码注册基础上，增加**账号密码登录**能力

---

## 一、改动概述

### 1.1 当前状态 vs 目标状态

| 能力 | 当前状态 | 目标状态 |
|------|---------|---------|
| 注册 | 邀请码 + 用户名 + 考区 | 邀请码 + 用户名 + **密码** + 考区 |
| 登录 | 无（注册即登录） | **用户名+密码登录** |
| 登出后再次登录 | 不支持 | **支持** |
| 密码管理 | 无 | 支持修改密码 |

### 1.2 改动范围

| 模块 | 改动类型 | 工作量 |
|------|---------|--------|
| 数据模型 | 新增密码字段 | 0.5h |
| 注册接口 | 增加密码参数和加密逻辑 | 1h |
| 登录接口 | 新增 | 1.5h |
| 密码修改接口 | 新增 | 1h |
| 认证中间件 | 保持（无需改动） | 0 |
| 前端 | 登录页 + 注册页增加密码框 | 2h |

---

## 二、数据模型改动

### 2.1 用户表新增字段

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| `password_hash` | string | bcrypt哈希密码 | 非空（注册时设置） |
| `phone` | string | 手机号（备选登录） | 可选，唯一 |
| `email` | string | 邮箱（备选登录） | 可选，唯一 |

### 2.2 存储方式

```
data/users/users.json
```

每条用户记录新增字段：

```json
{
  "id": "user_001",
  "username": "zhangsan",
  "password_hash": "$2b$12$Kx...",  // bcrypt哈希
  "phone": "13800138000",            // 可选
  "email": "zhang@example.com",      // 可选
  "invite_code": "ABC12345",
  "exam_region": "全国I卷",
  "grade": "高三",
  "school": "北京四中",
  "role": "user",
  "status": "active",
  "created_at": "2026-04-01T10:00:00",
  "last_login_at": "2026-04-04T15:30:00"
}
```

---

## 三、API接口改动

### 3.1 注册接口（修改）

**路径**：`POST /api/auth/register`

**请求体**（新增密码字段）：

```json
{
  "invite_code": "ABC12345",
  "username": "zhangsan",
  "password": "password123",           // 新增
  "confirm_password": "password123",   // 新增
  "exam_region": "全国I卷",
  "grade": "高三",
  "school": "北京四中"
}
```

**密码校验规则**：

| 规则 | 说明 |
|------|------|
| 长度 | 8-20位 |
| 非空 | 不能为空字符串 |
| 一致性 | 两次输入必须相同 |

**响应**（不变）：

```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "expires_in": 604800,
  "user": {
    "id": "user_001",
    "username": "zhangsan",
    "exam_region": "全国I卷"
  }
}
```

### 3.2 登录接口（新增）

**路径**：`POST /api/auth/login`

**请求体**：

```json
{
  "login_id": "zhangsan",   // 用户名 或 手机号 或 邮箱
  "password": "password123"
}
```

**处理逻辑**：

```
1. 根据login_id查询用户（支持用户名/手机号/邮箱三种方式）
2. 用户不存在 → 返回 401 "用户名或密码错误"
3. 验证密码（bcrypt.compare）
4. 密码错误 → 返回 401 "用户名或密码错误"
5. 检查用户状态（status是否active）
6. 更新last_login_at
7. 生成JWT Token
8. 返回Token和用户信息
```

**响应**：

```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "expires_in": 604800,
  "user": {
    "id": "user_001",
    "username": "zhangsan",
    "exam_region": "全国I卷",
    "grade": "高三"
  }
}
```

### 3.3 密码修改接口（新增）

**路径**：`PUT /api/users/password`

**认证**：需要登录（JWT Token）

**请求体**：

```json
{
  "old_password": "old123",
  "new_password": "new456",
  "confirm_password": "new456"
}
```

**处理逻辑**：

```
1. 从JWT获取user_id
2. 获取用户记录
3. 验证old_password正确性
4. 验证new_password符合规则（8-20位）
5. 验证new_password与confirm_password一致
6. bcrypt哈希新密码
7. 更新password_hash
8. 返回成功
```

**响应**：

```json
{
  "message": "密码修改成功，请重新登录"
}
```

### 3.4 登出接口（新增，可选）

**路径**：`POST /api/auth/logout`

**认证**：需要登录

**响应**：

```json
{
  "message": "登出成功"
}
```

**说明**：由于JWT无状态，后端只需返回成功，前端负责清除Token。

---

## 四、密码加密实现

### 4.1 技术选型

| 组件 | 选型 | 说明 |
|------|------|------|
| 哈希算法 | bcrypt | 抗彩虹表，自带盐值 |
| Python库 | `bcrypt` | `pip install bcrypt` |

### 4.2 核心函数

```python
import bcrypt

def hash_password(password: str) -> str:
    """加密密码，返回bcrypt哈希字符串"""
    salt = bcrypt.gensalt(rounds=10)
    return bcrypt.hashpw(password.encode(), salt).decode()

def verify_password(password: str, password_hash: str) -> bool:
    """验证密码是否正确"""
    return bcrypt.checkpw(password.encode(), password_hash.encode())
```

---

## 五、文件改动清单

### 5.1 新增文件

| 文件 | 说明 |
|------|------|
| `app/auth/password.py` | 密码加密/验证工具 |
| `app/api/routes/auth.py` | 认证接口（注册、登录、登出） |
| `app/api/routes/users.py` | 用户接口（密码修改） |

### 5.2 修改文件

| 文件 | 改动 | 说明 |
|------|------|------|
| `app/models/user.py` | 中度 | 添加password_hash字段 |
| `app/services/user_service.py` | 中度 | 添加登录验证方法 |
| `app/main.py` | 轻度 | 注册新路由 |
| `data/users/users.json` | 结构变化 | 每条用户记录增加password_hash |

### 5.3 不需要改动的文件

| 文件 | 原因 |
|------|------|
| `app/auth/jwt_handler.py` | JWT逻辑不变 |
| `app/auth/dependencies.py` | 认证中间件不变 |
| `app/orchestrator/*` | Agent逻辑不变 |
| `app/sub_agents/*` | Sub-agent不变 |

---

## 六、前端改动

### 6.1 注册页面

**新增字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| 密码 | password | 8-20位 |
| 确认密码 | password | 与密码一致 |

### 6.2 登录页面（新增）

**字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| 用户名/手机号 | text | 登录标识 |
| 密码 | password | |

**流程**：

```
输入login_id + 密码 → POST /api/auth/login → 成功 → 存储Token → 跳转首页
```

### 6.3 密码修改页面（新增）

**字段**：

| 字段 | 类型 |
|------|------|
| 旧密码 | password |
| 新密码 | password |
| 确认新密码 | password |

---

## 七、错误码定义

| HTTP状态码 | 错误码 | 说明 |
|-----------|--------|------|
| 400 | `INVALID_PASSWORD` | 密码不符合规则 |
| 400 | `PASSWORD_MISMATCH` | 两次密码不一致 |
| 401 | `INVALID_CREDENTIALS` | 用户名或密码错误 |
| 401 | `ACCOUNT_DISABLED` | 账号已被禁用 |
| 401 | `OLD_PASSWORD_INCORRECT` | 旧密码错误 |
| 404 | `USER_NOT_FOUND` | 用户不存在 |

---

## 八、实施顺序

### 阶段一：后端基础（2小时）

1. 安装bcrypt：`pip install bcrypt`
2. 创建`app/auth/password.py`
3. 修改用户模型，增加`password_hash`字段
4. 修改注册逻辑，增加密码加密

### 阶段二：登录接口（1.5小时）

5. 实现`POST /api/auth/login`
6. 实现用户查询（支持用户名/手机号/邮箱）
7. 添加登录失败计数（可选）

### 阶段三：密码管理（1小时）

8. 实现`PUT /api/users/password`
9. 添加密码修改验证逻辑

### 阶段四：前端适配（2小时）

10. 注册页增加密码框
11. 新建登录页
12. 新建密码修改页
13. 联调测试

---

## 九、测试用例

| 测试场景 | 预期结果 |
|---------|---------|
| 注册时密码长度<8 | 返回错误 |
| 注册时两次密码不一致 | 返回错误 |
| 注册成功 | 用户记录有password_hash |
| 正确用户名+密码登录 | 返回Token |
| 错误密码登录 | 返回401 |
| 不存在的用户名登录 | 返回401 |
| 修改密码时旧密码错误 | 返回401 |
| 修改密码成功 | 新密码可登录，旧密码不可 |

---

## 十、总结

| 维度 | 说明 |
|------|------|
| **总工作量** | 约6.5小时（后端4.5h + 前端2h） |
| **新增接口** | 3个（登录、登出、修改密码） |
| **修改接口** | 1个（注册） |
| **新增依赖** | `bcrypt` |
| **对现有架构影响** | 极小，仅用户模块增加密码字段 |

**核心改动点**：
1. 注册时要求用户设置密码
2. 新增用户名+密码登录接口
3. 登出后使用登录接口重新获取Token