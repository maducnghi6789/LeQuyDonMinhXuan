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
import bcrypt # BẢO MẬT: Thư viện mã hóa mật khẩu
from io import BytesIO
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta, timezone
import fitz  # PyMuPDF
import google.generativeai as genai

# --- CẤU HÌNH HỆ THỐNG V30 (BẢN A1 SUPREME) ---
ADMIN_CORE_EMAIL = "nghihgtq@gmail.com"
ADMIN_CORE_PW = "GiámĐốc2026"
VN_TZ = timezone(timedelta(hours=7))

# ==========================================
# 1. TIỆN ÍCH BẢO MẬT & XỬ LÝ CHUỖI
# ==========================================
def get_conn():
    """FIX (13): Tối ưu DB connection chống sập App đa luồng"""
    return sqlite3.connect('exam_db.sqlite', check_same_thread=False)

def hash_pw(pw):
    """FIX (3): Mã hóa mật khẩu an toàn"""
    return bcrypt.hashpw(pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def check_pw(pw, hashed):
    """FIX (3): Kiểm tra mật khẩu"""
    try:
        return bcrypt.checkpw(pw.encode('utf-8'), hashed.encode('utf-8'))
    except:
        return pw == hashed # Fallback cho mật khẩu cũ chưa mã hóa

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
    """Dọn dẹp chuỗi JSON an toàn chống lỗi Cú pháp và Markdown"""
    res = json_str.strip()
    bt = chr(96) 
    md_json = bt*3 + "json"
    md_code = bt*3
    if res.startswith(md_json): res = res[7:]
    if res.startswith(md_code): res = res[3:]
    if res.endswith(md_code): res = res[:-3]
    return res.strip()

def format_math(text):
    """Máy sấy công thức: Khắc phục lỗi hiển thị LaTeX"""
    if not isinstance(text, str): return str(text)
    bt = chr(96)
    text = re.sub(bt + r'([^' + bt + r']*\\[a-zA-Z]+[^' + bt + r']*)' + bt, r'$\1$', text)
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
    
    # BẢO MẬT: Kiểm tra Admin
    admin_exists = conn.execute("SELECT 1 FROM users WHERE username=?", (ADMIN_CORE_EMAIL,)).fetchone()
    if not admin_exists:
        c.execute("INSERT INTO users (username, password, role, fullname) VALUES (?, ?, 'core_admin', 'Giám Đốc Hệ Thống')", (ADMIN_CORE_EMAIL, hash_pw(ADMIN_CORE_PW)))
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
    
    # FIX (1): Chống SQL Injection
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
        
        # FIX (2): Chống lộ mật khẩu
        df_display = df.copy()
        if 'password' in df_display.columns:
            df_display['password'] = '********'
            
        st.dataframe(df_display[cols], use_container_width=True)
        sel_u = st.selectbox(f"Chọn {target_role}:", ["-- Chọn --"] + df['username'].tolist())
        
        if sel_u != "-- Chọn --":
            u_data = df[df['username'] == sel_u].iloc[0]
            with st.form(f"form_{sel_u}"):
                c1, c2 = st.columns(2)
                f_name = c1.text_input("Họ và Tên", value=u_data['fullname'])
                f_pass = c2.text_input("🔑 Mật khẩu", value="********") # Che mật khẩu cũ
                f_cls = c1.text_input("Lớp", value=u_data['class_name'] if u_data['class_name'] else "")
                f_sch = c2.text_input("Trường", value=u_data.get('school', '') if pd.notna(u_data.get('school')) else "")
                f_man = st.text_input("Quyền quản lý", value=u_data.get('managed_classes', '') if pd.notna(u_data.get('managed_classes')) else "") if target_role == 'sub_admin' else ""
                b_up, b_reset, b_del = st.columns(3)
                
                if b_up.form_submit_button("💾 CẬP NHẬT"):
                    new_pw = hash_pw(f_pass) if f_pass != "********" else u_data['password']
                    if target_role == 'sub_admin': conn.execute("UPDATE users SET fullname=?, password=?, class_name=?, school=?, managed_classes=? WHERE username=?", (f_name, new_pw, f_cls, f_sch, f_man, sel_u))
                    else: conn.execute("UPDATE users SET fullname=?, password=?, class_name=?, school=? WHERE username=?", (f_name, new_pw, f_cls, f_sch, sel_u))
                    conn.commit(); st.success("✅ Cập nhật xong!"); time.sleep(0.5); st.rerun()
                
                if b_reset.form_submit_button("🔄 RESET VỀ 123@"):
                    conn.execute("UPDATE users SET password=? WHERE username=?", (hash_pw("123@"), sel_u))
                    conn.commit(); st.success(f"✅ Đã reset {sel_u} về 123@"); time.sleep(1); st.rerun()
                
                if b_del.form_submit_button("🗑️ XÓA TÀI KHOẢN"):
                    log_deletion(st.session_state.current_user, "Tài khoản", sel_u, "Xóa thủ công")
                    conn.execute("DELETE FROM users WHERE username=?", (sel_u,)); conn.execute("DELETE FROM mandatory_results WHERE username=?", (sel_u,))
                    conn.commit(); st.warning(f"💥 Đã xóa {sel_u}"); time.sleep(0.5); st.rerun()
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
                            # FIX (3): Hash password khi tạo mới
                            conn.execute("INSERT INTO users (username, password, role, fullname, class_name) VALUES (?,?,?,?,?)", (uname, hash_pw("123@"), "student", name, cls))
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
                    conn.execute("INSERT INTO users (username, password, role, fullname, class_name) VALUES (?,?,?,?,?)", (u, hash_pw("123@"), "student", n, c))
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
                # FIX (8): Xóa lớp có thể lỗi None managed_classes
                if mng:
                    new_mng = ", ".join([c.strip() for c in mng.split(',') if c.strip() != sel_cl])
                else:
                    new_mng = ""
                conn.execute("UPDATE users SET managed_classes=? WHERE username=?", (new_mng, sa))
            log_deletion(st.session_state.current_user, "Lớp học", sel_cl, reason)
            conn.commit(); conn.close(); st.rerun()

# ==========================================
# 4. MODULE AI KHẢO THÍ (CHỐNG LỖI 404 & JSON)
# ==========================================
def extract_text_from_pdf(pdf_file):
    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
    text = ""
    for page in doc: text += page.get_text("text") + "\n"
    doc.close() # FIX (9): Tránh memory leak
    return text

def safe_ai_generate(prompt, api_key):
    """Trái tim AI: Bắt lỗi thân thiện, đảo model, chống Crash JSON"""
    genai.configure(api_key=api_key)
    # FIX (6): Fallback chống lỗi 404
    model_names = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-pro']
    last_err = ""
    for name in model_names:
        try:
            model = genai.GenerativeModel(name)
            response = model.generate_content(prompt)
            # FIX (5): AI JSON dễ crash
            try:
                return json.loads(clean_ai_json(response.text))
            except json.JSONDecodeError:
                return "LỖI AI: Định dạng JSON trả về không hợp lệ."
        except Exception as e:
            last_err = str(e)
            continue
            
    if "429" in last_err or "Quota" in last_err:
        return "LỖI HẠN NGẠCH (Quota 429): Quá tải yêu cầu. Hãy dùng API trả phí hoặc chờ 1 phút."
    elif "404" in last_err:
        return "LỖI KẾT NỐI (404): Không tìm thấy mô hình AI tương thích. Vui lòng kiểm tra lại API Key Google."
    else:
        return f"Lỗi AI không xác định: {last_err}"

def parse_exam_with_ai(raw_text, api_key):
    prompt = f"""Bạn là giáo viên Toán. Biên tập văn bản PDF dưới đây thành chuẩn đúng 40 câu trắc nghiệm.
    YÊU CẦU: Trả về mảng JSON array: [{{"q": "Câu hỏi", "options": ["A.", "B.", "C.", "D."], "ans": "A", "exp": "Hướng dẫn..."}}]
    LƯU Ý KỸ THUẬT: TẤT CẢ công thức Toán học PHẢI được bọc trong dấu $ (ví dụ: $\\sqrt{{2}}$). Escape backslash (\\\\frac).
    VĂN BẢN ĐỀ THI:
    {raw_text}
    """
    return safe_ai_generate(prompt, api_key)

def generate_free_practice_hybrid(api_key):
    """CÔNG NGHỆ HYBRID: Lấy 20 câu kho APP, sinh 20 câu AI, lắc đều."""
    conn = get_conn()
    exams = conn.execute("SELECT questions_json FROM mandatory_exams").fetchall()
    conn.close()
    
    local_bank = []
    for e in exams:
        try:
            qs = json.loads(e[0])
            local_bank.extend(qs)
        except: pass
    
    valid_local = [q for q in local_bank if 'q' in q and 'options' in q and 'ans' in q]
    
    num_app_qs = min(20, len(valid_local))
    # FIX (10): random.sample crash khi list rỗng
    app_qs = random.sample(valid_local, num_app_qs) if num_app_qs > 0 else []
    
    num_ai_qs = 40 - num_app_qs
    ai_qs = []
    
    if num_ai_qs > 0:
        app_context = ""
        if app_qs:
            app_context = "\n".join([f"- {q['q'][:100]}..." for q in app_qs])
        
        prompt = f"""Bạn là chuyên gia Toán. Sáng tác thêm ĐÚNG {num_ai_qs} câu trắc nghiệm để hoàn thiện 40 câu.
        Tránh trùng nội dung: {app_context}
        JSON BẮT BUỘC: [{{"q": "Câu hỏi", "options": ["A. ", "B. ", "C. ", "D. "], "ans": "A", "exp": "Hướng dẫn..."}}]. 
        LƯU Ý KỸ THUẬT: TẤT CẢ công thức Toán học PHẢI được bọc trong dấu $ (ví dụ: $\\sqrt{{2}}$). Escape backslash (\\\\frac).
        """
        ai_res = safe_ai_generate(prompt, api_key)
        
        if isinstance(ai_res, list): ai_qs = ai_res
        else: return ai_res 
            
    combined_qs = app_qs + ai_qs
    random.shuffle(combined_qs)
    return combined_qs[:40]

# ==========================================
# 5. TIỆN ÍCH HIỂN THỊ CÔNG THỨC TOÁN
# ==========================================
def render_exam_content(text):
    """Hỗ trợ render hiển thị nội dung chứa LaTeX lên giao diện UI"""
    st.write(format_math(text))

# ==========================================
# 6. GIAO DIỆN HỌC SINH (LÀM BÀI VÀ TRẢ KẾT QUẢ/XEM LẠI)
# ==========================================
def take_exam_ui(exam_data, exam_id, is_mandatory=True, is_review=False, user_ans_data=None):
    
    # --- CHẾ ĐỘ XEM LẠI BÀI ---
    if is_review and user_ans_data:
        st.markdown(f"### 🔍 XEM LẠI BÀI: {exam_data.get('title')}")
        questions = exam_data['questions']
        correct_count = 0
        for i, q in enumerate(questions):
            # FIX (7): Lỗi index int/string
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
                # BỎ NHÁY NGƯỢC XUNG QUANH usr_choice ĐỂ HIỂN THỊ TOÁN HỌC CHUẨN
                formatted_choice = format_math(str(usr_choice)) if usr_choice else 'Không chọn'
                st.markdown(f"**Bạn đã chọn:** {formatted_choice}")
                
                if not is_correct: st.error("Câu trả lời chưa chính xác.")
                # BỌC format_math CHO HƯỚNG DẪN GIẢI
                st.info(f"**Hướng dẫn (Brief Solution):**\n{format_math(q.get('exp', 'Đang cập nhật...'))}")
                
        if st.button("⬅️ Trở về danh sách đề"):
            st.session_state.show_results = False
            st.session_state.current_exam_id = None
            st.session_state.taking_free_exam = None
            st.session_state.taking_exam = None
            st.session_state.review_mode = False
            st.rerun()
        return

    # --- CHẾ ĐỘ LÀM BÀI MỚI ---
    st.markdown(f"### 📝 LÀM BÀI: {exam_data.get('title', 'Luyện đề tự do')}")
    time_limit = exam_data.get('time_limit', 90)
    questions = exam_data['questions']
    
    if 'student_answers' not in st.session_state or st.session_state.get('current_exam_id') != exam_id:
        st.session_state.student_answers = {}
        st.session_state.current_exam_id = exam_id
        st.session_state.show_results = False
        st.session_state[f"submitted_{exam_id}"] = False # Khởi tạo cờ submit

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
                // FIX (12): Timer JS Fallback
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
                # FIX (11): Chống spam submit bài
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
    st.set_page_config(page_title="LMS A1 SUPREME", layout="wide")
    init_db()
    
    if 'current_user' not in st.session_state:
        st.markdown("<h2 style='text-align: center;'>🎓 HỆ THỐNG LMS LÊ QUÝ ĐÔN A1</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.2, 1])
        with col2:
            with st.form("login"):
                u = st.text_input("Tài khoản").strip(); p = st.text_input("Mật khẩu", type="password").strip()
                if st.form_submit_button("🚀 ĐĂNG NHẬP"):
                    conn = get_conn()
                    # FIX (3): Kiểm tra Hash Password
                    res = conn.execute("SELECT role, fullname, class_name, managed_classes, password FROM users WHERE username=?", (u,)).fetchone()
                    conn.close()
                    if res and check_pw(p, res[4]):
                        st.session_state.current_user = u
                        st.session_state.role, st.session_state.fullname, st.session_state.class_name, st.session_state.managed = res[0], res[1], res[2], res[3]
                        st.rerun()
                    else: st.error("❌ Sai thông tin đăng nhập!")
    else:
        role = st.session_state.role
        with st.sidebar:
            st.markdown(f"### 👤 {st.session_state.fullname}")
            st.success(f"CẤP ĐỘ: {role.upper()}")
            
            api_key = get_api_key()
            if role == "core_admin":
                st.markdown("---")
                st.subheader("🔑 Cấu hình AI (Gemini)")
                new_key = st.text_input("Gemini API Key:", value=api_key, type="password")
                if st.button("💾 Lưu API"):
                    conn = get_conn()
                    conn.execute("INSERT OR REPLACE INTO system_settings VALUES ('GEMINI_API_KEY', ?)", (new_key.strip(),))
                    conn.commit(); conn.close(); st.success("✅ Đã lưu!")
            st.markdown("---")
            
            if role in ["core_admin", "sub_admin"]:
                menu = ["📤 Giao đề thi thử", "📊 Thống kê", "🔐 Cá nhân"]
                if role == "core_admin": menu = ["🛡️ Quản trị tối cao"] + menu
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
                # FIX (4): Bug crash khi managed_classes None
                if r[0]: c_man.extend([x.strip() for x in r[0].split(',') if x.strip()])
            all_cl = sorted(list(set(c_stu + c_man)))
            conn.close()

        if choice == "🛡️ Quản trị tối cao":
            st.header("🛡️ Quản trị tối cao (Admin Lõi)")
            t1, t2, t3, t4 = st.tabs(["👥 Admin thành viên", "🎓 Quản lý Học sinh", "📥 Nhập dữ liệu HS", "🚨 Xóa lớp học"])
            with t1:
                with st.form("add_sa"):
                    u_s, p_s, n_s, m_s = st.text_input("User"), st.text_input("Pass"), st.text_input("Tên"), st.text_input("Lớp (VD: 9A, 9E)")
                    if st.form_submit_button("Cấp quyền"):
                        conn = get_conn()
                        try:
                            # FIX (3): Thêm mã hóa PW cho admin con
                            conn.execute("INSERT INTO users (username, password, role, fullname, managed_classes) VALUES (?,?,'sub_admin',?,?)", (u_s, hash_pw(p_s), n_s, m_s))
                            conn.commit(); st.success("Xong!"); st.rerun()
                        except: st.error("Đã có User này!")
                        conn.close()
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
            if not api_key: st.error("❌ Hệ thống chưa cấu hình Gemini API Key.")
            else:
                target_classes = ["Tất cả các lớp"] + all_cl if role == "core_admin" else [x.strip() for x in st.session_state.managed.split(',')]
                with st.form("upload_pdf"):
                    e_title = st.text_input("Tên bài kiểm tra:")
                    e_class = st.selectbox("Giao bài cho lớp:", target_classes)
                    e_time = st.number_input("Thời gian (Phút):", min_value=15, value=90, step=5)
                    e_file = st.file_uploader("Tải Đề thi (PDF)", type="pdf")
                    
                    if st.form_submit_button("🚀 BIÊN TẬP & GIAO ĐỀ BẰNG AI"):
                        if e_title and e_file:
                            with st.spinner("🤖 AI đang giải đề và phân tích PDF... (Có thể mất 1-2 phút)"):
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
                            
                            max_wrong = stat_df['Số lượt sai'].max()
                            min_wrong = stat_df['Số lượt sai'].min()
                            
                            if max_wrong == 0:
                                st.success("🌟 100% học sinh trả lời đúng tất cả các câu!")
                            else:
                                hard_qs = stat_df[stat_df['Số lượt sai'] == max_wrong]['Câu hỏi'].tolist()
                                easy_qs = stat_df[stat_df['Số lượt sai'] == min_wrong]['Câu hỏi'].tolist()
                                st.error(f"🚨 **Câu sai nhiều nhất:** {', '.join(hard_qs)} ({max_wrong} lượt sai). Thầy cô cần tập trung ôn tập lại kiến thức phần này.")
                                st.success(f"🌟 **Câu làm tốt nhất:** {', '.join(easy_qs)} ({min_wrong} lượt sai).")
            conn.close()

        elif choice == "✍️ Kiểm tra bắt buộc":
            st.header("✍️ Kiểm tra bắt buộc")
            conn = get_conn()
            exams = conn.execute("SELECT id, title, questions_json, time_limit FROM mandatory_exams WHERE target_class=? OR target_class='Tất cả các lớp'", (st.session_state.class_name,)).fetchall()
            
            if not exams: st.info("🎉 Hiện tại bạn chưa có bài kiểm tra nào!")
            else:
                if st.session_state.get('taking_exam') is None:
                    for e_id, e_title, e_json, e_time in exams:
                        c1, c2 = st.columns([3, 1])
                        # Lấy thêm user_answers_json để phục vụ Xem lại bài
                        done = conn.execute("SELECT score, user_answers_json FROM mandatory_results WHERE username=? AND exam_id=?", (st.session_state.current_user, e_id)).fetchone()
                        
                        if done: 
                            # Nút bấm Xem lại bài (YÊU CẦU UI MỚI)
                            if c1.button(f"🔍 {e_title}", key=f"rev_{e_id}"):
                                st.session_state.taking_exam = {'id': e_id, 'title': e_title, 'time_limit': e_time, 'questions': json.loads(e_json)}
                                st.session_state.review_mode = True
                                st.session_state.review_data = json.loads(done[1])
                                st.rerun()
                            c2.success(f"Đã nộp: {done[0]} điểm")
                        else:
                            # Ẩn chữ "Thời gian..."
                            c1.markdown(f"**{e_title}**")
                            if c2.button("▶️ LÀM BÀI", key=f"btn_{e_id}"):
                                st.session_state.taking_exam = {'id': e_id, 'title': e_title, 'time_limit': e_time, 'questions': json.loads(e_json)}
                                st.session_state.review_mode = False
                                st.rerun()
                else: 
                    take_exam_ui(
                        st.session_state.taking_exam, 
                        st.session_state.taking_exam['id'], 
                        is_mandatory=True,
                        is_review=st.session_state.get('review_mode', False),
                        user_ans_data=st.session_state.get('review_data')
                    )
            conn.close()

        elif choice == "🚀 Luyện đề tự do":
            st.header("🚀 Luyện đề tự do") 
            if st.session_state.get('taking_free_exam') is None:
                if st.button("🪄 TẠO ĐỀ", type="primary"): 
                    if not api_key: st.error("❌ Hệ thống chưa kết nối AI.")
                    else:
                        with st.spinner("🤖 Đang quét kho dữ liệu và sinh đề... Xin chờ (hoặc thử lại nếu lỗi 429)."):
                            free_exam = generate_free_practice_hybrid(api_key)
                            if isinstance(free_exam, list): 
                                st.session_state.taking_free_exam = {'title': "Luyện đề Tự do", 'time_limit': 90, 'questions': free_exam}
                                st.rerun()
                            else: 
                                st.error(f"❌ {free_exam}")
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
