"""Application configuration."""
import os

# Server
HOST = os.getenv("APP_HOST", "0.0.0.0")
PORT = int(os.getenv("APP_PORT", "8807"))

# Database (MySQL)
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "XkOVjlR6FvmONtLi75BS")
DB_NAME = os.getenv("DB_NAME", "tg-client-server")

# Telegram Bot Notification
BOT_TOKEN = os.getenv("BOT_TOKEN", "8534398194:AAF6CKDeS_yGeo167C4znOq9cR3porDGJa0")
BOT_CHAT_ID = os.getenv("BOT_CHAT_ID", "-5181774632")

# JWT Secret for web client authentication
JWT_SECRET = os.getenv("JWT_SECRET", "tg-telethon-secret-key-2024")
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ACCOUNT_DIR = os.path.join(BASE_DIR, "account")
WAIT_LOGIN_DIR = os.path.join(ACCOUNT_DIR, "waitLogin")
LOGIN_SUCCESS_DIR = os.path.join(ACCOUNT_DIR, "loginSuccess")
LOGIN_FAILED_DIR = os.path.join(ACCOUNT_DIR, "loginFailed")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
