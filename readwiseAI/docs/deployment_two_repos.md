# 双仓库部署改造执行手册（Vercel + Railway）

> 目标：前端（Next.js）与后端（FastAPI）分别部署到两个独立仓库，使用公网 HTTPS 域名通信，不再依赖单仓库 rewrites。

---

## 1. 目标架构与边界

- 前端仓库：部署到 **Vercel**
- 后端仓库：部署到 **Railway**（或现有可用平台）
- 通信方式：前端通过 `NEXT_PUBLIC_API_BASE_URL` 直连后端 HTTPS 域名
- 不使用单仓库 `vercel.json` rewrites 作为生产依赖
- 当前文件存储架构下，后端保持 **单实例**，避免并发写冲突

---

## 2. 上线前基线核对

上线前先确认：

- 后端持久化目录：
  - `data/users`
  - `data/request_index`
  - `data/invites`
- 管理员账号、邀请码可恢复（可离线备份 JSON）
- 记录现网可用性基线：
  - 登录
  - `POST /api/attempt`
  - `GET /api/result/{request_id}`
  - 记忆相关接口（`/api/memory/*`）

---

## 3. 后端部署改造（先做）

### 3.1 Railway 服务设置

- 部署后端独立仓库
- 使用长期运行服务（非 serverless）
- 挂载持久化卷到后端项目 `data` 路径
- 设置健康检查（例如 `/`）
- 配置自动重启策略
- 保持单实例

### 3.2 后端环境变量

至少配置：

- `JWT_SECRET_KEY`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `CORS_ALLOWED_ORIGINS`（逗号分隔）
- `CORS_ALLOW_CREDENTIALS`

示例：

```env
JWT_SECRET_KEY=replace-with-a-strong-random-secret
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o
CORS_ALLOWED_ORIGINS=http://localhost:3000,https://your-frontend-domain.vercel.app
CORS_ALLOW_CREDENTIALS=true
```

---

## 4. 前端部署改造（后做）

### 4.1 Vercel 服务设置

- 部署前端独立仓库
- 绑定前端生产域名并启用 HTTPS

### 4.2 前端环境变量

- `NEXT_PUBLIC_API_BASE_URL`：后端生产域名（必须为 HTTPS）
- `NEXT_PUBLIC_API_TIMEOUT_MS`
- `NEXT_PUBLIC_API_RETRY_TIMES`
- `NEXT_PUBLIC_RESULT_POLL_INTERVAL_MS`
- `NEXT_PUBLIC_RESULT_POLL_TIMEOUT_MS`

示例：

```env
NEXT_PUBLIC_API_BASE_URL=https://your-backend-domain.example.com
NEXT_PUBLIC_API_TIMEOUT_MS=15000
NEXT_PUBLIC_API_RETRY_TIMES=2
NEXT_PUBLIC_RESULT_POLL_INTERVAL_MS=2000
NEXT_PUBLIC_RESULT_POLL_TIMEOUT_MS=90000
```

---

## 5. 数据迁移与切流

1. 从旧环境导出 `data` 目录并备份：
   ```bash
   # 在后端项目根目录执行（该目录下有 data/）
   tar -czf readwise-data-backup-$(date +%Y%m%d).tar.gz data
   ```
2. 将备份导入到新后端持久化卷（示例流程）：
   ```bash
   # 在新环境容器内（或挂载卷的运维机）执行
   mkdir -p /app/data
   tar -xzf readwise-data-backup-YYYY-MM-DD.tar.gz -C /app
   ```
   目标是恢复以下目录：`/app/data/users`、`/app/data/request_index`、`/app/data/invites`
3. 内部账号灰度验证完整链路
4. 将前端环境变量切到新后端域名
5. DNS 切流后观察，再下线旧环境

---

## 6. 上线验收清单

- 注册/登录/刷新 token 通过
- attempt 提交与 result 轮询稳定
- 错题、训练记录、会话、邀请码跨重启不丢失
- 前端无跨域报错
- 后端无持续 5xx
- 冷启动时前端可重试并提示用户等待

---

## 7. 回滚预案

- 保留旧后端可快速恢复
- 保留前端上一版部署快照与环境变量
- 回滚优先路径：恢复备份数据 + DNS 回切
- 切流窗口避免双写，降低数据冲突风险

---

## 8. 执行顺序建议

1. 后端新环境就绪与验收
2. 前端切换后端目标地址
3. 全量切流
4. 收尾文档与运维巡检规则
