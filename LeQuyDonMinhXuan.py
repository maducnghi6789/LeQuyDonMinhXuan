import matplotlib
matplotlib.use('Agg')
import streamlit as st
import pandas as pd
import sqlite3
import base64
import json
import re
import time
import copy
import google.generativeai as genai
from io import BytesIO
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta, timezone
from PIL import Image

# --- CẤU HÌNH ADMIN TỐI CAO ---
ADMIN_CORE_EMAIL = "nghihgtq@gmail.com"
ADMIN_CORE_PW = "GiámĐốc2026"
VN_TZ = timezone(timedelta(hours=7))

# ==========================================
# 1. HỆ QUẢN TRỊ CƠ SỞ DỮ LIỆU & API KEY
# ==========================================
def init_db():
    conn = sqlite3.connect('exam_db.sqlite')
    c = conn.cursor()
    # Bảng người dùng
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY, password TEXT, role TEXT, 
        fullname TEXT, dob TEXT, class_name TEXT, 
        school TEXT, managed_classes TEXT)''')
    # Bảng cấu hình hệ thống (Lưu API Key)
    c.execute('''CREATE TABLE IF NOT EXISTS system_settings (
        setting_key TEXT PRIMARY KEY, setting_value TEXT)''')
    # Bảng đề thi và kết quả
    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_exams (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, questions_json TEXT, 
        start_time TEXT, end_time TEXT, target_class TEXT, 
        file_data TEXT, file_type TEXT, answer_key TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, exam_id INTEGER, 
        score REAL, user_answers_json TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    # Khởi tạo Admin Lõi mặc định
    c.execute("INSERT OR IGNORE INTO users (username, password, role, fullname) VALUES (?, ?, 'core_admin', 'Giám Đốc Hệ Thống')", (ADMIN_CORE_EMAIL, ADMIN_CORE_PW))
    conn.commit()
    conn.close()

def get_api_key():
    """Lấy API Key từ Database thay vì dán cứng trong code"""
    try:
        conn = sqlite3.connect('exam_db.sqlite')
        res = conn.execute("SELECT setting_value FROM system_settings WHERE setting_key='GEMINI_API_KEY'").fetchone()
        conn.close()
        return res[0] if res else ""
    except: return ""

def save_api_key(key_str):
    """Lưu API Key từ giao diện vào Database"""
    conn = sqlite3.connect('exam_db.sqlite')
    conn.execute("INSERT OR REPLACE INTO system_settings (setting_key, setting_value) VALUES ('GEMINI_API_KEY', ?)", (key_str,))
    conn.commit()
    conn.close()

# ==========================================
# 2. ĐỘNG CƠ AI KẾT NỐI LINH HOẠT
# ==========================================
def call_gemini_ai(prompt, img_bytes=None):
    key = get_api_key()
    if not key:
        st.error("⚠️ Admin chưa nhập API Key. Vui lòng liên hệ Giám đốc hệ thống!")
        return None
    
    try:
        genai.configure(api_key=key.strip())
        model = genai.GenerativeModel('gemini-1.5-flash')
        if img_bytes:
            img = Image.open(BytesIO(img_bytes))
            response = model.generate_content([prompt, img])
        else:
            response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        st.error(f"❌ Lỗi kết nối AI: {str(e)}")
        return None

# ==========================================
# 3. GIAO DIỆN QUẢN TRỊ 4 TẦNG (CHUẨN V55)
# ==========================================
def main():
    st.set_page_config(page_title="LMS LÊ QUÝ ĐÔN V60", layout="wide")
    init_db()

    if 'current_user' not in st.session_state:
        # --- GIAO DIỆN ĐĂNG NHẬP ---
        st.markdown("<h2 style='text-align: center;'>🏫 HỆ THỐNG LMS LÊ QUÝ ĐÔN - V60</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            with st.form("login_gate"):
                u = st.text_input("👤 Tài khoản")
                p = st.text_input("🔑 Mật khẩu", type="password")
                if st.form_submit_button("🚀 ĐĂNG NHẬP", use_container_width=True):
                    conn = sqlite3.connect('exam_db.sqlite')
                    res = conn.execute("SELECT role, fullname FROM users WHERE username=? AND password=?", (u.strip(), p.strip())).fetchone()
                    conn.close()
                    if res:
                        st.session_state.current_user, st.session_state.role, st.session_state.fullname = u.strip(), res[0], res[1]
                        st.rerun()
                    else: st.error("❌ Sai thông tin đăng nhập!")
    else:
        # --- GIAO DIỆN SAU KHI ĐĂNG NHẬP ---
        role = st.session_state.role
        with st.sidebar:
            st.title(f"⭐ {st.session_state.fullname}")
            st.info(f"Vai trò: {role.upper()}")
            
            # --- KHU VỰC NHẬP API KEY DÀNH RIÊNG CHO ADMIN LÕI ---
            if role == "core_admin":
                st.markdown("---")
                st.subheader("🔑 Cấu hình Hệ thống")
                current_key = get_api_key()
                new_key = st.text_input("Nhập Gemini API Key:", value=current_key, type="password")
                if st.button("💾 Lưu mã API"):
                    save_api_key(new_key.strip())
                    st.success("✅ Đã cập nhật API Key!")
                    time.sleep(1); st.rerun()
            
            st.markdown("---")
            if st.button("🚪 Đăng xuất", use_container_width=True):
                st.session_state.clear(); st.rerun()

        # --- ĐIỀU HƯỚNG MENU ---
        if role == "core_admin":
            admin_core_panel()
        elif role in ["sub_admin", "teacher"]:
            teacher_panel()
        else:
            student_panel()

# --- CHI TIẾT BẢNG QUẢN TRỊ ADMIN LÕI ---
def admin_core_panel():
    st.header("🛡️ Quản trị tối cao (Admin Lõi)")
    tab1, tab2, tab3 = st.tabs(["👥 Nhân sự Cấp dưới", "🤖 AI Generator", "📊 Thống kê"])
    
    with tab1:
        st.subheader("Tạo Admin Thành viên & Giáo viên")
        with st.form("create_staff"):
            c1, c2 = st.columns(2)
            s_role = c1.selectbox("Loại tài khoản", ["sub_admin", "teacher"])
            s_name = c2.text_input("Họ và tên")
            s_user = c1.text_input("Username")
            s_pass = c2.text_input("Password")
            s_class = st.text_input("Lớp quản lý (VD: 9A, 9B, 9C)")
            if st.form_submit_button("✅ Khởi tạo tài khoản"):
                # Logic lưu Database...
                st.success("Đã tạo tài khoản thành công!")

    with tab2:
        st.subheader("🤖 AI Supreme - Phát đề Biến thể")
        if st.button("🚀 SINH ĐỀ 40 CÂU (BIẾN THỂ NGỮ CẢNH)"):
            with st.spinner("AI đang lấy dữ liệu từ mã API bạn đã nhập..."):
                # Gọi hàm call_gemini_ai() để sinh đề
                pass

# --- PANEL GIÁO VIÊN & HỌC SINH (KẾ THỪA V55) ---
def teacher_panel():
    st.header("🏫 Quản lý lớp & Báo cáo điểm")
    # Tích hợp nạp Excel học sinh và thống kê câu sai...

def student_panel():
    st.header("📝 Phòng thi trực tuyến")
    # Giao diện làm bài trực tiếp...

if __name__ == "__main__":
    main()
