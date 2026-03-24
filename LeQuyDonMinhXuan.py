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

# --- CẤU HÌNH HỆ THỐNG V36.1 (BẢN A1 SUPREME - FIX LỖI TOÁN HỌC) ---
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
        except:
            pass
        conn.commit(); conn.close()
    except: pass

# ==========================================
# 3. QUẢN LÝ NHÂN SỰ & HỌC SINH
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

def safe_ai_generate(prompt, api_key_string):
    if not api_key_string or not api_key_string.strip(): return "LỖI: Chưa nhập API Key."
    keys = [k.strip() for k in api_key_string.split(',') if k.strip()]
    random.shuffle(keys)
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

def parse_exam_with_ai(raw_text, api_key):
    prompt = f"""Trích xuất 40 câu trắc nghiệm Toán từ văn bản dưới đây.
    YÊU CẦU ĐỊNH DẠNG: Trả về mảng JSON Array: [{{"q": "...", "options": ["A.", "B.", "C.", "D."], "ans": "A", "exp": "..."}}]
    LƯU Ý: Bọc các công thức trong dấu $. Dùng nháy đơn (') bên trong chuỗi.
    VĂN BẢN:
    {raw_text}
    """
    return safe_ai_generate(prompt, api_key)

# ==========================================
# 5. BỘ CÔNG CỤ VẼ HÌNH ĐỘNG SVG (VECTOR GRAPHICS)
# ==========================================
def svg_right_triangle(base_label, height_label, hyp_label, angle_label, obj_name="Cây"):
    return f"""
    <div style="display: flex; justify-content: center; margin: 15px 0;">
    <svg width="220" height="160" viewBox="0 0 220 160" xmlns="http://www.w3.org/2000/svg">
        <polygon points="30,130 180,130 180,30" style="fill:#f8fafc;stroke:#334155;stroke-width:2" />
        <polyline points="170,130 170,120 180,120" style="fill:none;stroke:#334155;stroke-width:1.5" />
        <text x="90" y="148" font-family="Arial" font-size="14" font-weight="bold" fill="#0f172a">{base_label}</text>
        <text x="188" y="85" font-family="Arial" font-size="14" font-weight="bold" fill="#0f172a">{height_label}</text>
        <text x="80" y="70" font-family="Arial" font-size="14" font-weight="bold" fill="#0f172a" transform="rotate(-33 80 70)">{hyp_label}</text>
        <text x="55" y="125" font-family="Arial" font-size="13" font-weight="bold" fill="#dc2626">{angle_label}</text>
        <path d="M 60 130 A 30 30 0 0 0 50 115" fill="none" stroke="#dc2626" stroke-width="1.5"/>
    </svg>
    </div>
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
    </svg>
    </div>
    """

# ==========================================
# 5. ĐỘNG CƠ THUẬT TOÁN ĐẢO SỐ (100% OFFLINE)
# ==========================================
def generate_algorithmic_practice():
    exam = []
    
    def make_options(*args):
        opts = [f"${str(opt)}$" for opt in args]
        correct_val_formatted = opts[0]
        random.shuffle(opts)
        correct_opt_idx = opts.index(correct_val_formatted)
        labels = ["A.", "B.", "C.", "D."]
        ans_label = labels[correct_opt_idx]
        formatted_opts = [f"{labels[i]} {opts[i]}" for i in range(4)]
        return formatted_opts, ans_label

    # --- 1. CĂN THỨC (6 CÂU) ---
    a = random.randint(3, 11)
    b = random.randint(2, 5)
    exam.append({
        "q": f"Tính giá trị của biểu thức $P = \sqrt{{{a**2}}} - \sqrt{{{(-b)**2}}}$",
        "options": make_options(a-b, a+b, -a-b, b-a)[0], "ans": make_options(a-b, a+b, -a-b, b-a)[1],
        "exp": f"Ta có $P = {a} - |{-b}| = {a} - {b} = {a-b}$."
    })
    
    m = random.randint(2, 6); n = random.randint(1, 9)
    exam.append({
        "q": f"Biểu thức $\sqrt{{{n} - {m}x}}$ xác định khi và chỉ khi:",
        "options": make_options(f"x \le \\frac{{{n}}}{{{m}}}", f"x \ge \\frac{{{n}}}{{{m}}}", f"x < \\frac{{{n}}}{{{m}}}", f"x > \\frac{{{n}}}{{{m}}}")[0],
        "ans": make_options(f"x \le \\frac{{{n}}}{{{m}}}", f"x \ge \\frac{{{n}}}{{{m}}}", f"x < \\frac{{{n}}}{{{m}}}", f"x > \\frac{{{n}}}{{{m}}}")[1],
        "exp": f"Điều kiện: ${n} - {m}x \ge 0 \Leftrightarrow {m}x \le {n} \Leftrightarrow x \le \\frac{{{n}}}{{{m}}}$."
    })
    
    k = random.choice([2, 3, 5, 6, 7])
    exam.append({
        "q": f"Kết quả của phép trục căn thức ở mẫu $\\frac{{{k*2}}}{{\sqrt{{{k}}}}}$ là:",
        "options": make_options(f"2\sqrt{{{k}}}", f"\sqrt{{{k}}}", f"\\frac{{2}}{{\sqrt{{{k}}}}}", f"{k}\sqrt{{{k}}}")[0],
        "ans": make_options(f"2\sqrt{{{k}}}", f"\sqrt{{{k}}}", f"\\frac{{2}}{{\sqrt{{{k}}}}}", f"{k}\sqrt{{{k}}}")[1],
        "exp": f"$\\frac{{{k*2}}}{{\sqrt{{{k}}}}} = \\frac{{{k*2}\sqrt{{{k}}}}}{{{k}}} = 2\sqrt{{{k}}}$."
    })
    
    exam.append({
        "q": "Khẳng định nào sau đây là đúng?",
        "options": ["A. $\sqrt{16} + \sqrt{9} = 5$", "B. $\sqrt{16 + 9} = 7$", "C. $\sqrt{16} \cdot \sqrt{9} = 12$", "D. $\sqrt{16 - 9} = \sqrt{7}$"], 
        "ans": "C", "exp": "Ta có $\sqrt{16} \cdot \sqrt{9} = 4 \cdot 3 = 12$."
    })
    
    p = random.randint(2, 6)
    exam.append({
        "q": f"Phương trình $\sqrt{{2x - 1}} = {p}$ có nghiệm là:",
        "options": make_options(f"\\frac{{{p**2+1}}}{{2}}", f"\\frac{{{p**2-1}}}{{2}}", f"{p**2+1}", f"{p**2-1}")[0],
        "ans": make_options(f"\\frac{{{p**2+1}}}{{2}}", f"\\frac{{{p**2-1}}}{{2}}", f"{p**2+1}", f"{p**2-1}")[1],
        "exp": f"Bình phương hai vế: $2x - 1 = {p**2} \Leftrightarrow 2x = {p**2+1} \Leftrightarrow x = \\frac{{{p**2+1}}}{{2}}$."
    })
    
    exam.append({
        "q": "Rút gọn biểu thức $M = \sqrt{(2-\sqrt{5})^2} + \sqrt{5}$",
        "options": make_options("2\sqrt{5}-2", "2", "-2", "4\sqrt{5}")[0], "ans": make_options("2\sqrt{5}-2", "2", "-2", "4\sqrt{5}")[1],
        "exp": "Vì $2 < \sqrt{5}$ nên $\sqrt{(2-\sqrt{5})^2} = \sqrt{5}-2$. Vậy $M = \sqrt{5}-2 + \sqrt{5} = 2\sqrt{5}-2$."
    })

    # --- 2. HÀM SỐ y = ax^2 (3 CÂU) ---
    a2 = random.choice([-4, -2, 2, 4])
    x0 = random.randint(1, 3)
    exam.append({
        "q": f"Biết điểm $A({x0}; y_0)$ thuộc đồ thị hàm số $y = {a2}x^2$. Giá trị của $y_0$ là:",
        "options": make_options(a2*(x0**2), -a2*(x0**2), a2*x0, -a2*x0)[0],
        "ans": make_options(a2*(x0**2), -a2*(x0**2), a2*x0, -a2*x0)[1],
        "exp": f"Thay $x = {x0}$ vào hàm số: $y_0 = {a2} \cdot ({x0})^2 = {a2*(x0**2)}$."
    })
    
    is_up = "đồng biến" if a2 > 0 else "nghịch biến"
    exam.append({
        "q": f"Hàm số $y = {a2}x^2$ có tính chất nào sau đây?",
        "options": [f"A. Đồng biến khi $x > 0$" if a2>0 else f"A. Nghịch biến khi $x > 0$", 
                    f"B. Đồng biến khi $x < 0$" if a2>0 else f"B. Nghịch biến khi $x < 0$",
                    "C. Luôn đồng biến trên $\mathbb{R}$", "D. Luôn nghịch biến trên $\mathbb{R}$"],
        "ans": "A",
        "exp": f"Vì hệ số $a = {a2} {' > 0' if a2>0 else '< 0'}$, hàm số {is_up} khi $x > 0$."
    })
    
    exam.append({
        "q": f"Đồ thị hàm số $y = x^2$ và đường thẳng $y = -2x - 1$ có bao nhiêu điểm chung?",
        "options": make_options("1", "2", "0", "Vô số")[0], "ans": make_options("1", "2", "0", "Vô số")[1],
        "exp": "Xét pt hoành độ giao điểm: $x^2 + 2x + 1 = 0 \Leftrightarrow (x+1)^2 = 0$. Phương trình có nghiệm kép nên có 1 điểm chung."
    })

    # --- 3. PHƯƠNG TRÌNH & HỆ PHƯƠNG TRÌNH (8 CÂU) ---
    c_pt = random.randint(2, 6)
    exam.append({
        "q": f"Tập nghiệm của phương trình $x^2 - {(c_pt+1)}x + {c_pt} = 0$ là:",
        "options": make_options(f"\\{{1; {c_pt}\\}}", f"\\{{-1; -{c_pt}\\}}", f"\\{{0; {c_pt}\\}}", f"\\{{1; -{c_pt}\\}}")[0], 
        "ans": make_options(f"\\{{1; {c_pt}\\}}", f"\\{{-1; -{c_pt}\\}}", f"\\{{0; {c_pt}\\}}", f"\\{{1; -{c_pt}\\}}")[1],
        "exp": f"Nhận thấy $a+b+c = 1 - {(c_pt+1)} + {c_pt} = 0$. Phương trình có nghiệm $x_1 = 1, x_2 = {c_pt}$."
    })
    
    S = random.randint(3, 9)
    P = random.randint(-10, 10)
    s_str = f"- {S}x" if S > 0 else f"+ {-S}x"
    p_str = f"+ {P}" if P > 0 else f"- {-P}"
    exam.append({
        "q": f"Gọi $x_1, x_2$ là nghiệm của phương trình $x^2 {s_str} {p_str} = 0$. Giá trị của biểu thức $x_1 + x_2$ là:",
        "options": make_options(S, -S, P, -P)[0], "ans": make_options(S, -S, P, -P)[1],
        "exp": f"Theo hệ thức Vi-ét: $x_1 + x_2 = -\\frac{{b}}{{a}} = {S}$."
    })
    
    exam.append({
        "q": f"Gọi $x_1, x_2$ là nghiệm của phương trình $x^2 {s_str} {p_str} = 0$. Giá trị của $x_1 \cdot x_2$ là:",
        "options": make_options(P, -P, S, -S)[0], "ans": make_options(P, -P, S, -S)[1],
        "exp": f"Theo hệ thức Vi-ét: $x_1 \cdot x_2 = \\frac{{c}}{{a}} = {P}$."
    })
    
    exam.append({
        "q": "Nghiệm của hệ phương trình $\\begin{cases} 2x - y = 4 \\\\ x + y = 5 \end{cases}$ là:",
        "options": make_options("(3; 2)", "(2; 3)", "(1; -2)", "(-3; -2)")[0], "ans": make_options("(3; 2)", "(2; 3)", "(1; -2)", "(-3; -2)")[1],
        "exp": "Cộng vế theo vế ta được $3x = 9 \Rightarrow x = 3$. Thay vào pt (2) suy ra $y = 2$."
    })
    
    exam.append({
        "q": "Số nghiệm của phương trình $x^4 - 5x^2 + 4 = 0$ là:",
        "options": make_options("4", "2", "0", "1")[0], "ans": make_options("4", "2", "0", "1")[1],
        "exp": "Đặt $t = x^2 \ge 0$, pt trở thành $t^2 - 5t + 4 = 0$. Có nghiệm $t=1$ và $t=4$. Từ đó suy ra $x = \pm 1$ và $x = \pm 2$. Vậy có 4 nghiệm."
    })
    
    exam.append({
        "q": "Điều kiện của tham số $m$ để phương trình $x^2 - 2x + m - 3 = 0$ có nghiệm kép là:",
        "options": make_options("m = 4", "m = -4", "m = 2", "m = -2")[0], "ans": make_options("m = 4", "m = -4", "m = 2", "m = -2")[1],
        "exp": "$\Delta' = (-1)^2 - 1(m-3) = 4 - m$. Để phương trình có nghiệm kép thì $\Delta' = 0 \Leftrightarrow m = 4$."
    })
    
    exam.append({
        "q": "Cho phương trình $x^2 - 3x + 1 = 0$ có hai nghiệm $x_1, x_2$. Giá trị của biểu thức $T = x_1^2 + x_2^2$ bằng:",
        "options": make_options("7", "9", "11", "5")[0], "ans": make_options("7", "9", "11", "5")[1],
        "exp": "Theo Vi-ét: $S = 3, P = 1$. Ta có $T = S^2 - 2P = 3^2 - 2(1) = 7$."
    })
    
    c_nguyen = random.randint(1, 5)
    exam.append({
        "q": f"Số cặp nghiệm nguyên $(x; y)$ thỏa mãn phương trình $x y - 2x - y = {c_nguyen}$ là:",
        "options": make_options("4" if c_nguyen+2 in [3,5,7] else "6", "2", "8", "Vô số")[0], 
        "ans": make_options("4" if c_nguyen+2 in [3,5,7] else "6", "2", "8", "Vô số")[1],
        "exp": f"Biến đổi pt thành $x(y-2) - (y-2) = {c_nguyen+2} \Leftrightarrow (x-1)(y-2) = {c_nguyen+2}$. Dựa vào số ước nguyên của ${c_nguyen+2}$ để tìm số cặp nghiệm."
    })

    # --- 4. BẤT PHƯƠNG TRÌNH (3 CÂU) ---
    exam.append({
        "q": "Tập nghiệm của bất phương trình $-3x + 12 > 0$ là:",
        "options": make_options("x < 4", "x > 4", "x \ge 4", "x \le 4")[0], "ans": make_options("x < 4", "x > 4", "x \ge 4", "x \le 4")[1],
        "exp": "$-3x > -12$. Chia hai vế cho số âm phải đổi chiều $\Rightarrow x < 4$."
    })
    
    exam.append({
        "q": "Nghiệm nguyên âm lớn nhất thỏa mãn bất phương trình $2x + 5 > 0$ là:",
        "options": make_options("-2", "-1", "-3", "-4")[0], "ans": make_options("-2", "-1", "-3", "-4")[1],
        "exp": "$2x > -5 \Leftrightarrow x > -2.5$. Số nguyên âm lớn nhất thỏa mãn là $-2$."
    })
    
    exam.append({
        "q": "Tìm tất cả các giá trị của tham số $m$ để hàm số $y = (5 - 2m)x + 1$ nghịch biến trên $\mathbb{R}$.",
        "options": make_options("m > \\frac{5}{2}", "m < \\frac{5}{2}", "m \ge \\frac{5}{2}", "m \neq \\frac{5}{2}")[0], 
        "ans": make_options("m > \\frac{5}{2}", "m < \\frac{5}{2}", "m \ge \\frac{5}{2}", "m \neq \\frac{5}{2}")[1],
        "exp": "Hàm số nghịch biến khi hệ số góc $a < 0 \Leftrightarrow 5 - 2m < 0 \Leftrightarrow 2m > 5 \Leftrightarrow m > \\frac{5}{2}$."
    })

    # --- 5. HỆ THỨC LƯỢNG (5 CÂU KÈM HÌNH ẢNH DYNAMIC SVG) ---
    exam.append({
        "q": "Trong tam giác vuông, bình phương đường cao ứng với cạnh huyền bằng:",
        "options": ["A. Tích hai hình chiếu của hai cạnh góc vuông trên cạnh huyền", "B. Tích hai cạnh góc vuông", "C. Tích cạnh huyền và đường cao", "D. Tổng bình phương hai cạnh góc vuông"],
        "ans": "A", "exp": "Lý thuyết cơ bản: $h^2 = b' \cdot c'$."
    })
    
    obj_names = ["tòa nhà", "cột cờ", "tháp hải đăng", "cái cây"]
    obj = random.choice(obj_names)
    b_obj = random.randint(4, 15)
    g_obj = random.choice([30, 45, 60])
    h_obj = round(b_obj * math.tan(math.radians(g_obj)), 1)
    exam.append({
        "q": f"Bóng của một {obj} trên mặt đất dài ${b_obj}m$. Tia sáng mặt trời tạo với mặt đất một góc ${g_obj}^\circ$. Chiều cao của {obj} xấp xỉ bằng:",
        "svg": svg_right_triangle(base_label=f"{b_obj}m", height_label="? m", hyp_label="Tia sáng", angle_label=f"{g_obj}°", obj_name=obj),
        "options": make_options(f"{h_obj}m", f"{round(b_obj/math.tan(math.radians(g_obj)),1)}m", f"{round(b_obj*math.sin(math.radians(g_obj)),1)}m", f"{round(b_obj*math.cos(math.radians(g_obj)),1)}m")[0],
        "ans": make_options(f"{h_obj}m", f"{round(b_obj/math.tan(math.radians(g_obj)),1)}m", f"{round(b_obj*math.sin(math.radians(g_obj)),1)}m", f"{round(b_obj*math.cos(math.radians(g_obj)),1)}m")[1],
        "exp": f"Áp dụng tỉ số lượng giác: Chiều cao = Bóng $\\times \\tan({g_obj}^\circ) = {b_obj} \\times \\tan({g_obj}^\circ) \approx {h_obj}m$."
    })
    
    l_bay = random.randint(4, 15)
    g_bay = random.choice([20, 25, 30])
    h_bay = round(l_bay * math.sin(math.radians(g_bay)), 1)
    exam.append({
        "q": f"Một chiếc máy bay cất cánh theo đường thẳng tạo với mặt đất góc ${g_bay}^\circ$. Sau khi bay được ${l_bay}km$, máy bay đang ở độ cao bao nhiêu km?",
        "svg": svg_right_triangle(base_label="Mặt đất", height_label="? km", hyp_label=f"{l_bay}km", angle_label=f"{g_bay}°", obj_name="Máy bay"),
        "options": make_options(f"{h_bay}", f"{round(l_bay * math.cos(math.radians(g_bay)), 1)}", f"{round(l_bay / math.sin(math.radians(g_bay)), 1)}", f"{round(l_bay * math.tan(math.radians(g_bay)), 1)}")[0],
        "ans": make_options(f"{h_bay}", f"{round(l_bay * math.cos(math.radians(g_bay)), 1)}", f"{round(l_bay / math.sin(math.radians(g_bay)), 1)}", f"{round(l_bay * math.tan(math.radians(g_bay)), 1)}")[1],
        "exp": f"Độ cao = Quãng đường $\\times \\sin({g_bay}^\circ) = {l_bay} \\times \\sin({g_bay}^\circ) \approx {h_bay}km$."
    })
    
    h_thang = random.randint(4, 10)
    exam.append({
        "q": f"Một cái thang dài ${h_thang}m$ dựa vào tường. Biết chân thang cách tường ${h_thang/2}m$. Góc tạo bởi thang và mặt đất là:",
        "svg": svg_right_triangle(base_label=f"{h_thang/2}m", height_label="Tường", hyp_label=f"{h_thang}m", angle_label="? °", obj_name="Thang"),
        "options": make_options("60^\circ", "30^\circ", "45^\circ", "75^\circ")[0],
        "ans": make_options("60^\circ", "30^\circ", "45^\circ", "75^\circ")[1],
        "exp": f"Gọi $\\alpha$ là góc tạo bởi thang và mặt đất. $\\cos \\alpha = \\frac{{\\text{{kề}}}}{{\\text{{huyền}}}} = \\frac{{{h_thang/2}}}{{{h_thang}}} = \\frac{{1}}{{2}} \Rightarrow \\alpha = 60^\circ$."
    })

    exam.append({
        "q": "Giá trị của biểu thức $T = \cos^2 25^\circ + \cos^2 65^\circ$ bằng:",
        "options": make_options("1", "0", "0.5", "2")[0], "ans": make_options("1", "0", "0.5", "2")[1],
        "exp": "Vì hai góc phụ nhau nên $\cos 65^\circ = \sin 25^\circ$. Vậy $T = \cos^2 25^\circ + \sin^2 25^\circ = 1$."
    })

    # --- 6. ĐƯỜNG TRÒN (6 CÂU) ---
    exam.append({
        "q": "Góc nội tiếp chắn nửa đường tròn có số đo là:",
        "options": make_options("90^\circ", "180^\circ", "60^\circ", "120^\circ")[0], "ans": make_options("90^\circ", "180^\circ", "60^\circ", "120^\circ")[1],
        "exp": "Tính chất SGK: Góc nội tiếp chắn nửa đường tròn là góc vuông ($90^\circ$)."
    })
    
    g_tam = random.randint(60, 120)
    exam.append({
        "q": f"Cho đường tròn $(O)$, góc ở tâm $\widehat{{MON}} = {g_tam}^\circ$. Số đo cung nhỏ $MN$ là:",
        "options": make_options(f"{g_tam}^\circ", f"{g_tam/2}^\circ", f"{180-g_tam}^\circ", f"{360-g_tam}^\circ")[0],
        "ans": make_options(f"{g_tam}^\circ", f"{g_tam/2}^\circ", f"{180-g_tam}^\circ", f"{360-g_tam}^\circ")[1],
        "exp": "Số đo cung nhỏ bằng đúng số đo góc ở tâm chắn cung đó."
    })
    
    exam.append({
        "q": "Tứ giác $ABCD$ nội tiếp đường tròn. Nếu góc $\widehat{A} = 85^\circ$ thì góc $\widehat{C}$ đối diện với nó bằng:",
        "options": make_options("95^\circ", "85^\circ", "105^\circ", "15^\circ")[0], "ans": make_options("95^\circ", "85^\circ", "105^\circ", "15^\circ")[1],
        "exp": "Trong tứ giác nội tiếp, tổng hai góc đối bằng $180^\circ \Rightarrow \widehat{C} = 180^\circ - 85^\circ = 95^\circ$."
    })
    
    r_tron = random.randint(4, 9)
    exam.append({
        "q": f"Chu vi của đường tròn có bán kính $R = {r_tron}cm$ là:",
        "options": make_options(f"{2*r_tron}\pi", f"{r_tron}\pi", f"{r_tron**2}\pi", f"{(r_tron**2)/2}\pi")[0],
        "ans": make_options(f"{2*r_tron}\pi", f"{r_tron}\pi", f"{r_tron**2}\pi", f"{(r_tron**2)/2}\pi")[1],
        "exp": f"Chu vi $C = 2\pi R = 2\pi({r_tron}) = {2*r_tron}\pi$."
    })
    
    # [FIX LỖI TOÁN HỌC DÂY CUNG]: Lấy từ bộ số Pytago để đảm bảo R > d/2
    r_tron2, d_day = random.choice([(5, 6), (5, 8), (10, 12), (10, 16), (13, 10), (13, 24)])
    h_kc = math.sqrt(r_tron2**2 - (d_day/2)**2)
    exam.append({
        "q": f"Cho đường tròn tâm $O$ bán kính ${r_tron2}cm$ và dây cung $AB = {d_day}cm$. Khoảng cách từ tâm $O$ đến dây $AB$ là:",
        "options": make_options(f"{int(h_kc)}cm", f"{int(h_kc)+1}cm", f"{int(h_kc)-1}cm", f"{int(h_kc)+2}cm")[0], 
        "ans": make_options(f"{int(h_kc)}cm", f"{int(h_kc)+1}cm", f"{int(h_kc)-1}cm", f"{int(h_kc)+2}cm")[1],
        "exp": f"Gọi $H$ là trung điểm $AB \Rightarrow AH = {d_day/2}cm$. Áp dụng Pytago cho $\Delta OAH$: $OH = \sqrt{{{r_tron2}^2 - {(d_day/2)}^2}} = {int(h_kc)}cm$."
    })
    
    exam.append({
        "q": "Cho hai tiếp tuyến $AB$ và $AC$ cắt nhau tại $A$ (với $B, C$ là tiếp điểm). Khẳng định nào sau đây là ĐÚNG?",
        "options": ["A. $AB = AC$", "B. $AB \perp AC$", "C. $AB > AC$", "D. $AO \perp BC$ tại trọng tâm"], "ans": "A",
        "exp": "Theo tính chất hai tiếp tuyến cắt nhau, khoảng cách từ giao điểm đến hai tiếp điểm là bằng nhau."
    })

    # --- 7. HÌNH KHỐI (3 CÂU) ---
    exam.append({
        "q": "Công thức tính diện tích toàn phần của hình trụ có bán kính đáy $r$ và chiều cao $h$ là:",
        "options": ["A. $S_{tp} = 2\pi r h + 2\pi r^2$", "B. $S_{tp} = \pi r^2 h$", "C. $S_{tp} = \pi r l + \pi r^2$", "D. $S_{tp} = 4\pi r^2$"], "ans": "A",
        "exp": "Diện tích toàn phần bằng tổng diện tích xung quanh và diện tích hai đáy: $2\pi r h + 2\pi r^2$."
    })
    
    r_non = random.randint(3, 5); l_non = random.randint(6, 10)
    exam.append({
        "q": f"Một hình nón có bán kính đáy $r = {r_non}cm$, đường sinh $l = {l_non}cm$. Diện tích xung quanh của hình nón là:",
        "options": make_options(f"{r_non*l_non}\pi", f"{r_non**2 * l_non}\pi", f"{2*r_non*l_non}\pi", f"{(r_non*l_non)/3}\pi")[0],
        "ans": make_options(f"{r_non*l_non}\pi", f"{r_non**2 * l_non}\pi", f"{2*r_non*l_non}\pi", f"{(r_non*l_non)/3}\pi")[1],
        "exp": f"Công thức $S_{{xq}} = \pi r l = \pi \cdot {r_non} \cdot {l_non} = {r_non*l_non}\pi$."
    })
    
    exam.append({
        "q": "Thể tích của một hình cầu có bán kính $R$ được tính bằng công thức nào?",
        "options": ["A. $V = \\frac{4}{3}\pi R^3$", "B. $V = 4\pi R^2$", "C. $V = \\frac{1}{3}\pi R^3$", "D. $V = \pi R^3$"], "ans": "A",
        "exp": "Thể tích hình cầu bằng $\\frac{4}{3}\pi R^3$."
    })

    # --- 8. THỐNG KÊ XÁC SUẤT (6 CÂU KÈM HÌNH HỘP BÓNG SVG) ---
    c_list = [("xanh", "đỏ"), ("vàng", "trắng"), ("đỏ", "trắng"), ("xanh", "vàng")]
    
    for _ in range(5):
        color1, color2 = random.choice(c_list)
        win = random.randint(3, 8)
        lose = random.randint(4, 10)
        total = win + lose
        
        q = f"Trong một chiếc hộp kín có chứa ${win}$ quả bóng màu {color1} và ${lose}$ quả bóng màu {color2} (kích thước giống hệt nhau). Lấy ngẫu nhiên 1 quả bóng. Xác suất lấy được bóng màu {color1} là:"
        opts, ans = make_options(f"\\frac{{{win}}}{{{total}}}", f"\\frac{{{win}}}{{{lose}}}", f"\\frac{{{lose}}}{{{total}}}", f"\\frac{{1}}{{{total}}}")
        
        exam.append({
            "q": q, 
            "svg": svg_box_of_balls(color1, win, color2, lose),
            "options": opts, "ans": ans, 
            "exp": f"Xác suất $P = \\frac{{\\text{{Số bóng {color1}}}}}{{\\text{{Tổng số bóng}}}} = \\frac{{{win}}}{{{win} + {lose}}} = \\frac{{{win}}}{{{total}}}$"
        })
    
    exam.append({
        "q": "Gieo một con xúc xắc cân đối và đồng chất. Xác suất để xuất hiện mặt có số chấm là số nguyên tố bằng:",
        "options": make_options("\\frac{1}{2}", "\\frac{1}{3}", "\\frac{1}{6}", "\\frac{2}{3}")[0],
        "ans": make_options("\\frac{1}{2}", "\\frac{1}{3}", "\\frac{1}{6}", "\\frac{2}{3}")[1],
        "exp": "Số chấm là số nguyên tố thuộc tập $\{2; 3; 5\}$. Có 3 kết quả thuận lợi. Xác suất $P = \\frac{3}{6} = \\frac{1}{2}$."
    })

    random.shuffle(exam)
    return exam[:40]

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
                # RENDERING SVG NGAY TẠI ĐÂY NẾU CÓ
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
                # RENDERING SVG NGAY TẠI ĐÂY NẾU CÓ
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
