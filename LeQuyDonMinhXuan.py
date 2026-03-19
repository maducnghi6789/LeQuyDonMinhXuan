import matplotlib
matplotlib.use('Agg')
import streamlit as st
import pandas as pd
import sqlite3
import json
import time
import unicodedata
import random
from io import BytesIO
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta, timezone
import fitz  # PyMuPDF
import google.generativeai as genai

# --- CẤU HÌNH HỆ THỐNG ---
ADMIN_CORE_EMAIL = "nghihgtq@gmail.com"
ADMIN_CORE_PW = "GiámĐốc2026"
VN_TZ = timezone(timedelta(hours=7))

# ==========================================
# 1. TIỆN ÍCH XỬ LÝ USERNAME & CHUỖI AI
# ==========================================
def remove_accents(input_str):
    if not input_str: return ""
    nfkd_form = unicodedata.normalize('NFKD', str(input_str))
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).replace(" ", "").lower()

def gen_smart_username(fullname, existing_usernames):
    base_name = remove_accents(fullname)
    base_user = f"lqd_{base_name}"
    if base_user not in existing_usernames: return base_user
    counter = 1
    while True:
        new_user = f"{base_user}{counter}"
        if new_user not in existing_usernames: return new_user
        counter += 1

def clean_ai_json(json_str):
    """Dọn dẹp chuỗi JSON an toàn chống lỗi Cú pháp và lỗi hiển thị UI"""
    res = json_str.strip()
    md_json = "`" * 3 + "json"
    md_code = "`" * 3
    if res.startswith(md_json): res = res[7:]
    if res.startswith(md_code): res = res[3:]
    if res.endswith(md_code): res = res[:-3]
    return res.strip()

def get_api_key():
    conn = sqlite3.connect('exam_db.sqlite')
    res = conn.execute("SELECT setting_value FROM system_settings WHERE setting_key='GEMINI_API_KEY'").fetchone()
    conn.close()
    return res[0] if res else ""

# ==========================================
# 2. HỆ QUẢN TRỊ CƠ SỞ DỮ LIỆU
# ==========================================
def init_db():
    conn = sqlite3.connect('exam_db.sqlite')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY)''')
    
    user_cols = [("password", "TEXT"), ("role", "TEXT"), ("fullname", "TEXT"), ("dob", "TEXT"), ("class_name", "TEXT"), ("school", "TEXT"), ("managed_classes", "TEXT")]
    c.execute("PRAGMA table_info(users)")
    existing_u_cols = [row[1] for row in c.fetchall()]
    for col_name, col_type in user_cols:
        if col_name not in existing_u_cols:
            try: c.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
            except: pass
            
    c.execute('''CREATE TABLE IF NOT EXISTS system_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT)''')
    
    # BẢNG ĐỀ THI VÀ ĐIỂM SỐ
    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_exams (id INTEGER PRIMARY KEY AUTOINCREMENT)''')
    exam_cols = [("title", "TEXT"), ("questions_json", "TEXT"), ("time_limit", "INTEGER"), ("target_class", "TEXT"), ("created_by", "TEXT"), ("timestamp", "DATETIME DEFAULT CURRENT_TIMESTAMP")]
    c.execute("PRAGMA table_info(mandatory_exams)")
    existing_e_cols = [row[1] for row in c.fetchall()]
    for col_name, col_type in exam_cols:
        if col_name not in existing_e_cols:
            try: c.execute(f"ALTER TABLE mandatory_exams ADD COLUMN {col_name} {col_type}")
            except: pass

    c.execute('''CREATE TABLE IF NOT EXISTS mandatory_results (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, exam_id INTEGER, score REAL, user_answers_json TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute("INSERT OR IGNORE INTO users (username, password, role, fullname) VALUES (?, ?, 'core_admin', 'Giám Đốc Hệ Thống')", (ADMIN_CORE_EMAIL, ADMIN_CORE_PW))
    conn.commit(); conn.close()

def log_deletion(deleted_by, entity_type, entity_name, reason):
    try:
        conn = sqlite3.connect('exam_db.sqlite')
        vn_time = datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M:%S")
        try: conn.execute("INSERT INTO deletion_logs (deleted_by, entity_type, entity_name, reason, timestamp) VALUES (?, ?, ?, ?, ?)", (deleted_by, entity_type, entity_name, reason, vn_time))
        except:
            conn.execute("DROP TABLE IF EXISTS deletion_logs")
            conn.execute('''CREATE TABLE deletion_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, deleted_by TEXT, entity_type TEXT, entity_name TEXT, reason TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
            conn.execute("INSERT INTO deletion_logs (deleted_by, entity_type, entity_name, reason, timestamp) VALUES (?, ?, ?, ?, ?)", (deleted_by, entity_type, entity_name, reason, vn_time))
        conn.commit(); conn.close()
    except: pass

# ==========================================
# 3. QUẢN LÝ NHÂN SỰ & HỌC SINH (MK MẶC ĐỊNH 123@)
# ==========================================
def account_manager_ui(target_role, specific_class=None):
    st.markdown(f"#### 🛠️ Quản lý {target_role}")
    conn = sqlite3.connect('exam_db.sqlite')
    query = f"SELECT * FROM users WHERE role='{target_role}'"
    if specific_class and specific_class != "Tất cả các lớp": query += f" AND class_name='{specific_class}'"
    df = pd.read_sql_query(query, conn)
    if not df.empty:
        cols = ['username', 'fullname', 'password', 'class_name']
        if 'school' in df.columns: cols.append('school')
        if 'managed_classes' in df.columns and target_role == 'sub_admin': cols.append('managed_classes')
        st.dataframe(df[cols], use_container_width=True)
        sel_u = st.selectbox(f"Chọn {target_role}:", ["-- Chọn --"] + df['username'].tolist())
        if sel_u != "-- Chọn --":
            u_data = df[df['username'] == sel_u].iloc[0]
            with st.form(f"form_{sel_u}"):
                c1, c2 = st.columns(2)
                f_name = c1.text_input("Họ và Tên", value=u_data['fullname'])
                f_pass = c2.text_input("🔑 Mật khẩu", value=u_data['password'])
                f_cls = c1.text_input("Lớp", value=u_data['class_name'] if u_data['class_name'] else "")
                f_sch = c2.text_input("Trường", value=u_data.get('school', '') if pd.notna(u_data.get('school')) else "")
                f_man = st.text_input("Quyền quản lý", value=u_data.get('managed_classes', '') if pd.notna(u_data.get('managed_classes')) else "") if target_role == 'sub_admin' else ""
                b_up, b_reset, b_del = st.columns(3)
                if b_up.form_submit_button("💾 CẬP NHẬT"):
                    if target_role == 'sub_admin': conn.execute("UPDATE users SET fullname=?, password=?, class_name=?, school=?, managed_classes=? WHERE username=?", (f_name, f_pass, f_cls, f_sch, f_man, sel_u))
                    else: conn.execute("UPDATE users SET fullname=?, password=?, class_name=?, school=? WHERE username=?", (f_name, f_pass, f_cls, f_sch, sel_u))
                    conn.commit(); st.success("✅ Cập nhật xong!"); time.sleep(0.5); st.rerun()
                if b_reset.form_submit_button("🔄 RESET VỀ 123@"):
                    conn.execute("UPDATE users SET password=? WHERE username=?", ("123@", sel_u))
                    conn.commit(); st.success(f"✅ Đã reset {sel_u} về 123@"); time.sleep(1); st.rerun()
                if b_del.form_submit_button("🗑️ XÓA TÀI KHOẢN"):
                    log_deletion(st.session_state.current_user, "Tài khoản", sel_u, "Xóa thủ công")
                    conn.execute("DELETE FROM users WHERE username=?", (sel_u,)); conn.execute("DELETE FROM mandatory_results WHERE username=?", (sel_u,))
                    conn.commit(); st.warning(f"💥 Đã xóa {sel_u}"); time.sleep(0.5); st.rerun()
    else: st.info("Chưa có dữ liệu.")
    conn.close()

def import_student_module():
    st.markdown("### 📥 Nhập dữ liệu (Mật khẩu mặc định: 123@)")
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
            col_mapping = {}
            for col in df.columns:
                norm = remove_accents(str(col)).replace(" ", "").lower()
                if "hovaten" in norm or "hoten" in norm: col_mapping[col] = "Họ và tên"
                elif "lop" in norm: col_mapping[col] = "Lớp"
            df = df.rename(columns=col_mapping)
            if "Họ và tên" not in df.columns or "Lớp" not in df.columns: st.error("❌ Thiếu cột Họ tên/Lớp.")
            else:
                conn = sqlite3.connect('exam_db.sqlite')
                existing = set([r[0] for r in conn.execute("SELECT username FROM users").fetchall()])
                s, f, errs = 0, 0, []
                for idx, r in df.iterrows():
                    name, cls = str(r.get('Họ và tên', '')).strip(), str(r.get('Lớp', '')).strip()
                    if name and name.lower() != 'nan' and cls and cls.lower() != 'nan':
                        uname = gen_smart_username(name, existing); existing.add(uname)
                        try:
                            conn.execute("INSERT INTO users (username, password, role, fullname, class_name) VALUES (?,?,?,?,?)", (uname, "123@", "student", name, cls))
                            s += 1
                        except Exception as e: f += 1; errs.append(f"- Dòng {idx+2}: Lỗi DB")
                    else: f += 1; errs.append(f"- Dòng {idx+2}: Thiếu dữ liệu")
                conn.commit(); conn.close()
                st.success(f"✅ Tạo thành công: {s} | ❌ Lỗi: {f}")
    with t2:
        with st.form("manual_add"):
            n, c = st.text_input("Họ và tên"), st.text_input("Lớp")
            if st.form_submit_button("Tạo tài khoản"):
                if n and c:
                    conn = sqlite3.connect('exam_db.sqlite'); existing = set([r[0] for r in conn.execute("SELECT username FROM users").fetchall()])
                    u = gen_smart_username(n, existing)
                    conn.execute("INSERT INTO users (username, password, role, fullname, class_name) VALUES (?,?,?,?,?)", (u, "123@", "student", n, c))
                    conn.commit(); st.success(f"Đã tạo: {u} (MK: 123@)"); conn.close()

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
# 4. MODULE AI KHẢO THÍ (GIAO ĐỀ & TẠO ĐỀ)
# ==========================================
def extract_text_from_pdf(pdf_file):
    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
    text = ""
    for page in doc: text += page.get_text("text") + "\n"
    return text

def parse_exam_with_ai(raw_text, api_key):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-pro')
    prompt = f"""Bạn là một giáo viên chuyên Toán cấp 2. Nhiệm vụ của bạn là đọc văn bản trích xuất từ đề thi PDF dưới đây, biên tập lại thành chuẩn đúng 40 câu hỏi trắc nghiệm, tạo hướng dẫn giải ngắn gọn.
    YÊU CẦU BẮT BUỘC:
    1. Trả về DUY NHẤT mảng JSON array. Định dạng: [{{"q": "Nội dung câu hỏi", "options": ["A. ...", "B. ...", "C. ...", "D. ..."], "ans": "A", "exp": "Hướng dẫn giải..."}}]
    2. Công thức toán học PHẢI dùng chuẩn LaTeX (dùng $ cho inline và $$ cho block).
    3. Đảm bảo parse đủ số lượng câu hỏi có trong văn bản.

    VĂN BẢN ĐỀ THI:
    {raw_text}
    """
    try:
        response = model.generate_content(prompt)
        json_str = clean_ai_json(response.text)
        return json.loads(json_str)
    except Exception: return None

def generate_free_practice_ai(api_key):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-pro')
    prompt = """Bạn là chuyên gia bồi dưỡng học sinh giỏi Toán lớp 9. Hãy tự động sáng tác một đề kiểm tra trắc nghiệm gồm 40 câu hỏi mức độ Vận dụng và Vận dụng cao.
    YÊU CẦU ĐỀ BÀI:
    - Nội dung: Đại số (Hệ phương trình, Bất đẳng thức, Rút gọn biểu thức), Hình học (Đường tròn, Chứng minh), Số học (Chia hết, Phương trình nghiệm nguyên).
    - Ngữ cảnh: Có bài toán thực tế sinh động, số liệu mới mẻ, không lặp lại.
    - YÊU CẦU BẮT BUỘC VỀ ĐỊNH DẠNG:
      1. Trả về DUY NHẤT mảng JSON. Định dạng: [{"q": "Câu hỏi", "options": ["A. ", "B. ", "C. ", "D. "], "ans": "A", "exp": "Cách giải chi tiết ngắn gọn..."}]
      2. Toàn bộ công thức TOÁN học PHẢI được bọc trong $ (inline) hoặc $$ (block) chuẩn LaTeX.
    """
    try:
        response = model.generate_content(prompt)
        json_str = clean_ai_json(response.text)
        return json.loads(json_str)
    except Exception: return None

# ==========================================
# 5. GIAO DIỆN HỌC SINH (LÀM BÀI THI CÓ ĐẾM NGƯỢC)
# ==========================================
def take_exam_ui(exam_data, exam_id, is_mandatory=True):
    st.markdown(f"### 📝 {exam_data.get('title', 'Luyện đề tự do')}")
    time_limit = exam_data.get('time_limit', 90)
    questions = exam_data['questions']
    
    if 'student_answers' not in st.session_state or st.session_state.get('current_exam_id') != exam_id:
        st.session_state.student_answers = {}
        st.session_state.current_exam_id = exam_id
        st.session_state.show_results = False

    if not st.session_state.get('show_results'):
        timer_html = f"""
        <div style="position: fixed; top: 60px; right: 20px; background-color: #ff4b4b; color: white; padding: 10px 15px; border-radius: 8px; font-weight: bold; font-size: 16px; z-index: 9999; box-shadow: 2px 2px 10px rgba(0,0,0,0.5);">
            ⏳ CÒN LẠI: <span id="timer">{time_limit}:00</span>
        </div>
        <script>
            var limit = {time_limit} * 60 * 1000;
            var start = new Date().getTime();
            var x = setInterval(function() {{
                var now = new Date().getTime();
                var distance = limit - (now - start);
                var m = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
                var s = Math.floor((distance % (1000 * 60)) / 1000);
                document.getElementById("timer").innerHTML = m + "p " + s + "s ";
                if (distance < 0) {{
                    clearInterval(x);
                    document.getElementById("timer").innerHTML = "HẾT GIỜ!";
                    var btns = window.parent.document.querySelectorAll('button');
                    btns.forEach(b => {{ if(b.innerText.includes('NỘP BÀI')) b.click(); }});
                }}
            }}, 1000);
        </script>
        """
        st.components.v1.html(timer_html, height=0)

        with st.form(f"exam_form_{exam_id}"):
            for i, q in enumerate(questions):
                st.markdown(f"**Câu {i+1}:** {q['q']}")
                st.session_state.student_answers[i] = st.radio("Chọn đáp án:", q['options'], index=None, key=f"q_{i}")
                st.divider()
            
            if st.form_submit_button("✅ NỘP BÀI / KẾT THÚC"):
                correct = 0
                for i, q in enumerate(questions):
                    correct_char = q['ans'].strip()[0].upper()
                    usr_choice = st.session_state.student_answers.get(i)
                    if usr_choice and str(usr_choice).strip().upper().startswith(correct_char):
                        correct += 1
                
                score = round((correct / len(questions)) * 10, 2)
                
                if is_mandatory:
                    conn = sqlite3.connect('exam_db.sqlite')
                    ans_json = json.dumps(st.session_state.student_answers)
                    conn.execute("INSERT INTO mandatory_results (username, exam_id, score, user_answers_json) VALUES (?,?,?,?)", (st.session_state.current_user, exam_id, score, ans_json))
                    conn.commit(); conn.close()
                    
                st.session_state.score = score
                st.session_state.show_results = True
                st.rerun()
                
    else:
        st.success(f"🎉 HOÀN THÀNH! ĐIỂM CỦA BẠN: **{st.session_state.score} / 10**")
        st.markdown("### 🔍 XEM HƯỚNG DẪN GIẢI")
        for i, q in enumerate(questions):
            with st.expander(f"Câu {i+1} - Đáp án đúng: {q['ans']}"):
                st.markdown(f"**Đề:** {q['q']}")
                st.markdown(f"*Bạn chọn:* {st.session_state.student_answers.get(i, 'Không chọn')}")
                st.info(f"**Hướng dẫn (AI):**\n{q['exp']}")
        if st.button("⬅️ Trở về danh sách đề"):
            st.session_state.show_results = False
            st.session_state.current_exam_id = None
            st.session_state.taking_free_exam = None
            st.session_state.taking_exam = None
            st.rerun()

# ==========================================
# 6. GIAO DIỆN ĐIỀU HƯỚNG CHÍNH ĐỒNG BỘ
# ==========================================
def main():
    st.set_page_config(page_title="LMS Lê Quý Đôn V200", layout="wide")
    init_db()
    
    if 'current_user' not in st.session_state:
        st.markdown("<h2 style='text-align: center;'>🎓 HỆ THỐNG LMS LÊ QUÝ ĐÔN V200</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.2, 1])
        with col2:
            with st.form("login"):
                u = st.text_input("Tài khoản").strip(); p = st.text_input("Mật khẩu", type="password").strip()
                if st.form_submit_button("🚀 ĐĂNG NHẬP"):
                    conn = sqlite3.connect('exam_db.sqlite')
                    res = conn.execute("SELECT role, fullname, class_name, managed_classes FROM users WHERE username=? AND password=?", (u, p)).fetchone()
                    conn.close()
                    if res:
                        st.session_state.current_user = u
                        st.session_state.role, st.session_state.fullname, st.session_state.class_name, st.session_state.managed = res
                        st.rerun()
                    else: st.error("❌ Sai thông tin đăng nhập!")
    else:
        role = st.session_state.role
        with st.sidebar:
            st.markdown(f"### 👤 {st.session_state.fullname}")
            st.success(f"CẤP ĐỘ: {role.upper()}")
            
            api_key = get_api_key()
            if role == "core_admin":
                st.markdown("---")
                st.subheader("🔑 Cấu hình AI (Gemini)")
                new_key = st.text_input("Gemini API Key:", value=api_key, type="password")
                if st.button("💾 Lưu API"):
                    conn = sqlite3.connect('exam_db.sqlite')
                    conn.execute("INSERT OR REPLACE INTO system_settings VALUES ('GEMINI_API_KEY', ?)", (new_key.strip(),))
                    conn.commit(); conn.close(); st.success("✅ Đã lưu!")
            st.markdown("---")
            
            # --- MENU CHÍNH ---
            if role in ["core_admin", "sub_admin"]:
                menu = ["📤 Giao đề thi thử", "📊 Thống kê", "🔐 Cá nhân"]
                if role == "core_admin": menu = ["🛡️ Quản trị tối cao"] + menu
                elif role == "sub_admin": menu = ["👥 Quản lý khu vực"] + menu
            elif role == "student":
                menu = ["✍️ Kiểm tra bắt buộc", "🚀 Luyện đề tự do", "📊 Điểm số cá nhân", "🔐 Cá nhân"]
                
            choice = st.radio("Menu chính", menu)
            if st.button("🚪 Thoát", use_container_width=True): st.session_state.clear(); st.rerun()

        # ĐỒNG BỘ DANH SÁCH LỚP
        if role in ["core_admin", "sub_admin"]:
            conn = sqlite3.connect('exam_db.sqlite')
            c_stu = [r[0].strip() for r in conn.execute("SELECT DISTINCT class_name FROM users WHERE role='student' AND class_name != ''").fetchall()]
            c_man = []
            for r in conn.execute("SELECT managed_classes FROM users WHERE role='sub_admin'").fetchall():
                if r[0]: c_man.extend([x.strip() for x in r[0].split(',') if x.strip()])
            all_cl = sorted(list(set(c_stu + c_man)))
            conn.close()

        # ================= ROUTING =================
        if choice == "🛡️ Quản trị tối cao":
            st.header("🛡️ Quản trị tối cao (Admin Lõi)")
            t1, t2, t3, t4 = st.tabs(["👥 Admin thành viên", "🎓 Quản lý Học sinh", "📥 Nhập dữ liệu HS", "🚨 Xóa lớp học"])
            with t1:
                with st.form("add_sa"):
                    u_s, p_s, n_s, m_s = st.text_input("User"), st.text_input("Pass"), st.text_input("Tên"), st.text_input("Lớp (VD: 9A, 9E)")
                    if st.form_submit_button("Cấp quyền"):
                        conn = sqlite3.connect('exam_db.sqlite')
                        try:
                            conn.execute("INSERT INTO users (username, password, role, fullname, managed_classes) VALUES (?,?,'sub_admin',?,?)", (u_s, p_s, n_s, m_s))
                            conn.commit(); st.success("Xong!"); st.rerun()
                        except: st.error("Đã có User này!")
                        conn.close()
                account_manager_ui("sub_admin")
            with t2:
                sel = st.selectbox("Lớp:", ["Tất cả"] + all_cl)
                account_manager_ui("student", specific_class=sel if sel != "Tất cả" else None)
            with t3: import_student_module()
            with t4: delete_class_module(all_cl)

        elif choice == "👥 Quản lý khu vực":
            st.header("👥 Quản lý khu vực")
            conn = sqlite3.connect('exam_db.sqlite')
            st.session_state.managed = conn.execute("SELECT managed_classes FROM users WHERE username=?", (st.session_state.current_user,)).fetchone()[0]
            conn.close()
            my_cl = [x.strip() for x in st.session_state.managed.split(',')] if st.session_state.managed else []
            t1, t2 = st.tabs(["🎓 Danh sách học sinh", "📥 Nhập dữ liệu HS"])
            with t1:
                sel = st.selectbox("Chọn lớp:", ["Tất cả"] + my_cl)
                account_manager_ui("student", specific_class=sel if sel != "Tất cả" else (",".join(my_cl) if my_cl else "NONE"))
            with t2: import_student_module()

        elif choice == "📤 Giao đề thi thử":
            st.header("📤 Giao đề thi thử (Bằng File PDF)")
            st.info("💡 Tải file PDF chứa đề trắc nghiệm. AI sẽ tự động đọc, tạo hướng dẫn giải và ép chuẩn công thức Toán (LaTeX).")
            if not api_key: st.error("❌ Hệ thống chưa cấu hình Gemini API Key.")
            else:
                target_classes = ["Tất cả các lớp"] + all_cl if role == "core_admin" else [x.strip() for x in st.session_state.managed.split(',')]
                with st.form("upload_pdf"):
                    e_title = st.text_input("Tên bài kiểm tra:")
                    e_class = st.selectbox("Giao bài cho lớp:", target_classes)
                    e_time = st.number_input("Thời gian (Phút):", min_value=15, value=90, step=5)
                    e_file = st.file_uploader("Tải Đề thi (PDF)", type="pdf")
                    
                    if st.form_submit_button("🚀 BIÊN TẬP & GIAO ĐỀ BẰNG AI"):
                        if e_title and e_file:
                            with st.spinner("🤖 AI đang giải đề và phân tích PDF... (Có thể mất 1-2 phút)"):
                                raw_txt = extract_text_from_pdf(e_file)
                                exam_json = parse_exam_with_ai(raw_txt, api_key)
                                if exam_json:
                                    conn = sqlite3.connect('exam_db.sqlite')
                                    conn.execute("INSERT INTO mandatory_exams (title, questions_json, time_limit, target_class, created_by) VALUES (?,?,?,?,?)",
                                                 (e_title, json.dumps(exam_json), e_time, e_class, st.session_state.current_user))
                                    conn.commit(); conn.close()
                                    st.success(f"✅ Đã giao {len(exam_json)} câu hỏi cho lớp {e_class}!")
                                else: st.error("❌ AI không thể xử lý File PDF này. Hãy đảm bảo File chứa văn bản rõ ràng.")
                        else: st.warning("Vui lòng điền Tên bài và tải File!")

        # ================= MODULE MỚI: THỐNG KÊ (THAY CHO BẢNG ĐIỂM) =================
        elif choice == "📊 Thống kê":
            st.header("📊 Thống kê & Phân tích Đề thi")
            conn = sqlite3.connect('exam_db.sqlite')
            
            if role == "core_admin":
                exams = conn.execute("SELECT id, title, target_class, questions_json FROM mandatory_exams").fetchall()
            else:
                classes_str = "', '".join([x.strip() for x in st.session_state.managed.split(',')])
                exams = conn.execute(f"SELECT id, title, target_class, questions_json FROM mandatory_exams WHERE target_class IN ('{classes_str}') OR target_class='Tất cả các lớp'").fetchall()
                
            if not exams:
                st.info("Chưa có bài thi nào được giao.")
            else:
                exam_dict = {f"[{e[2]}] {e[1]}": e for e in exams}
                sel_exam_name = st.selectbox("📌 Chọn đề thi để xem thống kê:", ["-- Chọn đề thi --"] + list(exam_dict.keys()))
                
                if sel_exam_name != "-- Chọn đề thi --":
                    exam_id, exam_title, target_class, q_json_str = exam_dict[sel_exam_name]
                    questions = json.loads(q_json_str)
                    num_questions = len(questions)
                    
                    tb1, tb2, tb3 = st.tabs(["📋 Điểm số", "⚠️ Trốn thi", "📉 Phân tích câu hỏi"])
                    
                    res_df = pd.read_sql_query("SELECT u.fullname AS 'Họ tên', u.username, u.class_name AS 'Lớp', r.score AS 'Điểm', r.user_answers_json FROM mandatory_results r JOIN users u ON r.username = u.username WHERE r.exam_id = ?", conn, params=(exam_id,))
                    
                    with tb1:
                        if res_df.empty: st.info("Chưa có học sinh nào nộp bài.")
                        else: st.dataframe(res_df[['Họ tên', 'Lớp', 'Điểm']], use_container_width=True)
                    
                    with tb2:
                        if target_class == "Tất cả các lớp":
                            if role == "core_admin":
                                all_st = pd.read_sql_query("SELECT fullname, username, class_name FROM users WHERE role='student'", conn)
                            else:
                                classes_str = "', '".join([x.strip() for x in st.session_state.managed.split(',')])
                                all_st = pd.read_sql_query(f"SELECT fullname, username, class_name FROM users WHERE role='student' AND class_name IN ('{classes_str}')", conn)
                        else:
                            all_st = pd.read_sql_query("SELECT fullname, username, class_name FROM users WHERE role='student' AND class_name=?", conn, params=(target_class,))
                            
                        if res_df.empty: missing_df = all_st
                        else:
                            submitted = res_df['username'].tolist()
                            missing_df = all_st[~all_st['username'].isin(submitted)]
                            
                        if missing_df.empty:
                            st.success("🎉 Tuyệt vời! 100% học sinh đã hoàn thành bài thi.")
                        else:
                            st.warning(f"🚨 Có {len(missing_df)} học sinh chưa làm bài:")
                            st.dataframe(missing_df[['fullname', 'class_name', 'username']].rename(columns={'fullname':'Họ tên', 'class_name':'Lớp', 'username':'Tài khoản'}), use_container_width=True)

                    with tb3:
                        if res_df.empty:
                            st.info("Chưa có dữ liệu để phân tích biểu đồ.")
                        else:
                            wrong_counts = {f"Câu {i+1}": 0 for i in range(num_questions)}
                            for idx, row in res_df.iterrows():
                                try:
                                    u_ans = json.loads(row['user_answers_json'])
                                    for i, q in enumerate(questions):
                                        correct_char = q['ans'].strip()[0].upper()
                                        user_choice = u_ans.get(str(i), u_ans.get(i, "")) 
                                        if not user_choice or not str(user_choice).strip().upper().startswith(correct_char):
                                            wrong_counts[f"Câu {i+1}"] += 1
                                except: pass
                                        
                            stat_df = pd.DataFrame(list(wrong_counts.items()), columns=['Câu hỏi', 'Số lượt sai'])
                            st.markdown("**📊 Biểu đồ số lượt chọn SAI theo từng câu:**")
                            st.bar_chart(stat_df.set_index('Câu hỏi'))
                            
                            max_wrong = stat_df['Số lượt sai'].max()
                            min_wrong = stat_df['Số lượt sai'].min()
                            
                            if max_wrong == 0:
                                st.success("🌟 100% học sinh trả lời đúng tất cả các câu!")
                            else:
                                hard_qs = stat_df[stat_df['Số lượt sai'] == max_wrong]['Câu hỏi'].tolist()
                                easy_qs = stat_df[stat_df['Số lượt sai'] == min_wrong]['Câu hỏi'].tolist()
                                st.error(f"🚨 **Câu sai nhiều nhất:** {', '.join(hard_qs)} ({max_wrong} lượt sai). Thầy cô cần tập trung ôn tập lại kiến thức phần này.")
                                st.success(f"🌟 **Câu làm tốt nhất:** {', '.join(easy_qs)} ({min_wrong} lượt sai).")
            conn.close()

        elif choice == "✍️ Kiểm tra bắt buộc":
            st.header("✍️ Kiểm tra bắt buộc")
            conn = sqlite3.connect('exam_db.sqlite')
            exams = conn.execute("SELECT id, title, questions_json, time_limit FROM mandatory_exams WHERE target_class=? OR target_class='Tất cả các lớp'", (st.session_state.class_name,)).fetchall()
            
            if not exams: st.info("🎉 Hiện tại bạn chưa có bài kiểm tra nào!")
            else:
                if st.session_state.get('taking_exam') is None:
                    for e_id, e_title, e_json, e_time in exams:
                        c1, c2 = st.columns([3, 1])
                        c1.write(f"**{e_title}** (Thời gian: {e_time} phút)")
                        done = conn.execute("SELECT score FROM mandatory_results WHERE username=? AND exam_id=?", (st.session_state.current_user, e_id)).fetchone()
                        if done: c2.success(f"Đã nộp: {done[0]} điểm")
                        else:
                            if c2.button("▶️ LÀM BÀI", key=f"btn_{e_id}"):
                                st.session_state.taking_exam = {'id': e_id, 'title': e_title, 'time_limit': e_time, 'questions': json.loads(e_json)}
                                st.rerun()
                else: take_exam_ui(st.session_state.taking_exam, st.session_state.taking_exam['id'], True)
            conn.close()

        elif choice == "🚀 Luyện đề tự do":
            st.header("🚀 Luyện đề tự do (AI Sinh đề)")
            st.info("🤖 AI sẽ mix 40 câu hỏi Vận dụng & Vận dụng cao hoàn toàn mới bám sát đề thi HSG. Thời gian: 90 phút.")
            if st.session_state.get('taking_free_exam') is None:
                if st.button("🪄 BẤM ĐỂ AI TẠO ĐỀ & VÀO THI", type="primary"):
                    if not api_key: st.error("❌ Hệ thống chưa kết nối AI.")
                    else:
                        with st.spinner("🤖 Đang biên soạn 40 câu Toán cực khó... Xin chờ."):
                            free_exam = generate_free_practice_ai(api_key)
                            if free_exam:
                                st.session_state.taking_free_exam = {'title': "Luyện đề Vận Dụng Cao (AI Sinh)", 'time_limit': 90, 'questions': free_exam}
                                st.rerun()
                            else: st.error("❌ Máy chủ AI đang quá tải, vui lòng thử lại sau.")
            else:
                take_exam_ui(st.session_state.taking_free_exam, 9999, False)
                if st.button("❌ Hủy đề này"):
                    st.session_state.taking_free_exam = None
                    st.session_state.show_results = False
                    st.rerun()

        elif choice == "📊 Điểm số cá nhân":
            st.header("📊 Bảng điểm cá nhân")
            conn = sqlite3.connect('exam_db.sqlite')
            res = pd.read_sql_query("SELECT e.title AS 'Tên Bài', r.score AS 'Điểm', r.timestamp AS 'Ngày nộp' FROM mandatory_results r JOIN mandatory_exams e ON r.exam_id = e.id WHERE r.username=?", conn, params=(st.session_state.current_user,))
            st.dataframe(res, use_container_width=True)
            conn.close()
            
        elif choice == "🔐 Cá nhân":
            st.header("🔐 Thông tin cá nhân")
            st.info(f"Xin chào {st.session_state.fullname}! Mọi thông tin của bạn đang được bảo mật an toàn.")

if __name__ == "__main__":
    main()
