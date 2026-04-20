"""
Telegram Handler - Hybrid approach:
  - Button-based inline menu cho toàn bộ ordering flow (NO AI required)
  - AI (Gemini) chỉ dùng cho free-text chat / tư vấn món (optional, graceful fallback)
  - State machine cho checkout: name → phone → address → confirm
"""

import json
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
from .database import Database
from .order_manager import OrderManager, load_menu
from .payment import create_order_payment, format_order_summary, generate_order_number

logger = logging.getLogger(__name__)

MENU = load_menu()
db: Optional[Database] = None


def get_db() -> Database:
    return db


# ──────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────

def format_price(price: int) -> str:
    return f"{price:,}đ".replace(",", ".")


CATEGORY_EMOJI = {
    "Trà Sữa": "🧋",
    "Trà Trái Cây": "🍓",
    "Cà Phê": "☕",
    "Đá Xay": "🥤",
    "Topping": "✨",
}

# Mapping callback_data cho category (tránh ký tự dài)
CAT_CB = {
    "ts": "Trà Sữa",
    "ttc": "Trà Trái Cây",
    "cf": "Cà Phê",
    "dx": "Đá Xay",
    "top": "Topping",
}
CAT_CB_REV = {v: k for k, v in CAT_CB.items()}


def get_menu_items(category: Optional[str] = None):
    if category:
        return [i for i in MENU if i["category"] == category]
    return MENU


def get_item_by_id(item_id: str):
    for item in MENU:
        if item["item_id"] == item_id:
            return item
    return None


def get_toppings():
    return [i for i in MENU if i["category"] == "Topping"]


# ──────────────────────────────────────────────────────
# Keyboard Builders
# ──────────────────────────────────────────────────────

def kb_main_menu() -> InlineKeyboardMarkup:
    """Menu chính — chọn danh mục."""
    buttons = []
    for cb, cat in CAT_CB.items():
        if cat == "Topping":
            continue
        emoji = CATEGORY_EMOJI[cat]
        buttons.append([InlineKeyboardButton(f"{emoji} {cat}", callback_data=f"cat_{cb}")])
    buttons.append([InlineKeyboardButton("✨ Topping", callback_data="cat_top")])
    buttons.append([InlineKeyboardButton("🛒 Xem giỏ hàng", callback_data="view_cart")])
    return InlineKeyboardMarkup(buttons)


def kb_category_items(category: str) -> InlineKeyboardMarkup:
    """Danh sách món trong 1 danh mục — mỗi món 1 nút Chọn."""
    items = get_menu_items(category)
    buttons = []
    cb_cat = CAT_CB_REV.get(category, "ts")
    for item in items:
        if category == "Topping":
            label = f"{item['name']} — {format_price(item['price_m'])}"
        else:
            label = f"{item['name']}  M:{format_price(item['price_m'])} / L:{format_price(item['price_l'])}"
        # Max 64 bytes per callback_data
        buttons.append([InlineKeyboardButton(label, callback_data=f"itm_{item['item_id']}")])
    buttons.append([InlineKeyboardButton("⬅️ Quay lại", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)


def kb_size(item_id: str) -> InlineKeyboardMarkup:
    item = get_item_by_id(item_id)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"M — {format_price(item['price_m'])}", callback_data="sz_M"),
            InlineKeyboardButton(f"L — {format_price(item['price_l'])}", callback_data="sz_L"),
        ],
        [InlineKeyboardButton("⬅️ Quay lại", callback_data=f"cat_{CAT_CB_REV.get(item['category'], 'ts')}")],
    ])


def kb_quantity() -> InlineKeyboardMarkup:
    row1 = [InlineKeyboardButton(str(n), callback_data=f"qty_{n}") for n in range(1, 6)]
    row2 = [InlineKeyboardButton(str(n), callback_data=f"qty_{n}") for n in range(6, 11)]
    return InlineKeyboardMarkup([row1, row2])


def kb_toppings(selected: list[str]) -> InlineKeyboardMarkup:
    """Topping selector — toggle + Done."""
    toppings = get_toppings()
    buttons = []
    for t in toppings:
        checked = t["item_id"] in selected
        label = f"{'✅' if checked else '⬜'} {t['name']} +{format_price(t['price_m'])}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"top_{t['item_id']}")])
    done_label = f"✅ Thêm vào giỏ ({len(selected)} topping)" if selected else "➕ Thêm vào giỏ (không topping)"
    buttons.append([InlineKeyboardButton(done_label, callback_data="top_done")])
    buttons.append([InlineKeyboardButton("⬅️ Quay lại (đổi size)", callback_data="back_to_size")])
    return InlineKeyboardMarkup(buttons)


def kb_cart_actions(has_items: bool) -> InlineKeyboardMarkup:
    if has_items:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Đặt hàng ngay", callback_data="checkout_start")],
            [
                InlineKeyboardButton("🛍 Tiếp tục chọn", callback_data="main_menu"),
                InlineKeyboardButton("🗑 Xoá giỏ", callback_data="clear_cart"),
            ],
        ])
    else:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🛍 Xem menu", callback_data="main_menu")],
        ])


def kb_confirm_order(order_number: str, payment_link: str, is_mock: bool) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton("💳 Thanh toán ngay", url=payment_link)]]
    if is_mock:
        buttons.append([InlineKeyboardButton("📋 Xem đơn hàng", callback_data=f"order_{order_number}")])
    return InlineKeyboardMarkup(buttons)


# ──────────────────────────────────────────────────────
# Cart display
# ──────────────────────────────────────────────────────

async def get_cart_display(user_id: int) -> tuple[str, bool]:
    """Trả về (text, has_items)."""
    session = await get_db().get_session(user_id)
    cart = json.loads(session.get("cart", '{"items": []}'))
    items = cart.get("items", [])

    if not items:
        return "🛒 Giỏ hàng đang trống!\nChọn món từ menu nhé 😊", False

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
    return "\n".join(lines), True


# ──────────────────────────────────────────────────────
# Command Handlers
# ──────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # Reset checkout state
    context.user_data.pop("checkout_step", None)

    name = user.first_name or "bạn"
    text = (
        f"Xin chào *{name}* 👋🧋\n\n"
        f"Milu đây — nhân viên tư vấn của *Milkteainfo*!\n\n"
        f"Bạn muốn uống gì hôm nay? Chọn danh mục bên dưới nha:"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main_menu())


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧋 *MENU MILKTEAINFO*\nChọn danh mục:", parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main_menu())


async def cmd_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text, has_items = await get_cart_display(user_id)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_cart_actions(has_items))


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.clear()
    await get_db().clear_session_cart(user_id)
    await update.message.reply_text("✅ Đã huỷ đơn! Giỏ hàng đã xoá.\nNhắn /start để bắt đầu lại nhé 😊")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Hướng dẫn đặt hàng*\n\n"
        "1️⃣ Gõ /menu → chọn danh mục\n"
        "2️⃣ Chọn món → chọn size → chọn số lượng\n"
        "3️⃣ Chọn topping (hoặc bỏ qua)\n"
        "4️⃣ Kiểm tra giỏ → đặt hàng\n"
        "5️⃣ Điền tên, SĐT, địa chỉ\n"
        "6️⃣ Xác nhận & thanh toán!\n\n"
        "*Lệnh:*\n"
        "/start — Bắt đầu\n"
        "/menu — Xem menu\n"
        "/cart — Giỏ hàng\n"
        "/cancel — Huỷ đơn\n\n"
        "Hoặc cứ nhắn tự nhiên — Milu sẽ tư vấn cho bạn! 😊"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────────────
# Admin Commands
# ──────────────────────────────────────────────────────

async def cmd_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Cú pháp: /paid [mã đơn]")
        return
    order_number = context.args[0].upper()
    order = await get_db().mark_order_paid(order_number)
    if not order:
        await update.message.reply_text(f"❌ Không tìm thấy đơn #{order_number}")
        return
    await update.message.reply_text(f"✅ Đã xác nhận thanh toán đơn #{order_number}!")
    try:
        await context.bot.send_message(
            chat_id=order["user_id"],
            text=f"🎉 Thanh toán thành công!\nĐơn #{order_number} đã xác nhận.\nMilk-Tea đang pha trà cho bạn 🧋",
        )
    except Exception as e:
        logger.error(f"Cannot notify user: {e}")


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Cú pháp: /done [mã đơn]")
        return
    order_number = context.args[0].upper()
    order = await get_db().mark_order_done(order_number)
    if not order:
        await update.message.reply_text(f"❌ Không tìm thấy đơn #{order_number}")
        return
    await update.message.reply_text(f"🎉 Đơn #{order_number} đã giao!")
    try:
        await context.bot.send_message(
            chat_id=order["user_id"],
            text=f"🎉 Đơn #{order_number} đã giao thành công!\nCảm ơn bạn đã tin tưởng Milkteainfo 🧋❤️",
        )
    except Exception as e:
        logger.error(f"Cannot notify user: {e}")


async def cmd_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
# Callback Query Handler — Button-based ordering flow
# ──────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    # ── Main menu ──
    if data == "main_menu":
        await query.edit_message_text(
            "🧋 *MENU MILKTEAINFO*\nChọn danh mục:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main_menu(),
        )

    # ── Category ──
    elif data.startswith("cat_"):
        cb = data[4:]
        category = CAT_CB.get(cb)
        if not category:
            return
        emoji = CATEGORY_EMOJI.get(category, "🍵")
        items = get_menu_items(category)
        text = f"{emoji} *{category}*\nChọn món bạn muốn:"
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_category_items(category))

    # ── Item selected → choose size ──
    elif data.startswith("itm_"):
        item_id = data[4:]
        item = get_item_by_id(item_id)
        if not item:
            return

        # Topping không có size → thêm trực tiếp với qty=1
        if item["category"] == "Topping":
            context.user_data["pending_item"] = item_id
            context.user_data["pending_size"] = "M"
            context.user_data["pending_toppings"] = []
            await query.edit_message_text(
                f"✨ *{item['name']}*\nGiá: {format_price(item['price_m'])}\n\nChọn số lượng:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_quantity(),
            )
            return

        context.user_data["pending_item"] = item_id
        context.user_data["pending_toppings"] = []
        await query.edit_message_text(
            f"🧋 *{item['name']}*\nM: {format_price(item['price_m'])} | L: {format_price(item['price_l'])}\n\nChọn size:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_size(item_id),
        )

    # ── Size selected → choose quantity ──
    elif data.startswith("sz_"):
        size = data[3:]
        context.user_data["pending_size"] = size
        item_id = context.user_data.get("pending_item")
        item = get_item_by_id(item_id) if item_id else None
        name = item["name"] if item else "Món"
        price = item[f"price_{size.lower()}"] if item else 0
        await query.edit_message_text(
            f"*{name}* size {size} — {format_price(price)}\n\nChọn số lượng:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_quantity(),
        )

    # ── Quantity selected → choose toppings ──
    elif data.startswith("qty_"):
        qty = int(data[4:])
        context.user_data["pending_quantity"] = qty
        item_id = context.user_data.get("pending_item")
        item = get_item_by_id(item_id) if item_id else None

        # Topping không có topping → thêm ngay
        if item and item["category"] == "Topping":
            await _add_pending_to_cart(query, context, user_id)
            return

        selected = context.user_data.get("pending_toppings", [])
        name = item["name"] if item else "Món"
        size = context.user_data.get("pending_size", "M")
        await query.edit_message_text(
            f"*{name}* size {size} × {qty}\n\nChọn topping (tuỳ chọn):",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_toppings(selected),
        )

    # ── Toggle topping ──
    elif data.startswith("top_") and data != "top_done":
        top_id = data[4:]
        selected = context.user_data.get("pending_toppings", [])
        if top_id in selected:
            selected.remove(top_id)
        else:
            selected.append(top_id)
        context.user_data["pending_toppings"] = selected

        item_id = context.user_data.get("pending_item")
        item = get_item_by_id(item_id) if item_id else None
        size = context.user_data.get("pending_size", "M")
        qty = context.user_data.get("pending_quantity", 1)
        name = item["name"] if item else "Món"
        await query.edit_message_reply_markup(reply_markup=kb_toppings(selected))

    # ── Done with toppings → add to cart ──
    elif data == "top_done":
        await _add_pending_to_cart(query, context, user_id)

    # ── Back to size selection ──
    elif data == "back_to_size":
        item_id = context.user_data.get("pending_item")
        if item_id:
            item = get_item_by_id(item_id)
            await query.edit_message_text(
                f"🧋 *{item['name']}*\nChọn size:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_size(item_id),
            )

    # ── View cart ──
    elif data == "view_cart":
        text, has_items = await get_cart_display(user_id)
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_cart_actions(has_items))

    # ── Clear cart ──
    elif data == "clear_cart":
        await get_db().clear_session_cart(user_id)
        context.user_data.clear()
        await query.edit_message_text(
            "🗑 Giỏ hàng đã xoá!\nNhấn nút bên dưới để chọn lại nhé:",
            reply_markup=kb_cart_actions(False),
        )

    # ── Start checkout → ask for name ──
    elif data == "checkout_start":
        text, has_items = await get_cart_display(user_id)
        if not has_items:
            await query.edit_message_text("🛒 Giỏ hàng đang trống!", reply_markup=kb_cart_actions(False))
            return

        context.user_data["checkout_step"] = "name"
        await query.edit_message_text(
            f"{text}\n\n📦 *Thông tin giao hàng*\n\nBước 1/3: Nhập *tên người nhận* 👇",
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── Confirm order (after delivery info filled) ──
    elif data == "confirm_pay":
        await _process_checkout(query, context, user_id)


async def _add_pending_to_cart(query, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Thêm món đang chọn vào giỏ DB."""
    item_id = context.user_data.get("pending_item")
    size = context.user_data.get("pending_size", "M")
    qty = context.user_data.get("pending_quantity", 1)
    toppings = context.user_data.get("pending_toppings", [])

    if not item_id:
        await query.edit_message_text("❌ Lỗi: không tìm thấy món đang chọn. Vui lòng thử lại!")
        return

    # Load session và thêm vào cart
    session = await get_db().get_session(user_id)
    cart = json.loads(session.get("cart", '{"items": []}'))
    delivery_info = json.loads(session.get("delivery_info", "{}"))
    order_mgr = OrderManager(cart, delivery_info, MENU)

    result = order_mgr.add_item(item_id=item_id, size=size, quantity=qty, topping_ids=toppings)

    if result.get("success"):
        # Lưu cart vào DB
        await get_db().update_session(
            user_id=user_id,
            cart=json.dumps(order_mgr.cart, ensure_ascii=False),
        )
        # Xoá pending state
        for key in ["pending_item", "pending_size", "pending_quantity", "pending_toppings"]:
            context.user_data.pop(key, None)

        item = get_item_by_id(item_id)
        total = order_mgr.calculate_total()
        await query.edit_message_text(
            f"✅ Đã thêm vào giỏ!\n\n"
            f"*{item['name']}* size {size} × {qty}\n"
            f"Topping: {', '.join(t for t in toppings) if toppings else 'Không'}\n\n"
            f"🛒 Tổng giỏ hàng: *{format_price(total['total'])}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Thêm món khác", callback_data="main_menu")],
                [InlineKeyboardButton("🛒 Xem giỏ & Đặt hàng", callback_data="view_cart")],
            ]),
        )
    else:
        await query.edit_message_text(f"❌ {result.get('message', 'Lỗi thêm món')}", reply_markup=kb_main_menu())


async def _process_checkout(query, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Tạo đơn hàng và link thanh toán."""
    from_user = query.from_user

    # Lấy delivery info từ context
    name = context.user_data.get("delivery_name", "Khách hàng")
    phone = context.user_data.get("delivery_phone", "")
    address = context.user_data.get("delivery_address", "")

    session = await get_db().get_session(user_id)
    cart = json.loads(session.get("cart", '{"items": []}'))
    delivery_info = {"name": name, "phone": phone, "address": address}
    order_mgr = OrderManager(cart, delivery_info, MENU)

    if not cart.get("items"):
        await query.message.reply_text("❌ Giỏ hàng trống!")
        return

    total = order_mgr.calculate_total()["total"]
    order_number = generate_order_number()

    await get_db().create_order(
        order_number=order_number,
        user_id=user_id,
        username=from_user.username,
        first_name=from_user.first_name,
        total_amount=total,
        cart=cart,
        delivery_info=delivery_info,
    )

    payment_result = await create_order_payment(order_number, total)

    if payment_result.get("success"):
        payment_link = payment_result["payment_link"]
        payment_id = payment_result.get("payment_id", "")
        is_mock = payment_result.get("is_mock", True)

        await get_db().update_order_payment(order_number, payment_id, payment_link)

        mock_note = ""
        if is_mock:
            mock_note = f"\n\n⚠️ _Mock Payment - Admin xác nhận: /paid {order_number}_"

        await query.message.reply_text(
            f"🎉 *ĐẶT HÀNG THÀNH CÔNG!*\n\n"
            f"📋 Mã đơn: `#{order_number}`\n"
            f"👤 {name} — {phone}\n"
            f"📍 {address}\n"
            f"💰 Tổng: *{format_price(total)}*{mock_note}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💳 Thanh toán ngay", url=payment_link)
            ]]),
        )

        await get_db().clear_session_cart(user_id)
        context.user_data.clear()

        if settings.ADMIN_TELEGRAM_CHAT_ID:
            try:
                order = await get_db().get_order(order_number)
                if order:
                    summary = format_order_summary(order)
                    await query.message.get_bot().send_message(
                        chat_id=settings.ADMIN_TELEGRAM_CHAT_ID,
                        text=f"🔔 *ĐƠN MỚI!*\n\n{summary}",
                        parse_mode=ParseMode.MARKDOWN,
                    )
            except Exception as e:
                logger.error(f"Admin notify error: {e}")
    else:
        await query.message.reply_text(
            f"❌ Lỗi tạo link thanh toán: {payment_result.get('message', 'Unknown')}"
        )


# ──────────────────────────────────────────────────────
# Message Handler — State machine + AI fallback
# ──────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text or ""
    if not text.strip():
        return

    step = context.user_data.get("checkout_step")

    # ── Checkout state machine ──
    if step == "name":
        context.user_data["delivery_name"] = text.strip()
        context.user_data["checkout_step"] = "phone"
        await update.message.reply_text(
            "✅ Đã lưu tên!\n\nBước 2/3: Nhập *số điện thoại* 👇",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    elif step == "phone":
        context.user_data["delivery_phone"] = text.strip()
        context.user_data["checkout_step"] = "address"
        await update.message.reply_text(
            "✅ Đã lưu SĐT!\n\nBước 3/3: Nhập *địa chỉ giao hàng* 👇",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    elif step == "address":
        context.user_data["delivery_address"] = text.strip()
        context.user_data["checkout_step"] = None

        # Show confirmation
        name = context.user_data.get("delivery_name", "")
        phone = context.user_data.get("delivery_phone", "")
        address = text.strip()

        cart_text, has_items = await get_cart_display(user.id)
        confirm_text = (
            f"{cart_text}\n\n"
            f"📦 *Thông tin giao hàng:*\n"
            f"👤 {name}\n"
            f"📞 {phone}\n"
            f"📍 {address}\n\n"
            f"Xác nhận đặt hàng chứ bạn? 😊"
        )
        await update.message.reply_text(
            confirm_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Xác nhận & Thanh toán", callback_data="confirm_pay")],
                [
                    InlineKeyboardButton("✏️ Sửa thông tin", callback_data="checkout_start"),
                    InlineKeyboardButton("🗑 Huỷ", callback_data="clear_cart"),
                ],
            ]),
        )
        return

    # ── Free-text: AI (optional) hoặc fallback ──
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    if settings.has_gemini:
        try:
            from .ai_agent import process_message as ai_process
            reply, confirm_data = await ai_process(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                message=text,
                db=get_db(),
            )
            await update.message.reply_text(reply)
            # Nếu AI confirm order (từ free-text)
            if confirm_data and confirm_data.get("ready"):
                await _process_checkout_from_ai(update, context, user, confirm_data)
        except Exception as e:
            logger.error(f"AI error: {e}")
            await _fallback_reply(update)
    else:
        await _fallback_reply(update)


async def _fallback_reply(update: Update):
    """Fallback khi không có AI."""
    await update.message.reply_text(
        "Dùng các nút bên dưới để đặt hàng nhé! 😊",
        reply_markup=kb_main_menu(),
    )


async def _process_checkout_from_ai(update: Update, context, user, confirm_data: dict):
    """Xử lý khi AI confirm order qua free-text."""
    order_number = generate_order_number()
    cart = confirm_data["cart"]
    delivery_info = confirm_data["delivery_info"]
    total = confirm_data["total"]

    await get_db().create_order(
        order_number=order_number,
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        total_amount=total,
        cart=cart,
        delivery_info=delivery_info,
    )

    payment_result = await create_order_payment(order_number, total)

    if payment_result.get("success"):
        payment_link = payment_result["payment_link"]
        payment_id = payment_result.get("payment_id", "")
        is_mock = payment_result.get("is_mock", True)
        await get_db().update_order_payment(order_number, payment_id, payment_link)

        mock_note = f"\n\n⚠️ Mock: /paid {order_number}" if is_mock else ""
        await update.message.reply_text(
            f"🎉 Đặt hàng thành công!\n📋 Mã đơn: #{order_number}\n💰 {format_price(total)}{mock_note}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💳 Thanh toán", url=payment_link)]]),
        )
        await get_db().clear_session_cart(user.id)


# ──────────────────────────────────────────────────────
# App Builder
# ──────────────────────────────────────────────────────

def create_application(database: Database) -> Application:
    global db
    db = database

    app = Application.builder().token(settings.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("cart", cmd_cart))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("paid", cmd_paid))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CommandHandler("orders", cmd_orders))

    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
