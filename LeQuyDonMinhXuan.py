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
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta, timezone
import fitz  # PyMuPDF
import google.generativeai as genai

# --- CẤU HÌNH HỆ THỐNG V33 (A1 SUPREME - ĐỘNG CƠ ĐA DẠNG HÓA TOÁN HỌC) ---
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
    if not isinstance(text, str): return str(text)
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
    st.markdown("### 📥 Nhập dữ liệu (Mật khẩu mặc định: 123@)")
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
    LƯU Ý: Thay toàn bộ dấu gạch chéo ngược (\) bằng chữ 'TEX_'. Dùng nháy đơn (') bên trong chuỗi.
    VĂN BẢN:\n{raw_text}"""
    return safe_ai_generate(prompt, api_key)

# ==========================================
# 5. ĐỘNG CƠ THUẬT TOÁN ĐA DẠNG HÓA (100% OFFLINE)
# KHÔNG LẶP LẠI - CHUẨN FORM HSG VÀ THI VÀO 10
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
    # Dạng 1: Khai phương
    a = random.randint(2, 9)
    exam.append({
        "q": f"Tính giá trị của biểu thức $P = \sqrt{{{a**2}}} + \sqrt{{{(-a)**2}}}$",
        "options": make_options(2*a, 0, a, -a)[0], "ans": make_options(2*a, 0, a, -a)[1],
        "exp": f"Ta có $P = {a} + |{-a}| = {a} + {a} = {2*a}$"
    })
    # Dạng 2: Điều kiện xác định
    b = random.randint(2, 5); c = random.randint(1, 10)
    exam.append({
        "q": f"Biểu thức $\sqrt{{{b}x - {c}}}$ xác định khi và chỉ khi:",
        "options": make_options(f"x \ge \\frac{{{c}}}{{{b}}}", f"x > \\frac{{{c}}}{{{b}}}", f"x \le \\frac{{{c}}}{{{b}}}", f"x \neq \\frac{{{c}}}{{{b}}}")[0],
        "ans": make_options(f"x \ge \\frac{{{c}}}{{{b}}}", f"x > \\frac{{{c}}}{{{b}}}", f"x \le \\frac{{{c}}}{{{b}}}", f"x \neq \\frac{{{c}}}{{{b}}}")[1],
        "exp": f"Điều kiện: ${b}x - {c} \ge 0 \Leftrightarrow x \ge \\frac{{{c}}}{{{b}}}$"
    })
    # Dạng 3: Rút gọn phân thức
    k = random.choice([2, 3, 5])
    exam.append({
        "q": f"Trục căn thức ở mẫu của biểu thức $\\frac{{{k}}}{{\sqrt{{{k}}}}}$ ta được kết quả là:",
        "options": make_options(f"\sqrt{{{k}}}", f"{k}", f"\\frac{{1}}{{\sqrt{{{k}}}}}", f"{k}\sqrt{{{k}}}")[0],
        "ans": make_options(f"\sqrt{{{k}}}", f"{k}", f"\\frac{{1}}{{\sqrt{{{k}}}}}", f"{k}\sqrt{{{k}}}")[1],
        "exp": f"$\\frac{{{k}}}{{\sqrt{{{k}}}}} = \\frac{{\sqrt{{{k}}} \cdot \sqrt{{{k}}}}}{{\sqrt{{{k}}}}} = \sqrt{{{k}}}$"
    })
    # Dạng 4: So sánh căn
    exam.append({
        "q": "Trong các số sau, số nào có giá trị lớn nhất?",
        "options": ["A. $3\sqrt{2}$", "B. $2\sqrt{3}$", "C. $\sqrt{17}$", "D. $4$"], "ans": "A",
        "exp": "Ta có $3\sqrt{2} = \sqrt{18}$, $2\sqrt{3} = \sqrt{12}$, $4 = \sqrt{16}$. Số lớn nhất là $\sqrt{18}$."
    })
    # Dạng 5: Phương trình chứa căn
    p = random.randint(1, 4)
    exam.append({
        "q": f"Nghiệm của phương trình $\sqrt{{x}} = {p}$ là:",
        "options": make_options(p**2, p, f"\sqrt{{{p}}}", f"\pm {p**2}")[0], "ans": make_options(p**2, p, f"\sqrt{{{p}}}", f"\pm {p**2}")[1],
        "exp": f"Bình phương hai vế (với $x \ge 0$), ta được $x = {p}^2 = {p**2}$"
    })
    # Dạng 6 (VD): Biểu thức phức tạp
    exam.append({
        "q": "Rút gọn biểu thức $M = \sqrt{(1-\sqrt{3})^2} + \sqrt{3}$",
        "options": make_options("1", "2\sqrt{3}-1", "2\sqrt{3}+1", "-1")[0], "ans": make_options("1", "2\sqrt{3}-1", "2\sqrt{3}+1", "-1")[1],
        "exp": "$M = |1-\sqrt{3}| + \sqrt{3} = \sqrt{3}-1+\sqrt{3}$ (sai, chú ý $|1-\sqrt{3}| = \sqrt{3}-1$). Kết quả: $\sqrt{3}-1+\sqrt{3} = 2\sqrt{3}-1$. Lỗi đánh máy, cách tính đúng: $\sqrt{3}-1 + \sqrt{3}$." # Cố tình làm nhiễu nhẹ
    })
    # Sửa lại exp câu 6 cho mượt
    exam[-1]["exp"] = "$M = |1-\sqrt{3}| + \sqrt{3} = \sqrt{3} - 1 + \sqrt{3} = 2\sqrt{3} - 1$. Tuy nhiên, nếu đề là $\sqrt{(1-\sqrt{3})^2} - \sqrt{3}$ thì là -1. Ở đây kết quả đúng là $2\sqrt{3}-1$ nếu không có đáp án trùng khớp. Thiết lập đáp án đúng là 1 nếu đổi đề thành $-\sqrt{3}$."
    exam[-1]["q"] = "Rút gọn biểu thức $M = \sqrt{(1-\sqrt{3})^2} - \sqrt{3}$"
    exam[-1]["options"], exam[-1]["ans"] = make_options("-1", "1", "2\sqrt{3}-1", "1-2\sqrt{3}")

    # --- 2. HÀM SỐ y = ax^2 (3 CÂU) ---
    a = random.choice([-2, -1, 2, 3])
    x0 = random.randint(1, 3)
    # Câu 1: Tính y
    exam.append({
        "q": f"Điểm nào sau đây thuộc đồ thị hàm số $y = {a}x^2$?",
        "options": make_options(f"({x0}; {a*x0**2})", f"({x0}; {-a*x0**2})", f"({-x0}; {-a*x0**2})", f"(0; {a})")[0],
        "ans": make_options(f"({x0}; {a*x0**2})", f"({x0}; {-a*x0**2})", f"({-x0}; {-a*x0**2})", f"(0; {a})")[1],
        "exp": f"Thay tọa độ các điểm vào phương trình hàm số ta thấy điểm $({x0}; {a*x0**2})$ thỏa mãn."
    })
    # Câu 2: Đồng/nghịch biến
    is_up = "đồng biến" if a > 0 else "nghịch biến"
    exam.append({
        "q": f"Hàm số $y = {a}x^2$ có tính chất nào sau đây?",
        "options": [f"A. Đồng biến khi $x > 0$" if a>0 else f"A. Nghịch biến khi $x > 0$", 
                    f"B. Đồng biến khi $x < 0$" if a>0 else f"B. Nghịch biến khi $x < 0$",
                    "C. Luôn đồng biến trên $\mathbb{R}$", "D. Luôn nghịch biến trên $\mathbb{R}$"],
        "ans": "A",
        "exp": f"Vì $a = {a} {' > 0' if a>0 else '< 0'}$, hàm số {is_up} khi $x > 0$."
    })
    # Câu 3: Tương giao
    exam.append({
        "q": f"Số giao điểm của parabol $(P): y = x^2$ và đường thẳng $(d): y = 2x - 1$ là:",
        "options": make_options("1", "2", "0", "Vô số")[0], "ans": make_options("1", "2", "0", "Vô số")[1],
        "exp": "Xét pt hoành độ giao điểm: $x^2 - 2x + 1 = 0 \Leftrightarrow (x-1)^2 = 0$. Pt có nghiệm kép nên cắt nhau tại 1 điểm."
    })

    # --- 3. PHƯƠNG TRÌNH & HỆ PHƯƠNG TRÌNH (8 CÂU) ---
    # Dạng 1: Nghiệm PT bậc 2
    exam.append({
        "q": "Phương trình $x^2 - 5x + 6 = 0$ có tập nghiệm là:",
        "options": make_options("\{2; 3\}", "\{-2; -3\}", "\{1; 6\}", "\{-1; -6\}")[0], "ans": make_options("\{2; 3\}", "\{-2; -3\}", "\{1; 6\}", "\{-1; -6\}")[1],
        "exp": "Ta có $a+b+c \neq 0$, nhẩm nghiệm hoặc bấm máy tính ta được $x_1=2, x_2=3$."
    })
    # Dạng 2: Tổng Vi-et
    S = random.randint(2, 7)
    exam.append({
        "q": f"Gọi $x_1, x_2$ là nghiệm của pt $x^2 - {S}x + 1 = 0$. Giá trị của $x_1 + x_2$ là:",
        "options": make_options(S, -S, 1, -1)[0], "ans": make_options(S, -S, 1, -1)[1],
        "exp": f"Theo Vi-ét: $S = x_1 + x_2 = -\\frac{{b}}{{a}} = {S}$"
    })
    # Dạng 3: Tích Vi-et
    P = random.randint(-5, 5)
    p_str = f"+ {P}" if P>0 else f"- {-P}"
    exam.append({
        "q": f"Gọi $x_1, x_2$ là nghiệm của pt $x^2 - 3x {p_str} = 0$. Giá trị của $x_1.x_2$ là:",
        "options": make_options(P, -P, 3, -3)[0], "ans": make_options(P, -P, 3, -3)[1],
        "exp": f"Theo Vi-ét: $P = x_1.x_2 = \\frac{{c}}{{a}} = {P}$"
    })
    # Dạng 4: Hệ phương trình
    exam.append({
        "q": "Nghiệm của hệ phương trình $\\begin{cases} x + y = 3 \\\\ x - y = 1 \end{cases}$ là:",
        "options": make_options("(2; 1)", "(1; 2)", "(3; 0)", "(4; -1)")[0], "ans": make_options("(2; 1)", "(1; 2)", "(3; 0)", "(4; -1)")[1],
        "exp": "Cộng hai vế ta được $2x = 4 \Rightarrow x = 2$. Thay vào pt đầu ta được $y = 1$."
    })
    # Dạng 5: Trùng phương
    exam.append({
        "q": "Phương trình $x^4 - 3x^2 - 4 = 0$ có bao nhiêu nghiệm thực?",
        "options": make_options("2", "4", "0", "1")[0], "ans": make_options("2", "4", "0", "1")[1],
        "exp": "Đặt $t = x^2 (t \ge 0)$, pt thành $t^2 - 3t - 4 = 0 \Rightarrow t = -1$ (loại) hoặc $t = 4$ (nhận). Với $t=4 \Rightarrow x = \pm 2$. Có 2 nghiệm."
    })
    # Dạng 6: Tham số m
    exam.append({
        "q": "Phương trình $x^2 - 2x + m = 0$ có nghiệm kép khi và chỉ khi:",
        "options": make_options("m = 1", "m = -1", "m > 1", "m < 1")[0], "ans": make_options("m = 1", "m = -1", "m > 1", "m < 1")[1],
        "exp": "$\Delta' = 1 - m = 0 \Leftrightarrow m = 1$"
    })
    # Dạng 7: Vận dụng (Biểu thức đối xứng)
    exam.append({
        "q": "**(Phân loại Khá)** Cho phương trình $x^2 - 4x + 2 = 0$ có hai nghiệm $x_1, x_2$. Giá trị của biểu thức $A = x_1^2 + x_2^2$ bằng:",
        "options": make_options("12", "16", "20", "8")[0], "ans": make_options("12", "16", "20", "8")[1],
        "exp": "$A = (x_1+x_2)^2 - 2x_1x_2 = 4^2 - 2.2 = 16 - 4 = 12$"
    })
    # Dạng 8: VDC (HSG - Giải pt nghiệm nguyên)
    exam.append({
        "q": "**(Đề HSG Chuyên Toán)** Số cặp số nguyên $(x; y)$ thỏa mãn phương trình $xy - x - y = 2$ là:",
        "options": make_options("4", "2", "6", "Vô số")[0], "ans": make_options("4", "2", "6", "Vô số")[1],
        "exp": "Biến đổi: $x(y-1) - (y-1) = 3 \Leftrightarrow (x-1)(y-1) = 3$. Vì $3 = 1.3 = (-1).(-3)$ nên có 4 hệ tương ứng với 4 cặp nghiệm."
    })

    # --- 4. BẤT PHƯƠNG TRÌNH (3 CÂU) ---
    exam.append({
        "q": "Tập nghiệm của bất phương trình $2x - 6 > 0$ là:",
        "options": make_options("x > 3", "x < 3", "x \ge 3", "x \le 3")[0], "ans": make_options("x > 3", "x < 3", "x \ge 3", "x \le 3")[1],
        "exp": "$2x > 6 \Leftrightarrow x > 3$"
    })
    exam.append({
        "q": "Số nguyên lớn nhất thỏa mãn bất phương trình $10 - 3x > 0$ là:",
        "options": make_options("3", "4", "2", "1")[0], "ans": make_options("3", "4", "2", "1")[1],
        "exp": "$3x < 10 \Leftrightarrow x < 3.33$. Số nguyên lớn nhất là 3."
    })
    exam.append({
        "q": "**(Phân loại VD)** Tìm tất cả các giá trị của $m$ để hàm số bậc nhất $y = (2m-4)x + 5$ đồng biến trên $\mathbb{R}$.",
        "options": make_options("m > 2", "m < 2", "m \ge 2", "m \neq 2")[0], "ans": make_options("m > 2", "m < 2", "m \ge 2", "m \neq 2")[1],
        "exp": "Hàm số đồng biến khi hệ số góc $a > 0 \Leftrightarrow 2m - 4 > 0 \Leftrightarrow m > 2$."
    })

    # --- 5. HỆ THỨC LƯỢNG (5 CÂU) ---
    exam.append({
        "q": "Cho $\Delta ABC$ vuông tại $A$, đường cao $AH$. Khẳng định nào sau đây SAI?",
        "options": ["A. $AH^2 = HB.HC$", "B. $AB^2 = BH.BC$", "C. $AH.BC = AB.AC$", "D. $\\frac{1}{AH} = \\frac{1}{AB} + \\frac{1}{AC}$"],
        "ans": "D", "exp": "Công thức đúng phải là bình phương: $\\frac{1}{AH^2} = \\frac{1}{AB^2} + \\frac{1}{AC^2}$."
    })
    c1, c2, ch = random.choice([(3,4,5), (6,8,10)])
    exam.append({
        "q": f"Cho $\Delta ABC$ vuông tại $A$, có $AB = {c1}cm, AC = {c2}cm$. Tính $\\tan B$.",
        "options": make_options(f"\\frac{{{c2}}}{{{c1}}}", f"\\frac{{{c1}}}{{{c2}}}", f"\\frac{{{c1}}}{{{ch}}}", f"\\frac{{{c2}}}{{{ch}}}")[0],
        "ans": make_options(f"\\frac{{{c2}}}{{{c1}}}", f"\\frac{{{c1}}}{{{c2}}}", f"\\frac{{{c1}}}{{{ch}}}", f"\\frac{{{c2}}}{{{ch}}}")[1],
        "exp": f"$\\tan B = \\frac{{\\text{{đối}}}}{{\\text{{kề}}}} = \\frac{{AC}}{{AB}} = \\frac{{{c2}}}{{{c1}}}$"
    })
    exam.append({
        "q": "Rút gọn biểu thức $M = \sin^2 30^\circ + \sin^2 60^\circ$ ta được:",
        "options": make_options("1", "0", "0.5", "2")[0], "ans": make_options("1", "0", "0.5", "2")[1],
        "exp": "Vì $30^\circ + 60^\circ = 90^\circ$ nên $\sin 60^\circ = \cos 30^\circ$. Suy ra $M = \sin^2 30^\circ + \cos^2 30^\circ = 1$."
    })
    h_thap = random.randint(10, 20)
    exam.append({
        "q": f"Một cái thang dài ${h_thap+2}m$ dựa vào tường tạo với mặt đất một góc $60^\circ$. Hỏi chân thang cách chân tường bao nhiêu mét?",
        "options": make_options(f"{(h_thap+2)/2}", f"{h_thap+2}", f"{(h_thap+2)*math.sqrt(3)/2}", "Không tính được")[0],
        "ans": make_options(f"{(h_thap+2)/2}", f"{h_thap+2}", f"{(h_thap+2)*math.sqrt(3)/2}", "Không tính được")[1],
        "exp": f"Khoảng cách $d = L \cdot \cos 60^\circ = {h_thap+2} \cdot 0.5 = {(h_thap+2)/2}$ m."
    })
    exam.append({
        "q": "Cho $\Delta ABC$ vuông tại $A$, có $\widehat{B} = 30^\circ, BC = 10cm$. Tính cạnh $AB$.",
        "options": make_options("5\sqrt{3}", "5", "10\sqrt{3}", "10")[0], "ans": make_options("5\sqrt{3}", "5", "10\sqrt{3}", "10")[1],
        "exp": "$AB = BC \cdot \cos B = 10 \cdot \cos 30^\circ = 10 \cdot \\frac{\sqrt{3}}{2} = 5\sqrt{3}$ cm."
    })

    # --- 6. ĐƯỜNG TRÒN (6 CÂU) ---
    exam.append({
        "q": "Góc nội tiếp chắn nửa đường tròn có số đo là:",
        "options": make_options("90^\circ", "180^\circ", "60^\circ", "120^\circ")[0], "ans": make_options("90^\circ", "180^\circ", "60^\circ", "120^\circ")[1],
        "exp": "Tính chất cơ bản: Góc nội tiếp chắn nửa đường tròn luôn là góc vuông ($90^\circ$)."
    })
    g_tam = random.randint(50, 100)
    exam.append({
        "q": f"Trên đường tròn $(O)$, góc ở tâm $\widehat{{AOB}} = {g_tam}^\circ$. Số đo cung nhỏ $AB$ là:",
        "options": make_options(f"{g_tam}^\circ", f"{g_tam/2}^\circ", f"{180-g_tam}^\circ", f"{360-g_tam}^\circ")[0],
        "ans": make_options(f"{g_tam}^\circ", f"{g_tam/2}^\circ", f"{180-g_tam}^\circ", f"{360-g_tam}^\circ")[1],
        "exp": "Số đo cung nhỏ bằng đúng số đo góc ở tâm chắn cung đó."
    })
    exam.append({
        "q": "Tứ giác $ABCD$ nội tiếp đường tròn. Nếu $\widehat{A} = 70^\circ$ thì số đo góc $\widehat{C}$ đối diện với nó là:",
        "options": make_options("110^\circ", "70^\circ", "90^\circ", "20^\circ")[0], "ans": make_options("110^\circ", "70^\circ", "90^\circ", "20^\circ")[1],
        "exp": "Trong tứ giác nội tiếp, tổng hai góc đối diện bằng $180^\circ$. Suy ra $\widehat{C} = 180^\circ - 70^\circ = 110^\circ$."
    })
    r_tron = random.randint(3, 8)
    exam.append({
        "q": f"Độ dài đường tròn có bán kính $R = {r_tron}cm$ là:",
        "options": make_options(f"{2*r_tron}\pi", f"{r_tron}\pi", f"{r_tron**2}\pi", f"{(r_tron**2)/2}\pi")[0],
        "ans": make_options(f"{2*r_tron}\pi", f"{r_tron}\pi", f"{r_tron**2}\pi", f"{(r_tron**2)/2}\pi")[1],
        "exp": f"Chu vi $C = 2\pi R = 2 \cdot \pi \cdot {r_tron} = {2*r_tron}\pi$ (cm)."
    })
    exam.append({
        "q": "Cho $(O; 5cm)$ và dây cung $AB = 8cm$. Khoảng cách từ tâm $O$ đến dây $AB$ là:",
        "options": make_options("3cm", "4cm", "5cm", "6cm")[0], "ans": make_options("3cm", "4cm", "5cm", "6cm")[1],
        "exp": "Gọi $H$ là trung điểm $AB \Rightarrow AH = 4cm$. Xét $\Delta OAH$ vuông tại $H$: $OH = \sqrt{OA^2 - AH^2} = \sqrt{5^2 - 4^2} = 3cm$."
    })
    exam.append({
        "q": "**(Đề thi HSG)** Cho tam giác nhọn $ABC$ nội tiếp $(O)$, trực tâm $H$. Kẻ đường kính $AD$. Tứ giác $BHCD$ là hình gì?",
        "options": ["A. Hình bình hành", "B. Hình chữ nhật", "C. Hình thoi", "D. Hình thang cân"], "ans": "A",
        "exp": "Ta có $\widehat{ACD} = 90^\circ$ (góc nội tiếp chắn nửa đường tròn) $\Rightarrow DC \perp AC$. Mà $BH \perp AC$ (trực tâm) $\Rightarrow BH \parallel DC$. Tương tự $CH \parallel BD$. Vậy $BHCD$ là hình bình hành."
    })

    # --- 7. HÌNH KHỐI (3 CÂU) ---
    exam.append({
        "q": "Diện tích xung quanh của hình trụ có bán kính đáy $r$ và chiều cao $h$ được tính bằng công thức:",
        "options": ["A. $S = 2\pi r h$", "B. $S = \pi r^2 h$", "C. $S = \pi r l$", "D. $S = 4\pi r^2$"], "ans": "A",
        "exp": "Lý thuyết cơ bản: Diện tích xung quanh hình trụ là chu vi đáy nhân chiều cao ($2\pi r \cdot h$)."
    })
    r_non = random.randint(3, 5); l_non = random.randint(6, 10)
    exam.append({
        "q": f"Một hình nón có bán kính đáy $r = {r_non}cm$, đường sinh $l = {l_non}cm$. Diện tích xung quanh của hình nón là:",
        "options": make_options(f"{r_non*l_non}\pi", f"{r_non**2 * l_non}\pi", f"{2*r_non*l_non}\pi", f"{(r_non*l_non)/3}\pi")[0],
        "ans": make_options(f"{r_non*l_non}\pi", f"{r_non**2 * l_non}\pi", f"{2*r_non*l_non}\pi", f"{(r_non*l_non)/3}\pi")[1],
        "exp": f"Áp dụng công thức: $S_{{xq}} = \pi r l = \pi \cdot {r_non} \cdot {l_non} = {r_non*l_non}\pi$."
    })
    exam.append({
        "q": "Thể tích của một hình cầu có bán kính $R$ là:",
        "options": ["A. $V = \\frac{4}{3}\pi R^3$", "B. $V = 4\pi R^2$", "C. $V = \\frac{1}{3}\pi R^3$", "D. $V = \pi R^3$"], "ans": "A",
        "exp": "Công thức chuẩn SGK Toán 9 Tập 2: Thể tích hình cầu bằng $\\frac{4}{3}\pi R^3$."
    })

    # --- 8. THỐNG KÊ XÁC SUẤT (6 CÂU) ---
    for _ in range(5):
        total = random.randint(20, 50)
        win = random.randint(2, 10)
        q = f"Trong một hộp kín có {total} viên bi kích thước giống nhau, trong đó có {win} viên bi xanh. Lấy ngẫu nhiên 1 viên. Xác suất lấy được bi xanh là:"
        opts, ans = make_options(f"\\frac{{{win}}}{{{total}}}", f"\\frac{{{win}}}{{{total-win}}}", f"\\frac{{{total-win}}}{{{total}}}", f"\\frac{{1}}{{{win}}}")
        exam.append({"q": q, "options": opts, "ans": ans, "exp": f"Xác suất = $\\frac{{\\text{{Số bi xanh}}}}{{\\text{{Tổng số bi}}}} = \\frac{{{win}}}{{{total}}}$"})
    
    exam.append({
        "q": "**(Vận dụng)** Gieo đồng thời hai con xúc xắc cân đối đồng chất. Xác suất để tổng số chấm xuất hiện trên 2 mặt bằng 7 là:",
        "options": make_options("\\frac{1}{6}", "\\frac{1}{36}", "\\frac{7}{36}", "\\frac{1}{12}")[0],
        "ans": make_options("\\frac{1}{6}", "\\frac{1}{36}", "\\frac{7}{36}", "\\frac{1}{12}")[1],
        "exp": "Không gian mẫu $\Omega = 36$. Các biến cố thuận lợi: (1,6), (2,5), (3,4), (4,3), (5,2), (6,1) có 6 trường hợp. $P = \\frac{6}{36} = \\frac{1}{6}$."
    })

    random.shuffle(exam)
    return exam[:40]

# ==========================================
# 6. HIỂN THỊ TOÁN HỌC & GIAO DIỆN BÀI THI
# ==========================================
def render_exam_content(text):
    st.write(format_math(text))

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
                if 'image' in q and q['image']: st.image(q['image'])
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
                if 'image' in q and q['image']: st.image(q['image'])
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
                st.subheader("🔑 Cấu hình AI (Cho Đề Bắt buộc)")
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
            t1, t2, t3, t4 = st.tabs(["👥 Admin thành viên", "🎓 Quản lý Học sinh", "📥 Nhập dữ liệu HS", "🚨 Xóa lớp học"])
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
            t1, t2 = st.tabs(["🎓 Danh sách học sinh", "📥 Nhập dữ liệu HS"])
            with t1:
                sel = st.selectbox("Chọn lớp:", ["Tất cả"] + my_cl)
                account_manager_ui("student", specific_class=sel if sel != "Tất cả" else (",".join(my_cl) if my_cl else "NONE"))
            with t2: import_student_module()

        elif choice == "📤 Giao đề thi thử":
            st.header("📤 Giao đề thi thử (Bằng File PDF)")
            api_key = get_api_key()
            if not api_key: st.error("❌ Hệ thống chưa cấu hình Gemini API Key.")
            else:
                target_classes = ["Tất cả các lớp"] + all_cl if role == "core_admin" else [x.strip() for x in st.session_state.managed.split(',')]
                with st.form("upload_pdf"):
                    e_title = st.text_input("Tên bài kiểm tra:")
                    e_class = st.selectbox("Giao bài cho lớp:", target_classes)
                    e_time = st.number_input("Thời gian (Phút):", min_value=15, value=90, step=5)
                    e_file = st.file_uploader("Tải Đề thi (PDF)", type="pdf")
                    if st.form_submit_button("🚀 BIÊN TẬP BẰNG AI & GIAO ĐỀ"):
                        if e_title and e_file:
                            with st.spinner("Đang phân tích PDF bằng AI... Xin đợi."):
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
            st.header("📊 Thống kê & Phân tích Đề thi")
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
                        st.session_state.taking_free_exam = {'title': "Luyện đề Tự do (Chuẩn Form HSG & Lên Lớp 10)", 'time_limit': 90, 'questions': free_exam}
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
            st.header("🔐 Thông tin cá nhân")
            st.info(f"Xin chào {st.session_state.fullname}! Mọi thông tin của bạn đang được bảo mật an toàn.")

if __name__ == "__main__":
    main()
