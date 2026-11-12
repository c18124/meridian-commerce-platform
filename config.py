import os
from dotenv import load_dotenv

load_dotenv()

# DeepSeek 配置
MODEL = "deepseek-chat"
API_KEY = os.getenv("DEEPSEEK_API_KEY")

# MySQL 数据库配置
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("没有配置 DATABASE_URL")

# Redis 配置
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
