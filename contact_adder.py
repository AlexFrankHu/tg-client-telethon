"""Contact adder module - polls pending assign logs and adds contacts via Telethon."""
import asyncio
import logging
import random

import aiohttp
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
        except asyncio.CancelledError:
            break
        try:
            await _process_pending_logs()
        except asyncio.CancelledError:
            logger.warning("[ContactAdder] CancelledError during processing, will retry next cycle")
            continue
        except Exception as e:
            logger.error(f"[ContactAdder] poll error: {e}")


async def _process_pending_logs():
    """Fetch pending assign logs and try to add contacts."""
    pending_logs = await _get_pending_logs()
    if not pending_logs:
        return

    logger.info(f"[ContactAdder] Found {len(pending_logs)} pending assign logs")
    affected_batch_nos = set()

    for log_entry in pending_logs:
        try:
            log_id = log_entry['id']
            account_phone = log_entry['account_phone']
            account_id = log_entry['account_id']
            contact_phone = log_entry.get('contact_phone')
            contact_username = log_entry.get('contact_username')
            contact_batch_no = log_entry.get('contact_batch_no')
            retry_count = log_entry.get('retry_count') or 0

            # Determine if this is a username-based or phone-based add
            is_username = bool(contact_username and not contact_phone)
            contact_display = contact_username if is_username else contact_phone

            # Check if account is online and connected
            if account_phone not in client_manager.active_clients:
                continue

            client = client_manager.active_clients[account_phone]

            # Try to reconnect if client is disconnected
            if not client.is_connected():
                logger.warning(f"[ContactAdder] log_id={log_id}: {account_phone} 已断开连接，尝试重连")
                try:
                    await asyncio.wait_for(client.connect(), timeout=15)
                    logger.info(f"[ContactAdder] {account_phone} 重连成功")
                except Exception as e:
                    logger.warning(f"[ContactAdder] {account_phone} 重连失败: {e}，跳过")
                    continue

            logger.info(f"[ContactAdder] 处理 log_id={log_id}: {account_phone} -> {contact_display} (retry={retry_count}, username={is_username})")

            # Try to add contact with timeout to prevent hanging
            try:
                if is_username:
                    await asyncio.wait_for(
                        _add_by_username(client, log_id, account_id, contact_username, retry_count),
                        timeout=60
                    )
                else:
                    await asyncio.wait_for(
                        _add_by_phone(client, log_id, account_id, contact_phone, retry_count),
                        timeout=60
                    )

            except asyncio.TimeoutError:
                new_retry = retry_count + 1
                logger.error(f"[ContactAdder] log_id={log_id}: 操作超时(60s)")
                await _update_log(log_id, 'pending', '操作超时将重试', new_retry)

            except asyncio.CancelledError:
                logger.warning(f"[ContactAdder] log_id={log_id}: CancelledError，跳过")
                continue

            except Exception as e:
                error_msg = str(e)
                new_retry = retry_count + 1
                logger.error(f"[ContactAdder] log_id={log_id}: 添加异常: {error_msg}")

                if _is_network_error(error_msg) and new_retry < MAX_RETRY_COUNT:
                    await _update_log(log_id, 'pending', f'网络异常将重试: {error_msg[:200]}', new_retry)
                elif new_retry >= MAX_RETRY_COUNT:
                    await _update_log(log_id, 'failed', f'超过最大重试次数({MAX_RETRY_COUNT}): {error_msg[:200]}', new_retry)
                else:
                    await _update_log(log_id, 'failed', error_msg[:300], new_retry)

            if contact_batch_no:
                affected_batch_nos.add(contact_batch_no)

            await asyncio.sleep(2)  # rate-limit between add operations

        except asyncio.CancelledError:
            logger.warning(f"[ContactAdder] CancelledError in log processing loop, continuing")
            continue
        except Exception as e:
            logger.error(f"[ContactAdder] 处理 log_id={log_entry.get('id')} 异常: {e}")

    # Refresh stats for all affected contact batches
    for batch_no in affected_batch_nos:
        await _refresh_batch_stats(batch_no)


async def _add_by_phone(client, log_id, account_id, contact_phone, retry_count):
    """Add contact by phone number using ImportContactsRequest."""
    normalized_phone = contact_phone.strip()
    if not normalized_phone.startswith("+"):
        normalized_phone = "+" + normalized_phone

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
        if user_id:
            await _ensure_contact_record(account_id, user_id, contact_phone)
        return

    # Import contact
    input_contact = InputPhoneContact(
        client_id=random.randint(0, 2**31),
        phone=normalized_phone,
        first_name=normalized_phone,
        last_name=""
    )
    result = await client(ImportContactsRequest([input_contact]))
    logger.info(f"[ContactAdder] log_id={log_id}: ImportContacts结果: imported={len(result.imported)}, users={len(result.users)}, retry_contacts={result.retry_contacts}")

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
    elif result.retry_contacts:
        logger.warning(f"[ContactAdder] log_id={log_id}: ImportContacts被限制, retry_contacts={result.retry_contacts}, 尝试通过搜索添加")
        # retry_contacts means user exists but import was rate-limited, try fallback
        fallback_ok = await _fallback_add_by_phone(client, log_id, account_id, normalized_phone, contact_phone, retry_count)
        if not fallback_ok:
            await _update_log(log_id, 'pending', f'ImportContacts被限制,搜索也失败,将重试', retry_count + 1)
    else:
        # Fallback: try to find the user by phone and add via AddContactRequest
        logger.warning(f"[ContactAdder] log_id={log_id}: ImportContacts返回空, 尝试通过手机号搜索用户")
        fallback_ok = await _fallback_add_by_phone(client, log_id, account_id, normalized_phone, contact_phone, retry_count)
        if not fallback_ok:
            await _update_log(log_id, 'failed', '该号码未注册Telegram或无法添加', retry_count + 1)


async def _fallback_add_by_phone(client, log_id, account_id, normalized_phone, contact_phone, retry_count):
    """Fallback: try ResolvePhone or get_entity to find user, then AddContactRequest."""
    from telethon.tl.functions.contacts import AddContactRequest, ResolvePhoneRequest
    from telethon.tl.types import InputUser

    user = None

    # Method 1: Try ResolvePhoneRequest (Telegram layer 160+)
    try:
        phone_clean = normalized_phone.replace("+", "")
        resolved = await client(ResolvePhoneRequest(phone=phone_clean))
        if resolved and resolved.users:
            user = resolved.users[0]
            logger.info(f"[ContactAdder] log_id={log_id}: ResolvePhone找到用户 user_id={user.id}")
    except Exception as e:
        logger.info(f"[ContactAdder] log_id={log_id}: ResolvePhone失败: {e}")

    # Method 2: Try get_entity with phone number
    if not user:
        try:
            entity = await client.get_entity(normalized_phone)
            if entity:
                user = entity
                logger.info(f"[ContactAdder] log_id={log_id}: get_entity找到用户 user_id={user.id}")
        except Exception as e:
            logger.info(f"[ContactAdder] log_id={log_id}: get_entity失败: {e}")

    if not user:
        logger.warning(f"[ContactAdder] log_id={log_id}: 所有方式都无法找到用户 {normalized_phone}")
        return False

    # Found the user, now add as contact via AddContactRequest
    try:
        input_user = InputUser(user_id=user.id, access_hash=user.access_hash)
        await client(AddContactRequest(
            id=input_user,
            first_name=user.first_name or normalized_phone,
            last_name=user.last_name or "",
            phone=normalized_phone,
            add_phone_privacy_exception=True
        ))
        logger.info(f"[ContactAdder] log_id={log_id}: AddContactRequest成功, user_id={user.id}")
        await _update_log(log_id, 'success', f'通过搜索添加成功(user_id={user.id})', retry_count + 1)
        await _ensure_contact_record(account_id, user.id, contact_phone)
        return True
    except Exception as e:
        logger.error(f"[ContactAdder] log_id={log_id}: AddContactRequest失败: {e}")
        raise  # let outer handler deal with it


async def _add_by_username(client, log_id, account_id, contact_username, retry_count):
    """Add contact by username using get_entity + send_message or AddContactRequest."""
    username = contact_username.strip()
    if username.startswith("@"):
        username = username[1:]

    # Try to resolve the username
    try:
        entity = await client.get_entity(username)
    except Exception as e:
        error_msg = str(e).lower()
        if 'no user has' in error_msg or 'cannot find' in error_msg or 'nobody is using' in error_msg:
            logger.warning(f"[ContactAdder] log_id={log_id}: 用户名 @{username} 不存在")
            await _update_log(log_id, 'failed', f'用户名 @{username} 不存在', retry_count + 1)
            return
        raise  # re-raise for network error handling

    if not entity:
        await _update_log(log_id, 'failed', f'无法解析用户名 @{username}', retry_count + 1)
        return

    user_id = entity.id

    # Check if already a friend
    already_friend = False
    try:
        result = await client(GetContactsRequest(hash=0))
        for user in result.users:
            if user.id == user_id:
                already_friend = True
                break
    except Exception:
        pass

    if already_friend:
        logger.info(f"[ContactAdder] log_id={log_id}: @{username} 已是好友, user_id={user_id}")
        await _update_log(log_id, 'skipped', '已是好友', retry_count + 1)
        await _ensure_contact_record(account_id, user_id, username)
        return

    # Add as contact using AddContactRequest
    from telethon.tl.functions.contacts import AddContactRequest
    from telethon.tl.types import InputUser
    try:
        await client(AddContactRequest(
            id=entity,
            first_name=getattr(entity, 'first_name', '') or username,
            last_name=getattr(entity, 'last_name', '') or '',
            phone='',
            add_phone_privacy_exception=False
        ))
        logger.info(f"[ContactAdder] log_id={log_id}: @{username} 添加成功, user_id={user_id}")
        await _update_log(log_id, 'success', '添加成功', retry_count + 1)
        await _ensure_contact_record(account_id, user_id, username)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[ContactAdder] log_id={log_id}: AddContact @{username} 失败: {error_msg}")
        raise  # let outer handler deal with it


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
                           phone_number, is_mutual, is_bot, user_type, auto_reply, source, create_time)
                           VALUES (%s, %s, %s, %s, %s, 0, 0, 'regular', 1, 'import', NOW())""",
                        (account_id, user_id, phone, phone, phone),
                    )
                    logger.info(f"[ContactAdder] tg_contact 已创建: account_id={account_id}, user_id={user_id}")
                else:
                    await cur.execute(
                        "UPDATE tg_contact SET source = 'import' WHERE id = %s AND source != 'import'",
                        (existing['id'],),
                    )
    except Exception as e:
        logger.error(f"[ContactAdder] 写入tg_contact失败: {e}")


async def _refresh_batch_stats(batch_no: str):
    """Call Java API to refresh contact import batch statistics."""
    try:
        url = f"http://localhost:8809/tg/import/refreshContactBatchStats?batchNo={batch_no}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    logger.info(f"[ContactAdder] 已刷新批次统计: {batch_no}")
                else:
                    logger.warning(f"[ContactAdder] 刷新批次统计失败: {batch_no}, status={resp.status}")
    except Exception as e:
        logger.warning(f"[ContactAdder] 刷新批次统计异常: {batch_no}, {e}")
