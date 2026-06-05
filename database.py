"""Database operations for account management."""
import aiomysql
import config
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

pool = None

TABLE_NAME = "tg_telethon_account"
LOGIN_LOG_TABLE = "tg_login_log"

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `phone` VARCHAR(32) NOT NULL COMMENT '手机号',
    `api_id` INT DEFAULT NULL COMMENT 'Telegram API ID',
    `api_hash` VARCHAR(64) DEFAULT NULL COMMENT 'Telegram API Hash',
    `tg_user_id` BIGINT DEFAULT NULL COMMENT 'Telegram用户ID',
    `nickname` VARCHAR(128) DEFAULT NULL COMMENT '昵称(firstName + lastName)',
    `username` VARCHAR(64) DEFAULT NULL COMMENT '用户名',
    `status` VARCHAR(20) NOT NULL DEFAULT 'offline' COMMENT '状态: online-在线, offline-下线, banned-已被注销',
    `last_login_time` DATETIME DEFAULT NULL COMMENT '最后登录时间',
    `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `update_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY `uk_phone` (`phone`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Telethon账号管理表';
"""

CREATE_LOGIN_LOG_SQL = f"""
CREATE TABLE IF NOT EXISTS `{LOGIN_LOG_TABLE}` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `phone` VARCHAR(32) NOT NULL COMMENT '手机号',
    `result` VARCHAR(20) NOT NULL COMMENT '登录结果: success-成功, failed-失败, banned-已被注销',
    `reason` VARCHAR(512) DEFAULT NULL COMMENT '失败原因',
    `tg_user_id` BIGINT DEFAULT NULL COMMENT 'Telegram用户ID',
    `nickname` VARCHAR(128) DEFAULT NULL COMMENT '昵称',
    `login_time` DATETIME NOT NULL COMMENT '登录时间',
    `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX `idx_phone` (`phone`),
    INDEX `idx_login_time` (`login_time`),
    INDEX `idx_result` (`result`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='登录日志表';
"""


async def init_db():
    """Initialize database connection pool and create table if not exists."""
    global pool
    pool = await aiomysql.create_pool(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        db=config.DB_NAME,
        charset="utf8mb4",
        autocommit=True,
        minsize=2,
        maxsize=10,
    )
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(CREATE_TABLE_SQL)
            await cur.execute(CREATE_LOGIN_LOG_SQL)
    logger.info("Database initialized")


async def close_db():
    """Close database connection pool."""
    global pool
    if pool:
        pool.close()
        await pool.wait_closed()


async def upsert_account(phone: str, api_id: int = None, api_hash: str = None,
                         tg_user_id: int = None, nickname: str = None,
                         username: str = None, status: str = "online"):
    """Insert or update account record."""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            sql = f"""
                INSERT INTO `{TABLE_NAME}` (phone, api_id, api_hash, tg_user_id, nickname, username, status, last_login_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    api_id = VALUES(api_id),
                    api_hash = VALUES(api_hash),
                    tg_user_id = VALUES(tg_user_id),
                    nickname = VALUES(nickname),
                    username = VALUES(username),
                    status = VALUES(status),
                    last_login_time = VALUES(last_login_time)
            """
            await cur.execute(sql, (phone, api_id, api_hash, tg_user_id, nickname,
                                    username, status, datetime.now()))


async def update_status(phone: str, status: str):
    """Update account status."""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"UPDATE `{TABLE_NAME}` SET status = %s WHERE phone = %s",
                (status, phone)
            )


async def get_all_accounts():
    """Get all accounts."""
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(f"SELECT * FROM `{TABLE_NAME}` ORDER BY id")
            return await cur.fetchall()


async def get_account_by_phone(phone: str):
    """Get account by phone number."""
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                f"SELECT * FROM `{TABLE_NAME}` WHERE phone = %s", (phone,)
            )
            return await cur.fetchone()


async def insert_login_log(phone: str, result: str, reason: str = None,
                           tg_user_id: int = None, nickname: str = None):
    """Insert a login log record.

    Args:
        phone: Account phone number.
        result: Login result - 'success', 'failed', or 'banned'.
        reason: Failure reason (optional).
        tg_user_id: Telegram user ID (on success).
        nickname: User nickname (on success).
    """
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            sql = f"""
                INSERT INTO `{LOGIN_LOG_TABLE}` (phone, result, reason, tg_user_id, nickname, login_time)
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (phone, result, reason, tg_user_id, nickname, datetime.now()))
