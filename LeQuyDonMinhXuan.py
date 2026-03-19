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
from io import BytesIO
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta, timezone
import fitz  # PyMuPDF
import google.generativeai as genai

# --- CẤU HÌNH HỆ THỐNG ---
ADMIN_CORE_EMAIL = "nghihgtq@gmail.com"
ADMIN_CORE_PW = "GiámĐốc2026"
VN_TZ = timezone(timedelta(hours=7))

# ==========================================
# 1. TIỆN ÍCH XỬ LÝ DỮ LIỆU & TOÁN HỌC
# ==========================================
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
    """Làm sạch JSON dùng mã hóa ký tự để CHỐNG LỖI SyntaxError dòng 45"""
    res = json_str.strip()
    bt = chr(96) # Ký tự backtick `
    marker_json = bt + bt + bt + "json"
    marker_code = bt + bt + bt
    if res.startswith(marker_json): res = res[7:]
    elif res.startswith(marker_code): res = res[3:]
    if res.endswith(marker_code): res = res[:-3]
    return res.strip()

def format_math(text):
    """Máy sấy công thức: Sửa lỗi hiển thị LaTeX/Backtick"""
    if not isinstance(text, str): return str(text)
    bt = chr(96)
    # Chuyển backtick sang $
    text = re.sub(bt + r'([^' + bt + r']*\\[a-zA-Z]+[^' + bt + r']*)' + bt, r'$\1$', text)
    # Triệt tiêu gạch chéo kép
    text = text.replace('\\\\', '\\')
    return text

def get_api_key():
    conn = sqlite3.connect('exam_db.sqlite')
    res = conn.execute("SELECT setting_value FROM system_settings WHERE setting_key='GEMINI_API_KEY'").fetchone()
    conn.close()
    return res[0] if res else ""

# ==========================================
# 2. HỆ QUẢN TRỊ CƠ SỞ DỮ LIỆU
# ==========================================
def init_db():
    conn = sqlite3.connect('exam_db.sqlite')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, role TEXT, fullname TEXT, dob TEXT, class_name TEXT, school TEXT, managed_classes TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS system_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_exams (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, questions_json TEXT, time_limit INTEGER, target_class TEXT, created_by TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_results (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, exam_id INTEGER, score REAL, user_answers_json TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute("INSERT OR IGNORE INTO users (username, password, role, fullname) VALUES (?, ?, 'core_admin', 'Giám Đốc Hệ Thống')", (ADMIN_CORE_EMAIL, ADMIN_CORE_PW))
    conn.commit(); conn.close()

# ==========================================
# 3. QUẢN LÝ TÀI KHOẢN (MẬT KHẨU MẶC ĐỊNH 123@)
# ==========================================
def account_manager_ui(target_role, specific_class=None):
    st.markdown(f"#### 🛠️ Quản lý {target_role}")
    conn = sqlite3.connect('exam_db.sqlite')
    query = f"SELECT * FROM users WHERE role='{target_role}'"
    if specific_class and specific_class != "Tất cả các lớp": query += f" AND class_name='{specific_class}'"
    df = pd.read_sql_query(query, conn)
    if not df.empty:
        cols = ['username', 'fullname', 'password', 'class_name']
        st.dataframe(df[cols], use_container_width=True)
        sel_u = st.selectbox(f"Chọn {target_role}:", ["-- Chọn --"] + df['username'].tolist(), key=f"sel_{target_role}")
        if sel_u != "-- Chọn --":
            u_data = df[df['username'] == sel_u].iloc[0]
            with st.form(f"form_{sel_u}"):
                f_name = st.text_input("Họ và Tên", value=u_data['fullname'])
                f_pass = st.text_input("🔑 Mật khẩu", value=u_data['password'])
                b_up, b_reset = st.columns(2)
                if b_up.form_submit_button("💾 CẬP NHẬT"):
                    conn.execute("UPDATE users SET fullname=?, password=? WHERE username=?", (f_name, f_pass, sel_u))
                    conn.commit(); st.success("Xong!"); st.rerun()
                if b_reset.form_submit_button("🔄 RESET VỀ 123@"):
                    conn.execute("UPDATE users SET password='123@' WHERE username=?", (sel_u,))
                    conn.commit(); st.success("Đã reset!"); st.rerun()
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
                conn = sqlite3.connect('exam_db.sqlite')
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
                conn.commit(); conn.close()
                st.success(f"✅ Thành công: {s} | ❌ Lỗi: {f}")
    with t2:
        with st.form("manual_add"):
            n, c = st.text_input("Họ và tên"), st.text_input("Lớp")
            if st.form_submit_button("Tạo tài khoản"):
                if n and c:
                    conn = sqlite3.connect('exam_db.sqlite'); existing = set([r[0] for r in conn.execute("SELECT username FROM users").fetchall()])
                    u = gen_smart_username(n, existing)
                    conn.execute("INSERT INTO users (username, password, role, fullname, class_name) VALUES (?,?,?,?,?)", (u, "123@", "student", n, c))
                    conn.commit(); st.success(f"Đã tạo: {u} (MK: 123@)"); conn.close()

# ==========================================
# 4. ĐỘNG CƠ AI VƯỢT RÀO & HYBRID MATRIX
# ==========================================
def extract_text_from_pdf(pdf_file):
    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
    return "\n".join([page.get_text("text") for page in doc])

def safe_ai_generate(prompt, api_key):
    """Cơ chế Vượt rào API: Tự động đảo mô hình nếu lỗi 404"""
    genai.configure(api_key=api_key)
    model_names = ['gemini-2.0-flash', 'gemini-1.5-flash-latest', 'gemini-pro']
    last_err = ""
    for name in model_names:
        try:
            model = genai.GenerativeModel(name)
            response = model.generate_content(prompt)
            return json.loads(clean_ai_json(response.text))
        except Exception as e:
            last_err = str(e)
            continue
    return f"Lỗi AI: {last_err}"

def parse_exam_with_ai(raw_text, api_key):
    prompt = f"Biên tập văn bản PDF sau thành JSON 40 câu trắc nghiệm Toán. Dùng chuẩn LaTeX bọc trong $ hoặc $$. Escape dấu backslash. DỮ LIỆU: {raw_text}"
    return safe_ai_generate(prompt, api_key)

def generate_free_practice_hybrid(api_key):
    conn = sqlite3.connect('exam_db.sqlite')
    exams = conn.execute("SELECT questions_json FROM mandatory_exams").fetchall()
    conn.close()
    local_bank = []
    for e in exams:
        try: local_bank.extend(json.loads(e[0]))
        except: pass
    valid_local = [q for q in local_bank if 'q' in q]
    app_qs = random.sample(valid_local, min(20, len(valid_local))) if valid_local else []
    
    num_ai = 40 - len(app_qs)
    ai_qs = []
    if num_ai > 0:
        ctx = "\n".join([f"- {q['q'][:50]}" for q in app_qs])
        prompt = f"Sáng tác {num_ai} câu Toán 9 Vận dụng cao. Tránh trùng nội dung với: {ctx}. Trả về JSON mảng câu hỏi, dùng chuẩn LaTeX bọc trong $ hoặc $$. Escape backslash."
        res = safe_ai_generate(prompt, api_key)
        if isinstance(res, list): ai_qs = res
    
    combined = app_qs + ai_qs
    random.shuffle(combined)
    return combined[:40]

# ==========================================
# 5. GIAO DIỆN HỌC SINH (CHẤM ĐIỂM & TOÁN HỌC)
# ==========================================
def take_exam_ui(exam_data, exam_id, is_mandatory=True):
    st.markdown(f"### 📝 {exam_data.get('title', 'Luyện đề')}")
    questions = exam_data['questions']
    if 'student_answers' not in st.session_state or st.session_state.get('current_exam_id') != exam_id:
        st.session_state.student_answers = {}; st.session_state.current_exam_id = exam_id; st.session_state.show_results = False

    if not st.session_state.show_results:
        with st.form(f"exam_{exam_id}"):
            for i, q in enumerate(questions):
                st.markdown(f"**Câu {i+1}:**"); st.write(format_math(q['q']))
                st.session_state.student_answers[i] = st.radio("Chọn:", q['options'], index=None, key=f"q_{i}", format_func=format_math)
            if st.form_submit_button("✅ NỘP BÀI"):
                correct = sum(1 for i, q in enumerate(questions) if st.session_state.student_answers.get(i) and str(st.session_state.student_answers[i]).startswith(q['ans']))
                st.session_state.score = round((correct/len(questions))*10, 2)
                st.session_state.correct_count = correct
                if is_mandatory:
                    conn = sqlite3.connect('exam_db.sqlite')
                    conn.execute("INSERT INTO mandatory_results (username, exam_id, score, user_answers_json) VALUES (?,?,?,?)", (st.session_state.current_user, exam_id, st.session_state.score, json.dumps(st.session_state.student_answers)))
                    conn.commit(); conn.close()
                st.session_state.show_results = True; st.rerun()
    else:
        st.success(f"🎉 ĐIỂM: {st.session_state.score} | ĐÚNG: {st.session_state.correct_count}/{len(questions)}")
        for i, q in enumerate(questions):
            ans = st.session_state.student_answers.get(i)
            is_right = ans and str(ans).startswith(q['ans'])
            with st.expander(f"Câu {i+1}: {'✅' if is_right else '❌'}"):
                st.write(format_math(q['q']))
                st.info(f"Giải: {format_math(q.get('exp',''))}")

# ==========================================
# 6. GIAO DIỆN CHÍNH
# ==========================================
def main():
    st.set_page_config(page_title="LMS Lê Quý Đôn V200", layout="wide")
    init_db()
    if 'current_user' not in st.session_state:
        col1, col2, col3 = st.columns([1,1.2,1])
        with col2:
            with st.form("login"):
                u = st.text_input("User"); p = st.text_input("Pass", type="password")
                if st.form_submit_button("🚀 ĐĂNG NHẬP"):
                    conn = sqlite3.connect('exam_db.sqlite')
                    res = conn.execute("SELECT role, fullname, class_name, managed_classes FROM users WHERE username=? AND password=?", (u, p)).fetchone()
                    if res: st.session_state.current_user, st.session_state.role, st.session_state.fullname, st.session_state.class_name, st.session_state.managed = u, res[0], res[1], res[2], res[3]; st.rerun()
                    else: st.error("Sai thông tin!")
    else:
        role, api_key = st.session_state.role, get_api_key()
        with st.sidebar:
            st.write(f"👤 {st.session_state.fullname}"); st.info(role.upper())
            if role == "core_admin":
                new_key = st.text_input("Gemini API Key:", value=api_key, type="password")
                if st.button("Lưu API"):
                    conn = sqlite3.connect('exam_db.sqlite'); conn.execute("INSERT OR REPLACE INTO system_settings VALUES ('GEMINI_API_KEY', ?)", (new_key,)); conn.commit(); st.success("Đã lưu"); st.rerun()
            menu = ["📤 Giao đề thi thử", "📊 Thống kê"] if role != "student" else ["✍️ Kiểm tra bắt buộc", "🚀 Luyện đề tự do"]
            if role == "core_admin": menu = ["🛡️ Quản trị tối cao"] + menu
            choice = st.radio("Menu", menu)
            if st.button("🚪 Thoát"): st.session_state.clear(); st.rerun()

        if choice == "📤 Giao đề thi thử":
            if not api_key: st.error("Chưa có API Key!")
            else:
                with st.form("up_pdf"):
                    t = st.text_input("Tên bài"); c = st.text_input("Lớp"); f = st.file_uploader("PDF", type="pdf")
                    if st.form_submit_button("🚀 BIÊN TẬP & XEM TRƯỚC"):
                        with st.spinner("AI đang xử lý..."):
                            res = parse_exam_with_ai(extract_text_from_pdf(f), api_key)
                            if isinstance(res, list): st.session_state.temp_exam = {'t':t, 'c':c, 'q':res}
                            else: st.error(res)
                if 'temp_exam' in st.session_state:
                    for i, q in enumerate(st.session_state.temp_exam['q']):
                        with st.expander(f"Câu {i+1}"): st.write(format_math(q['q'])); st.success(format_math(q.get('exp','')))
                    if st.button("💾 XÁC NHẬN GIAO ĐỀ"):
                        conn = sqlite3.connect('exam_db.sqlite')
                        conn.execute("INSERT INTO mandatory_exams (title, questions_json, target_class, created_by) VALUES (?,?,?,?)", (st.session_state.temp_exam['t'], json.dumps(st.session_state.temp_exam['q']), st.session_state.temp_exam['c'], st.session_state.current_user))
                        conn.commit(); st.success("Đã giao!"); del st.session_state.temp_exam

        elif choice == "🛡️ Quản trị tối cao":
            t1, t2 = st.tabs(["Admin", "Học sinh"])
            with t2: account_manager_ui("student")

        elif choice == "✍️ Kiểm tra bắt buộc":
            conn = sqlite3.connect('exam_db.sqlite')
            exams = conn.execute("SELECT id, title, questions_json FROM mandatory_exams WHERE target_class=?", (st.session_state.class_name,)).fetchall()
            for eid, title, qj in exams:
                if st.button(f"Làm bài: {title}"): st.session_state.active_exam = {'id':eid, 'title':title, 'questions':json.loads(qj)}
            if 'active_exam' in st.session_state: take_exam_ui(st.session_state.active_exam, st.session_state.active_exam['id'])

        elif choice == "🚀 Luyện đề tự do":
            if st.button("🪄 TẠO ĐỀ HYBRID (APP+AI)"):
                with st.spinner("Đang lai tạo đề..."):
                    res = generate_free_practice_hybrid(api_key)
                    if isinstance(res, list): st.session_state.free_exam = {'questions':res}
                    else: st.error(res)
            if 'free_exam' in st.session_state: take_exam_ui(st.session_state.free_exam, 999)

if __name__ == "__main__":
    main()
