"""Contact adder module - polls pending assign logs and adds contacts via Telethon."""
import asyncio
import logging
import random

import aiomysql
from telethon.tl.functions.contacts import ImportContactsRequest, GetContactsRequest
from telethon.tl.types import InputPhoneContact

import database
import client_manager

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60  # seconds
MAX_RETRY_COUNT = 30

# Network-related error keywords that should trigger retry
NETWORK_ERROR_KEYWORDS = [
    'timeout', 'timed out', 'connection', 'network', 'unreachable',
    'reset', 'refused', 'broken pipe', 'eof', 'disconnect',
    'flood', 'floodwait', 'server error', 'internal error',
    'temporarily unavailable', 'could not connect',
]


def _is_network_error(error_msg: str) -> bool:
    """Check if an error message indicates a network/connectivity issue."""
    lower = error_msg.lower()
    return any(kw in lower for kw in NETWORK_ERROR_KEYWORDS)


async def poll_contact_adder():
    """Background task: poll pending contact assign logs every POLL_INTERVAL seconds."""
    while True:
        try:
            await asyncio.sleep(POLL_INTERVAL)
            await _process_pending_logs()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[ContactAdder] poll error: {e}")


async def _process_pending_logs():
    """Fetch pending assign logs and try to add contacts."""
    pending_logs = await _get_pending_logs()
    if not pending_logs:
        return

    logger.info(f"[ContactAdder] Found {len(pending_logs)} pending assign logs")

    for log_entry in pending_logs:
        try:
            log_id = log_entry['id']
            account_phone = log_entry['account_phone']
            account_id = log_entry['account_id']
            contact_phone = log_entry['contact_phone']
            retry_count = log_entry.get('retry_count') or 0

            # Check if account is online
            if account_phone not in client_manager.active_clients:
                logger.debug(f"[ContactAdder] 跳过 log_id={log_id}: 账号 {account_phone} 不在线")
                continue

            client = client_manager.active_clients[account_phone]

            logger.info(f"[ContactAdder] 处理 log_id={log_id}: {account_phone} -> {contact_phone} (retry={retry_count})")

            # Normalize phone: ensure + prefix
            normalized_phone = contact_phone.strip()
            if not normalized_phone.startswith("+"):
                normalized_phone = "+" + normalized_phone

            # Try to add contact
            try:
                # Check if already a contact
                already_friend = False
                user_id = None
                try:
                    entity = await client.get_entity(normalized_phone)
                    if entity:
                        result = await client(GetContactsRequest(hash=0))
                        phone_clean = normalized_phone.replace("+", "")
                        for user in result.users:
                            if user.phone and user.phone.replace("+", "") == phone_clean:
                                already_friend = True
                                user_id = user.id
                                break
                except Exception:
                    pass

                if already_friend:
                    logger.info(f"[ContactAdder] log_id={log_id}: 已是好友, user_id={user_id}")
                    await _update_log(log_id, 'skipped', '已是好友', retry_count + 1)
                    # Ensure tg_contact record exists
                    if user_id:
                        await _ensure_contact_record(account_id, user_id, contact_phone)
                    continue

                # Import contact
                input_contact = InputPhoneContact(
                    client_id=random.randint(0, 2**31),
                    phone=normalized_phone,
                    first_name=normalized_phone,
                    last_name=""
                )
                result = await client(ImportContactsRequest([input_contact]))

                if result.imported:
                    user = result.users[0] if result.users else None
                    user_id = user.id if user else None
                    logger.info(f"[ContactAdder] log_id={log_id}: 添加成功, user_id={user_id}")
                    await _update_log(log_id, 'success', '添加成功', retry_count + 1)
                    if user_id:
                        await _ensure_contact_record(account_id, user_id, contact_phone)
                elif result.users:
                    user_id = result.users[0].id
                    logger.info(f"[ContactAdder] log_id={log_id}: 已是好友, user_id={user_id}")
                    await _update_log(log_id, 'skipped', '已是好友', retry_count + 1)
                    if user_id:
                        await _ensure_contact_record(account_id, user_id, contact_phone)
                else:
                    logger.warning(f"[ContactAdder] log_id={log_id}: 该号码未注册Telegram或无法添加")
                    await _update_log(log_id, 'failed', '该号码未注册Telegram或无法添加', retry_count + 1)

            except Exception as e:
                error_msg = str(e)
                new_retry = retry_count + 1
                logger.error(f"[ContactAdder] log_id={log_id}: 添加异常: {error_msg}")

                if _is_network_error(error_msg) and new_retry < MAX_RETRY_COUNT:
                    # Network error: keep as pending for retry
                    await _update_log(log_id, 'pending', f'网络异常将重试: {error_msg[:200]}', new_retry)
                elif new_retry >= MAX_RETRY_COUNT:
                    await _update_log(log_id, 'failed', f'超过最大重试次数({MAX_RETRY_COUNT}): {error_msg[:200]}', new_retry)
                else:
                    await _update_log(log_id, 'failed', error_msg[:300], new_retry)

            await asyncio.sleep(2)  # rate-limit between add operations

        except Exception as e:
            logger.error(f"[ContactAdder] 处理 log_id={log_entry.get('id')} 异常: {e}")


async def _get_pending_logs() -> list:
    """Get all pending assign logs where retry_count < MAX_RETRY_COUNT."""
    async with database.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT * FROM tg_contact_assign_log "
                "WHERE status = 'pending' AND (retry_count IS NULL OR retry_count < %s) "
                "ORDER BY id ASC",
                (MAX_RETRY_COUNT,),
            )
            return await cur.fetchall()


async def _update_log(log_id: int, status: str, remark: str, retry_count: int):
    """Update a contact assign log entry."""
    async with database.pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE tg_contact_assign_log SET status = %s, remark = %s, retry_count = %s WHERE id = %s",
                (status, remark, retry_count, log_id),
            )


async def _ensure_contact_record(account_id: int, user_id: int, phone: str):
    """Ensure a tg_contact record exists for this account+user."""
    try:
        async with database.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT id FROM tg_contact WHERE tg_account_id = %s AND user_id = %s",
                    (account_id, user_id),
                )
                existing = await cur.fetchone()
                if not existing:
                    await cur.execute(
                        """INSERT INTO tg_contact (tg_account_id, user_id, first_name, nickname,
                           phone_number, is_mutual, is_bot, user_type, auto_reply, create_time)
                           VALUES (%s, %s, %s, %s, %s, 0, 0, 'regular', 1, NOW())""",
                        (account_id, user_id, phone, phone, phone),
                    )
                    logger.info(f"[ContactAdder] tg_contact 已创建: account_id={account_id}, user_id={user_id}")
    except Exception as e:
        logger.error(f"[ContactAdder] 写入tg_contact失败: {e}")
