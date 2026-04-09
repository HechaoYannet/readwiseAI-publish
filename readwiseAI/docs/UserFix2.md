# 用户数据目录重构任务书

> 基于已实现的JWT认证和用户隔离，重构`checkpoints/`和`results/`目录结构


## 一、重构目标

### 1.1 当前状态

| 模块 | 当前存储路径 | 是否按用户隔离 |
|------|-------------|---------------|
| `long_term/` | `data/long_term/{user_id}/` | ✅ 已实现 |
| `working/sessions/` | `data/working/sessions/{user_id}/` | ✅ 已实现 |
| `checkpoints/` | `data/checkpoints/` | ❌ 未隔离 |
| `results/` | `data/results/` | ❌ 未隔离 |

### 1.2 目标状态

统一为以下目录结构：

```
data/
├── users/
│   └── {user_id}/
│       ├── checkpoints/      # 请求状态存档
│       ├── results/          # 请求结果存档
│       ├── long_term/        # 长期记忆（已存在）
│       └── working/          # 工作记忆（已存在）
│           └── sessions/
└── corpus/                   # 公共语料库（不变）
```


## 二、改动范围

### 2.1 需要修改的文件

| 文件 | 改动内容 | 优先级 |
|------|---------|--------|
| `orchestrator/checkpoint.py` | 修改存储路径，增加`user_id`子目录 | P0 |
| `orchestrator/agent.py` | 修改Checkpoint加载路径 | P0 |
| `api/routes/results.py` | 修改结果读取路径，增加权限校验 | P0 |
| `api/routes/attempts.py` | 修改Checkpoint保存路径 | P0 |
| `internal/callback.py` | 修改Checkpoint恢复路径 | P1 |

### 2.2 不需要修改的文件

| 文件 | 原因 |
|------|------|
| `models/long_term_memory.py` | 已按用户隔离 |
| `models/working_memory.py` | 已按用户隔离 |
| `sub_agents/*.py` | 不直接操作文件路径 |
| `tools/*.py` | 不涉及用户数据存储 |


## 三、迁移要点

### 3.1 路径构建规则

**改动前**：
```
data/checkpoints/{request_id}.json
data/results/{request_id}.json
```

**改动后**：
```
data/users/{user_id}/checkpoints/{request_id}.json
data/users/{user_id}/results/{request_id}.json
```

### 3.2 关键代码改动点

| 改动点 | 位置 | 说明 |
|--------|------|------|
| Checkpoint保存 | `checkpoint.py` 的 `save()` | 路径增加`users/{user_id}/`前缀 |
| Checkpoint加载 | `checkpoint.py` 的 `load()` | 同上 |
| Checkpoint删除 | `checkpoint.py` 的 `delete()` | 同上 |
| 结果保存 | `attempts.py` 完成处 | 保存到`users/{user_id}/results/` |
| 结果读取 | `results.py` 的 `get_result()` | 从`users/{user_id}/results/`读取 |

### 3.3 权限校验要点

| 校验点 | 说明 |
|--------|------|
| 结果查询时 | 从JWT获取`user_id`，验证与请求路径中的`request_id`对应的用户一致 |
| Checkpoint恢复时 | 加载前验证`user_id`匹配 |
| 跨用户访问 | 返回403 Forbidden，而非404（防止探测） |

### 3.4 错误处理要点

| 场景 | 处理方式 |
|------|---------|
| 目录不存在 | 自动创建`data/users/{user_id}/checkpoints/` |
| 用户目录创建失败 | 记录日志，返回500 |
| 权限校验失败 | 返回`{"error": "Forbidden"}`，状态码403 |
| 请求ID不存在 | 返回`{"status": "not_found"}`，状态码200（不暴露信息） |


## 四、重要检查点

### 4.1 代码检查清单

- [ ] `checkpoint.py` 所有方法都使用了新的路径规则
- [ ] `results.py` 读取结果时从新路径读取
- [ ] `attempts.py` 保存结果时保存到新路径
- [ ] 权限校验：`GET /api/result/{request_id}` 验证了`user_id`归属
- [ ] 权限校验：Dispatcher恢复Checkpoint前验证了`user_id`
- [ ] 目录自动创建逻辑已添加
- [ ] 错误日志记录了路径和user_id

### 4.2 功能测试检查点

| 测试场景 | 预期结果 |
|---------|---------|
| 用户A提交请求 | Checkpoint保存在`data/users/A/checkpoints/` |
| 用户A查询结果 | 从`data/users/A/results/`返回结果 |
| 用户A查用户B的request_id | 返回403 Forbidden |
| 不存在的request_id | 返回200 + `{"status": "not_found"}` |
| 新用户首次请求 | 自动创建`data/users/{user_id}/`目录 |
| 并发请求 | 目录创建操作线程安全 |

### 4.3 回归测试检查点

| 测试场景 | 预期结果 |
|---------|---------|
| 完整诊断流程 | 提交→轮询→获取结果，正常返回 |
| 问答专家查词 | 正常返回，不受路径影响 |
| 出题专家出题 | 正常返回 |
| 语料库检索 | 正常返回（公共目录不变） |
| 长期记忆读写 | 路径不变，功能正常 |
| 工作记忆读写 | 路径不变，功能正常 |


## 五、注意事项

### 5.1 常见陷阱

| 陷阱 | 说明 | 应对 |
|------|------|------|
| 路径拼接顺序错误 | 先拼`users/{user_id}`再拼子目录 | 统一使用`Path`的`/`运算符 |
| 忘记创建父目录 | 写入文件前目录不存在 | 写入前调用`parent.mkdir(parents=True, exist_ok=True)` |
| 权限校验暴露信息 | 返回404会暴露资源是否存在 | 统一返回403（权限不足）或200+not_found |
| 硬编码路径分隔符 | Windows用`\`，Linux用`/` | 使用`Path`或`os.path.join` |
| 忘记处理user_id为空 | JWT解析失败时user_id为空 | 在入口处校验，返回401 |

### 5.2 并发安全

| 场景 | 风险 | 应对 |
|------|------|------|
| 多请求同时创建同一用户目录 | 文件系统错误 | `exist_ok=True` 忽略已存在 |
| 多请求同时写同一Checkpoint | 数据覆盖 | 使用文件锁或请求ID唯一性保证 |

### 5.3 性能考虑

| 考虑 | 说明 |
|------|------|
| 目录层级增加 | 从2层变为4层，影响可忽略 |
| 文件数量 | 内测期<500个文件，无性能问题 |
| 路径解析 | 使用`Path`对象缓存父目录 |


## 六、验收标准

### 6.1 代码质量

- [ ] 无硬编码路径
- [ ] 所有文件操作有错误处理
- [ ] 权限校验逻辑统一封装
- [ ] 日志记录了关键操作

### 6.2 功能正确性

- [ ] 两个不同用户的请求数据完全隔离
- [ ] 用户无法查看其他用户的请求结果
- [ ] 现有功能（诊断、出题、问答、语料）全部正常

### 6.3 安全性

- [ ] 无user_id路径遍历漏洞（如`../../`）
- [ ] 权限校验不可绕过
- [ ] 错误信息不泄露系统路径


## 七、回滚方案

如重构后出现问题，回滚步骤：

1. 恢复修改的4-5个文件到上一版本
2. 重启服务
3. 验证旧路径`data/checkpoints/`和`data/results/`可正常读取

**注意**：回滚后新产生的Checkpoint会写入旧路径，新旧路径数据不互通。建议回滚前备份新路径数据。


## 八、总结

| 维度 | 说明 |
|------|------|
| 改动文件数 | 约5个 |
| 预估工时 | 2-3小时（含测试） |
| 风险等级 | 低（仅路径变更，逻辑不变） |
| 是否需要停机 | 否（重启服务即可） |

**一句话总结**：将`checkpoints/`和`results/`从平铺结构改为`users/{user_id}/`嵌套结构，增加权限校验，其他逻辑不变。


## 九、另外
POST api/attempt 中不应传入user_id,而是jwt_token,确保用户请求时为登录状态。其他只有在登录状态下才可调用的api也应该做这种改动。
