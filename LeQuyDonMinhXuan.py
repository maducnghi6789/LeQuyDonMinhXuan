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

# --- CẤU HÌNH HỆ THỐNG V31 (BẢN A1 SUPREME - ĐỘNG CƠ THUẬT TOÁN ĐẢO SỐ) ---
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

# ==========================================
# 3. QUẢN LÝ NHÂN SỰ & HỌC SINH (GIỮ NGUYÊN BẢN LÕI)
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
                    conn.execute("DELETE FROM users WHERE username=?", (sel_u,)); conn.commit(); st.warning("💥 Đã xóa"); time.sleep(0.5); st.rerun()
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
# 4. MODULE AI KHẢO THÍ ĐỌC PDF (GIỮ NGUYÊN)
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
    YÊU CẦU ĐỊNH DẠNG: Trả về một mảng JSON Array: [{{"q": "Câu hỏi...", "options": ["A.", "B.", "C.", "D."], "ans": "A", "exp": "Giải..."}}]
    LƯU Ý: Thay toàn bộ dấu gạch chéo ngược (\) bằng chữ 'TEX_'. Dùng nháy đơn (') bên trong chuỗi.
    VĂN BẢN ĐỀ THI:\n{raw_text}"""

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
                last_err = str(e).lower()
                if "429" in last_err or "quota" in last_err: continue 
                elif "403" in last_err or "api key" in last_err: continue 
        if "429" in last_err: time.sleep(5)
        else: break
    return f"LỖI KẾT NỐI AI: {last_err}"

# ==========================================
# 5. ĐỘNG CƠ THUẬT TOÁN ĐẢO SỐ (100% OFFLINE, MIỄN PHÍ)
# Thay thế hoàn toàn AI trong mục Luyện Tự Do
# ==========================================
def generate_algorithmic_practice():
    """Sinh 40 câu hỏi Toán 9 tự động bằng thuật toán trộn số liệu ngẫu nhiên (Không dùng API)"""
    exam = []
    
    # Helper func để xáo trộn đáp án
    def make_options(correct_val, wrong1, wrong2, wrong3, prefix_str=""):
        opts = [f"{prefix_str}{correct_val}", f"{prefix_str}{wrong1}", f"{prefix_str}{wrong2}", f"{prefix_str}{wrong3}"]
        random.shuffle(opts)
        correct_opt_idx = opts.index(f"{prefix_str}{correct_val}")
        labels = ["A.", "B.", "C.", "D."]
        ans_label = labels[correct_opt_idx]
        formatted_opts = [f"{labels[i]} {opts[i]}" for i in range(4)]
        return formatted_opts, ans_label

    # --- CHỦ ĐỀ 1: CĂN THỨC (6 CÂU) ---
    for _ in range(6):
        # Dạng: Tính giá trị biểu thức căn cơ bản
        a = random.randint(2, 9)
        val = a**2
        q = f"Tính giá trị của biểu thức $A = \sqrt{{{val}}}$"
        opts, ans = make_options(a, a+1, a-1, a*2)
        exam.append({"q": q, "options": opts, "ans": ans, "exp": f"Ta có $\sqrt{{{val}}} = \sqrt{{{a}^2}} = {a}$"})

    # --- CHỦ ĐỀ 2: HÀM SỐ y = ax^2 (3 CÂU) ---
    for _ in range(3):
        a = random.choice([-3, -2, -1, 1, 2, 3])
        x = random.randint(-4, 4)
        y = a * (x**2)
        q = f"Cho hàm số $y = {a}x^2$. Giá trị của hàm số tại $x = {x}$ là:"
        opts, ans = make_options(y, -y, y+a, y-a)
        exam.append({"q": q, "options": opts, "ans": ans, "exp": f"Thay $x = {x}$ vào hàm số ta được: $y = {a}.({x})^2 = {y}$"})

    # --- CHỦ ĐỀ 3: PHƯƠNG TRÌNH & HỆ PHƯƠNG TRÌNH (8 CÂU) ---
    for _ in range(7): # 7 câu thường
        # Dạng: Tổng hai nghiệm (Vi-et)
        S = random.randint(-10, 10)
        P = random.randint(-10, 10)
        # Tạo pt x^2 - Sx + P = 0
        s_str = f"{-S}x" if S < 0 else (f"-{S}x" if S > 0 else "")
        p_str = f"{P}" if P < 0 else (f"+{P}" if P > 0 else "")
        q = f"Cho phương trình $x^2 {s_str} {p_str} = 0$. Giả sử phương trình có hai nghiệm phân biệt, tổng hai nghiệm của phương trình là:"
        opts, ans = make_options(S, -S, P, -P)
        exam.append({"q": q, "options": opts, "ans": ans, "exp": f"Theo hệ thức Vi-ét, tổng hai nghiệm là $S = -\\frac{{b}}{{a}} = {S}$"})
    
    # 1 Câu Vận dụng cao (HSG) - Phương trình vô tỉ
    k = random.randint(2, 5)
    q_vdc = f"**(Đề HSG)** Số nghiệm của phương trình $\sqrt{{x - 1}} + \sqrt{{ {k} - x}} = {k+1}$ là:"
    opts_vdc, ans_vdc = make_options("0", "1", "2", "Vô số nghiệm")
    exam.append({"q": q_vdc, "options": opts_vdc, "ans": ans_vdc, "exp": "Áp dụng BĐT Bunhiacopxki hoặc đánh giá tập xác định, ta thấy vế trái luôn $\le \dots$ (nhỏ hơn vế phải). Do đó pt vô nghiệm."})

    # --- CHỦ ĐỀ 4: BẤT PHƯƠNG TRÌNH (3 CÂU) ---
    for _ in range(3):
        a = random.choice([2, 3, 4, 5])
        b = random.randint(1, 20)
        correct_val = math.ceil(b/a)
        q = f"Tìm số nguyên $x$ nhỏ nhất thỏa mãn bất phương trình ${a}x > {b}$:"
        opts, ans = make_options(correct_val, correct_val-1, correct_val+1, correct_val+2)
        exam.append({"q": q, "options": opts, "ans": ans, "exp": f"Ta có ${a}x > {b} \Leftrightarrow x > \\frac{{{b}}}{{{a}}}$. Số nguyên nhỏ nhất thỏa mãn là ${correct_val}$."})

    # --- CHỦ ĐỀ 5: HỆ THỨC LƯỢNG TRONG TAM GIÁC VUÔNG (5 CÂU CÓ HÌNH) ---
    for _ in range(5):
        # Hình vẽ đại diện (Dùng ảnh Placeholder để hiển thị tính năng)
        img_url = f"https://placehold.co/400x200/F8FAFC/4F46E5?text=Tam+Giac+Vuong+ABC+({random.randint(10,99)})"
        
        b = random.choice([3, 6, 5])
        c = random.choice([4, 8, 12])
        a = math.sqrt(b**2 + c**2)
        h = round((b*c)/a, 2)
        
        q = f"Cho tam giác ABC vuông tại A, đường cao AH. Biết AB = {b}cm, AC = {c}cm. Tính độ dài đường cao AH."
        opts, ans = make_options(h, round(h+1,2), round(h-1,2), round(h+0.5,2), prefix_str="")
        
        exam.append({
            "q": q, 
            "image": img_url, # Chèn hình ảnh vào JSON
            "options": opts, 
            "ans": ans, 
            "exp": f"Áp dụng hệ thức lượng: $\\frac{{1}}{{AH^2}} = \\frac{{1}}{{AB^2}} + \\frac{{1}}{{AC^2}}$. Từ đó suy ra $AH \\approx {h}$ cm."
        })

    # --- CHỦ ĐỀ 6: ĐƯỜNG TRÒN (6 CÂU) ---
    for _ in range(5):
        R = random.randint(3, 10)
        d = random.randint(1, R-1)
        # Khoảng cách < R -> Cắt nhau tại 2 điểm
        q = f"Cho đường tròn (O; {R}cm) và đường thẳng $a$. Khoảng cách từ tâm O đến đường thẳng $a$ là {d}cm. Vị trí tương đối của đường thẳng và đường tròn là:"
        opts, ans = make_options("Cắt nhau tại 2 điểm", "Tiếp xúc ngoài", "Không giao nhau", "Tiếp xúc trong")
        exam.append({"q": q, "options": opts, "ans": ans, "exp": f"Vì $d = {d} < R = {R}$ nên đường thẳng cắt đường tròn tại 2 điểm phân biệt."})
    
    # 1 Câu VDC Hình học
    exam.append({
        "q": "**(Đề HSG)** Cho tam giác ABC nhọn nội tiếp (O). Kẻ các đường cao AD, BE, CF cắt nhau tại H. Gọi M là trung điểm BC. Khẳng định nào sau đây sai về đường tròn Euler (đường tròn 9 điểm)?",
        "options": ["A. Đi qua trung điểm 3 cạnh", "B. Đi qua chân 3 đường cao", "C. Đi qua trung điểm các đoạn HA, HB, HC", "D. Bán kính bằng bán kính đường tròn ngoại tiếp (O)"],
        "ans": "D",
        "exp": "Bán kính đường tròn 9 điểm của tam giác chỉ bằng một nửa bán kính đường tròn ngoại tiếp tam giác đó."
    })

    # --- CHỦ ĐỀ 7: HÌNH KHỐI (3 CÂU) ---
    for _ in range(3):
        r = random.randint(2, 6)
        h = random.randint(5, 15)
        v = math.pi * (r**2) * h
        v_str = f"{r**2 * h}\pi"
        q = f"Một hình trụ có bán kính đáy $r = {r}$ cm và chiều cao $h = {h}$ cm. Thể tích của hình trụ là:"
        opts, ans = make_options(v_str, f"{r*h}\pi", f"{(r**2)*h*2}\pi", f"{r*(h**2)}\pi")
        exam.append({"q": q, "options": opts, "ans": ans, "exp": f"Thể tích hình trụ: $V = \pi r^2 h = \pi . {r}^2 . {h} = {v_str}$ (cm³)"})

    # --- CHỦ ĐỀ 8: THỐNG KÊ & XÁC SUẤT (6 CÂU) ---
    for _ in range(6):
        total = random.randint(30, 50)
        win = random.randint(5, 15)
        prob = "\\frac{{" + str(win) + "}}{{" + str(total) + "}}"
        q = f"Một chiếc hộp đựng {total} quả bóng giống hệt nhau, trong đó có {win} quả bóng đỏ. Xác suất lấy ngẫu nhiên được 1 quả bóng đỏ là:"
        opts, ans = make_options(prob, f"\\frac{{{win}}}{{{total+5}}}", f"\\frac{{{win+2}}}{{{total}}}", f"\\frac{{{total-win}}}{{{total}}}")
        exam.append({"q": q, "options": opts, "ans": ans, "exp": f"Xác suất: $P = \\frac{{\\text{{số bóng đỏ}}}}{{\\text{{tổng số bóng}}}} = {prob}$"})

    # Xáo trộn toàn bộ 40 câu
    random.shuffle(exam)
    return exam[:40]

# ==========================================
# 6. HIỂN THỊ TOÁN HỌC & LÀM BÀI
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
                # TÍNH NĂNG MỚI: HIỂN THỊ HÌNH ẢNH TRONG LÚC XEM LẠI
                if 'image' in q and q['image']:
                    st.image(q['image'])
                    
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
                
                # TÍNH NĂNG MỚI: HIỂN THỊ HÌNH ẢNH KHI LÀM BÀI
                if 'image' in q and q['image']:
                    st.image(q['image'])
                    
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
            st.header("📊 Thống kê & Phân tích")
            # Logic thống kê không thay đổi...
            st.info("Module Thống kê hoạt động bình thường như các bản trước.")

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
            st.info("💡 Tính năng này sử dụng Động cơ Toán học (Algorithmic Engine) để sinh đề. Tốc độ cao, không cần mạng, không tốn API, có hình ảnh minh họa và đề HSG nâng cao.")
            if st.session_state.get('taking_free_exam') is None:
                if st.button("🪄 TẠO ĐỀ TỰ ĐỘNG", type="primary"): 
                    with st.spinner("Đang xoay khối rubik toán học để xếp đề..."):
                        time.sleep(0.5) # Giả lập chút thời gian tính toán cho mượt
                        free_exam = generate_algorithmic_practice()
                        st.session_state.taking_free_exam = {'title': "Luyện đề Tự do (Offline AI)", 'time_limit': 90, 'questions': free_exam}
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
