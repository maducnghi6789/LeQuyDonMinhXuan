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

# --- CẤU HÌNH HỆ THỐNG V30 SUPREME ---
ADMIN_CORE_EMAIL = "nghihgtq@gmail.com"
ADMIN_CORE_PW = "GiámĐốc2026"
VN_TZ = timezone(timedelta(hours=7))

# ==========================================
# 1. TIỆN ÍCH XỬ LÝ DỮ LIỆU & TOÁN HỌC
# ==========================================
def remove_accents(input_str):
    if not input_str: return ""
    nfkd_form = unicodedata.normalize('NFKD', str(input_str))
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).replace(" ", "").lower() [cite: 1]

def gen_smart_username(fullname, existing_usernames):
    base_name = remove_accents(fullname)
    base_user = f"lqd_{base_name}"
    if base_user not in existing_usernames: return base_user
    counter = 1
    while True:
        new_user = f"{base_user}{counter}"
        if new_user not in existing_usernames: return new_user
        counter += 1 [cite: 2]

def clean_ai_json(json_str):
    """Làm sạch JSON chống lỗi cú pháp chuỗi"""
    res = json_str.strip()
    bt = chr(96) 
    marker_json = bt + bt + bt + "json"
    marker_code = bt + bt + bt
    if res.startswith(marker_json): res = res[7:]
    elif res.startswith(marker_code): res = res[3:]
    if res.endswith(marker_code): res = res[:-3]
    return res.strip() [cite: 3]

def format_math(text):
    """Sửa lỗi hiển thị LaTeX/Backtick"""
    if not isinstance(text, str): return str(text)
    bt = chr(96)
    text = re.sub(bt + r'([^' + bt + r']*\\[a-zA-Z]+[^' + bt + r']*)' + bt, r'$\1$', text)
    text = text.replace('\\\\', '\\')
    return text

def get_api_key():
    conn = sqlite3.connect('exam_db.sqlite')
    res = conn.execute("SELECT setting_value FROM system_settings WHERE setting_key='GEMINI_API_KEY'").fetchone()
    conn.close()
    return res[0] if res else "" [cite: 3]

# ==========================================
# 2. HỆ QUẢN TRỊ CƠ SỞ DỮ LIỆU
# ==========================================
def init_db():
    conn = sqlite3.connect('exam_db.sqlite')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, role TEXT, fullname TEXT, dob TEXT, class_name TEXT, school TEXT, managed_classes TEXT)''') [cite: 4]
    c.execute('''CREATE TABLE IF NOT EXISTS system_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT)''') [cite: 5]
    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_exams (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, questions_json TEXT, time_limit INTEGER, target_class TEXT, created_by TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''') [cite: 5]
    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_results (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, exam_id INTEGER, score REAL, user_answers_json TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''') [cite: 6]
    c.execute("INSERT OR IGNORE INTO users (username, password, role, fullname) VALUES (?, ?, 'core_admin', 'Giám Đốc Hệ Thống')", (ADMIN_CORE_EMAIL, ADMIN_CORE_PW))
    conn.commit(); conn.close() [cite: 7]

# ==========================================
# 3. ĐỘNG CƠ AI VƯỢT RÀO (KHẮC PHỤC LỖI 404/429)
# ==========================================
def safe_ai_generate(prompt, api_key):
    """Cơ chế Vượt rào AI đồng bộ cho giáo viên và học sinh"""
    genai.configure(api_key=api_key)
    model_names = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-pro']
    last_err = ""
    for name in model_names:
        try:
            model = genai.GenerativeModel(name)
            response = model.generate_content(prompt)
            return json.loads(clean_ai_json(response.text))
        except Exception as e:
            last_err = str(e); continue
    return f"Lỗi kết nối AI: {last_err}. Vui lòng kiểm tra lại API Key." [cite: 32, 33, 34]

def parse_exam_with_ai(raw_text, api_key):
    prompt = f"Biên tập PDF thành JSON 40 câu trắc nghiệm Toán. Dùng chuẩn LaTeX bọc trong $ hoặc $$. Escape dấu backslash. DỮ LIỆU: {raw_text}"
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
    return combined[:40] [cite: 38, 39, 46]

# ==========================================
# 4. GIAO DIỆN HỌC SINH (LÀM BÀI & XEM LẠI BÀI)
# ==========================================
def take_exam_ui(exam_data, exam_id, is_mandatory=True, is_review=False, user_ans_data=None):
    st.markdown(f"### {'🔍 XEM LẠI BÀI' if is_review else '📝 LÀM BÀI'}: {exam_data.get('title')}")
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
                st.markdown(f"**Đáp án chuẩn:** {q['ans']}")
                st.info(f"💡 **Hướng dẫn giải:**\n{format_math(q.get('exp',''))}")
        if st.button("⬅️ Quay lại danh sách"):
            st.session_state.active_exam = None; st.session_state.review_mode = False; st.rerun()
        return

    if 'student_answers' not in st.session_state or st.session_state.get('current_exam_id') != exam_id:
        st.session_state.student_answers = {}; st.session_state.current_exam_id = exam_id; st.session_state.show_results = False

    if not st.session_state.show_results:
        timer_html = f"<div style='position:fixed;top:60px;right:20px;background:#ff4b4b;color:white;padding:10px;border-radius:8px;z-index:9999;'>⏳ CÒN LẠI: <span id='timer'>{exam_data.get('time_limit', 90)}:00</span></div>"
        st.components.v1.html(timer_html + "<script>var limit="+str(exam_data.get('time_limit', 90))+"*60*1000;var start=new Date().getTime();var x=setInterval(function(){var now=new Date().getTime();var distance=limit-(now-start);var m=Math.floor((distance%(1000*60*60))/(1000*60));var s=Math.floor((distance%(1000*60))/1000);document.getElementById('timer').innerHTML=m+'p '+s+'s ';if(distance<0){clearInterval(x);window.parent.document.querySelectorAll('button').forEach(b=>{if(b.innerText.includes('NỘP BÀI'))b.click();});}},1000);</script>", height=0) [cite: 48, 49, 53]

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
                st.session_state.show_results = True; st.rerun() [cite: 55, 56, 57, 58]
    else:
        st.info("Bài làm đã được nộp thành công. Bấm vào tên bài ở danh sách để xem lại.")
        if st.button("Quay lại"): st.session_state.show_results = False; st.session_state.active_exam = None; st.rerun()

# ==========================================
# 5. GIAO DIỆN CHÍNH
# ==========================================
def main():
    st.set_page_config(page_title="LMS V30 SUPREME", layout="wide")
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
                    else: st.error("Sai tài khoản hoặc mật khẩu!") [cite: 66, 67, 68]
    else:
        role, api_key = st.session_state.role, get_api_key()
        with st.sidebar:
            st.write(f"👤 {st.session_state.fullname}"); st.info(f"CẤP ĐỘ: {role.upper()}")
            if role == "core_admin":
                new_key = st.text_input("Gemini API Key:", value=api_key, type="password")
                if st.button("Lưu API"):
                    conn = sqlite3.connect('exam_db.sqlite'); conn.execute("INSERT OR REPLACE INTO system_settings VALUES ('GEMINI_API_KEY', ?)", (new_key,)); conn.commit(); st.success("Đã lưu"); st.rerun() [cite: 70, 71, 72]
            menu = ["📤 Giao đề thi thử", "📊 Thống kê"] if role != "student" else ["✍️ Kiểm tra bắt buộc", "🚀 Luyện đề tự do", "📊 Điểm số cá nhân"]
            choice = st.radio("Menu chính", menu)
            if st.button("🚪 Thoát"): st.session_state.clear(); st.rerun() [cite: 74, 75]

        if choice == "✍️ Kiểm tra bắt buộc":
            st.header("✍️ Kiểm tra bắt buộc")
            conn = sqlite3.connect('exam_db.sqlite')
            exams = conn.execute("SELECT id, title, questions_json, time_limit FROM mandatory_exams WHERE target_class=? OR target_class='Tất cả các lớp'", (st.session_state.class_name,)).fetchall() [cite: 116]
            for eid, title, qj in exams:
                done = conn.execute("SELECT score, user_answers_json FROM mandatory_results WHERE username=? AND exam_id=?", (st.session_state.current_user, eid)).fetchone() [cite: 118]
                col_a, col_b = st.columns([3, 1])
                if done:
                    if col_a.button(f"🔍 {title}", key=f"rev_{eid}"):
                        st.session_state.active_exam = {'title': title, 'questions': json.loads(qj), 'time_limit': 0}
                        st.session_state.review_mode = True; st.session_state.review_data = json.loads(done[1])
                    col_b.success(f"Đã nộp: {done[0]}đ")
                else:
                    if col_a.button(f"▶️ {title}", key=f"start_{eid}"):
                        st.session_state.active_exam = {'id':eid, 'title':title, 'questions':json.loads(qj), 'time_limit': 90}
                        st.session_state.review_mode = False [cite: 119, 120]
            if st.session_state.get('active_exam'):
                st.divider(); take_exam_ui(st.session_state.active_exam, st.session_state.active_exam.get('id', 999), is_mandatory=True, is_review=st.session_state.get('review_mode', False), user_ans_data=st.session_state.get('review_data'))

        elif choice == "🚀 Luyện đề tự do":
            st.header("🚀 Luyện đề tự do")
            if st.button("🪄 TẠO ĐỀ HYBRID (APP+AI)"):
                with st.spinner("AI đang phối hợp tạo đề..."):
                    res = generate_free_practice_hybrid(api_key)
                    if isinstance(res, list): st.session_state.free_exam = {'title': 'Đề luyện tập V30', 'questions':res, 'time_limit': 90}
                    else: st.error(res) [cite: 122, 123, 124]
            if st.session_state.get('free_exam'):
                take_exam_ui(st.session_state.free_exam, 888, is_mandatory=False)

        elif choice == "📤 Giao đề thi thử":
            if not api_key: st.error("Chưa có API Key!")
            else:
                with st.form("up_pdf"):
                    t = st.text_input("Tên đề"); c = st.text_input("Lớp"); f = st.file_uploader("PDF", type="pdf")
                    if st.form_submit_button("🚀 BIÊN TẬP & PREVIEW"):
                        with st.spinner("AI đang giải đề..."):
                            res = parse_exam_with_ai(extract_text_from_pdf(f), api_key)
                            if isinstance(res, list): st.session_state.temp_exam = {'t':t, 'c':c, 'q':res}
                            else: st.error(res) [cite: 86, 87, 88]
                if st.session_state.get('temp_exam'):
                    data = st.session_state.temp_exam
                    for i, q in enumerate(data['q']):
                        with st.expander(f"Câu {i+1}"): st.write(format_math(q['q'])); st.success(f"Đ/A: {q['ans']}")
                    if st.button("💾 GIAO ĐỀ"):
                        conn = sqlite3.connect('exam_db.sqlite'); conn.execute("INSERT INTO mandatory_exams (title, questions_json, target_class, created_by) VALUES (?,?,?,?)", (data['t'], json.dumps(data['q']), data['c'], st.session_state.current_user)); conn.commit(); st.success("Xong!"); del st.session_state.temp_exam; st.rerun() [cite: 89, 90, 91]

if __name__ == "__main__":
    main()
