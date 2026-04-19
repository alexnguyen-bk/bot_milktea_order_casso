import aiosqlite
import json
import os
from datetime import datetime
from typing import Optional


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    async def init(self):
        """Tạo các bảng nếu chưa có."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    conversation_history TEXT DEFAULT '[]',
                    cart TEXT DEFAULT '{"items": []}',
                    delivery_info TEXT DEFAULT '{}',
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_number TEXT UNIQUE NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    status TEXT DEFAULT 'pending',
                    total_amount INTEGER NOT NULL,
                    cart TEXT NOT NULL,
                    delivery_info TEXT DEFAULT '{}',
                    payment_id TEXT,
                    payment_link TEXT,
                    created_at TEXT,
                    paid_at TEXT,
                    done_at TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    item_id TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    size TEXT,
                    quantity INTEGER NOT NULL,
                    unit_price INTEGER NOT NULL,
                    toppings TEXT DEFAULT '[]',
                    subtotal INTEGER NOT NULL,
                    FOREIGN KEY (order_id) REFERENCES orders(id)
                )
            """)
            await db.commit()

    # ──────────────────────────────
    # SESSION
    # ──────────────────────────────

    async def get_session(self, user_id: int) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM sessions WHERE user_id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return {
                    "user_id": user_id,
                    "username": None,
                    "first_name": None,
                    "conversation_history": "[]",
                    "cart": '{"items": []}',
                    "delivery_info": "{}",
                }

    async def update_session(
        self,
        user_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        conversation_history: Optional[str] = None,
        cart: Optional[str] = None,
        delivery_info: Optional[str] = None,
    ):
        now = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            existing = await db.execute(
                "SELECT user_id FROM sessions WHERE user_id = ?", (user_id,)
            )
            row = await existing.fetchone()
            if row:
                await db.execute(
                    """UPDATE sessions SET
                        username = COALESCE(?, username),
                        first_name = COALESCE(?, first_name),
                        conversation_history = COALESCE(?, conversation_history),
                        cart = COALESCE(?, cart),
                        delivery_info = COALESCE(?, delivery_info),
                        updated_at = ?
                    WHERE user_id = ?""",
                    (username, first_name, conversation_history, cart, delivery_info, now, user_id),
                )
            else:
                await db.execute(
                    """INSERT INTO sessions
                        (user_id, username, first_name, conversation_history, cart, delivery_info, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        user_id, username, first_name,
                        conversation_history or "[]",
                        cart or '{"items": []}',
                        delivery_info or "{}",
                        now, now,
                    ),
                )
            await db.commit()

    async def clear_session_cart(self, user_id: int):
        """Xoá giỏ hàng và delivery info sau khi đặt xong."""
        await self.update_session(
            user_id=user_id,
            cart='{"items": []}',
            delivery_info="{}",
            conversation_history="[]",
        )

    # ──────────────────────────────
    # ORDERS
    # ──────────────────────────────

    async def create_order(
        self,
        order_number: str,
        user_id: int,
        username: Optional[str],
        first_name: Optional[str],
        total_amount: int,
        cart: dict,
        delivery_info: dict,
    ) -> int:
        now = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """INSERT INTO orders
                    (order_number, user_id, username, first_name, total_amount, cart, delivery_info, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order_number, user_id, username, first_name,
                    total_amount,
                    json.dumps(cart, ensure_ascii=False),
                    json.dumps(delivery_info, ensure_ascii=False),
                    now,
                ),
            )
            order_id = cursor.lastrowid

            # Insert order items
            for item in cart.get("items", []):
                toppings = item.get("toppings", [])
                await db.execute(
                    """INSERT INTO order_items
                        (order_id, item_id, item_name, size, quantity, unit_price, toppings, subtotal)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        order_id,
                        item["item_id"],
                        item["item_name"],
                        item.get("size"),
                        item["quantity"],
                        item["unit_price"],
                        json.dumps(toppings, ensure_ascii=False),
                        item["subtotal"],
                    ),
                )
            await db.commit()
            return order_id

    async def update_order_payment(self, order_number: str, payment_id: str, payment_link: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE orders SET payment_id = ?, payment_link = ? WHERE order_number = ?",
                (payment_id, payment_link, order_number),
            )
            await db.commit()

    async def mark_order_paid(self, order_number: str) -> Optional[dict]:
        now = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE orders SET status = 'paid', paid_at = ? WHERE order_number = ?",
                (now, order_number),
            )
            await db.commit()
            return await self.get_order(order_number)

    async def mark_order_done(self, order_number: str) -> Optional[dict]:
        now = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE orders SET status = 'done', done_at = ? WHERE order_number = ?",
                (now, order_number),
            )
            await db.commit()
            return await self.get_order(order_number)

    async def get_order(self, order_number: str) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM orders WHERE order_number = ?", (order_number,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    d = dict(row)
                    d["cart"] = json.loads(d["cart"])
                    d["delivery_info"] = json.loads(d["delivery_info"])
                    return d
                return None

    async def get_order_by_id(self, order_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM orders WHERE id = ?", (order_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    d = dict(row)
                    d["cart"] = json.loads(d["cart"])
                    d["delivery_info"] = json.loads(d["delivery_info"])
                    return d
                return None

    async def get_all_orders(self, status: Optional[str] = None, limit: int = 50) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = "SELECT * FROM orders"
            params = []
            if status:
                query += " WHERE status = ?"
                params.append(status)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                result = []
                for row in rows:
                    d = dict(row)
                    d["cart"] = json.loads(d["cart"])
                    d["delivery_info"] = json.loads(d["delivery_info"])
                    result.append(d)
                return result

    async def get_pending_order_by_user(self, user_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM orders WHERE user_id = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    d = dict(row)
                    d["cart"] = json.loads(d["cart"])
                    d["delivery_info"] = json.loads(d["delivery_info"])
                    return d
                return None

    async def get_stats(self) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) as total, SUM(total_amount) as revenue FROM orders WHERE status IN ('paid','done')"
            ) as cursor:
                row = await cursor.fetchone()
                total_orders = row[0] or 0
                total_revenue = row[1] or 0

            async with db.execute(
                "SELECT COUNT(*) FROM orders WHERE status = 'pending'"
            ) as cursor:
                pending = (await cursor.fetchone())[0] or 0

            async with db.execute(
                "SELECT COUNT(*) FROM orders WHERE status = 'done'"
            ) as cursor:
                done = (await cursor.fetchone())[0] or 0

            return {
                "total_orders": total_orders,
                "total_revenue": total_revenue,
                "pending": pending,
                "done": done,
            }
