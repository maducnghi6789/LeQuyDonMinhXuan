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
# 1. TIỆN ÍCH XỬ LÝ USERNAME (lqd_ + không dấu)
# ==========================================
def remove_accents(input_str):
    if not input_str: return ""
    nfkd_form = unicodedata.normalize('NFKD', str(input_str))
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).replace(" ", "").lower()

def gen_smart_username(fullname, dob, class_name):
    base_name = remove_accents(fullname)
    base_user = f"lqd_{base_name}"
    conn = sqlite3.connect('exam_db.sqlite')
    count = conn.execute("SELECT COUNT(*) FROM users WHERE username=? AND class_name=?", (base_user, class_name)).fetchone()[0]
    conn.close()
    if count > 0:
        if not dob or str(dob).lower() in ['nan', 'none', '']: return None
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
    conn.commit(); conn.close()

def get_api_key():
    conn = sqlite3.connect('exam_db.sqlite')
    res = conn.execute("SELECT setting_value FROM system_settings WHERE setting_key='GEMINI_API_KEY'").fetchone()
    conn.close()
    return res[0] if res else ""

# ==========================================
# 3. MODULE QUẢN LÝ TÀI KHOẢN ĐỒNG BỘ
# ==========================================
def account_manager_ui(target_role, specific_class=None):
    conn = sqlite3.connect('exam_db.sqlite')
    query = f"SELECT * FROM users WHERE role='{target_role}'"
    
    # Nếu lọc theo lớp (Dành cho Admin Lõi quản lý theo lớp)
    if specific_class and specific_class != "Tất cả các lớp":
        query += f" AND class_name='{specific_class}'"
    
    df = pd.read_sql_query(query, conn)
    if not df.empty:
        st.dataframe(df[['username', 'fullname', 'password', 'class_name', 'school']], use_container_width=True)
        sel_u = st.selectbox(f"Chọn {target_role} để xử lý:", ["-- Chọn --"] + df['username'].tolist(), key=f"sel_{target_role}_{specific_class}")
        if sel_u != "-- Chọn --":
            u_data = df[df['username'] == sel_u].iloc[0]
            with st.form(f"form_{sel_u}"):
                c1, c2 = st.columns(2)
                f_name = c1.text_input("Họ và Tên", value=u_data['fullname'])
                f_pass = c2.text_input("Mật khẩu", value=u_data['password'])
                f_cls = c1.text_input("Lớp", value=u_data['class_name'] if u_data['class_name'] else "")
                f_sch = c2.text_input("Trường", value=u_data['school'] if u_data['school'] else "")
                
                b_up, b_del = st.columns(2)
                if b_up.form_submit_button("💾 CẬP NHẬT"):
                    conn.execute("UPDATE users SET fullname=?, password=?, class_name=?, school=? WHERE username=?", (f_name, f_pass, f_cls, f_sch, sel_u))
                    conn.commit(); st.success("✅ Đã cập nhật!"); time.sleep(0.5); st.rerun()
                if b_del.form_submit_button("🗑️ XÓA TÀI KHOẢN"):
                    conn.execute("DELETE FROM users WHERE username=?", (sel_u,))
                    conn.commit(); st.warning(f"💥 Đã xóa {sel_u}"); time.sleep(0.5); st.rerun()
    else: st.info(f"Chưa có dữ liệu cho mục này.")
    conn.close()

# ==========================================
# 4. GIAO DIỆN CHÍNH
# ==========================================
def main():
    st.set_page_config(page_title="LMS Lê Quý Đôn V100 Premium", layout="wide")
    init_db()

    if 'current_user' not in st.session_state:
        st.markdown("<h2 style='text-align: center;'>🎓 HỆ THỐNG LMS LÊ QUÝ ĐÔN V100 PREMIUM</h2>", unsafe_allow_html=True)
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
            menu = ["✍️ Phòng thi", "📊 Bảng điểm", "🔐 Cá nhân"]
            if role == "core_admin": menu = ["🛡️ Quản trị tối cao"] + menu
            elif role == "sub_admin": menu = ["👥 Quản lý khu vực", "🤖 AI Sinh đề"] + menu
            choice = st.radio("Menu chính", menu)
            if st.button("🚪 Thoát", use_container_width=True): st.session_state.clear(); st.rerun()

        if choice == "🛡️ Quản trị tối cao":
            st.header("🛡️ Quản trị tối cao (Admin Lõi)")
            t1, t2 = st.tabs(["👥 Quản lý Admin thành viên", "🎓 Quản lý học sinh theo lớp"])
            with t1:
                with st.form("add_sub"):
                    u_s, p_s = st.text_input("Username Admin TV"), st.text_input("Mật khẩu")
                    n_s, m_s = st.text_input("Họ tên"), st.text_input("Lớp/Vùng quản lý")
                    if st.form_submit_button("✅ Cấp quyền Admin TV"):
                        conn = sqlite3.connect('exam_db.sqlite')
                        conn.execute("INSERT INTO users (username, password, role, fullname, managed_classes) VALUES (?,?,'sub_admin',?,?)", (u_s, p_s, n_s, m_s))
                        conn.commit(); conn.close(); st.rerun()
                st.divider()
                account_manager_ui("sub_admin")
            with t2:
                conn = sqlite3.connect('exam_db.sqlite')
                all_classes = [r[0] for r in conn.execute("SELECT DISTINCT class_name FROM users WHERE role='student' AND class_name IS NOT NULL").fetchall()]
                conn.close()
                selected_class = st.selectbox("📌 Chọn lớp học để giám sát dữ liệu:", ["Tất cả các lớp"] + all_classes)
                account_manager_ui("student", specific_class=selected_class)

        elif choice == "👥 Quản lý khu vực":
            st.header("👥 Quản lý khu vực (Admin Thành viên)")
            # Module của Admin thành viên nạp Excel & quản lý học sinh của họ
            st.info(f"Khu vực quản lý: {st.session_state.managed}")

if __name__ == "__main__":
    main()
