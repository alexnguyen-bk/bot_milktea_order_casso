import asyncio
import logging
import signal
import sys
import os
import json
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from telegram.ext import Application

# Thêm thư mục gốc vào sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from bot.database import Database
from bot.telegram_handler import create_application
from bot.payment import format_order_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────
# FastAPI Admin API
# ──────────────────────────────────────────────────────

def create_api(database: Database) -> FastAPI:
    api = FastAPI(title="Milkteainfo Admin API", version="1.0")
    api.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @api.get("/orders")
    async def get_orders(status: str = None, limit: int = 50):
        orders = await database.get_all_orders(status=status, limit=limit)
        return orders

    @api.get("/orders/{order_number}")
    async def get_order(order_number: str):
        order = await database.get_order(order_number.upper())
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return order

    @api.post("/orders/{order_number}/done")
    async def mark_done(order_number: str):
        order = await database.mark_order_done(order_number.upper())
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return order

    @api.get("/stats")
    async def get_stats():
        return await database.get_stats()

    @api.post("/webhook/payos")
    async def payos_webhook(request: Request):
        """Nhận callback từ PayOS khi thanh toán thành công."""
        try:
            body = await request.json()
            order_code = str(body.get("data", {}).get("orderCode", ""))
            status = body.get("data", {}).get("status", "")
            if status == "PAID" and order_code:
                await database.mark_order_paid(order_code)
                logger.info(f"PayOS webhook: Order {order_code} marked as paid")
            return {"code": "00", "desc": "success"}
        except Exception as e:
            logger.error(f"PayOS webhook error: {e}")
            return {"code": "01", "desc": str(e)}

    @api.get("/health")
    async def health():
        return {"status": "ok", "service": "Milkteainfo Bot"}

    return api


# ──────────────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────────────

async def main():
    # Kiểm tra BOT_TOKEN
    if not settings.BOT_TOKEN:
        logger.error("BOT_TOKEN chưa được cấu hình! Kiểm tra file .env")
        sys.exit(1)

    if not settings.has_gemini:
        logger.warning("⚠️  GEMINI_API_KEY chưa set — bot sẽ không trả lời được!")

    logger.info(f"🧋 Khởi động Milkteainfo Bot...")
    logger.info(f"📦 Database: {settings.DB_PATH}")
    logger.info(f"💳 Payment: {'Mock' if settings.use_mock_payment else 'PayOS thực'}")
    logger.info(f"🌐 Mode: {'Webhook' if settings.use_webhook else 'Polling'}")

    # Khởi tạo database
    database = Database(settings.DB_PATH)
    await database.init()
    logger.info("✅ Database đã sẵn sàng")

    # Tạo bot application
    bot_app: Application = create_application(database)
    await bot_app.initialize()

    # Tạo FastAPI admin API
    api_app = create_api(database)

    if settings.use_webhook:
        # ── Chế độ Webhook (production) ──
        webhook_url = f"{settings.WEBHOOK_URL}/telegram/{settings.BOT_TOKEN}"
        await bot_app.bot.set_webhook(url=webhook_url)
        logger.info(f"✅ Webhook đã đặt tại: {webhook_url}")

        # Thêm webhook handler vào FastAPI
        @api_app.post(f"/telegram/{settings.BOT_TOKEN}")
        async def telegram_webhook(request: Request):
            from telegram import Update
            data = await request.json()
            update = Update.de_json(data, bot_app.bot)
            await bot_app.process_update(update)
            return JSONResponse(content={"ok": True})

        await bot_app.start()
        server = uvicorn.Server(
            uvicorn.Config(api_app, host="0.0.0.0", port=settings.API_PORT, log_level="warning")
        )
        logger.info(f"🚀 Server đang chạy tại port {settings.API_PORT}")
        await server.serve()
        await bot_app.stop()

    else:
        # ── Chế độ Polling (local dev) ──
        await bot_app.start()
        await bot_app.updater.start_polling(drop_pending_updates=True)
        logger.info("✅ Bot đang chạy (polling mode)...")
        logger.info("   Nhấn Ctrl+C để dừng bot")

        # Thử chạy FastAPI, tự tìm port chưa bị chiếm
        import socket as _socket
        api_task = None
        server = None
        for port in [settings.API_PORT, settings.API_PORT + 1, 8080, 8888]:
            with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
                if s.connect_ex(("localhost", port)) != 0:  # port trống
                    server_config = uvicorn.Config(
                        api_app, host="0.0.0.0", port=port, log_level="warning"
                    )
                    server = uvicorn.Server(server_config)
                    logger.info(f"📊 Admin API: http://localhost:{port}/orders")
                    logger.info(f"📊 Admin Dashboard: mở file admin/dashboard.html trong trình duyệt")
                    api_task = asyncio.create_task(server.serve())
                    break

        if not api_task:
            logger.warning("⚠️  Không tìm được port trống cho Admin API. Bot vẫn chạy bình thường.")

        # Giữ bot chạy đến khi Ctrl+C
        try:
            if api_task:
                await api_task
            else:
                await asyncio.Event().wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("🛑 Đang tắt bot...")
        finally:
            if server:
                server.should_exit = True
            if api_task and not api_task.done():
                api_task.cancel()
                try:
                    await api_task
                except (asyncio.CancelledError, Exception):
                    pass
            await bot_app.updater.stop()
            await bot_app.stop()
            await bot_app.shutdown()
            logger.info("👋 Bot đã tắt. Tạm biệt!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
