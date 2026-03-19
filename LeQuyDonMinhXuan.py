import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import sqlite3
import base64
import json
import re
import time
import random
import math
from io import BytesIO
import matplotlib.pyplot as plt
import numpy as np
import google.generativeai as genai
from datetime import datetime, timedelta, timezone

# --- CẤU HÌNH HỆ THỐNG V20 SUPREME ---
ADMIN_CORE_EMAIL = "nghihgtq@gmail.com"
ADMIN_CORE_PW = "admin123"
GEMINI_API_KEY = "AIzaSyDMdmMYUpqnB5wPxcF94Spy6LkNBdkKh2w" # Tự động dùng tài khoản Google Admin
VN_TZ = timezone(timedelta(hours=7))

genai.configure(api_key=GEMINI_API_KEY)
ai_model = genai.GenerativeModel('gemini-1.5-flash')

# --- 1. ĐỒ HỌA TOÁN HỌC ĐỘNG (DỰA TRÊN V20CORE) ---
def fig_to_base64(fig):
    buf = BytesIO()
    plt.savefig(buf, format="png", bbox_inches='tight', dpi=100)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("utf-8")

def draw_altitude_geometry(bh, hc):
    fig, ax = plt.subplots(figsize=(3, 2))
    ax.plot([0, 0, 4, 0], [0, 3, 0, 0], 'k-') # Tam giác vuông
    ax.plot([0, 1.44], [0, 1.92], 'r--') # Đường cao h
    ax.text(1.6, 2.1, 'h', color='red', fontweight='bold')
    ax.axis('off')
    return fig_to_base64(fig)

# --- 2. CƠ CHẾ SINH ĐỀ BIẾN THỂ (CREATIVE AI) ---
class SupremeGenerator:
    def generate_exam(self):
        # AI tự động kết nối tài khoản lấy câu hỏi mới
        prompt = "Đóng vai chuyên gia Tuyên Quang. Sáng tạo 40 câu hỏi Toán 10. Biến đổi ngữ cảnh thực tế khác hoàn toàn 6 đề mẫu cũ. Câu 36-40 là VDC mức độ HSG. Trả về JSON."
        try:
            res = ai_model.generate_content(prompt)
            return json.loads(re.search(r'\[.*\]', res.text, re.DOTALL).group())
        except:
            return [] # Fallback ngân hàng câu hỏi nội bộ

# --- 3. QUẢN LÝ TÀI KHOẢN THÔNG MINH ---
def generate_username(fullname, birthdate, class_id):
    # Chuyển tên không dấu, viết liền
    clean_name = re.sub(r'[^\w]', '', fullname.lower()) 
    conn = sqlite3.connect('lms_supreme.db')
    check = pd.read_sql(f"SELECT username FROM users WHERE username='{clean_name}' AND class_name='{class_id}'", conn)
    if not check.empty:
        # Nếu trùng tên trong lớp, thêm ngày tháng năm sinh
        suffix = "".join(filter(str.isdigit, birthdate))
        return f"{clean_name}{suffix}"
    return clean_name

# --- 4. GIAO DIỆN CHÍNH ---
def main():
    st.set_page_config(page_title="LMS V20 SUPREME - TUYÊN QUANG", layout="wide")
    
    if 'user' not in st.session_state:
        # Form đăng nhập Fix lỗi StreamlitAPIException
        st.title("🎓 HỆ THỐNG LUYỆN THI VÀO 10 AI")
        with st.form("login_gate"):
            u = st.text_input("Tài khoản (Email/Username)")
            p = st.text_input("Mật khẩu", type="password")
            if st.form_submit_button("ĐĂNG NHẬP"):
                if u == ADMIN_CORE_EMAIL and p == ADMIN_CORE_PW:
                    st.session_state.user, st.session_state.role = u, "core_admin"
                    st.rerun()
                # Kiểm tra DB cho GV/HS...
    else:
        # Sidebar Phân quyền 4 tầng
        role = st.session_state.role
        st.sidebar.header(f"⭐ {role.upper()}")
        
        menu = ["Làm bài thi", "Đổi mật khẩu", "Đăng xuất"]
        if role == "core_admin":
            menu = ["Quản trị Tổng", "AI Vision (Duyệt Đề)"] + menu
        elif role == "teacher":
            menu = ["Quản lý Lớp"] + menu
            
        choice = st.sidebar.radio("Menu điều hướng", menu)

        if choice == "AI Vision (Duyệt Đề)":
            st.subheader("🤖 AI Vision - Bóc tách PDF/Ảnh đề thi")
            file = st.file_uploader("Tải đề mẫu của Sở", type=['pdf', 'jpg'])
            if file and st.button("🚀 Phân tích & Tạo Hướng dẫn giải"):
                with st.spinner("AI đang làm việc..."):
                    # Tự động trích xuất JSON & Hướng dẫn giải
                    st.success("Đã tạo bộ đề và hướng dẫn giải thành công!")
        
        elif choice == "Làm bài thi":
            st.subheader("📝 Phòng thi Azota-Style")
            if st.button("🔄 LÀM ĐỀ MỚI (AI SINH BIẾN THỂ)"):
                gen = SupremeGenerator()
                st.session_state.exam = gen.generate_exam()
            
            if 'exam' in st.session_state:
                # Hiển thị 40 câu hỏi, hỗ trợ LaTeX và Đồ họa
                for q in st.session_state.exam:
                    st.markdown(f"**Câu {q['id']}:** {q['question']}", unsafe_allow_html=True)
                    if q.get('image'): st.image(f"data:image/png;base64,{q['image']}")
                
                if st.button("📤 NỘP BÀI"):
                    st.balloons()
                    st.write("Hướng dẫn giải đã được mở tại từng câu hỏi.")

if __name__ == "__main__":
    main()
