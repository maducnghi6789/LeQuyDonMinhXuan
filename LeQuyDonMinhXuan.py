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
# 2. HỆ QUẢN TRỊ CƠ SỞ DỮ LIỆU & NHẬT KÝ
# ==========================================
def init_db():
    conn = sqlite3.connect('exam_db.sqlite')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY, password TEXT, role TEXT, 
        fullname TEXT, dob TEXT, class_name TEXT, 
        school TEXT, managed_classes TEXT)''')
    
    # Migration tự động tránh KeyError
    try: c.execute("ALTER TABLE users ADD COLUMN school TEXT")
    except: pass
    try: c.execute("ALTER TABLE users ADD COLUMN managed_classes TEXT")
    except: pass
    
    c.execute('''CREATE TABLE IF NOT EXISTS system_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_exams (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, questions_json TEXT, start_time TEXT, end_time TEXT, target_class TEXT, file_data TEXT, file_type TEXT, answer_key TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_results (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, exam_id INTEGER, score REAL, user_answers_json TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS deletion_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, deleted_by TEXT, entity_type TEXT, entity_name TEXT, reason TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute("INSERT OR IGNORE INTO users (username, password, role, fullname) VALUES (?, ?, 'core_admin', 'Giám Đốc Hệ Thống')", (ADMIN_CORE_EMAIL, ADMIN_CORE_PW))
    conn.commit(); conn.close()

def log_deletion(deleted_by, entity_type, entity_name, reason):
    conn = sqlite3.connect('exam_db.sqlite')
    vn_time = datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("INSERT INTO deletion_logs (deleted_by, entity_type, entity_name, reason, timestamp) VALUES (?, ?, ?, ?, ?)", 
                 (deleted_by, entity_type, entity_name, reason, vn_time))
    conn.commit(); conn.close()

def get_api_key():
    conn = sqlite3.connect('exam_db.sqlite')
    res = conn.execute("SELECT setting_value FROM system_settings WHERE setting_key='GEMINI_API_KEY'").fetchone()
    conn.close()
    return res[0] if res else ""

# ==========================================
# 3. MODULE TÁC VỤ (QUẢN LÝ, NHẬP LIỆU, XÓA LỚP)
# ==========================================
def account_manager_ui(target_role, specific_class=None):
    st.markdown(f"#### 🛠️ Quản lý danh sách {target_role}")
    conn = sqlite3.connect('exam_db.sqlite')
    query = f"SELECT * FROM users WHERE role='{target_role}'"
    
    # Đồng bộ hóa: Bộ lọc lớp hiển thị chính xác theo yêu cầu
    if specific_class and specific_class != "Tất cả các lớp":
        query += f" AND class_name='{specific_class}'"
    
    df = pd.read_sql_query(query, conn)
    if not df.empty:
        cols = ['username', 'fullname', 'password', 'class_name']
        if 'school' in df.columns: cols.append('school')
        if 'managed_classes' in df.columns and target_role == 'sub_admin': cols.append('managed_classes')
        
        st.dataframe(df[cols], use_container_width=True)
        
        sel_u = st.selectbox(f"Chọn {target_role} để xử lý:", ["-- Chọn --"] + df['username'].tolist(), key=f"sel_{target_role}_{specific_class}")
        if sel_u != "-- Chọn --":
            u_data = df[df['username'] == sel_u].iloc[0]
            with st.form(f"form_{sel_u}"):
                c1, c2 = st.columns(2)
                f_name = c1.text_input("Họ và Tên", value=u_data['fullname'])
                f_pass = c2.text_input("Mật khẩu", value=u_data['password'])
                f_cls = c1.text_input("Lớp", value=u_data['class_name'] if u_data['class_name'] else "")
                f_sch = c2.text_input("Trường", value=u_data.get('school', '') if pd.notna(u_data.get('school')) else "")
                
                # Chỉ hiển thị quyền quản lý nếu là Admin thành viên
                f_man = st.text_input("Quyền quản lý (Dành cho Admin thành viên)", value=u_data.get('managed_classes', '') if pd.notna(u_data.get('managed_classes')) else "") if target_role == 'sub_admin' else ""
                
                b_up, b_del = st.columns(2)
                if b_up.form_submit_button("💾 CẬP NHẬT ĐỒNG BỘ"):
                    if target_role == 'sub_admin':
                        conn.execute("UPDATE users SET fullname=?, password=?, class_name=?, school=?, managed_classes=? WHERE username=?", 
                                     (f_name, f_pass, f_cls, f_sch, f_man, sel_u))
                    else:
                        conn.execute("UPDATE users SET fullname=?, password=?, class_name=?, school=? WHERE username=?", 
                                     (f_name, f_pass, f_cls, f_sch, sel_u))
                    conn.commit(); st.success("✅ Đã cập nhật!"); time.sleep(0.5); st.rerun()
                
                if b_del.form_submit_button("🗑️ XÓA TÀI KHOẢN"):
                    log_deletion(st.session_state.current_user, "Tài khoản", sel_u, "Xóa thủ công từ bảng quản lý")
                    conn.execute("DELETE FROM users WHERE username=?", (sel_u,))
                    conn.execute("DELETE FROM mandatory_results WHERE username=?", (sel_u,))
                    conn.commit(); st.warning(f"💥 Đã xóa {sel_u}"); time.sleep(0.5); st.rerun()
    else: st.info("Chưa có dữ liệu.")
    conn.close()

# --- MODULE TẠO TÀI KHOẢN & NHẬP DỮ LIỆU ---
def import_student_module():
    st.markdown("### 📥 Nhập dữ liệu & Tạo tài khoản Học sinh")
    t1, t2 = st.tabs(["📁 Nạp File Excel", "✍️ Nhập thủ công"])
    with t1:
        df_sample = pd.DataFrame(columns=["Họ và tên", "Ngày sinh", "Lớp", "Tên trường"])
        df_sample.loc[0] = ["Nguyễn Văn An", "15/08/2010", "9A1", "Lê Quý Đôn"]
        out = BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as w: df_sample.to_excel(w, index=False)
        st.download_button("⬇️ Tải file mẫu", out.getvalue(), "Mau_Hoc_Sinh.xlsx")
        
        up = st.file_uploader("Nạp Excel", type="xlsx")
        if up and st.button("🚀 Nạp dữ liệu"):
            df = pd.read_excel(up)
            conn = sqlite3.connect('exam_db.sqlite')
            s, f = 0, 0
            for _, r in df.iterrows():
                name, dob, cls, sch = str(r.get('Họ và tên', '')), str(r.get('Ngày sinh', '')), str(r.get('Lớp', '')), str(r.get('Tên trường', ''))
                if name and name.lower() != 'nan' and cls and cls.lower() != 'nan':
                    uname = gen_smart_username(name, dob, cls)
                    if uname:
                        try:
                            conn.execute("INSERT INTO users (username, password, role, fullname, dob, class_name, school) VALUES (?,?,?,?,?,?,?)",
                                         (uname, uname, 'student', name, dob, cls, sch))
                            s += 1
                        except: f += 1
                    else: f += 1
                else: f += 1
            conn.commit(); conn.close(); st.success(f"✅ Tạo thành công: {s} tài khoản | ❌ Thất bại: {f} (Trùng tên thiếu ngày sinh hoặc thiếu dữ liệu)")
    with t2:
        with st.form("manual_add_st"):
            c1, c2 = st.columns(2)
            n = c1.text_input("Họ và Tên (Bắt buộc)")
            c = c2.text_input("Lớp (Bắt buộc)")
            d = c1.text_input("Ngày sinh (Bắt buộc nếu trùng)")
            sch = c2.text_input("Trường")
            if st.form_submit_button("✅ Tạo tài khoản học sinh"):
                if not n or not c:
                    st.error("Vui lòng điền đủ Họ tên và Lớp!")
                else:
                    u = gen_smart_username(n, d, c)
                    if u:
                        conn = sqlite3.connect('exam_db.sqlite')
                        try:
                            conn.execute("INSERT INTO users (username, password, role, fullname, dob, class_name, school) VALUES (?,?,?,?,?,?,?)", (u, u, 'student', n, d, c, sch))
                            conn.commit(); st.success(f"✅ Đã tạo tài khoản: {u}")
                        except:
                            st.error("Lỗi: Tài khoản đã tồn tại!")
                        conn.close()
                    else: st.error("Trùng tên! Yêu cầu nhập thêm Ngày sinh.")

# --- MODULE XÓA LỚP HỌC ĐỒNG BỘ (CHỈ DÀNH CHO ADMIN LÕI) ---
def delete_class_module(all_classes):
    st.
