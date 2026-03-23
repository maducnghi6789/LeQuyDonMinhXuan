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

# --- CẤU HÌNH HỆ THỐNG V32 (A1 SUPREME - ĐỘNG CƠ TOÁN HỌC CHUẨN MỰC) ---
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
            conn.execute("DROP TABLE IF EXISTS deletion_logs")
            conn.execute('''CREATE TABLE deletion_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, deleted_by TEXT, entity_type TEXT, entity_name TEXT, reason TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
            conn.execute("INSERT INTO deletion_logs (deleted_by, entity_type, entity_name, reason, timestamp) VALUES (?, ?, ?, ?, ?)", (deleted_by, entity_type, entity_name, reason, vn_time))
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
        st.download_button(label="⬇️ XUẤT DANH SÁCH (EXCEL)", data=out.getvalue(), file_name=f"Danh_sach_{target_role}_{datetime.now(VN_TZ).strftime('%Y%m%d')}.xlsx")
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
                    conn.commit(); st.success("✅ Cập nhật xong!"); time.sleep(0.5); st.rerun()
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
                s, f, errs = 0, 0, []
                for idx, r in df.iterrows():
                    name, cls = str(r.get('Họ và tên', '')).strip(), str(r.get('Lớp', '')).strip()
                    if name and name.lower() != 'nan' and cls and cls.lower() != 'nan':
                        uname = gen_smart_username(name, existing); existing.add(uname)
                        try:
                            conn.execute("INSERT INTO users (username, password, role, fullname, class_name) VALUES (?,?,?,?,?)", (uname, "123@", "student", name, cls))
                            s += 1
                        except Exception as e: f += 1; errs.append(f"- Dòng {idx+2}: Lỗi DB")
                    else: f += 1; errs.append(f"- Dòng {idx+2}: Thiếu dữ liệu")
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
    st.markdown("### 🚨 Xóa lớp học")
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
# 4. MODULE AI ĐỌC PDF (DÀNH CHO GIAO ĐỀ BẮT BUỘC)
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
    LƯU Ý: 
    1. Bọc các công thức trong dấu $. (VD: $\sqrt{{2}}$)
    2. Dùng nháy đơn (') bên trong chuỗi, KHÔNG dùng nháy kép (").
    VĂN BẢN:
    {raw_text}
    """
    return safe_ai_generate(prompt, api_key)

# ==========================================
# 5. ĐỘNG CƠ THUẬT TOÁN ĐẢO SỐ (100% OFFLINE, CHUẨN TOÁN HỌC)
# Chuyên gia đã sửa lỗi Format Toán học & Lỗi mất dấu phương trình
# ==========================================
def generate_algorithmic_practice():
    """Sinh 40 câu Toán bám sát Ma trận. Hiển thị chuẩn Toán học LaTeX."""
    exam = []
    
    # Hàm trộn đáp án & CHUẨN HÓA BỌC DẤU $ CHO OPTIONS
    def make_options(*args):
        # Đảm bảo mọi đáp án đều được bọc trong $...$ để render Toán học chuẩn xác
        opts = [f"${str(opt)}$" for opt in args]
        correct_val_formatted = opts[0] # Đáp án đúng luôn truyền vào đầu tiên
        
        random.shuffle(opts)
        correct_opt_idx = opts.index(correct_val_formatted)
        
        labels = ["A.", "B.", "C.", "D."]
        ans_label = labels[correct_opt_idx]
        formatted_opts = [f"{labels[i]} {opts[i]}" for i in range(4)]
        return formatted_opts, ans_label

    # --- 1. CĂN THỨC (6 CÂU) ---
    for _ in range(6):
        a = random.randint(2, 12)
        val = a**2
        q = f"Tính giá trị của biểu thức $A = \sqrt{{{val}}}$"
        opts, ans = make_options(a, a+1, a-1, a*2)
        exam.append({"q": q, "options": opts, "ans": ans, "exp": f"Ta có $\sqrt{{{val}}} = \sqrt{{{a}^2}} = {a}$"})

    # --- 2. HÀM SỐ y = ax^2 (3 CÂU) ---
    for _ in range(3):
        a = random.choice([-3, -2, -1, 1, 2, 3])
        x = random.randint(-4, 4)
        y = a * (x**2)
        q = f"Cho hàm số $y = {a}x^2$. Giá trị của hàm số tại $x = {x}$ là:"
        opts, ans = make_options(y, -y, y+abs(a), y-abs(a))
        exam.append({"q": q, "options": opts, "ans": ans, "exp": f"Thay $x = {x}$ vào hàm số ta được: $y = {a}.({x})^2 = {y}$"})

    # --- 3. PHƯƠNG TRÌNH & HỆ PHƯƠNG TRÌNH (8 CÂU) ---
    for _ in range(7): 
        S = random.randint(-10, 10)
        P = random.randint(-15, 15)
        
        # [ĐÃ SỬA LỖI MẤT DẤU] Tạo chuỗi phương trình x^2 - Sx + P = 0 chuẩn xác
        s_part = ""
        if S > 0: s_part = f"- {S}x"
        elif S < 0: s_part = f"+ {-S}x"
        
        p_part = ""
        if P > 0: p_part = f"+ {P}"
        elif P < 0: p_part = f"- {-P}"
        
        eq_str = f"x^2 {s_part} {p_part} = 0".replace("  ", " ").strip()
        
        q = f"Cho phương trình ${eq_str}$. Giả sử phương trình có hai nghiệm phân biệt, tổng hai nghiệm của phương trình là:"
        opts, ans = make_options(S, -S, P, -P)
        exam.append({"q": q, "options": opts, "ans": ans, "exp": f"Theo hệ thức Vi-ét, tổng hai nghiệm là $S = -\\frac{{b}}{{a}} = {S}$"})
    
    # 1 Câu VDC (HSG) - Hệ phương trình
    k = random.randint(2, 5)
    q_vdc = f"**(Đề HSG)** Biết hệ phương trình $\\begin{{cases}} x+y = {k} \\\\ x^2+y^2 = {k**2 - 2} \\end{{cases}}$ có nghiệm $(x;y)$. Tính giá trị của $P = x^3 + y^3$."
    opts_vdc, ans_vdc = make_options(k**3 - 3*k, k**3, k**3 + 3*k, k**2)
    exam.append({"q": q_vdc, "options": opts_vdc, "ans": ans_vdc, "exp": f"Ta có $xy = \\frac{{(x+y)^2 - (x^2+y^2)}}{{2}} = 1$. Suy ra $x^3+y^3 = (x+y)(x^2+y^2-xy) = {k}({k**2-2} - 1)$."})

    # --- 4. BẤT PHƯƠNG TRÌNH (3 CÂU) ---
    for _ in range(3):
        a = random.choice([2, 3, 4, 5])
        b = random.randint(1, 20)
        correct_val = math.ceil(b/a)
        if (correct_val * a) == b: correct_val += 1 # Đảm bảo > chứ không phải >=
        
        q = f"Tìm số nguyên $x$ nhỏ nhất thỏa mãn bất phương trình ${a}x > {b}$:"
        opts, ans = make_options(correct_val, correct_val-1, correct_val+1, correct_val+2)
        exam.append({"q": q, "options": opts, "ans": ans, "exp": f"Ta có ${a}x > {b} \Leftrightarrow x > \\frac{{{b}}}{{{a}}}$. Số nguyên nhỏ nhất thỏa mãn là $x = {correct_val}$."})

    # --- 5. HỆ THỨC LƯỢNG TRONG TAM GIÁC VUÔNG (5 CÂU) ---
    for _ in range(5):
        # Tạo bộ số Pytago cơ bản
        pytago_sets = [(3,4,5), (6,8,10), (5,12,13), (9,12,15)]
        b, c, a = random.choice(pytago_sets)
        h = f"\\frac{{{b*c}}}{{{a}}}"
        
        q = f"Cho tam giác $ABC$ vuông tại $A$, có đường cao $AH$. Biết độ dài hai cạnh góc vuông là $AB = {b}$ cm và $AC = {c}$ cm. Độ dài đường cao $AH$ là:"
        opts, ans = make_options(h, f"\\frac{{{b+c}}}{{{2}}}", f"\\frac{{{a}}}{{{2}}}", f"\\frac{{{b*c}}}{{{b+c}}}")
        exam.append({
            "q": q, 
            "options": opts, 
            "ans": ans, 
            "exp": f"Độ dài cạnh huyền $BC = \sqrt{{{b}^2 + {c}^2}} = {a}$. Áp dụng hệ thức lượng $AH.BC = AB.AC \Rightarrow AH = {h}$ cm."
        })

    # --- 6. ĐƯỜNG TRÒN (6 CÂU) ---
    for _ in range(5):
        R = random.randint(4, 12)
        d = random.randint(1, R-1)
        q = f"Cho đường tròn $(O; {R}cm)$ và đường thẳng $d$. Biết khoảng cách từ tâm $O$ đến đường thẳng $d$ là ${d}cm$. Vị trí tương đối của đường thẳng và đường tròn là:"
        # Với text dài, ta không bọc $, tạo custom options
        opts_text = ["Cắt nhau tại 2 điểm", "Tiếp xúc nhau", "Không giao nhau", "Trùng nhau"]
        random.shuffle(opts_text)
        ans_idx = opts_text.index("Cắt nhau tại 2 điểm")
        labels = ["A.", "B.", "C.", "D."]
        exam.append({
            "q": q, 
            "options": [f"{labels[i]} {opts_text[i]}" for i in range(4)], 
            "ans": labels[ans_idx], 
            "exp": f"Vì khoảng cách $d = {d} < R = {R}$ nên đường thẳng cắt đường tròn tại 2 điểm phân biệt."
        })
    
    # 1 Câu VDC Hình học
    exam.append({
        "q": "**(Đề HSG)** Tứ giác $ABCD$ nội tiếp đường tròn $(O)$. Gọi $M, N, P, Q$ lần lượt là điểm chính giữa của các cung $AB, BC, CD, DA$. Khẳng định nào sau đây đúng về hai đoạn thẳng $MP$ và $NQ$?",
        "options": ["A. Vuông góc với nhau", "B. Bằng nhau", "C. Song song với nhau", "D. Cắt nhau tại tâm O"],
        "ans": "A",
        "exp": "Góc tạo bởi 2 dây cung $MP$ và $NQ$ chắn nửa tổng số đo 4 cung, bằng $\\frac{360^\circ}{4} = 90^\circ$. Suy ra $MP \perp NQ$."
    })

    # --- 7. HÌNH KHỐI (3 CÂU) ---
    for _ in range(3):
        r = random.randint(2, 6)
        h = random.randint(5, 10)
        v_str = f"{r**2 * h}\\pi"
        q = f"Một hình trụ có bán kính đáy $r = {r}$ cm và chiều cao $h = {h}$ cm. Thể tích của hình trụ là:"
        opts, ans = make_options(v_str, f"{r*h}\\pi", f"{r**2 * h * 2}\\pi", f"\\frac{{{r**2 * h}\\pi}}{{3}}")
        exam.append({"q": q, "options": opts, "ans": ans, "exp": f"Thể tích hình trụ: $V = \pi r^2 h = \pi . {r}^2 . {h} = {v_str}$ (cm³)"})

    # --- 8. THỐNG KÊ & XÁC SUẤT (6 CÂU) ---
    for _ in range(6):
        total = random.randint(30, 60)
        win = random.randint(5, 15)
        # [ĐÃ SỬA LỖI PHÂN SỐ] Sử dụng dấu ngoặc nhọn an toàn cho LaTeX
        prob = f"\\frac{{{win}}}{{{total}}}"
        wrong1 = f"\\frac{{{win}}}{{{total+5}}}"
        wrong2 = f"\\frac{{{win+2}}}{{{total}}}"
        wrong3 = f"\\frac{{{total-win}}}{{{total}}}"
        
        q = f"Một chiếc hộp đựng ${total}$ quả bóng giống hệt nhau, trong đó có ${win}$ quả bóng đỏ. Lấy ngẫu nhiên 1 quả bóng. Xác suất lấy được quả bóng đỏ là:"
        opts, ans = make_options(prob, wrong1, wrong2, wrong3)
        exam.append({"q": q, "options": opts, "ans": ans, "exp": f"Xác suất: $P = \\frac{{\\text{{số kết quả thuận lợi}}}}{{\\text{{tổng số kết quả}}}} = {prob}$"})

    # Xáo trộn toàn bộ 40 câu
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
                
            if not exams:
                st.info("Chưa có bài thi nào được giao.")
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
                            if role == "core_admin":
                                all_st = pd.read_sql_query("SELECT fullname, username, class_name FROM users WHERE role='student'", conn)
                            else:
                                classes_str = "', '".join([x.strip() for x in st.session_state.managed.split(',')])
                                all_st = pd.read_sql_query(f"SELECT fullname, username, class_name FROM users WHERE role='student' AND class_name IN ('{classes_str}')", conn)
                        else:
                            all_st = pd.read_sql_query("SELECT fullname, username, class_name FROM users WHERE role='student' AND class_name=?", conn, params=(target_class,))
                            
                        if res_df.empty: missing_df = all_st
                        else:
                            submitted = res_df['username'].tolist()
                            missing_df = all_st[~all_st['username'].isin(submitted)]
                            
                        if missing_df.empty:
                            st.success("🎉 Tuyệt vời! 100% học sinh đã hoàn thành bài thi.")
                        else:
                            st.warning(f"🚨 Có {len(missing_df)} học sinh chưa làm bài:")
                            st.dataframe(missing_df[['fullname', 'class_name', 'username']].rename(columns={'fullname':'Họ tên', 'class_name':'Lớp', 'username':'Tài khoản'}), use_container_width=True)

                    with tb3:
                        if res_df.empty:
                            st.info("Chưa có dữ liệu để phân tích biểu đồ.")
                        else:
                            wrong_counts = {f"Câu {i+1}": 0 for i in range(num_questions)}
                            for idx, row in res_df.iterrows():
                                try:
                                    u_ans = json.loads(row['user_answers_json'])
                                    for i, q in enumerate(questions):
                                        correct_char = q['ans'].strip()[0].upper()
                                        user_choice = u_ans.get(str(i), u_ans.get(i, "")) 
                                        if not user_choice or not str(user_choice).strip().upper().startswith(correct_char):
                                            wrong_counts[f"Câu {i+1}"] += 1
                                except: pass
                                        
                            stat_df = pd.DataFrame(list(wrong_counts.items()), columns=['Câu hỏi', 'Số lượt sai'])
                            st.markdown("**📊 Biểu đồ số lượt chọn SAI theo từng câu:**")
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
            st.header("🚀 Luyện đề tự do (Thuật toán 100% Offline)") 
            st.info("💡 Hệ thống sử dụng Động cơ Toán học để tự động trộn số liệu, tạo ra hàng ngàn đề khác nhau không cần chờ AI.")
            if st.session_state.get('taking_free_exam') is None:
                if st.button("TẠO ĐỀ", type="primary"): 
                    with st.spinner("Đang tạo đề, xin đợi..."):
                        time.sleep(0.5) 
                        free_exam = generate_algorithmic_practice()
                        st.session_state.taking_free_exam = {'title': "Luyện đề Tự do (Offline)", 'time_limit': 90, 'questions': free_exam}
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
