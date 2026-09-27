"""
db.py
-----
โมดูลนี้ทำหน้าที่จัดการข้อมูลทั้งหมดของระบบผ่านไฟล์ JSON
(users, menu, inventory, tables, orders)

กฎที่ยึดถือในไฟล์นี้:
- ห้ามใช้ Database Engine ใดๆ ใช้ไฟล์ .json เท่านั้น
- ทุกฟังก์ชันมี Try/Except ครอบการอ่าน/เขียนไฟล์และการคำนวณ
- ทุกฟังก์ชันรับพารามิเตอร์และมี return ค่าเสมอ (ไม่มีตรรกะลอยนอกฟังก์ชัน)
- มีการ validate ค่าตัวเลข (ห้ามติดลบ, ห้ามไม่ใช่ตัวเลข) ในทุกจุดที่เกี่ยวข้อง
"""

import json
import os
import uuid
import random
import logging
import math
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# ค่าคงที่ / โครงสร้าง path ของไฟล์ข้อมูล
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

FILE_PATHS = {
    "users": os.path.join(DATA_DIR, "users.json"),
    "menu": os.path.join(DATA_DIR, "menu.json"),
    "inventory": os.path.join(DATA_DIR, "inventory.json"),
    "tables": os.path.join(DATA_DIR, "tables.json"),
    "orders": os.path.join(DATA_DIR, "orders.json"),
    "bills": os.path.join(DATA_DIR, "bills.json"),
    "settings": os.path.join(DATA_DIR, "settings.json"),
}

# ชื่อร้านเริ่มต้น (ใช้เมื่อยังไม่เคยตั้งค่า หรือไฟล์ settings.json เสียหาย/หายไป)
DEFAULT_RESTAURANT_NAME = "ครัวไทย OS"

# ข้อมูลเริ่มต้น (ใช้ตอนไฟล์ยังไม่มีอยู่จริง)
DEFAULT_DATA = {
    "users": [
        {"user_id": "U001", "username": "admin", "password": "admin123", "role": "admin", "full_name": "ผู้ดูแลระบบ"},
        {"user_id": "U002", "username": "staff", "password": "staff123", "role": "staff", "full_name": "พนักงานเสิร์ฟ"},
    ],
    "menu": [
        {
            "menu_id": "M001",
            "name": "ผัดกะเพราหมูสับ",
            "price": 50.0,
            "category": "จานเดียว",
            "is_available": True,
            "recipe": [
                {"ingredient_id": "ING001", "qty_used": 0.15},
                {"ingredient_id": "ING002", "qty_used": 0.02},
                {"ingredient_id": "ING003", "qty_used": 0.05},
            ],
        },
        {
            "menu_id": "M002",
            "name": "ข้าวผัดหมู",
            "price": 45.0,
            "category": "จานเดียว",
            "is_available": True,
            "recipe": [
                {"ingredient_id": "ING001", "qty_used": 0.12},
                {"ingredient_id": "ING004", "qty_used": 0.2},
            ],
        },
    ],
    "inventory": [
        {"ingredient_id": "ING001", "name": "เนื้อหมูสับ", "stock_qty": 20.0, "unit": "กก.", "reorder_point": 5.0, "cost_per_unit": 120.0},
        {"ingredient_id": "ING002", "name": "พริกกะเพรา", "stock_qty": 5.0, "unit": "กก.", "reorder_point": 1.0, "cost_per_unit": 80.0},
        {"ingredient_id": "ING003", "name": "น้ำมันพืช", "stock_qty": 10.0, "unit": "ลิตร", "reorder_point": 2.0, "cost_per_unit": 45.0},
        {"ingredient_id": "ING004", "name": "ข้าวสวย", "stock_qty": 30.0, "unit": "กก.", "reorder_point": 5.0, "cost_per_unit": 25.0},
    ],
    "tables": [
        {"table_id": "T01", "table_name": "โต๊ะ 1", "status": "ว่าง", "pin": None, "opened_by": None, "opened_at": None},
        {"table_id": "T02", "table_name": "โต๊ะ 2", "status": "ว่าง", "pin": None, "opened_by": None, "opened_at": None},
        {"table_id": "T03", "table_name": "โต๊ะ 3", "status": "ว่าง", "pin": None, "opened_by": None, "opened_at": None},
    ],
    "orders": [],
    "bills": [],
    "settings": {"restaurant_name": DEFAULT_RESTAURANT_NAME},
}


# ---------------------------------------------------------------------------
# Logger: บันทึก log กรณีตัดสต็อกแล้วยอดติดลบ (ตามกฎเหล็ก: ต้องบันทึก log ไว้)
# ---------------------------------------------------------------------------

def _get_stock_logger():
    """
    เตรียมและคืนค่า logger สำหรับบันทึกเหตุการณ์ 'สต็อกติดลบ' ลงไฟล์ logs/stock_shortage.log
    ตั้งค่า handler แค่ครั้งเดียว (กันการซ้อน handler เวลาโมดูลถูก import หลายรอบ)

    Returns:
        logging.Logger | None: logger ที่พร้อมใช้งาน หรือ None หากตั้งค่าไม่สำเร็จ
    """
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        logger = logging.getLogger("stock_shortage_logger")
        if not logger.handlers:
            log_path = os.path.join(LOG_DIR, "stock_shortage.log")
            handler = logging.FileHandler(log_path, encoding="utf-8")
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.WARNING)
            logger.propagate = False
        return logger
    except Exception:
        return None


def _get_admin_logger():
    """
    เตรียมและคืนค่า logger สำหรับบันทึกการกระทำของ Admin ลงไฟล์ logs/admin_actions.log
    ใช้บันทึกทุกครั้งที่ Admin เพิ่ม/แก้ไข/ลบเมนู หรือเปลี่ยนสถานะอาหารหมด (ตามกฎเหล็ก)

    Returns:
        logging.Logger | None: logger ที่พร้อมใช้งาน หรือ None หากตั้งค่าไม่สำเร็จ
    """
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        logger = logging.getLogger("admin_actions_logger")
        if not logger.handlers:
            log_path = os.path.join(LOG_DIR, "admin_actions.log")
            handler = logging.FileHandler(log_path, encoding="utf-8")
            formatter = logging.Formatter("%(asctime)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False
        return logger
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 1) ฟังก์ชันพื้นฐาน: init ไฟล์ทั้งหมด
# ---------------------------------------------------------------------------

def init_data_files() -> bool:
    """
    ตรวจสอบและสร้างโฟลเดอร์/ไฟล์ JSON เริ่มต้นทั้งหมด หากยังไม่มีอยู่จริง

    Returns:
        bool: True หากเตรียมไฟล์สำเร็จทั้งหมด, False หากมีปัญหาระหว่างสร้างไฟล์
    """
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        for key, path in FILE_PATHS.items():
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(DEFAULT_DATA.get(key, []), f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        # ห้ามโชว์ error ของ python ให้ผู้ใช้เห็น -> คืนค่า False ให้ชั้นบน (app.py) แจ้งข้อความแทน
        return False


# ---------------------------------------------------------------------------
# 2) ฟังก์ชันอ่าน/เขียนไฟล์ JSON แบบทั่วไป (generic)
# ---------------------------------------------------------------------------

def read_json_file(file_key: str):
    """
    อ่านข้อมูลจากไฟล์ JSON ตาม key ที่กำหนด (users/menu/inventory/tables/orders)

    Args:
        file_key (str): ชื่อคีย์ของไฟล์ใน FILE_PATHS

    Returns:
        list | dict | None: ข้อมูลที่อ่านได้ (โครงสร้างเดิมในไฟล์)
                             คืนค่า None หากอ่านไม่สำเร็จหรือ key ไม่ถูกต้อง
    """
    try:
        if file_key not in FILE_PATHS:
            return None

        path = FILE_PATHS[file_key]
        if not os.path.exists(path):
            init_data_files()

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, FileNotFoundError, PermissionError, OSError):
        return None
    except Exception:
        return None


def write_json_file(file_key: str, data) -> bool:
    """
    เขียนข้อมูลลงไฟล์ JSON ตาม key ที่กำหนด

    Args:
        file_key (str): ชื่อคีย์ของไฟล์ใน FILE_PATHS
        data (list | dict): ข้อมูลที่จะเขียนทับลงไฟล์

    Returns:
        bool: True หากเขียนไฟล์สำเร็จ, False หากเกิดข้อผิดพลาด
    """
    try:
        if file_key not in FILE_PATHS:
            return False

        path = FILE_PATHS[file_key]
        # เขียนลงไฟล์ชั่วคราวก่อน แล้วค่อย replace เพื่อลดโอกาสไฟล์เสียหายระหว่างเขียน
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        return True
    except (PermissionError, OSError):
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 3) ฟังก์ชันเกี่ยวกับผู้ใช้ / สิทธิ์
# ---------------------------------------------------------------------------

def authenticate_user(username: str, password: str):
    """
    ตรวจสอบชื่อผู้ใช้และรหัสผ่าน เพื่อยืนยันตัวตนและดึง role

    Args:
        username (str): ชื่อผู้ใช้ที่กรอกเข้ามา
        password (str): รหัสผ่านที่กรอกเข้ามา

    Returns:
        dict | None: ข้อมูลผู้ใช้ (ไม่รวม password ในผลลัพธ์จริงที่จะส่งออกไป UI)
                     คืนค่า None หากข้อมูลไม่ถูกต้องหรือเกิดข้อผิดพลาด
    """
    try:
        if not isinstance(username, str) or not isinstance(password, str):
            return None
        if username.strip() == "" or password.strip() == "":
            return None

        users = read_json_file("users")
        if not users:
            return None

        for user in users:
            if user.get("username") == username and user.get("password") == password:
                # คืนค่าเฉพาะข้อมูลที่จำเป็น ไม่ส่ง password กลับออกไป
                return {
                    "user_id": user.get("user_id"),
                    "username": user.get("username"),
                    "role": user.get("role"),
                    "full_name": user.get("full_name"),
                }
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 4) ฟังก์ชันเกี่ยวกับเมนูอาหาร
# ---------------------------------------------------------------------------

def get_menu_list(only_available: bool = False):
    """
    ดึงรายการเมนูอาหารทั้งหมด

    Args:
        only_available (bool): หากเป็น True จะกรองเฉพาะเมนูที่ is_available = True

    Returns:
        list: รายการเมนูอาหาร (list of dict) หรือ list ว่างหากเกิดข้อผิดพลาด
    """
    try:
        menu = read_json_file("menu")
        if menu is None:
            return []
        if only_available:
            menu = [m for m in menu if m.get("is_available", False)]
        menu = sorted(menu, key=lambda m: str(m.get("name", "")))
        return menu
    except Exception:
        return []


def get_menu_by_id(menu_id: str):
    """
    ค้นหาข้อมูลเมนูจาก menu_id

    Args:
        menu_id (str): รหัสเมนู

    Returns:
        dict | None: ข้อมูลเมนู หรือ None หากไม่พบ / เกิดข้อผิดพลาด
    """
    try:
        if not isinstance(menu_id, str) or menu_id.strip() == "":
            return None
        menu = read_json_file("menu")
        if not menu:
            return None
        for item in menu:
            if item.get("menu_id") == menu_id:
                return item
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 5) ฟังก์ชันเกี่ยวกับสต็อกวัตถุดิบ (inventory)
# ---------------------------------------------------------------------------

def get_inventory_list():
    """
    ดึงรายการวัตถุดิบทั้งหมดในสต็อก

    Returns:
        list: รายการวัตถุดิบ (list of dict) หรือ list ว่างหากเกิดข้อผิดพลาด
    """
    try:
        inventory = read_json_file("inventory")
        if inventory is None:
            return []
        return sorted(inventory, key=lambda i: str(i.get("name", "")))
    except Exception:
        return []


def get_ingredient_by_id(ingredient_id: str):
    """
    ค้นหาข้อมูลวัตถุดิบจาก ingredient_id

    Args:
        ingredient_id (str): รหัสวัตถุดิบ

    Returns:
        dict | None: ข้อมูลวัตถุดิบ หรือ None หากไม่พบ
    """
    try:
        if not isinstance(ingredient_id, str) or ingredient_id.strip() == "":
            return None
        inventory = get_inventory_list()
        for ing in inventory:
            if ing.get("ingredient_id") == ingredient_id:
                return ing
        return None
    except Exception:
        return None


def update_stock_quantity(ingredient_id: str, new_qty) -> tuple:
    """
    แก้ไขจำนวนสต็อกวัตถุดิบโดยตรง (สำหรับ admin เติมของเข้าคลัง)

    Args:
        ingredient_id (str): รหัสวัตถุดิบ
        new_qty (int | float): จำนวนสต็อกใหม่ ห้ามติดลบและต้องเป็นตัวเลขเท่านั้น

    Returns:
        tuple(bool, str): (สถานะความสำเร็จ, ข้อความแจ้งผลลัพธ์ที่อ่านง่าย)
    """
    try:
        if not isinstance(ingredient_id, str) or ingredient_id.strip() == "":
            return False, "รหัสวัตถุดิบไม่ถูกต้อง"

        # ป้องกันการกรอกตัวอักษรในช่องตัวเลข (bool ก็ไม่ควรผ่าน)
        if isinstance(new_qty, bool) or not isinstance(new_qty, (int, float)):
            return False, "จำนวนสต็อกต้องเป็นตัวเลขเท่านั้น"

        if new_qty < 0:
            return False, "จำนวนสต็อกต้องไม่ติดลบ"

        inventory = get_inventory_list()
        found = False
        for ing in inventory:
            if ing.get("ingredient_id") == ingredient_id:
                ing["stock_qty"] = float(new_qty)
                found = True
                break

        if not found:
            return False, "ไม่พบวัตถุดิบนี้ในระบบ"

        success = write_json_file("inventory", inventory)
        if not success:
            return False, "บันทึกข้อมูลสต็อกไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"

        return True, "อัปเดตสต็อกวัตถุดิบสำเร็จ"
    except Exception:
        return False, "เกิดข้อผิดพลาดในการอัปเดตสต็อก กรุณาลองใหม่อีกครั้ง"


def check_stock_for_order(items: list) -> tuple:
    """
    ตรวจสอบว่าสต็อกวัตถุดิบเพียงพอสำหรับรายการอาหารที่จะสั่งหรือไม่
    (ใช้ recipe ของแต่ละเมนูมาคำนวณยอดใช้วัตถุดิบรวม)

    Args:
        items (list): รายการอาหาร เช่น [{"menu_id": "M001", "quantity": 2}, ...]

    Returns:
        tuple(bool, str): (สต็อกพอหรือไม่, ข้อความอธิบายผลลัพธ์)
    """
    try:
        if not isinstance(items, list) or len(items) == 0:
            return False, "ไม่มีรายการอาหารที่จะสั่ง"

        # รวมยอดวัตถุดิบที่ต้องใช้ทั้งหมดก่อน แล้วค่อยเทียบกับสต็อกจริง
        required_ingredients = {}

        for item in items:
            if not isinstance(item, dict):
                return False, "รูปแบบรายการอาหารไม่ถูกต้อง"

            menu_id = item.get("menu_id")
            quantity = item.get("quantity")

            if not isinstance(menu_id, str) or menu_id.strip() == "":
                return False, "รหัสเมนูไม่ถูกต้อง"

            if isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
                return False, f"จำนวนของเมนู {menu_id} ต้องเป็นตัวเลขเท่านั้น"

            if quantity <= 0:
                return False, f"จำนวนของเมนู {menu_id} ต้องมากกว่า 0"

            menu_item = get_menu_by_id(menu_id)
            if menu_item is None:
                return False, f"ไม่พบเมนูรหัส {menu_id} ในระบบ"

            if not menu_item.get("is_available", False):
                return False, f"เมนู '{menu_item.get('name', menu_id)}' ถูกปิดการขายอยู่"

            recipe = menu_item.get("recipe", [])
            for r in recipe:
                ing_id = r.get("ingredient_id")
                qty_used_per_unit = r.get("qty_used", 0)
                total_needed = qty_used_per_unit * quantity
                required_ingredients[ing_id] = required_ingredients.get(ing_id, 0) + total_needed

        # เทียบกับสต็อกจริง
        for ing_id, needed_qty in required_ingredients.items():
            ingredient = get_ingredient_by_id(ing_id)
            if ingredient is None:
                return False, f"ไม่พบวัตถุดิบรหัส {ing_id} ในระบบ"
            if ingredient.get("stock_qty", 0) < needed_qty:
                return False, f"วัตถุดิบ '{ingredient.get('name')}' ไม่เพียงพอต่อการปรุงอาหาร"

        return True, "สต็อกวัตถุดิบเพียงพอ"
    except Exception:
        return False, "เกิดข้อผิดพลาดในการตรวจสอบสต็อก กรุณาลองใหม่อีกครั้ง"


def deduct_stock_for_order(items: list) -> tuple:
    """
    ตัดสต็อกวัตถุดิบจริงตามรายการอาหารที่ขายได้ (ควรเรียกหลังจาก check_stock_for_order ผ่านแล้วเท่านั้น)

    Args:
        items (list): รายการอาหาร เช่น [{"menu_id": "M001", "quantity": 2}, ...]

    Returns:
        tuple(bool, str): (สถานะความสำเร็จ, ข้อความแจ้งผลลัพธ์)
    """
    try:
        # ตรวจสอบซ้ำอีกครั้งก่อนตัดจริง ป้องกันกรณีเรียกฟังก์ชันนี้ตรงๆ โดยไม่เช็คก่อน
        is_enough, message = check_stock_for_order(items)
        if not is_enough:
            return False, message

        inventory = get_inventory_list()
        inventory_map = {ing["ingredient_id"]: ing for ing in inventory}

        for item in items:
            menu_id = item.get("menu_id")
            quantity = item.get("quantity")
            menu_item = get_menu_by_id(menu_id)
            if menu_item is None:
                return False, f"ไม่พบเมนูรหัส {menu_id} ในระบบ"

            recipe = menu_item.get("recipe", [])
            for r in recipe:
                ing_id = r.get("ingredient_id")
                qty_used_per_unit = r.get("qty_used", 0)
                total_used = qty_used_per_unit * quantity
                if ing_id in inventory_map:
                    inventory_map[ing_id]["stock_qty"] -= total_used
                    if inventory_map[ing_id]["stock_qty"] < 0:
                        inventory_map[ing_id]["stock_qty"] = 0

        success = write_json_file("inventory", list(inventory_map.values()))
        if not success:
            return False, "ตัดสต็อกไม่สำเร็จ กรุณาตรวจสอบข้อมูลอีกครั้ง"

        return True, "ตัดสต็อกวัตถุดิบสำเร็จ"
    except Exception:
        return False, "เกิดข้อผิดพลาดในการตัดสต็อก กรุณาลองใหม่อีกครั้ง"


# ---------------------------------------------------------------------------
# 6) ฟังก์ชันเกี่ยวกับโต๊ะอาหาร
# ---------------------------------------------------------------------------

def get_all_tables():
    """
    ดึงรายการโต๊ะทั้งหมด

    Returns:
        list: รายการโต๊ะ (list of dict) หรือ list ว่างหากเกิดข้อผิดพลาด
    """
    try:
        tables = read_json_file("tables")
        if tables is None:
            return []
        return sorted(tables, key=lambda t: str(t.get("table_name", "")))
    except Exception:
        return []


def _generate_table_id() -> str:
    """
    สร้างรหัสโต๊ะใหม่แบบไม่ซ้ำ (T01, T02, ...) โดยหาเลขที่มากที่สุดที่มีอยู่แล้วบวกเพิ่ม
    ระบบเป็นผู้กำหนดรหัสเองเสมอ ไม่รับรหัสจากฟอร์มโดยตรง เพื่อกันรหัสชนกันหรือถูกปลอมแปลง

    Returns:
        str: รหัสโต๊ะใหม่ เช่น "T04"
    """
    try:
        tables = get_all_tables()
        if not tables:
            return "T01"

        max_num = 0
        for t in tables:
            tid = t.get("table_id", "")
            if isinstance(tid, str) and tid.startswith("T") and tid[1:].isdigit():
                max_num = max(max_num, int(tid[1:]))

        return f"T{max_num + 1:02d}"
    except Exception:
        return "T" + uuid.uuid4().hex[:6].upper()


def add_table(table_name: str, created_by: str = None) -> tuple:
    """
    เพิ่มโต๊ะใหม่เข้าระบบ (Staff/Admin เท่านั้น — ตรวจสิทธิ์จริงทำที่ฝั่ง routeใน app.py)
    ระบบสร้าง table_id ให้อัตโนมัติแบบไล่เลขต่อจากโต๊ะที่มีอยู่ (T01, T02, ...)
    โต๊ะใหม่เริ่มต้นด้วยสถานะ 'ว่าง' เสมอ (ยังไม่มี pin จนกว่าจะถูกเปิดโต๊ะ)

    Args:
        table_name (str): ชื่อโต๊ะที่ต้องการตั้ง เช่น "โต๊ะ 4" หรือ "โต๊ะ VIP"
        created_by (str|None): ชื่อผู้ใช้งาน (staff/admin) ที่เป็นคนเพิ่มโต๊ะ เก็บไว้บันทึก log เท่านั้น

    Returns:
        tuple(bool, dict|str): (สถานะความสำเร็จ, ข้อมูลโต๊ะที่สร้างใหม่ หรือข้อความ error)
    """
    try:
        if not isinstance(table_name, str) or table_name.strip() == "":
            return False, "กรุณากรอกชื่อโต๊ะ"

        clean_name = table_name.strip()

        if len(clean_name) > 50:
            return False, "ชื่อโต๊ะยาวเกินไป (สูงสุด 50 ตัวอักษร)"

        tables = get_all_tables()

        # กันชื่อโต๊ะซ้ำ (ไม่สนตัวพิมพ์เล็ก/ใหญ่และช่องว่างหัวท้าย) เพื่อไม่ให้พนักงานสับสนหน้างาน
        for t in tables:
            existing_name = t.get("table_name", "")
            if isinstance(existing_name, str) and existing_name.strip().lower() == clean_name.lower():
                return False, f"มีโต๊ะชื่อ '{clean_name}' อยู่ในระบบแล้ว กรุณาใช้ชื่ออื่น"

        new_table = {
            "table_id": _generate_table_id(),
            "table_name": clean_name,
            "status": "ว่าง",
            "pin": None,
            "opened_by": None,
            "opened_at": None,
        }

        tables.append(new_table)
        success = write_json_file("tables", tables)
        if not success:
            return False, "บันทึกโต๊ะใหม่ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"

        logger = _get_admin_logger()
        if logger is not None:
            try:
                logger.info(
                    "เพิ่มโต๊ะใหม่ | โดย=%s | table_id=%s | ชื่อ=%s",
                    created_by or "unknown", new_table["table_id"], new_table["table_name"],
                )
            except Exception:
                pass

        return True, new_table
    except Exception:
        return False, "เกิดข้อผิดพลาดในการเพิ่มโต๊ะ กรุณาลองใหม่อีกครั้ง"


def update_table_status(table_id: str, new_status: str) -> tuple:
    """
    อัปเดตสถานะโต๊ะ (เช่น 'ว่าง', 'มีลูกค้า', 'รอทำความสะอาด')

    Args:
        table_id (str): รหัสโต๊ะ
        new_status (str): สถานะใหม่ของโต๊ะ

    Returns:
        tuple(bool, str): (สถานะความสำเร็จ, ข้อความแจ้งผลลัพธ์)
    """
    try:
        if not isinstance(table_id, str) or table_id.strip() == "":
            return False, "รหัสโต๊ะไม่ถูกต้อง"
        if not isinstance(new_status, str) or new_status.strip() == "":
            return False, "สถานะโต๊ะไม่ถูกต้อง"

        tables = get_all_tables()
        found = False
        for t in tables:
            if t.get("table_id") == table_id:
                t["status"] = new_status
                found = True
                break

        if not found:
            return False, "ไม่พบโต๊ะนี้ในระบบ"

        success = write_json_file("tables", tables)
        if not success:
            return False, "บันทึกสถานะโต๊ะไม่สำเร็จ"

        return True, "อัปเดตสถานะโต๊ะสำเร็จ"
    except Exception:
        return False, "เกิดข้อผิดพลาดในการอัปเดตสถานะโต๊ะ"


def _generate_unique_pin(existing_pins: set) -> str:
    """
    สุ่ม PIN 4 หลัก (0000-9999) ที่ไม่ซ้ำกับ PIN ที่กำลังใช้งานอยู่

    Args:
        existing_pins (set): เซตของ PIN ที่กำลังใช้งานอยู่ในปัจจุบัน

    Returns:
        str: PIN 4 หลัก แบบ string (เก็บเลข 0 นำหน้าได้ เช่น "0042")
    """
    try:
        # กันกรณีสุดขั้ว (ใช้ครบทั้ง 10000 ค่าแล้ว) ไม่ให้ loop ไม่รู้จบ
        max_attempts = 20000
        for _ in range(max_attempts):
            candidate = str(random.randint(0, 9999)).zfill(4)
            if candidate not in existing_pins:
                return candidate
        return str(random.randint(0, 9999)).zfill(4)
    except Exception:
        return "0000"


def open_table(table_id: str, staff_username: str) -> tuple:
    """
    เปิดโต๊ะสำหรับลูกค้าใหม่: สุ่ม PIN 4 หลัก และเปลี่ยนสถานะโต๊ะเป็น 'มีลูกค้า'
    ใช้โดย Staff/Admin เท่านั้น (ตรวจสิทธิ์จริงจะทำที่ฝั่ง route ใน app.py)

    Args:
        table_id (str): รหัสโต๊ะที่จะเปิด
        staff_username (str): ชื่อผู้ใช้งาน (staff/admin) ที่เป็นคนเปิดโต๊ะ เก็บไว้อ้างอิง

    Returns:
        tuple(bool, dict | str): (สถานะความสำเร็จ, ข้อมูลโต๊ะที่อัปเดตแล้ว(มี pin) หรือข้อความ error)
    """
    try:
        if not isinstance(table_id, str) or table_id.strip() == "":
            return False, "รหัสโต๊ะไม่ถูกต้อง"
        if not isinstance(staff_username, str) or staff_username.strip() == "":
            return False, "ไม่พบข้อมูลผู้เปิดโต๊ะ"

        tables = get_all_tables()
        target_table = None
        existing_pins = set()

        for t in tables:
            if t.get("status") == "มีลูกค้า" and t.get("pin"):
                existing_pins.add(t.get("pin"))
            if t.get("table_id") == table_id:
                target_table = t

        if target_table is None:
            return False, "ไม่พบโต๊ะนี้ในระบบ"

        if target_table.get("status") == "มีลูกค้า":
            return False, "โต๊ะนี้มีลูกค้าใช้งานอยู่แล้ว"

        new_pin = _generate_unique_pin(existing_pins)
        target_table["status"] = "มีลูกค้า"
        target_table["pin"] = new_pin
        target_table["opened_by"] = staff_username
        target_table["opened_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        success = write_json_file("tables", tables)
        if not success:
            return False, "เปิดโต๊ะไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"

        return True, target_table
    except Exception:
        return False, "เกิดข้อผิดพลาดในการเปิดโต๊ะ กรุณาลองใหม่อีกครั้ง"


def build_qr_login_path(table: dict):
    """
    สร้าง path สำหรับลิงก์ QR Code เข้าโต๊ะ โดยอิงจาก table_id + pin ปัจจุบันของโต๊ะ
    (ข้อมูลทั้งสองค่านี้ถูกเซ็ตไว้แล้วใน open_table() จึงไม่ต้องเพิ่ม field ใหม่ใน tables.json)

    ใช้ pin เดียวกับระบบ PIN Code เดิมเป็น token ยืนยันตัวตนใน QR ด้วย เพื่อไม่ให้ table_id
    (ซึ่งมักเดาง่าย/เรียงลำดับ) ถูกใช้สวมสิทธิ์เข้าโต๊ะอื่นได้โดยไม่รู้ PIN จริง

    Args:
        table (dict): ข้อมูลโต๊ะ (จาก get_all_tables() หรือ open_table())

    Returns:
        str | None: path แบบ relative เช่น "/customer/qr-login/table_01?pin=1234"
                    คืนค่า None หากโต๊ะยังไม่เปิดใช้งาน (ไม่มี pin) หรือข้อมูลไม่ครบ
    """
    try:
        if not isinstance(table, dict):
            return None

        table_id = table.get("table_id")
        pin = table.get("pin")
        status = table.get("status")

        if not table_id or not pin or status != "มีลูกค้า":
            return None

        return f"/customer/qr-login/{table_id}?pin={pin}"
    except Exception:
        return None


def verify_table_pin(pin: str):
    """
    ตรวจสอบ PIN 4 หลักที่ลูกค้ากรอกเข้ามา ว่าตรงกับโต๊ะที่เปิดใช้งานอยู่หรือไม่

    Args:
        pin (str): PIN ที่ลูกค้ากรอก (ควรเป็นตัวเลข 4 หลัก)

    Returns:
        dict | None: ข้อมูลโต๊ะ หากพบ PIN ที่ตรงกันและโต๊ะสถานะ 'มีลูกค้า'
                     คืนค่า None หาก PIN ไม่ถูกต้อง/รูปแบบผิด/ไม่พบ
    """
    try:
        if not isinstance(pin, str):
            return None
        pin = pin.strip()

        # validation: ต้องเป็นตัวเลขล้วน 4 หลักเท่านั้น ห้ามมีตัวอักษรปน
        if len(pin) != 4 or not pin.isdigit():
            return None

        tables = get_all_tables()
        for t in tables:
            if t.get("status") == "มีลูกค้า" and t.get("pin") == pin:
                return t
        return None
    except Exception:
        return None


def close_table(table_id: str) -> tuple:
    """
    ปิดโต๊ะหลังลูกค้าชำระเงินเสร็จ: ล้างค่า PIN และเปลี่ยนสถานะกลับเป็น 'ว่าง'

    Args:
        table_id (str): รหัสโต๊ะที่จะปิด

    Returns:
        tuple(bool, str): (สถานะความสำเร็จ, ข้อความแจ้งผลลัพธ์)
    """
    try:
        if not isinstance(table_id, str) or table_id.strip() == "":
            return False, "รหัสโต๊ะไม่ถูกต้อง"

        tables = get_all_tables()
        found = False
        for t in tables:
            if t.get("table_id") == table_id:
                t["status"] = "ว่าง"
                t["pin"] = None
                t["opened_by"] = None
                t["opened_at"] = None
                found = True
                break

        if not found:
            return False, "ไม่พบโต๊ะนี้ในระบบ"

        success = write_json_file("tables", tables)
        if not success:
            return False, "ปิดโต๊ะไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"

        return True, "ปิดโต๊ะสำเร็จ"
    except Exception:
        return False, "เกิดข้อผิดพลาดในการปิดโต๊ะ"


def delete_table(table_id: str) -> tuple:
    """
    ลบโต๊ะออกจากระบบถาวร (Staff/Admin เท่านั้น — ตรวจสิทธิ์จริงทำที่ฝั่ง route ใน app.py)

    เงื่อนไขความปลอดภัยของข้อมูล:
    - ห้ามลบโต๊ะที่สถานะ 'มีลูกค้า' (กำลังใช้งานอยู่) เด็ดขาด ต้องปิดโต๊ะ (close_table) ก่อนเสมอ
      เพื่อกัน PIN/QR ของลูกค้าที่กำลังนั่งอยู่หลุดใช้งานไม่ได้กลางคัน และกันโต๊ะหายจากระบบ
      ทั้งที่ยังมีลูกค้าอยู่จริง
    - ออเดอร์/บิลเก่าที่เคยผูกกับ table_id นี้ (ในไฟล์ orders.json/bills.json) จะไม่ถูกแก้ไขหรือลบ
      ยังเก็บ table_id เดิมไว้เป็นข้อมูลประวัติได้ตามปกติ แม้โต๊ะจะถูกลบไปแล้ว

    Args:
        table_id (str): รหัสโต๊ะที่จะลบ

    Returns:
        tuple(bool, str): (สถานะความสำเร็จ, ข้อความแจ้งผลลัพธ์)
    """
    try:
        if not isinstance(table_id, str) or table_id.strip() == "":
            return False, "รหัสโต๊ะไม่ถูกต้อง"

        tables = get_all_tables()
        target_table = next((t for t in tables if t.get("table_id") == table_id), None)

        if target_table is None:
            return False, "ไม่พบโต๊ะนี้ในระบบ"

        if target_table.get("status") == "มีลูกค้า":
            return False, "ไม่สามารถลบโต๊ะที่มีลูกค้าใช้งานอยู่ได้ กรุณาปิดโต๊ะก่อนแล้วค่อยลบ"

        table_name = target_table.get("table_name", table_id)
        remaining_tables = [t for t in tables if t.get("table_id") != table_id]

        success = write_json_file("tables", remaining_tables)
        if not success:
            return False, "ลบโต๊ะไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"

        logger = _get_admin_logger()
        if logger is not None:
            try:
                logger.info("ลบโต๊ะ | table_id=%s | ชื่อ=%s", table_id, table_name)
            except Exception:
                pass

        return True, f"ลบ {table_name} ออกจากระบบเรียบร้อยแล้ว"
    except Exception:
        return False, "เกิดข้อผิดพลาดในการลบโต๊ะ กรุณาลองใหม่อีกครั้ง"


def search_menu(keyword: str = "", category: str = "") -> list:
    """
    ค้นหาและกรองเมนูอาหารทั้งหมด (รวมเมนูที่ "อาหารหมด" / is_available = False ด้วย)
    ตามคำค้นหา (ชื่อเมนู) และหมวดหมู่
    หมายเหตุ: จงใจไม่กรอง only_available ออก เพื่อให้หน้าลูกค้าแสดงเมนูที่หมดพร้อมป้ายกำกับ
    แทนที่จะทำให้เมนูหายไปเฉยๆ จนลูกค้าเข้าใจผิดว่าร้านไม่มีขาย
    (ฝั่ง customer_order ยัง validate ปฏิเสธการสั่งเมนูที่ is_available = False อยู่เหมือนเดิม)

    Args:
        keyword (str): คำค้นหา จะเทียบแบบ substring แบบไม่สนตัวพิมพ์เล็ก/ใหญ่กับชื่อเมนู
        category (str): หมวดหมู่ที่ต้องการกรอง ("" หมายถึงไม่กรอง แสดงทุกหมวด)

    Returns:
        list: รายการเมนู (list of dict) ที่ตรงเงื่อนไข (ทั้งที่พร้อมขายและอาหารหมด)
              หรือ list ว่างหากเกิดข้อผิดพลาด
    """
    try:
        if not isinstance(keyword, str):
            keyword = ""
        if not isinstance(category, str):
            category = ""

        keyword = keyword.strip().lower()
        category = category.strip()

        # ดึงเมนูทั้งหมด (รวมเมนูที่ is_available = False ด้วย)
        # เพื่อให้หน้าลูกค้าเห็นว่าเมนูนี้มีอยู่จริงแต่ "อาหารหมด" แทนที่จะหายไปเฉยๆ
        menu = get_menu_list(only_available=False)
        result = []
        for item in menu:
            name = str(item.get("name", "")).lower()
            item_category = str(item.get("category", ""))

            if keyword and keyword not in name:
                continue
            if category and category != item_category:
                continue

            result.append(item)
        return result
    except Exception:
        return []


def get_menu_categories() -> list:
    """
    ดึงรายชื่อหมวดหมู่เมนูทั้งหมดที่มีอยู่ (จากเมนูที่พร้อมขาย) แบบไม่ซ้ำและเรียงตามตัวอักษร

    Returns:
        list: รายชื่อหมวดหมู่ (list of str) หรือ list ว่างหากเกิดข้อผิดพลาด
    """
    try:
        menu = get_menu_list(only_available=True)
        categories = sorted({item.get("category") for item in menu if item.get("category")})
        return categories
    except Exception:
        return []


# ---------------------------------------------------------------------------
# 7ก) ฟังก์ชันสำหรับ Admin: CRUD จัดการเมนูอาหาร
# ---------------------------------------------------------------------------

def _generate_menu_id() -> str:
    """
    สร้างรหัสเมนูใหม่แบบไม่ซ้ำ (M001, M002, ...) โดยหาเลขที่มากที่สุดที่มีอยู่แล้วบวกเพิ่ม
    ระบบเป็นผู้กำหนดรหัสเองเสมอ ไม่รับรหัสจากฟอร์มโดยตรง เพื่อกันรหัสชนกันหรือถูกปลอมแปลง

    Returns:
        str: รหัสเมนูใหม่ เช่น "M005"
    """
    try:
        menu = read_json_file("menu")
        if not menu:
            return "M001"

        max_num = 0
        for item in menu:
            mid = item.get("menu_id", "")
            if isinstance(mid, str) and mid.startswith("M") and mid[1:].isdigit():
                max_num = max(max_num, int(mid[1:]))

        return f"M{max_num + 1:03d}"
    except Exception:
        return "M" + uuid.uuid4().hex[:6].upper()


def _validate_recipe(recipe_raw) -> tuple:
    """
    ตรวจสอบความถูกต้องของข้อมูลสูตรอาหาร (recipe) ที่ Admin กรอกผ่านฟอร์ม
    ห้าม ingredient_id ปลอม, ห้าม qty_used ติดลบ/เป็นศูนย์/ไม่ใช่ตัวเลข

    Args:
        recipe_raw: ข้อมูลที่คาดว่าเป็น list ของ {"ingredient_id":.., "qty_used":..}

    Returns:
        tuple(bool, list|str): (ผ่าน validation หรือไม่, รายการ recipe ที่สะอาดแล้ว หรือข้อความ error)
    """
    try:
        if not isinstance(recipe_raw, list):
            return False, "รูปแบบข้อมูลสูตรอาหารไม่ถูกต้อง"

        cleaned = []
        seen_ingredients = set()
        valid_ingredient_ids = {ing["ingredient_id"] for ing in get_inventory_list()}

        for row in recipe_raw:
            if not isinstance(row, dict):
                return False, "รูปแบบข้อมูลสูตรอาหารไม่ถูกต้อง"

            ing_id = row.get("ingredient_id")
            qty_used = row.get("qty_used")

            if not isinstance(ing_id, str) or ing_id.strip() == "":
                return False, "กรุณาเลือกวัตถุดิบให้ครบทุกแถว"

            if ing_id not in valid_ingredient_ids:
                return False, f"ไม่พบวัตถุดิบรหัส {ing_id} ในระบบ"

            if ing_id in seen_ingredients:
                return False, "มีวัตถุดิบซ้ำกันในสูตรอาหาร กรุณาตรวจสอบอีกครั้ง"
            seen_ingredients.add(ing_id)

            if isinstance(qty_used, bool) or not isinstance(qty_used, (int, float)):
                return False, "ปริมาณวัตถุดิบต่อจานต้องเป็นตัวเลขเท่านั้น"

            if not math.isfinite(qty_used):
                return False, "ปริมาณวัตถุดิบต่อจานไม่ใช่ตัวเลขที่ถูกต้อง"

            if qty_used <= 0:
                return False, "ปริมาณวัตถุดิบต่อจานต้องมากกว่า 0"

            cleaned.append({"ingredient_id": ing_id, "qty_used": float(qty_used)})

        return True, cleaned
    except Exception:
        return False, "เกิดข้อผิดพลาดในการตรวจสอบสูตรอาหาร"


def add_menu_item(name: str, price, category: str, recipe_raw: list, image_filename, admin_username: str) -> tuple:
    """
    เพิ่มเมนูอาหารใหม่ (Admin เท่านั้น) พร้อม validate ทุกฟิลด์และบันทึก log

    Args:
        name (str): ชื่อเมนู
        price (int|float): ราคา ต้องมากกว่า 0
        category (str): หมวดหมู่
        recipe_raw (list): สูตรอาหาร [{"ingredient_id":.., "qty_used":..}, ...]
        image_filename (str|None): ชื่อไฟล์รูปภาพที่ถูกตรวจสอบและบันทึกไว้แล้ว (จาก app.py) หรือ None
        admin_username (str): ผู้ทำรายการ เพื่อบันทึกลง log

    Returns:
        tuple(bool, dict|str): (สถานะความสำเร็จ, ข้อมูลเมนูที่สร้าง หรือข้อความ error)
    """
    try:
        if not isinstance(name, str) or name.strip() == "":
            return False, "กรุณากรอกชื่อเมนู"
        if len(name.strip()) > 100:
            return False, "ชื่อเมนูยาวเกินไป (สูงสุด 100 ตัวอักษร)"

        if isinstance(price, bool) or not isinstance(price, (int, float)):
            return False, "ราคาต้องเป็นตัวเลขเท่านั้น"
        if not math.isfinite(price):
            return False, "ราคาไม่ใช่ตัวเลขที่ถูกต้อง"
        if price <= 0:
            return False, "ราคาต้องมากกว่า 0 เท่านั้น"

        if not isinstance(category, str) or category.strip() == "":
            return False, "กรุณาระบุหมวดหมู่"

        recipe_ok, recipe_result = _validate_recipe(recipe_raw)
        if not recipe_ok:
            return False, recipe_result

        if image_filename is not None and not isinstance(image_filename, str):
            return False, "ข้อมูลรูปภาพไม่ถูกต้อง"

        menu = read_json_file("menu")
        if menu is None:
            menu = []

        new_item = {
            "menu_id": _generate_menu_id(),
            "name": name.strip(),
            "price": float(price),
            "category": category.strip(),
            "is_available": True,
            "image": image_filename,
            "recipe": recipe_result,
        }

        menu.append(new_item)
        success = write_json_file("menu", menu)
        if not success:
            return False, "บันทึกเมนูใหม่ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"

        logger = _get_admin_logger()
        if logger is not None:
            try:
                logger.info(
                    "เพิ่มเมนูใหม่ | โดย=%s | menu_id=%s | ชื่อ=%s | ราคา=%.2f | หมวดหมู่=%s",
                    admin_username, new_item["menu_id"], new_item["name"], new_item["price"], new_item["category"],
                )
            except Exception:
                pass

        return True, new_item
    except Exception:
        return False, "เกิดข้อผิดพลาดในการเพิ่มเมนู กรุณาลองใหม่อีกครั้ง"


def update_menu_item(
    menu_id: str, name: str, price, category: str, recipe_raw: list, new_image_filename, admin_username: str
) -> tuple:
    """
    แก้ไขเมนูอาหารที่มีอยู่ (Admin เท่านั้น) พร้อม validate ทุกฟิลด์และบันทึก log การเปลี่ยนแปลง

    Args:
        menu_id (str): รหัสเมนูที่จะแก้ไข
        name, price, category, recipe_raw: ข้อมูลใหม่ (validate เหมือน add_menu_item)
        new_image_filename (str|None): ชื่อไฟล์รูปใหม่ (ถ้ามีการอัปโหลดใหม่) หรือ None = ใช้รูปเดิมต่อ
        admin_username (str): ผู้ทำรายการ

    Returns:
        tuple(bool, dict|str): (สถานะความสำเร็จ, ข้อมูลเมนูที่แก้ไขแล้ว หรือข้อความ error)
                                หากมีการเปลี่ยนรูป จะคืน key พิเศษ "_old_image" ไว้ให้ app.py ไปลบไฟล์เก่าทิ้ง
    """
    try:
        if not isinstance(menu_id, str) or menu_id.strip() == "":
            return False, "รหัสเมนูไม่ถูกต้อง"

        if not isinstance(name, str) or name.strip() == "":
            return False, "กรุณากรอกชื่อเมนู"
        if len(name.strip()) > 100:
            return False, "ชื่อเมนูยาวเกินไป (สูงสุด 100 ตัวอักษร)"

        if isinstance(price, bool) or not isinstance(price, (int, float)):
            return False, "ราคาต้องเป็นตัวเลขเท่านั้น"
        if not math.isfinite(price):
            return False, "ราคาไม่ใช่ตัวเลขที่ถูกต้อง"
        if price <= 0:
            return False, "ราคาต้องมากกว่า 0 เท่านั้น"

        if not isinstance(category, str) or category.strip() == "":
            return False, "กรุณาระบุหมวดหมู่"

        recipe_ok, recipe_result = _validate_recipe(recipe_raw)
        if not recipe_ok:
            return False, recipe_result

        if new_image_filename is not None and not isinstance(new_image_filename, str):
            return False, "ข้อมูลรูปภาพไม่ถูกต้อง"

        menu = read_json_file("menu")
        if not menu:
            return False, "ไม่พบข้อมูลเมนูในระบบ"

        target = next((m for m in menu if m.get("menu_id") == menu_id), None)
        if target is None:
            return False, "ไม่พบเมนูนี้ในระบบ"

        changes = []
        if target.get("name") != name.strip():
            changes.append(f"ชื่อ '{target.get('name')}' -> '{name.strip()}'")
        if float(target.get("price", 0)) != float(price):
            changes.append(f"ราคา {target.get('price')} -> {price}")
        if target.get("category") != category.strip():
            changes.append(f"หมวดหมู่ '{target.get('category')}' -> '{category.strip()}'")

        old_image = target.get("image")

        target["name"] = name.strip()
        target["price"] = float(price)
        target["category"] = category.strip()
        target["recipe"] = recipe_result

        image_changed = False
        if new_image_filename is not None:
            target["image"] = new_image_filename
            image_changed = True
            changes.append("เปลี่ยนรูปภาพเมนู")

        success = write_json_file("menu", menu)
        if not success:
            return False, "บันทึกการแก้ไขเมนูไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"

        logger = _get_admin_logger()
        if logger is not None:
            try:
                if changes:
                    logger.info(
                        "แก้ไขเมนู | โดย=%s | menu_id=%s | การเปลี่ยนแปลง: %s",
                        admin_username, menu_id, "; ".join(changes),
                    )
                else:
                    logger.info("แก้ไขเมนู | โดย=%s | menu_id=%s | ไม่มีการเปลี่ยนแปลงค่าจริง", admin_username, menu_id)
            except Exception:
                pass

        result = dict(target)
        if image_changed and old_image:
            result["_old_image"] = old_image
        return True, result
    except Exception:
        return False, "เกิดข้อผิดพลาดในการแก้ไขเมนู กรุณาลองใหม่อีกครั้ง"


def delete_menu_item(menu_id: str, admin_username: str) -> tuple:
    """
    ลบเมนูอาหารออกจากระบบ (Admin เท่านั้น) พร้อมบันทึก log

    Args:
        menu_id (str): รหัสเมนูที่จะลบ
        admin_username (str): ผู้ทำรายการ

    Returns:
        tuple(bool, str): (สถานะความสำเร็จ, ชื่อไฟล์รูปภาพเดิม(ถ้ามี ให้ app.py ไปลบไฟล์ทิ้ง) หรือข้อความ error)
    """
    try:
        if not isinstance(menu_id, str) or menu_id.strip() == "":
            return False, "รหัสเมนูไม่ถูกต้อง"

        menu = read_json_file("menu")
        if not menu:
            return False, "ไม่พบข้อมูลเมนูในระบบ"

        target = next((m for m in menu if m.get("menu_id") == menu_id), None)
        if target is None:
            return False, "ไม่พบเมนูนี้ในระบบ"

        old_image = target.get("image")
        menu_name = target.get("name", menu_id)

        menu = [m for m in menu if m.get("menu_id") != menu_id]
        success = write_json_file("menu", menu)
        if not success:
            return False, "ลบเมนูไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"

        logger = _get_admin_logger()
        if logger is not None:
            try:
                logger.info("ลบเมนู | โดย=%s | menu_id=%s | ชื่อ=%s", admin_username, menu_id, menu_name)
            except Exception:
                pass

        return True, old_image
    except Exception:
        return False, "เกิดข้อผิดพลาดในการลบเมนู กรุณาลองใหม่อีกครั้ง"


def toggle_menu_availability(menu_id: str, admin_username: str) -> tuple:
    """
    สลับสถานะเปิด/ปิดขายของเมนู (เช่น กดแจ้ง 'อาหารหมด') พร้อมบันทึก log ตามกฎเหล็ก

    Args:
        menu_id (str): รหัสเมนู
        admin_username (str): ผู้ทำรายการ

    Returns:
        tuple(bool, str): (สถานะความสำเร็จ, ข้อความแจ้งผลลัพธ์)
    """
    try:
        if not isinstance(menu_id, str) or menu_id.strip() == "":
            return False, "รหัสเมนูไม่ถูกต้อง"

        menu = read_json_file("menu")
        if not menu:
            return False, "ไม่พบข้อมูลเมนูในระบบ"

        target = next((m for m in menu if m.get("menu_id") == menu_id), None)
        if target is None:
            return False, "ไม่พบเมนูนี้ในระบบ"

        old_status = target.get("is_available", True)
        target["is_available"] = not old_status

        success = write_json_file("menu", menu)
        if not success:
            return False, "อัปเดตสถานะเมนูไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"

        logger = _get_admin_logger()
        if logger is not None:
            try:
                logger.info(
                    "เปลี่ยนสถานะเมนู | โดย=%s | menu_id=%s | ชื่อ=%s | is_available: %s -> %s",
                    admin_username, menu_id, target.get("name"), old_status, target["is_available"],
                )
            except Exception:
                pass

        status_text = "พร้อมขาย" if target["is_available"] else "อาหารหมด"
        return True, f"เปลี่ยนสถานะ '{target.get('name')}' เป็น '{status_text}' สำเร็จ"
    except Exception:
        return False, "เกิดข้อผิดพลาดในการเปลี่ยนสถานะเมนู"


def get_menu_item_by_id_raw(menu_id: str):
    """เหมือน get_menu_by_id แต่คงชื่อแยกไว้ให้ route ฝั่ง admin เรียกใช้ชัดเจนว่าใช้เพื่อดึงข้อมูลไปแก้ไข"""
    return get_menu_by_id(menu_id)


# ---------------------------------------------------------------------------
# 7ข) ฟังก์ชันสำหรับ Admin: จัดการ Reorder Point ของวัตถุดิบ
# ---------------------------------------------------------------------------

def update_ingredient_settings(ingredient_id: str, stock_qty, reorder_point, admin_username: str = "") -> tuple:
    """
    แก้ไขจำนวนสต็อกและจุดสั่งซื้อเพิ่ม (reorder point) ของวัตถุดิบ (Admin เท่านั้น)

    Args:
        ingredient_id (str): รหัสวัตถุดิบ
        stock_qty (int|float): จำนวนสต็อกใหม่ ห้ามติดลบ
        reorder_point (int|float): จุดแจ้งเตือนให้สั่งซื้อเพิ่ม ห้ามติดลบ
        admin_username (str): ผู้ทำรายการ

    Returns:
        tuple(bool, str): (สถานะความสำเร็จ, ข้อความแจ้งผลลัพธ์)
    """
    try:
        if not isinstance(ingredient_id, str) or ingredient_id.strip() == "":
            return False, "รหัสวัตถุดิบไม่ถูกต้อง"

        if isinstance(stock_qty, bool) or not isinstance(stock_qty, (int, float)):
            return False, "จำนวนสต็อกต้องเป็นตัวเลขเท่านั้น"
        if not math.isfinite(stock_qty):
            return False, "จำนวนสต็อกไม่ใช่ตัวเลขที่ถูกต้อง"
        if stock_qty < 0:
            return False, "จำนวนสต็อกต้องไม่ติดลบ"

        if isinstance(reorder_point, bool) or not isinstance(reorder_point, (int, float)):
            return False, "จุดสั่งซื้อเพิ่มต้องเป็นตัวเลขเท่านั้น"
        if not math.isfinite(reorder_point):
            return False, "จุดสั่งซื้อเพิ่มไม่ใช่ตัวเลขที่ถูกต้อง"
        if reorder_point < 0:
            return False, "จุดสั่งซื้อเพิ่มต้องไม่ติดลบ"

        inventory = get_inventory_list()
        target = next((ing for ing in inventory if ing.get("ingredient_id") == ingredient_id), None)
        if target is None:
            return False, "ไม่พบวัตถุดิบนี้ในระบบ"

        target["stock_qty"] = float(stock_qty)
        target["reorder_point"] = float(reorder_point)

        success = write_json_file("inventory", inventory)
        if not success:
            return False, "บันทึกข้อมูลวัตถุดิบไม่สำเร็จ"

        logger = _get_admin_logger()
        if logger is not None and admin_username:
            try:
                logger.info(
                    "แก้ไขวัตถุดิบ | โดย=%s | ingredient_id=%s | สต็อก=%.3f | จุดสั่งซื้อเพิ่ม=%.3f",
                    admin_username, ingredient_id, target["stock_qty"], target["reorder_point"],
                )
            except Exception:
                pass

        return True, "อัปเดตข้อมูลวัตถุดิบสำเร็จ"
    except Exception:
        return False, "เกิดข้อผิดพลาดในการอัปเดตวัตถุดิบ"


# ---------------------------------------------------------------------------
# 7ค) ฟังก์ชันสำหรับ Admin Dashboard: ยอดขาย / เมนูขายดี / มูลค่าสต็อก / แจ้งเตือน
# ---------------------------------------------------------------------------

def get_daily_sales(date_str: str = None) -> dict:
    """
    สรุปยอดขายของวันที่ระบุ (จากข้อมูลบิลที่เช็คบิลสำเร็จแล้วใน bills.json)

    Args:
        date_str (str|None): วันที่รูปแบบ "YYYY-MM-DD" หากไม่ระบุจะใช้วันนี้

    Returns:
        dict: {"date": str, "total_sales": float, "bill_count": int} หรือค่า 0 ทั้งหมดหากเกิดข้อผิดพลาด
    """
    try:
        if not isinstance(date_str, str) or date_str.strip() == "":
            date_str = datetime.now().strftime("%Y-%m-%d")

        bills = read_json_file("bills")
        if not bills:
            return {"date": date_str, "total_sales": 0.0, "bill_count": 0}

        total = 0.0
        count = 0
        for b in bills:
            checked_out_at = b.get("checked_out_at", "")
            if isinstance(checked_out_at, str) and checked_out_at.startswith(date_str):
                grand_total = b.get("grand_total", 0)
                if isinstance(grand_total, (int, float)) and not isinstance(grand_total, bool):
                    total += grand_total
                    count += 1

        return {"date": date_str, "total_sales": round(total, 2), "bill_count": count}
    except Exception:
        return {"date": date_str or "", "total_sales": 0.0, "bill_count": 0}


def get_best_selling_menu(limit: int = 5) -> list:
    """
    หาเมนูขายดีที่สุด (สะสมจากทุกบิลที่เช็คบิลสำเร็จแล้ว) เรียงจากจำนวนที่ขายได้มากไปน้อย

    Args:
        limit (int): จำนวนอันดับสูงสุดที่ต้องการ

    Returns:
        list: [{"menu_id","name","total_qty","total_revenue"}, ...] เรียงจากขายดีที่สุด
    """
    try:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            limit = 5

        orders = read_json_file("orders")
        if not orders:
            return []

        summary = {}
        for o in orders:
            if not o.get("billed", False):
                continue
            for item in o.get("items", []):
                menu_id = item.get("menu_id")
                name = item.get("name", menu_id)
                qty = item.get("quantity", 0)
                subtotal = item.get("subtotal", 0)
                if not isinstance(qty, (int, float)) or isinstance(qty, bool):
                    continue
                if menu_id not in summary:
                    summary[menu_id] = {"menu_id": menu_id, "name": name, "total_qty": 0, "total_revenue": 0.0}
                summary[menu_id]["total_qty"] += qty
                if isinstance(subtotal, (int, float)) and not isinstance(subtotal, bool):
                    summary[menu_id]["total_revenue"] += subtotal

        ranked = sorted(summary.values(), key=lambda x: x["total_qty"], reverse=True)
        return ranked[:limit]
    except Exception:
        return []


def get_stock_value() -> float:
    """
    คำนวณมูลค่ารวมของสต็อกวัตถุดิบคงเหลือทั้งหมด (stock_qty x cost_per_unit ของแต่ละรายการ)
    หากวัตถุดิบใดติดลบ จะนับมูลค่าเป็น 0 สำหรับรายการนั้น (ของที่ไม่มีจริง ไม่ควรมีมูลค่าติดลบ)

    Returns:
        float: มูลค่าสต็อกรวม (บาท) หรือ 0.0 หากเกิดข้อผิดพลาด
    """
    try:
        inventory = get_inventory_list()
        total_value = 0.0
        for ing in inventory:
            stock_qty = ing.get("stock_qty", 0)
            cost_per_unit = ing.get("cost_per_unit", 0)
            if not isinstance(stock_qty, (int, float)) or isinstance(stock_qty, bool):
                continue
            if not isinstance(cost_per_unit, (int, float)) or isinstance(cost_per_unit, bool):
                continue
            total_value += max(stock_qty, 0) * cost_per_unit
        return round(total_value, 2)
    except Exception:
        return 0.0


def get_low_stock_alerts() -> list:
    """
    ดึงรายการวัตถุดิบที่สต็อกคงเหลือต่ำกว่าจุดสั่งซื้อเพิ่ม (reorder point)

    Returns:
        list: [{"ingredient_id","name","stock_qty","reorder_point","unit"}, ...] หรือ list ว่าง
    """
    try:
        inventory = get_inventory_list()
        alerts = []
        for ing in inventory:
            stock_qty = ing.get("stock_qty", 0)
            reorder_point = ing.get("reorder_point", 0)
            if not isinstance(stock_qty, (int, float)) or isinstance(stock_qty, bool):
                continue
            if not isinstance(reorder_point, (int, float)) or isinstance(reorder_point, bool):
                continue
            if stock_qty < reorder_point:
                alerts.append({
                    "ingredient_id": ing.get("ingredient_id"),
                    "name": ing.get("name"),
                    "stock_qty": stock_qty,
                    "reorder_point": reorder_point,
                    "unit": ing.get("unit"),
                })
        return alerts
    except Exception:
        return []


# ---------------------------------------------------------------------------
# 7) ฟังก์ชันเกี่ยวกับออเดอร์ (order)
# ---------------------------------------------------------------------------

def create_order(table_id: str, items: list, created_by: str = "customer") -> tuple:
    """
    สร้างออเดอร์ใหม่: ตรวจสอบความถูกต้องของข้อมูล -> เช็คสต็อก -> ตัดสต็อก -> บันทึกออเดอร์

    Args:
        table_id (str): รหัสโต๊ะที่สั่ง
        items (list): รายการอาหาร เช่น [{"menu_id": "M001", "quantity": 2, "note": "ไม่เผ็ด"}, ...]
            note เป็นฟิลด์ optional (สตริงหมายเหตุ/ความต้องการพิเศษ) ไม่ใส่มาก็ได้ ค่าเริ่มต้นเป็นสตริงว่าง
        created_by (str): ผู้สร้างออเดอร์ (username หรือ role) เพื่อบันทึกไว้อ้างอิง

    Returns:
        tuple(bool, dict | str): (สถานะความสำเร็จ, ข้อมูลออเดอร์ที่สร้าง หรือข้อความ error)
    """
    try:
        if not isinstance(table_id, str) or table_id.strip() == "":
            return False, "กรุณาระบุโต๊ะให้ถูกต้อง"

        if not isinstance(items, list) or len(items) == 0:
            return False, "กรุณาเลือกรายการอาหารอย่างน้อย 1 รายการ"

        # ตรวจสอบว่าโต๊ะมีอยู่จริง
        tables = get_all_tables()
        table_exists = any(t.get("table_id") == table_id for t in tables)
        if not table_exists:
            return False, "ไม่พบโต๊ะที่ระบุในระบบ"

        # ตรวจสอบสต็อกก่อนเสมอ (validation หลักของออเดอร์ - ยังไม่ตัดสต็อกจริงตรงนี้)
        is_enough, message = check_stock_for_order(items)
        if not is_enough:
            return False, message

        # คำนวณราคารวม
        total_price = 0.0
        order_items_detail = []
        for item in items:
            menu_item = get_menu_by_id(item.get("menu_id"))
            quantity = item.get("quantity")
            if menu_item is None:
                return False, "พบรายการเมนูที่ไม่ถูกต้องระหว่างคำนวณราคา"

            price = menu_item.get("price", 0)
            if isinstance(price, bool) or not isinstance(price, (int, float)) or price < 0:
                return False, f"ราคาของเมนู '{menu_item.get('name')}' ไม่ถูกต้อง"

            subtotal = price * quantity
            total_price += subtotal

            # หมายเหตุ/ความต้องการพิเศษของลูกค้าต่อรายการ (optional) — รับเฉพาะสตริง, ตัดช่องว่างหัวท้าย,
            # จำกัดความยาวกันข้อความยาวเกินไปหลุดเข้าไปในระบบ
            raw_note = item.get("note", "")
            note = raw_note.strip() if isinstance(raw_note, str) else ""
            note = note[:200]

            order_items_detail.append({
                "menu_id": menu_item.get("menu_id"),
                "name": menu_item.get("name"),
                "quantity": quantity,
                "price": price,
                "subtotal": subtotal,
                "note": note,
            })

        # หมายเหตุสถาปัตยกรรม: การ "ตัดสต็อกจริง" ตามสูตรอาหารจะเกิดขึ้นตอน "เช็คบิล" เท่านั้น
        # (ดูฟังก์ชัน commit_stock_deduction / checkout_table) เพื่อไม่ให้ตัดสต็อกซ้ำสองรอบ
        # และสอดคล้องกับ requirement: "เมื่อกดเช็คบิลสำเร็จ ให้เรียกฟังก์ชันตัดสต็อกวัตถุดิบทันที"

        # บันทึกออเดอร์
        orders = read_json_file("orders")
        if orders is None:
            orders = []

        new_order = {
            "order_id": "ORD-" + uuid.uuid4().hex[:8].upper(),
            "table_id": table_id,
            "items": order_items_detail,
            "total_price": round(total_price, 2),
            "status": "รอดำเนินการ",
            "created_by": created_by,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "billed": False,
            "bill_id": None,
        }

        orders.append(new_order)
        save_success = write_json_file("orders", orders)
        if not save_success:
            return False, "บันทึกออเดอร์ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"

        return True, new_order
    except Exception:
        return False, "เกิดข้อผิดพลาดในการสร้างออเดอร์ กรุณาลองใหม่อีกครั้ง"


def get_orders_list(status_filter: str = None):
    """
    ดึงรายการออเดอร์ทั้งหมด สามารถกรองตามสถานะได้

    Args:
        status_filter (str | None): หากระบุ จะคืนเฉพาะออเดอร์ที่มีสถานะตรงกัน

    Returns:
        list: รายการออเดอร์ (list of dict) หรือ list ว่างหากเกิดข้อผิดพลาด
    """
    try:
        orders = read_json_file("orders")
        if orders is None:
            return []
        if status_filter:
            if not isinstance(status_filter, str):
                return []
            return [o for o in orders if o.get("status") == status_filter]
        return orders
    except Exception:
        return []


def update_order_status(order_id: str, new_status: str) -> tuple:
    """
    อัปเดตสถานะออเดอร์ (เช่น 'รอดำเนินการ', 'กำลังปรุง', 'เสิร์ฟแล้ว', 'ยกเลิก')

    Args:
        order_id (str): รหัสออเดอร์
        new_status (str): สถานะใหม่

    Returns:
        tuple(bool, str): (สถานะความสำเร็จ, ข้อความแจ้งผลลัพธ์)
    """
    try:
        allowed_status = ["รอดำเนินการ", "กำลังปรุง", "เสิร์ฟแล้ว", "ยกเลิก"]

        if not isinstance(order_id, str) or order_id.strip() == "":
            return False, "รหัสออเดอร์ไม่ถูกต้อง"

        if not isinstance(new_status, str) or new_status not in allowed_status:
            return False, "สถานะออเดอร์ไม่ถูกต้อง"

        orders = read_json_file("orders")
        if not orders:
            return False, "ไม่พบข้อมูลออเดอร์ในระบบ"

        found = False
        for order in orders:
            if order.get("order_id") == order_id:
                order["status"] = new_status
                found = True
                break

        if not found:
            return False, "ไม่พบออเดอร์นี้ในระบบ"

        success = write_json_file("orders", orders)
        if not success:
            return False, "บันทึกสถานะออเดอร์ไม่สำเร็จ"

        return True, "อัปเดตสถานะออเดอร์สำเร็จ"
    except Exception:
        return False, "เกิดข้อผิดพลาดในการอัปเดตสถานะออเดอร์"


# ---------------------------------------------------------------------------
# 8) ฟังก์ชันสำหรับ Kitchen Display
# ---------------------------------------------------------------------------

def get_active_orders_sorted() -> list:
    """
    ดึงออเดอร์ทั้งหมดเรียงตามลำดับเวลาที่สั่ง (เก่าสุดก่อน) สำหรับหน้า Kitchen Display
    เรียงโดยใช้ created_at ป้องกันกรณีข้อมูลเสียหาย/รูปแบบวันที่ผิดด้วยการจับ error รายรายการ

    Returns:
        list: รายการออเดอร์ทั้งหมด เรียงจากเก่าไปใหม่ หรือ list ว่างหากเกิดข้อผิดพลาด
    """
    try:
        orders = get_orders_list()
        if not orders:
            return []

        def _sort_key(order):
            try:
                return datetime.strptime(order.get("created_at", ""), "%Y-%m-%d %H:%M:%S")
            except Exception:
                return datetime.min

        return sorted(orders, key=_sort_key)
    except Exception:
        return []


ORDER_STATUS_FLOW = {
    "รอดำเนินการ": "กำลังปรุง",
    "กำลังปรุง": "เสิร์ฟแล้ว",
}


def advance_order_status(order_id: str) -> tuple:
    """
    เลื่อนสถานะออเดอร์ไปขั้นถัดไปตามลำดับที่กำหนดไว้ (รอดำเนินการ -> กำลังปรุง -> เสิร์ฟแล้ว)
    ไม่รับสถานะที่พิมพ์เองจาก client โดยตรง เพื่อกันการส่งค่าสถานะที่ผิดเงื่อนไข

    Args:
        order_id (str): รหัสออเดอร์

    Returns:
        tuple(bool, str): (สถานะความสำเร็จ, ข้อความแจ้งผลลัพธ์)
    """
    try:
        if not isinstance(order_id, str) or order_id.strip() == "":
            return False, "รหัสออเดอร์ไม่ถูกต้อง"

        orders = read_json_file("orders")
        if not orders:
            return False, "ไม่พบข้อมูลออเดอร์ในระบบ"

        target_order = next((o for o in orders if o.get("order_id") == order_id), None)
        if target_order is None:
            return False, "ไม่พบออเดอร์นี้ในระบบ"

        current_status = target_order.get("status")
        next_status = ORDER_STATUS_FLOW.get(current_status)

        if next_status is None:
            return False, f"ออเดอร์นี้อยู่ในสถานะ '{current_status}' ไม่สามารถเลื่อนสถานะต่อได้"

        return update_order_status(order_id, next_status)
    except Exception:
        return False, "เกิดข้อผิดพลาดในการเลื่อนสถานะออเดอร์"


def cancel_order(order_id: str) -> tuple:
    """
    ยกเลิกออเดอร์ (ทำได้เฉพาะออเดอร์ที่ยังไม่เสิร์ฟและยังไม่ถูกเช็คบิลเท่านั้น)
    เนื่องจากยังไม่มีการตัดสต็อกจริงตอนสั่ง (จะตัดตอนเช็คบิล) การยกเลิกจึงไม่ต้องคืนสต็อก

    Args:
        order_id (str): รหัสออเดอร์

    Returns:
        tuple(bool, str): (สถานะความสำเร็จ, ข้อความแจ้งผลลัพธ์)
    """
    try:
        if not isinstance(order_id, str) or order_id.strip() == "":
            return False, "รหัสออเดอร์ไม่ถูกต้อง"

        orders = read_json_file("orders")
        if not orders:
            return False, "ไม่พบข้อมูลออเดอร์ในระบบ"

        target_order = next((o for o in orders if o.get("order_id") == order_id), None)
        if target_order is None:
            return False, "ไม่พบออเดอร์นี้ในระบบ"

        if target_order.get("billed", False):
            return False, "ออเดอร์นี้ถูกเช็คบิลไปแล้ว ไม่สามารถยกเลิกได้"

        if target_order.get("status") == "เสิร์ฟแล้ว":
            return False, "ออเดอร์นี้เสิร์ฟไปแล้ว ไม่สามารถยกเลิกได้"

        return update_order_status(order_id, "ยกเลิก")
    except Exception:
        return False, "เกิดข้อผิดพลาดในการยกเลิกออเดอร์"


# ---------------------------------------------------------------------------
# 9) ฟังก์ชันเช็คบิล (คำนวณส่วนลด/ภาษี/ยอดรวม + ตัดสต็อกจริง + ปิดโต๊ะ)
# ---------------------------------------------------------------------------

def get_orders_for_table(table_id: str, exclude_billed: bool = True, exclude_cancelled: bool = True) -> list:
    """
    ดึงออเดอร์ทั้งหมดของโต๊ะที่ระบุ (ใช้ตอนคำนวณเช็คบิล)

    Args:
        table_id (str): รหัสโต๊ะ
        exclude_billed (bool): ตัดออเดอร์ที่ถูกเช็คบิลไปแล้วออก
        exclude_cancelled (bool): ตัดออเดอร์ที่ถูกยกเลิกออก

    Returns:
        list: รายการออเดอร์ของโต๊ะนี้ หรือ list ว่างหากเกิดข้อผิดพลาด
    """
    try:
        if not isinstance(table_id, str) or table_id.strip() == "":
            return []

        orders = read_json_file("orders")
        if not orders:
            return []

        result = []
        for order in orders:
            if order.get("table_id") != table_id:
                continue
            if exclude_cancelled and order.get("status") == "ยกเลิก":
                continue
            if exclude_billed and order.get("billed", False):
                continue
            result.append(order)
        return result
    except Exception:
        return []


def commit_stock_deduction(items: list, reference_id: str = "") -> dict:
    """
    ตัดสต็อกวัตถุดิบจริงตามสูตรอาหาร (ใช้ตอนเช็คบิลเท่านั้น)
    ต่างจาก deduct_stock_for_order ตรงที่ฟังก์ชันนี้ "ไม่บล็อก" แม้สต็อกจะไม่พอ
    หากตัดแล้วยอดติดลบ จะปล่อยให้ติดลบจริงในไฟล์ inventory.json และบันทึก log แจ้งเตือนไว้
    (ตามกฎ: หากยอดสต็อกติดลบให้บันทึก log ไว้ ไม่ใช่บล็อกการเช็คบิล)

    Args:
        items (list): [{"menu_id": .., "quantity": ..}, ...] ที่รวมทุกออเดอร์ในบิลนี้แล้ว
        reference_id (str): รหัสอ้างอิง (เช่น bill_id) เก็บไว้ใน log เพื่อสืบย้อนภายหลัง

    Returns:
        dict: {
            "deductions": [{"ingredient_id","name","unit","qty_deducted","before_qty","after_qty"}, ...]
                          รายการวัตถุดิบทุกตัวที่ถูกตัดจริงจากบิลนี้ (ใช้ทำรายงานย้อนหลัง),
            "warnings": [{"ingredient_id","name","resulting_qty","unit"}, ...]
                        เฉพาะรายการที่ตัดแล้วสต็อกติดลบ
        }
        คืนค่า {"deductions": [], "warnings": []} หากไม่มีอะไรถูกตัด หรือเกิดข้อผิดพลาดระหว่างประมวลผล
    """
    try:
        if not isinstance(items, list):
            return {"deductions": [], "warnings": []}

        # รวมยอดวัตถุดิบที่ต้องใช้ทั้งหมดจากทุกเมนูในบิลนี้ก่อน
        required_qty = {}
        for item in items:
            if not isinstance(item, dict):
                continue

            menu_id = item.get("menu_id")
            quantity = item.get("quantity")

            if not isinstance(menu_id, str) or menu_id.strip() == "":
                continue
            if isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or quantity <= 0:
                continue

            menu_item = get_menu_by_id(menu_id)
            if menu_item is None:
                continue

            for r in menu_item.get("recipe", []):
                ing_id = r.get("ingredient_id")
                qty_used_per_unit = r.get("qty_used", 0)
                if not isinstance(qty_used_per_unit, (int, float)) or isinstance(qty_used_per_unit, bool):
                    continue
                required_qty[ing_id] = required_qty.get(ing_id, 0) + (qty_used_per_unit * quantity)

        inventory = get_inventory_list()
        deductions = []
        warnings = []
        logger = _get_stock_logger()

        for ing in inventory:
            ing_id = ing.get("ingredient_id")
            if ing_id not in required_qty:
                continue

            before_qty = ing.get("stock_qty", 0)
            if isinstance(before_qty, bool) or not isinstance(before_qty, (int, float)):
                before_qty = 0

            after_qty = round(before_qty - required_qty[ing_id], 4)
            ing["stock_qty"] = after_qty

            deductions.append({
                "ingredient_id": ing_id,
                "name": ing.get("name"),
                "unit": ing.get("unit"),
                "qty_deducted": round(required_qty[ing_id], 4),
                "before_qty": before_qty,
                "after_qty": after_qty,
            })

            if after_qty < 0:
                warnings.append({
                    "ingredient_id": ing_id,
                    "name": ing.get("name"),
                    "resulting_qty": after_qty,
                    "unit": ing.get("unit"),
                })
                if logger is not None:
                    try:
                        logger.warning(
                            "สต็อกติดลบหลังเช็คบิล | อ้างอิง=%s | วัตถุดิบ=%s (%s) | คงเหลือ=%.3f %s",
                            reference_id, ing.get("name"), ing_id, after_qty, ing.get("unit"),
                        )
                    except Exception:
                        pass

        write_json_file("inventory", inventory)
        return {"deductions": deductions, "warnings": warnings}
    except Exception:
        return {"deductions": [], "warnings": []}


def calculate_bill(table_id: str, discount_percent=0, tax_percent=7) -> tuple:
    """
    คำนวณยอดเช็คบิลของโต๊ะ: รวมยอดทุกออเดอร์ที่ยังไม่เช็คบิล -> หักส่วนลด -> บวกภาษี
    ใช้ Decimal ในการคำนวณเงินทั้งหมด เพื่อความแม่นยำ (ป้องกันปัญหาทศนิยมของ float)

    Args:
        table_id (str): รหัสโต๊ะ
        discount_percent (int|float): เปอร์เซ็นต์ส่วนลด ต้องอยู่ระหว่าง 0-100
        tax_percent (int|float): เปอร์เซ็นต์ภาษี ต้องอยู่ระหว่าง 0-100

    Returns:
        tuple(bool, dict|str): (สถานะความสำเร็จ, ข้อมูลบิลที่คำนวณแล้ว หรือข้อความ error)
    """
    try:
        if not isinstance(table_id, str) or table_id.strip() == "":
            return False, "รหัสโต๊ะไม่ถูกต้อง"

        if isinstance(discount_percent, bool) or not isinstance(discount_percent, (int, float)):
            return False, "ส่วนลดต้องเป็นตัวเลขเท่านั้น"
        if isinstance(tax_percent, bool) or not isinstance(tax_percent, (int, float)):
            return False, "ภาษีต้องเป็นตัวเลขเท่านั้น"

        if discount_percent < 0 or discount_percent > 100:
            return False, "ส่วนลดต้องอยู่ระหว่าง 0 ถึง 100 เปอร์เซ็นต์เท่านั้น"
        if tax_percent < 0 or tax_percent > 100:
            return False, "ภาษีต้องอยู่ระหว่าง 0 ถึง 100 เปอร์เซ็นต์เท่านั้น"

        orders = get_orders_for_table(table_id, exclude_billed=True, exclude_cancelled=True)
        if not orders:
            return False, "ไม่มีออเดอร์ที่ต้องชำระสำหรับโต๊ะนี้ (อาจเช็คบิลไปแล้ว หรือยังไม่มีการสั่งอาหาร)"

        subtotal = Decimal("0")
        for order in orders:
            price = order.get("total_price", 0)
            if isinstance(price, bool) or not isinstance(price, (int, float)):
                continue
            subtotal += Decimal(str(price))

        two_places = Decimal("0.01")
        discount_amount = (subtotal * Decimal(str(discount_percent)) / Decimal("100")).quantize(
            two_places, rounding=ROUND_HALF_UP
        )
        after_discount = subtotal - discount_amount
        tax_amount = (after_discount * Decimal(str(tax_percent)) / Decimal("100")).quantize(
            two_places, rounding=ROUND_HALF_UP
        )
        grand_total = (after_discount + tax_amount).quantize(two_places, rounding=ROUND_HALF_UP)

        return True, {
            "table_id": table_id,
            "orders": orders,
            "subtotal": float(subtotal.quantize(two_places, rounding=ROUND_HALF_UP)),
            "discount_percent": discount_percent,
            "discount_amount": float(discount_amount),
            "tax_percent": tax_percent,
            "tax_amount": float(tax_amount),
            "grand_total": float(grand_total),
        }
    except Exception:
        return False, "เกิดข้อผิดพลาดในการคำนวณบิล กรุณาลองใหม่อีกครั้ง"


def checkout_table(table_id: str, discount_percent, tax_percent, staff_username: str) -> tuple:
    """
    เช็คบิลโต๊ะ: คำนวณยอด -> ตัดสต็อกวัตถุดิบตามสูตรอาหารทันที (จุดสำคัญตามกฎเหล็ก) ->
    บันทึกบิลลง bills.json -> ปิดโต๊ะกลับเป็น 'ว่าง'

    Args:
        table_id (str): รหัสโต๊ะที่จะเช็คบิล
        discount_percent (int|float): เปอร์เซ็นต์ส่วนลด
        tax_percent (int|float): เปอร์เซ็นต์ภาษี
        staff_username (str): พนักงานที่ทำรายการเช็คบิล

    Returns:
        tuple(bool, dict|str): (สถานะความสำเร็จ, ข้อมูลบิลฉบับสมบูรณ์ หรือข้อความ error)
    """
    try:
        success, bill_calc = calculate_bill(table_id, discount_percent, tax_percent)
        if not success:
            return False, bill_calc

        orders = bill_calc["orders"]

        # รวมจำนวนวัตถุดิบจากทุกออเดอร์ของบิลนี้ เพื่อตัดสต็อกครั้งเดียวให้ถูกต้องตามสูตรอาหาร
        # และเก็บรายการอาหารแบบละเอียด (bill_items) ไว้ในบิลโดยตรง เพื่อให้ดูประวัติย้อนหลังได้
        # แม้ในอนาคตข้อมูลใน orders.json จะถูกเปลี่ยนแปลงหรือลบไป
        aggregated_items = {}
        bill_items = []
        for order in orders:
            for order_item in order.get("items", []):
                menu_id = order_item.get("menu_id")
                qty = order_item.get("quantity", 0)
                if not isinstance(menu_id, str):
                    continue
                if isinstance(qty, bool) or not isinstance(qty, (int, float)):
                    continue
                aggregated_items[menu_id] = aggregated_items.get(menu_id, 0) + qty

                bill_items.append({
                    "menu_id": menu_id,
                    "name": order_item.get("name", menu_id),
                    "quantity": qty,
                    "price": order_item.get("price", 0),
                    "subtotal": order_item.get("subtotal", 0),
                    "note": order_item.get("note", ""),
                    "order_id": order.get("order_id"),
                })

        items_for_deduction = [{"menu_id": mid, "quantity": qty} for mid, qty in aggregated_items.items()]

        bill_id = "BILL-" + uuid.uuid4().hex[:8].upper()

        # *** จุดสำคัญตามกฎเหล็ก: ตัดสต็อกวัตถุดิบตามสูตรอาหารทันทีเมื่อเช็คบิลสำเร็จ ***
        stock_result = commit_stock_deduction(items_for_deduction, reference_id=bill_id)
        stock_deductions = stock_result.get("deductions", [])
        stock_warnings = stock_result.get("warnings", [])

        # ทำเครื่องหมายว่าออเดอร์เหล่านี้ถูกเช็คบิลแล้ว (กันสั่งซ้ำ/เช็คบิลซ้ำ)
        all_orders = read_json_file("orders")
        if all_orders is None:
            all_orders = []
        billed_order_ids = {o.get("order_id") for o in orders}
        for order in all_orders:
            if order.get("order_id") in billed_order_ids:
                order["billed"] = True
                order["bill_id"] = bill_id

        if not write_json_file("orders", all_orders):
            return False, "บันทึกสถานะออเดอร์หลังเช็คบิลไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"

        # บันทึกบิลลง bills.json
        table_info = next((t for t in get_all_tables() if t.get("table_id") == table_id), {})
        bill_record = {
            "bill_id": bill_id,
            "table_id": table_id,
            "table_name": table_info.get("table_name", table_id),
            "order_ids": list(billed_order_ids),
            "items": bill_items,
            "subtotal": bill_calc["subtotal"],
            "discount_percent": bill_calc["discount_percent"],
            "discount_amount": bill_calc["discount_amount"],
            "tax_percent": bill_calc["tax_percent"],
            "tax_amount": bill_calc["tax_amount"],
            "grand_total": bill_calc["grand_total"],
            "stock_deductions": stock_deductions,
            "stock_warnings": stock_warnings,
            "checked_out_by": staff_username,
            "checked_out_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        bills = read_json_file("bills")
        if bills is None:
            bills = []
        bills.append(bill_record)
        if not write_json_file("bills", bills):
            return False, "บันทึกข้อมูลบิลไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"

        # ปิดโต๊ะกลับเป็น 'ว่าง' ตามกฎเหล็ก (หลังตัดสต็อกและบันทึกบิลสำเร็จแล้วเท่านั้น)
        close_success, close_message = close_table(table_id)
        if not close_success:
            bill_record["close_table_warning"] = close_message

        return True, bill_record
    except Exception:
        return False, "เกิดข้อผิดพลาดในการเช็คบิล กรุณาลองใหม่อีกครั้ง"


# ---------------------------------------------------------------------------
# 8) ฟังก์ชันเกี่ยวกับประวัติบิล / รายงานการขายเชิงลึก (Sales History & Reports)
# ---------------------------------------------------------------------------

def get_all_bills() -> list:
    """
    ดึงประวัติบิลทั้งหมดที่เช็คบิลสำเร็จแล้ว เรียงจากล่าสุดไปเก่าสุด (สำหรับ Admin)

    Returns:
        list: รายการบิล (list of dict) เรียงจาก checked_out_at ล่าสุดไปเก่าสุด
              คืนค่า list ว่างหากไม่มีบิล หรือเกิดข้อผิดพลาดระหว่างประมวลผล
    """
    try:
        bills = read_json_file("bills")
        if not bills:
            return []

        def _sort_key(b):
            checked_out_at = b.get("checked_out_at", "")
            return checked_out_at if isinstance(checked_out_at, str) else ""

        return sorted(bills, key=_sort_key, reverse=True)
    except Exception:
        return []


def get_bill_detail(bill_id: str):
    """
    ดึงรายละเอียดเชิงลึกของบิลเดียว ตาม bill_id ที่ระบุ
    ใช้สำหรับหน้า "รายละเอียดบิลรายรายการ" ของ Admin

    Args:
        bill_id (str): รหัสบิลที่ต้องการดูรายละเอียด

    Returns:
        dict | None: ข้อมูลบิลฉบับเต็ม (รวมรายการอาหาร, ยอดเงิน, รายงานการตัดสต็อก)
                     คืนค่า None หากไม่พบบิลนี้ หรือเกิดข้อผิดพลาดระหว่างประมวลผล
    """
    try:
        if not isinstance(bill_id, str) or bill_id.strip() == "":
            return None

        bills = read_json_file("bills")
        if not bills:
            return None

        for b in bills:
            if b.get("bill_id") == bill_id:
                return b
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 9) ฟังก์ชันเกี่ยวกับการตั้งค่าร้าน (Restaurant Settings)
# ---------------------------------------------------------------------------

def get_restaurant_settings() -> dict:
    """
    ดึงค่าการตั้งค่าร้าน (ปัจจุบันมีเฉพาะชื่อร้าน) จาก settings.json

    หากไฟล์ยังไม่มีอยู่จริง อ่านไม่สำเร็จ หรือค่าที่เก็บไว้ผิดรูปแบบ
    จะคืนค่าเริ่มต้นเสมอ (ห้ามให้หน้าเว็บพังเพราะขาดไฟล์การตั้งค่านี้)

    Returns:
        dict: {"restaurant_name": str} คืนค่า DEFAULT_RESTAURANT_NAME หากยังไม่เคยตั้งค่า
    """
    try:
        settings = read_json_file("settings")
        if not isinstance(settings, dict):
            settings = {}

        restaurant_name = settings.get("restaurant_name")
        if not isinstance(restaurant_name, str) or restaurant_name.strip() == "":
            restaurant_name = DEFAULT_RESTAURANT_NAME

        return {"restaurant_name": restaurant_name}
    except Exception:
        return {"restaurant_name": DEFAULT_RESTAURANT_NAME}


def update_restaurant_settings(restaurant_name: str) -> tuple:
    """
    บันทึกชื่อร้านใหม่ลงใน settings.json อย่างปลอดภัย (เขียนไฟล์ชั่วคราวก่อนแล้วค่อย replace
    ผ่าน write_json_file เพื่อลดโอกาสไฟล์เสียหายระหว่างเขียน)

    Args:
        restaurant_name (str): ชื่อร้านใหม่ ห้ามเป็นค่าว่างหรือมีแต่ช่องว่าง

    Returns:
        tuple(bool, str): (สถานะความสำเร็จ, ข้อความแจ้งผลลัพธ์ที่อ่านง่าย)
    """
    try:
        if not isinstance(restaurant_name, str):
            return False, "ชื่อร้านต้องเป็นข้อความเท่านั้น"

        cleaned_name = restaurant_name.strip()
        if cleaned_name == "":
            return False, "กรุณากรอกชื่อร้าน ห้ามเว้นว่าง"

        if len(cleaned_name) > 100:
            return False, "ชื่อร้านต้องมีความยาวไม่เกิน 100 ตัวอักษร"

        settings = read_json_file("settings")
        if not isinstance(settings, dict):
            settings = {}
        settings["restaurant_name"] = cleaned_name

        if not write_json_file("settings", settings):
            return False, "บันทึกชื่อร้านไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"

        return True, "บันทึกชื่อร้านสำเร็จ"
    except Exception:
        return False, "เกิดข้อผิดพลาดในการบันทึกชื่อร้าน กรุณาลองใหม่อีกครั้ง"


# เตรียมไฟล์ข้อมูลให้พร้อมทันทีที่โมดูลนี้ถูก import ครั้งแรก
init_data_files()