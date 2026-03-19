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
# 1. TIỆN ÍCH XỬ LÝ USERNAME (TỰ ĐỘNG ĐÁNH SỐ)
# ==========================================
def remove_accents(input_str):
    if not input_str: return ""
    nfkd_form = unicodedata.normalize('NFKD', str(input_str))
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).replace(" ", "").lower()

def gen_smart_username(fullname):
    base_name = remove_accents(fullname)
    base_user = f"lqd_{base_name}"
    
    conn = sqlite3.connect('exam_db.sqlite')
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM users WHERE username=?", (base_user,))
    if c.fetchone()[0] == 0:
        conn.close()
        return base_user
        
    counter = 1
    while True:
        new_user = f"{base_user}{counter}"
        c.execute("SELECT COUNT(*) FROM users WHERE username=?", (new_user,))
        if c.fetchone()[0] == 0:
            conn.close()
            return new_user
        counter += 1

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
    # CHỐT CHẶN AN TOÀN: Ép tạo bảng ngay trước khi Insert để chống lỗi Streamlit Cloud
    conn.execute('''CREATE TABLE IF NOT EXISTS deletion_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        deleted_by TEXT, 
        entity_type TEXT, 
        entity_name TEXT, 
        reason TEXT, 
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        
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
                f_sch = c2.text_
