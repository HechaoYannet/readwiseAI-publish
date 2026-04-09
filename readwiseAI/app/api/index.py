# backend/api/index.py
import sys
from pathlib import Path

# 将 backend 目录添加到 Python 路径
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from app.main import app  # 导入你的 FastAPI app 实例

# 直接导出 app，无需 Mangum 适配器[citation:5]