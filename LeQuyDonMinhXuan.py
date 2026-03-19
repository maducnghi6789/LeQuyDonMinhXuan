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
import random
import math
from io import BytesIO
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta, timezone
from PIL import Image

# --- THƯ VIỆN AI & PDF ---
try:
    import google.generativeai as genai
    AI_AVAILABLE = True
except:
    AI_AVAILABLE = False

try:
    import fitz  # PyMuPDF
    PDF_RENDERER_AVAILABLE = True
except:
    PDF_RENDERER_AVAILABLE = False

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
    # Bảng cấu hình hệ thống
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
    c.execute("INSERT OR IGNORE INTO users (username, password, role, fullname) VALUES (?, ?, 'core_admin', 'Giám Đốc Hệ Thống')", 
              ("nghihgtq@gmail.com", "GiámĐốc2026"))
    conn.commit()
    conn.close()

def get_api_key():
    try:
        conn = sqlite3.connect('exam_db.sqlite')
        res = conn.execute("SELECT setting_value FROM system_settings WHERE setting_key='GEMINI_API_KEY'").fetchone()
        conn.close()
        return res[0] if res else ""
    except: return ""

def save_api_key(key_str):
    conn = sqlite3.connect('exam_db.sqlite')
    conn.execute("INSERT OR REPLACE INTO system_settings (setting_key, setting_value) VALUES ('GEMINI_API_KEY', ?)", (key_str,))
    conn.commit()
    conn.close()

# ==========================================
# 2. TIỆN ÍCH QUẢN TRỊ (ADMIN LÕI & THÀNH VIÊN)
# ==========================================
def create_account(u, p, name, role, managed="", cls=""):
    conn = sqlite3.connect('exam_db.sqlite')
    try:
        conn.execute("INSERT INTO users (username, password, role, fullname, managed_classes, class_name) VALUES (?,?,?,?,?,?)", 
                     (u.strip(), p.strip(), role, name.strip(), managed, cls))
        conn.commit(); return True
    except: return False
    finally: conn.close()

def delete_account(u):
    conn = sqlite3.connect('exam_db.sqlite')
    try:
        conn.execute("DELETE FROM users WHERE username=?", (u,))
        conn.commit(); return True
    except: return False
    finally: conn.close()

# ==========================================
# 3. GIAO DIỆN CHÍNH (VIỆT HÓA TOÀN DIỆN)
# ==========================================
def main():
    st.set_page_config(page_title="LMS LÊ QUÝ ĐÔN V60", layout="wide", page_icon="🏫")
    init_db()

    if 'current_user' not in st.session_state:
        # --- CỔNG ĐĂNG NHẬP ---
        st.markdown("<h2 style='text-align: center; color: #1E88E5;'>🏫 HỆ THỐNG QUẢN LÝ HỌC TẬP V60</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.2, 1])
        with col2:
            with st.form("login_gate"):
                u = st.text_input("👤 Tên đăng nhập / Email")
                p = st.text_input("🔑 Mật khẩu", type="password")
                if st.form_submit_button("🚀 ĐĂNG NHẬP", use_container_width=True):
                    conn = sqlite3.connect('exam_db.sqlite')
                    res = conn.execute("SELECT role, fullname FROM users WHERE username=? AND password=?", (u.strip(), p.strip())).fetchone()
                    conn.close()
                    if res:
                        st.session_state.current_user, st.session_state.role, st.session_state.fullname = u.strip(), res[0], res[1]
                        st.rerun()
                    else: st.error("❌ Sai tài khoản hoặc mật khẩu")
    else:
        # --- THANH ĐIỀU HƯỚNG ---
        role = st.session_state.role
        with st.sidebar:
            st.markdown(f"### 👤 {st.session_state.fullname}")
            st.info(f"Vai trò: {role.upper()}")
            
            # --- QUẢN LÝ API (CHỈ ADMIN LÕI) ---
            if role == "core_admin":
                st.markdown("---")
                st.subheader("🔑 Cấu hình API AI")
                curr_key = get_api_key()
                new_key = st.text_input("Mã Gemini API Key:", value=curr_key, type="password")
                if st.button("💾 Lưu mã API"):
                    save_api_key(new_key.strip())
                    st.success("✅ Đã cập nhật thành công!")
            
            st.markdown("---")
            menu = ["✍️ Làm bài thi", "📊 Kết quả học tập", "🔐 Đổi mật khẩu"]
            if role == "core_admin":
                menu = ["🛡️ Quản trị tối cao", "🤖 Sinh đề AI"] + menu
            elif role == "sub_admin":
                menu = ["👥 Quản lý giáo viên"] + menu
            elif role == "teacher":
                menu = ["🏫 Quản lý lớp học"] + menu
            
            choice = st.radio("Danh mục", menu)
            if st.button("🚪 Đăng xuất", use_container_width=True):
                st.session_state.clear(); st.rerun()

        # --- ĐIỀU HƯỚNG CHỨC NĂNG ---
        if choice == "🛡️ Quản trị tối cao":
            admin_core_ui()
        elif choice == "🤖 Sinh đề AI":
            st.header("🤖 Trí tuệ nhân tạo sinh đề")
            st.write("Sử dụng API đã cấu hình để tạo đề biến thể ngữ cảnh Tuyên Quang.")
        elif choice == "👥 Quản lý giáo viên" or choice == "🏫 Quản lý lớp học":
            staff_and_class_ui(role)
        elif choice == "✍️ Làm bài thi":
            st.header("✍️ Phòng thi trực tuyến")
            # Logic làm bài thi chuẩn Azota

# ==========================================
# 4. MODULE QUẢN TRỊ NHÂN SỰ (FULL QUYỀN XÓA)
# ==========================================
def admin_core_ui():
    st.header("🛡️ Tổng quản hệ thống (Admin Lõi)")
    tab1, tab2 = st.tabs(["👥 Quản lý Admin thành viên", "👨‍🏫 Quản lý Giáo viên toàn trường"])
    
    conn = sqlite3.connect('exam_db.sqlite')
    
    with tab1:
        st.subheader("Tạo mới Admin thành viên")
        with st.form("add_sub"):
            c1, c2 = st.columns(2)
            u = c1.text_input("Tài khoản (Sub-Admin)")
            p = c2.text_input("Mật khẩu")
            n = c1.text_input("Họ và tên")
            m = c2.text_input("Vùng/Khối quản lý")
            if st.form_submit_button("✅ Cấp quyền Admin thành viên"):
                if create_account(u, p, n, "sub_admin", m): st.success("✅ Đã tạo thành công!")
                else: st.error("❌ Username đã tồn tại!")
        
        st.divider()
        st.subheader("Danh sách & Xóa Admin thành viên")
        df_sub = pd.read_sql_query("SELECT username, fullname, managed_classes FROM users WHERE role='sub_admin'", conn)
        st.dataframe(df_sub, use_container_width=True)
        
        del_u = st.selectbox("Chọn tài khoản cần xóa:", ["-- Chọn --"] + df_sub['username'].tolist(), key="del_sub")
        if del_u != "-- Chọn --" and st.button("🗑 XÓA VĨNH VIỄN ADMIN NÀY", type="primary"):
            if delete_account(del_u): st.success("✅ Đã xóa!"); time.sleep(1); st.rerun()

    with tab2:
        st.subheader("Tạo mới Giáo viên")
        with st.form("add_tea"):
            c1, c2 = st.columns(2)
            u = c1.text_input("Tài khoản (Giáo viên)")
            p = c2.text_input("Mật khẩu")
            n = c1.text_input("Họ và tên")
            m = c2.text_input("Lớp phụ trách (VD: 9A1)")
            if st.form_submit_button("✅ Cấp quyền Giáo viên"):
                if create_account(u, p, n, "teacher", m): st.success("✅ Đã tạo thành công!")
                else: st.error("❌ Username đã tồn tại!")

        st.divider()
        st.subheader("Danh sách & Xóa Giáo viên")
        df_tea = pd.read_sql_query("SELECT username, fullname, managed_classes FROM users WHERE role='teacher'", conn)
        st.dataframe(df_tea, use_container_width=True)
        
        del_t = st.selectbox("Chọn tài khoản giáo viên cần xóa:", ["-- Chọn --"] + df_tea['username'].tolist(), key="del_tea")
        if del_t != "-- Chọn --" and st.button("🗑 XÓA VĨNH VIỄN GIÁO VIÊN NÀY", type="primary"):
            if delete_account(del_t): st.success("✅ Đã xóa!"); time.sleep(1); st.rerun()
    
    conn.close()

def staff_and_class_ui(role):
    st.header(f"🏫 Quản lý đơn vị - {st.session_state.fullname}")
    # Logic dành cho Sub-Admin tạo Giáo viên và Giáo viên nạp danh sách Học sinh từ Excel
    st.info("Module này cho phép quản lý chi tiết học sinh và nạp file Excel.")

if __name__ == "__main__":
    main()
