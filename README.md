# 🧋 Milkteainfo Bot — AI Chatbot Đặt Trà Sữa

> Telegram bot AI tự động hỗ trợ khách đặt hàng, quản lý giỏ hàng và tích hợp thanh toán cho quán Milkteainfo.

[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://python.org)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-blue)](https://core.telegram.org/bots)
[![Gemini AI](https://img.shields.io/badge/Google-Gemini%202.5-green)](https://ai.google.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green)](https://fastapi.tiangolo.com)

## 🎯 Tính năng

### Khách hàng
- 🛍️ **Menu button-based** — Chọn danh mục → Chọn món → Chọn size/số lượng → Chọn topping
- 🤖 **AI Chat (Gemini)** — Nhắn tự nhiên để được tư vấn món
- 🛒 **Quản lý giỏ hàng** — Xem, sửa, xoá từng món
- 📦 **Nhập thông tin giao hàng** — Tên, SĐT, địa chỉ qua step-by-step
- 💳 **Thanh toán** — PayOS QR hoặc Mock Payment
- 🔔 **Nhận thông báo** — Khi đơn được xác nhận và hoàn thành

### Admin (quản trị)
- `/paid [mã đơn]` — Xác nhận thanh toán + tự động notify khách "đang pha chế"
- `/done [mã đơn]` — Hoàn thành đơn + notify khách "đơn đã xong"
- `/orders` — Xem danh sách đơn hàng gần đây
- 📊 Dashboard tại `admin/dashboard.html` — Quản lý đơn realtime

## 📁 Cấu trúc dự án

```
boba-bot/
├── bot/
│   ├── main.py               # Entry point (Telegram polling + FastAPI)
│   ├── telegram_handler.py   # Handlers: commands, buttons, AI chat
│   ├── ai_agent.py           # Gemini AI agent + function calling
│   ├── order_manager.py      # Logic giỏ hàng
│   ├── payment.py            # PayOS / Mock payment
│   └── database.py           # SQLite async database
├── data/
│   └── menu.csv              # Menu 27 món
├── admin/
│   └── dashboard.html        # Admin dashboard
├── config.py                 # Cấu hình tập trung
├── .env.example              # Template biến môi trường
├── requirements.txt
├── Dockerfile
└── run_bot.bat               # Script chạy nhanh (Windows)
```

## 🚀 Cài đặt & Chạy

### 1. Clone và cài dependencies

```bash
git clone https://github.com/alexnguyen-bk/bot_milktea_order_casso.git
cd bot_milktea_order_casso
pip install -r requirements.txt
```

### 2. Cấu hình `.env`

```bash
cp .env.example .env
```

Mở `.env` và điền:

```env
# Telegram Bot Token (lấy từ @BotFather)
BOT_TOKEN=your_telegram_bot_token

# Gemini API Key (miễn phí tại https://aistudio.google.com/app/apikey)
GEMINI_API_KEY=AIzaSy...
GEMINI_MODEL=gemini-2.5-flash

# Admin Telegram Chat ID (lấy từ @userinfobot)
ADMIN_TELEGRAM_CHAT_ID=

# PayOS (để trống để dùng Mock Payment)
PAYOS_CLIENT_ID=
PAYOS_API_KEY=
PAYOS_CHECKSUM_KEY=
```

### 3. Chạy bot

```bash
# Windows: double-click run_bot.bat
# Hoặc:
python -m bot.main
```

Bot sẽ chạy tại:
- **Telegram**: `@milkteainfo_bot`
- **Admin API**: `http://localhost:8000/orders`
- **Dashboard**: Mở file `admin/dashboard.html`

## 🤖 Luồng đặt hàng

```
/start → Chọn danh mục → Chọn món → Size/Số lượng → Topping
       → Xem giỏ → Đặt hàng → Nhập tên/SĐT/địa chỉ → Xác nhận
       → Thanh toán → [Admin: /paid] → Pha chế → [Admin: /done] → Done!
```

## 🔔 Quy trình Admin

| Lệnh | Tác dụng | Bot sẽ notify khách |
|------|----------|-------------------|
| `/paid {mã}` | Xác nhận thanh toán | "Đang pha chế, 10-15 phút nữa!" |
| `/done {mã}` | Đánh dấu hoàn thành | "Trà của bạn đã sẵn sàng! 🧋" |
| `/orders` | Xem danh sách đơn | — |

## 📊 Tech Stack

| Thành phần | Công nghệ |
|------------|-----------|
| Bot framework | python-telegram-bot 21.6 |
| AI | Google Gemini 2.5 Flash |
| Database | SQLite (aiosqlite) |
| Admin API | FastAPI + uvicorn |
| Payment | PayOS / Mock |
| Deploy | Railway / Render (Docker) |

## 🌐 Deploy lên Railway

1. Push code lên GitHub
2. Vào [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Thêm các biến môi trường từ `.env`
4. Railway tự build từ `Dockerfile`

---

> Dự án này được xây dựng cho Entry Test Intern Software Engineer 2026 — Casso Company.
