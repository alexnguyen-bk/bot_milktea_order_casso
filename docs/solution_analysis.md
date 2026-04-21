# TÀI LIỆU PHÂN TÍCH GIẢI PHÁP
## AI Chatbot Tự Động Đặt Hàng Trà Sữa — Milkteainfo Bot

---

**Ứng viên:** Nguyễn Trọng Thịnh  
**Vị trí:** Intern Software Engineer 2026  
**Công ty:** Casso Company Limited  
**Telegram Bot:** [@milkteainfo_bot](https://t.me/milkteainfo_bot)  
**GitHub:** [github.com/alexnguyen-bk/bot_milktea_order_casso](https://github.com/alexnguyen-bk/bot_milktea_order_casso)

---

## 1. BỐI CẢNH & VẤN ĐỀ

### 1.1 Bối cảnh

Quán trà sữa Milkteainfo phục vụ chủ yếu khách văn phòng trong khu vực lân cận. Lượng đơn đặt hàng online qua Telegram ngày càng tăng cao, dẫn đến tình trạng:

- **Phản hồi chậm:** Chủ quán không thể trả lời kịp thời tất cả tin nhắn
- **Sai thông tin đơn:** Ghi chép thủ công dễ nhầm lẫn tên món, size, topping
- **Mất khách:** Khách chờ lâu không được phản hồi, dẫn đến phàn nàn
- **Quản lý khó khăn:** Không có hệ thống theo dõi đơn hàng tập trung

### 1.2 Yêu cầu bài toán

Xây dựng một **bản sao AI của chủ quán** hoạt động trên Telegram, có khả năng:

| STT | Yêu cầu | Ưu tiên |
|-----|---------|---------|
| 1 | Giao tiếp tự nhiên với khách hàng | Cao |
| 2 | Hỗ trợ khách đặt món từ menu | Cao |
| 3 | Tính tiền tự động | Cao |
| 4 | Tổng hợp thông tin để làm món và giao hàng | Cao |
| 5 | Tích hợp thanh toán (PayOS) | Trung bình |
| 6 | Thông báo admin khi có đơn mới | Trung bình |

---

## 2. PHÂN TÍCH & LỰA CHỌN GIẢI PHÁP

### 2.1 Các phương án tiếp cận

**Phương án A — Chatbot dựa hoàn toàn vào AI (LLM-only)**

- Ưu điểm: Linh hoạt, tự nhiên
- Nhược điểm: Chi phí API cao, dễ bị lỗi quota, độ trễ cao, khó kiểm soát luồng đặt hàng

**Phương án B — Chatbot button-based thuần túy (không AI)**

- Ưu điểm: Ổn định, nhanh, không tốn API
- Nhược điểm: UX cứng nhắc, không đáp ứng yêu cầu "sử dụng LLM"

**Phương án C — Hybrid (được chọn) ✅**

- **Inline keyboard buttons** cho toàn bộ luồng đặt hàng (ổn định 100%)
- **AI Gemini** cho free-text chat, tư vấn món, xử lý câu hỏi tự nhiên
- Kết hợp ưu điểm của cả hai phương án

### 2.2 Lý do chọn Phương án Hybrid

1. **Tính ổn định:** Luồng đặt hàng chính không phụ thuộc vào AI → không bị lỗi khi quota hết
2. **UX tốt hơn:** Buttons cho phép khách chọn nhanh mà không cần gõ phím nhiều
3. **Tích hợp LLM thực chất:** AI được dùng để tư vấn, gợi ý, trả lời câu hỏi — đúng với tinh thần bài thi
4. **Dễ mở rộng:** Có thể thêm tính năng AI nâng cao (recommendation, upsell) sau này

---

## 3. KIẾN TRÚC HỆ THỐNG

### 3.1 Sơ đồ tổng quan

```
┌─────────────────────────────────────────────────────────────┐
│                        TELEGRAM                              │
│              Khách hàng ↔ @milkteainfo_bot                  │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP Long Polling
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   BOT APPLICATION (Python)                   │
│                                                             │
│  ┌─────────────────┐    ┌──────────────────────────────┐   │
│  │ Telegram Handler│    │         AI Agent              │   │
│  │  (Inline Menu   │    │  (Google Gemini 2.5 Flash)   │   │
│  │   + State FSM)  │    │   Function Calling Loop       │   │
│  └────────┬────────┘    └──────────────┬───────────────┘   │
│           │                            │                    │
│           ▼                            ▼                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Order Manager + Database (SQLite)       │   │
│  │         cart / orders / conversation_history         │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                             │                               │
│           ┌─────────────────▼───────────────────┐          │
│           │         FastAPI Admin API           │          │
│           │    GET /orders, POST /orders/...    │          │
│           └─────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────┘
             │                            │
             ▼                            ▼
    ┌─────────────────┐        ┌──────────────────────┐
    │   PayOS API     │        │   Admin Dashboard    │
    │  (QR Payment)   │        │  (dashboard.html)    │
    └─────────────────┘        └──────────────────────┘
```

### 3.2 Luồng đặt hàng (Button Flow)

```
/start
  └── Chọn danh mục (Trà Sữa / Trà Trái Cây / Cà Phê / Đá Xay / Topping)
        └── Chọn món (Inline Keyboard — từng món)
              └── Chọn size (M / L)
                    └── Chọn số lượng (1–10)
                          └── Chọn topping (toggle checkbox)
                                └── ✅ Thêm vào giỏ
                                      └── Xem giỏ hàng
                                            └── Đặt hàng
                                                  ├── Nhập tên [validate ≥ 2 ký tự]
                                                  ├── Nhập SĐT [validate 10 số VN]
                                                  ├── Nhập địa chỉ
                                                  └── Xác nhận → Tạo đơn + Link thanh toán
```

### 3.3 Luồng AI Chat (Free-text)

```
User nhắn tin tự nhiên
      │
      ▼
Kiểm tra checkout_step?
  ├── Có → State Machine xử lý (không gọi AI)
  └── Không → Gọi Gemini API
                    │
                    ▼
            Function Calling Loop:
            - get_menu()
            - add_to_order()
            - get_cart()
            - calculate_total()
            - save_delivery_info()
            - confirm_order()
                    │
                    ▼
            Trả lời dưới dạng "Milu" (nhân vật AI)
```

---

## 4. CÔNG NGHỆ SỬ DỤNG

| Thành phần | Công nghệ | Lý do chọn |
|------------|-----------|-----------|
| **Bot Framework** | python-telegram-bot 21.6 | Async, production-ready, hỗ trợ đầy đủ Telegram API |
| **AI / LLM** | Google Gemini 2.5 Flash | Free tier, function calling, tiếng Việt tốt |
| **Database** | SQLite + aiosqlite | Nhẹ, không cần server, phù hợp scale nhỏ |
| **Admin API** | FastAPI + uvicorn | Nhanh, async, tự tạo docs |
| **Payment** | PayOS | Đề xuất của đề bài, phổ biến ở VN |
| **Deploy** | Docker + Railway | CI/CD đơn giản, free tier |
| **Language** | Python 3.10+ | Ecosystem AI phong phú, async support |

### 4.1 Chi tiết Google Gemini Integration

```python
# Sử dụng SDK google-genai (mới nhất, thay thế google-generativeai đã deprecated)
from google import genai

client = genai.Client(api_key=GEMINI_API_KEY)

# Function Calling — AI tự quyết định gọi hàm nào
tools = [get_menu, add_to_order, get_cart, calculate_total, 
         save_delivery_info, confirm_order]

response = await client.aio.models.generate_content(
    model="gemini-2.5-flash",
    contents=conversation_history,
    config=GenerateContentConfig(tools=tools, system_instruction=SYSTEM_PROMPT)
)
```

**System Prompt** định nghĩa nhân vật "Milu" — nhân viên tư vấn thân thiện, hiểu menu và biết tư vấn đặt hàng phù hợp với khẩu vị và ngân sách khách hàng.

---

## 5. CÁC TÍNH NĂNG CHÍNH

### 5.1 Button-based Ordering (100% ổn định, không cần AI)

| Tính năng | Mô tả |
|-----------|-------|
| Inline Menu | 27 món chia 5 danh mục với giá và mã item |
| Size selection | M/L với giá hiển thị trực tiếp |
| Quantity | 1–10 items/lần |
| Topping | Toggle checkbox, hiện tổng số đã chọn |
| Giỏ hàng | Xem, xoá, cập nhật realtime |
| Checkout | State machine: tên → SĐT → địa chỉ → xác nhận |

### 5.2 Validation dữ liệu

```python
# Validate SĐT Việt Nam
phone = re.sub(r'[\s\-\.\(\)]', '', text.strip())
if phone.startswith('+84'):
    phone = '0' + phone[3:]  # Chuẩn hóa về dạng 0xxx
if not re.fullmatch(r'(03|05|07|08|09)\d{8}', phone):
    # Báo lỗi và yêu cầu nhập lại
```

Hỗ trợ các định dạng: `0901234567`, `+84901234567`, `090 123 4567`, `090-123-4567`

### 5.3 Admin Management

| Lệnh | Chức năng | Thông báo khách |
|------|-----------|----------------|
| `/paid [mã]` | Xác nhận thanh toán | "Đang pha chế, 10–15 phút nữa!" |
| `/done [mã]` | Đánh dấu hoàn thành | "Trà của bạn đã sẵn sàng! 🧋" |
| `/orders` | Xem 10 đơn gần nhất | — |
| `/myid` | Lấy Chat ID của tài khoản | — |

### 5.4 Payment Integration

```
PayOS credentials đầy đủ → Tạo QR code thật
PayOS credentials trống  → Mock Payment tự động
                           (Admin xác nhận bằng /paid)
```

### 5.5 Admin Dashboard

File `admin/dashboard.html` kết nối API `http://localhost:8000/orders` để hiển thị danh sách đơn hàng realtime, hỗ trợ lọc theo trạng thái (pending/paid/done).

---

## 6. CẤU TRÚC DATABASE

### Bảng `chat_sessions`
```sql
CREATE TABLE chat_sessions (
    user_id INTEGER PRIMARY KEY,
    cart TEXT DEFAULT '{"items": []}',
    delivery_info TEXT DEFAULT '{}',
    conversation_history TEXT DEFAULT '[]',
    updated_at TIMESTAMP
);
```

### Bảng `orders`
```sql
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_number TEXT UNIQUE,
    user_id INTEGER,
    username TEXT,
    first_name TEXT,
    status TEXT DEFAULT 'pending',  -- pending / paid / done
    total_amount INTEGER,
    cart TEXT,
    delivery_info TEXT,
    payment_link TEXT,
    payment_id TEXT,
    created_at TIMESTAMP,
    paid_at TIMESTAMP,
    done_at TIMESTAMP
);
```

---

## 7. KẾT QUẢ DEMO

### 7.1 Test Cases đã thực hiện

| Test Case | Kết quả |
|-----------|---------|
| `/start` → hiển thị menu và buttons | ✅ Pass |
| Chọn danh mục → hiện danh sách món | ✅ Pass |
| Chọn món → chọn size → chọn qty | ✅ Pass |
| Toggle topping (thêm/bỏ) | ✅ Pass |
| Xem giỏ hàng | ✅ Pass |
| Checkout flow (tên/SĐT/địa chỉ) | ✅ Pass |
| Validate SĐT sai → báo lỗi | ✅ Pass |
| Validate SĐT đúng → tiếp tục | ✅ Pass |
| Đặt hàng → nhận mã đơn + link | ✅ Pass |
| Admin `/paid` → khách nhận thông báo | ✅ Pass |
| Admin `/done` → khách nhận thông báo | ✅ Pass |
| AI free-text chat (Gemini) | ✅ Pass |
| Fallback khi AI lỗi | ✅ Pass |
| `/orders` liệt kê đơn hàng | ✅ Pass |

### 7.2 Ví dụ hội thoại

```
Khách: /start
Bot: Xin chào Thinh 👋🧋 Milu đây! [Menu buttons]

Khách: [Click Trà Sữa]
Bot: 🧋 Trà Sữa — Chọn món: [TS01 Trân châu đen] [TS02 Trân châu trắng]...

Khách: [Click TS01 - Trà sữa trân châu đen]
Bot: M — 35.000đ | L — 45.000đ [Size buttons]

Khách: [Click M] → [Click 1] → [Click top_done]
Bot: ✅ Đã thêm vào giỏ! Tổng: 35.000đ [Xem giỏ | Thêm món]

Khách: [Click Đặt hàng] → Nhập "Thinh Nguyen"
Bot: ✅ Xin chào Thinh Nguyen! Bước 2/3: Nhập số điện thoại

Khách: 0357040485
Bot: ✅ Đã lưu SĐT 0357040485! Bước 3/3: Nhập địa chỉ

Khách: Lê Lợi, Quận 1, HCM
Bot: [Xem giỏ + thông tin] Xác nhận đặt hàng chứ? [Confirm | Sửa | Huỷ]

Khách: [Click Xác nhận]
Bot: 🎉 ĐẶT HÀNG THÀNH CÔNG! #04207268 — 35.000đ [💳 Thanh toán]

Admin: /paid 04207268
Bot→Admin: ✅ Đã xác nhận + tóm tắt đơn + gợi ý /done
Bot→Khách: ✅ Thanh toán xác nhận! Đang pha chế, 10–15 phút nữa!

Admin: /done 04207268
Bot→Admin: 🎉 Đơn #04207268 hoàn thành!
Bot→Khách: 🎉 Trà của bạn đã sẵn sàng! 🧋 Chúc ngon miệng!
```

---

## 8. ĐIỂM NỔI BẬT & ĐỔI MỚI

### 8.1 Cách tiếp cận Hybrid thông minh
Phần lớn chatbot đặt hàng chọn **một** trong hai hướng: AI thuần túy (dễ lỗi/tốn kém) hoặc button thuần túy (thiếu tính AI). Giải pháp này **kết hợp cả hai**, ưu tiên ổn định nhưng vẫn đảm bảo trải nghiệm AI thực chất.

### 8.2 Graceful Degradation
Khi Gemini API lỗi (quota, 503, network), hệ thống **tự động fallback** về hướng dẫn dùng menu buttons — bot không bao giờ "chết" hoàn toàn.

### 8.3 State Machine cho Checkout
Thay vì phó mặc AI quản lý luồng thu thập thông tin giao hàng (hay sai, hay bỏ sót), hệ thống dùng **Finite State Machine rõ ràng**: `idle → name → phone → address → confirm`. Mỗi bước có validation riêng.

### 8.4 Character AI "Milu"
System prompt thiết kế nhân vật "Milu" — nhân viên trà sữa thân thiện, dùng tiếng Việt tự nhiên, biết gợi ý món theo khẩu vị, tạo cảm giác được phục vụ bởi người thật.

---

## 9. HƯỚNG PHÁT TRIỂN

| Tính năng | Mô tả | Ưu tiên |
|-----------|-------|---------|
| Deploy 24/7 | Railway/Render với Dockerfile | Cao |
| PayOS thật | Điền đủ credentials | Cao |
| Webhook mode | Thay polling để hiệu quả hơn | Trung bình |
| Zalo OA | Mở rộng sang nền tảng Zalo | Trung bình |
| Loyalty points | Hệ thống tích điểm khách hàng | Thấp |
| Recommendation AI | Gợi ý món dựa trên lịch sử đặt | Thấp |
| Analytics Dashboard | Thống kê doanh thu, top món | Thấp |

---

## 10. HƯỚNG DẪN CHẠY

```bash
# 1. Clone repo
git clone https://github.com/alexnguyen-bk/bot_milktea_order_casso.git
cd bot_milktea_order_casso

# 2. Cài dependencies
pip install -r requirements.txt

# 3. Cấu hình .env
cp .env.example .env
# Điền BOT_TOKEN, GEMINI_API_KEY, ADMIN_TELEGRAM_CHAT_ID

# 4. Chạy bot
python -m bot.main
# Hoặc Windows: double-click run_bot.bat
```

**Demo bot:** [@milkteainfo_bot](https://t.me/milkteainfo_bot)

---

*Tài liệu được lập bởi: Nguyễn Duy Thịnh — Intern Software Engineer 2026*  
