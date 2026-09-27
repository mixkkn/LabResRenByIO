"""
app.py
------
ไฟล์หลักของเว็บแอป Flask: ระบบจัดการร้านอาหารและสต็อกสินค้า

ส่วนที่ทำในไฟล์นี้ (ตามที่สั่งงาน):
1. ระบบ Login แบบแบ่งสิทธิ์ (Role-based): admin / staff / customer
2. Staff เปิดโต๊ะ -> ระบบสุ่ม PIN 4 หลัก และเปลี่ยนสถานะโต๊ะเป็น 'มีลูกค้า'
3. Customer login ด้วย PIN 4 หลักเพื่อเข้าสู่โต๊ะของตัวเอง
4. ป้องกัน Customer ไม่ให้เข้าหน้า Admin/Staff ด้วยการเช็คสิทธิ์ฝั่ง Server (decorator)

หมายเหตุ: ตรรกะการจัดการข้อมูลทั้งหมดอยู่ใน db.py
ไฟล์นี้ทำหน้าที่เป็นชั้น Route/Controller เท่านั้น
"""

from functools import wraps
import json
import os
import io
import uuid

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    abort,
)
from werkzeug.exceptions import HTTPException
from PIL import Image
import cloudinary
import cloudinary.uploader

import db

app = Flask(__name__)
# NOTE: โปรเจคจริงควรอ่านค่านี้จาก environment variable ไม่ควร hardcode ไว้ในโค้ด
app.secret_key = "restaurant-system-dev-secret-key-change-me"

MENU_PAGE_SIZE = 6  # จำนวนเมนูต่อหน้าในหน้าสั่งอาหารของลูกค้า
MAX_QTY_PER_ITEM = 50  # จำกัดจำนวนสูงสุดต่อเมนู กันการสั่งจำนวนผิดปกติ

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # จำกัดขนาดไฟล์ที่อัปโหลดไว้ที่ 5MB

# ตั้งค่า Cloudinary (แนะนำให้เปลี่ยนเป็นค่าจริงจากบัญชี Cloudinary ของคุณ)
cloudinary.config(
    cloud_name = "pmbes3y7",
    api_key = "123376446413482",
    api_secret = "YMHgO5bUeBm-GrVK8xwfhFYSZ4w"
)


def _validate_and_save_image(file_storage):
    """
    ตรวจสอบไฟล์รูปภาพและอัปโหลดขึ้น Cloudinary โดยตรง (แก้ปัญหา Read-Only บน Vercel)
    """
    try:
        if file_storage is None or not getattr(file_storage, "filename", ""):
            return True, None

        original_name = file_storage.filename.strip()
        if original_name == "":
            return True, None

        if "." not in original_name:
            return False, "ไฟล์รูปภาพต้องมีนามสกุลไฟล์ (เช่น .jpg, .png)"

        ext = original_name.rsplit(".", 1)[1].lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            return False, f"รองรับเฉพาะไฟล์นามสกุล {', '.join(sorted(ALLOWED_IMAGE_EXTENSIONS))} เท่านั้น"

        file_bytes = file_storage.read()
        file_storage.seek(0)

        if len(file_bytes) == 0:
            return False, "ไฟล์รูปภาพว่างเปล่า กรุณาเลือกไฟล์ใหม่"

        # ยืนยันว่าเป็นไฟล์รูปภาพจริง ไม่ใช่ไฟล์อื่นที่แค่เปลี่ยนนามสกุลมาหลอก
        try:
            img = Image.open(io.BytesIO(file_bytes))
            img.verify()
        except Exception:
            return False, "ไฟล์ที่อัปโหลดไม่ใช่ไฟล์รูปภาพที่ถูกต้อง (นามสกุลไฟล์อาจถูกปลอมแปลง)"

        # อัปโหลดขึ้น Cloudinary แทนการเซฟลงดิสก์เครื่อง
        upload_result = cloudinary.uploader.upload(file_bytes, folder="restaurant_menu")
        secure_url = upload_result.get("secure_url")

        return True, secure_url
    except Exception:
        return False, "เกิดข้อผิดพลาดในการอัปโหลดรูปภาพขึ้นคลาวด์ กรุณาลองใหม่อีกครั้ง"


def _delete_image_file(filename):
    """จัดการลบรูปภาพ (หากใช้ Cloudinary จะอาศัยการจัดการผ่าน Cloud แพลตฟอร์ม)"""
    pass


# ---------------------------------------------------------------------------
# Decorator สำหรับตรวจสอบสิทธิ์ (Role-based access control) ฝั่ง Server
# ---------------------------------------------------------------------------

def login_required(allowed_roles=None):
    """
    Decorator สำหรับบังคับให้ต้อง login ก่อนเข้าถึง route
    และเช็ค role ฝั่ง server เสมอ (ไม่เชื่อค่าที่ client ส่งมา)

    Args:
        allowed_roles (list | None): รายชื่อ role ที่อนุญาตให้เข้าถึง route นี้
                                      หากเป็น None แปลว่าแค่ login แล้วก็เข้าได้ทุก role

    Returns:
        function: ฟังก์ชัน decorator ที่ครอบ route handler อีกที
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(*args, **kwargs):
            try:
                current_role = session.get("role")

                if not current_role:
                    flash("กรุณาเข้าสู่ระบบก่อนใช้งานส่วนนี้", "error")
                    return redirect(url_for("index"))

                if allowed_roles is not None and current_role not in allowed_roles:
                    # Customer หรือ role อื่นพยายามเข้าหน้าที่ไม่มีสิทธิ์ -> บล็อกฝั่ง server ทันที
                    abort(403)

                return view_func(*args, **kwargs)
            except HTTPException:
                # ปล่อยให้ abort(403)/404 ฯลฯ ทำงานตามปกติ ไม่ใช่ error ที่ต้อง catch
                raise
            except Exception:
                flash("เกิดข้อผิดพลาดในการตรวจสอบสิทธิ์ กรุณาเข้าสู่ระบบใหม่อีกครั้ง", "error")
                session.clear()
                return redirect(url_for("index"))
        return wrapped_view
    return decorator


# ---------------------------------------------------------------------------
# หน้าแรก / เลือกช่องทางเข้าสู่ระบบ
# ---------------------------------------------------------------------------

@app.context_processor
def inject_restaurant_settings():
    """
    ฉีดชื่อร้านปัจจุบันเข้าไปในทุก Template โดยอัตโนมัติ (ใช้ใน base.html: navbar, title, footer)
    ทำงานทุกครั้งที่มีการ render_template โดยไม่ต้องส่ง restaurant_name ทีละ route
    """
    try:
        settings = db.get_restaurant_settings()
        return {"restaurant_name": settings.get("restaurant_name", db.DEFAULT_RESTAURANT_NAME)}
    except Exception:
        return {"restaurant_name": db.DEFAULT_RESTAURANT_NAME}


@app.route("/")
def index():
    """
    หน้าแรก: หากยัง login อยู่ ให้เด้งไปหน้า dashboard ตาม role โดยอัตโนมัติ
    หากยังไม่ login ให้แสดงหน้าเลือกช่องทางเข้าสู่ระบบ (พนักงาน / ลูกค้า)
    """
    try:
        role = session.get("role")
        if role == "admin":
            return redirect(url_for("admin_dashboard"))
        if role == "staff":
            return redirect(url_for("staff_dashboard"))
        if role == "customer":
            return redirect(url_for("customer_dashboard"))
        return render_template("index.html")
    except Exception:
        return render_template("index.html")


# ---------------------------------------------------------------------------
# Login: Staff / Admin (username + password)
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    """
    หน้า Login สำหรับ Staff และ Admin ด้วย username/password
    มี server-side validation: ห้ามส่งค่าว่าง, ตรวจสอบชนิดข้อมูลก่อนส่งเข้า db
    """
    if request.method == "GET":
        return render_template("login.html")

    try:
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        # Validation ฝั่ง server: ห้ามเป็นค่าว่างหรือมีแต่ช่องว่าง
        if not isinstance(username, str) or not isinstance(password, str):
            flash("รูปแบบข้อมูลไม่ถูกต้อง", "error")
            return render_template("login.html")

        if username.strip() == "" or password.strip() == "":
            flash("กรุณากรอกชื่อผู้ใช้และรหัสผ่านให้ครบถ้วน", "error")
            return render_template("login.html")

        user = db.authenticate_user(username.strip(), password)

        if user is None:
            flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง", "error")
            return render_template("login.html")

        if user.get("role") not in ("admin", "staff"):
            # กันไว้อีกชั้น เผื่อมีการเพิ่ม role แปลกๆ ในไฟล์ users.json ภายหลัง
            flash("บัญชีนี้ไม่มีสิทธิ์เข้าสู่ระบบส่วนนี้", "error")
            return render_template("login.html")

        # เก็บเฉพาะข้อมูลที่จำเป็นใน session และกำหนด role จากฝั่ง server เท่านั้น
        session.clear()
        session["role"] = user.get("role")
        session["username"] = user.get("username")
        session["user_id"] = user.get("user_id")
        session["full_name"] = user.get("full_name")

        flash(f"เข้าสู่ระบบสำเร็จ ยินดีต้อนรับคุณ {user.get('full_name')}", "success")

        if user.get("role") == "admin":
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("staff_dashboard"))

    except Exception:
        flash("เกิดข้อผิดพลาดระหว่างเข้าสู่ระบบ กรุณาลองใหม่อีกครั้ง", "error")
        return render_template("login.html")


# ---------------------------------------------------------------------------
# Login: Customer (PIN 4 หลัก)
# ---------------------------------------------------------------------------

@app.route("/customer/login", methods=["GET", "POST"])
def customer_login():
    """
    หน้า Login สำหรับ Customer โดยใช้ PIN 4 หลักที่ Staff สุ่มให้ตอนเปิดโต๊ะ
    Server-side validation: ต้องเป็นตัวเลขล้วน 4 หลักเท่านั้น ห้ามมีตัวอักษรปน
    """
    if request.method == "GET":
        return render_template("customer_login.html")

    try:
        pin = request.form.get("pin", "")

        if not isinstance(pin, str):
            flash("รูปแบบ PIN ไม่ถูกต้อง", "error")
            return render_template("customer_login.html")

        pin = pin.strip()

        if pin == "":
            flash("กรุณากรอกรหัส PIN", "error")
            return render_template("customer_login.html")

        if len(pin) != 4 or not pin.isdigit():
            flash("รหัส PIN ต้องเป็นตัวเลข 4 หลักเท่านั้น", "error")
            return render_template("customer_login.html")

        table = db.verify_table_pin(pin)

        if table is None:
            flash("รหัส PIN ไม่ถูกต้อง หรือโต๊ะนี้ยังไม่ได้เปิดใช้งาน", "error")
            return render_template("customer_login.html")

        session.clear()
        session["role"] = "customer"
        session["table_id"] = table.get("table_id")
        session["table_name"] = table.get("table_name")

        flash(f"เข้าสู่ระบบสำเร็จ สำหรับ {table.get('table_name')}", "success")
        return redirect(url_for("customer_dashboard"))

    except Exception:
        flash("เกิดข้อผิดพลาดระหว่างเข้าสู่ระบบ กรุณาลองใหม่อีกครั้ง", "error")
        return render_template("customer_login.html")


@app.route("/customer/qr-login/<table_id>")
def customer_qr_login(table_id):
    """
    Endpoint สำหรับลูกค้าสแกน QR Code ที่ติดอยู่บนโต๊ะเพื่อเข้าสู่ระบบทันที
    โดยไม่ต้องพิมพ์ PIN เอง

    สำคัญ: ต้องแนบ pin ปัจจุบันของโต๊ะมาทาง query string เสมอ (?pin=XXXX)
    แล้วตรวจสอบ table_id + pin คู่กันฝั่ง server เหมือน flow ของ customer_login
    ทุกประการ (ใช้ db.verify_table_pin ตัวเดิม ซึ่งเช็คสถานะ 'มีลูกค้า' อยู่แล้ว)
    ห้ามเชื่อ table_id เพียงอย่างเดียว เพราะเดาง่ายและจะเป็นช่องโหว่ให้สวมสิทธิ์โต๊ะอื่น
    """
    try:
        if not isinstance(table_id, str) or table_id.strip() == "":
            flash("ลิงก์ QR Code ไม่ถูกต้อง", "error")
            return redirect(url_for("customer_login"))

        pin = request.args.get("pin", "")
        if not isinstance(pin, str):
            pin = ""
        pin = pin.strip()

        if len(pin) != 4 or not pin.isdigit():
            flash("ลิงก์ QR Code ไม่ถูกต้องหรือหมดอายุแล้ว กรุณาสแกนใหม่หรือแจ้งพนักงาน", "error")
            return redirect(url_for("customer_login"))

        table = db.verify_table_pin(pin)

        # ต้องตรงกันทั้ง pin และ table_id ใน URL ป้องกันกรณี QR เก่า/PIN หลุดไปตรงกับโต๊ะอื่นพอดี
        if table is None or table.get("table_id") != table_id:
            flash("โต๊ะนี้ยังไม่ได้เปิดใช้งาน หรือลิงก์ QR Code หมดอายุแล้ว กรุณาติดต่อพนักงาน", "error")
            return redirect(url_for("customer_login"))

        session.clear()
        session["role"] = "customer"
        session["table_id"] = table.get("table_id")
        session["table_name"] = table.get("table_name")

        flash(f"เข้าสู่ระบบสำเร็จผ่าน QR Code สำหรับ {table.get('table_name')}", "success")
        return redirect(url_for("customer_dashboard"))

    except Exception:
        flash("เกิดข้อผิดพลาดระหว่างเข้าสู่ระบบผ่าน QR Code กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("customer_login"))


@app.route("/logout")
def logout():
    """ล้าง session ทั้งหมดและกลับไปหน้าแรก (ใช้ได้ทุก role)"""
    session.clear()
    flash("ออกจากระบบเรียบร้อยแล้ว", "success")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Staff: เปิดโต๊ะ + สุ่ม PIN
# ---------------------------------------------------------------------------

@app.route("/staff/dashboard")
@login_required(allowed_roles=["staff", "admin"])
def staff_dashboard():
    """แสดงรายการโต๊ะทั้งหมด พร้อมสถานะและปุ่มเปิดโต๊ะ (เฉพาะ staff/admin)"""
    tables = db.get_all_tables()
    return render_template("staff_dashboard.html", tables=tables)


@app.route("/staff/tables/add", methods=["POST"])
@login_required(allowed_roles=["staff", "admin"])
def staff_add_table():
    """
    เพิ่มโต๊ะใหม่เข้าระบบ (staff/admin เท่านั้น)
    ระบบสร้าง table_id ให้อัตโนมัติใน db.add_table() ฝั่งนี้ทำหน้าที่แค่รับ/ตรวจสอบชื่อโต๊ะจากฟอร์ม
    """
    try:
        table_name = request.form.get("table_name", "")

        if not isinstance(table_name, str) or table_name.strip() == "":
            flash("กรุณากรอกชื่อโต๊ะก่อนเพิ่ม", "error")
            return redirect(url_for("staff_dashboard"))

        staff_username = session.get("username", "unknown")
        success, result = db.add_table(table_name.strip(), created_by=staff_username)

        if not success:
            flash(result, "error")
        else:
            flash(f"เพิ่ม {result.get('table_name')} (รหัส {result.get('table_id')}) สำเร็จ", "success")

        return redirect(url_for("staff_dashboard"))
    except Exception:
        flash("เกิดข้อผิดพลาดในการเพิ่มโต๊ะ กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("staff_dashboard"))


@app.route("/staff/tables/<table_id>/open", methods=["POST"])
@login_required(allowed_roles=["staff", "admin"])
def staff_open_table(table_id):
    """
    เปิดโต๊ะ: เรียก db.open_table() เพื่อสุ่ม PIN และเปลี่ยนสถานะโต๊ะเป็น 'มีลูกค้า'
    รับ table_id จาก URL แต่ยืนยันสิทธิ์ผู้เปิดจาก session เท่านั้น (ห้ามเชื่อ client)
    """
    try:
        if not isinstance(table_id, str) or table_id.strip() == "":
            flash("รหัสโต๊ะไม่ถูกต้อง", "error")
            return redirect(url_for("staff_dashboard"))

        staff_username = session.get("username", "unknown")
        success, result = db.open_table(table_id, staff_username)

        if not success:
            flash(result, "error")
        else:
            flash(f"เปิด {result.get('table_name')} สำเร็จ! รหัส PIN สำหรับลูกค้าคือ: {result.get('pin')}", "success")

        return redirect(url_for("staff_dashboard"))
    except Exception:
        flash("เกิดข้อผิดพลาดในการเปิดโต๊ะ กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("staff_dashboard"))


@app.route("/staff/tables/<table_id>/close", methods=["POST"])
@login_required(allowed_roles=["staff", "admin"])
def staff_close_table(table_id):
    """ปิดโต๊ะ (ล้าง PIN, เปลี่ยนสถานะกลับเป็น 'ว่าง') หลังลูกค้าชำระเงินเสร็จ"""
    try:
        success, message = db.close_table(table_id)
        flash(message, "success" if success else "error")
        return redirect(url_for("staff_dashboard"))
    except Exception:
        flash("เกิดข้อผิดพลาดในการปิดโต๊ะ กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("staff_dashboard"))


@app.route("/staff/tables/<table_id>/delete", methods=["POST"])
@login_required(allowed_roles=["staff", "admin"])
def staff_delete_table(table_id):
    """
    ลบโต๊ะออกจากระบบถาวร (staff/admin เท่านั้น)
    db.delete_table() จะปฏิเสธการลบเองหากโต๊ะนั้นสถานะ 'มีลูกค้า' อยู่ (ต้องปิดโต๊ะก่อนเสมอ)
    """
    try:
        if not isinstance(table_id, str) or table_id.strip() == "":
            flash("รหัสโต๊ะไม่ถูกต้อง", "error")
            return redirect(url_for("staff_dashboard"))

        success, message = db.delete_table(table_id)
        flash(message, "success" if success else "error")
        return redirect(url_for("staff_dashboard"))
    except Exception:
        flash("เกิดข้อผิดพลาดในการลบโต๊ะ กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("staff_dashboard"))


# ---------------------------------------------------------------------------
# Staff: Kitchen Display - แสดงออเดอร์ตามลำดับเวลา + เลื่อน/ยกเลิกสถานะ
# ---------------------------------------------------------------------------

@app.route("/staff/kitchen")
@login_required(allowed_roles=["staff", "admin"])
def kitchen_display():
    """
    หน้า Kitchen Display: แสดงออเดอร์ทั้งหมดเรียงตามลำดับเวลาที่สั่ง (เก่าสุดก่อน)
    แยกกลุ่มออเดอร์ที่ยังทำงานอยู่ (รอดำเนินการ/กำลังปรุง) ออกจากที่จบแล้ว (เสิร์ฟแล้ว/ยกเลิก)
    """
    try:
        orders = db.get_active_orders_sorted()
        active_orders = [o for o in orders if o.get("status") in ("รอดำเนินการ", "กำลังปรุง")]
        finished_orders = [o for o in orders if o.get("status") in ("เสิร์ฟแล้ว", "ยกเลิก")]
        # แสดงออเดอร์ที่จบแล้วล่าสุดก่อน (กลับลำดับ) เพื่อดูประวัติล่าสุดได้ง่าย
        finished_orders = list(reversed(finished_orders))[:20]

        return render_template(
            "kitchen_display.html",
            active_orders=active_orders,
            finished_orders=finished_orders,
        )
    except Exception:
        flash("เกิดข้อผิดพลาดในการโหลดหน้าครัว กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("staff_dashboard"))


@app.route("/staff/kitchen/orders/<order_id>/advance", methods=["POST"])
@login_required(allowed_roles=["staff", "admin"])
def kitchen_advance_order(order_id):
    """เลื่อนสถานะออเดอร์ไปขั้นถัดไป (รอดำเนินการ -> กำลังปรุง -> เสิร์ฟแล้ว)"""
    try:
        success, message = db.advance_order_status(order_id)
        flash(message, "success" if success else "error")
        return redirect(url_for("kitchen_display"))
    except Exception:
        flash("เกิดข้อผิดพลาดในการเลื่อนสถานะออเดอร์ กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("kitchen_display"))


@app.route("/staff/kitchen/orders/<order_id>/cancel", methods=["POST"])
@login_required(allowed_roles=["staff", "admin"])
def kitchen_cancel_order(order_id):
    """ยกเลิกออเดอร์ (ทำได้เฉพาะออเดอร์ที่ยังไม่เสิร์ฟและยังไม่ถูกเช็คบิล)"""
    try:
        success, message = db.cancel_order(order_id)
        flash(message, "success" if success else "error")
        return redirect(url_for("kitchen_display"))
    except Exception:
        flash("เกิดข้อผิดพลาดในการยกเลิกออเดอร์ กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("kitchen_display"))


# ---------------------------------------------------------------------------
# Staff: ระบบเช็คบิล (คำนวณส่วนลด/ภาษี/ยอดรวม -> ตัดสต็อก -> ปิดโต๊ะ)
# ---------------------------------------------------------------------------

def _parse_percent_value(raw_value: str, field_name: str, default: float):
    """
    แปลงค่าที่กรอกมาจากฟอร์ม (string) ให้เป็นตัวเลขเปอร์เซ็นต์ที่ถูกต้อง (0-100)
    ห้ามให้ error ของ python หลุดออกไป และห้ามรับตัวอักษร/ค่าติดลบ/ค่าเกิน 100

    Returns:
        tuple(bool, float|str): (ผ่าน validation หรือไม่, ค่าตัวเลข หรือข้อความ error)
    """
    try:
        if raw_value is None or str(raw_value).strip() == "":
            return True, default

        text = str(raw_value).strip()
        # อนุญาตเฉพาะตัวเลขและจุดทศนิยมเท่านั้น (ป้องกันตัวอักษร/สัญลักษณ์แปลกปลอม)
        value = float(text)

        if value != value:  # NaN check
            return False, f"{field_name}ไม่ถูกต้อง"
        if value < 0 or value > 100:
            return False, f"{field_name}ต้องอยู่ระหว่าง 0 ถึง 100 เปอร์เซ็นต์เท่านั้น"

        return True, value
    except (ValueError, TypeError):
        return False, f"{field_name}ต้องเป็นตัวเลขเท่านั้น ห้ามมีตัวอักษรหรือสัญลักษณ์ปน"
    except Exception:
        return False, f"เกิดข้อผิดพลาดในการตรวจสอบ{field_name}"


@app.route("/staff/tables/<table_id>/checkout", methods=["GET"])
@login_required(allowed_roles=["staff", "admin"])
def checkout_preview(table_id):
    """
    หน้าพรีวิวเช็คบิล: แสดงรายการออเดอร์ทั้งหมดของโต๊ะ พร้อมช่องกรอกส่วนลด/ภาษี
    เพื่อดูยอดที่คำนวณแล้วก่อนกดยืนยันจริง (ยังไม่ตัดสต็อกในขั้นตอนนี้)
    """
    try:
        # อ่านค่า preview จาก query string (ถ้ามี) เพื่อให้ปรับส่วนลด/ภาษีแล้วเห็นยอดใหม่ได้ทันที
        discount_ok, discount_value = _parse_percent_value(request.args.get("discount"), "ส่วนลด", 0)
        tax_ok, tax_value = _parse_percent_value(request.args.get("tax"), "ภาษี", 7)

        if not discount_ok:
            flash(discount_value, "error")
            discount_value = 0
        if not tax_ok:
            flash(tax_value, "error")
            tax_value = 7

        success, bill_calc = db.calculate_bill(table_id, discount_value, tax_value)

        if not success:
            flash(bill_calc, "error")
            return redirect(url_for("staff_dashboard"))

        return render_template("checkout.html", bill=bill_calc, table_id=table_id)
    except Exception:
        flash("เกิดข้อผิดพลาดในการโหลดหน้าเช็คบิล กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("staff_dashboard"))


@app.route("/staff/tables/<table_id>/checkout", methods=["POST"])
@login_required(allowed_roles=["staff", "admin"])
def checkout_confirm(table_id):
    """
    ยืนยันเช็คบิลจริง: validate ส่วนลด/ภาษีอีกครั้งฝั่ง server (ห้ามเชื่อค่าจากฟอร์มเดิม)
    แล้วเรียก db.checkout_table() ซึ่งจะตัดสต็อกตามสูตรอาหารทันทีและปิดโต๊ะ
    """
    try:
        discount_ok, discount_value = _parse_percent_value(request.form.get("discount"), "ส่วนลด", 0)
        if not discount_ok:
            flash(discount_value, "error")
            return redirect(url_for("checkout_preview", table_id=table_id))

        tax_ok, tax_value = _parse_percent_value(request.form.get("tax"), "ภาษี", 7)
        if not tax_ok:
            flash(tax_value, "error")
            return redirect(url_for("checkout_preview", table_id=table_id))

        staff_username = session.get("username", "unknown")
        success, result = db.checkout_table(table_id, discount_value, tax_value, staff_username)

        if not success:
            flash(result, "error")
            return redirect(url_for("staff_dashboard"))

        return render_template("receipt.html", bill=result)
    except Exception:
        flash("เกิดข้อผิดพลาดในการเช็คบิล กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("staff_dashboard"))


# ---------------------------------------------------------------------------
# Admin: หน้าควบคุมหลัก (Dashboard สรุปข้อมูล) เฉพาะ admin เท่านั้น
# ---------------------------------------------------------------------------

@app.route("/admin/dashboard")
@login_required(allowed_roles=["admin"])
def admin_dashboard():
    """
    หน้าสรุปสำหรับ Admin (หน้าเดียวจบ): ยอดขายรายวัน, เมนูขายดี,
    มูลค่าสต็อกคงเหลือ, และแจ้งเตือนวัตถุดิบที่ต่ำกว่าจุดสั่งซื้อเพิ่ม (reorder point)
    """
    try:
        tables = db.get_all_tables()
        inventory = db.get_inventory_list()
        daily_sales = db.get_daily_sales()
        best_sellers = db.get_best_selling_menu(limit=5)
        stock_value = db.get_stock_value()
        low_stock_alerts = db.get_low_stock_alerts()

        return render_template(
            "admin_dashboard.html",
            tables=tables,
            inventory=inventory,
            daily_sales=daily_sales,
            best_sellers=best_sellers,
            stock_value=stock_value,
            low_stock_alerts=low_stock_alerts,
        )
    except Exception:
        flash("เกิดข้อผิดพลาดในการโหลดหน้า Dashboard กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("index"))


@app.route("/admin/ingredients/<ingredient_id>/update", methods=["POST"])
@login_required(allowed_roles=["admin"])
def admin_ingredient_update(ingredient_id):
    """แก้ไขจำนวนสต็อกและจุดสั่งซื้อเพิ่ม (reorder point) ของวัตถุดิบจากหน้า Dashboard"""
    try:
        stock_raw = request.form.get("stock_qty", "")
        reorder_raw = request.form.get("reorder_point", "")

        try:
            stock_qty = float(stock_raw)
        except (ValueError, TypeError):
            flash("จำนวนสต็อกต้องเป็นตัวเลขเท่านั้น ห้ามกรอกตัวอักษร", "error")
            return redirect(url_for("admin_dashboard"))

        try:
            reorder_point = float(reorder_raw)
        except (ValueError, TypeError):
            flash("จุดสั่งซื้อเพิ่มต้องเป็นตัวเลขเท่านั้น ห้ามกรอกตัวอักษร", "error")
            return redirect(url_for("admin_dashboard"))

        admin_username = session.get("username", "unknown")
        success, message = db.update_ingredient_settings(ingredient_id, stock_qty, reorder_point, admin_username)
        flash(message, "success" if success else "error")
        return redirect(url_for("admin_dashboard"))
    except Exception:
        flash("เกิดข้อผิดพลาดในการอัปเดตวัตถุดิบ กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# Admin: ตั้งค่าร้าน (เปลี่ยนชื่อร้าน)
# ---------------------------------------------------------------------------

@app.route("/admin/settings", methods=["GET", "POST"])
@login_required(allowed_roles=["admin"])
def admin_settings():
    """
    หน้าตั้งค่าร้านสำหรับ Admin: ปัจจุบันรองรับการเปลี่ยน "ชื่อร้าน"
    GET: ดึงชื่อร้านปัจจุบันมาแสดงในฟอร์ม
    POST: ตรวจสอบค่าที่ส่งมา (ห้ามว่าง) แล้วบันทึกผ่าน db.update_restaurant_settings()
    """
    if request.method == "GET":
        try:
            settings = db.get_restaurant_settings()
            return render_template("admin_settings.html", settings=settings)
        except Exception:
            flash("เกิดข้อผิดพลาดในการโหลดหน้าตั้งค่าร้าน กรุณาลองใหม่อีกครั้ง", "error")
            return redirect(url_for("admin_dashboard"))

    try:
        restaurant_name = request.form.get("restaurant_name", "")

        if not isinstance(restaurant_name, str) or restaurant_name.strip() == "":
            flash("กรุณากรอกชื่อร้าน ห้ามเว้นว่าง", "error")
            return redirect(url_for("admin_settings"))

        success, message = db.update_restaurant_settings(restaurant_name)
        flash(message, "success" if success else "error")
        return redirect(url_for("admin_settings"))
    except Exception:
        flash("เกิดข้อผิดพลาดในการบันทึกชื่อร้าน กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("admin_settings"))


# ---------------------------------------------------------------------------
# Admin: CRUD จัดการเมนูอาหาร (เพิ่ม/แก้ไข/ลบ/เปลี่ยนสถานะ + อัปโหลดรูปภาพ)
# ---------------------------------------------------------------------------

@app.route("/admin/menu")
@login_required(allowed_roles=["admin", "staff"])
def admin_menu_list():
    """หน้ารายการเมนูทั้งหมดสำหรับ Admin (รวมเมนูที่ปิดขาย/อาหารหมดด้วย)"""
    try:
        menu = db.get_menu_list(only_available=False)
        return render_template("admin_menu_list.html", menu=menu)
    except Exception:
        flash("เกิดข้อผิดพลาดในการโหลดรายการเมนู กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("admin_dashboard"))


def _parse_recipe_and_price(form, files):
    """
    Helper รวมการอ่าน+validate เบื้องต้นของฟอร์มเมนู (ใช้ร่วมกันทั้งหน้าเพิ่ม/แก้ไข)
    คืนค่า (ok, data_dict_or_error_message)
    """
    name = form.get("name", "")
    price_raw = form.get("price", "")
    category = form.get("category", "")
    recipe_json = form.get("recipe_data", "[]")

    if not isinstance(price_raw, str) or price_raw.strip() == "":
        return False, "กรุณากรอกราคา"

    try:
        price = float(price_raw.strip())
    except ValueError:
        return False, "ราคาต้องเป็นตัวเลขเท่านั้น ห้ามกรอกตัวอักษร"

    try:
        recipe_raw = json.loads(recipe_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        return False, "ข้อมูลสูตรอาหารไม่ถูกต้อง กรุณาลองใหม่อีกครั้ง"

    image_file = files.get("image")
    image_ok, image_result = _validate_and_save_image(image_file)
    if not image_ok:
        return False, image_result

    return True, {
        "name": name,
        "price": price,
        "category": category,
        "recipe_raw": recipe_raw,
        "image_result": image_result,
    }


@app.route("/admin/menu/new", methods=["GET", "POST"])
@login_required(allowed_roles=["admin"])
def admin_menu_new():
    """เพิ่มเมนูอาหารใหม่ พร้อมสูตรอาหารและรูปภาพ (ไม่บังคับต้องมีรูป)"""
    if request.method == "GET":
        ingredients = db.get_inventory_list()
        return render_template("admin_menu_form.html", mode="new", menu_item=None, ingredients=ingredients)

    try:
        ok, parsed = _parse_recipe_and_price(request.form, request.files)
        if not ok:
            flash(parsed, "error")
            return redirect(url_for("admin_menu_new"))

        admin_username = session.get("username", "unknown")
        success, result = db.add_menu_item(
            parsed["name"], parsed["price"], parsed["category"], parsed["recipe_raw"],
            parsed["image_result"], admin_username,
        )

        if not success:
            flash(result, "error")
            return redirect(url_for("admin_menu_new"))

        flash(f"เพิ่มเมนู '{result.get('name')}' สำเร็จ", "success")
        return redirect(url_for("admin_menu_list"))
    except Exception:
        flash("เกิดข้อผิดพลาดในการเพิ่มเมนู กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("admin_menu_new"))


@app.route("/admin/menu/<menu_id>/edit", methods=["GET", "POST"])
@login_required(allowed_roles=["admin"])
def admin_menu_edit(menu_id):
    """แก้ไขเมนูอาหารที่มีอยู่ (เปลี่ยนรูปได้ หรือเว้นว่างไว้เพื่อใช้รูปเดิมต่อ)"""
    if request.method == "GET":
        menu_item = db.get_menu_item_by_id_raw(menu_id)
        if menu_item is None:
            flash("ไม่พบเมนูนี้ในระบบ", "error")
            return redirect(url_for("admin_menu_list"))
        ingredients = db.get_inventory_list()
        return render_template("admin_menu_form.html", mode="edit", menu_item=menu_item, ingredients=ingredients)

    try:
        current_item = db.get_menu_item_by_id_raw(menu_id)
        if current_item is None:
            flash("ไม่พบเมนูนี้ในระบบ", "error")
            return redirect(url_for("admin_menu_list"))

        ok, parsed = _parse_recipe_and_price(request.form, request.files)
        if not ok:
            flash(parsed, "error")
            return redirect(url_for("admin_menu_edit", menu_id=menu_id))

        remove_image = request.form.get("remove_image") == "1"
        current_image = current_item.get("image")

        if parsed["image_result"]:
            final_image = parsed["image_result"]
        elif remove_image:
            final_image = ""
        else:
            final_image = current_image

        admin_username = session.get("username", "unknown")
        success, result = db.update_menu_item(
            menu_id, parsed["name"], parsed["price"], parsed["category"], parsed["recipe_raw"],
            final_image, admin_username,
        )

        if not success:
            flash(result, "error")
            return redirect(url_for("admin_menu_edit", menu_id=menu_id))

        flash(f"แก้ไขเมนู '{result.get('name')}' สำเร็จ", "success")
        return redirect(url_for("admin_menu_list"))
    except Exception:
        flash("เกิดข้อผิดพลาดในการแก้ไขเมนู กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("admin_menu_edit", menu_id=menu_id))


@app.route("/admin/menu/<menu_id>/delete", methods=["POST"])
@login_required(allowed_roles=["admin"])
def admin_menu_delete(menu_id):
    """ลบเมนูอาหารออกจากระบบ"""
    try:
        admin_username = session.get("username", "unknown")
        success, result = db.delete_menu_item(menu_id, admin_username)
        if not success:
            flash(result, "error")
        else:
            flash("ลบเมนูสำเร็จ", "success")
        return redirect(url_for("admin_menu_list"))
    except Exception:
        flash("เกิดข้อผิดพลาดในการลบเมนู กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("admin_menu_list"))


@app.route("/admin/menu/<menu_id>/toggle", methods=["POST"])
@login_required(allowed_roles=["admin", "staff"])
def admin_menu_toggle(menu_id):
    """สลับสถานะเปิด/ปิดขายของเมนู"""
    try:
        admin_username = session.get("username", "unknown")
        success, message = db.toggle_menu_availability(menu_id, admin_username)
        flash(message, "success" if success else "error")
        return redirect(url_for("admin_menu_list"))
    except Exception:
        flash("เกิดข้อผิดพลาดในการเปลี่ยนสถานะเมนู กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("admin_menu_list"))


# ---------------------------------------------------------------------------
# Admin: ประวัติบิลย้อนหลัง / รายงานการขายเชิงลึก
# ---------------------------------------------------------------------------

@app.route("/admin/bills")
@login_required(allowed_roles=["admin"])
def admin_bills_list():
    try:
        bills = db.get_all_bills()
        return render_template("admin_bills_list.html", bills=bills)
    except Exception:
        flash("เกิดข้อผิดพลาดในการโหลดประวัติบิล กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("admin_dashboard"))


@app.route("/admin/bills/<bill_id>")
@login_required(allowed_roles=["admin"])
def admin_bill_detail(bill_id):
    try:
        bill = db.get_bill_detail(bill_id)
        if bill is None:
            flash("ไม่พบบิลนี้ในระบบ", "error")
            return redirect(url_for("admin_bills_list"))
        return render_template("admin_bill_detail.html", bill=bill)
    except Exception:
        flash("เกิดข้อผิดพลาดในการโหลดรายละเอียดบิล กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("admin_bills_list"))


# ---------------------------------------------------------------------------
# Customer: หน้าของลูกค้า
# ---------------------------------------------------------------------------

def _get_active_customer_table():
    try:
        table_id = session.get("table_id")
        if not table_id:
            return None
        tables = db.get_all_tables()
        current_table = next((t for t in tables if t.get("table_id") == table_id), None)
        if current_table is None or current_table.get("status") != "มีลูกค้า":
            return None
        return current_table
    except Exception:
        return None


@app.route("/customer/dashboard")
@login_required(allowed_roles=["customer"])
def customer_dashboard():
    try:
        current_table = _get_active_customer_table()
        if current_table is None:
            session.clear()
            flash("เซสชันของโต๊ะนี้สิ้นสุดลงแล้ว กรุณาเข้าสู่ระบบใหม่อีกครั้ง", "error")
            return redirect(url_for("customer_login"))

        menu = db.get_menu_list(only_available=False)
        my_table_id = current_table.get("table_id")
        all_current_orders = db.get_active_orders_sorted()
        my_orders = [
            o for o in all_current_orders
            if o.get("table_id") == my_table_id and o.get("status") != "ยกเลิก"
        ]
        my_orders = list(reversed(my_orders))

        return render_template(
            "customer_dashboard.html", table=current_table, menu=menu, my_orders=my_orders
        )
    except Exception:
        flash("เกิดข้อผิดพลาด กรุณาเข้าสู่ระบบใหม่อีกครั้ง", "error")
        session.clear()
        return redirect(url_for("index"))


@app.route("/customer/menu")
@login_required(allowed_roles=["customer"])
def customer_menu():
    try:
        current_table = _get_active_customer_table()
        if current_table is None:
            session.clear()
            flash("เซสชันของโต๊ะนี้สิ้นสุดลงแล้ว กรุณาเข้าสู่ระบบใหม่อีกครั้ง", "error")
            return redirect(url_for("customer_login"))

        search = request.args.get("search", "").strip()
        category = request.args.get("category", "").strip()

        try:
            page = int(request.args.get("page", "1"))
        except (TypeError, ValueError):
            page = 1
        if page < 1:
            page = 1

        filtered_menu = db.search_menu(search, category)
        total_items = len(filtered_menu)
        total_pages = max(1, (total_items + MENU_PAGE_SIZE - 1) // MENU_PAGE_SIZE)

        if page > total_pages:
            page = total_pages

        start_index = (page - 1) * MENU_PAGE_SIZE
        end_index = start_index + MENU_PAGE_SIZE
        page_items = filtered_menu[start_index:end_index]
        categories = db.get_menu_categories()

        return render_template(
            "customer_menu.html",
            table=current_table,
            menu=page_items,
            categories=categories,
            search=search,
            selected_category=category,
            page=page,
            total_pages=total_pages,
            total_items=total_items,
        )
    except Exception:
        flash("เกิดข้อผิดพลาดในการโหลดเมนู กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("customer_dashboard"))


@app.route("/customer/order", methods=["POST"])
@login_required(allowed_roles=["customer"])
def customer_order():
    try:
        current_table = _get_active_customer_table()
        if current_table is None:
            session.clear()
            flash("เซสชันของโต๊ะนี้สิ้นสุดลงแล้ว กรุณาเข้าสู่ระบบใหม่อีกครั้ง", "error")
            return redirect(url_for("customer_login"))

        raw_cart = request.form.get("cart_data", "")
        if not isinstance(raw_cart, str) or raw_cart.strip() == "":
            flash("กรุณาเลือกรายการอาหารก่อนยืนยันออเดอร์", "error")
            return redirect(url_for("customer_menu"))

        try:
            cart_items = json.loads(raw_cart)
        except (json.JSONDecodeError, TypeError, ValueError):
            flash("ข้อมูลออเดอร์ไม่ถูกต้อง กรุณาลองใหม่อีกครั้ง", "error")
            return redirect(url_for("customer_menu"))

        if not isinstance(cart_items, list) or len(cart_items) == 0:
            flash("กรุณาเลือกรายการอาหารก่อนยืนยันออเดอร์", "error")
            return redirect(url_for("customer_menu"))

        merged_items = {}
        for raw_item in cart_items:
            if not isinstance(raw_item, dict):
                flash("รูปแบบรายการอาหารไม่ถูกต้อง", "error")
                return redirect(url_for("customer_menu"))

            menu_id = raw_item.get("menu_id")
            quantity = raw_item.get("quantity")

            if not isinstance(menu_id, str) or menu_id.strip() == "":
                flash("รหัสเมนูไม่ถูกต้อง", "error")
                return redirect(url_for("customer_menu"))

            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
                flash("จำนวนอาหารต้องเป็นตัวเลขจำนวนเต็มบวกเท่านั้น", "error")
                return redirect(url_for("customer_menu"))

            if quantity > MAX_QTY_PER_ITEM:
                flash(f"สั่งอาหารได้สูงสุด {MAX_QTY_PER_ITEM} ที่ต่อเมนู", "error")
                return redirect(url_for("customer_menu"))

            menu_item = db.get_menu_by_id(menu_id)
            if menu_item is None or not menu_item.get("is_available", False):
                flash("พบเมนูที่ไม่มีอยู่จริงหรือถูกปิดการขาย", "error")
                return redirect(url_for("customer_menu"))

            note = str(raw_item.get("note", "")).strip()[:200]
            if menu_id in merged_items:
                merged_items[menu_id]["quantity"] += quantity
                if note and note not in merged_items[menu_id]["note"]:
                    merged_items[menu_id]["note"] = (merged_items[menu_id]["note"] + "; " + note)[:200]
            else:
                merged_items[menu_id] = {"quantity": quantity, "note": note}

        final_items = [
            {"menu_id": mid, "quantity": data["quantity"], "note": data["note"]}
            for mid, data in merged_items.items()
        ]

        success, result = db.create_order(
            current_table.get("table_id"), final_items, created_by=current_table.get("table_name")
        )

        if not success:
            flash(result, "error")
            return redirect(url_for("customer_menu"))

        flash(f"สั่งอาหารสำเร็จ! หมายเลขออเดอร์ {result.get('order_id')}", "success")
        return redirect(url_for("customer_dashboard"))
    except Exception:
        flash("เกิดข้อผิดพลาดในการสั่งอาหาร กรุณาลองใหม่อีกครั้ง", "error")
        return redirect(url_for("customer_menu"))


@app.errorhandler(403)
def forbidden_error(e):
    return render_template("error.html", code=403, message="คุณไม่มีสิทธิ์เข้าถึงหน้านี้"), 403


@app.errorhandler(404)
def not_found_error(e):
    return render_template("error.html", code=404, message="ไม่พบหน้าที่คุณต้องการ"), 404


@app.errorhandler(500)
def internal_error(e):
    return render_template("error.html", code=500, message="เกิดข้อผิดพลาดในระบบ กรุณาลองใหม่อีกครั้ง"), 500


if __name__ == "__main__":
    #db.init_data_files()
    app.run(debug=True, host="0.0.0.0", port=5000)