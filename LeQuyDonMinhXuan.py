import matplotlib
matplotlib.use('Agg')
import streamlit as st
import pandas as pd
import sqlite3
import json
import time
import unicodedata
import random
import re
import math
from io import BytesIO
from datetime import datetime, timedelta, timezone
import fitz  # PyMuPDF
import google.generativeai as genai

# --- CẤU HÌNH HỆ THỐNG V46 (A1 SUPREME - FINAL VỚI TÍNH NĂNG XÓA HÀNG LOẠT) ---
ADMIN_CORE_EMAIL = "maducnghi6789@gmail.com"
ADMIN_CORE_PW = "admin123"
VN_TZ = timezone(timedelta(hours=7))

# ==========================================
# 1. TIỆN ÍCH BẢO MẬT & XỬ LÝ CHUỖI
# ==========================================
def get_conn():
    return sqlite3.connect('exam_db.sqlite', check_same_thread=False)

def remove_accents(input_str):
    if not input_str: return ""
    nfkd_form = unicodedata.normalize('NFKD', str(input_str))
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).replace(" ", "").lower()

def gen_smart_username(fullname, existing_usernames):
    base_name = remove_accents(fullname)
    base_user = f"lqd_{base_name}"
    if base_user not in existing_usernames: return base_user
    counter = 1
    while True:
        new_user = f"{base_user}{counter}"
        if new_user not in existing_usernames: return new_user
        counter += 1

def clean_ai_json(json_str):
    res = json_str.strip()
    res = re.sub(r'```json', '', res, flags=re.IGNORECASE)
    res = re.sub(r'```', '', res)
    start_idx = res.find('[')
    end_idx = res.rfind(']')
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        res = res[start_idx:end_idx+1]
    res = re.sub(r',\s*]', ']', res)
    res = re.sub(r',\s*}', '}', res)
    # FIX LỖI ẢO GIÁC NGOẶC KÉP CỦA AI TRONG CHUỖI JSON
    res = res.replace('{{', '{').replace('}}', '}')
    return res

def format_math(text):
    if not isinstance(text, str): return text
    bt = chr(96)
    text = re.sub(bt + r'(.*?)' + bt, r'$\1$', text)
    text = text.replace('TEX_', '\\')
    text = text.replace('\\\\', '\\')
    text = text.replace('{{', '{').replace('}}', '}')
    return text

def get_api_key():
    conn = get_conn()
    res = conn.execute("SELECT setting_value FROM system_settings WHERE setting_key='GEMINI_API_KEY'").fetchone()
    conn.close()
    return res[0] if res else ""

# ==========================================
# 2. HỆ QUẢN TRỊ CƠ SỞ DỮ LIỆU
# ==========================================
def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY)")
    user_cols = [("password", "TEXT"), ("role", "TEXT"), ("fullname", "TEXT"), ("dob", "TEXT"), ("class_name", "TEXT"), ("school", "TEXT"), ("managed_classes", "TEXT")]
    c.execute("PRAGMA table_info(users)")
    existing_u_cols = [row[1] for row in c.fetchall()]
    for col_name, col_type in user_cols:
        if col_name not in existing_u_cols:
            try: c.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
            except: pass
            
    c.execute("CREATE TABLE IF NOT EXISTS system_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS mandatory_exams (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, questions_json TEXT, time_limit INTEGER, target_class TEXT, created_by TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
    
    c.execute("PRAGMA table_info(mandatory_exams)")
    existing_e_cols = [row[1] for row in c.fetchall()]
    exam_cols = [("title", "TEXT"), ("questions_json", "TEXT"), ("time_limit", "INTEGER"), ("target_class", "TEXT"), ("created_by", "TEXT"), ("timestamp", "DATETIME DEFAULT CURRENT_TIMESTAMP")]
    for col_name, col_type in exam_cols:
        if col_name not in existing_e_cols:
            try: c.execute(f"ALTER TABLE mandatory_exams ADD COLUMN {col_name} {col_type}")
            except: pass

    c.execute("CREATE TABLE IF NOT EXISTS mandatory_results (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, exam_id INTEGER, score REAL, user_answers_json TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
    
    admin_exists = conn.execute("SELECT 1 FROM users WHERE username=?", (ADMIN_CORE_EMAIL,)).fetchone()
    if not admin_exists:
        c.execute("INSERT INTO users (username, password, role, fullname) VALUES (?, ?, 'core_admin', 'Quản trị mạng')", (ADMIN_CORE_EMAIL, ADMIN_CORE_PW))
    else:
        c.execute("UPDATE users SET password=?, role='core_admin', fullname='Quản trị mạng' WHERE username=?", (ADMIN_CORE_PW, ADMIN_CORE_EMAIL))
    
    c.execute("UPDATE users SET password='123@' WHERE password LIKE '$2b$12$%' AND role='student'")
    conn.commit(); conn.close()

def log_deletion(deleted_by, entity_type, entity_name, reason):
    try:
        conn = get_conn()
        vn_time = datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M:%S")
        try: conn.execute("INSERT INTO deletion_logs (deleted_by, entity_type, entity_name, reason, timestamp) VALUES (?, ?, ?, ?, ?)", (deleted_by, entity_type, entity_name, reason, vn_time))
        except: pass
        conn.commit(); conn.close()
    except: pass

# ==========================================
# 3. QUẢN LÝ TÀI KHOẢN & XÓA HÀNG LOẠT
# ==========================================
def account_manager_ui(target_role, specific_class=None):
    conn = get_conn()
    query = "SELECT * FROM users WHERE role=?"
    params = [target_role]
    if specific_class and specific_class != "Tất cả các lớp" and specific_class != "Tất cả": 
        query += " AND class_name=?"
        params.append(specific_class)
    df = pd.read_sql_query(query, conn, params=params)
    
    if not df.empty:
        cols = ['username', 'fullname', 'password', 'class_name']
        if 'school' in df.columns: cols.append('school')
        if 'managed_classes' in df.columns and target_role == 'sub_admin': cols.append('managed_classes')
        
        st.dataframe(df[cols], use_container_width=True)
        
        out = BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as w:
            rename_cols = {'username': 'Tài khoản', 'fullname': 'Họ và tên', 'password': 'Mật khẩu', 'class_name': 'Lớp'}
            df[cols].rename(columns=rename_cols).to_excel(w, index=False)
        st.download_button("⬇️ XUẤT DANH SÁCH (EXCEL)", data=out.getvalue(), file_name=f"Danh_sach_{target_role}_{datetime.now(VN_TZ).strftime('%Y%m%d')}.xlsx")
        st.divider()
        
        # SỬA / XÓA TỪNG TÀI KHOẢN
        sel_u = st.selectbox(f"Chọn {target_role} để chỉnh sửa:", ["-- Chọn --"] + df['username'].tolist())
        if sel_u != "-- Chọn --":
            u_data = df[df['username'] == sel_u].iloc[0]
            with st.form(f"form_{sel_u}"):
                c1, c2 = st.columns(2)
                f_name = c1.text_input("Họ và Tên", value=u_data['fullname'])
                f_pass = c2.text_input("🔑 Mật khẩu", value=u_data['password']) 
                f_cls = c1.text_input("Lớp", value=u_data['class_name'] if u_data['class_name'] else "")
                f_sch = c2.text_input("Trường", value=u_data.get('school', '') if pd.notna(u_data.get('school')) else "")
                f_man = st.text_input("Quyền quản lý", value=u_data.get('managed_classes', '') if pd.notna(u_data.get('managed_classes')) else "") if target_role == 'sub_admin' else ""
                b_up, b_reset, b_del = st.columns(3)
                if b_up.form_submit_button("💾 CẬP NHẬT"):
                    if target_role == 'sub_admin': conn.execute("UPDATE users SET fullname=?, password=?, class_name=?, school=?, managed_classes=? WHERE username=?", (f_name, f_pass, f_cls, f_sch, f_man, sel_u))
                    else: conn.execute("UPDATE users SET fullname=?, password=?, class_name=?, school=? WHERE username=?", (f_name, f_pass, f_cls, f_sch, sel_u))
                    conn.commit(); st.success("✅ Xong!"); time.sleep(0.5); st.rerun()
                if b_reset.form_submit_button("🔄 RESET VỀ 123@"):
                    conn.execute("UPDATE users SET password=? WHERE username=?", ("123@", sel_u)); conn.commit(); st.success("✅ Xong!"); time.sleep(1); st.rerun()
                if b_del.form_submit_button("🗑️ XÓA TÀI KHOẢN"):
                    log_deletion(st.session_state.current_user, "Tài khoản", sel_u, "Xóa thủ công")
                    conn.execute("DELETE FROM users WHERE username=?", (sel_u,)); conn.execute("DELETE FROM mandatory_results WHERE username=?", (sel_u,))
                    conn.commit(); st.warning("💥 Đã xóa"); time.sleep(0.5); st.rerun()

        # TÍNH NĂNG MỚI: XÓA TOÀN BỘ HỌC SINH ĐANG HIỂN THỊ
        if target_role == 'student':
            st.divider()
            with st.expander("🚨 NGUY HIỂM: XÓA TOÀN BỘ HỌC SINH TRONG DANH SÁCH NÀY"):
                st.warning("CẢNH BÁO: Hành động này sẽ xóa VĨNH VIỄN toàn bộ học sinh đang hiển thị ở bảng trên và tất cả kết quả thi của họ. KHÔNG THỂ KHÔI PHỤC!")
                cf_delete = st.text_input("Để xác nhận, hãy gõ chữ 'XOA' vào ô bên dưới:")
                if st.button("🔥 XÁC NHẬN XÓA HÀNG LOẠT", type="primary"):
                    if cf_delete == "XOA":
                        for u in df['username'].tolist():
                            conn.execute("DELETE FROM mandatory_results WHERE username=?", (u,))
                            conn.execute("DELETE FROM users WHERE username=?", (u,))
                        conn.commit()
                        st.success(f"✅ Đã xóa sạch {len(df)} học sinh!")
                        time.sleep(1.5)
                        st.rerun()
                    else:
                        st.error("Mã xác nhận không đúng!")

    else: 
        st.info("Chưa có dữ liệu.")
    conn.close()

def import_student_module():
    t1, t2 = st.tabs(["📁 Nạp Excel", "✍️ Nhập thủ công"])
    with t1:
        df_sample = pd.DataFrame(columns=["Họ và tên", "Ngày sinh", "Lớp", "Tên trường"])
        df_sample.loc[0] = ["Nguyễn Văn An", "15/08/2010", "9A1", "Lê Quý Đôn"]
        out = BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as w: df_sample.to_excel(w, index=False)
        st.download_button("⬇️ Tải file mẫu", out.getvalue(), "Mau_Hoc_Sinh.xlsx")
        up = st.file_uploader("Nạp Excel", type="xlsx")
        if up and st.button("🚀 Nạp dữ liệu"):
            df = pd.read_excel(up)
            col_mapping = {}
            for col in df.columns:
                norm = remove_accents(str(col)).replace(" ", "").lower()
                if "hovaten" in norm or "hoten" in norm: col_mapping[col] = "Họ và tên"
                elif "lop" in norm: col_mapping[col] = "Lớp"
            df = df.rename(columns=col_mapping)
            if "Họ và tên" not in df.columns or "Lớp" not in df.columns: st.error("❌ Thiếu cột Họ tên/Lớp.")
            else:
                conn = get_conn()
                existing = set([r[0] for r in conn.execute("SELECT username FROM users").fetchall()])
                s, f = 0, 0
                for idx, r in df.iterrows():
                    name, cls = str(r.get('Họ và tên', '')).strip(), str(r.get('Lớp', '')).strip()
                    if name and name.lower() != 'nan' and cls and cls.lower() != 'nan':
                        uname = gen_smart_username(name, existing); existing.add(uname)
                        try:
                            conn.execute("INSERT INTO users (username, password, role, fullname, class_name) VALUES (?,?,?,?,?)", (uname, "123@", "student", name, cls))
                            s += 1
                        except: f += 1
                    else: f += 1
                conn.commit(); conn.close()
                st.success(f"✅ Tạo thành công: {s} | ❌ Lỗi: {f}")
    with t2:
        with st.form("manual_add"):
            n, c = st.text_input("Họ và tên"), st.text_input("Lớp")
            if st.form_submit_button("Tạo tài khoản"):
                if n and c:
                    conn = get_conn(); existing = set([r[0] for r in conn.execute("SELECT username FROM users").fetchall()])
                    u = gen_smart_username(n, existing)
                    conn.execute("INSERT INTO users (username, password, role, fullname, class_name) VALUES (?,?,?,?,?)", (u, "123@", "student", n, c))
                    conn.commit(); st.success(f"Đã tạo: {u} (MK: 123@)"); conn.close()

def delete_class_module(all_classes):
    if not all_classes: return
    sel_cl = st.selectbox("Chọn lớp xóa:", ["-- Chọn --"] + all_classes)
    if sel_cl != "-- Chọn --":
        reason = st.text_input("Lý do xóa:")
        if st.button("XÁC NHẬN XÓA LỚP", type="primary") and reason:
            conn = get_conn()
            stus = [r[0] for r in conn.execute("SELECT username FROM users WHERE class_name=? AND role='student'", (sel_cl,)).fetchall()]
            for u in stus: conn.execute("DELETE FROM mandatory_results WHERE username=?", (u,))
            conn.execute("DELETE FROM users WHERE class_name=? AND role='student'", (sel_cl,))
            subs = conn.execute("SELECT username, managed_classes FROM users WHERE role='sub_admin'").fetchall()
            for sa, mng in subs:
                if mng:
                    new_mng = ", ".join([c.strip() for c in mng.split(',') if c.strip() != sel_cl])
                else:
                    new_mng = ""
                conn.execute("UPDATE users SET managed_classes=? WHERE username=?", (new_mng, sa))
            log_deletion(st.session_state.current_user, "Lớp học", sel_cl, reason)
            conn.commit(); conn.close(); st.rerun()

# ==========================================
# 4. MODULE AI ĐỌC & BIÊN SOẠN ĐỀ
# ==========================================
def extract_text_from_pdf(pdf_file):
    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
    text = ""
    for page in doc: text += page.get_text("text") + "\n"
    doc.close()
    return text

def safe_ai_generate(prompt, api_key_string):
    if not api_key_string or not api_key_string.strip(): return "LỖI: Chưa nhập API Key."
    keys = [k.strip() for k in api_key_string.split(',') if k.strip()]
    random.shuffle(keys)
    
    models_to_try = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash-latest', 'gemini-1.5-flash', 'gemini-1.0-pro']
    last_err = ""
    for attempt in range(2):
        for current_key in keys:
            genai.configure(api_key=current_key)
            for model_name in models_to_try:
                try:
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.85))
                    
                    raw_response = response.text.replace('TEX_', '\\')
                    cleaned_text = clean_ai_json(raw_response)
                    
                    try:
                        parsed_json = json.loads(cleaned_text)
                        if isinstance(parsed_json, list) and len(parsed_json) > 0: return parsed_json
                    except json.JSONDecodeError:
                        continue 
                except Exception as e:
                    err_msg = str(e).lower()
                    last_err = err_msg
                    if "404" in err_msg or "not found" in err_msg: continue 
                    elif "429" in err_msg or "quota" in err_msg: break 
                    elif "403" in err_msg or "api key" in err_msg: break 
                    else: continue
        if "429" in last_err or "quota" in last_err: time.sleep(5)
        else: break
    return f"LỖI TẠO ĐỀ: {last_err}. Vui lòng thử lại sau 1 phút."

def generate_ai_exam_for_admin(api_key):
    prompt = """Hãy đóng vai là một chuyên gia ra đề thi Toán.
    YÊU CẦU TỐI THƯỢNG: TẠO MỘT ĐỀ THI GỒM ĐÚNG 40 CÂU KHÁC NHAU HOÀN TOÀN VỀ DẠNG BÀI. TUYỆT ĐỐI KHÔNG ĐƯỢC LẶP LẠI (Ví dụ: Không ra 2 câu cùng tính khoảng cách dây cung). Phải phủ sóng đầy đủ 40 kiến thức riêng biệt.
    MA TRẬN: Căn thức, Hàm số y=ax^2, PT & Hệ PT, Bất PT, Hệ thức lượng, Đường tròn, Hình khối, Thống kê & Xác suất.
    ĐỊNH DẠNG JSON BẮT BUỘC: [{"q": "...", "options": ["A. $...$", "B. $...$", "C. $...$", "D. $...$"], "ans": "A", "exp": "Giải nhanh..."}]
    LƯU Ý CỰC KỲ QUAN TRỌNG: 
    1. Bắt buộc bọc MỌI biểu thức Toán và phân số trong dấu $. 
    2. KHÔNG dùng ngoặc nhọn kép {{ }}. Chỉ dùng { } cho phân số.
    3. Trả về đúng định dạng JSON Array, KHÔNG kèm Markdown (không có ```json).
    """
    return safe_ai_generate(prompt, api_key)

def parse_admin_exam_with_ai(raw_text, api_key):
    prompt = f"""Đọc đề thi Toán dưới đây. CHUẨN HÓA TOÁN HỌC, TÌM ĐÁP ÁN ĐÚNG và VIẾT HƯỚNG DẪN GIẢI.
    YÊU CẦU ĐỊNH DẠNG JSON BẮT BUỘC: [{{"q": "...", "options": ["A. $...$", "B. $...$", "C. $...$", "D. $...$"], "ans": "A", "exp": "Giải nhanh..."}}]
    LƯU Ý: Bọc các công thức trong dấu $. Dùng nháy đơn (') bên trong chuỗi. KHÔNG dùng ngoặc nhọn kép {{ }}. CHỈ XUẤT JSON.
    VĂN BẢN ĐỀ THI: {raw_text}
    """
    return safe_ai_generate(prompt, api_key)

# ==========================================
# 5. BỘ CÔNG CỤ VẼ HÌNH ĐỘNG SVG (VECTOR GRAPHICS)
# ==========================================
def svg_bar_chart(cat1, val1, cat2, val2, cat3, val3, title="Biểu đồ Tần số"):
    max_v = max(val1, val2, val3, 1)
    scale = 100 / max_v
    return f"""
    <div style="display: flex; justify-content: center; margin: 15px 0;">
    <svg width="240" height="180" viewBox="0 0 240 180" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)">
        <text x="120" y="20" font-family="Arial" font-size="13" font-weight="bold" fill="#1e293b" text-anchor="middle">{title}</text>
        <line x1="40" y1="30" x2="40" y2="140" stroke="#334155" stroke-width="2"/>
        <line x1="40" y1="140" x2="220" y2="140" stroke="#334155" stroke-width="2"/>
        <rect x="60" y="{140 - val1*scale}" width="30" height="{val1*scale}" fill="#3b82f6"/>
        <text x="75" y="{135 - val1*scale}" font-family="Arial" font-size="12" font-weight="bold" fill="#0f172a" text-anchor="middle">{val1}</text>
        <text x="75" y="155" font-family="Arial" font-size="12" font-weight="bold" fill="#334155" text-anchor="middle">{cat1}</text>
        <rect x="120" y="{140 - val2*scale}" width="30" height="{val2*scale}" fill="#ef4444"/>
        <text x="135" y="{135 - val2*scale}" font-family="Arial" font-size="12" font-weight="bold" fill="#0f172a" text-anchor="middle">{val2}</text>
        <text x="135" y="155" font-family="Arial" font-size="12" font-weight="bold" fill="#334155" text-anchor="middle">{cat2}</text>
        <rect x="180" y="{140 - val3*scale}" width="30" height="{val3*scale}" fill="#10b981"/>
        <text x="195" y="{135 - val3*scale}" font-family="Arial" font-size="12" font-weight="bold" fill="#0f172a" text-anchor="middle">{val3}</text>
        <text x="195" y="155" font-family="Arial" font-size="12" font-weight="bold" fill="#334155" text-anchor="middle">{cat3}</text>
    </svg></div>
    """

def svg_pie_chart(p1, p2, p3):
    return f"""
    <div style="display: flex; justify-content: center; margin: 15px 0;">
    <svg width="220" height="200" viewBox="0 0 220 200" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)">
        <path d="M 110 100 L 110 20 A 80 80 0 0 1 190 100 Z" fill="#3b82f6" stroke="#fff" stroke-width="2"/>
        <path d="M 110 100 L 190 100 A 80 80 0 0 1 110 180 Z" fill="#ef4444" stroke="#fff" stroke-width="2"/>
        <path d="M 110 100 L 110 180 A 80 80 0 0 1 110 20 Z" fill="#10b981" stroke="#fff" stroke-width="2"/>
        <text x="140" y="60" font-family="Arial" font-size="13" fill="#fff" font-weight="bold">{p1}%</text>
        <text x="140" y="150" font-family="Arial" font-size="13" fill="#fff" font-weight="bold">{p2}%</text>
        <text x="60" y="105" font-family="Arial" font-size="13" fill="#fff" font-weight="bold">{p3}%</text>
    </svg></div>
    """

def svg_parabola_intersection(a_val, b_val):
    return f"""
    <div style="display: flex; justify-content: center; margin: 15px 0;">
    <svg width="200" height="200" viewBox="0 0 200 200" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)">
        <defs><pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse"><path d="M 20 0 L 0 0 0 20" fill="none" stroke="#e2e8f0" stroke-width="1"/></pattern></defs>
        <rect width="200" height="200" fill="url(#grid)" />
        <line x1="100" y1="0" x2="100" y2="200" stroke="#333" stroke-width="2"/>
        <line x1="0" y1="140" x2="200" y2="140" stroke="#333" stroke-width="2"/>
        <text x="185" y="135" font-family="Arial" font-size="12" font-weight="bold">x</text>
        <text x="105" y="15" font-family="Arial" font-size="12" font-weight="bold">y</text>
        <polyline points="40,-40 60,60 80,120 100,140 120,120 140,60 160,-40" fill="none" stroke="#2563eb" stroke-width="2.5"/>
        <line x1="20" y1="180" x2="160" y2="40" stroke="#dc2626" stroke-width="2"/>
        <circle cx="80" cy="120" r="4" fill="#0f172a"/>
        <text x="40" y="125" font-family="Arial" font-size="13" font-weight="bold" fill="#0f172a">{a_val}</text>
        <circle cx="140" cy="60" r="4" fill="#0f172a"/>
        <text x="145" y="65" font-family="Arial" font-size="13" font-weight="bold" fill="#0f172a">{b_val}</text>
    </svg></div>
    """

def svg_circle_inscribed_angle(angle):
    return f"""
    <div style="display: flex; justify-content: center; margin: 15px 0;">
    <svg width="200" height="200" viewBox="0 0 200 200" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)">
        <circle cx="100" cy="100" r="80" fill="#f8fafc" stroke="#334155" stroke-width="2"/>
        <circle cx="100" cy="100" r="3" fill="#0f172a"/>
        <text x="95" y="115" font-family="Arial" font-size="13" font-weight="bold">O</text>
        <polygon points="100,20 40,153 160,153" fill="none" stroke="#2563eb" stroke-width="2"/>
        <polyline points="40,153 100,100 160,153" fill="none" stroke="#dc2626" stroke-width="1.5" stroke-dasharray="4,4"/>
        <text x="95" y="15" font-family="Arial" font-size="14" font-weight="bold">A</text>
        <text x="25" y="160" font-family="Arial" font-size="14" font-weight="bold">B</text>
        <text x="165" y="160" font-family="Arial" font-size="14" font-weight="bold">C</text>
        <text x="85" y="50" font-family="Arial" font-size="13" font-weight="bold" fill="#2563eb">{angle}°</text>
    </svg></div>
    """

def svg_building(h_val, shadow_val, angle_val):
    return f"""
    <div style="display: flex; justify-content: center; margin: 15px 0;">
    <svg width="250" height="180" viewBox="0 0 250 180" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)">
        <rect x="40" y="30" width="50" height="120" fill="#94a3b8" stroke="#334155" stroke-width="2"/>
        <rect x="50" y="40" width="10" height="15" fill="#e2e8f0"/>
        <rect x="70" y="40" width="10" height="15" fill="#e2e8f0"/>
        <rect x="50" y="70" width="10" height="15" fill="#e2e8f0"/>
        <rect x="70" y="70" width="10" height="15" fill="#e2e8f0"/>
        <line x1="90" y1="150" x2="220" y2="150" stroke="#334155" stroke-width="3"/>
        <line x1="220" y1="150" x2="90" y2="30" stroke="#f59e0b" stroke-width="2" stroke-dasharray="5,5"/>
        <text x="140" y="170" font-family="Arial" font-size="14" font-weight="bold" fill="#0f172a">{shadow_val}</text>
        <text x="10" y="95" font-family="Arial" font-size="14" font-weight="bold" fill="#0f172a">{h_val}</text>
        <text x="175" y="145" font-family="Arial" font-size="13" font-weight="bold" fill="#dc2626">{angle_val}</text>
        <path d="M 190 150 A 30 30 0 0 0 180 135" fill="none" stroke="#dc2626" stroke-width="1.5"/>
    </svg></div>
    """

def svg_ladder(ladder_val, dist_val, angle_val):
    return f"""
    <div style="display: flex; justify-content: center; margin: 15px 0;">
    <svg width="220" height="180" viewBox="0 0 220 180" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)">
        <line x1="40" y1="20" x2="40" y2="160" stroke="#475569" stroke-width="4"/>
        <line x1="40" y1="160" x2="200" y2="160" stroke="#475569" stroke-width="4"/>
        <line x1="40" y1="40" x2="160" y2="160" stroke="#b45309" stroke-width="6" stroke-linecap="round"/>
        <text x="105" y="90" font-family="Arial" font-size="14" font-weight="bold" fill="#b45309" transform="rotate(-45 105 90)">{ladder_val}</text>
        <text x="90" y="175" font-family="Arial" font-size="14" font-weight="bold" fill="#0f172a">{dist_val}</text>
        <text x="120" y="155" font-family="Arial" font-size="13" font-weight="bold" fill="#dc2626">{angle_val}</text>
        <path d="M 130 160 A 30 30 0 0 0 120 145" fill="none" stroke="#dc2626" stroke-width="1.5"/>
    </svg></div>
    """

def svg_cylinder(r_val, h_val):
    return f"""
    <div style="display: flex; justify-content: center; margin: 15px 0;">
    <svg width="200" height="200" viewBox="0 0 200 200" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)">
        <ellipse cx="100" cy="40" rx="60" ry="20" fill="#e2e8f0" stroke="#334155" stroke-width="2"/>
        <path d="M 40 40 L 40 160 A 60 20 0 0 0 160 160 L 160 40" fill="#f8fafc" stroke="#334155" stroke-width="2"/>
        <path d="M 40 160 A 60 20 0 0 1 160 160" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="5,5"/>
        <line x1="100" y1="40" x2="160" y2="40" stroke="#dc2626" stroke-width="2"/>
        <text x="120" y="35" font-family="Arial" font-size="14" font-weight="bold" fill="#dc2626">r={r_val}</text>
        <line x1="170" y1="40" x2="170" y2="160" stroke="#2563eb" stroke-width="2"/>
        <text x="175" y="105" font-family="Arial" font-size="14" font-weight="bold" fill="#2563eb">h={h_val}</text>
    </svg></div>
    """

def svg_cone(r_val, l_val):
    return f"""
    <div style="display: flex; justify-content: center; margin: 15px 0;">
    <svg width="180" height="200" viewBox="0 0 180 200" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)">
        <path d="M 90 20 L 20 160 A 70 25 0 0 0 160 160 Z" fill="#f8fafc" stroke="#334155" stroke-width="2"/>
        <path d="M 20 160 A 70 25 0 0 1 160 160" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="5,5"/>
        <line x1="90" y1="160" x2="160" y2="160" stroke="#dc2626" stroke-width="2"/>
        <text x="110" y="155" font-family="Arial" font-size="14" font-weight="bold" fill="#dc2626">r={r_val}</text>
        <text x="135" y="90" font-family="Arial" font-size="14" font-weight="bold" fill="#0f172a">l={l_val}</text>
    </svg></div>
    """

def svg_right_triangle(base_label, height_label, hyp_label, angle_label, obj_name="Máy bay"):
    return f"""
    <div style="display: flex; justify-content: center; margin: 15px 0;">
    <svg width="220" height="160" viewBox="0 0 220 160" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)">
        <polygon points="30,130 180,130 180,30" style="fill:#f8fafc;stroke:#334155;stroke-width:2" />
        <polyline points="170,130 170,120 180,120" style="fill:none;stroke:#334155;stroke-width:1.5" />
        <text x="90" y="148" font-family="Arial" font-size="14" font-weight="bold" fill="#0f172a">{base_label}</text>
        <text x="188" y="85" font-family="Arial" font-size="14" font-weight="bold" fill="#0f172a">{height_label}</text>
        <text x="80" y="70" font-family="Arial" font-size="14" font-weight="bold" fill="#0f172a" transform="rotate(-33 80 70)">{hyp_label}</text>
        <text x="55" y="125" font-family="Arial" font-size="13" font-weight="bold" fill="#dc2626">{angle_label}</text>
        <path d="M 60 130 A 30 30 0 0 0 50 115" fill="none" stroke="#dc2626" stroke-width="1.5"/>
    </svg></div>
    """

def svg_box_of_balls(color1_name, color1_count, color2_name, color2_count):
    balls = ""
    c_map = {"xanh": "#2563eb", "đỏ": "#dc2626", "vàng": "#eab308", "trắng": "#f8fafc"}
    c1 = c_map.get(color1_name, "#2563eb")
    c2 = c_map.get(color2_name, "#dc2626")
    color_list = [c1]*color1_count + [c2]*color2_count
    random.shuffle(color_list)
    row, col = 0, 0
    for color in color_list:
        cx = 30 + col * 25
        cy = 30 + row * 25
        stroke = "#cbd5e1" if color == "#f8fafc" else "none"
        balls += f'<circle cx="{cx}" cy="{cy}" r="10" fill="{color}" stroke="{stroke}" stroke-width="1"/>'
        col += 1
        if col >= 8: col = 0; row += 1
    box_h = 50 + row * 25
    return f"""
    <div style="display: flex; justify-content: center; margin: 15px 0;">
    <svg width="240" height="{box_h}" viewBox="0 0 240 {box_h}" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)">
        <rect x="10" y="10" width="220" height="{box_h-20}" rx="8" style="fill:#f1f5f9;stroke:#64748b;stroke-width:2" stroke-dasharray="5,5" />
        {balls}
    </svg></div>
    """

# ==========================================
# 6. ĐỘNG CƠ THUẬT TOÁN ĐẢO SỐ (100% OFFLINE CHO LUYỆN TỰ DO)
# ==========================================
def generate_algorithmic_practice():
    questions = []
    
    def make_opts(*args):
        opts = [f"${str(opt)}$" for opt in args]
        correct = opts[0]
        random.shuffle(opts)
        idx = opts.index(correct)
        labels = ["A.", "B.", "C.", "D."]
        return [f"{labels[i]} {opts[i]}" for i in range(4)], labels[idx]

    pool_1, pool_2, pool_3, pool_4, pool_5, pool_6, pool_7, pool_8 = [], [], [], [], [], [], [], []

    # --- POOL 1: CĂN THỨC ---
    a1 = random.randint(3, 9); b1 = random.randint(2, 5)
    opt, ans = make_opts(a1-b1, a1+b1, b1-a1, -a1-b1)
    pool_1.append({"q": f"Tính giá trị của biểu thức $P = \sqrt{{{a1**2}}} - \sqrt{{{(-b1)**2}}}$", "options": opt, "ans": ans, "exp": f"$P = {a1} - |- {b1}| = {a1} - {b1} = {a1-b1}$."})
    
    m2 = random.randint(2, 5); n2 = random.randint(1, 9)
    opt, ans = make_opts(f"x \\le \\frac{{{n2}}}{{{m2}}}", f"x \\ge \\frac{{{n2}}}{{{m2}}}", f"x < \\frac{{{n2}}}{{{m2}}}", f"x > \\frac{{{n2}}}{{{m2}}}")
    pool_1.append({"q": f"Biểu thức $\sqrt{{{n2} - {m2}x}}$ xác định khi và chỉ khi:", "options": opt, "ans": ans, "exp": f"${n2} - {m2}x \\ge 0 \Leftrightarrow {m2}x \\le {n2} \Leftrightarrow x \\le \\frac{{{n2}}}{{{m2}}}$."})

    k3 = random.choice([2, 3, 5, 7])
    opt, ans = make_opts(f"2\sqrt{{{k3}}}", f"\sqrt{{{k3}}}", f"\\frac{{2}}{{\sqrt{{{k3}}}}}", f"{k3}\sqrt{{{k3}}}")
    pool_1.append({"q": f"Kết quả của phép trục căn thức ở mẫu $\\frac{{{k3*2}}}{{\sqrt{{{k3}}}}}$ là:", "options": opt, "ans": ans, "exp": f"Nhân cả tử và mẫu với $\sqrt{{{k3}}}$ ta được $\\frac{{{k3*2}\sqrt{{{k3}}}}}{{{k3}}} = 2\sqrt{{{k3}}}$."})

    pool_1.append({"q": "Khẳng định nào sau đây là đúng?", "options": ["A. $\sqrt{16} \cdot \sqrt{9} = 12$", "B. $\sqrt{16 + 9} = 7$", "C. $\sqrt{16} + \sqrt{9} = 5$", "D. $\sqrt{16 - 9} = \sqrt{7}$"], "ans": "A", "exp": "Ta có $\sqrt{16} \cdot \sqrt{9} = 4 \cdot 3 = 12$."})

    p5 = random.randint(2, 6)
    opt, ans = make_opts(f"\\frac{{{p5**2+1}}}{{2}}", f"\\frac{{{p5**2-1}}}{{2}}", f"{p5**2+1}", f"{p5**2-1}")
    pool_1.append({"q": f"Phương trình $\sqrt{{2x - 1}} = {p5}$ có nghiệm là:", "options": opt, "ans": ans, "exp": f"Bình phương hai vế: $2x - 1 = {p5**2} \Leftrightarrow 2x = {p5**2+1} \Leftrightarrow x = \\frac{{{p5**2+1}}}{{2}}$."})

    opt, ans = make_opts("2\sqrt{5}-2", "2", "-2", "4\sqrt{5}")
    pool_1.append({"q": "Rút gọn biểu thức $M = \sqrt{(2-\sqrt{5})^2} + \sqrt{5}$", "options": opt, "ans": ans, "exp": "Vì $2 < \sqrt{5}$ nên $\sqrt{(2-\sqrt{5})^2} = |2-\sqrt{5}| = \sqrt{5}-2$. Vậy $M = \sqrt{5}-2 + \sqrt{5} = 2\sqrt{5}-2$."})

    n7 = random.randint(2, 5)
    v7 = (n7-1)**2
    opt, ans = make_opts(v7, v7-1, v7+1, v7*2)
    pool_1.append({"q": f"Biết $\sqrt{{x}} = {n7-1}$, thì $x$ bằng:", "options": opt, "ans": ans, "exp": f"Bình phương hai vế: $x = ({n7-1})^2 = {v7}$."})

    # --- POOL 2: HÀM SỐ & ĐỒ THỊ ---
    a_h1 = random.choice([-3, -2, 2, 3]); x_h1 = random.randint(1, 3)
    opt, ans = make_opts(a_h1*(x_h1**2), -a_h1*(x_h1**2), a_h1*x_h1, -a_h1*x_h1)
    pool_2.append({"q": f"Biết điểm $M({x_h1}; y_0)$ thuộc đồ thị hàm số $y = {a_h1}x^2$. Giá trị của $y_0$ là:", "options": opt, "ans": ans, "exp": f"Thay $x = {x_h1}$ vào hàm số: $y_0 = {a_h1} \cdot ({x_h1})^2 = {a_h1*(x_h1**2)}$."})

    is_up = "đồng biến" if a_h1 > 0 else "nghịch biến"
    pool_2.append({"q": f"Hàm số $y = {a_h1}x^2$ có tính chất nào sau đây?", "options": [f"A. Đồng biến khi $x > 0$" if a_h1>0 else f"A. Nghịch biến khi $x > 0$", f"B. Đồng biến khi $x < 0$" if a_h1>0 else f"B. Nghịch biến khi $x < 0$", "C. Luôn đồng biến trên $\mathbb{R}$", "D. Luôn nghịch biến trên $\mathbb{R}$"], "ans": "A", "exp": f"Vì hệ số $a = {a_h1}$, hàm số {is_up} khi $x > 0$."})

    opt, ans = make_opts("A(-1; 1) \\text{ và } B(2; 4)", "A(1; -1) \\text{ và } B(4; 2)", "A(-1; -1) \\text{ và } B(2; -4)", "A(1; 1) \\text{ và } B(2; 2)")
    pool_2.append({"q": "Dựa vào đồ thị dưới đây, tọa độ các giao điểm của parabol $(P): y = x^2$ và đường thẳng $(d): y = x + 2$ là:", "svg": svg_parabola_intersection("A(-1; 1)", "B(2; 4)"), "options": opt, "ans": ans, "exp": "Quan sát trên đồ thị, hai điểm cắt nhau rõ ràng tại $A(-1; 1)$ và $B(2; 4)$."})

    m_h4 = random.randint(2, 5)
    opt, ans = make_opts(m_h4-2, m_h4+2, 2-m_h4, 0)
    pool_2.append({"q": f"Đường thẳng $y = ({m_h4} - m)x + 3$ đi qua điểm $A(1; 5)$. Giá trị của $m$ là:", "options": opt, "ans": ans, "exp": f"Thay $x=1, y=5$ vào phương trình: $5 = {m_h4} - m + 3 \Leftrightarrow m = {m_h4} + 3 - 5 = {m_h4-2}$."})

    opt, ans = make_opts("-3", "3", "4", "-4")
    pool_2.append({"q": "Hệ số góc của đường thẳng $y = -3x + 4$ là:", "options": opt, "ans": ans, "exp": "Đường thẳng $y = ax + b$ có hệ số góc là $a$. Vậy hệ số góc là $-3$."})

    opt, ans = make_opts("m = \\pm 1", "m = 1", "m = -1", "m = 2")
    pool_2.append({"q": "Hai đường thẳng $y = 2x + 1$ và $y = (m^2+1)x + 3$ song song với nhau khi:", "options": opt, "ans": ans, "exp": "Điều kiện song song: Hệ số góc bằng nhau $\Rightarrow m^2 + 1 = 2 \Leftrightarrow m^2 = 1 \Leftrightarrow m = \\pm 1$."})

    a_h7 = random.choice([2, 4])
    opt, ans = make_opts(a_h7*4, -a_h7*4, a_h7*2, -a_h7*2)
    pool_2.append({"q": f"Giá trị của hàm số $y = {a_h7}x^2$ tại $x = -2$ là:", "options": opt, "ans": ans, "exp": f"Thay $x = -2 \Rightarrow y = {a_h7} \cdot (-2)^2 = {a_h7*4}$."})

    # --- POOL 3: PHƯƠNG TRÌNH & HỆ PHƯƠNG TRÌNH ---
    opt, ans = make_opts("(3; 2)", "(2; 3)", "(1; -2)", "(-3; -2)")
    pool_3.append({"q": "Nghiệm của hệ phương trình $\\begin{cases} 2x - y = 4 \\\\ x + y = 5 \end{cases}$ là:", "options": opt, "ans": ans, "exp": "Cộng vế theo vế ta được $3x = 9 \Rightarrow x = 3$. Thay vào pt (2) suy ra $y = 2$."})

    c_pt = random.randint(2, 6)
    opt, ans = make_opts(f"\\{{1; {c_pt}\\}}", f"\\{{-1; -{c_pt}\\}}", f"\\{{0; {c_pt}\\}}", f"\\{{1; -{c_pt}\\}}")
    pool_3.append({"q": f"Tập nghiệm của phương trình $x^2 - {(c_pt+1)}x + {c_pt} = 0$ là:", "options": opt, "ans": ans, "exp": f"Nhận thấy $a+b+c = 1 - {(c_pt+1)} + {c_pt} = 0$. Phương trình có nghiệm $x_1 = 1, x_2 = {c_pt}$."})

    S = random.randint(3, 9); P = random.randint(-8, 8)
    s_str = f"- {S}x" if S > 0 else f"+ {-S}x"
    p_str = f"+ {P}" if P > 0 else f"- {-P}"
    opt, ans = make_opts(S, -S, P, -P)
    pool_3.append({"q": f"Gọi $x_1, x_2$ là nghiệm của phương trình $x^2 {s_str} {p_str} = 0$. Giá trị của biểu thức $x_1 + x_2$ là:", "options": opt, "ans": ans, "exp": f"Theo hệ thức Vi-ét: $x_1 + x_2 = -\\frac{{b}}{{a}} = {S}$."})

    opt, ans = make_opts(P, -P, S, -S)
    pool_3.append({"q": f"Gọi $x_1, x_2$ là nghiệm của phương trình $x^2 {s_str} {p_str} = 0$. Giá trị của $x_1 \cdot x_2$ là:", "options": opt, "ans": ans, "exp": f"Theo hệ thức Vi-ét: $x_1 \cdot x_2 = \\frac{{c}}{{a}} = {P}$."})

    opt, ans = make_opts("4", "2", "0", "1")
    pool_3.append({"q": "Số nghiệm của phương trình $x^4 - 5x^2 + 4 = 0$ là:", "options": opt, "ans": ans, "exp": "Đặt $t = x^2 \\ge 0$, pt trở thành $t^2 - 5t + 4 = 0$. Có nghiệm $t=1$ và $t=4$. Từ đó suy ra $x = \\pm 1$ và $x = \\pm 2$. Vậy có 4 nghiệm."})

    opt, ans = make_opts("m = 4", "m = -4", "m = 2", "m = -2")
    pool_3.append({"q": "Điều kiện của tham số $m$ để phương trình $x^2 - 2x + m - 3 = 0$ có nghiệm kép là:", "options": opt, "ans": ans, "exp": "$\Delta' = (-1)^2 - 1(m-3) = 4 - m$. Để phương trình có nghiệm kép thì $\Delta' = 0 \Leftrightarrow m = 4$."})

    opt, ans = make_opts("7", "9", "11", "5")
    pool_3.append({"q": "Cho phương trình $x^2 - 3x + 1 = 0$ có hai nghiệm $x_1, x_2$. Giá trị của biểu thức $T = x_1^2 + x_2^2$ bằng:", "options": opt, "ans": ans, "exp": "Theo Vi-ét: $S = 3, P = 1$. Ta có $T = (x_1+x_2)^2 - 2x_1x_2 = 3^2 - 2(1) = 7$."})

    c_ng = random.randint(1, 5); ans_ng = "4" if c_ng+2 in [3,5,7] else "6"
    opt, ans = make_opts(ans_ng, "2", "8", "Vô số")
    pool_3.append({"q": f"Số cặp số nguyên $(x; y)$ thỏa mãn phương trình $x y - 2x - y = {c_ng}$ là:", "options": opt, "ans": ans, "exp": f"Biến đổi pt thành $x(y-2) - (y-2) = {c_ng+2} \Leftrightarrow (x-1)(y-2) = {c_ng+2}$. Dựa vào số ước nguyên của ${c_ng+2}$ để tìm số cặp."})

    # --- POOL 4: BẤT PHƯƠNG TRÌNH ---
    opt, ans = make_opts("x < 4", "x > 4", "x \\ge 4", "x \\le 4")
    pool_4.append({"q": "Tập nghiệm của bất phương trình $-3x + 12 > 0$ là:", "options": opt, "ans": ans, "exp": "$-3x > -12$. Chia hai vế cho số âm phải đổi chiều $\Rightarrow x < 4$."})
    
    opt, ans = make_opts("-2", "-1", "-3", "-4")
    pool_4.append({"q": "Nghiệm nguyên âm lớn nhất thỏa mãn bất phương trình $2x + 5 > 0$ là:", "options": opt, "ans": ans, "exp": "$2x > -5 \Leftrightarrow x > -2.5$. Số nguyên âm lớn nhất thỏa mãn là $-2$."})
    
    opt, ans = make_opts("m > \\frac{5}{2}", "m < \\frac{5}{2}", "m \\ge \\frac{5}{2}", "m \\neq \\frac{5}{2}")
    pool_4.append({"q": "Tìm tất cả các giá trị của tham số $m$ để hàm số $y = (5 - 2m)x + 1$ nghịch biến trên $\mathbb{R}$.", "options": opt, "ans": ans, "exp": "Hàm số nghịch biến khi hệ số góc $a < 0 \Leftrightarrow 5 - 2m < 0 \Leftrightarrow 2m > 5 \Leftrightarrow m > \\frac{5}{2}$."})
    
    opt, ans = make_opts("2", "1", "4", "0.5")
    pool_4.append({"q": "Cho $x, y > 0$ thỏa mãn $x+y=2$. Giá trị nhỏ nhất của biểu thức $P = \\frac{1}{x} + \\frac{1}{y}$ là:", "options": opt, "ans": ans, "exp": "Áp dụng BĐT $\\frac{1}{x} + \\frac{1}{y} \\ge \\frac{4}{x+y} = \\frac{4}{2} = 2$. Dấu = xảy ra khi $x=y=1$."})

    # --- POOL 5: HỆ THỨC LƯỢNG ---
    pool_5.append({"q": "Trong tam giác vuông, bình phương đường cao ứng với cạnh huyền bằng:", "options": ["A. Tích hai hình chiếu của hai cạnh góc vuông trên cạnh huyền", "B. Tích hai cạnh góc vuông", "C. Tích cạnh huyền và đường cao", "D. Tổng bình phương hai cạnh góc vuông"], "ans": "A", "exp": "Lý thuyết cơ bản: $h^2 = b' \cdot c'$."})
    
    opt, ans = make_opts("1", "0", "0.5", "2")
    pool_5.append({"q": "Giá trị của biểu thức $T = \cos^2 25^\circ + \cos^2 65^\circ$ bằng:", "options": opt, "ans": ans, "exp": "Vì hai góc phụ nhau nên $\cos 65^\circ = \sin 25^\circ$. Vậy $T = \cos^2 25^\circ + \sin^2 25^\circ = 1$."})
    
    b27 = random.randint(4, 15); g27 = random.choice([30, 45, 60]); h27 = round(b27 * math.tan(math.radians(g27)), 1)
    obj = random.choice(["tòa nhà", "cột cờ", "tháp hải đăng", "cái cây"])
    opt, ans = make_opts(f"{h27}m", f"{round(b27/math.tan(math.radians(g27)),1)}m", f"{round(b27*math.sin(math.radians(g27)),1)}m", f"{round(b27*math.cos(math.radians(g27)),1)}m")
    pool_5.append({"q": f"Bóng của một {obj} trên mặt đất dài ${b27}m$. Tia sáng mặt trời tạo với mặt đất một góc ${g27}^\circ$. Chiều cao của {obj} xấp xỉ bằng:", "svg": svg_building("? m", f"{b27}m", f"{g27}°"), "options": opt, "ans": ans, "exp": f"Chiều cao = Bóng $\\times \\tan({g27}^\circ) = {b27} \\times \\tan({g27}^\circ) \\approx {h27}m$."})
    
    l_bay = random.randint(4, 15); g_bay = random.choice([20, 25, 30]); h_bay = round(l_bay * math.sin(math.radians(g_bay)), 1)
    opt, ans = make_opts(f"{h_bay}km", f"{round(l_bay * math.cos(math.radians(g_bay)), 1)}km", f"{round(l_bay / math.sin(math.radians(g_bay)), 1)}km", f"{round(l_bay * math.tan(math.radians(g_bay)), 1)}km")
    pool_5.append({"q": f"Một chiếc máy bay cất cánh theo đường thẳng tạo với mặt đất góc ${g_bay}^\circ$. Sau khi bay được ${l_bay}km$, máy bay đang ở độ cao bao nhiêu km?", "svg": svg_right_triangle("Mặt đất", "? km", f"{l_bay}km", f"{g_bay}°", "Máy bay"), "options": opt, "ans": ans, "exp": f"Độ cao = Quãng đường $\\times \\sin({g_bay}^\circ) = {l_bay} \\times \\sin({g_bay}^\circ) \\approx {h_bay}km$."})
    
    h28 = random.choice([4, 6, 8])
    opt, ans = make_opts("60^\circ", "30^\circ", "45^\circ", "75^\circ")
    pool_5.append({"q": f"Một cái thang dài ${h28}m$ dựa vào tường. Biết chân thang cách tường ${int(h28/2)}m$. Góc tạo bởi thang và mặt đất là:", "svg": svg_ladder(f"{h28}m", f"{int(h28/2)}m", "? °"), "options": opt, "ans": ans, "exp": f"$\\cos \\alpha = \\frac{{{int(h28/2)}}}{{{h28}}} = \\frac{{1}}{{2}} \Rightarrow \\alpha = 60^\circ$."})
    
    c1, c2, ch = random.choice([(3,4,5), (6,8,10)])
    opt, ans = make_opts(f"\\frac{{{c1*c2}}}{{{ch}}}", f"\\frac{{{ch}}}{{2}}", f"\\frac{{{c1+c2}}}{{2}}", f"{c1+c2}")
    pool_5.append({"q": f"Cho $\Delta ABC$ vuông tại $A$, có $AB = {c1}cm, AC = {c2}cm$. Độ dài đường cao $AH$ là:", "options": opt, "ans": ans, "exp": f"Cạnh huyền $BC = {ch}$. $AH.BC = AB.AC \Rightarrow AH = \\frac{{{c1*c2}}}{{{ch}}}$."})

    # --- POOL 6: ĐƯỜNG TRÒN ---
    opt, ans = make_opts("90^\circ", "180^\circ", "60^\circ", "120^\circ")
    pool_6.append({"q": "Góc nội tiếp chắn nửa đường tròn có số đo là:", "options": opt, "ans": ans, "exp": "Tính chất SGK: Góc nội tiếp chắn nửa đường tròn là góc vuông ($90^\circ$)."})
    
    g_noi_tiep = random.choice([30, 45, 60])
    opt, ans = make_opts(f"{g_noi_tiep*2}^\circ", f"{g_noi_tiep}^\circ", f"{180-g_noi_tiep}^\circ", f"{90-g_noi_tiep}^\circ")
    pool_6.append({"q": f"Dựa vào hình vẽ bên dưới, biết góc nội tiếp $\widehat{{BAC}} = {g_noi_tiep}^\circ$. Số đo của góc ở tâm $\widehat{{BOC}}$ cùng chắn cung $BC$ là:", "svg": svg_circle_inscribed_angle(g_noi_tiep), "options": opt, "ans": ans, "exp": "Số đo góc ở tâm luôn gấp đôi số đo góc nội tiếp cùng chắn một cung."})
    
    opt, ans = make_opts("95^\circ", "85^\circ", "105^\circ", "15^\circ")
    pool_6.append({"q": "Tứ giác $ABCD$ nội tiếp đường tròn. Nếu góc $\widehat{A} = 85^\circ$ thì góc $\widehat{C}$ đối diện với nó bằng:", "options": opt, "ans": ans, "exp": "Trong tứ giác nội tiếp, tổng hai góc đối bằng $180^\circ \Rightarrow \widehat{C} = 180^\circ - 85^\circ = 95^\circ$."})
    
    r_tron = random.randint(4, 9)
    opt, ans = make_opts(f"{2*r_tron}\pi", f"{r_tron}\pi", f"{r_tron**2}\pi", f"{(r_tron**2)/2}\pi")
    pool_6.append({"q": f"Chu vi của đường tròn có bán kính $R = {r_tron}cm$ là:", "
