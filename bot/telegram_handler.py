import logging
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

from config import settings
from .ai_agent import process_message, MENU
from .database import Database
from .order_manager import OrderManager
from .payment import (
    create_order_payment,
    format_order_summary,
    generate_order_number,
)

logger = logging.getLogger(__name__)

# Database instance (sẽ được init trong main)
db: Optional[Database] = None


def get_db() -> Database:
    return db


# ──────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────

def format_price(price: int) -> str:
    return f"{price:,}đ".replace(",", ".")


def build_menu_keyboard() -> InlineKeyboardMarkup:
    """Quick menu category buttons."""
    categories = ["Trà Sữa", "Trà Trái Cây", "Cà Phê", "Đá Xay", "Topping"]
    buttons = [[InlineKeyboardButton(f"🧋 {cat}", callback_data=f"menu_{cat}")] for cat in categories]
    return InlineKeyboardMarkup(buttons)


def format_menu_text(category: Optional[str] = None) -> str:
    """Format menu thành text đẹp."""
    order_mgr = OrderManager({}, {}, MENU)
    items = order_mgr.get_menu(category)
    if not items:
        return "Không có món nào trong danh mục này."

    emoji_map = {
        "Trà Sữa": "🧋",
        "Trà Trái Cây": "🍓",
        "Cà Phê": "☕",
        "Đá Xay": "🥤",
        "Topping": "✨",
    }

    if category:
        header = f"{emoji_map.get(category, '🍵')} *{category}*\n{'─' * 28}\n"
        lines = []
        for item in items:
            if category == "Topping":
                lines.append(
                    f"`{item['item_id']}` {item['name']}\n"
                    f"      💰 {format_price(item['price_m'])}\n"
                )
            else:
                lines.append(
                    f"`{item['item_id']}` *{item['name']}*\n"
                    f"      M: {format_price(item['price_m'])} | L: {format_price(item['price_l'])}\n"
                )
        return header + "\n".join(lines)
    else:
        # Hiển thị theo từng danh mục
        groups = {}
        for item in items:
            cat = item["category"]
            if cat not in groups:
                groups[cat] = []
            groups[cat].append(item)

        text = "🧋 *MENU MILKTEAINFO*\n\n"
        for cat, cat_items in groups.items():
            text += f"{emoji_map.get(cat, '🍵')} *{cat}*\n"
            for item in cat_items[:3]:  # Chỉ hiện 3 món đầu mỗi loại
                if cat == "Topping":
                    text += f"  • {item['name']} — {format_price(item['price_m'])}\n"
                else:
                    text += f"  • {item['name']} — M:{format_price(item['price_m'])}/L:{format_price(item['price_l'])}\n"
            if len(cat_items) > 3:
                text += f"  _...và {len(cat_items) - 3} món khác_\n"
            text += "\n"
        return text


def format_cart_text(session: dict) -> str:
    """Format giỏ hàng thành text."""
    import json
    cart = json.loads(session.get("cart", '{"items": []}'))
    di = json.loads(session.get("delivery_info", "{}"))

    items = cart.get("items", [])
    if not items:
        return "🛒 Giỏ hàng của bạn đang trống!\nHãy nhắn tin để đặt món nhé 😊"

    total = sum(i["subtotal"] for i in items)
    lines = ["🛒 *GIỎ HÀNG CỦA BẠN*\n"]
    for item in items:
        topping_str = ""
        if item.get("toppings"):
            topping_str = "\n  ➕ " + ", ".join(t["name"] for t in item["toppings"])
        lines.append(
            f"• *{item['item_name']}* size {item['size']} × {item['quantity']}"
            f" = {format_price(item['subtotal'])}{topping_str}"
        )
    lines.append(f"\n💰 *Tổng: {format_price(total)}*")

    if di:
        lines.append(
            f"\n📦 *Giao đến:*\n"
            f"  👤 {di.get('name', '')} — {di.get('phone', '')}\n"
            f"  📍 {di.get('address', '')}"
        )
    else:
        lines.append("\n⚠️ _Chưa có thông tin giao hàng_")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────
# Command Handlers
# ──────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.first_name or "bạn"
    text = (
        f"Xin chào *{name}* 👋🧋\n\n"
        f"Milu đây — nhân viên tư vấn của *Milkteainfo*!\n\n"
        f"Quán mình có:\n"
        f"🧋 Trà sữa các loại\n"
        f"🍓 Trà trái cây tươi\n"
        f"☕ Cà phê cao cấp\n"
        f"🥤 Đá xay mát lạnh\n"
        f"✨ Topping đa dạng\n\n"
        f"Bạn muốn uống gì hôm nay? Cứ nhắn tin thoải mái nha! 😊"
    )
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_menu_keyboard(),
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = format_menu_text()
    keyboard = build_menu_keyboard()
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


async def cmd_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = await get_db().get_session(user_id)
    text = format_cart_text(session)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Xác nhận đặt hàng", callback_data="action_checkout"),
            InlineKeyboardButton("🗑 Xoá giỏ", callback_data="action_clear"),
        ]
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await get_db().clear_session_cart(user_id)
    await update.message.reply_text(
        "✅ Đã huỷ đơn hàng của bạn. Giỏ hàng đã được xoá!\nNhắn tin để đặt lại bất cứ lúc nào 😊"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Hướng dẫn sử dụng bot*\n\n"
        "💬 *Đặt hàng:* Chỉ cần nhắn tin tự nhiên!\n"
        "Ví dụ: _'cho mình 2 trà sữa trân châu M'_\n\n"
        "*Các lệnh:*\n"
        "/start — Bắt đầu\n"
        "/menu — Xem menu\n"
        "/cart — Xem giỏ hàng\n"
        "/cancel — Huỷ đơn\n"
        "/help — Hướng dẫn\n\n"
        "🔑 *Admin:*\n"
        "/paid \\[mã đơn\\] — Xác nhận đã thanh toán\n"
        "/done \\[mã đơn\\] — Đánh dấu đã giao\n"
        "/orders — Xem danh sách đơn hàng"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────────────
# Admin Commands
# ──────────────────────────────────────────────────────

async def cmd_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /paid [order_number] — Xác nhận thanh toán."""
    if not context.args:
        await update.message.reply_text("Cú pháp: /paid [mã đơn]\nVí dụ: /paid 04191234")
        return
    order_number = context.args[0].upper()
    order = await get_db().mark_order_paid(order_number)
    if not order:
        await update.message.reply_text(f"❌ Không tìm thấy đơn hàng #{order_number}")
        return

    summary = format_order_summary(order)
    await update.message.reply_text(f"✅ Đã xác nhận thanh toán!\n\n{summary}")

    # Thông báo cho khách
    try:
        await context.bot.send_message(
            chat_id=order["user_id"],
            text=(
                f"🎉 Thanh toán thành công!\n\n"
                f"Đơn #{order_number} của bạn đã được xác nhận.\n"
                f"Milkteainfo đang chuẩn bị đồ cho bạn nhé! 🧋\n"
                f"Dự kiến giao hàng trong 30-45 phút."
            ),
        )
    except Exception as e:
        logger.error(f"Cannot notify user: {e}")


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /done [order_number] — Đánh dấu đã giao."""
    if not context.args:
        await update.message.reply_text("Cú pháp: /done [mã đơn]")
        return
    order_number = context.args[0].upper()
    order = await get_db().mark_order_done(order_number)
    if not order:
        await update.message.reply_text(f"❌ Không tìm thấy đơn #{order_number}")
        return

    await update.message.reply_text(f"🎉 Đơn #{order_number} đã giao thành công!")

    try:
        await context.bot.send_message(
            chat_id=order["user_id"],
            text=(
                f"🎉 Đơn hàng #{order_number} đã được giao!\n\n"
                f"Cảm ơn bạn đã tin tưởng Milkteainfo 🧋❤️\n"
                f"Hẹn gặp lại lần sau nhé!"
            ),
        )
    except Exception as e:
        logger.error(f"Cannot notify user: {e}")


async def cmd_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: Xem danh sách đơn hàng gần đây."""
    orders = await get_db().get_all_orders(limit=10)
    if not orders:
        await update.message.reply_text("Chưa có đơn hàng nào.")
        return

    status_emoji = {"pending": "⏳", "paid": "✅", "done": "🎉"}
    lines = ["📋 *Đơn hàng gần đây:*\n"]
    for o in orders:
        di = o.get("delivery_info", {})
        lines.append(
            f"{status_emoji.get(o['status'], '❓')} `#{o['order_number']}`"
            f" — {di.get('name', 'N/A')}"
            f" — {format_price(o['total_amount'])}"
            f" ({o['status']})"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────────────
# Message Handler — AI Agent
# ──────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý tất cả tin nhắn thường qua AI agent."""
    user = update.effective_user
    message_text = update.message.text or ""

    if not message_text.strip():
        return

    # Hiển thị "đang nhập..."
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing",
    )

    try:
        reply, confirm_data = await process_message(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            message=message_text,
            db=get_db(),
        )
    except Exception as e:
        logger.error(f"process_message error: {e}", exc_info=True)
        await update.message.reply_text("❌ Lỗi xử lý tin nhắn. Vui lòng thử lại!")
        return

    # Gửi reply từ AI — KHÔNG dùng parse_mode để tránh lỗi Markdown
    try:
        await update.message.reply_text(reply)
    except Exception as e:
        logger.error(f"send reply error: {e}")
        # Fallback: gửi plain text
        safe_reply = reply.replace("*", "").replace("_", "").replace("`", "")
        await update.message.reply_text(safe_reply)

    # Nếu AI muốn xác nhận đơn → xử lý thanh toán
    if confirm_data and confirm_data.get("ready"):
        await process_checkout(update, context, user, confirm_data)


async def process_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE, user, confirm_data: dict):
    """Tạo đơn hàng và link thanh toán."""
    order_number = generate_order_number()
    cart = confirm_data["cart"]
    delivery_info = confirm_data["delivery_info"]
    total = confirm_data["total"]

    # Lưu đơn hàng vào DB
    await get_db().create_order(
        order_number=order_number,
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        total_amount=total,
        cart=cart,
        delivery_info=delivery_info,
    )

    # Tạo link thanh toán
    payment_result = await create_order_payment(order_number, total)

    if payment_result.get("success"):
        payment_link = payment_result["payment_link"]
        payment_id = payment_result.get("payment_id", "")
        is_mock = payment_result.get("is_mock", True)

        # Cập nhật payment info vào order
        await get_db().update_order_payment(order_number, payment_id, payment_link)

        mock_note = ""
        if is_mock:
            mock_note = (
                "\n\n⚠️ _Đây là link demo (Mock Payment)_\n"
                f"Admin xác nhận bằng lệnh: `/paid {order_number}`"
            )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Thanh toán ngay", url=payment_link)]
        ])

        await update.message.reply_text(
            f"🎉 *Đặt hàng thành công!*\n\n"
            f"📋 Mã đơn: `#{order_number}`\n"
            f"💰 Tổng tiền: *{format_price(total)}*\n\n"
            f"Nhấn nút bên dưới để thanh toán nhé! ⬇️{mock_note}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )

        # Xoá giỏ hàng sau khi đặt thành công
        await get_db().clear_session_cart(user.id)

        # Gửi thông báo lên nhóm admin
        if settings.ADMIN_TELEGRAM_CHAT_ID:
            try:
                order = await get_db().get_order(order_number)
                if order:
                    summary = format_order_summary(order)
                    await context.bot.send_message(
                        chat_id=settings.ADMIN_TELEGRAM_CHAT_ID,
                        text=f"🔔 *ĐƠN MỚI!*\n\n{summary}",
                        parse_mode=ParseMode.MARKDOWN,
                    )
            except Exception as e:
                logger.error(f"Cannot notify admin: {e}")
    else:
        await update.message.reply_text(
            f"❌ Lỗi tạo link thanh toán: {payment_result.get('message', 'Unknown error')}\n"
            f"Vui lòng thử lại hoặc liên hệ admin!"
        )


# ──────────────────────────────────────────────────────
# Callback Query Handler (Inline Keyboard)
# ──────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("menu_"):
        category = data.replace("menu_", "")
        text = format_menu_text(category)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Xem tất cả", callback_data="menu_all")]
        ])
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

    elif data == "menu_all":
        text = format_menu_text()
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=build_menu_keyboard())

    elif data == "action_clear":
        user_id = query.from_user.id
        await get_db().clear_session_cart(user_id)
        await query.edit_message_text("🗑 Giỏ hàng đã được xoá! Nhắn tin để đặt lại nhé 😊")

    elif data == "action_checkout":
        # Trigger checkout flow qua AI
        await query.edit_message_text(
            "✅ Vui lòng nhắn 'xác nhận đặt hàng' để Milu xử lý cho bạn nhé! 😊"
        )


# ──────────────────────────────────────────────────────
# App Builder
# ──────────────────────────────────────────────────────

def create_application(database: Database) -> Application:
    """Tạo Telegram Application với tất cả handlers."""
    global db
    db = database

    app = Application.builder().token(settings.BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("cart", cmd_cart))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("help", cmd_help))

    # Admin commands
    app.add_handler(CommandHandler("paid", cmd_paid))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CommandHandler("orders", cmd_orders))

    # Inline keyboard callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Text messages → AI agent
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
