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
# 1. TIỆN ÍCH XỬ LÝ CHUỖI & USERNAME (V95)
# ==========================================
def remove_accents(input_str):
    if not input_str: return ""
    # Chuẩn hóa unicode để loại bỏ dấu tiếng Việt
    nfkd_form = unicodedata.normalize('NFKD', str(input_str))
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).replace(" ", "").lower()

def gen_smart_username(fullname, dob, class_name):
    base_user = remove_accents(fullname)
    conn = sqlite3.connect('exam_db.sqlite')
    # Kiểm tra xem username này đã tồn tại trong LỚP này chưa
    count = conn.execute("SELECT COUNT(*) FROM users WHERE username=? AND class_name=?", (base_user, class_name)).fetchone()[0]
    conn.close()
    
    if count > 0:
        # Nếu trùng tên, bắt buộc phải có ngày sinh
        if not dob or str(dob).lower() in ['nan', 'none', '']:
            return None # Trả về None để báo lỗi yêu cầu ngày sinh
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
    
    # Khởi tạo Admin Lõi mặc định
    c.execute("INSERT OR IGNORE INTO users (username, password, role, fullname) VALUES (?, ?, 'core_admin', 'Giám Đốc Hệ Thống')", (ADMIN_CORE_EMAIL, ADMIN_CORE_PW))
    conn.commit()
    conn.close()

def get_api_key():
    conn = sqlite3.connect('exam_db.sqlite')
    res = conn.execute("SELECT setting_value FROM system_settings WHERE setting_key='GEMINI_API_KEY'").fetchone()
    conn.close()
    return res[0] if res else ""

# ==========================================
# 3. MODULE NHẬP LIỆU HỌC SINH (EXCEL & THỦ CÔNG)
# ==========================================
def input_student_module(target_managed_classes=None):
    st.markdown("### 📥 Nhập dữ liệu học sinh")
    t1, t2 = st.tabs(["📁 Nạp File Excel", "✍️ Nhập thủ công"])
    
    with t1:
        # Tạo File Mẫu
        df_sample = pd.DataFrame(columns=["Họ và tên", "Ngày sinh", "Lớp", "Tên trường"])
        df_sample.loc[0] = ["Nguyễn Văn An", "15/08/2010", "9A1", "THCS Lê Quý Đôn"]
        out = BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as w: df_sample.to_excel(w, index=False)
        st.download_button("⬇️ Tải File Excel Mẫu", out.getvalue(), "Mau_Danh_Sach_HS.xlsx")
        
        up_file = st.file_uploader("Tải lên file Excel học sinh", type="xlsx")
        if up_file and st.button("🚀 Tiến hành nạp dữ liệu"):
            df = pd.read_excel(up_file)
            conn = sqlite3.connect('exam_db.sqlite')
            s, f = 0, 0
            for _, r in df.iterrows():
                name, dob, cls, sch = r['Họ và tên'], r['Ngày sinh'], r['Lớp'], r['Tên trường']
                uname = gen_smart_username(name, dob, cls)
                if uname:
                    try:
                        conn.execute("INSERT INTO users (username, password, role, fullname, dob, class_name, school) VALUES (?,?,?,?,?,?,?)",
                                     (uname, uname, 'student', name, str(dob), str(cls), str(sch)))
                        s += 1
                    except: f += 1
                else: f += 1
            conn.commit(); conn.close()
            st.success(f"✅ Thành công: {s} | ❌ Thất bại: {f} (Do trùng tên thiếu ngày sinh hoặc lỗi định dạng)")

    with t2:
        with st.form("manual_add"):
            c1, c2 = st.columns(2)
            f_name = c1.text_input("Họ và tên (Bắt buộc)")
            f_class = c2.text_input("Lớp (Bắt buộc)")
            f_dob = c1.text_input("Ngày sinh (Bắt buộc nếu trùng tên)")
            f_school = c2.text_input("Tên trường")
            if st.form_submit_button("✅ Tạo tài khoản"):
                if not f_name or not f_class:
                    st.error("Vui lòng điền đủ Họ tên và Lớp!")
                else:
                    uname = gen_smart_username(f_name, f_dob, f_class)
                    if uname:
                        conn = sqlite3.connect('exam_db.sqlite')
                        try:
                            conn.execute("INSERT INTO users (username, password, role, fullname, dob, class_name, school) VALUES (?,?,?,?,?,?,?)",
                                         (uname, uname, 'student', f_name, f_dob, f_class, f_school))
                            conn.commit(); st.success(f"Đã tạo: {uname}")
                        except: st.error("Lỗi: Tài khoản đã tồn tại!")
                        conn.close()
                    else: st.error("Hệ thống phát hiện trùng tên! Vui lòng nhập thêm Ngày sinh.")

# ==========================================
# 4. GIAO DIỆN PHÂN QUYỀN 3 TẦNG
# ==========================================
def main():
    st.set_page_config(page_title="LMS Lê Quý Đôn V95", layout="wide")
    init_db()

    if 'current_user' not in st.session_state:
        st.markdown("<h2 style='text-align: center; color:#1E88E5;'>🏫 HỆ THỐNG QUẢN LÝ HỌC TẬP V95</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.2, 1])
        with col2:
            with st.form("login_gate"):
                u = st.text_input("👤 Tài khoản").strip()
                p = st.text_input("🔑 Mật khẩu", type="password").strip()
                if st.form_submit_button("🚀 ĐĂNG NHẬP", use_container_width=True):
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
            st.info(f"VAI TRÒ: {role.upper()}")
            
            if role == "core_admin":
                st.markdown("---")
                st.subheader("🔑 Cấu hình API AI")
                new_key = st.text_input("Nhập Gemini API Key:", value=get_api_key(), type="password")
                if st.button("💾 Lưu mã API"):
                    conn = sqlite3.connect('exam_db.sqlite')
                    conn.execute("INSERT OR REPLACE INTO system_settings VALUES ('GEMINI_API_KEY', ?)", (new_key.strip(),))
                    conn.commit(); conn.close(); st.success("✅ Đã lưu thành công!")
            
            st.markdown("---")
            menu = ["✍️ Vào phòng thi", "📊 Bảng điểm", "🔐 Cá nhân"]
            if role == "core_admin": menu = ["🛡️ Quản trị tối cao", "🤖 AI Sinh đề"] + menu
            elif role == "sub_admin": menu = ["👥 Quản lý khu vực", "🤖 AI Sinh đề"] + menu
            
            choice = st.radio("Danh mục chính", menu)
            if st.button("🚪 Thoát", use_container_width=True): st.session_state.clear(); st.rerun()

        # --- ĐIỀU HƯỚNG ---
        if choice == "🛡️ Quản trị tối cao":
            st.header("🛡️ Quản trị tối cao (Admin Lõi)")
            t1, t2, t3 = st.tabs(["👥 Admin thành viên", "🎓 Quản lý học sinh", "📥 Nhập dữ liệu HS"])
            with t1:
                # Chức năng tạo Admin Thành viên và Xóa Admin Thành viên...
                st.write("Dùng để tạo và quản lý Admin thành viên khu vực.")
            with t2:
                # Chức năng sửa/xóa học sinh toàn trường
                st.write("Quản lý danh sách học sinh toàn hệ thống.")
            with t3: input_student_module("")

        elif choice == "👥 Quản lý khu vực":
            st.header("👥 Quản trị khu vực (Admin thành viên)")
            t1, t2 = st.tabs(["🎓 Danh sách lớp", "📥 Nhập dữ liệu HS"])
            with t1: 
                st.write(f"Quản lý lớp: {st.session_state.managed}")
                # Module Sửa/Xóa học sinh trong phạm vi quản lý
            with t2: input_student_module(st.session_state.managed)

if __name__ == "__main__":
    main()
