import hashlib
import hmac
import json
import logging
import time
from datetime import datetime
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


def generate_order_number() -> str:
    """Tạo mã đơn hàng dạng MMDD + 4 số."""
    now = datetime.now()
    ts = str(int(time.time() * 1000))[-4:]
    return f"{now.strftime('%m%d')}{ts}"


# ──────────────────────────────────────────────────────
# MOCK PAYMENT (dùng khi không có PayOS credentials)
# ──────────────────────────────────────────────────────

class MockPayment:
    """Mock thanh toán để demo không cần PayOS account thật."""

    async def create_payment_link(self, order_number: str, amount: int, description: str) -> dict:
        fake_link = f"https://pay.milkteainfo.demo/order/{order_number}"
        return {
            "success": True,
            "order_number": order_number,
            "amount": amount,
            "payment_link": fake_link,
            "payment_id": f"MOCK-{order_number}",
            "is_mock": True,
        }

    async def verify_webhook(self, data: dict, signature: str) -> bool:
        return True  # Mock always succeeds


# ──────────────────────────────────────────────────────
# REAL PAYOS INTEGRATION
# ──────────────────────────────────────────────────────

class PayOSPayment:
    """Tích hợp PayOS thực để thanh toán QR."""

    BASE_URL = "https://api-merchant.payos.vn"

    def __init__(self):
        self.client_id = settings.PAYOS_CLIENT_ID
        self.api_key = settings.PAYOS_API_KEY
        self.checksum_key = settings.PAYOS_CHECKSUM_KEY

    def _sign(self, data: dict) -> str:
        """Tạo chữ ký HMAC-SHA256."""
        payload = "&".join(f"{k}={v}" for k, v in sorted(data.items()))
        return hmac.new(
            self.checksum_key.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

    async def create_payment_link(self, order_number: str, amount: int, description: str) -> dict:
        order_code = int(order_number.replace("-", "")) % 9007199254740991  # JS safe int

        payload = {
            "orderCode": order_code,
            "amount": amount,
            "description": description[:25],  # PayOS giới hạn 25 ký tự
            "returnUrl": "https://milkteainfo.com/payment/success",
            "cancelUrl": "https://milkteainfo.com/payment/cancel",
        }

        # Tạo chữ ký
        sign_data = {
            "amount": amount,
            "cancelUrl": payload["cancelUrl"],
            "description": payload["description"],
            "orderCode": order_code,
            "returnUrl": payload["returnUrl"],
        }
        payload["signature"] = self._sign(sign_data)

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{self.BASE_URL}/v2/payment-requests",
                    json=payload,
                    headers={
                        "x-client-id": self.client_id,
                        "x-api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    timeout=15,
                )
                data = resp.json()
                if data.get("code") == "00":
                    return {
                        "success": True,
                        "order_number": order_number,
                        "amount": amount,
                        "payment_link": data["data"]["checkoutUrl"],
                        "payment_id": str(data["data"]["paymentLinkId"]),
                        "is_mock": False,
                    }
                else:
                    logger.error(f"PayOS error: {data}")
                    return {"success": False, "message": data.get("desc", "Lỗi PayOS")}
            except Exception as e:
                logger.error(f"PayOS request failed: {e}")
                return {"success": False, "message": str(e)}

    async def verify_webhook(self, data: dict, signature: str) -> bool:
        """Xác thực webhook từ PayOS."""
        sign_data = {k: v for k, v in data.items() if k != "signature"}
        expected = self._sign(sign_data)
        return hmac.compare_digest(expected, signature)


# ──────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────

def get_payment_provider():
    if settings.use_mock_payment:
        logger.info("Dùng MockPayment (không có PayOS credentials)")
        return MockPayment()
    else:
        logger.info("Dùng PayOS thực")
        return PayOSPayment()


payment_provider = get_payment_provider()


async def create_order_payment(order_number: str, amount: int) -> dict:
    """Tạo link thanh toán cho đơn hàng."""
    description = f"MilkTea #{order_number}"
    return await payment_provider.create_payment_link(order_number, amount, description)


def format_order_summary(order: dict) -> str:
    """Tạo tóm tắt đơn hàng để gửi lên nhóm admin."""
    cart = order.get("cart", {})
    items = cart.get("items", [])
    di = order.get("delivery_info", {})
    status_emoji = {"pending": "⏳", "paid": "✅", "done": "🎉"}.get(order.get("status", "pending"), "❓")

    created_at = order.get("created_at", "")
    try:
        dt = datetime.fromisoformat(created_at)
        time_str = dt.strftime("%H:%M %d/%m/%Y")
    except Exception:
        time_str = created_at

    lines = [
        f"📋 ĐƠN HÀNG #{order['order_number']} {status_emoji}",
        f"👤 Khách: {di.get('name', 'N/A')} | {di.get('phone', 'N/A')}",
        f"📍 Giao đến: {di.get('address', 'N/A')}",
        "─────────────────────────",
    ]

    for item in items:
        topping_str = ""
        toppings = item.get("toppings", [])
        if toppings:
            topping_str = "\n   ➕ " + ", ".join(t["name"] for t in toppings)

        lines.append(
            f"🧋 {item['item_name']} size {item['size']} × {item['quantity']}"
            f" = {item['subtotal']:,}đ{topping_str}"
        )

    lines.append("─────────────────────────")
    lines.append(f"💰 Tổng: {order['total_amount']:,}đ")
    lines.append(f"⏰ {time_str}")

    return "\n".join(lines)
