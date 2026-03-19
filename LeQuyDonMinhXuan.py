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

# --- KHỞI TẠO CẤU HÌNH ---
ADMIN_CORE_EMAIL = "nghihgtq@gmail.com"
ADMIN_CORE_PW = "GiámĐốc2026"
VN_TZ = timezone(timedelta(hours=7))

# ==========================================
# 1. HỆ QUẢN TRỊ CƠ SỞ DỮ LIỆU (DATABASE)
# ==========================================
def init_db():
    conn = sqlite3.connect('exam_db.sqlite')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY, password TEXT, role TEXT, 
        fullname TEXT, dob TEXT, class_name TEXT, 
        school TEXT, managed_classes TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS system_settings (
        setting_key TEXT PRIMARY KEY, setting_value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_exams (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, questions_json TEXT, 
        start_time TEXT, end_time TEXT, target_class TEXT, 
        file_data TEXT, file_type TEXT, answer_key TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, exam_id INTEGER, 
        score REAL, user_answers_json TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    # Khởi tạo Admin Lõi
    c.execute("INSERT OR IGNORE INTO users (username, password, role, fullname) VALUES (?, ?, 'core_admin', 'Giám Đốc Hệ Thống')", (ADMIN_CORE_EMAIL, ADMIN_CORE_PW))
    conn.commit()
    conn.close()

def get_api_key():
    conn = sqlite3.connect('exam_db.sqlite')
    res = conn.execute("SELECT setting_value FROM system_settings WHERE setting_key='GEMINI_API_KEY'").fetchone()
    conn.close()
    return res[0] if res else ""

# ==========================================
# 2. MODULE QUẢN TRỊ THÀNH PHẦN (THEO YÊU CẦU ẢNH)
# ==========================================
def manage_user_component(role_filter, managed_list):
    """Tính năng: Sửa, Xóa, Đổi mật khẩu học sinh/giáo viên"""
    conn = sqlite3.connect('exam_db.sqlite')
    query = f"SELECT username, fullname, password, class_name, dob FROM users WHERE role='{role_filter}'"
    if managed_list and st.session_state.role != 'core_admin':
        classes = "','".join([x.strip() for x in managed_list.split(',')])
        query += f" AND class_name IN ('{classes}')"
    
    df = pd.read_sql_query(query, conn)
    if df.empty:
        st.info("Chưa có dữ liệu thành viên.")
        return

    st.dataframe(df, use_container_width=True)
    
    selected_u = st.selectbox(f"🎯 Chọn tài khoản {role_filter} để xử lý:", ["-- Chọn --"] + df['username'].tolist())
    if selected_u != "-- Chọn --":
        u_data = df[df['username'] == selected_u].iloc[0]
        with st.form("edit_member_form"):
            st.markdown(f"### Chỉnh sửa: {selected_u}")
            col1, col2 = st.columns(2)
            new_name = col1.text_input("Họ và Tên", value=u_data['fullname'])
            new_pw = col2.text_input("Mật khẩu mới", value=u_data['password'])
            new_class = col1.text_input("Lớp/Đơn vị", value=u_data['class_name'])
            
            c_save, c_del = st.columns(2)
            if c_save.form_submit_button("💾 LƯU THÔNG TIN"):
                conn.execute("UPDATE users SET fullname=?, password=?, class_name=? WHERE username=?", (new_name, new_pw, new_class, selected_u))
                conn.commit()
                st.success("✅ Đã cập nhật!")
                st.rerun()
            
            if c_del.form_submit_button("🗑️ XÓA TÀI KHOẢN"):
                conn.execute("DELETE FROM users WHERE username=?", (selected_u))
                conn.execute("DELETE FROM mandatory_results WHERE username=?", (selected_u))
                conn.commit()
                st.warning(f"💥 Đã xóa vĩnh viễn {selected_u}")
                st.rerun()
    conn.close()

# ==========================================
# 3. GIAO DIỆN CHÍNH & PHÂN QUYỀN
# ==========================================
def main():
    st.set_page_config(page_title="LMS LÊ QUÝ ĐÔN V65", layout="wide")
    init_db()

    if 'current_user' not in st.session_state:
        # Giao diện Đăng nhập chuẩn V55
        st.markdown("<h2 style='text-align: center;'>🎓 HỆ THỐNG LMS LÊ QUÝ ĐÔN V65</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.2, 1])
        with col2:
            with st.form("login_gate"):
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
        # SIDEBAR VIỆT HÓA
        role = st.session_state.role
        with st.sidebar:
            st.markdown(f"### 👤 {st.session_state.fullname}")
            st.success(f"Cấp độ: {role.upper()}")
            
            if role == "core_admin":
                st.markdown("---")
                st.subheader("🔑 Cấu hình API")
                new_key = st.text_input("Nhập Gemini API Key:", value=get_api_key(), type="password")
                if st.button("💾 Lưu mã API"):
                    conn = sqlite3.connect('exam_db.sqlite')
                    conn.execute("INSERT OR REPLACE INTO system_settings VALUES ('GEMINI_API_KEY', ?)", (new_key.strip(),))
                    conn.commit(); conn.close()
                    st.success("✅ Đã cập nhật!")
            
            st.markdown("---")
            menu = ["✍️ Làm bài thi", "📊 Kết quả", "🔐 Đổi mật khẩu"]
            if role == "core_admin":
                menu = ["🛡️ Quản trị tối cao", "🤖 Sinh đề AI"] + menu
            elif role == "sub_admin":
                menu = ["👥 Quản lý nhân sự", "🤖 Sinh đề AI"] + menu
            elif role == "teacher":
                menu = ["🏫 Quản lý lớp"] + menu
            
            choice = st.radio("Danh mục điều hướng", menu)
            if st.button("🚪 Đăng xuất", use_container_width=True):
                st.session_state.clear(); st.rerun()

        # ĐIỀU HƯỚNG THEO LỰA CHỌN
        if choice == "🛡️ Quản trị tối cao":
            st.header("🛡️ Quản trị tối cao (Admin Lõi)")
            t1, t2, t3 = st.tabs(["👥 Admin thành viên", "👨‍🏫 Giáo viên", "📑 Nhật ký xóa"])
            with t1: manage_user_component("sub_admin", "")
            with t2: manage_user_component("teacher", "")
            
        elif choice == "👥 Quản lý nhân sự":
            st.header("👥 Quản trị khu vực (Admin thành viên)")
            t1, t2 = st.tabs(["👨‍🏫 Giáo viên của tôi", "🎓 Học sinh của tôi"])
            with t1: manage_user_component("teacher", st.session_state.managed)
            with t2: manage_user_component("student", st.session_state.managed)

        elif choice == "🏫 Quản lý lớp":
            st.header("🏫 Quản lý lớp học (Giáo viên)")
            # Chức năng nạp Excel và sửa/xóa học sinh lớp mình
            manage_user_component("student", st.session_state.managed)

        elif choice == "🤖 Sinh đề AI":
            st.header("🤖 Trí tuệ nhân tạo sinh đề")
            # Logic sinh đề 40 câu bám sát ma trận Tuyên Quang

if __name__ == "__main__":
    main()
