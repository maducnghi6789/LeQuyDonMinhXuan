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

# --- CẤU HÌNH HỆ THỐNG V37.1 (A1 SUPREME - FIX LỖI TYPO & CHUẨN HÓA LATEX) ---
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
    start_idx = res.find('[')
    end_idx = res.rfind(']')
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        res = res[start_idx:end_idx+1]
    res = re.sub(r',\s*]', ']', res)
    res = re.sub(r',\s*}', '}', res)
    return res

def format_math(text):
    if not isinstance(text, str): return text
    bt = chr(96)
    text = re.sub(bt + r'(.*?)' + bt, r'$\1$', text)
    text = text.replace('TEX_', '\\')
    text = text.replace('\\\\', '\\')
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
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY)''')
    user_cols = [("password", "TEXT"), ("role", "TEXT"), ("fullname", "TEXT"), ("dob", "TEXT"), ("class_name", "TEXT"), ("school", "TEXT"), ("managed_classes", "TEXT")]
    c.execute("PRAGMA table_info(users)")
    existing_u_cols = [row[1] for row in c.fetchall()]
    for col_name, col_type in user_cols:
        if col_name not in existing_u_cols:
            try: c.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
            except: pass
            
    c.execute('''CREATE TABLE IF NOT EXISTS system_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_exams (id INTEGER PRIMARY KEY AUTOINCREMENT)''')
    exam_cols = [("title", "TEXT"), ("questions_json", "TEXT"), ("time_limit", "INTEGER"), ("target_class", "TEXT"), ("created_by", "TEXT"), ("timestamp", "DATETIME DEFAULT CURRENT_TIMESTAMP")]
    c.execute("PRAGMA table_info(mandatory_exams)")
    existing_e_cols = [row[1] for row in c.fetchall()]
    for col_name, col_type in exam_cols:
        if col_name not in existing_e_cols:
            try: c.execute(f"ALTER TABLE mandatory_exams ADD COLUMN {col_name} {col_type}")
            except: pass

    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_results (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, exam_id INTEGER, score REAL, user_answers_json TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
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
# 3. QUẢN LÝ TÀI KHOẢN (GIỮ NGUYÊN)
# ==========================================
def account_manager_ui(target_role, specific_class=None):
    st.markdown(f"#### 🛠️ Quản lý {target_role}")
    conn = get_conn()
    query = "SELECT * FROM users WHERE role=?"
    params = [target_role]
    if specific_class and specific_class != "Tất cả các lớp": 
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
    else: st.info("Chưa có dữ liệu.")
    conn.close()

def import_student_module():
    st.markdown("### 📥 Nhập dữ liệu")
    t1, t2 = st.tabs(["📁 Nạp File Excel", "✍️ Nhập thủ công"])
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

# ==========================================
# 4. MODULE AI ĐỌC PDF (GIAO ĐỀ BẮT BUỘC)
# ==========================================
def extract_text_from_pdf(pdf_file):
    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
    text = ""
    for page in doc: text += page.get_text("text") + "\n"
    doc.close()
    return text

def parse_exam_with_ai(raw_text, api_key_string):
    if not api_key_string or not api_key_string.strip(): return "LỖI: Chưa nhập API Key."
    keys = [k.strip() for k in api_key_string.split(',') if k.strip()]
    random.shuffle(keys)
    prompt = f"""Trích xuất 40 câu trắc nghiệm Toán từ văn bản dưới đây.
    YÊU CẦU ĐỊNH DẠNG: Trả về mảng JSON Array: [{{"q": "...", "options": ["A.", "B.", "C.", "D."], "ans": "A", "exp": "..."}}]
    LƯU Ý: Bọc các công thức trong dấu $. Dùng nháy đơn (') bên trong chuỗi.
    VĂN BẢN:
    {raw_text}
    """
    last_err = ""
    for attempt in range(2):
        for current_key in keys:
            genai.configure(api_key=current_key)
            try:
                model = genai.GenerativeModel('gemini-1.5-flash')
                response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.2))
                raw_response = response.text.replace('TEX_', '\\')
                cleaned_text = clean_ai_json(raw_response)
                parsed_json = json.loads(cleaned_text)
                if isinstance(parsed_json, list) and len(parsed_json) > 0: return parsed_json
            except Exception as e:
                err_msg = str(e).lower()
                last_err = err_msg
                if "429" in err_msg or "quota" in err_msg: continue 
                elif "403" in err_msg or "api key" in err_msg: break
                else: continue
        if "429" in last_err or "quota" in last_err: time.sleep(5)
        else: break
    return f"LỖI TẠO ĐỀ TỪ PDF: Vui lòng kiểm tra lại API Key hoặc File PDF."

# ==========================================
# 5. BỘ CÔNG CỤ VẼ HÌNH ĐỘNG SVG (VECTOR GRAPHICS THEO NGỮ CẢNH)
# ==========================================
def svg_building(h_val, shadow_val, angle_val):
    return f"""
    <div style="display: flex; justify-content: center; margin: 15px 0;">
    <svg width="250" height="180" viewBox="0 0 250 180" xmlns="http://www.w3.org/2000/svg">
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
    <svg width="220" height="180" viewBox="0 0 220 180" xmlns="http://www.w3.org/2000/svg">
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
    <svg width="160" height="200" viewBox="0 0 160 200" xmlns="http://www.w3.org/2000/svg">
        <ellipse cx="80" cy="40" rx="60" ry="20" fill="#e2e8f0" stroke="#334155" stroke-width="2"/>
        <path d="M 20 40 L 20 160 A 60 20 0 0 0 140 160 L 140 40" fill="#f8fafc" stroke="#334155" stroke-width="2"/>
        <path d="M 20 160 A 60 20 0 0 1 140 160" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="5,5"/>
        <line x1="80" y1="40" x2="140" y2="40" stroke="#dc2626" stroke-width="2"/>
        <text x="100" y="35" font-family="Arial" font-size="14" font-weight="bold" fill="#dc2626">r={r_val}</text>
        <line x1="150" y1="40" x2="150" y2="160" stroke="#2563eb" stroke-width="2"/>
        <text x="155" y="105" font-family="Arial" font-size="14" font-weight="bold" fill="#2563eb">h={h_val}</text>
    </svg></div>
    """

def svg_cone(r_val, l_val):
    return f"""
    <div style="display: flex; justify-content: center; margin: 15px 0;">
    <svg width="180" height="200" viewBox="0 0 180 200" xmlns="http://www.w3.org/2000/svg">
        <path d="M 90 20 L 20 160 A 70 25 0 0 0 160 160 Z" fill="#f8fafc" stroke="#334155" stroke-width="2"/>
        <path d="M 20 160 A 70 25 0 0 1 160 160" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="5,5"/>
        <line x1="90" y1="160" x2="160" y2="160" stroke="#dc2626" stroke-width="2"/>
        <text x="110" y="155" font-family="Arial" font-size="14" font-weight="bold" fill="#dc2626">r={r_val}</text>
        <text x="135" y="90" font-family="Arial" font-size="14" font-weight="bold" fill="#0f172a">l={l_val}</text>
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
        if col >= 8:
            col = 0; row += 1
    box_h = 50 + row * 25
    return f"""
    <div style="display: flex; justify-content: center; margin: 15px 0;">
    <svg width="240" height="{box_h}" viewBox="0 0 240 {box_h}" xmlns="http://www.w3.org/2000/svg">
        <rect x="10" y="10" width="220" height="{box_h-20}" rx="8" style="fill:#f1f5f9;stroke:#64748b;stroke-width:2" stroke-dasharray="5,5" />
        {balls}
    </svg></div>
    """

# ==========================================
# 6. ĐỘNG CƠ THUẬT TOÁN ĐẢO SỐ (100% OFFLINE, 40 DẠNG ĐỘC LẬP)
# ==========================================
def generate_algorithmic_practice():
    questions = []
    
    def make_options(*args):
        # Đã FIX TÊN HÀM thành make_options đồng nhất
        opts = [f"${str(opt)}$" for opt in args]
        correct = opts[0]
        random.shuffle(opts)
        idx = opts.index(correct)
        labels = ["A.", "B.", "C.", "D."]
        return [f"{labels[i]} {opts[i]}" for i in range(4)], labels[idx]

    # --- CHƯƠNG 1: CĂN THỨC (6 DẠNG) ---
    a1 = random.randint(3, 9); b1 = random.randint(2, 5)
    q1_opts, q1_ans = make_options(a1-b1, a1+b1, b1-a1, -a1-b1)
    questions.append({
        "q": f"Tính giá trị của biểu thức $P = \sqrt{{{a1**2}}} - \sqrt{{{(-b1)**2}}}$",
        "options": q1_opts, "ans": q1_ans, "exp": f"$P = {a1} - |- {b1}| = {a1} - {b1} = {a1-b1}$."
    })
    
    m2 = random.randint(2, 5); n2 = random.randint(1, 9)
    q2_opts, q2_ans = make_options(f"x \\le \\frac{{{n2}}}{{{m2}}}", f"x \\ge \\frac{{{n2}}}{{{m2}}}", f"x < \\frac{{{n2}}}{{{m2}}}", f"x > \\frac{{{n2}}}{{{m2}}}")
    questions.append({
        "q": f"Biểu thức $\sqrt{{{n2} - {m2}x}}$ xác định khi và chỉ khi:",
        "options": q2_opts, "ans": q2_ans, "exp": f"${n2} - {m2}x \\ge 0 \Leftrightarrow {m2}x \\le {n2} \Leftrightarrow x \\le \\frac{{{n2}}}{{{m2}}}$."
    })

    k3 = random.choice([2, 3, 5, 7])
    q3_opts, q3_ans = make_options(f"2\sqrt{{{k3}}}", f"\sqrt{{{k3}}}", f"\\frac{{2}}{{\sqrt{{{k3}}}}}", f"{k3}\sqrt{{{k3}}}")
    questions.append({
        "q": f"Kết quả của phép trục căn thức ở mẫu $\\frac{{{k3*2}}}{{\sqrt{{{k3}}}}}$ là:",
        "options": q3_opts, "ans": q3_ans, "exp": f"Nhân cả tử và mẫu với $\sqrt{{{k3}}}$ ta được $\\frac{{{k3*2}\sqrt{{{k3}}}}}{{{k3}}} = 2\sqrt{{{k3}}}$."
    })

    questions.append({
        "q": "Khẳng định nào sau đây là đúng?",
        "options": ["A. $\sqrt{16} \cdot \sqrt{9} = 12$", "B. $\sqrt{16 + 9} = 7$", "C. $\sqrt{16} + \sqrt{9} = 5$", "D. $\sqrt{16 - 9} = \sqrt{7}$"], 
        "ans": "A", "exp": "Ta có $\sqrt{16} \cdot \sqrt{9} = 4 \cdot 3 = 12$."
    })

    p5 = random.randint(2, 6)
    q5_opts, q5_ans = make_options(f"\\frac{{{p5**2+1}}}{{2}}", f"\\frac{{{p5**2-1}}}{{2}}", f"{p5**2+1}", f"{p5**2-1}")
    questions.append({
        "q": f"Phương trình $\sqrt{{2x - 1}} = {p5}$ có nghiệm là:",
        "options": q5_opts, "ans": q5_ans, "exp": f"Bình phương hai vế: $2x - 1 = {p5**2} \Leftrightarrow 2x = {p5**2+1} \Leftrightarrow x = \\frac{{{p5**2+1}}}{{2}}$."
    })

    q6_opts, q6_ans = make_options("2\sqrt{5}-2", "2", "-2", "4\sqrt{5}")
    questions.append({
        "q": "Rút gọn biểu thức $M = \sqrt{(2-\sqrt{5})^2} + \sqrt{5}$",
        "options": q6_opts, "ans": q6_ans,
        "exp": "Vì $2 < \sqrt{5}$ nên $\sqrt{(2-\sqrt{5})^2} = |2-\sqrt{5}| = \sqrt{5}-2$. Vậy $M = \sqrt{5}-2 + \sqrt{5} = 2\sqrt{5}-2$."
    })

    # --- CHƯƠNG 2: HÀM SỐ & ĐỒ THỊ (6 DẠNG) ---
    a7 = random.choice([-3, -2, 2, 3])
    x7 = random.randint(1, 3)
    q7_opts, q7_ans = make_options(a7*(x7**2), -a7*(x7**2), a7*x7, -a7*x7)
    questions.append({
        "q": f"Biết điểm $A({x7}; y_0)$ thuộc đồ thị hàm số $y = {a7}x^2$. Giá trị của $y_0$ là:",
        "options": q7_opts, "ans": q7_ans, "exp": f"Thay $x = {x7}$ vào hàm số: $y_0 = {a7} \cdot ({x7})^2 = {a7*(x7**2)}$."
    })

    is_up8 = "đồng biến" if a7 > 0 else "nghịch biến"
    questions.append({
        "q": f"Hàm số $y = {a7}x^2$ có tính chất nào sau đây?",
        "options": [f"A. Đồng biến khi $x > 0$" if a7>0 else f"A. Nghịch biến khi $x > 0$", 
                    f"B. Đồng biến khi $x < 0$" if a7>0 else f"B. Nghịch biến khi $x < 0$",
                    "C. Luôn đồng biến trên $\mathbb{R}$", "D. Luôn nghịch biến trên $\mathbb{R}$"],
        "ans": "A", "exp": f"Vì hệ số $a = {a7}$, hàm số {is_up8} khi $x > 0$."
    })

    q9_opts, q9_ans = make_options("1", "2", "0", "Vô số")
    questions.append({
        "q": f"Đồ thị hàm số $y = x^2$ và đường thẳng $y = -2x - 1$ có bao nhiêu điểm chung?",
        "options": q9_opts, "ans": q9_ans,
        "exp": "Xét pt hoành độ giao điểm: $x^2 + 2x + 1 = 0 \Leftrightarrow (x+1)^2 = 0$. Pt có nghiệm kép nên có 1 điểm chung."
    })

    m10 = random.randint(2, 5)
    q10_opts, q10_ans = make_options(m10-2, m10+2, 2-m10, 0)
    questions.append({
        "q": f"Đường thẳng $y = ({m10} - m)x + 3$ đi qua điểm $A(1; 5)$. Giá trị của $m$ là:",
        "options": q10_opts, "ans": q10_ans,
        "exp": f"Thay $x=1, y=5$ vào phương trình: $5 = {m10} - m + 3 \Leftrightarrow m = {m10} + 3 - 5 = {m10-2}$."
    })

    q11_opts, q11_ans = make_options("-3", "3", "4", "-4")
    questions.append({
        "q": "Hệ số góc của đường thẳng $y = -3x + 4$ là:",
        "options": q11_opts, "ans": q11_ans,
        "exp": "Đường thẳng $y = ax + b$ có hệ số góc là $a$. Vậy hệ số góc là $-3$."
    })

    q12_opts, q12_ans = make_options("m = \\pm 1", "m = 1", "m = -1", "m = 2")
    questions.append({
        "q": "Hai đường thẳng $y = 2x + 1$ và $y = (m^2+1)x + 3$ song song với nhau khi:",
        "options": q12_opts, "ans": q12_ans,
        "exp": "Điều kiện song song: $m^2 + 1 = 2 \Leftrightarrow m^2 = 1 \Leftrightarrow m = \\pm 1$."
    })

    # --- CHƯƠNG 3: PHƯƠNG TRÌNH & HỆ PHƯƠNG TRÌNH (8 DẠNG) ---
    q13_opts, q13_ans = make_options("(3; 2)", "(2; 3)", "(1; -2)", "(-3; -2)")
    questions.append({
        "q": "Nghiệm của hệ phương trình $\\begin{cases} 2x - y = 4 \\\\ x + y = 5 \end{cases}$ là:",
        "options": q13_opts, "ans": q13_ans,
        "exp": "Cộng vế theo vế ta được $3x = 9 \Rightarrow x = 3$. Thay vào pt (2) suy ra $y = 2$."
    })

    c14 = random.randint(2, 6)
    q14_opts, q14_ans = make_options(f"\\{{1; {c14}\\}}", f"\\{{-1; -{c14}\\}}", f"\\{{0; {c14}\\}}", f"\\{{1; -{c14}\\}}")
    questions.append({
        "q": f"Tập nghiệm của phương trình $x^2 - {(c14+1)}x + {c14} = 0$ là:",
        "options": q14_opts, "ans": q14_ans,
        "exp": f"Nhận thấy $a+b+c = 1 - {(c14+1)} + {c14} = 0$. Phương trình có nghiệm $x_1 = 1, x_2 = {c14}$."
    })

    S15 = random.randint(3, 9); P15 = random.randint(-8, 8)
    s15_str = f"- {S15}x" if S15 > 0 else f"+ {-S15}x"
    p15_str = f"+ {P15}" if P15 > 0 else f"- {-P15}"
    q15_opts, q15_ans = make_options(S15, -S15, P15, -P15)
    questions.append({
        "q": f"Gọi $x_1, x_2$ là nghiệm của phương trình $x^2 {s15_str} {p15_str} = 0$. Giá trị của biểu thức $x_1 + x_2$ là:",
        "options": q15_opts, "ans": q15_ans,
        "exp": f"Theo hệ thức Vi-ét: $x_1 + x_2 = -\\frac{{b}}{{a}} = {S15}$."
    })

    q16_opts, q16_ans = make_options(P15, -P15, S15, -S15)
    questions.append({
        "q": f"Gọi $x_1, x_2$ là nghiệm của phương trình $x^2 {s15_str} {p15_str} = 0$. Giá trị của $x_1 \cdot x_2$ là:",
        "options": q16_opts, "ans": q16_ans,
        "exp": f"Theo hệ thức Vi-ét: $x_1 \cdot x_2 = \\frac{{c}}{{a}} = {P15}$."
    })

    q17_opts, q17_ans = make_options("4", "2", "0", "1")
    questions.append({
        "q": "Số nghiệm của phương trình $x^4 - 5x^2 + 4 = 0$ là:",
        "options": q17_opts, "ans": q17_ans,
        "exp": "Đặt $t = x^2 \\ge 0$, pt trở thành $t^2 - 5t + 4 = 0$. Có nghiệm $t=1$ và $t=4$. Từ đó suy ra $x = \\pm 1$ và $x = \\pm 2$. Vậy có 4 nghiệm."
    })

    q18_opts, q18_ans = make_options("m = 4", "m = -4", "m = 2", "m = -2")
    questions.append({
        "q": "Điều kiện của tham số $m$ để phương trình $x^2 - 2x + m - 3 = 0$ có nghiệm kép là:",
        "options": q18_opts, "ans": q18_ans,
        "exp": "$\Delta' = (-1)^2 - 1(m-3) = 4 - m$. Để phương trình có nghiệm kép thì $\Delta' = 0 \Leftrightarrow m = 4$."
    })

    q19_opts, q19_ans = make_options("7", "9", "11", "5")
    questions.append({
        "q": "Cho phương trình $x^2 - 3x + 1 = 0$ có hai nghiệm $x_1, x_2$. Giá trị của biểu thức $T = x_1^2 + x_2^2$ bằng:",
        "options": q19_opts, "ans": q19_ans,
        "exp": "Theo Vi-ét: $S = 3, P = 1$. Ta có $T = (x_1+x_2)^2 - 2x_1x_2 = 3^2 - 2(1) = 7$."
    })

    c20 = random.randint(1, 5)
    ans20 = "4" if c20+2 in [3,5,7] else "6"
    q20_opts, q20_ans = make_options(ans20, "2", "8", "Vô số")
    questions.append({
        "q": f"Số cặp số nguyên $(x; y)$ thỏa mãn phương trình $x y - 2x - y = {c20}$ là:",
        "options": q20_opts, "ans": q20_ans,
        "exp": f"Biến đổi pt thành $x(y-2) - (y-2) = {c20+2} \Leftrightarrow (x-1)(y-2) = {c20+2}$. Dựa vào số ước nguyên của ${c20+2}$ để tìm số cặp."
    })

    # --- CHƯƠNG 4: BẤT PHƯƠNG TRÌNH (4 DẠNG) ---
    q21_opts, q21_ans = make_options("x < 4", "x > 4", "x \\ge 4", "x \\le 4")
    questions.append({
        "q": "Tập nghiệm của bất phương trình $-3x + 12 > 0$ là:",
        "options": q21_opts, "ans": q21_ans,
        "exp": "$-3x > -12$. Chia hai vế cho số âm phải đổi chiều $\Rightarrow x < 4$."
    })
    
    q22_opts, q22_ans = make_options("-2", "-1", "-3", "-4")
    questions.append({
        "q": "Nghiệm nguyên âm lớn nhất thỏa mãn bất phương trình $2x + 5 > 0$ là:",
        "options": q22_opts, "ans": q22_ans,
        "exp": "$2x > -5 \Leftrightarrow x > -2.5$. Số nguyên âm lớn nhất thỏa mãn là $-2$."
    })
    
    q23_opts, q23_ans = make_options("m > \\frac{5}{2}", "m < \\frac{5}{2}", "m \\ge \\frac{5}{2}", "m \\neq \\frac{5}{2}")
    questions.append({
        "q": "Tìm tất cả các giá trị của tham số $m$ để hàm số $y = (5 - 2m)x + 1$ nghịch biến trên $\mathbb{R}$.",
        "options": q23_opts, "ans": q23_ans,
        "exp": "Hàm số nghịch biến khi hệ số góc $a < 0 \Leftrightarrow 5 - 2m < 0 \Leftrightarrow 2m > 5 \Leftrightarrow m > \\frac{5}{2}$."
    })
    
    q24_opts, q24_ans = make_options("2", "1", "4", "0.5")
    questions.append({
        "q": "Cho $x, y > 0$ thỏa mãn $x+y=2$. Giá trị nhỏ nhất của biểu thức $P = \\frac{1}{x} + \\frac{1}{y}$ là:",
        "options": q24_opts, "ans": q24_ans,
        "exp": "Áp dụng BĐT $\\frac{1}{x} + \\frac{1}{y} \\ge \\frac{4}{x+y} = \\frac{4}{2} = 2$. Dấu = xảy ra khi $x=y=1$."
    })

    # --- CHƯƠNG 5: HỆ THỨC LƯỢNG (5 DẠNG) ---
    questions.append({
        "q": "Trong tam giác vuông, bình phương đường cao ứng với cạnh huyền bằng:",
        "options": ["A. Tích hai hình chiếu của hai cạnh góc vuông trên cạnh huyền", "B. Tích hai cạnh góc vuông", "C. Tích cạnh huyền và đường cao", "D. Tổng bình phương hai cạnh góc vuông"],
        "ans": "A", "exp": "Lý thuyết cơ bản: $h^2 = b' \cdot c'$."
    })
    
    q26_opts, q26_ans = make_options("1", "0", "0.5", "2")
    questions.append({
        "q": "Giá trị của biểu thức $T = \cos^2 25^\circ + \cos^2 65^\circ$ bằng:",
        "options": q26_opts, "ans": q26_ans,
        "exp": "Vì hai góc phụ nhau nên $\cos 65^\circ = \sin 25^\circ$. Vậy $T = \cos^2 25^\circ + \sin^2 25^\circ = 1$."
    })
    
    obj_names = ["tòa nhà", "cột cờ", "tháp hải đăng", "cái cây"]
    obj = random.choice(obj_names)
    b27 = random.randint(4, 15); g27 = random.choice([30, 45, 60]); h27 = round(b27 * math.tan(math.radians(g27)), 1)
    q27_opts, q27_ans = make_options(f"{h27}m", f"{round(b27/math.tan(math.radians(g27)),1)}m", f"{round(b27*math.sin(math.radians(g27)),1)}m", f"{round(b27*math.cos(math.radians(g27)),1)}m")
    questions.append({
        "q": f"Bóng của một {obj} trên mặt đất dài ${b27}m$. Tia sáng mặt trời tạo với mặt đất một góc ${g27}^\circ$. Chiều cao của {obj} xấp xỉ bằng:",
        "svg": svg_building(h_val="? m", shadow_val=f"{b27}m", angle_val=f"{g27}°"),
        "options": q27_opts, "ans": q27_ans,
        "exp": f"Chiều cao = Bóng $\\times \\tan({g27}^\circ) = {b27} \\times \\tan({g27}^\circ) \\approx {h27}m$."
    })
    
    h28 = random.choice([4, 6, 8])
    q28_opts, q28_ans = make_options("60^\circ", "30^\circ", "45^\circ", "75^\circ")
    questions.append({
        "q": f"Một cái thang dài ${h28}m$ dựa vào tường. Biết chân thang cách tường ${int(h28/2)}m$. Góc tạo bởi thang và mặt đất là:",
        "svg": svg_ladder(ladder_val=f"{h28}m", dist_val=f"{int(h28/2)}m", angle_val="? °"),
        "options": q28_opts, "ans": q28_ans,
        "exp": f"Gọi $\\alpha$ là góc tạo bởi thang và mặt đất. $\\cos \\alpha = \\frac{{\\text{{kề}}}}{{\\text{{huyền}}}} = \\frac{{{int(h28/2)}}}{{{h28}}} = \\frac{{1}}{{2}} \Rightarrow \\alpha = 60^\circ$."
    })
    
    c29_1, c29_2, c29_h = random.choice([(3,4,5), (6,8,10)])
    q29_opts, q29_ans = make_options(f"\\frac{{{c29_1*c29_2}}}{{{c29_h}}}", f"\\frac{{{c29_h}}}{{2}}", f"\\frac{{{c29_1+c29_2}}}{{2}}", f"{c29_1+c29_2}")
    questions.append({
        "q": f"Cho $\Delta ABC$ vuông tại $A$, có $AB = {c29_1}cm, AC = {c29_2}cm$. Độ dài đường cao $AH$ là:",
        "options": q29_opts, "ans": q29_ans,
        "exp": f"Cạnh huyền $BC = {c29_h}$. Dùng hệ thức $AH.BC = AB.AC \Rightarrow AH = \\frac{{{c29_1*c29_2}}}{{{c29_h}}}$."
    })

    # --- CHƯƠNG 6: ĐƯỜNG TRÒN (6 DẠNG) ---
    q30_opts, q30_ans = make_options("90^\circ", "180^\circ", "60^\circ", "120^\circ")
    questions.append({
        "q": "Góc nội tiếp chắn nửa đường tròn có số đo là:",
        "options": q30_opts, "ans": q30_ans,
        "exp": "Tính chất SGK: Góc nội tiếp chắn nửa đường tròn là góc vuông ($90^\circ$)."
    })
    
    g31 = random.randint(60, 120)
    q31_opts, q31_ans = make_options(f"{g31}^\circ", f"{g31/2}^\circ", f"{180-g31}^\circ", f"{360-g31}^\circ")
    questions.append({
        "q": f"Cho đường tròn $(O)$, góc ở tâm $\widehat{{MON}} = {g31}^\circ$. Số đo cung nhỏ $MN$ là:",
        "options": q31_opts, "ans": q31_ans,
        "exp": "Số đo cung nhỏ bằng đúng số đo góc ở tâm chắn cung đó."
    })
    
    q32_opts, q32_ans = make_options("95^\circ", "85^\circ", "105^\circ", "15^\circ")
    questions.append({
        "q": "Tứ giác $ABCD$ nội tiếp đường tròn. Nếu góc $\widehat{A} = 85^\circ$ thì góc $\widehat{C}$ đối diện với nó bằng:",
        "options": q32_opts, "ans": q32_ans,
        "exp": "Trong tứ giác nội tiếp, tổng hai góc đối bằng $180^\circ \Rightarrow \widehat{C} = 180^\circ - 85^\circ = 95^\circ$."
    })
    
    r33, d33 = random.choice([(5, 8), (10, 16), (13, 24)])
    h33 = int(math.sqrt(r33**2 - (d33/2)**2))
    q33_opts, q33_ans = make_options(f"{h33}cm", f"{h33+1}cm", f"{h33-1}cm", f"{h33+2}cm")
    questions.append({
        "q": f"Cho đường tròn tâm $O$ bán kính ${r33}cm$ và dây cung $AB = {d33}cm$. Khoảng cách từ tâm $O$ đến dây $AB$ là:",
        "options": q33_opts, "ans": q33_ans,
        "exp": f"Gọi $H$ là trung điểm $AB \Rightarrow AH = {int(d33/2)}cm$. Áp dụng Pytago cho $\Delta OAH$: $OH = \sqrt{{{r33}^2 - {int(d33/2)}^2}} = {h33}cm$."
    })
    
    questions.append({
        "q": "Cho hai tiếp tuyến $AB$ và $AC$ cắt nhau tại $A$ (với $B, C$ là tiếp điểm). Khẳng định nào sau đây là ĐÚNG?",
        "options": ["A. $AB = AC$", "B. $AB \perp AC$", "C. $AB > AC$", "D. $AO \perp BC$ tại trọng tâm"], "ans": "A",
        "exp": "Theo tính chất hai tiếp tuyến cắt nhau, khoảng cách từ giao điểm đến hai tiếp điểm là bằng nhau."
    })
    
    questions.append({
        "q": "Cho đoạn thẳng $AB$ cố định. Quỹ tích các điểm $M$ nhìn đoạn $AB$ dưới một góc vuông là:",
        "options": ["A. Đường tròn đường kính AB", "B. Đường trung trực của AB", "C. Tia phân giác của góc vuông", "D. Đoạn thẳng AB"], "ans": "A",
        "exp": "Định lý cơ bản về quỹ tích cung chứa góc: Tập hợp các điểm nhìn đoạn thẳng dưới 1 góc vuông là đường tròn đường kính đoạn thẳng đó."
    })

    # --- CHƯƠNG 7: HÌNH KHỐI (3 DẠNG CÓ SVG) ---
    r36 = random.randint(2, 4); h36 = random.randint(5, 8)
    q36_opts, q36_ans = make_options(f"{2*r36*h36}\pi", f"{r36*h36}\pi", f"{r36**2 * h36}\pi", f"{4*r36*h36}\pi")
    questions.append({
        "q": f"Cho hình trụ có bán kính đáy $r = {r36}$ và chiều cao $h = {h36}$. Diện tích xung quanh của hình trụ là:",
        "svg": svg_cylinder(r_val=str(r36), h_val=str(h36)),
        "options": q36_opts, "ans": q36_ans,
        "exp": f"$S_{{xq}} = 2\pi r h = 2\pi({r36})({h36}) = {2*r36*h36}\pi$."
    })
    
    r37 = random.randint(3, 5); l37 = random.randint(6, 10)
    q37_opts, q37_ans = make_options(f"{r37*l37}\pi", f"{r37**2 * l37}\pi", f"{2*r37*l37}\pi", f"{(r37*l37)/3}\pi")
    questions.append({
        "q": f"Một hình nón có bán kính đáy $r = {r37}cm$, đường sinh $l = {l37}cm$. Diện tích xung quanh của hình nón là:",
        "svg": svg_cone(r_val=str(r37), l_val=str(l37)),
        "options": q37_opts, "ans": q37_ans,
        "exp": f"Công thức $S_{{xq}} = \pi r l = \pi \cdot {r37} \cdot {l37} = {r37*l37}\pi$."
    })
    
    questions.append({
        "q": "Thể tích của một hình cầu có bán kính $R$ được tính bằng công thức nào?",
        "options": ["A. $V = \\frac{4}{3}\pi R^3$", "B. $V = 4\pi R^2$", "C. $V = \\frac{1}{3}\pi R^3$", "D. $V = \pi R^3$"], "ans": "A",
        "exp": "Thể tích hình cầu bằng $\\frac{4}{3}\pi R^3$."
    })

    # --- CHƯƠNG 8: THỐNG KÊ XÁC SUẤT (2 DẠNG) ---
    color1, color2 = random.choice([("xanh", "đỏ"), ("vàng", "trắng"), ("đỏ", "trắng")])
    w39 = random.randint(3, 7); l39 = random.randint(4, 8); tot39 = w39 + l39
    q39_opts, q39_ans = make_options(f"\\frac{{{w39}}}{{{tot39}}}", f"\\frac{{{w39}}}{{{l39}}}", f"\\frac{{{l39}}}{{{tot39}}}", f"\\frac{{1}}{{{tot39}}}")
    questions.append({
        "q": f"Trong hộp có ${w39}$ quả bóng {color1} và ${l39}$ quả bóng {color2}. Lấy ngẫu nhiên 1 quả bóng. Xác suất lấy được bóng {color1} là:",
        "svg": svg_box_of_balls(color1, w39, color2, l39),
        "options": q39_opts, "ans": q39_ans,
        "exp": f"Xác suất = Tổng bóng {color1} / Tổng số bóng = $\\frac{{{w39}}}{{{tot39}}}$."
    })
    
    q40_opts, q40_ans = make_options("\\frac{1}{2}", "\\frac{1}{3}", "\\frac{1}{6}", "\\frac{2}{3}")
    questions.append({
        "q": "Gieo một con xúc xắc cân đối và đồng chất. Xác suất để xuất hiện mặt có số chấm là số nguyên tố bằng:",
        "options": q40_opts, "ans": q40_ans,
        "exp": "Số chấm là số nguyên tố thuộc tập $\{2; 3; 5\}$. Có 3 kết quả thuận lợi. Xác suất $P = \\frac{3}{6} = \\frac{1}{2}$."
    })

    random.shuffle(questions)
    return questions

# ==========================================
# 6. HIỂN THỊ TOÁN HỌC & GIAO DIỆN BÀI THI
# ==========================================
def render_exam_content(text):
    st.markdown(format_math(text), unsafe_allow_html=True)

def take_exam_ui(exam_data, exam_id, is_mandatory=True, is_review=False, user_ans_data=None):
    if is_review and user_ans_data:
        st.markdown(f"### 🔍 XEM LẠI BÀI: {exam_data.get('title')}")
        questions = exam_data['questions']
        correct_count = 0
        for i, q in enumerate(questions):
            ans = user_ans_data.get(str(i)) or user_ans_data.get(i)
            correct_char = q['ans'].strip()[0].upper()
            if ans and str(ans).strip().upper().startswith(correct_char):
                correct_count += 1
                
        st.success("🎉 **BẠN ĐANG XEM LẠI KẾT QUẢ BÀI THI!**")
        col1, col2 = st.columns(2)
        score = round((correct_count / len(questions)) * 10, 2)
        col1.metric("📌 TỔNG ĐIỂM", f"{score} / 10")
        col2.metric("🎯 SỐ CÂU ĐÚNG", f"{correct_count} / {len(questions)}")
        st.divider()
        
        st.markdown("### 📊 CHI TIẾT TỪNG CÂU & HƯỚNG DẪN GIẢI")
        for i, q in enumerate(questions):
            correct_char = q['ans'].strip()[0].upper()
            usr_choice = user_ans_data.get(str(i)) or user_ans_data.get(i)
            is_correct = False
            if usr_choice and str(usr_choice).strip().upper().startswith(correct_char):
                is_correct = True
                
            icon = "✅ ĐÚNG" if is_correct else "❌ SAI"
            with st.expander(f"Câu {i+1}: {icon} | Đáp án chuẩn: {q['ans']}"):
                render_exam_content(q['q'])
                if 'svg' in q and q['svg']:
                    st.markdown(q['svg'], unsafe_allow_html=True)
                formatted_choice = format_math(str(usr_choice)) if usr_choice else 'Không chọn'
                st.markdown(f"**Bạn đã chọn:** {formatted_choice}")
                if not is_correct: st.error("Câu trả lời chưa chính xác.")
                st.info(f"**Hướng dẫn:**\n{format_math(q.get('exp', 'Đang cập nhật...'))}")
                
        if st.button("⬅️ Trở về danh sách đề"):
            st.session_state.show_results = False
            st.session_state.current_exam_id = None
            st.session_state.taking_free_exam = None
            st.session_state.taking_exam = None
            st.session_state.review_mode = False
            st.rerun()
        return

    st.markdown(f"### 📝 LÀM BÀI: {exam_data.get('title', 'Luyện đề tự do')}")
    time_limit = exam_data.get('time_limit', 90)
    questions = exam_data['questions']
    
    if 'student_answers' not in st.session_state or st.session_state.get('current_exam_id') != exam_id:
        st.session_state.student_answers = {}
        st.session_state.current_exam_id = exam_id
        st.session_state.show_results = False
        st.session_state[f"submitted_{exam_id}"] = False 

    if not st.session_state.get('show_results'):
        timer_html = f"""
        <div style="position: fixed; top: 60px; right: 20px; background-color: #ff4b4b; color: white; padding: 10px 15px; border-radius: 8px; font-weight: bold; font-size: 16px; z-index: 9999; box-shadow: 2px 2px 10px rgba(0,0,0,0.5);">
            ⏳ CÒN LẠI: <span id="timer">{time_limit}:00</span>
        </div>
        <script>
            var limit = {time_limit} * 60 * 1000;
            var start = new Date().getTime();
            var x = setInterval(function() {{
                var now = new Date().getTime();
                var distance = limit - (now - start);
                var m = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
                var s = Math.floor((distance % (1000 * 60)) / 1000);
                document.getElementById("timer").innerHTML = m + "p " + s + "s ";
                if (distance < 0 && !window.submitted) {{
                    window.submitted = true;
                    clearInterval(x);
                    document.getElementById("timer").innerHTML = "HẾT GIỜ!";
                    var btns = window.parent.document.querySelectorAll('button');
                    btns.forEach(b => {{ if(b.innerText.includes('NỘP BÀI')) b.click(); }});
                }}
            }}, 1000);
        </script>
        """
        st.components.v1.html(timer_html, height=0)

        with st.form(f"exam_form_{exam_id}"):
            for i, q in enumerate(questions):
                st.markdown(f"**Câu {i+1}:**")
                render_exam_content(q['q'])
                if 'svg' in q and q['svg']:
                    st.markdown(q['svg'], unsafe_allow_html=True)
                formatted_options = [format_math(q_opt) for q_opt in q['options']]
                st.session_state.student_answers[i] = st.radio("Chọn đáp án:", formatted_options, index=None, key=f"q_{i}")
                st.divider()
            
            if st.form_submit_button("✅ NỘP BÀI / KẾT THÚC"):
                if not st.session_state.get(f"submitted_{exam_id}"):
                    st.session_state[f"submitted_{exam_id}"] = True
                    correct = 0
                    for i, q in enumerate(questions):
                        correct_char = q['ans'].strip()[0].upper()
                        usr_choice = st.session_state.student_answers.get(i) or st.session_state.student_answers.get(str(i))
                        if usr_choice and str(usr_choice).strip().upper().startswith(correct_char):
                            correct += 1
                    
                    score = round((correct / len(questions)) * 10, 2)
                    
                    if is_mandatory:
                        conn = get_conn()
                        ans_json = json.dumps(st.session_state.student_answers)
                        conn.execute("INSERT INTO mandatory_results (username, exam_id, score, user_answers_json) VALUES (?,?,?,?)", (st.session_state.current_user, exam_id, score, ans_json))
                        conn.commit(); conn.close()
                        
                    st.session_state.score = score
                    st.session_state.correct_count = correct
                    st.session_state.show_results = True
                    st.rerun()
                
    else:
        st.success("🎉 **BẠN ĐÃ HOÀN THÀNH BÀI THI! Bấm nút bên dưới để trở về.**")
        col1, col2 = st.columns(2)
        col1.metric("📌 TỔNG ĐIỂM", f"{st.session_state.score} / 10")
        col2.metric("🎯 SỐ CÂU ĐÚNG", f"{st.session_state.correct_count} / {len(questions)}")
        st.divider()
        
        if st.button("⬅️ Trở về danh sách đề"):
            st.session_state.show_results = False
            st.session_state.current_exam_id = None
            st.session_state.taking_free_exam = None
            st.session_state.taking_exam = None
            st.rerun()

# ==========================================
# 7. GIAO DIỆN ĐIỀU HƯỚNG CHÍNH
# ==========================================
def main():
    st.set_page_config(page_title="LMS Lê Quý Đôn", layout="wide")
    init_db()
    
    if 'current_user' not in st.session_state:
        st.markdown("<h2 style='text-align: center;'>🎓 HỆ THỐNG LMS LÊ QUÝ ĐÔN</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.2, 1])
        with col2:
            with st.form("login"):
                u = st.text_input("Tài khoản").strip(); p = st.text_input("Mật khẩu", type="password").strip()
                if st.form_submit_button("🚀 ĐĂNG NHẬP"):
                    conn = get_conn()
                    res = conn.execute("SELECT role, fullname, class_name, managed_classes, password FROM users WHERE username=?", (u,)).fetchone()
                    conn.close()
                    if res and p == res[4]:
                        st.session_state.current_user = u
                        st.session_state.role, st.session_state.fullname, st.session_state.class_name, st.session_state.managed = res[0], res[1], res[2], res[3]
                        st.rerun()
                    else: st.error("❌ Sai thông tin đăng nhập!")
    else:
        role = st.session_state.role
        with st.sidebar:
            st.markdown(f"### 👤 {st.session_state.fullname}")
            st.success(f"CẤP ĐỘ: {role.upper()}")
            
            if role == "core_admin":
                st.markdown("---")
                st.subheader("🔑 Cấu hình AI")
                api_key = get_api_key()
                new_key = st.text_input("Gemini API Key:", value=api_key, type="password")
                if st.button("💾 Lưu API"):
                    conn = get_conn()
                    conn.execute("INSERT OR REPLACE INTO system_settings VALUES ('GEMINI_API_KEY', ?)", (new_key.strip(),))
                    conn.commit(); conn.close(); st.success("✅ Đã lưu!")
            st.markdown("---")
            
            if role in ["core_admin", "sub_admin"]:
                menu = ["📤 Giao đề thi thử", "📊 Thống kê", "🔐 Cá nhân"]
                if role == "core_admin": menu = ["🛡️ Quản trị chung"] + menu
                elif role == "sub_admin": menu = ["👥 Quản lý khu vực"] + menu
            elif role == "student":
                menu = ["✍️ Kiểm tra bắt buộc", "🚀 Luyện đề tự do", "📊 Điểm số cá nhân", "🔐 Cá nhân"]
                
            choice = st.radio("Menu chính", menu)
            if st.button("🚪 Thoát", use_container_width=True): st.session_state.clear(); st.rerun()

        if role in ["core_admin", "sub_admin"]:
            conn = get_conn()
            c_stu = [r[0].strip() for r in conn.execute("SELECT DISTINCT class_name FROM users WHERE role='student' AND class_name != ''").fetchall()]
            c_man = []
            for r in conn.execute("SELECT managed_classes FROM users WHERE role='sub_admin'").fetchall():
                if r[0]: c_man.extend([x.strip() for x in r[0].split(',') if x.strip()])
            all_cl = sorted(list(set(c_stu + c_man)))
            conn.close()

        if choice == "🛡️ Quản trị chung":
            st.header("🛡️ Quản trị chung")
            t1, t2, t3, t4 = st.tabs(["👥 Admin thành viên", "🎓 Quản lý Học sinh", "📥 Nhập dữ liệu", "🚨 Xóa lớp học"])
            with t1:
                with st.form("add_sa"):
                    u_s, p_s, n_s, m_s = st.text_input("User"), st.text_input("Pass"), st.text_input("Tên"), st.text_input("Lớp (VD: 9A, 9E)")
                    if st.form_submit_button("Cấp quyền"):
                        conn = get_conn(); conn.execute("INSERT INTO users (username, password, role, fullname, managed_classes) VALUES (?,?,'sub_admin',?,?)", (u_s, p_s, n_s, m_s)); conn.commit(); st.success("Xong!"); st.rerun()
                account_manager_ui("sub_admin")
            with t2:
                sel = st.selectbox("Lớp:", ["Tất cả"] + all_cl)
                account_manager_ui("student", specific_class=sel if sel != "Tất cả" else None)
            with t3: import_student_module()
            with t4: delete_class_module(all_cl)

        elif choice == "👥 Quản lý khu vực":
            st.header("👥 Quản lý khu vực")
            conn = get_conn()
            st.session_state.managed = conn.execute("SELECT managed_classes FROM users WHERE username=?", (st.session_state.current_user,)).fetchone()[0]
            conn.close()
            my_cl = [x.strip() for x in st.session_state.managed.split(',')] if st.session_state.managed else []
            t1, t2 = st.tabs(["🎓 Danh sách học sinh", "📥 Nhập dữ liệu"])
            with t1:
                sel = st.selectbox("Chọn lớp:", ["Tất cả"] + my_cl)
                account_manager_ui("student", specific_class=sel if sel != "Tất cả" else (",".join(my_cl) if my_cl else "NONE"))
            with t2: import_student_module()

        elif choice == "📤 Giao đề thi thử":
            st.header("📤 Giao đề thi thử")
            api_key = get_api_key()
            if not api_key: st.error("❌ Hệ thống chưa cấu hình Gemini API Key.")
            else:
                target_classes = ["Tất cả các lớp"] + all_cl if role == "core_admin" else [x.strip() for x in st.session_state.managed.split(',')]
                with st.form("upload_pdf"):
                    e_title = st.text_input("Tên bài kiểm tra:")
                    e_class = st.selectbox("Giao bài cho lớp:", target_classes)
                    e_time = st.number_input("Thời gian (Phút):", min_value=15, value=90, step=5)
                    e_file = st.file_uploader("Tải Đề thi (PDF)", type="pdf")
                    if st.form_submit_button("🚀 BIÊN TẬP & GIAO ĐỀ"):
                        if e_title and e_file:
                            with st.spinner("Đang biên tập đề, xin đợi..."):
                                raw_txt = extract_text_from_pdf(e_file)
                                exam_res = parse_exam_with_ai(raw_txt, api_key)
                                if isinstance(exam_res, list):
                                    conn = get_conn()
                                    conn.execute("INSERT INTO mandatory_exams (title, questions_json, time_limit, target_class, created_by) VALUES (?,?,?,?,?)",
                                                 (e_title, json.dumps(exam_res), e_time, e_class, st.session_state.current_user))
                                    conn.commit(); conn.close()
                                    st.success(f"✅ Đã giao {len(exam_res)} câu hỏi cho lớp {e_class}!")
                                else: st.error(f"❌ {exam_res}")
                        else: st.warning("Vui lòng điền Tên bài và tải File!")

        elif choice == "📊 Thống kê":
            st.header("📊 Thống kê")
            conn = get_conn()
            if role == "core_admin":
                exams = conn.execute("SELECT id, title, target_class, questions_json FROM mandatory_exams").fetchall()
            else:
                classes_str = "', '".join([x.strip() for x in st.session_state.managed.split(',')])
                exams = conn.execute(f"SELECT id, title, target_class, questions_json FROM mandatory_exams WHERE target_class IN ('{classes_str}') OR target_class='Tất cả các lớp'").fetchall()
            if not exams: st.info("Chưa có bài thi nào được giao.")
            else:
                exam_dict = {f"[{e[2]}] {e[1]}": e for e in exams}
                sel_exam_name = st.selectbox("📌 Chọn đề thi để xem thống kê:", ["-- Chọn đề thi --"] + list(exam_dict.keys()))
                if sel_exam_name != "-- Chọn đề thi --":
                    exam_id, exam_title, target_class, q_json_str = exam_dict[sel_exam_name]
                    questions = json.loads(q_json_str)
                    num_questions = len(questions)
                    tb1, tb2, tb3 = st.tabs(["📋 Điểm số", "⚠️ Trốn thi", "📉 Phân tích câu hỏi"])
                    res_df = pd.read_sql_query("SELECT u.fullname AS 'Họ tên', u.username, u.class_name AS 'Lớp', r.score AS 'Điểm', r.user_answers_json FROM mandatory_results r JOIN users u ON r.username = u.username WHERE r.exam_id = ?", conn, params=(exam_id,))
                    with tb1:
                        if res_df.empty: st.info("Chưa có học sinh nào nộp bài.")
                        else: st.dataframe(res_df[['Họ tên', 'Lớp', 'Điểm']], use_container_width=True)
                    with tb2:
                        if target_class == "Tất cả các lớp":
                            if role == "core_admin": all_st = pd.read_sql_query("SELECT fullname, username, class_name FROM users WHERE role='student'", conn)
                            else: all_st = pd.read_sql_query(f"SELECT fullname, username, class_name FROM users WHERE role='student' AND class_name IN ('{classes_str}')", conn)
                        else: all_st = pd.read_sql_query("SELECT fullname, username, class_name FROM users WHERE role='student' AND class_name=?", conn, params=(target_class,))
                        if res_df.empty: missing_df = all_st
                        else:
                            submitted = res_df['username'].tolist()
                            missing_df = all_st[~all_st['username'].isin(submitted)]
                        if missing_df.empty: st.success("🎉 Tuyệt vời! 100% học sinh đã hoàn thành bài thi.")
                        else: st.warning(f"🚨 Có {len(missing_df)} học sinh chưa làm bài:"); st.dataframe(missing_df[['fullname', 'class_name', 'username']].rename(columns={'fullname':'Họ tên', 'class_name':'Lớp', 'username':'Tài khoản'}), use_container_width=True)
                    with tb3:
                        if res_df.empty: st.info("Chưa có dữ liệu để phân tích biểu đồ.")
                        else:
                            wrong_counts = {f"Câu {i+1}": 0 for i in range(num_questions)}
                            for idx, row in res_df.iterrows():
                                try:
                                    u_ans = json.loads(row['user_answers_json'])
                                    for i, q in enumerate(questions):
                                        correct_char = q['ans'].strip()[0].upper()
                                        user_choice = u_ans.get(str(i), u_ans.get(i, "")) 
                                        if not user_choice or not str(user_choice).strip().upper().startswith(correct_char): wrong_counts[f"Câu {i+1}"] += 1
                                except: pass
                            stat_df = pd.DataFrame(list(wrong_counts.items()), columns=['Câu hỏi', 'Số lượt sai'])
                            st.bar_chart(stat_df.set_index('Câu hỏi'))
            conn.close()

        elif choice == "✍️ Kiểm tra bắt buộc":
            st.header("✍️ Kiểm tra bắt buộc")
            conn = get_conn()
            student_class = st.session_state.class_name.strip() if st.session_state.class_name else ""
            exams = conn.execute("SELECT id, title, questions_json, time_limit FROM mandatory_exams WHERE trim(target_class)=? OR target_class='Tất cả các lớp'", (student_class,)).fetchall()
            if not exams: st.info("🎉 Hiện tại bạn chưa có bài kiểm tra nào được giao!")
            else:
                if st.session_state.get('taking_exam') is None:
                    for e_id, e_title, e_json, e_time in exams:
                        c1, c2 = st.columns([3, 1])
                        done = conn.execute("SELECT score, user_answers_json FROM mandatory_results WHERE username=? AND exam_id=?", (st.session_state.current_user, e_id)).fetchone()
                        if done: 
                            if c1.button(f"🔍 {e_title}", key=f"rev_{e_id}"):
                                st.session_state.taking_exam = {'id': e_id, 'title': e_title, 'time_limit': e_time, 'questions': json.loads(e_json)}
                                st.session_state.review_mode = True
                                st.session_state.review_data = json.loads(done[1])
                                st.rerun()
                            c2.success(f"Đã nộp: {done[0]} điểm")
                        else:
                            c1.markdown(f"**{e_title}**")
                            if c2.button("▶️ LÀM BÀI", key=f"btn_{e_id}"):
                                st.session_state.taking_exam = {'id': e_id, 'title': e_title, 'time_limit': e_time, 'questions': json.loads(e_json)}
                                st.session_state.review_mode = False
                                st.rerun()
                else: 
                    take_exam_ui(st.session_state.taking_exam, st.session_state.taking_exam['id'], True, st.session_state.get('review_mode', False), st.session_state.get('review_data'))
            conn.close()

        elif choice == "🚀 Luyện đề tự do":
            st.header("🚀 Luyện đề tự do") 
            if st.session_state.get('taking_free_exam') is None:
                if st.button("TẠO ĐỀ", type="primary"): 
                    with st.spinner("Đang tạo đề, xin đợi..."):
                        time.sleep(0.5) 
                        free_exam = generate_algorithmic_practice()
                        st.session_state.taking_free_exam = {'title': "Luyện đề tự do", 'time_limit': 90, 'questions': free_exam}
                        st.rerun()
            else:
                take_exam_ui(st.session_state.taking_free_exam, 9999, False)
                if st.button("❌ Hủy đề này"):
                    st.session_state.taking_free_exam = None
                    st.session_state.show_results = False
                    st.rerun()

        elif choice == "📊 Điểm số cá nhân":
            st.header("📊 Bảng điểm cá nhân")
            conn = get_conn()
            res = pd.read_sql_query("SELECT e.title AS 'Tên Bài', r.score AS 'Điểm', r.timestamp AS 'Ngày nộp' FROM mandatory_results r JOIN mandatory_exams e ON r.exam_id = e.id WHERE r.username=?", conn, params=(st.session_state.current_user,))
            st.dataframe(res, use_container_width=True)
            conn.close()
            
        elif choice == "🔐 Cá nhân":
            st.header("🔐 Cá nhân")
            st.info(f"Xin chào {st.session_state.fullname}!")

if __name__ == "__main__":
    main()
