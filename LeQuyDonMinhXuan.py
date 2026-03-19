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

# --- CẤU HÌNH HỆ THỐNG ---
ADMIN_CORE_EMAIL = "nghihgtq@gmail.com"
ADMIN_CORE_PW = "GiámĐốc2026"
VN_TZ = timezone(timedelta(hours=7))

try:
    import google.generativeai as genai
    AI_AVAILABLE = True
except:
    AI_AVAILABLE = False

# ==========================================
# 1. HỆ QUẢN TRỊ CƠ SỞ DỮ LIỆU & ĐỒNG BỘ
# ==========================================
def init_db():
    conn = sqlite3.connect('exam_db.sqlite')
    c = conn.cursor()
    # Bảng người dùng (Chỉ còn 3 Role: core_admin, sub_admin, student)
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
# 2. MODULE TÁC VỤ THÀNH PHẦN (ĐỒNG BỘ HÓA)
# ==========================================
def manage_accounts_ui(target_role, managed_filter=None):
    """Tính năng: Sửa, Xóa, Đổi mật khẩu, Thống kê cho Admin Thành viên & Học sinh"""
    conn = sqlite3.connect('exam_db.sqlite')
    query = f"SELECT * FROM users WHERE role='{target_role}'"
    
    # Đồng bộ hóa phạm vi quản lý
    if managed_filter and st.session_state.role != 'core_admin':
        classes = "','".join([x.strip() for x in managed_filter.split(',')])
        query += f" AND class_name IN ('{classes}')"
    
    df = pd.read_sql_query(query, conn)
    if df.empty:
        st.info(f"Chưa có dữ liệu {target_role}.")
        return

    st.dataframe(df[['username', 'fullname', 'password', 'class_name', 'managed_classes']], use_container_width=True)
    
    sel_user = st.selectbox(f"🎯 Chọn tài khoản để xử lý:", ["-- Chọn --"] + df['username'].tolist(), key=f"sel_{target_role}")
    if sel_user != "-- Chọn --":
        u_info = df[df['username'] == sel_user].iloc[0]
        with st.form(f"form_{sel_user}"):
            c1, c2 = st.columns(2)
            f_name = c1.text_input("Họ và Tên", value=u_info['fullname'])
            f_pass = c2.text_input("Mật khẩu", value=u_info['password'])
            f_class = c1.text_input("Lớp/Vùng", value=u_info['class_name'] if u_info['class_name'] else "")
            f_mang = c2.text_input("Quyền quản lý (Dành cho Admin thành viên)", value=u_info['managed_classes'] if u_info['managed_classes'] else "")
            
            btn_save, btn_del = st.columns(2)
            if btn_save.form_submit_button("💾 CẬP NHẬT ĐỒNG BỘ"):
                conn.execute("UPDATE users SET fullname=?, password=?, class_name=?, managed_classes=? WHERE username=?", 
                             (f_name, f_pass, f_class, f_mang, sel_user))
                conn.commit()
                st.success("✅ Đã đồng bộ hóa dữ liệu!")
                st.rerun()
                
            if btn_del.form_submit_button("🗑️ XÓA VĨNH VIỄN"):
                conn.execute("DELETE FROM users WHERE username=?", (sel_user,))
                conn.execute("DELETE FROM mandatory_results WHERE username=?", (sel_user,))
                conn.commit()
                st.warning(f"🔥 Đã xóa tài khoản {sel_user}")
                st.rerun()
    conn.close()

# ==========================================
# 3. GIAO DIỆN PHÂN QUYỀN MỚI (3 CẤP ĐỘ)
# ==========================================
def main():
    st.set_page_config(page_title="LMS LÊ QUÝ ĐÔN V70", layout="wide")
    init_db()

    if 'current_user' not in st.session_state:
        st.markdown("<h2 style='text-align: center;'>🎓 HỆ THỐNG LMS LÊ QUÝ ĐÔN - V70</h2>", unsafe_allow_html=True)
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
                    else: st.error("❌ Sai thông tin!")
    else:
        # SIDEBAR
        role = st.session_state.role
        with st.sidebar:
            st.markdown(f"### 👤 {st.session_state.fullname}")
            st.success(f"CẤP ĐỘ: {role.upper()}")
            
            if role == "core_admin":
                st.markdown("---")
                st.subheader("🔑 API AI Nguồn")
                new_key = st.text_input("Nhập API Key:", value=get_api_key(), type="password")
                if st.button("💾 Lưu và Đồng bộ"):
                    conn = sqlite3.connect('exam_db.sqlite')
                    conn.execute("INSERT OR REPLACE INTO system_settings VALUES ('GEMINI_API_KEY', ?)", (new_key.strip(),))
                    conn.commit(); conn.close()
                    st.success("✅ API đã sẵn sàng!")
            
            st.markdown("---")
            menu = ["✍️ Vào phòng thi", "📊 Bảng điểm", "🔐 Cá nhân"]
            if role == "core_admin":
                menu = ["🏢 Quản trị tối cao", "🤖 AI Generator"] + menu
            elif role == "sub_admin":
                menu = ["👥 Quản lý khu vực", "🤖 AI Generator"] + menu
            
            choice = st.radio("Danh mục chính", menu)
            if st.button("🚪 Thoát hệ thống", use_container_width=True):
                st.session_state.clear(); st.rerun()

        # ĐIỀU HƯỚNG
        if choice == "🏢 Quản trị tối cao":
            st.header("🏢 Bảng điều khiển Giám đốc (Admin Lõi)")
            t1, t2 = st.tabs(["👥 Admin thành viên", "🎓 Toàn bộ học sinh"])
            with t1:
                st.subheader("Tạo Admin thành viên mới")
                with st.form("add_sub"):
                    u_sub = st.text_input("Username Sub-Admin")
                    p_sub = st.text_input("Mật khẩu")
                    n_sub = st.text_input("Họ tên")
                    m_sub = st.text_input("Vùng quản lý (VD: Khối 9, Lớp 9A)")
                    if st.form_submit_button("✅ Cấp quyền Admin"):
                        conn = sqlite3.connect('exam_db.sqlite')
                        conn.execute("INSERT INTO users (username, password, role, fullname, managed_classes) VALUES (?,?,'sub_admin',?,?)", (u_sub, p_sub, n_sub, m_sub))
                        conn.commit(); conn.close(); st.rerun()
                st.divider()
                manage_accounts_ui("sub_admin", "")
            with t2: manage_accounts_ui("student", "")

        elif choice == "👥 Quản lý khu vực":
            st.header("👥 Quản lý lớp học (Admin thành viên)")
            # Admin thành viên quản lý học sinh (Sửa, Xóa, Đổi mật khẩu)
            manage_accounts_ui("student", st.session_state.managed)

        elif choice == "✍️ Vào phòng thi":
            st.header("📝 Phòng thi trực tuyến")
            # Hiển thị bài thi...

if __name__ == "__main__":
    main()
