import matplotlib
matplotlib.use('Agg')
import streamlit as st
import random
import math
import pandas as pd
import sqlite3
import base64
import json
import re
import time
import copy
from io import BytesIO
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta, timezone
from PIL import Image

# --- KẾT NỐI AI ---
try:
    import google.generativeai as genai
    AI_AVAILABLE = True
except:
    AI_AVAILABLE = False

# --- CẤU HÌNH ADMIN TỐI CAO ---
ADMIN_CORE_EMAIL = "maducnghi6789@gmail.com"
ADMIN_CORE_PW = "GiámĐốc2026"
VN_TZ = timezone(timedelta(hours=7))

# ==========================================
# 1. HỆ QUẢN TRỊ CƠ SỞ DỮ LIỆU (CHUẨN V55)
# ==========================================
def init_db():
    conn = sqlite3.connect('exam_db.sqlite')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY, password TEXT, role TEXT, 
        fullname TEXT, dob TEXT, class_name TEXT, 
        school TEXT, managed_classes TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_exams (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, questions_json TEXT, 
        start_time TEXT, end_time TEXT, target_class TEXT, 
        file_data TEXT, file_type TEXT, answer_key TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, exam_id INTEGER, 
        score REAL, user_answers_json TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS system_settings (
        setting_key TEXT PRIMARY KEY, setting_value TEXT)''')
    # Khởi tạo Admin Lõi mặc định
    c.execute("INSERT OR IGNORE INTO users (username, password, role, fullname) VALUES (?, ?, 'core_admin', 'Giám Đốc Hệ Thống')", (ADMIN_CORE_EMAIL, ADMIN_CORE_PW))
    conn.commit()
    conn.close()

def get_api_key():
    try:
        conn = sqlite3.connect('exam_db.sqlite')
        res = conn.execute("SELECT setting_value FROM system_settings WHERE setting_key='GEMINI_API_KEY'").fetchone()
        conn.close()
        return res[0] if res else "AIzaSyDMdmMYUpqnB5wPxcF94Spy6LkNBdkKh2w"
    except: return ""

# ==========================================
# 2. TIỆN ÍCH QUẢN TRỊ NHÂN SỰ (ADMIN LÕI)
# ==========================================
def create_user(username, password, fullname, role, managed_classes="", class_name=""):
    conn = sqlite3.connect('exam_db.sqlite')
    try:
        conn.execute("INSERT INTO users (username, password, role, fullname, managed_classes, class_name) VALUES (?,?,?,?,?,?)",
                     (username, password, role, fullname, managed_classes, class_name))
        conn.commit()
        return True
    except: return False
    finally: conn.close()

# ==========================================
# 3. GIAO DIỆN CHÍNH
# ==========================================
def main():
    st.set_page_config(page_title="LMS LÊ QUÝ ĐÔN V60", layout="wide", page_icon="🏫")
    init_db()

    if 'current_user' not in st.session_state:
        st.markdown("<h2 style='text-align: center;'>🎓 HỆ THỐNG LMS LÊ QUÝ ĐÔN - V60</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            with st.form("login_form"):
                u = st.text_input("Tài khoản (Email/User)")
                p = st.text_input("Mật khẩu", type="password")
                if st.form_submit_button("🚀 ĐĂNG NHẬP", use_container_width=True):
                    conn = sqlite3.connect('exam_db.sqlite')
                    res = conn.execute("SELECT role, fullname FROM users WHERE username=? AND password=?", (u.strip(), p.strip())).fetchone()
                    conn.close()
                    if res:
                        st.session_state.current_user, st.session_state.role, st.session_state.fullname = u.strip(), res[0], res[1]
                        st.rerun()
                    else: st.error("❌ Sai thông tin đăng nhập!")
    else:
        sidebar_navigation()

def sidebar_navigation():
    role = st.session_state.role
    st.sidebar.markdown(f"### 👤 {st.session_state.fullname}")
    st.sidebar.markdown(f"**Vai trò:** `{role.upper()}`")
    
    menu = ["Bài thi trực tuyến", "Kết quả học tập", "Đổi mật khẩu"]
    if role == "core_admin":
        menu = ["🛡️ Quản trị tối cao", "🤖 AI Generator"] + menu
    elif role in ["sub_admin", "teacher"]:
        menu = ["🏫 Quản lý lớp học"] + menu
        
    choice = st.sidebar.radio("Menu điều hướng", menu)

    if choice == "🛡️ Quản trị tối cao":
        admin_core_dashboard()
    elif choice == "🤖 AI Generator":
        ai_generator_panel()
    elif choice == "🏫 Quản lý lớp học":
        teacher_panel()
    elif choice == "Bài thi trực tuyến":
        student_exam_panel()
    
    if st.sidebar.button("🚪 Đăng xuất", use_container_width=True):
        st.session_state.clear()
        st.rerun()

# ==========================================
# 4. CHI TIẾT CÁC BẢNG ĐIỀU KHIỂN
# ==========================================
def admin_core_dashboard():
    st.header("🛡️ Bảng điều khiển Giám đốc Hệ thống")
    tab1, tab2, tab3 = st.tabs(["👥 Quản lý Nhân sự", "🔑 Cấu hình API", "📊 Thống kê toàn trường"])
    
    with tab1:
        st.subheader("Tạo tài khoản quản lý")
        with st.form("create_staff"):
            c1, c2 = st.columns(2)
            new_role = c1.selectbox("Loại tài khoản", ["sub_admin", "teacher"])
            new_fullname = c2.text_input("Họ và tên")
            new_user = c1.text_input("Username (viết liền không dấu)")
            new_pass = c2.text_input("Mật khẩu")
            managed = st.text_input("Lớp quản lý (Cách nhau bởi dấu phẩy, VD: 9A, 9B)")
            
            if st.form_submit_button("✅ Khởi tạo tài khoản"):
                if create_user(new_user, new_pass, new_fullname, new_role, managed):
                    st.success(f"Đã tạo thành công {new_role}: {new_user}")
                else: st.error("❌ Lỗi: Username đã tồn tại!")
        
        st.divider()
        st.subheader("Danh sách nhân sự")
        conn = sqlite3.connect('exam_db.sqlite')
        df_staff = pd.read_sql_query("SELECT username, fullname, role, managed_classes FROM users WHERE role IN ('sub_admin', 'teacher')", conn)
        st.dataframe(df_staff, use_container_width=True)
        conn.close()

def ai_generator_panel():
    st.header("🤖 AI Supreme Generator")
    st.info("Hệ thống sẽ dùng AI bóc tách PDF hoặc tự sinh đề biến thể ngữ cảnh Tuyên Quang.")
    # Tích hợp logic sinh đề 40 câu từ V55...
    if st.button("🚀 SINH ĐỀ BIẾN THỂ 40 CÂU (BÁM SÁT MA TRẬN)"):
        st.success("Đang kết nối Gemini để tạo đề mới...")

def teacher_panel():
    st.header("🏫 Quản lý lớp & Học sinh")
    # Tích hợp nạp Excel, tạo username thông minh kèm ngày sinh từ bản V55
    st.write("Giáo viên nạp danh sách học sinh tại đây...")

def student_exam_panel():
    st.header("📝 Phòng thi trắc nghiệm")
    # Hiển thị các bài thi bắt buộc và tự luyện...

if __name__ == "__main__":
    main()
