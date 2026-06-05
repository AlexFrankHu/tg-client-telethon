"""Main application entry point - FastAPI server."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

import config
import database
import client_manager
import notify

# Setup logging
os.makedirs(config.LOGS_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(config.LOGS_DIR, "app.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    # Startup
    logger.info("Starting tg-client-telethon...")
    await database.init_db()

    # Auto-login accounts in loginSuccess directory
    results = await client_manager.login_all_success_accounts()
    online_count = sum(1 for r in results if r.get("success"))
    logger.info(f"Startup login complete: {online_count}/{len(results)} accounts online")

    if results:
        await notify.send_notification(
            "服务启动",
            f"tg-client-telethon 已启动\n登录账号: {online_count}/{len(results)} 个在线"
        )

    yield

    # Shutdown
    logger.info("Shutting down...")
    await client_manager.disconnect_all()
    await database.close_db()
    logger.info("Shutdown complete")


app = FastAPI(title="tg-client-telethon", lifespan=lifespan)


@app.get("/api/status")
async def status():
    """Server status."""
    return {
        "status": "running",
        "active_accounts": client_manager.get_active_phones(),
        "active_count": len(client_manager.active_clients),
    }


@app.post("/api/login/wait")
async def login_wait_accounts():
    """Login all accounts in waitLogin directory."""
    results = await client_manager.login_all_wait_accounts()
    return {
        "total": len(results),
        "success": sum(1 for r in results if r.get("success")),
        "results": results,
    }


@app.post("/api/login/{phone}")
async def login_single_account(phone: str):
    """Login a specific account from waitLogin directory."""
    accounts = client_manager.get_wait_login_accounts()
    target = next((a for a in accounts if a["phone"] == phone), None)
    if not target:
        return {"success": False, "error": f"Account {phone} not found in waitLogin directory"}
    result = await client_manager.login_account(target, from_wait=True)
    return result


@app.post("/api/logout/{phone}")
async def logout_account(phone: str):
    """Logout a specific account."""
    result = await client_manager.logout_account(phone)
    return result


@app.get("/api/accounts")
async def list_accounts():
    """List all accounts from database."""
    accounts = await database.get_all_accounts()
    # Convert datetime objects to string for JSON serialization
    for acc in accounts:
        for key in ["last_login_time", "create_time", "update_time"]:
            if acc.get(key):
                acc[key] = acc[key].strftime("%Y-%m-%d %H:%M:%S")
    return {"accounts": accounts}


@app.get("/api/accounts/active")
async def list_active_accounts():
    """List currently active (online) accounts."""
    return {
        "phones": client_manager.get_active_phones(),
        "count": len(client_manager.active_clients),
    }


@app.get("/api/accounts/wait")
async def list_wait_accounts():
    """List accounts waiting to login."""
    accounts = client_manager.get_wait_login_accounts()
    return {
        "accounts": [{"phone": a["phone"], "api_id": a.get("api_id")} for a in accounts],
        "count": len(accounts),
    }


@app.post("/api/notify/test")
async def test_notify(title: str = "测试通知", content: str = "这是一条测试消息"):
    """Test notification."""
    await notify.send_notification(title, content)
    return {"success": True, "message": "Notification sent"}


if __name__ == "__main__":
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=False)
