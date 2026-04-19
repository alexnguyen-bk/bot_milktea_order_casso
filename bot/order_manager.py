import csv
import uuid
from typing import Optional


def load_menu(csv_path: str = "data/menu.csv") -> list[dict]:
    """Load menu từ file CSV."""
    items = []
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["price_m"] = int(row["price_m"])
            row["price_l"] = int(row["price_l"])
            row["available"] = row["available"].upper() == "TRUE"
            items.append(row)
    return items


class OrderManager:
    """Quản lý giỏ hàng và logic đặt món."""

    def __init__(self, cart: dict, delivery_info: dict, menu: list[dict]):
        self.cart = cart if cart else {"items": []}
        if "items" not in self.cart:
            self.cart["items"] = []
        self.delivery_info = delivery_info if delivery_info else {}
        self.menu = menu
        # Index theo item_id để tra nhanh
        self._menu_index = {item["item_id"]: item for item in menu}

    # ──────────────────────────────
    # MENU
    # ──────────────────────────────

    def get_menu(self, category: Optional[str] = None) -> list[dict]:
        if category:
            return [i for i in self.menu if i["category"] == category and i["available"]]
        return [i for i in self.menu if i["available"]]

    def get_categories(self) -> list[str]:
        seen = []
        for item in self.menu:
            if item["category"] not in seen:
                seen.append(item["category"])
        return seen

    def get_item(self, item_id: str) -> Optional[dict]:
        return self._menu_index.get(item_id)

    def get_toppings(self) -> list[dict]:
        return [i for i in self.menu if i["category"] == "Topping" and i["available"]]

    # ──────────────────────────────
    # CART  
    # ──────────────────────────────

    def add_item(
        self,
        item_id: str,
        size: str,
        quantity: int,
        topping_ids: Optional[list[str]] = None,
    ) -> dict:
        item = self.get_item(item_id)
        if not item:
            return {"success": False, "message": f"Không tìm thấy món '{item_id}' trong menu."}

        if item["category"] == "Topping":
            return {"success": False, "message": "Topping được thêm kèm theo món chính, không thêm riêng lẻ."}

        if not item["available"]:
            return {"success": False, "message": f"Rất tiếc, {item['name']} hiện đã hết."}

        size = size.upper()
        if size not in ("M", "L"):
            return {"success": False, "message": "Size phải là M hoặc L."}

        unit_price = item["price_m"] if size == "M" else item["price_l"]

        # Xử lý toppings
        toppings_data = []
        topping_price = 0
        for tid in (topping_ids or []):
            top = self.get_item(tid)
            if top and top["category"] == "Topping":
                toppings_data.append({"item_id": tid, "name": top["name"], "price": top["price_m"]})
                topping_price += top["price_m"]

        item_total_price = unit_price + topping_price
        subtotal = item_total_price * quantity

        cart_item = {
            "cart_item_id": str(uuid.uuid4())[:8],
            "item_id": item_id,
            "item_name": item["name"],
            "size": size,
            "quantity": quantity,
            "unit_price": unit_price,
            "toppings": toppings_data,
            "topping_price": topping_price,
            "subtotal": subtotal,
        }
        self.cart["items"].append(cart_item)
        return {"success": True, "message": f"Đã thêm {quantity}x {item['name']} size {size} vào giỏ.", "item": cart_item}

    def view_cart(self) -> dict:
        items = self.cart.get("items", [])
        if not items:
            return {"empty": True, "items": [], "total": 0}
        total = sum(i["subtotal"] for i in items)
        return {"empty": False, "items": items, "total": total}

    def calculate_total(self) -> dict:
        items = self.cart.get("items", [])
        if not items:
            return {"total": 0, "items_count": 0}
        total = sum(i["subtotal"] for i in items)
        return {"total": total, "items_count": len(items)}

    def update_item(self, cart_item_id: str, quantity: Optional[int] = None, size: Optional[str] = None) -> dict:
        for item in self.cart["items"]:
            if item["cart_item_id"] == cart_item_id:
                if quantity is not None:
                    if quantity <= 0:
                        return self.remove_item(cart_item_id)
                    item["quantity"] = quantity

                if size is not None:
                    size = size.upper()
                    menu_item = self.get_item(item["item_id"])
                    if menu_item:
                        item["size"] = size
                        item["unit_price"] = menu_item["price_m"] if size == "M" else menu_item["price_l"]

                # Tính lại subtotal
                item["subtotal"] = (item["unit_price"] + item.get("topping_price", 0)) * item["quantity"]
                return {"success": True, "message": "Đã cập nhật món.", "item": item}
        return {"success": False, "message": f"Không tìm thấy món có ID '{cart_item_id}' trong giỏ."}

    def remove_item(self, cart_item_id: str) -> dict:
        before = len(self.cart["items"])
        self.cart["items"] = [i for i in self.cart["items"] if i["cart_item_id"] != cart_item_id]
        if len(self.cart["items"]) < before:
            return {"success": True, "message": "Đã xoá món khỏi giỏ hàng."}
        return {"success": False, "message": "Không tìm thấy món này trong giỏ."}

    def clear_cart(self) -> dict:
        self.cart["items"] = []
        self.delivery_info = {}
        return {"success": True, "message": "Đã xoá toàn bộ giỏ hàng."}

    def set_delivery_info(self, name: str, phone: str, address: str) -> dict:
        self.delivery_info = {"name": name, "phone": phone, "address": address}
        return {"success": True, "message": "Đã lưu thông tin giao hàng.", "delivery_info": self.delivery_info}

    def get_delivery_info(self) -> dict:
        return self.delivery_info

    def is_ready_to_order(self) -> tuple[bool, str]:
        """Kiểm tra giỏ hàng đủ điều kiện đặt hàng chưa."""
        if not self.cart.get("items"):
            return False, "Giỏ hàng đang trống."
        di = self.delivery_info
        if not di.get("name"):
            return False, "Thiếu tên người nhận."
        if not di.get("phone"):
            return False, "Thiếu số điện thoại."
        if not di.get("address"):
            return False, "Thiếu địa chỉ giao hàng."
        return True, "OK"
