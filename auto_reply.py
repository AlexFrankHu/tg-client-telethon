"""Auto-reply module for automatic message responses.

Two triggers:
1. Incoming message (state=0): reply to friend's message in real-time.
2. Periodic polling (state=1~8): proactively send messages based on rules.
"""
import asyncio
import logging
from datetime import datetime, timedelta

import httpx
import aiomysql
from telethon.tl.types import User

import config
import database
import client_manager

logger = logging.getLogger(__name__)

# Official / excluded Telegram IDs (extensible)
OFFICIAL_IDS = {777000}

# Configuration (from config module)
REPLY_API_URL = getattr(config, 'REPLY_API_URL', 'http://127.0.0.1:8000/generate-reply')
POLL_INTERVAL = getattr(config, 'AUTO_REPLY_INTERVAL', 300)  # seconds


# ---------------------------------------------------------------------------
# Trigger 1: Incoming message auto-reply (state=0)
# ---------------------------------------------------------------------------

async def handle_incoming_message(phone: str, event, client):
    """Handle incoming message for auto-reply (state=0)."""
    try:
        msg = event.message
        if not msg or msg.out:
            return

        user_id = msg.sender_id
        if not user_id:
            logger.debug(f"[{phone}] [AutoReply] 跳过: sender_id 为空")
            return

        logger.info(f"[{phone}] [AutoReply] 收到消息, sender_id={user_id}")

        # Exclude official IDs
        if user_id in OFFICIAL_IDS:
            logger.info(f"[{phone}] [AutoReply] 跳过: 官方ID {user_id}")
            return

        # Exclude bots
        try:
            sender = await event.get_sender()
            if not sender or not isinstance(sender, User):
                logger.info(f"[{phone}] [AutoReply] 跳过: sender不是User类型")
                return
            if sender.bot:
                logger.info(f"[{phone}] [AutoReply] 跳过: 机器人 {user_id}")
                return
        except Exception as e:
            logger.warning(f"[{phone}] [AutoReply] 获取sender失败: {e}")
            return

        # Account info
        account = await database.get_account_by_phone(phone)
        if not account:
            logger.info(f"[{phone}] [AutoReply] 跳过: 账号不存在")
            return
        if not account.get('auto_reply', 1):
            logger.info(f"[{phone}] [AutoReply] 跳过: 账号未开启自动回复")
            return
        account_id = account['id']

        # Contact info — wait briefly for save_realtime_message to upsert contact
        await asyncio.sleep(1)
        contact = await _get_contact(account_id, user_id)
        if not contact:
            logger.info(f"[{phone}] [AutoReply] 跳过: 好友 {user_id} 不在联系人表中")
            return
        if not contact.get('auto_reply', 1):
            logger.info(f"[{phone}] [AutoReply] 跳过: 好友 {user_id} 未开启自动回复")
            return

        # Build context & call API
        my_nickname = account.get('nickname') or phone
        friend_nickname = contact.get('nickname') or str(user_id)
        logger.info(f"[{phone}] [AutoReply] 准备请求自动回复: state=0, "
                    f"account_id={account_id}, user_id={user_id}, "
                    f"my_nickname={my_nickname}, friend_nickname={friend_nickname}")

        chat_context = await _build_chat_context(account_id, user_id, my_nickname, friend_nickname)

        reply = await _get_reply_content(
            state=0,
            my_nickname=my_nickname,
            customer_name=friend_nickname,
            chat_context=chat_context,
        )
        if reply:
            await asyncio.sleep(2)  # brief delay for naturalness
            await _send_auto_reply(client, phone, account_id, user_id, reply)
            logger.info(f"[{phone}] [AutoReply] 自动回复成功: user_id={user_id}, state=0")
        else:
            logger.warning(f"[{phone}] [AutoReply] API未返回有效回复内容")
    except Exception as e:
        logger.error(f"[{phone}] [AutoReply] 处理incoming消息异常: {e}")


# ---------------------------------------------------------------------------
# Trigger 2: Periodic polling (state=1~8)
# ---------------------------------------------------------------------------

async def poll_auto_reply():
    """Background task: poll contacts for proactive auto-reply every POLL_INTERVAL seconds."""
    while True:
        try:
            await asyncio.sleep(POLL_INTERVAL)
            logger.info("Auto-reply poll: starting...")
            await _process_proactive_replies()
            logger.info("Auto-reply poll: done")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Auto-reply poll error: {e}")


async def _process_proactive_replies():
    """Iterate eligible contacts and send proactive messages where state >= 0."""
    contacts = await _get_eligible_contacts()
    if not contacts:
        return

    logger.info(f"Auto-reply poll: {len(contacts)} eligible contacts")

    for row in contacts:
        try:
            phone = row['phone']
            if phone not in client_manager.active_clients:
                continue

            client = client_manager.active_clients[phone]
            account_id = row['account_id']
            user_id = row['user_id']

            last_send_time = row.get('last_send_time')
            last_receive_time = row.get('last_receive_time')

            state = await _calculate_state(account_id, user_id, last_send_time, last_receive_time)
            if state < 0:
                continue

            my_nickname = row.get('account_nickname') or phone
            friend_nickname = row.get('nickname') or str(user_id)
            chat_context = await _build_chat_context(account_id, user_id, my_nickname, friend_nickname)

            reply = await _get_reply_content(
                state=state,
                my_nickname=my_nickname,
                customer_name=friend_nickname,
                chat_context=chat_context,
            )
            if reply:
                await _send_auto_reply(client, phone, account_id, user_id, reply)
                logger.info(f"[{phone}] Proactive auto-reply to {user_id} (state={state})")
                await asyncio.sleep(3)  # rate-limit between sends
        except Exception as e:
            logger.error(f"Auto-reply poll error for user_id={row.get('user_id')}: {e}")


# ---------------------------------------------------------------------------
# State calculation
# ---------------------------------------------------------------------------

async def _calculate_state(account_id: int, chat_id: int,
                           last_send_time, last_receive_time) -> int:
    """Return the state (1~8) for proactive messaging, or -1 to skip."""
    now = datetime.now()

    if last_receive_time is None:
        # Friend has never sent a message
        if last_send_time is None:
            return 1

        send_count = await _get_outgoing_message_count(account_id, chat_id)
        if send_count == 0:
            return 1

        hours_since_last = (now - last_send_time).total_seconds() / 3600

        if send_count == 1 and hours_since_last >= 1:
            return 2
        if send_count == 2 and hours_since_last >= 3:
            return 3
        if send_count == 3 and hours_since_last >= 24:
            return 4
        return -1  # send_count > 3 or interval too short
    else:
        # Friend has sent messages before
        if last_send_time is None:
            return -1

        hours_since_last = (now - last_send_time).total_seconds() / 3600

        # Check last 5 messages to count consecutive outgoing from the newest
        last_messages = await _get_last_messages(account_id, chat_id, 5)
        consecutive_out = 0
        for m in last_messages:
            if m.get('is_outgoing'):
                consecutive_out += 1
            else:
                break

        if consecutive_out >= 5:
            return -1
        if consecutive_out == 4 and 48 <= hours_since_last <= 72:
            return 8
        if consecutive_out == 3 and 24 <= hours_since_last <= 48:
            return 7
        if consecutive_out == 2 and 12 <= hours_since_last <= 24:
            return 6
        if consecutive_out == 1 and 3 <= hours_since_last <= 12:
            return 5
        return -1


# ---------------------------------------------------------------------------
# Reply API
# ---------------------------------------------------------------------------

async def _get_reply_content(state: int, my_nickname: str,
                             customer_name: str, chat_context: str) -> str | None:
    """Call http://127.0.0.1:8000/generate-reply and return the reply text."""
    try:
        body = {
            "state": state,
            "agent_gender": 1,       # female (fixed)
            "customer_gender": 2,    # unknown (fixed)
            "my_nickname": my_nickname,
            "customer_name": customer_name,
            "chat_context": chat_context,
        }
        logger.info(f"[AutoReply] 请求地址: {REPLY_API_URL}")
        logger.info(f"[AutoReply] 请求参数: state={state}, agent_gender=1, customer_gender=2, "
                     f"my_nickname={my_nickname}, customer_name={customer_name}")
        logger.info(f"[AutoReply] chat_context:\n{chat_context}")

        async with httpx.AsyncClient(timeout=30) as http_client:
            resp = await http_client.post(REPLY_API_URL, json=body)
            logger.info(f"[AutoReply] 响应状态码: {resp.status_code}")
            logger.info(f"[AutoReply] 响应内容: {resp.text}")
            if resp.status_code == 200:
                data = resp.json()
                reply = data.get("reply")
                logger.info(f"[AutoReply] 解析回复内容: {reply}")
                return reply
            logger.warning(f"[AutoReply] API返回非200: {resp.status_code}, body={resp.text[:500]}")
    except Exception as e:
        logger.error(f"[AutoReply] API请求异常: {e}")
    return None


# ---------------------------------------------------------------------------
# Send message helper
# ---------------------------------------------------------------------------

async def _send_auto_reply(client, phone: str, account_id: int,
                           user_id: int, text: str):
    """Send a message via Telethon. Event handler saves it & updates last_send_time."""
    try:
        await client.send_message(user_id, text)
        logger.info(f"[{phone}] Sent auto-reply to {user_id}: {text[:80]}...")
    except Exception as e:
        logger.error(f"[{phone}] Failed to send auto-reply to {user_id}: {e}")


# ---------------------------------------------------------------------------
# Chat context builder
# ---------------------------------------------------------------------------

async def _build_chat_context(account_id: int, chat_id: int,
                              my_nickname: str, friend_nickname: str,
                              limit: int = 20) -> str:
    """Build context string: {nickname}[{time}]:{content} per line."""
    messages = await _get_chat_messages(account_id, chat_id, limit)
    if not messages:
        return ""

    messages.reverse()  # chronological order

    lines = []
    for msg in messages:
        nickname = my_nickname if msg.get('is_outgoing') else friend_nickname
        t = msg.get('send_time')
        time_str = t.strftime('%Y-%m-%d %H:%M:%S') if t else ''
        content = msg.get('text_content') or ''
        if content:
            lines.append(f"{nickname}[{time_str}]:{content}")
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

async def _get_contact(account_id: int, user_id: int):
    async with database.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT * FROM tg_contact WHERE tg_account_id = %s AND user_id = %s",
                (account_id, user_id),
            )
            return await cur.fetchone()


async def _get_eligible_contacts() -> list:
    """Contacts eligible for proactive auto-reply polling."""
    placeholders = ','.join(['%s'] * len(OFFICIAL_IDS)) if OFFICIAL_IDS else '0'
    params = list(OFFICIAL_IDS) if OFFICIAL_IDS else []

    sql = f"""
        SELECT c.*,
               a.id AS account_id, a.phone,
               a.nickname AS account_nickname
        FROM tg_contact c
        JOIN tg_telethon_account a ON c.tg_account_id = a.id
        WHERE c.auto_reply = 1
          AND c.is_bot = 0
          AND c.user_id NOT IN ({placeholders})
          AND a.auto_reply = 1
          AND a.status = 'online'
          AND (a.is_deleted = 0 OR a.is_deleted IS NULL)
          AND (
              c.last_send_time IS NULL
              OR c.last_receive_time IS NULL
              OR (
                  TIMESTAMPDIFF(HOUR, c.last_send_time, NOW()) < 72
                  AND c.last_send_time > c.last_receive_time
              )
          )
    """
    async with database.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()


async def _get_outgoing_message_count(account_id: int, chat_id: int) -> int:
    async with database.pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM tg_chat_message "
                "WHERE tg_account_id = %s AND chat_id = %s AND is_outgoing = 1",
                (account_id, chat_id),
            )
            row = await cur.fetchone()
            return row[0] if row else 0


async def _get_last_messages(account_id: int, chat_id: int, limit: int = 5) -> list:
    """Last N messages (newest first)."""
    async with database.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT is_outgoing, send_time, text_content "
                "FROM tg_chat_message "
                "WHERE tg_account_id = %s AND chat_id = %s "
                "ORDER BY send_time DESC, message_id DESC LIMIT %s",
                (account_id, chat_id, limit),
            )
            return await cur.fetchall()


async def _get_chat_messages(account_id: int, chat_id: int, limit: int = 20) -> list:
    """Recent messages for context building (newest first)."""
    async with database.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT is_outgoing, send_time, text_content "
                "FROM tg_chat_message "
                "WHERE tg_account_id = %s AND chat_id = %s "
                "ORDER BY send_time DESC, message_id DESC LIMIT %s",
                (account_id, chat_id, limit),
            )
            return await cur.fetchall()
