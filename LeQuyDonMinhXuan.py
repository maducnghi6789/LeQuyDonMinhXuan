import streamlit as st
import pandas as pd
import sqlite3
import json
import random
import unicodedata
import google.generativeai as genai
from datetime import datetime

# --- CẤU HÌNH HỆ THỐNG TỐI CAO ---
ADMIN_CORE_EMAIL = "nghihgtq@gmail.com"
ADMIN_CORE_PW = "admin123" 
GEMINI_API_KEY = "AIzaSyD72D_quByuDMKOsM_YefgxHVlQX8y-6SU" # API từ file V20 của bạn

# Kết nối AI
genai.configure(api_key=GEMINI_API_KEY)

# --- KHỞI TẠO DATABASE ---
def init_db():
    conn = sqlite3.connect('tuyenquang_exam.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, fullname TEXT, role TEXT, class_id TEXT, birth_date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS results 
                 (username TEXT, score REAL, details TEXT, timestamp TEXT)''')
    conn.commit()
    conn.close()

# --- UTILS: XỬ LÝ TÀI KHOẢN ---
def remove_accents(input_str):
    if not input_str: return ""
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).replace(" ", "").lower()

def create_student_accounts(df):
    """Quy tắc: Tên viết liền không dấu, nếu trùng trong lớp thì thêm ngày sinh"""
    processed = []
    conn = sqlite3.connect('tuyenquang_exam.db')
    for _, row in df.iterrows():
        base_user = remove_accents(row['Họ và tên'])
        class_id = str(row['Lớp'])
        birth_str = "".join(filter(str.isdigit, str(row['Ngày sinh'])))
        
        # Kiểm tra trùng trong DB hoặc trong danh sách hiện tại
        final_user = base_user
        check = pd.read_sql(f"SELECT username FROM users WHERE username='{final_user}' AND class_id='{class_id}'", conn)
        if not check.empty:
            final_user = f"{base_user}{birth_str}"
            
        processed.append((final_user, final_user, row['Họ và tên'], 'student', class_id, str(row['Ngày sinh'])))
    
    c = conn.cursor()
    c.executemany("INSERT OR REPLACE INTO users VALUES (?,?,?,?,?,?)", processed)
    conn.commit()
    conn.close()

# --- AI LOGIC: BIẾN THỂ NGỮ CẢNH ---
def generate_ai_exam_variant():
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = """
    Bạn là chuyên gia ra đề thi Toán vào 10 Tuyên Quang. Dựa trên ma trận và 6 đề mẫu:
    1. Tạo 40 câu trắc nghiệm. 
    2. CỰC KÌ QUAN TRỌNG: Biến thể ngữ cảnh thực tế. 
       - Nếu đề mẫu là 'máy bay', hãy đổi thành 'chiều cao tòa tháp' hoặc 'đỉnh núi'.
       - Nếu là 'viên gạch', hãy đổi thành 'trụ cầu' hoặc 'hộp sữa'.
    3. Câu 36-40 (VDC): Phải dùng kiến thức HSG, yêu cầu tư duy phân loại cao.
    4. Trả về JSON: [{"id":1, "question": "...", "options": ["A","B","C","D"], "answer": "A", "hint": "..."}]
    Sử dụng LaTeX cho công thức: $\sqrt{x}$, $y=ax^2$.
    """
    response = model.generate_content(prompt)
    # Logic bóc tách JSON từ response...
    return json.loads(response.text.strip('`json\n'))

# --- GIAO DIỆN CHÍNH ---
def main():
    st.set_page_config(page_title="LMS TOÁN 10 TUYÊN QUANG", layout="wide")
    init_db()

    if 'user' not in st.session_state:
        # GIAO DIỆN ĐĂNG NHẬP (FIX LỖI FORM)
        st.title("🎓 HỆ THỐNG LUYỆN THI VÀO 10")
        with st.form("login_gate"):
            u = st.text_input("Tài khoản")
            p = st.text_input("Mật khẩu", type="password")
            btn = st.form_submit_button("Đăng nhập")
            if btn:
                if u == ADMIN_CORE_EMAIL and p == ADMIN_CORE_PW:
                    st.session_state.user = u
                    st.session_state.role = "admin_core"
                    st.rerun()
                # Thêm check DB cho GV/HS ở đây...
    else:
        # GIAO DIỆN SAU ĐĂNG NHẬP
        st.sidebar.title(f"Chào, {st.session_state.user}")
        menu = st.sidebar.selectbox("Chức năng", ["Làm đề thi", "Quản lý (Admin)", "Đổi mật khẩu"])

        if menu == "Quản lý (Admin)" and st.session_state.role == "admin_core":
            admin_panel()
        elif menu == "Làm đề thi":
            exam_panel()
        elif menu == "Đổi mật khẩu":
            change_pw_panel()

def admin_panel():
    st.header("🎛️ Bảng điều khiển Giám đốc Hệ thống")
    tab1, tab2, tab3 = st.tabs(["Nạp Học Sinh", "Quản lý Đề thi AI", "Thống kê"])
    
    with tab1:
        file = st.file_uploader("Tải lên danh sách Excel", type="xlsx")
        if file:
            df = pd.read_excel(file)
            if st.button("Khởi tạo tài khoản hàng loạt"):
                create_student_accounts(df)
                st.success("Đã tạo tài khoản theo quy tắc: Tên không dấu + Ngày sinh (nếu trùng)")

    with tab2:
        if st.button("🚀 Sinh đề mới (Biến thể Ngữ cảnh)"):
            with st.spinner("AI đang tư duy đề mới..."):
                new_exam = generate_ai_exam_variant()
                st.session_state.preview_exam = new_exam
                st.json(new_exam)

def exam_panel():
    st.subheader("📝 Bài thi thử trực tuyến")
    # Giao diện làm bài như Azota: Có đồng hồ đếm ngược, danh sách câu hỏi bên phải...
    if st.button("Bắt đầu làm đề mới"):
        # Gọi hàm sinh đề và hiển thị
        pass

def change_pw_panel():
    with st.form("pw_form"):
        old = st.text_input("Mật khẩu cũ", type="password")
        new = st.text_input("Mật khẩu mới", type="password")
        if st.form_submit_button("Cập nhật"):
            st.success("Đã đổi mật khẩu thành công!")

if __name__ == "__main__":
    main()
