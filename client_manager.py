"""Telegram client manager using Telethon."""
import os
import json
import shutil
import asyncio
import logging
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    AuthKeyUnregisteredError, UserDeactivatedBanError,
)

import config
import database
import notify

logger = logging.getLogger(__name__)

# Active clients: phone -> TelegramClient
active_clients: dict[str, TelegramClient] = {}


def get_wait_login_accounts() -> list[dict]:
    """Scan waitLogin directory for account files (.json + .session pairs)."""
    accounts = []
    wait_dir = config.WAIT_LOGIN_DIR
    if not os.path.exists(wait_dir):
        return accounts

    json_files = [f for f in os.listdir(wait_dir) if f.endswith(".json")]
    for jf in json_files:
        phone = jf.replace(".json", "")
        session_file = phone + ".session"
        if os.path.exists(os.path.join(wait_dir, session_file)):
            json_path = os.path.join(wait_dir, jf)
            try:
                with open(json_path, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                accounts.append({
                    "phone": phone,
                    "json_path": json_path,
                    "session_path": os.path.join(wait_dir, session_file),
                    "api_id": data.get("app_id") or data.get("api_id"),
                    "api_hash": data.get("app_hash") or data.get("api_hash"),
                    "data": data,
                })
            except Exception as e:
                logger.error(f"Failed to read {json_path}: {e}")
    return accounts


def get_login_success_accounts() -> list[dict]:
    """Scan loginSuccess directory for already logged-in accounts."""
    accounts = []
    success_dir = config.LOGIN_SUCCESS_DIR
    if not os.path.exists(success_dir):
        return accounts

    for folder_name in os.listdir(success_dir):
        folder_path = os.path.join(success_dir, folder_name)
        if not os.path.isdir(folder_path):
            continue

        phone = folder_name
        json_file = os.path.join(folder_path, phone + ".json")
        session_file = os.path.join(folder_path, phone + ".session")

        if os.path.exists(json_file) and os.path.exists(session_file):
            try:
                with open(json_file, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                accounts.append({
                    "phone": phone,
                    "folder_path": folder_path,
                    "json_path": json_file,
                    "session_path": session_file,
                    "api_id": data.get("app_id") or data.get("api_id"),
                    "api_hash": data.get("app_hash") or data.get("api_hash"),
                    "data": data,
                })
            except Exception as e:
                logger.error(f"Failed to read {json_file}: {e}")
    return accounts


def _move_to_failed(phone: str):
    """Move account files from waitLogin to loginFailed directory."""
    os.makedirs(config.LOGIN_FAILED_DIR, exist_ok=True)
    src_json = os.path.join(config.WAIT_LOGIN_DIR, phone + ".json")
    src_session = os.path.join(config.WAIT_LOGIN_DIR, phone + ".session")
    dst_json = os.path.join(config.LOGIN_FAILED_DIR, phone + ".json")
    dst_session = os.path.join(config.LOGIN_FAILED_DIR, phone + ".session")
    if os.path.exists(src_json):
        shutil.move(src_json, dst_json)
    if os.path.exists(src_session):
        shutil.move(src_session, dst_session)


async def login_account(account: dict, from_wait: bool = True) -> dict:
    """Login a single account using Telethon.

    Args:
        account: Account info dict with phone, api_id, api_hash, session_path, etc.
        from_wait: If True, move files from waitLogin to loginSuccess on success.

    Returns:
        dict with login result.
    """
    phone = account["phone"]
    api_id = account.get("api_id")
    api_hash = account.get("api_hash")

    if not api_id or not api_hash:
        msg = f"Account {phone}: missing api_id or api_hash"
        logger.error(msg)
        if from_wait:
            _move_to_failed(phone)
        await notify.send_notification("登录失败", f"账号 +{phone}\n原因: 缺少 api_id 或 api_hash")
        return {"phone": phone, "success": False, "error": msg}

    # Session file path (without .session extension for Telethon)
    if from_wait:
        session_path = os.path.join(config.WAIT_LOGIN_DIR, phone)
    else:
        session_path = os.path.join(account["folder_path"], phone)

    try:
        client = TelegramClient(session_path, api_id, api_hash)
        await client.connect()

        if not await client.is_user_authorized():
            msg = f"Account {phone}: session not authorized, cannot auto-login"
            logger.warning(msg)
            await client.disconnect()
            if from_wait:
                _move_to_failed(phone)
            await notify.send_notification("登录失败", f"账号 +{phone}\n原因: session 未授权，需要重新验证")
            return {"phone": phone, "success": False, "error": msg}

        # Get user info
        me = await client.get_me()
        nickname = " ".join(filter(None, [me.first_name, me.last_name]))
        username = me.username

        # Login success - move files if from waitLogin
        if from_wait:
            dest_dir = os.path.join(config.LOGIN_SUCCESS_DIR, phone)
            os.makedirs(dest_dir, exist_ok=True)
            # Create data folder for this account's cache
            os.makedirs(os.path.join(dest_dir, "data"), exist_ok=True)

            # Move .json and .session files
            src_json = os.path.join(config.WAIT_LOGIN_DIR, phone + ".json")
            src_session = os.path.join(config.WAIT_LOGIN_DIR, phone + ".session")
            dst_json = os.path.join(dest_dir, phone + ".json")
            dst_session = os.path.join(dest_dir, phone + ".session")

            if os.path.exists(src_json):
                shutil.move(src_json, dst_json)
            if os.path.exists(src_session):
                shutil.move(src_session, dst_session)

            # Telethon creates session at session_path + ".session"
            # After move, we need to reconnect from new location
            await client.disconnect()
            new_session_path = os.path.join(dest_dir, phone)
            client = TelegramClient(new_session_path, api_id, api_hash)
            await client.connect()

        # Save to active clients
        active_clients[phone] = client

        # Update database
        await database.upsert_account(
            phone=phone,
            api_id=api_id,
            api_hash=api_hash,
            tg_user_id=me.id,
            nickname=nickname,
            username=username,
            status="online",
        )

        logger.info(f"Account +{phone} logged in successfully (user_id={me.id}, nickname={nickname})")
        await notify.send_notification(
            "登录成功",
            f"账号: +{phone}\n昵称: {nickname}\n用户名: @{username or '-'}\nUser ID: {me.id}"
        )

        return {
            "phone": phone,
            "success": True,
            "user_id": me.id,
            "nickname": nickname,
            "username": username,
        }

    except (AuthKeyUnregisteredError, UserDeactivatedBanError) as e:
        error_msg = str(e)
        logger.error(f"Account +{phone} banned/deactivated: {error_msg}")
        if from_wait:
            _move_to_failed(phone)
        await database.upsert_account(phone=phone, api_id=api_id, api_hash=api_hash, status="banned")
        await notify.send_notification("账号已被注销", f"账号: +{phone}\n原因: {error_msg}")
        return {"phone": phone, "success": False, "error": error_msg}

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Account +{phone} login failed: {error_msg}")
        if from_wait:
            _move_to_failed(phone)
        await notify.send_notification("登录失败", f"账号: +{phone}\n原因: {error_msg}")
        return {"phone": phone, "success": False, "error": error_msg}


async def login_all_wait_accounts() -> list[dict]:
    """Login all accounts in waitLogin directory."""
    accounts = get_wait_login_accounts()
    if not accounts:
        logger.info("No accounts in waitLogin directory")
        return []

    results = []
    for account in accounts:
        result = await login_account(account, from_wait=True)
        results.append(result)
        await asyncio.sleep(1)  # Small delay between logins

    return results


async def login_all_success_accounts() -> list[dict]:
    """Re-login all accounts in loginSuccess directory (used on startup)."""
    accounts = get_login_success_accounts()
    if not accounts:
        logger.info("No accounts in loginSuccess directory")
        return []

    results = []
    for account in accounts:
        result = await login_account(account, from_wait=False)
        results.append(result)
        await asyncio.sleep(1)

    return results


async def logout_account(phone: str) -> dict:
    """Disconnect and mark account as offline."""
    client = active_clients.pop(phone, None)
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass

    await database.update_status(phone, "offline")
    logger.info(f"Account +{phone} logged out")
    return {"phone": phone, "status": "offline"}


async def disconnect_all():
    """Disconnect all active clients."""
    for phone, client in list(active_clients.items()):
        try:
            await client.disconnect()
            await database.update_status(phone, "offline")
        except Exception:
            pass
    active_clients.clear()
    logger.info("All clients disconnected")


def get_active_phones() -> list[str]:
    """Get list of currently active account phones."""
    return list(active_clients.keys())
