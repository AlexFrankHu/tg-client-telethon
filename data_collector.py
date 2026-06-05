"""Data collection module - collects contacts and chat history."""
import logging
import asyncio
from datetime import datetime
from telethon import functions
from telethon.tl.types import (
    User, UserStatusOnline, UserStatusOffline, UserStatusRecently,
    MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage,
    Document, Photo, MessageService
)
import database

logger = logging.getLogger(__name__)

CONTACT_TABLE = "tg_contact"
MESSAGE_TABLE = "tg_chat_message"


async def get_account_id(phone: str):
    """Get account ID from database by phone."""
    account = await database.get_account_by_phone(phone)
    if account:
        return account["id"]
    return None


async def sync_contacts_and_history(client, phone: str):
    """Sync contacts and chat history for an account."""
    account_id = await get_account_id(phone)
    if not account_id:
        logger.warning(f"Account {phone} not found in database, skip sync")
        return

    logger.info(f"[{phone}] Starting data sync...")

    # 1. Collect contacts
    try:
        result = await client(functions.contacts.GetContactsRequest(hash=0))
        contacts = getattr(result, "users", [])
        logger.info(f"[{phone}] Got {len(contacts)} contacts")
        for user in contacts:
            if isinstance(user, User):
                await upsert_contact(account_id, user)
    except Exception as e:
        logger.error(f"[{phone}] Failed to get contacts: {e}")

    # 2. Collect chats and history
    try:
        dialogs = await client.get_dialogs(limit=100)
        logger.info(f"[{phone}] Got {len(dialogs)} dialogs")
        for dialog in dialogs:
            if dialog.is_user:
                # Save the user as contact too
                entity = dialog.entity
                if isinstance(entity, User):
                    await upsert_contact(account_id, entity)
                # Get chat history
                await collect_chat_history(client, account_id, dialog.entity.id)
            elif dialog.is_group or dialog.is_channel:
                # Get group/channel history too
                await collect_chat_history(client, account_id, dialog.entity.id)
            await asyncio.sleep(0.5)  # Rate limit
    except Exception as e:
        logger.error(f"[{phone}] Failed to collect dialogs: {e}")

    logger.info(f"[{phone}] Data sync complete")


async def collect_chat_history(client, account_id: int, chat_id: int, limit: int = 500):
    """Collect chat history for a specific chat."""
    try:
        messages = await client.get_messages(chat_id, limit=limit)
        count = 0
        for msg in messages:
            if isinstance(msg, MessageService):
                continue
            await upsert_message(account_id, chat_id, msg)
            count += 1
        if count > 0:
            logger.debug(f"  Collected {count} messages for chat {chat_id}")
    except Exception as e:
        logger.error(f"  Failed to collect history for chat {chat_id}: {e}")


async def upsert_contact(account_id: int, user: User):
    """Insert or update a contact record."""
    try:
        user_id = user.id
        first_name = user.first_name or ""
        last_name = user.last_name or ""
        nickname = " ".join(filter(None, [first_name, last_name]))
        username = user.username
        phone_number = user.phone
        is_mutual = getattr(user, "mutual_contact", False)
        is_bot = user.bot or False
        is_premium = getattr(user, "premium", False) or False
        is_verified = getattr(user, "verified", False) or False

        if user.bot:
            user_type = "bot"
        elif user.deleted:
            user_type = "deleted"
        else:
            user_type = "regular"

        # Last online time
        last_online = None
        status = user.status
        if isinstance(status, UserStatusOnline):
            last_online = datetime.now()
        elif isinstance(status, UserStatusOffline):
            last_online = status.was_online

        async with database.pool.acquire() as conn:
            async with conn.cursor() as cur:
                sql = f"""
                    INSERT INTO `{CONTACT_TABLE}` (tg_account_id, user_id, first_name, last_name, nickname,
                        username, phone_number, is_mutual, is_bot, is_premium, is_verified, user_type,
                        last_online_time, update_time)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON DUPLICATE KEY UPDATE
                        first_name = VALUES(first_name),
                        last_name = VALUES(last_name),
                        nickname = VALUES(nickname),
                        username = VALUES(username),
                        phone_number = VALUES(phone_number),
                        is_mutual = VALUES(is_mutual),
                        is_bot = VALUES(is_bot),
                        is_premium = VALUES(is_premium),
                        is_verified = VALUES(is_verified),
                        user_type = VALUES(user_type),
                        last_online_time = VALUES(last_online_time),
                        update_time = NOW()
                """
                await cur.execute(sql, (account_id, user_id, first_name, last_name, nickname,
                                        username, phone_number, is_mutual, is_bot, is_premium,
                                        is_verified, user_type, last_online))
    except Exception as e:
        logger.error(f"Failed to upsert contact {user.id}: {e}")


async def save_realtime_message(phone: str, event):
    """Save a real-time incoming/outgoing message to database."""
    try:
        account_id = await get_account_id(phone)
        if not account_id:
            return
        chat_id = event.chat_id
        msg = event.message
        if msg and not isinstance(msg, MessageService):
            await upsert_message(account_id, chat_id, msg)
    except Exception as e:
        logger.error(f"[{phone}] save_realtime_message error: {e}")


async def upsert_message(account_id: int, chat_id: int, msg):
    """Insert a message record (skip if exists)."""
    try:
        message_id = msg.id
        sender_user_id = msg.sender_id.user_id if msg.sender_id and hasattr(msg.sender_id, "user_id") else None
        sender_chat_id = msg.sender_id.channel_id if msg.sender_id and hasattr(msg.sender_id, "channel_id") else None
        sender_name = None
        is_outgoing = msg.out or False
        send_time = msg.date

        # Determine content type and extract media info
        content_type = "text"
        text_content = msg.text or msg.message or ""
        media_file_id = None
        media_file_size = None
        media_mime_type = None
        media_file_name = None
        media_duration = None
        media_width = None
        media_height = None
        thumbnail_file_id = None

        if msg.media:
            if isinstance(msg.media, MessageMediaPhoto):
                content_type = "photo"
                if msg.media.photo and isinstance(msg.media.photo, Photo):
                    media_file_id = str(msg.media.photo.id)
            elif isinstance(msg.media, MessageMediaDocument):
                doc = msg.media.document
                if isinstance(doc, Document):
                    media_file_id = str(doc.id)
                    media_file_size = doc.size
                    media_mime_type = doc.mime_type
                    for attr in doc.attributes:
                        attr_type = type(attr).__name__
                        if attr_type == "DocumentAttributeFilename":
                            media_file_name = attr.file_name
                        elif attr_type == "DocumentAttributeVideo":
                            content_type = "video"
                            media_duration = attr.duration
                            media_width = attr.w
                            media_height = attr.h
                        elif attr_type == "DocumentAttributeAudio":
                            if attr.voice:
                                content_type = "voice"
                            else:
                                content_type = "document"
                            media_duration = attr.duration
                        elif attr_type == "DocumentAttributeSticker":
                            content_type = "sticker"
                    if content_type == "text":
                        content_type = "document"
            elif isinstance(msg.media, MessageMediaWebPage):
                content_type = "text"  # Keep as text with URL
            else:
                content_type = "other"

        async with database.pool.acquire() as conn:
            async with conn.cursor() as cur:
                sql = f"""
                    INSERT IGNORE INTO `{MESSAGE_TABLE}` (tg_account_id, chat_id, message_id, sender_user_id,
                        sender_chat_id, sender_name, is_outgoing, send_time, content_type, text_content,
                        media_file_id, media_file_size, media_mime_type, media_file_name, media_duration,
                        media_width, media_height, thumbnail_file_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                await cur.execute(sql, (account_id, chat_id, message_id, sender_user_id,
                                        sender_chat_id, sender_name, is_outgoing, send_time,
                                        content_type, text_content, media_file_id, media_file_size,
                                        media_mime_type, media_file_name, media_duration,
                                        media_width, media_height, thumbnail_file_id))
    except Exception as e:
        logger.error(f"Failed to insert message {msg.id}: {e}")
