import matplotlib
matplotlib.use('Agg')
import streamlit as st
import pandas as pd
import sqlite3
import base64
import json
import re
import time
import unicodedata
import copy
import random
from io import BytesIO
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta, timezone
from PIL import Image

# --- CẤU HÌNH ---
ADMIN_CORE_EMAIL = "nghihgtq@gmail.com"
ADMIN_CORE_PW = "GiámĐốc2026"
VN_TZ = timezone(timedelta(hours=7))

# ==========================================
# 1. TIỆN ÍCH XỬ LÝ CHUỖI & USERNAME
# ==========================================
def remove_accents(input_str):
    if not input_str: return ""
    nfkd_form = unicodedata.normalize('NFKD', str(input_str))
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).replace(" ", "").lower()

def gen_smart_username(fullname, dob, class_name):
    base_user = remove_accents(fullname)
    conn = sqlite3.connect('exam_db.sqlite')
    # Kiểm tra trùng tên trong cùng một lớp
    check = conn.execute("SELECT COUNT(*) FROM users WHERE username=? AND class_name=?", (base_user, class_name)).fetchone()[0]
    conn.close()
    if check > 0:
        if not dob or str(dob).lower() == 'nan': return None # Yêu cầu nhập ngày sinh nếu trùng
        suffix = "".join(filter(str.isdigit, str(dob)))
        return f"{base_user}{suffix}"
    return base_user

# ==========================================
# 2. HỆ QUẢN TRỊ CƠ SỞ DỮ LIỆU
# ==========================================
def init_db():
    conn = sqlite3.connect('exam_db.sqlite')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY, password TEXT, role TEXT, 
        fullname TEXT, dob TEXT, class_name TEXT, 
        school TEXT, managed_classes TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS system_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_exams (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, questions_json TEXT, start_time TEXT, end_time TEXT, target_class TEXT, file_data TEXT, file_type TEXT, answer_key TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_results (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, exam_id INTEGER, score REAL, user_answers_json TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute("INSERT OR IGNORE INTO users (username, password, role, fullname) VALUES (?, ?, 'core_admin', 'Giám Đốc Hệ Thống')", (ADMIN_CORE_EMAIL, ADMIN_CORE_PW))
    conn.commit()
    conn.close()

def get_api_key():
    conn = sqlite3.connect('exam_db.sqlite')
    res = conn.execute("SELECT setting_value FROM system_settings WHERE setting_key='GEMINI_API_KEY'").fetchone()
    conn.close()
    return res[0] if res else ""

# ==========================================
# 3. GIAO DIỆN QUẢN TRỊ (ADMIN LÕI & THÀNH VIÊN)
# ==========================================
def main():
    st.set_page_config(page_title="LMS Lê Quý Đôn V80", layout="wide", page_icon="🏫")
    init_db()

    if 'current_user' not in st.session_state:
        # --- CỔNG ĐĂNG NHẬP ---
        st.markdown("<h2 style='text-align: center;'>🏫 HỆ THỐNG LMS LÊ QUÝ ĐÔN V80</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.2, 1])
        with col2:
            with st.form("login"):
                u = st.text_input("👤 Tên đăng nhập")
                p = st.text_input("🔑 Mật khẩu", type="password")
                if st.form_submit_button("🚀 ĐĂNG NHẬP", use_container_width=True):
                    conn = sqlite3.connect('exam_db.sqlite')
                    res = conn.execute("SELECT role, fullname, managed_classes FROM users WHERE username=? AND password=?", (u.strip(), p.strip())).fetchone()
                    conn.close()
                    if res:
                        st.session_state.current_user, st.session_state.role, st.session_state.fullname, st.session_state.managed = u.strip(), res[0], res[1], res[2]
                        st.rerun()
                    else: st.error("❌ Sai tài khoản hoặc mật khẩu")
    else:
        sidebar_ui()

def sidebar_ui():
    role = st.session_state.role
    with st.sidebar:
        st.markdown(f"### 👤 {st.session_state.fullname}")
        st.success(f"CẤP ĐỘ: {role.upper()}")
        
        if role == "core_admin":
            st.markdown("---")
            st.subheader("🔑 Cấu hình API Nguồn")
            new_key = st.text_input("Nhập API Key:", value=get_api_key(), type="password")
            if st.button("💾 Lưu và Đồng bộ"):
                conn = sqlite3.connect('exam_db.sqlite')
                conn.execute("INSERT OR REPLACE INTO system_settings VALUES ('GEMINI_API_KEY', ?)", (new_key.strip(),))
                conn.commit(); conn.close()
                st.success("✅ Đã lưu API!")

        st.markdown("---")
        menu = ["✍️ Vào phòng thi", "📊 Bảng điểm", "🔐 Cá nhân"]
        if role == "core_admin": menu = ["🛡️ Quản trị tối cao", "🤖 AI Sinh đề"] + menu
        elif role == "sub_admin": menu = ["👥 Quản lý khu vực", "🤖 AI Sinh đề"] + menu
        
        choice = st.radio("Danh mục", menu)
        if st.button("🚪 Thoát", use_container_width=True): st.session_state.clear(); st.rerun()

    if choice == "🛡️ Quản trị tối cao": admin_core_ui()
    elif choice == "👥 Quản lý khu vực": admin_sub_ui()
    elif choice == "✍️ Vào phòng thi": student_exam_ui()

# --- MODULE NHẬP DỮ LIỆU HỌC SINH ---
def input_student_ui(managed_classes):
    st.subheader("📥 Nhập dữ liệu học sinh")
    t1, t2 = st.tabs(["📁 Nạp file Excel", "✍️ Nhập thủ công"])
    
    with t1:
        # Tải file mẫu
        df_sample = pd.DataFrame(columns=["Họ và tên", "Ngày sinh", "Lớp", "Tên trường"])
        df_sample.loc[0] = ["Nguyễn Văn An", "15/05/2010", "9A1", "THCS Lê Quý Đôn"]
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer: df_sample.to_excel(writer, index=False)
        st.download_button("⬇️ Tải File Excel Mẫu", data=output.getvalue(), file_name="Mau_Hoc_Sinh.xlsx")
        
        uploaded_file = st.file_uploader("Chọn file Excel đã điền", type="xlsx")
        if uploaded_file and st.button("🚀 Nạp dữ liệu Excel"):
            df = pd.read_excel(uploaded_file)
            conn = sqlite3.connect('exam_db.sqlite')
            success, fail = 0, 0
            for _, r in df.iterrows():
                u = gen_smart_username(r['Họ và tên'], r['Ngày sinh'], r['Lớp'])
                if u:
                    try:
                        conn.execute("INSERT INTO users (username, password, role, fullname, dob, class_name, school) VALUES (?,?,?,?,?,?,?)",
                                     (u, u, 'student', r['Họ và tên'], str(r['Ngày sinh']), str(r['Lớp']), str(r['Tên trường'])))
                        success += 1
                    except: fail += 1
                else: fail += 1
            conn.commit(); conn.close()
            st.success(f"✅ Thành công: {success} | ❌ Thất bại: {fail} (Do trùng hoặc thiếu ngày sinh)")

    with t2:
        with st.form("manual_student"):
            c1, c2 = st.columns(2)
            f_name = c1.text_input("Họ và Tên (Bắt buộc)")
            f_dob = c2.text_input("Ngày sinh (Bắt buộc nếu trùng tên)")
            f_class = c1.text_input("Lớp (Bắt buộc)")
            f_school = c2.text_input("Tên trường")
            if st.form_submit_button("✅ Tạo tài khoản"):
                u = gen_smart_username(f_name, f_dob, f_class)
                if u:
                    conn = sqlite3.connect('exam_db.sqlite')
                    conn.execute("INSERT INTO users (username, password, role, fullname, dob, class_name, school) VALUES (?,?,?,?,?,?,?)",
                                 (u, u, 'student', f_name, f_dob, f_class, f_school))
                    conn.commit(); conn.close(); st.success(f"Đã tạo: {u}")
                else: st.error("Lỗi: Trùng tên yêu cầu nhập Ngày sinh!")

# --- GIAO DIỆN ADMIN LÕI & THÀNH VIÊN ---
def admin_core_ui():
    st.header("🛡️ Quản trị tối cao")
    tab_sub, tab_stu = st.tabs(["👥 Quản lý Admin Thành viên", "🎓 Quản lý Học sinh toàn trường"])
    with tab_sub:
        with st.form("add_sub"):
            u, p, n, m = st.text_input("Username"), st.text_input("Mật khẩu"), st.text_input("Họ tên"), st.text_input("Vùng quản lý")
            if st.form_submit_button("Cấp quyền Sub-Admin"):
                # Logic thêm Sub-Admin vào DB
                pass
    with tab_stu: input_student_ui("")

def admin_sub_ui():
    st.header("👥 Quản lý khu vực (Admin Thành viên)")
    input_student_ui(st.session_state.managed)

if __name__ == "__main__":
    main()
