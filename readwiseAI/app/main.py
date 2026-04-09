"""ReadWise AI – FastAPI application entry point."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import attempts, callback, results, auth, users, memory, sessions

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="ReadWise AI", version="0.2.0")

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # 你的 Next.js 前端地址
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有方法，包括 OPTIONS
    allow_headers=["*"],  # 允许所有请求头
)

# Auth & user routes
app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")

# Public API
app.include_router(attempts.router, prefix="/api")
app.include_router(results.router, prefix="/api")
app.include_router(memory.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")

# Internal callback (sub-agent → orchestrator)
app.include_router(callback.router, prefix="/internal")


@app.get("/")
async def root():
    return {"message": "ReadWise AI is running"}
