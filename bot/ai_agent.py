import json
import logging
from typing import Optional

from google import genai
from google.genai import types

from config import settings
from .database import Database
from .order_manager import OrderManager, load_menu

logger = logging.getLogger(__name__)

# Load menu một lần khi khởi động
MENU = load_menu()

SYSTEM_PROMPT = """Bạn là Milu 🧋 — nhân viên tư vấn nhiệt tình của quán Milkteainfo. Bạn thân thiện, vui vẻ, dùng emoji phù hợp để tạo không khí vui vẻ.

Nhiệm vụ của bạn:
1. Chào đón khách, giới thiệu menu hấp dẫn
2. Tư vấn món phù hợp khẩu vị
3. Nhận đặt món, gợi ý topping phù hợp
4. Thu thập thông tin giao hàng (tên, SĐT, địa chỉ) trước khi xác nhận
5. Xác nhận đơn và tạo link thanh toán

Quy tắc quan trọng:
- Luôn trả lời bằng tiếng Việt
- Khi thêm món vào giỏ, BẮT BUỘC gọi hàm add_to_order
- Khi khách hỏi giỏ hàng, gọi view_cart trước rồi mới trả lời
- Trước khi confirm_order, hỏi và lưu đầy đủ: tên, SĐT, địa chỉ giao hàng
- Gợi ý thêm topping khi khách đặt trà sữa hoặc đá xay
- Không bịa ra món không có trong menu
- Nếu khách muốn huỷ, gọi clear_cart
- Luôn xác nhận lại đơn (dùng view_cart + calculate_total) trước khi confirm_order
- Size M/L: M nhỏ hơn, L lớn hơn và đắt hơn 5-10k

Tính cách: Thân thiện như nhân viên quán thực thụ, không quá formal, đôi khi dùng các từ vui như "oki nha", "dạ bạn ơi", "chờ Milu check nha"."""


# ──────────────────────────────────────────────────────
# Function declarations cho Gemini (google-genai SDK mới)
# ──────────────────────────────────────────────────────

TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="get_menu",
                description="Lấy danh sách món trong menu. Gọi khi khách hỏi về menu hoặc muốn xem có gì.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "category": types.Schema(
                            type=types.Type.STRING,
                            description="Lọc theo danh mục. Bỏ trống để lấy tất cả.",
                            enum=["Trà Sữa", "Trà Trái Cây", "Cà Phê", "Đá Xay", "Topping"],
                        )
                    },
                ),
            ),
            types.FunctionDeclaration(
                name="add_to_order",
                description="Thêm một món vào giỏ hàng của khách.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "item_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID món trong menu, ví dụ: TS01, CF02, DX03",
                        ),
                        "size": types.Schema(
                            type=types.Type.STRING,
                            description="Size: M hoặc L",
                            enum=["M", "L"],
                        ),
                        "quantity": types.Schema(
                            type=types.Type.INTEGER,
                            description="Số lượng (tối thiểu 1)",
                        ),
                        "topping_ids": types.Schema(
                            type=types.Type.ARRAY,
                            description="Danh sách ID topping, ví dụ: ['TOP01', 'TOP06']",
                            items=types.Schema(type=types.Type.STRING),
                        ),
                    },
                    required=["item_id", "size", "quantity"],
                ),
            ),
            types.FunctionDeclaration(
                name="view_cart",
                description="Xem giỏ hàng hiện tại với tất cả món đã thêm và tổng tiền.",
                parameters=types.Schema(type=types.Type.OBJECT, properties={}),
            ),
            types.FunctionDeclaration(
                name="update_cart_item",
                description="Sửa số lượng hoặc size của một món trong giỏ.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "cart_item_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID của item trong giỏ (lấy từ view_cart)",
                        ),
                        "quantity": types.Schema(
                            type=types.Type.INTEGER,
                            description="Số lượng mới. Đặt 0 để xoá món.",
                        ),
                        "size": types.Schema(
                            type=types.Type.STRING,
                            description="Size mới: M hoặc L",
                            enum=["M", "L"],
                        ),
                    },
                    required=["cart_item_id"],
                ),
            ),
            types.FunctionDeclaration(
                name="remove_from_cart",
                description="Xoá một món khỏi giỏ hàng.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "cart_item_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID của item trong giỏ (lấy từ view_cart)",
                        )
                    },
                    required=["cart_item_id"],
                ),
            ),
            types.FunctionDeclaration(
                name="clear_cart",
                description="Xoá toàn bộ giỏ hàng khi khách muốn huỷ đơn.",
                parameters=types.Schema(type=types.Type.OBJECT, properties={}),
            ),
            types.FunctionDeclaration(
                name="calculate_total",
                description="Tính tổng tiền của đơn hàng hiện tại.",
                parameters=types.Schema(type=types.Type.OBJECT, properties={}),
            ),
            types.FunctionDeclaration(
                name="set_delivery_info",
                description="Lưu thông tin giao hàng của khách.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "name": types.Schema(type=types.Type.STRING, description="Tên người nhận"),
                        "phone": types.Schema(type=types.Type.STRING, description="Số điện thoại"),
                        "address": types.Schema(
                            type=types.Type.STRING, description="Địa chỉ giao hàng đầy đủ"
                        ),
                    },
                    required=["name", "phone", "address"],
                ),
            ),
            types.FunctionDeclaration(
                name="confirm_order",
                description="Xác nhận đặt hàng và tạo link thanh toán. Chỉ gọi khi khách đồng ý và đủ thông tin giao hàng.",
                parameters=types.Schema(type=types.Type.OBJECT, properties={}),
            ),
        ]
    )
]


# ──────────────────────────────────────────────────────
# Thực thi function calls
# ──────────────────────────────────────────────────────

def execute_tool(name: str, args: dict, order_mgr: OrderManager) -> dict:
    if name == "get_menu":
        items = order_mgr.get_menu(args.get("category"))
        return {"items": items, "count": len(items)}

    elif name == "add_to_order":
        return order_mgr.add_item(
            item_id=args["item_id"],
            size=args["size"],
            quantity=int(args.get("quantity", 1)),
            topping_ids=list(args.get("topping_ids", [])),
        )

    elif name == "view_cart":
        return order_mgr.view_cart()

    elif name == "update_cart_item":
        return order_mgr.update_item(
            cart_item_id=args["cart_item_id"],
            quantity=args.get("quantity"),
            size=args.get("size"),
        )

    elif name == "remove_from_cart":
        return order_mgr.remove_item(args["cart_item_id"])

    elif name == "clear_cart":
        return order_mgr.clear_cart()

    elif name == "calculate_total":
        return order_mgr.calculate_total()

    elif name == "set_delivery_info":
        return order_mgr.set_delivery_info(
            name=args["name"], phone=args["phone"], address=args["address"]
        )

    elif name == "confirm_order":
        ready, msg = order_mgr.is_ready_to_order()
        if not ready:
            return {"ready": False, "message": msg}
        total = order_mgr.calculate_total()
        return {
            "ready": True,
            "cart": order_mgr.cart,
            "delivery_info": order_mgr.delivery_info,
            "total": total["total"],
            "action": "CONFIRM_ORDER",
        }

    return {"error": f"Unknown function: {name}"}


# ──────────────────────────────────────────────────────
# Main AI processing với Gemini (google-genai SDK)
# ──────────────────────────────────────────────────────

async def process_message(
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
    message: str,
    db: Database,
) -> tuple[str, Optional[dict]]:
    """
    Xử lý tin nhắn qua Gemini 2.0 Flash.
    Returns: (response_text, confirm_order_data | None)
    """
    if not settings.has_gemini:
        return (
            "⚠️ Bot chưa được cấu hình Gemini API Key.\n"
            "Admin cần điền GEMINI_API_KEY vào file .env",
            None,
        )

    # Khởi tạo Gemini client
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    # Load session từ DB
    session = await db.get_session(user_id)
    stored_history = json.loads(session.get("conversation_history", "[]"))
    cart = json.loads(session.get("cart", '{"items": []}'))
    delivery_info = json.loads(session.get("delivery_info", "{}"))

    order_mgr = OrderManager(cart, delivery_info, MENU)

    # Build Gemini contents (history + tin nhắn mới)
    # Format: list of Content objects với role 'user' hoặc 'model'
    contents = []
    for turn in stored_history:
        contents.append(
            types.Content(
                role=turn["role"],
                parts=[types.Part(text=turn["content"])],
            )
        )
    # Thêm tin nhắn mới nhất
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part(text=message)],
        )
    )

    confirm_data = None
    reply = None

    try:
        # Function calling loop
        max_iterations = 10
        for iteration in range(max_iterations):
            response = await client.aio.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    tools=TOOLS,
                    temperature=0.7,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True  # Xử lý function calling thủ công
                    ),
                ),
            )

            candidate = response.candidates[0]
            parts = candidate.content.parts

            # Kiểm tra có function call không
            func_calls = [p for p in parts if p.function_call is not None]

            if not func_calls:
                # Không có function call → text response cuối cùng
                reply = "".join(
                    p.text for p in parts if p.text
                ).strip()
                # Lưu assistant turn vào contents
                contents.append(candidate.content)
                break

            # Thêm model's function call turn vào contents
            contents.append(candidate.content)

            # Thực thi tất cả function calls
            function_response_parts = []
            for part in func_calls:
                func_name = part.function_call.name
                func_args = dict(part.function_call.args) if part.function_call.args else {}

                logger.info(f"[Gemini Tool] {func_name}({json.dumps(func_args, ensure_ascii=False)[:100]})")
                result = execute_tool(func_name, func_args, order_mgr)

                # Bắt signal xác nhận đơn
                if func_name == "confirm_order" and result.get("action") == "CONFIRM_ORDER":
                    confirm_data = result

                function_response_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=func_name,
                            response={"result": json.dumps(result, ensure_ascii=False)},
                        )
                    )
                )

            # Thêm function responses vào contents (role=user)
            contents.append(
                types.Content(role="user", parts=function_response_parts)
            )

    except Exception as e:
        logger.error(f"Gemini API error: {e}", exc_info=True)
        return f"❌ Lỗi AI: {str(e)[:150]}\nVui lòng thử lại!", None

    # Cập nhật stored history (chỉ lưu text turns, không lưu function call trung gian)
    stored_history.append({"role": "user", "content": message})
    if reply:
        stored_history.append({"role": "model", "content": reply})

    # Giới hạn 30 turns để tránh tốn token
    stored_history = stored_history[-30:]

    # Lưu session
    await db.update_session(
        user_id=user_id,
        username=username,
        first_name=first_name,
        conversation_history=json.dumps(stored_history, ensure_ascii=False),
        cart=json.dumps(order_mgr.cart, ensure_ascii=False),
        delivery_info=json.dumps(order_mgr.delivery_info, ensure_ascii=False),
    )

    return reply or "Xin lỗi, có lỗi xảy ra. Vui lòng thử lại! 🙏", confirm_data
