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
# 3. MODULE NHẬP DỮ LIỆU & QUẢN LÝ TÁC VỤ (VIỆT HÓA)
# ==========================================
def student_management_module(managed_filter=None):
    st.markdown("### 📥 Nhập dữ liệu & Quản lý Học sinh")
    t1, t2, t3 = st.tabs(["📁 Nạp File Excel", "✍️ Nhập thủ công", "🛠️ Chỉnh sửa/Xóa"])
    
    with t1:
        # Tạo file mẫu
        df_sample = pd.DataFrame(columns=["Họ và tên", "Ngày sinh", "Lớp", "Tên trường"])
        df_sample.loc[0] = ["Nguyễn Văn An", "15/08/2010", "9A1", "THCS Lê Quý Đôn"]
        out = BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as w: df_sample.to_excel(w, index=False)
        st.download_button("⬇️ Tải File Mẫu", out.getvalue(), "Mau_Hoc_Sinh.xlsx")
        
        up = st.file_uploader("Nạp Excel học sinh", type="xlsx")
        if up and st.button("🚀 Bắt đầu nạp"):
            df = pd.read_excel(up)
            conn = sqlite3.connect('exam_db.sqlite')
            s, f = 0, 0
            for _, r in df.iterrows():
                name, dob, cls, sch = str(r['Họ và tên']), str(r['Ngày sinh']), str(r['Lớp']), str(r['Tên trường'])
                uname = remove_accents(name)
                if check_username_exists(uname, cls):
                    if not dob or dob == 'nan': f += 1; continue
                    uname = f"{uname}{''.join(filter(str.isdigit, dob))}"
                try:
                    conn.execute("INSERT INTO users (username, password, role, fullname, dob, class_name, school) VALUES (?,?,?,?,?,?,?)",
                                 (uname, uname, 'student', name, dob, cls, sch))
                    s += 1
                except: f += 1
            conn.commit(); conn.close(); st.success(f"✅ Đã nạp: {s} | ❌ Lỗi: {f}")

    with t2:
        with st.form("manual_st"):
            c1, c2 = st.columns(2)
            f_n, f_c = c1.text_input("Họ và Tên"), c2.text_input("Lớp")
            f_d, f_s = c1.text_input("Ngày sinh"), c2.text_input("Tên trường")
            if st.form_submit_button("✅ Khởi tạo"):
                uname = remove_accents(f_n)
                if check_username_exists(uname, f_c):
                    if not f_d: st.error("Trùng tên! Nhập ngày sinh.")
                    else: uname = f"{uname}{''.join(filter(str.isdigit, f_d))}"
                if uname:
                    conn = sqlite3.connect('exam_db.sqlite')
                    conn.execute("INSERT INTO users (username, password, role, fullname, dob, class_name, school) VALUES (?,?,?,?,?,?,?)",
                                 (uname, uname, 'student', f_n, f_d, f_c, f_s))
                    conn.commit(); conn.close(); st.success(f"Tạo: {uname}")

    with t3:
        st.subheader("🛠️ Tác vụ Sửa/Xóa học sinh")
        conn = sqlite3.connect('exam_db.sqlite')
        query = "SELECT * FROM users WHERE role='student'"
        if managed_filter and st.session_state.role != 'core_admin':
            cls_list = "','".join([x.strip() for x in managed_filter.split(',')])
            query += f" AND class_name IN ('{cls_list}')"
        df_view = pd.read_sql_query(query, conn)
        st.dataframe(df_view[['username', 'fullname', 'password', 'class_name']], use_container_width=True)
        
        sel_u = st.selectbox("Chọn học sinh xử lý:", ["-- Chọn --"] + df_view['username'].tolist())
        if sel_u != "-- Chọn --":
            u_data = df_view[df_view['username'] == sel_u].iloc[0]
            with st.form(f"edit_{sel_u}"):
                new_pw = st.text_input("Đổi mật khẩu", value=u_data['password'])
                btn_u, btn_d = st.columns(2)
                if btn_u.form_submit_button("💾 Cập nhật"):
                    conn.execute("UPDATE users SET password=? WHERE username=?", (new_pw, sel_u))
                    conn.commit(); st.rerun()
                if btn_d.form_submit_button("🗑️ Xóa tài khoản"):
                    conn.execute("DELETE FROM users WHERE username=?", (sel_u,))
                    conn.commit(); st.rerun()
        conn.close()

# ==========================================
# 4. GIAO DIỆN PHÂN QUYỀN V100 (ARCHITECT)
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
                    else: st.error("❌ Sai thông tin!")
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
            if st.button("🚪 Thoát", use_container_width=True): st.session_state.clear(); st.rerun()

        if choice == "🛡️ Quản trị tối cao":
            st.header("🛡️ Quản trị tối cao (Admin Lõi)")
            st.subheader("Quản lý Admin Thành viên")
            with st.form("add_sub"):
                c1, c2 = st.columns(2)
                u_s, p_s = c1.text_input("Username Admin TV"), c2.text_input("Mật khẩu")
                n_s, m_s = c1.text_input("Họ tên"), c2.text_input("Vùng/Lớp quản lý")
                if st.form_submit_button("✅ Khởi tạo Admin Thành viên"):
                    conn = sqlite3.connect('exam_db.sqlite')
                    conn.execute("INSERT INTO users (username, password, role, fullname, managed_classes) VALUES (?,?,'sub_admin',?,?)", (u_s, p_s, n_s, m_s))
                    conn.commit(); conn.close(); st.rerun()
            
            # DANH SÁCH VÀ SỬA (KHÔNG XÓA THEO YÊU CẦU)
            conn = sqlite3.connect('exam_db.sqlite')
            df_sub = pd.read_sql_query("SELECT username, fullname, password, managed_classes FROM users WHERE role='sub_admin'", conn)
            st.dataframe(df_sub, use_container_width=True)
            st.warning("⚠️ Chế độ bảo vệ: Admin Lõi không được phép xóa Admin thành viên để bảo toàn hệ thống.")
            conn.close()

        elif choice == "👥 Quản lý khu vực":
            st.header("👥 Quản lý lớp học (Admin Thành viên)")
            student_management_module(st.session_state.managed)

if __name__ == "__main__":
    main()
