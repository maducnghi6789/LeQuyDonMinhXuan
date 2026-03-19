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
# 1. TIỆN ÍCH XỬ LÝ USERNAME (SỬA LỖI TRÙNG LẶP)
# ==========================================
def remove_accents(input_str):
    if not input_str: return ""
    nfkd_form = unicodedata.normalize('NFKD', str(input_str))
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).replace(" ", "").lower()

def gen_smart_username(fullname, existing_usernames):
    """Tạo username lqd_ + tên không dấu, tự động đánh số nếu trùng trong bộ nhớ đệm"""
    base_name = remove_accents(fullname)
    base_user = f"lqd_{base_name}"
    
    if base_user not in existing_usernames:
        return base_user
        
    counter = 1
    while True:
        new_user = f"{base_user}{counter}"
        if new_user not in existing_usernames:
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
    conn.execute('''CREATE TABLE IF NOT EXISTS deletion_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, deleted_by TEXT, entity_type TEXT, entity_name TEXT, reason TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
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
# 3. MODULE TÁC VỤ (GIỮ NGUYÊN BẢN V100)
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
                f_sch = c2.text_input("Trường", value=u_data.get('school', '') if pd.notna(u_data.get('school')) else "")
                f_man = st.text_input("Quyền quản lý", value=u_data.get('managed_classes', '') if pd.notna(u_data.get('managed_classes')) else "") if target_role == 'sub_admin' else ""
                
                b_up, b_del = st.columns(2)
                if b_up.form_submit_button("💾 CẬP NHẬT"):
                    if target_role == 'sub_admin':
                        conn.execute("UPDATE users SET fullname=?, password=?, class_name=?, school=?, managed_classes=? WHERE username=?", (f_name, f_pass, f_cls, f_sch, f_man, sel_u))
                    else:
                        conn.execute("UPDATE users SET fullname=?, password=?, class_name=?, school=? WHERE username=?", (f_name, f_pass, f_cls, f_sch, sel_u))
                    conn.commit(); st.success("✅ Đã cập nhật!"); time.sleep(0.5); st.rerun()
                if b_del.form_submit_button("🗑️ XÓA"):
                    log_deletion(st.session_state.current_user, "Tài khoản", sel_u, "Xóa thủ công")
                    conn.execute("DELETE FROM users WHERE username=?", (sel_u,))
                    conn.execute("DELETE FROM mandatory_results WHERE username=?", (sel_u,))
                    conn.commit(); st.warning(f"💥 Đã xóa {sel_u}"); time.sleep(0.5); st.rerun()
    conn.close()

# --- MODULE NHẬP DỮ LIỆU ĐÃ FIX LỖI IMPORT ---
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
            
            # Tự động map tên cột thông minh (Bất chấp dấu cách thừa)
            col_mapping = {}
            for col in df.columns:
                norm_col = remove_accents(str(col)).replace(" ", "").lower()
                if "hovaten" in norm_col or "hoten" in norm_col: col_mapping[col] = "Họ và tên"
                elif "lop" in norm_col: col_mapping[col] = "Lớp"
                elif "ngaysinh" in norm_col: col_mapping[col] = "Ngày sinh"
                elif "truong" in norm_col: col_mapping[col] = "Tên trường"
            df = df.rename(columns=col_mapping)
            
            if "Họ và tên" not in df.columns or "Lớp" not in df.columns:
                st.error("❌ File Excel thiếu cột 'Họ và tên' hoặc 'Lớp'.")
            else:
                conn = sqlite3.connect('exam_db.sqlite')
                # Tải bộ nhớ tạm Username để check trùng ngay lập tức
                existing_usernames = set([r[0] for r in conn.execute("SELECT username FROM users").fetchall()])
                s, f = 0, 0
                error_details = []
                for idx, r in df.iterrows():
                    row_idx = idx + 2
                    name, dob, cls, sch = str(r.get('Họ và tên', '')).strip(), str(r.get('Ngày sinh', '')).strip(), str(r.get('Lớp', '')).strip(), str(r.get('Tên trường', '')).strip()
                    if name and name.lower() != 'nan' and cls and cls.lower() != 'nan':
                        # Tạo username và nạp luôn vào bộ nhớ tạm
                        uname = gen_smart_username(name, existing_usernames)
                        existing_usernames.add(uname)
                        try:
                            conn.execute("INSERT INTO users (username, password, role, fullname, dob, class_name, school) VALUES (?,?,?,?,?,?,?)", (uname, uname, 'student', name, dob, cls, sch))
                            s += 1
                        except Exception as e:
                            f += 1
                            error_details.append(f"- **Dòng {row_idx}:** {str(e)}")
                    else:
                        f += 1
                        error_details.append(f"- **Dòng {row_idx}:** Thiếu Họ tên/Lớp")
                conn.commit(); conn.close()
                st.success(f"✅ Thành công: {s} | ❌ Lỗi: {f}")
                if f > 0:
                    with st.expander("Chi tiết lỗi"):
                        for err in error_details: st.markdown(err)
    with t2:
        with st.form("manual_add"):
            n, c = st.text_input("Họ và tên"), st.text_input("Lớp")
            d, s = st.text_input("Ngày sinh"), st.text_input("Trường")
            if st.form_submit_button("Tạo tài khoản"):
                conn = sqlite3.connect('exam_db.sqlite')
                existing = set([r[0] for r in conn.execute("SELECT username FROM users").fetchall()])
                u = gen_smart_username(n, existing)
                try:
                    conn.execute("INSERT INTO users (username, password, role, fullname, dob, class_name, school) VALUES (?,?,?,?,?,?,?)", (u, u, 'student', n, d, c, s))
                    conn.commit(); st.success(f"Đã tạo: {u}")
                except: st.error("Lỗi!")
                conn.close()

def delete_class_module(all_classes):
    st.markdown("### 🚨 Xóa lớp học")
    if not all_classes: return
    sel_cl = st.selectbox("Chọn lớp xóa:", ["-- Chọn --"] + all_classes)
    if sel_cl != "-- Chọn --":
        reason = st.text_input("Lý do xóa:")
        if st.button("XÁC NHẬN XÓA LỚP", type="primary") and reason:
            conn = sqlite3.connect('exam_db.sqlite')
            stus = [r[0] for r in conn.execute("SELECT username FROM users WHERE class_name=? AND role='student'", (sel_cl,)).fetchall()]
            for u in stus: conn.execute("DELETE FROM mandatory_results WHERE username=?", (u,))
            conn.execute("DELETE FROM users WHERE class_name=? AND role='student'", (sel_cl,))
            subs = conn.execute("SELECT username, managed_classes FROM users WHERE role='sub_admin'").fetchall()
            for sa, mng in subs:
                if mng:
                    new_mng = ", ".join([c.strip() for c in mng.split(',') if c.strip() != sel_cl])
                    conn.execute("UPDATE users SET managed_classes=? WHERE username=?", (new_mng, sa))
            log_deletion(st.session_state.current_user, "Lớp học", sel_cl, reason)
            conn.commit(); conn.close(); st.rerun()

# ==========================================
# 4. GIAO DIỆN CHÍNH (GIỮ NGUYÊN BẢN V100)
# ==========================================
def main():
    st.set_page_config(page_title="LMS Lê Quý Đôn V100 Supreme", layout="wide")
    init_db()
    if 'current_user' not in st.session_state:
        st.markdown("<h2 style='text-align: center;'>🎓 HỆ THỐNG LMS LÊ QUÝ ĐÔN V100</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.2, 1])
        with col2:
            with st.form("login"):
                u = st.text_input("Tài khoản").strip(); p = st.text_input("Mật khẩu", type="password").strip()
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
                st.subheader("🔑 Cấu hình API")
                new_key = st.text_input("Gemini API Key:", value=get_api_key(), type="password")
                if st.button("💾 Lưu API"):
                    conn = sqlite3.connect('exam_db.sqlite')
                    conn.execute("INSERT OR REPLACE INTO system_settings VALUES ('GEMINI_API_KEY', ?)", (new_key.strip(),))
                    conn.commit(); conn.close(); st.success("✅ Đã lưu!")
            st.markdown("---")
            menu = ["✍️ Vào phòng thi", "🤖 AI Sinh đề", "📊 Bảng điểm", "📤 Phát đề/Giao bài", "🔐 Cá nhân"]
            if role == "core_admin": menu = ["🛡️ Quản trị tối cao"] + menu
            elif role == "sub_admin": menu = ["👥 Quản lý khu vực"] + menu
            choice = st.radio("Menu chính", menu)
            if st.button("🚪 Thoát", use_container_width=True): st.session_state.clear(); st.rerun()

        conn = sqlite3.connect('exam_db.sqlite')
        c_stu = [r[0].strip() for r in conn.execute("SELECT DISTINCT class_name FROM users WHERE role='student' AND class_name != ''").fetchall()]
        c_man = []
        for r in conn.execute("SELECT managed_classes FROM users WHERE role='sub_admin'").fetchall():
            if r[0]: c_man.extend([x.strip() for x in r[0].split(',') if x.strip()])
        all_cl = sorted(list(set(c_stu + c_man)))
        conn.close()

        if choice == "🛡️ Quản trị tối cao":
            st.header("🛡️ Quản trị tối cao (Admin Lõi)")
            t1, t2, t3, t4 = st.tabs(["👥 Admin thành viên", "🎓 Giám sát Học sinh", "📥 Nhập dữ liệu HS", "🚨 Xóa lớp học"])
            with t1:
                with st.form("add_sa"):
                    u_s, p_s, n_s, m_s = st.text_input("User"), st.text_input("Pass"), st.text_input("Tên"), st.text_input("Lớp (VD: 9A, 9E)")
                    if st.form_submit_button("Cấp quyền"):
                        conn = sqlite3.connect('exam_db.sqlite')
                        try:
                            conn.execute("INSERT INTO users (username, password, role, fullname, managed_classes) VALUES (?,?,'sub_admin',?,?)", (u_s, p_s, n_s, m_s))
                            conn.commit(); st.success("Xong!"); st.rerun()
                        except: st.error("Đã có User!")
                        conn.close()
                account_manager_ui("sub_admin")
            with t2:
                sel = st.selectbox("Lớp:", ["Tất cả"] + all_cl)
                account_manager_ui("student", specific_class=sel if sel != "Tất cả" else None)
            with t3: import_student_module()
            with t4: delete_class_module(all_cl)

        elif choice == "👥 Quản lý khu vực":
            st.header("👥 Quản lý khu vực (Admin Thành viên)")
            my_cl = [x.strip() for x in st.session_state.managed.split(',')] if st.session_state.managed else []
            t1, t2 = st.tabs(["🎓 Danh sách học sinh", "📥 Nhập dữ liệu HS"])
            with t1:
                sel = st.selectbox("Chọn lớp:", ["Tất cả"] + my_cl)
                account_manager_ui("student", specific_class=sel if sel != "Tất cả" else (",".join(my_cl) if my_cl else "NONE"))
            with t2: import_student_module()

if __name__ == "__main__":
    main()
