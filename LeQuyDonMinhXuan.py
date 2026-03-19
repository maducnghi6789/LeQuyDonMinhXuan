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

# --- KẾT NỐI THƯ VIỆN AI ---
try:
    import google.generativeai as genai
    AI_AVAILABLE = True
except:
    AI_AVAILABLE = False

VN_TZ = timezone(timedelta(hours=7))

# ==========================================
# 1. HỆ QUẢN TRỊ CƠ SỞ DỮ LIỆU & API KEY
# ==========================================
def init_db():
    conn = sqlite3.connect('exam_db.sqlite')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY, password TEXT, role TEXT, 
        fullname TEXT, dob TEXT, class_name TEXT, managed_classes TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS system_settings (
        setting_key TEXT PRIMARY KEY, setting_value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_exams (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, questions_json TEXT, 
        start_time TEXT, end_time TEXT, target_class TEXT, 
        file_data TEXT, file_type TEXT, answer_key TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, exam_id INTEGER, 
        score REAL, user_answers_json TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    # Khởi tạo Admin Lõi mặc định (nghihgtq@gmail.com)
    c.execute("INSERT OR IGNORE INTO users (username, password, role, fullname) VALUES (?, ?, 'core_admin', 'Giám Đốc Hệ Thống')", 
              ("nghihgtq@gmail.com", "GiámĐốc2026"))
    conn.commit()
    conn.close()

def get_api_key():
    conn = sqlite3.connect('exam_db.sqlite')
    res = conn.execute("SELECT setting_value FROM system_settings WHERE setting_key='GEMINI_API_KEY'").fetchone()
    conn.close()
    return res[0] if res else ""

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
        conn.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)", (u, p, role, name, "", cls, managed))
        conn.commit(); return True
    except: return False
    finally: conn.close()

# ==========================================
# 3. GIAO DIỆN CHÍNH (VIỆT HÓA 100%)
# ==========================================
def main():
    st.set_page_config(page_title="LMS LÊ QUÝ ĐÔN V60", layout="wide", page_icon="🏫")
    init_db()

    if 'current_user' not in st.session_state:
        # CỔNG ĐĂNG NHẬP
        st.markdown("<h2 style='text-align: center;'>🎓 HỆ THỐNG QUẢN LÝ HỌC TẬP V60</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.2, 1])
        with col2:
            with st.form("login"):
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
        # THANH ĐIỀU HƯỚNG SIDEBAR
        role = st.session_state.role
        with st.sidebar:
            st.markdown(f"### 👤 {st.session_state.fullname}")
            st.info(f"Vai trò: {role.upper()}")
            
            # --- QUẢN LÝ API DÀNH RIÊNG CHO ADMIN LÕI ---
            if role == "core_admin":
                st.markdown("---")
                st.subheader("🔑 Cấu hình API AI")
                curr_key = get_api_key()
                new_key = st.text_input("Nhập Gemini API Key:", value=curr_key, type="password")
                if st.button("💾 Lưu mã API"):
                    save_api_key(new_key.strip())
                    st.success("✅ Đã cập nhật!")
            
            st.markdown("---")
            menu = ["✍️ Làm bài thi", "📊 Kết quả học tập", "🔐 Đổi mật khẩu"]
            if role == "core_admin":
                menu = ["🏢 Quản trị tối cao", "🤖 AI Sinh đề"] + menu
            elif role == "sub_admin":
                menu = ["👥 Quản lý giáo viên"] + menu
            elif role == "teacher":
                menu = ["🏫 Quản lý lớp học"] + menu
            
            choice = st.radio("Menu chính", menu)
            if st.button("🚪 Đăng xuất", use_container_width=True):
                st.session_state.clear(); st.rerun()

        # --- ĐIỀU HƯỚNG CHỨC NĂNG ---
        if "Quản trị tối cao" in choice:
            admin_core_ui()
        elif "Quản lý giáo viên" in choice or "Quản lý lớp học" in choice:
            staff_management_ui(role)
        elif "AI Sinh đề" in choice:
            ai_generator_ui()
        elif "Làm bài thi" in choice:
            student_exam_ui()

# --- PANEL ADMIN LÕI ---
def admin_core_ui():
    st.header("🏢 Tổng quản hệ thống (Admin Lõi)")
    t1, t2 = st.tabs(["👥 Quản lý Admin thành viên", "👨‍🏫 Quản lý Giáo viên"])
    with t1:
        with st.form("add_sub_admin"):
            c1, c2 = st.columns(2)
            u = c1.text_input("Tên đăng nhập Admin thành viên")
            p = c2.text_input("Mật khẩu")
            n = c1.text_input("Họ và tên")
            m = c2.text_input("Lớp/Vùng quản lý (VD: 9A, 9B)")
            if st.form_submit_button("✅ Tạo Admin thành viên"):
                if create_account(u, p, n, "sub_admin", m): st.success("Đã tạo!")
                else: st.error("Lỗi trùng Username!")
        # Hiển thị danh sách...
    with t2:
        st.write("Quản lý danh sách Giáo viên toàn trường...")

# --- PANEL SINH ĐỀ AI (V55 CORE) ---
def ai_generator_ui():
    st.header("🤖 Trí tuệ nhân tạo sinh đề")
    st.write("Hệ thống bám sát ma trận Sở GD&ĐT Tuyên Quang.")
    if st.button("🚀 SINH BỘ ĐỀ 40 CÂU BIẾN THỂ"):
        # Tích hợp hàm ExamGenerator().generate_matrix_exam() từ V55
        st.info("Đang kết nối API và tạo đề...")

# --- PANEL HỌC SINH ---
def student_exam_ui():
    st.header("✍️ Phòng thi trực tuyến")
    t1, t2 = st.tabs(["📝 Bài tập bắt buộc", "🤖 Đề tự luyện AI"])
    with t1:
        st.write("Danh sách bài thi từ giáo viên...")
    with t2:
        st.write("Luyện tập 40 câu chuẩn ma trận...")

if __name__ == "__main__":
    main()
