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

# --- CẤU HÌNH HỆ THỐNG V30 (NỀN TẢNG A1) ---
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
    """Dọn dẹp JSON tránh lỗi SyntaxError bằng cách mã hóa backtick"""
    res = json_str.strip()
    bt = chr(96) 
    marker_json = bt + bt + bt + "json"
    marker_code = bt + bt + bt
    if res.startswith(marker_json): res = res[7:]
    elif res.startswith(marker_code): res = res[3:]
    if res.endswith(marker_code): res = res[:-3]
    return res.strip()

def format_math(text):
    """Sửa lỗi hiển thị LaTeX/Backtick chuẩn cho bản A1 SUPREME"""
    if not isinstance(text, str): return str(text)
    bt = chr(96)
    text = re.sub(bt + r'([^' + bt + r']*\\[a-zA-Z]+[^' + bt + r']*)' + bt, r'$\1$', text)
    text = text.replace('\\\\', '\\')
    return text

def get_api_key():
    conn = sqlite3.connect('exam_db.sqlite')
    res = conn.execute("SELECT setting_value FROM system_settings WHERE setting_key='GEMINI_API_KEY'").fetchone()
    conn.close()
    return res[0] if res else ""

# ==========================================
# 2. HỆ QUẢN TRỊ CƠ SỞ DỮ LIỆU (FULL A1)
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

def log_deletion(deleted_by, entity_type, entity_name, reason):
    try:
        conn = sqlite3.connect('exam_db.sqlite')
        vn_time = datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M:%S")
        try: conn.execute("INSERT INTO deletion_logs (deleted_by, entity_type, entity_name, reason, timestamp) VALUES (?, ?, ?, ?, ?)", (deleted_by, entity_type, entity_name, reason, vn_time))
        except:
            conn.execute("DROP TABLE IF EXISTS deletion_logs")
            conn.execute('''CREATE TABLE deletion_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, deleted_by TEXT, entity_type TEXT, entity_name TEXT, reason TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
            conn.execute("INSERT INTO deletion_logs (deleted_by, entity_type, entity_name, reason, timestamp) VALUES (?, ?, ?, ?, ?)", (deleted_by, entity_type, entity_name, reason, vn_time))
        conn.commit(); conn.close()
    except: pass

# ==========================================
# 3. QUẢN LÝ TÀI KHOẢN (FULL A1)
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

# ==========================================
# 4. ĐỘNG CƠ AI A1 (KHẮC PHỤC LỖI KẾT NỐI & 404)
# ==========================================
def extract_text_from_pdf(pdf_file):
    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
    return "\n".join([page.get_text("text") for page in doc])

def safe_ai_generate(prompt, api_key):
    """Cơ chế Vượt rào AI đồng bộ cho A1 SUPREME"""
    genai.configure(api_key=api_key)
    model_names = ['gemini-2.0-flash', 'gemini-1.5-flash-latest', 'gemini-pro']
    last_err = ""
    for name in model_names:
        try:
            model = genai.GenerativeModel(name)
            response = model.generate_content(prompt)
            return json.loads(clean_ai_json(response.text))
        except Exception as e:
            last_err = str(e); continue
    return f"Lỗi AI: {last_err}. Vui lòng kiểm tra API Key."

def generate_free_practice_hybrid(api_key):
    """Thuật toán Hybrid: 20 câu APP + 20 câu AI (Không lặp lại)"""
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
        prompt = f"Sáng tác {num_ai} câu Toán 9. Tránh trùng nội dung: {ctx}. Trả về JSON mảng câu hỏi, LaTeX bọc trong $ hoặc $$."
        res = safe_ai_generate(prompt, api_key)
        if isinstance(res, list): ai_qs = res
    
    combined = app_qs + ai_qs
    random.shuffle(combined)
    return combined[:40]

# ==========================================
# 5. GIAO DIỆN HỌC SINH (LÀM & XEM LẠI BÀI)
# ==========================================
def take_exam_ui(exam_data, exam_id, is_mandatory=True, is_review=False, user_ans_data=None):
    st.markdown(f"### {'🔍 XEM LẠI' if is_review else '📝 LÀM BÀI'}: {exam_data.get('title')}")
    questions = exam_data['questions']
    
    if is_review and user_ans_data:
        correct_count = 0
        for i, q in enumerate(questions):
            ans = user_ans_data.get(str(i))
            if ans and str(ans).startswith(q['ans']): correct_count += 1
        st.success(f"📊 Kết quả: {round((correct_count/len(questions))*10, 2)} điểm | Đúng {correct_count}/{len(questions)} câu.")
        for i, q in enumerate(questions):
            ans = user_ans_data.get(str(i))
            is_right = ans and str(ans).startswith(q['ans'])
            with st.expander(f"Câu {i+1}: {'✅ ĐÚNG' if is_right else '❌ SAI'}"):
                st.write(format_math(q['q']))
                st.markdown(f"**Bạn chọn:** {ans if ans else 'Bỏ trống'}")
                st.info(f"💡 **Giải:** {format_math(q.get('exp',''))}")
        if st.button("⬅️ Quay lại danh sách"):
            st.session_state.active_exam = None; st.session_state.review_mode = False; st.rerun()
        return

    if 'student_answers' not in st.session_state or st.session_state.get('current_exam_id') != exam_id:
        st.session_state.student_answers = {}; st.session_state.current_exam_id = exam_id; st.session_state.show_results = False

    if not st.session_state.show_results:
        with st.form(f"exam_{exam_id}"):
            for i, q in enumerate(questions):
                st.markdown(f"**Câu {i+1}:**"); st.write(format_math(q['q']))
                st.session_state.student_answers[i] = st.radio("Chọn đáp án:", q['options'], index=None, key=f"q_{i}", format_func=format_math)
                st.divider()
            if st.form_submit_button("✅ NỘP BÀI"):
                correct = sum(1 for i, q in enumerate(questions) if st.session_state.student_answers.get(i) and str(st.session_state.student_answers[i]).startswith(q['ans']))
                score = round((correct/len(questions))*10, 2)
                if is_mandatory:
                    conn = sqlite3.connect('exam_db.sqlite')
                    conn.execute("INSERT INTO mandatory_results (username, exam_id, score, user_answers_json) VALUES (?,?,?,?)", (st.session_state.current_user, exam_id, score, json.dumps(st.session_state.student_answers)))
                    conn.commit(); conn.close()
                st.session_state.show_results = True; st.rerun()
    else:
        st.info("Nộp bài thành công! Bấm vào tên đề ở danh sách để xem lại chi tiết.")
        if st.button("Quay lại"): st.session_state.show_results = False; st.session_state.active_exam = None; st.rerun()

# ==========================================
# 6. GIAO DIỆN CHÍNH A1 SUPREME
# ==========================================
def main():
    st.set_page_config(page_title="LMS A1 SUPREME", layout="wide")
    init_db()
    if 'current_user' not in st.session_state:
        col1, col2, col3 = st.columns([1,1.2,1])
        with col2:
            st.title("🎓 ĐĂNG NHẬP")
            with st.form("login"):
                u = st.text_input("Tài khoản").strip(); p = st.text_input("Mật khẩu", type="password").strip()
                if st.form_submit_button("🚀 ĐĂNG NHẬP"):
                    conn = sqlite3.connect('exam_db.sqlite')
                    res = conn.execute("SELECT role, fullname, class_name, managed_classes FROM users WHERE username=? AND password=?", (u, p)).fetchone()
                    if res: st.session_state.current_user, st.session_state.role, st.session_state.fullname, st.session_state.class_name, st.session_state.managed = u, res[0], res[1], res[2], res[3]; st.rerun()
                    else: st.error("Sai tài khoản hoặc mật khẩu!")
    else:
        role, api_key = st.session_state.role, get_api_key()
        with st.sidebar:
            st.write(f"👤 {st.session_state.fullname}"); st.info(f"CẤP ĐỘ: {role.upper()}")
            if role == "core_admin":
                new_key = st.text_input("Gemini API Key:", value=api_key, type="password")
                if st.button("Lưu API"):
                    conn = sqlite3.connect('exam_db.sqlite'); conn.execute("INSERT OR REPLACE INTO system_settings VALUES ('GEMINI_API_KEY', ?)", (new_key,)); conn.commit(); st.success("Đã lưu!"); st.rerun()
            menu = ["📤 Giao đề thi thử", "📊 Thống kê"] if role != "student" else ["✍️ Kiểm tra bắt buộc", "🚀 Luyện đề tự do", "📊 Điểm số cá nhân"]
            choice = st.radio("Menu chính", menu)
            if st.button("🚪 Thoát"): st.session_state.clear(); st.rerun()

        if choice == "✍️ Kiểm tra bắt buộc":
            st.header("✍️ Kiểm tra bắt buộc")
            conn = sqlite3.connect('exam_db.sqlite')
            exams = conn.execute("SELECT id, title, questions_json FROM mandatory_exams WHERE target_class=? OR target_class='Tất cả các lớp'", (st.session_state.class_name,)).fetchall()
            for eid, title, qj in exams:
                done = conn.execute("SELECT score, user_answers_json FROM mandatory_results WHERE username=? AND exam_id=?", (st.session_state.current_user, eid)).fetchone()
                col_a, col_b = st.columns([3, 1])
                # Nút bấm vào Test1 để Xem lại hoặc Làm bài (Bỏ mô tả khoanh tròn)
                if done:
                    if col_a.button(f"🔍 {title}", key=f"rev_{eid}"):
                        st.session_state.active_exam = {'title': title, 'questions': json.loads(qj)}
                        st.session_state.review_mode = True; st.session_state.review_data = json.loads(done[1])
                    col_b.success(f"Đã nộp: {done[0]}đ")
                else:
                    if col_a.button(f"▶️ {title}", key=f"start_{eid}"):
                        st.session_state.active_exam = {'id':eid, 'title':title, 'questions':json.loads(qj)}
                        st.session_state.review_mode = False
            if st.session_state.get('active_exam'):
                st.divider(); take_exam_ui(st.session_state.active_exam, st.session_state.active_exam.get('id', 999), is_review=st.session_state.get('review_mode', False), user_ans_data=st.session_state.get('review_data'))

        elif choice == "🚀 Luyện đề tự do":
            st.header("🚀 Luyện đề tự do") # Đã bỏ các dòng chữ khoanh tròn rườm rà
            if st.button("🪄 TẠO ĐỀ & VÀO THI", type="primary"):
                with st.spinner("AI đang phối hợp tạo đề..."):
                    res = generate_free_practice_hybrid(api_key)
                    if isinstance(res, list): st.session_state.free_exam = {'title': 'Đề luyện tập tự do', 'questions':res}
                    else: st.error(res)
            if st.session_state.get('free_exam'):
                take_exam_ui(st.session_state.free_exam, 888, is_mandatory=False)

        elif choice == "📤 Giao đề thi thử":
            if not api_key: st.error("Chưa có API Key!")
            else:
                with st.form("up_pdf"):
                    t = st.text_input("Tên bài"); c = st.text_input("Lớp"); f = st.file_uploader("PDF", type="pdf")
                    if st.form_submit_button("🚀 BIÊN TẬP & XEM TRƯỚC"):
                        with st.spinner("Đang giải PDF..."):
                            res = safe_ai_generate(f"Biên tập PDF sau thành JSON 40 câu trắc nghiệm Toán. Dùng chuẩn LaTeX. DỮ LIỆU: {extract_text_from_pdf(f)}", api_key)
                            if isinstance(res, list): st.session_state.temp_exam = {'t':t, 'c':c, 'q':res}
                            else: st.error(res)
                if st.session_state.get('temp_exam'):
                    data = st.session_state.temp_exam
                    for i, q in enumerate(data['q']):
                        with st.expander(f"Câu {i+1}"): st.write(format_math(q['q'])); st.success(f"Đáp án: {q['ans']}")
                    if st.button("💾 XÁC NHẬN GIAO ĐỀ"):
                        conn = sqlite3.connect('exam_db.sqlite'); conn.execute("INSERT INTO mandatory_exams (title, questions_json, target_class, created_by) VALUES (?,?,?,?)", (data['t'], json.dumps(data['q']), data['c'], st.session_state.current_user)); conn.commit(); st.success("Đã giao!"); del st.session_state.temp_exam; st.rerun()

        elif choice == "📊 Thống kê":
            st.header("📊 Thống kê kết quả")
            conn = sqlite3.connect('exam_db.sqlite')
            results = pd.read_sql_query("SELECT u.fullname, u.class_name, e.title, r.score FROM mandatory_results r JOIN users u ON r.username = u.username JOIN mandatory_exams e ON r.exam_id = e.id", conn)
            st.dataframe(results, use_container_width=True)

if __name__ == "__main__":
    main()
