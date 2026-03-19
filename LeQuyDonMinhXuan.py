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

# --- CẤU HÌNH HỆ THỐNG ---
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

def check_username_exists(username, class_name):
    conn = sqlite3.connect('exam_db.sqlite')
    count = conn.execute("SELECT COUNT(*) FROM users WHERE username=? AND class_name=?", (username, class_name)).fetchone()[0]
    conn.close()
    return count > 0

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
# 3. MODULE NHẬP DỮ LIỆU HỌC SINH (DÀNH CHO ADMIN THÀNH VIÊN)
# ==========================================
def input_student_ui(current_managed_classes):
    st.markdown("### 📥 Quản lý nhập liệu học sinh")
    t1, t2 = st.tabs(["📁 Nạp File Excel", "✍️ Nhập thủ công"])
    
    with t1:
        # Tạo file Excel mẫu
        df_sample = pd.DataFrame(columns=["Họ và tên", "Ngày sinh", "Lớp", "Tên trường"])
        df_sample.loc[0] = ["Nguyễn Văn An", "15/08/2010", "9A1", "THCS Lê Quý Đôn"]
        out = BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as w: df_sample.to_excel(w, index=False)
        st.download_button("⬇️ Tải File Excel Mẫu", out.getvalue(), "Mau_Hoc_Sinh.xlsx")
        
        up = st.file_uploader("Nạp danh sách học sinh (Excel)", type="xlsx")
        if up and st.button("🚀 Bắt đầu nạp dữ liệu"):
            df = pd.read_excel(up)
            conn = sqlite3.connect('exam_db.sqlite')
            s, f = 0, 0
            for _, r in df.iterrows():
                name, dob, cls, sch = str(r['Họ và tên']), str(r['Ngày sinh']), str(r['Lớp']), str(r['Tên trường'])
                uname = remove_accents(name)
                
                # Logic kiểm tra trùng tên trong lớp
                if check_username_exists(uname, cls):
                    if dob == 'nan' or not dob:
                        f += 1; continue # Bỏ qua nếu trùng mà không có ngày sinh
                    suffix = "".join(filter(str.isdigit, dob))
                    uname = f"{uname}{suffix}"
                
                try:
                    conn.execute("INSERT INTO users (username, password, role, fullname, dob, class_name, school) VALUES (?,?,?,?,?,?,?)",
                                 (uname, uname, 'student', name, dob, cls, sch))
                    s += 1
                except: f += 1
            conn.commit(); conn.close()
            st.success(f"✅ Đã nạp thành công: {s} học sinh. Thất bại: {f}.")

    with t2:
        with st.form("manual_student"):
            c1, c2 = st.columns(2)
            f_name = c1.text_input("Họ và Tên (Bắt buộc)")
            f_class = c2.text_input("Lớp (Bắt buộc)")
            f_dob = c1.text_input("Ngày sinh (Chỉ bắt buộc nếu trùng tên)")
            f_school = c2.text_input("Tên trường")
            if st.form_submit_button("✅ Khởi tạo học sinh"):
                uname = remove_accents(f_name)
                if check_username_exists(uname, f_class):
                    if not f_dob:
                        st.error("Phát hiện trùng tên trong lớp! Vui lòng nhập Ngày sinh.")
                    else:
                        suffix = "".join(filter(str.isdigit, f_dob))
                        uname = f"{uname}{suffix}"
                
                if uname:
                    conn = sqlite3.connect('exam_db.sqlite')
                    try:
                        conn.execute("INSERT INTO users (username, password, role, fullname, dob, class_name, school) VALUES (?,?,?,?,?,?,?)",
                                     (uname, uname, 'student', f_name, f_dob, f_class, f_school))
                        conn.commit(); st.success(f"Tạo thành công tài khoản: {uname}")
                    except: st.error("Lỗi: Tài khoản đã tồn tại.")
                    conn.close()

# ==========================================
# 4. GIAO DIỆN PHÂN QUYỀN 3 TẦNG (V100)
# ==========================================
def main():
    st.set_page_config(page_title="LMS Lê Quý Đôn V100", layout="wide")
    init_db()

    if 'current_user' not in st.session_state:
        st.markdown("<h2 style='text-align: center;'>🎓 HỆ THỐNG LMS LÊ QUÝ ĐÔN V100</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.2, 1])
        with col2:
            with st.form("login"):
                u = st.text_input("Tài khoản").strip()
                p = st.text_input("Mật khẩu", type="password").strip()
                if st.form_submit_button("🚀 ĐĂNG NHẬP"):
                    conn = sqlite3.connect('exam_db.sqlite')
                    res = conn.execute("SELECT role, fullname, managed_classes FROM users WHERE username=? AND password=?", (u, p)).fetchone()
                    conn.close()
                    if res:
                        st.session_state.current_user, st.session_state.role, st.session_state.fullname, st.session_state.managed = u, res[0], res[1], res[2]
                        st.rerun()
                    else: st.error("❌ Sai thông tin đăng nhập!")
    else:
        role = st.session_state.role
        with st.sidebar:
            st.markdown(f"### 👤 {st.session_state.fullname}")
            st.success(f"CẤP ĐỘ: {role.upper()}")
            
            if role == "core_admin":
                st.markdown("---")
                st.subheader("🔑 Cấu hình API Nguồn")
                new_key = st.text_input("Gemini API Key:", value=get_api_key(), type="password")
                if st.button("💾 Lưu API"):
                    conn = sqlite3.connect('exam_db.sqlite')
                    conn.execute("INSERT OR REPLACE INTO system_settings VALUES ('GEMINI_API_KEY', ?)", (new_key.strip(),))
                    conn.commit(); conn.close(); st.success("✅ Đã lưu!")
            
            st.markdown("---")
            menu = ["✍️ Vào phòng thi", "📊 Bảng điểm", "🔐 Cá nhân"]
            if role == "core_admin": menu = ["🛡️ Quản trị tối cao"] + menu
            elif role == "sub_admin": menu = ["👥 Quản lý khu vực", "🤖 AI Sinh đề"] + menu
            
            choice = st.radio("Menu chính", menu)
            if st.button("🚪 Đăng xuất", use_container_width=True): st.session_state.clear(); st.rerun()

        # --- ĐIỀU HƯỚNG TÁC VỤ ---
        if choice == "🛡️ Quản trị tối cao":
            st.header("🛡️ Quản trị tối cao (Admin Lõi)")
            # CHỈ CHO PHÉP TẠO ADMIN THÀNH VIÊN VÀ QUẢN LÝ NHÂN SỰ CẤP CAO
            st.subheader("Tạo Admin Thành viên mới")
            with st.form("add_sa"):
                u_sa, p_sa, n_sa, m_sa = st.text_input("Username"), st.text_input("Mật khẩu"), st.text_input("Họ tên"), st.text_input("Lớp quản lý")
                if st.form_submit_button("✅ Cấp quyền Admin"):
                    conn = sqlite3.connect('exam_db.sqlite')
                    conn.execute("INSERT INTO users (username, password, role, fullname, managed_classes) VALUES (?,?,'sub_admin',?,?)", (u_sa, p_sa, n_sa, m_sa))
                    conn.commit(); conn.close(); st.rerun()

        elif choice == "👥 Quản lý khu vực":
            st.header("👥 Quản trị khu vực (Admin Thành viên)")
            input_student_ui(st.session_state.managed)
            # Module Sửa/Xóa học sinh dành cho Admin Thành viên...

if __name__ == "__main__":
    main()
