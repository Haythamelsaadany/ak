import streamlit as st
import os
import sqlite3
import pandas as pd
import datetime
import bcrypt
import qrcode
import shutil
import zipfile
from io import BytesIO
from PIL import Image
import urllib.parse
import re
import requests
import tempfile
import io

# ======================== الثوابت ========================
DB_NAME = 'gallery.db'
IMG_FOLDER = "images"
BACKUP_FOLDER = "backups"

for folder in [IMG_FOLDER, BACKUP_FOLDER]:
    os.makedirs(folder, exist_ok=True)

st.set_page_config(page_title="Antiq Khana", page_icon="🏛️", layout="wide")

# ------------------------ CSS ------------------------
st.markdown("""
<style>
.brand-title {
    text-align: center; padding: 1rem;
    background: linear-gradient(135deg, #8e44ad, #c0392b);
    border-radius: 12px; color: white; margin-bottom: 1.5rem;
    font-size: 1.8rem; font-weight: bold;
}
</style>
""", unsafe_allow_html=True)

# ------------------------ OCR ------------------------
try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

def is_tesseract_ready():
    if not TESSERACT_AVAILABLE:
        return False, "pytesseract not installed"
    try:
        possible_paths = ['/usr/bin/tesseract', '/app/.apt/usr/bin/tesseract']
        for path in possible_paths:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                break
        version = pytesseract.get_tesseract_version()
        return True, f"Tesseract {version}"
    except:
        return False, "Tesseract not found"

def extract_text_from_image(image_file):
    ready, _ = is_tesseract_ready()
    if not ready:
        return "OCR not available"
    try:
        img = Image.open(image_file)
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        text = pytesseract.image_to_string(img, lang='ara+eng')
        return text.strip()
    except Exception as e:
        return f"Error: {e}"

# ------------------------ دالة قاعدة البيانات ------------------------
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS antiques (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT,
            price REAL,
            place_of_origin TEXT,
            description TEXT,
            date_added TEXT,
            sold TEXT DEFAULT '0',
            image_path TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT,
            role TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS sales (
            invoice_id TEXT PRIMARY KEY,
            customer_name TEXT,
            customer_phone TEXT,
            item_id TEXT,
            item_name TEXT,
            price REAL,
            discount REAL,
            total REAL,
            sale_date TEXT
        )''')
        # admin user
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username='admin'")
        if not cur.fetchone():
            hashed = bcrypt.hashpw("admin123".encode(), bcrypt.gensalt())
            conn.execute("INSERT INTO users VALUES (?,?,?)", ("admin", hashed, "admin"))
        # sample items
        cur.execute("SELECT COUNT(*) FROM antiques")
        if cur.fetchone()[0] == 0:
            now = datetime.datetime.now().isoformat()
            samples = [
                ("ANT001", "تمثال فرعوني", "تماثيل", 450.0, "مصر", "تمثال للإله حورس", now, "0", ""),
                ("ANT002", "مصحف عثماني", "مخطوطات", 1200.0, "تركيا", "مصحف نادر", now, "0", "")
            ]
            conn.executemany("INSERT INTO antiques VALUES (?,?,?,?,?,?,?,?,?)", samples)

def log_action(username, action, item_id=""):
    pass  # اختياري

def save_image(uploaded_file, item_id):
    if uploaded_file:
        img = Image.open(uploaded_file)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        path = os.path.join(IMG_FOLDER, f"{item_id}.jpg")
        img.save(path, "JPEG", quality=85)
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("UPDATE antiques SET image_path=? WHERE id=?", (path, item_id))
        return path
    return None

def get_image_path(item_id):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("SELECT image_path FROM antiques WHERE id=?", (item_id,))
        row = cur.fetchone()
        if row and row[0] and os.path.exists(row[0]):
            return row[0]
    return None

def generate_invoice_id():
    today = datetime.datetime.now().strftime("%Y%m%d")
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sales WHERE invoice_id LIKE ?", (f"INV-{today}-%",))
        count = cur.fetchone()[0]
        return f"INV-{today}-{count+1:04d}"

def sell_item(item_id, customer_name, customer_phone, discount=0):
    with sqlite3.connect(DB_NAME) as conn:
        df = pd.read_sql("SELECT * FROM antiques WHERE id=? AND sold='0'", conn, params=(item_id,))
        if df.empty:
            return False, "Not found or sold"
        item = df.iloc[0]
        price = float(item['price'])
        total = price - discount
        inv_id = generate_invoice_id()
        sale_date = datetime.datetime.now().isoformat()
        conn.execute("INSERT INTO sales VALUES (?,?,?,?,?,?,?,?,?)",
                     (inv_id, customer_name, customer_phone, item_id, item['name'], price, discount, total, sale_date))
        conn.execute("UPDATE antiques SET sold='1' WHERE id=?", (item_id,))
        return True, inv_id

def create_search_urls(term):
    encoded = urllib.parse.quote(term)
    return {
        "1stDibs": f"https://www.1stdibs.com/search/?q={encoded}",
        "Invaluable": f"https://www.invaluable.com/search/?q={encoded}",
        "eBay Sold": f"https://www.ebay.com/sch/i.html?_nkw={encoded}&LH_Sold=1"
    }

# ------------------------ واجهات التطبيق ------------------------
def show_gallery():
    st.markdown('<div class="brand-title">🏛️ Antiq Khana</div>', unsafe_allow_html=True)
    st.header("المعرض")
    with sqlite3.connect(DB_NAME) as conn:
        df = pd.read_sql("SELECT * FROM antiques ORDER BY date_added DESC", conn)
    if df.empty:
        st.info("لا توجد قطع. أضف قطعاً جديدة.")
        return
    search = st.text_input("🔍 بحث بالاسم أو الكود")
    if search:
        df = df[df['name'].str.contains(search, case=False, na=False) | df['id'].str.contains(search, case=False, na=False)]
    for _, row in df.iterrows():
        with st.container(border=True):
            col1, col2 = st.columns([1, 2])
            with col1:
                img_path = get_image_path(row['id'])
                if img_path:
                    st.image(img_path, use_container_width=True)
                else:
                    st.image("https://via.placeholder.com/150", use_container_width=True)
            with col2:
                st.subheader(row['name'])
                st.write(f"**الكود:** {row['id']}")
                st.write(f"**السعر:** ${row['price']:.2f}")
                st.write(f"**الحالة:** {'❌ مباع' if row['sold']=='1' else '✅ متوفر'}")
                if st.button(f"تفاصيل", key=row['id']):
                    st.session_state.selected_item = row['id']
                    st.rerun()

def show_details():
    if not st.session_state.get("selected_item"):
        st.session_state.page = "gallery"
        st.rerun()
    with sqlite3.connect(DB_NAME) as conn:
        row = pd.read_sql("SELECT * FROM antiques WHERE id=?", conn, params=(st.session_state.selected_item,)).iloc[0]
    st.title(f"📌 {row['name']}")
    img_path = get_image_path(row['id'])
    if img_path:
        st.image(img_path, width=300)
    st.write(f"**الكود:** {row['id']}")
    st.write(f"**التصنيف:** {row['category'] or '-'}")
    st.write(f"**بلد المنشأ:** {row['place_of_origin'] or '-'}")
    st.write(f"**الوصف:** {row['description'] or '-'}")
    st.write(f"**السعر:** ${row['price']:.2f}")
    st.write(f"**الحالة:** {'مباع' if row['sold']=='1' else 'متوفر'}")
    st.markdown("---")
    st.subheader("🔍 بحث خارجي للتسعير")
    term = f"{row['name']} {row['category']} {row['place_of_origin']}".strip()
    urls = create_search_urls(term)
    cols = st.columns(len(urls))
    for i, (site, url) in enumerate(urls.items()):
        with cols[i]:
            st.link_button(site, url)
    if st.button("🔙 الرجوع للمعرض"):
        st.session_state.selected_item = None
        st.rerun()

def show_add_item():
    if st.session_state.role not in ['admin', 'editor']:
        st.error("غير مصرح")
        return
    st.header("➕ إضافة قطعة جديدة")
    with st.form("add"):
        code = st.text_input("الكود *")
        name = st.text_input("الاسم *")
        cat = st.text_input("التصنيف")
        price = st.number_input("السعر", min_value=0.0, step=0.5)
        origin = st.text_input("بلد المنشأ")
        desc = st.text_area("الوصف")
        img = st.file_uploader("الصورة", type=['jpg', 'png', 'jpeg'])
        if st.form_submit_button("حفظ"):
            if not code or not name:
                st.error("الكود والاسم مطلوبان")
            else:
                with sqlite3.connect(DB_NAME) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id FROM antiques WHERE id=?", (code,))
                    if cur.fetchone():
                        st.error("الكود موجود مسبقاً")
                    else:
                        now = datetime.datetime.now().isoformat()
                        conn.execute("INSERT INTO antiques (id, name, category, price, place_of_origin, description, date_added, sold, image_path) VALUES (?,?,?,?,?,?,?,?,?)",
                                     (code, name, cat, price, origin, desc, now, '0', ''))
                        if img:
                            save_image(img, code)
                        st.success("تمت الإضافة")
                        st.rerun()

def show_sales():
    if st.session_state.role not in ['admin', 'editor']:
        st.error("غير مصرح")
        return
    st.header("🧾 بيع قطعة")
    with sqlite3.connect(DB_NAME) as conn:
        avail = pd.read_sql("SELECT id, name, price FROM antiques WHERE sold='0'", conn)
    if avail.empty:
        st.warning("لا توجد قطع متاحة للبيع")
        return
    with st.form("sale"):
        opt = {f"{r['name']} - ${r['price']}": r['id'] for _, r in avail.iterrows()}
        sel = st.selectbox("اختر القطعة", list(opt.keys()))
        item_id = opt[sel]
        price = avail[avail['id']==item_id]['price'].values[0]
        disc = st.number_input("الخصم", 0.0, float(price), step=1.0)
        total = price - disc
        cust_name = st.text_input("اسم العميل")
        cust_phone = st.text_input("رقم الهاتف")
        if st.form_submit_button("إصدار فاتورة"):
            if not cust_name or not cust_phone:
                st.error("اسم العميل والهاتف مطلوبان")
            else:
                ok, inv_id = sell_item(item_id, cust_name, cust_phone, disc)
                if ok:
                    st.success(f"تم البيع. رقم الفاتورة: {inv_id}")
                    st.rerun()
                else:
                    st.error("فشل البيع")

def show_search_image():
    st.header("🔍 بحث بالصورة (OCR)")
    uploaded = st.file_uploader("اختر صورة", type=['jpg', 'png', 'jpeg'])
    if uploaded:
        col1, col2 = st.columns(2)
        with col1:
            st.image(uploaded, caption="الصورة المرفوعة", width=200)
        with col2:
            if st.button("استخراج النص والبحث"):
                text = extract_text_from_image(uploaded)
                st.write("**النص المستخرج:**")
                st.code(text)
                if text and "خطأ" not in text:
                    keywords = re.findall(r'[\u0600-\u06FF\w]+', text)
                    keywords = [k for k in keywords if len(k) > 2]
                    if keywords:
                        with sqlite3.connect(DB_NAME) as conn:
                            df = pd.read_sql("SELECT * FROM antiques", conn)
                        results = []
                        for kw in keywords:
                            matches = df[df['name'].str.contains(kw, case=False, na=False) |
                                         df['description'].str.contains(kw, case=False, na=False)]
                            results.extend(matches.to_dict('records'))
                        if results:
                            st.success(f"تم العثور على {len(results)} نتيجة")
                            for r in results[:5]:
                                st.write(f"- {r['name']} (Code: {r['id']})")
                        else:
                            st.info("لم يتم العثور على قطع مطابقة")
                else:
                    st.warning("لم يتم التعرف على نص واضح")

def show_backup():
    if st.session_state.role != "admin":
        st.error("Admin only")
        return
    st.header("💾 النسخ الاحتياطي")
    if st.button("إنشاء نسخة"):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(BACKUP_FOLDER, f"backup_{ts}.zip")
        with zipfile.ZipFile(backup_path, 'w') as zipf:
            if os.path.exists(DB_NAME):
                zipf.write(DB_NAME)
            if os.path.exists(IMG_FOLDER):
                for root, _, files in os.walk(IMG_FOLDER):
                    for f in files:
                        zipf.write(os.path.join(root, f))
        with open(backup_path, "rb") as f:
            st.download_button("تحميل النسخة", f, file_name=f"backup_{ts}.zip")
    uploaded = st.file_uploader("استعادة من نسخة", type=['zip'])
    if uploaded:
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(io.BytesIO(uploaded.read()), 'r') as zipf:
                zipf.extractall(tmp)
            db_backup = os.path.join(tmp, DB_NAME)
            if os.path.exists(db_backup):
                shutil.copy2(db_backup, DB_NAME)
                st.success("تمت الاستعادة بنجاح، أعد تشغيل التطبيق")
                st.rerun()
            else:
                st.error("الملف لا يحتوي على قاعدة بيانات")

def show_stats():
    st.header("📊 إحصائيات")
    with sqlite3.connect(DB_NAME) as conn:
        df = pd.read_sql("SELECT * FROM antiques", conn)
        sales = pd.read_sql("SELECT * FROM sales", conn)
    if not df.empty:
        c1, c2, c3 = st.columns(3)
        c1.metric("إجمالي القطع", len(df))
        c2.metric("مباعة", len(df[df['sold']=='1']))
        c3.metric("متاحة", len(df[df['sold']=='0']))
        if not sales.empty:
            st.metric("إجمالي الإيرادات", f"${sales['total'].sum():.2f}")

def show_import_export():
    st.header("📂 استيراد/تصدير Excel")
    with st.expander("تصدير"):
        with sqlite3.connect(DB_NAME) as conn:
            out = pd.read_sql("SELECT id, name, category, price, place_of_origin, description FROM antiques", conn)
        if not out.empty:
            buf = BytesIO()
            out.to_excel(buf, index=False)
            st.download_button("تحميل Excel", buf.getvalue(), file_name="antiques.xlsx")
    with st.expander("استيراد"):
        f = st.file_uploader("اختر ملف Excel", type=['xlsx'])
        if f and st.button("استيراد"):
            df = pd.read_excel(f)
            count = 0
            with sqlite3.connect(DB_NAME) as conn:
                for _, row in df.iterrows():
                    if 'id' in row and 'name' in row:
                        conn.execute("INSERT OR REPLACE INTO antiques (id, name, category, price, place_of_origin, description, date_added, sold) VALUES (?,?,?,?,?,?,?,?)",
                                     (str(row['id']), str(row['name']), str(row.get('category', '')), float(row.get('price', 0)), str(row.get('place_of_origin', '')), str(row.get('description', '')), datetime.datetime.now().isoformat(), '0'))
                        count += 1
            st.success(f"تم استيراد {count} قطعة")

def show_user_management():
    if st.session_state.role != "admin":
        st.error("Admin only")
        return
    st.header("👥 إدارة المستخدمين")
    with st.form("new_user"):
        uname = st.text_input("اسم المستخدم")
        pwd = st.text_input("كلمة المرور", type="password")
        role = st.selectbox("الدور", ["viewer", "editor", "admin"])
        if st.form_submit_button("إضافة"):
            if uname and pwd:
                hashed = bcrypt.hashpw(pwd.encode(), bcrypt.gensalt())
                try:
                    with sqlite3.connect(DB_NAME) as conn:
                        conn.execute("INSERT INTO users VALUES (?,?,?)", (uname, hashed, role))
                    st.success("تمت الإضافة")
                except:
                    st.error("اسم المستخدم موجود")
    with sqlite3.connect(DB_NAME) as conn:
        users = pd.read_sql("SELECT username, role FROM users", conn)
    st.dataframe(users)

def change_password():
    with st.sidebar.form("change_pwd"):
        old = st.text_input("كلمة المرور الحالية", type="password")
        new = st.text_input("كلمة المرور الجديدة", type="password")
        confirm = st.text_input("تأكيد", type="password")
        if st.form_submit_button("تغيير"):
            if new != confirm:
                st.sidebar.error("غير متطابقة")
            else:
                with sqlite3.connect(DB_NAME) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT password FROM users WHERE username=?", (st.session_state.username,))
                    row = cur.fetchone()
                    if row and bcrypt.checkpw(old.encode(), row[0]):
                        hashed = bcrypt.hashpw(new.encode(), bcrypt.gensalt())
                        conn.execute("UPDATE users SET password=? WHERE username=?", (hashed, st.session_state.username))
                        st.sidebar.success("تم التغيير")
                    else:
                        st.sidebar.error("كلمة المرور الحالية خاطئة")

# ------------------------ حالة الجلسة ------------------------
if "auth" not in st.session_state:
    st.session_state.auth = False
    st.session_state.username = ""
    st.session_state.role = ""
    st.session_state.page = "gallery"
    st.session_state.selected_item = None

# ------------------------ تسجيل الدخول ------------------------
if not st.session_state.auth:
    st.title("🏛️ Antiq Khana")
    st.subheader("تسجيل الدخول")
    un = st.text_input("اسم المستخدم")
    pw = st.text_input("كلمة المرور", type="password")
    if st.button("دخول"):
        init_db()
        with sqlite3.connect(DB_NAME) as conn:
            cur = conn.cursor()
            cur.execute("SELECT password, role FROM users WHERE username=?", (un,))
            row = cur.fetchone()
            if row and bcrypt.checkpw(pw.encode(), row[0]):
                st.session_state.auth = True
                st.session_state.username = un
                st.session_state.role = row[1]
                st.rerun()
            else:
                st.error("بيانات غير صحيحة")
    st.stop()

# ------------------------ القائمة الجانبية ------------------------
st.sidebar.markdown(f"**مرحباً {st.session_state.username}** - {st.session_state.role}")
if st.sidebar.button("🔐 تغيير كلمة المرور"):
    change_password()

menu = ["🖼️ المعرض", "➕ إضافة قطعة", "🧾 بيع", "🔍 بحث بالصورة", "📊 إحصائيات", "📂 استيراد/تصدير", "👥 إدارة المستخدمين", "💾 نسخ احتياطي"]
choice = st.sidebar.radio("القائمة", menu)

if choice == "🖼️ المعرض":
    show_gallery()
elif choice == "➕ إضافة قطعة":
    show_add_item()
elif choice == "🧾 بيع":
    show_sales()
elif choice == "🔍 بحث بالصورة":
    show_search_image()
elif choice == "📊 إحصائيات":
    show_stats()
elif choice == "📂 استيراد/تصدير":
    show_import_export()
elif choice == "👥 إدارة المستخدمين":
    show_user_management()
elif choice == "💾 نسخ احتياطي":
    show_backup()

if st.session_state.get("selected_item"):
    show_details()

if __name__ == "__main__":
    init_db()