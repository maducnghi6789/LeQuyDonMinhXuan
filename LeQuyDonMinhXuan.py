import streamlit as st
import google.generativeai as genai
from PyPDF2 import PdfReader
import io

# --- CẤU HÌNH ADMIN LÕI ---
ADMIN_CORE_EMAIL = "nghihgtq@gmail.com"

# --- CẤU HÌNH AI (GEMINI) ---
# Bạn hãy dán API Key của mình vào đây
genai.configure(api_key="AIzaSy...") 

def extract_text_from_pdf(pdf_file):
    """Bóc tách văn bản từ file PDF đề thi"""
    reader = PdfReader(pdf_file)
    text = ""
    for page in reader.pages:
        text += page.extract_text()
    return text

def ai_process_exam(pdf_text):
    """Dùng AI để phân tích đề thi và tạo đáp án tự động"""
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"""
    Bạn là chuyên gia khảo thí của Sở GD&ĐT Tuyên Quang. 
    Dưới đây là nội dung đề thi vào 10: {pdf_text[:5000]}
    Hãy trích xuất:
    1. Danh sách 40 câu hỏi trắc nghiệm.
    2. Đáp án đúng cho từng câu.
    3. Hướng dẫn giải ngắn gọn cho các câu Vận dụng cao.
    Trả về định dạng JSON chuẩn.
    """
    response = model.generate_content(prompt)
    return response.text

# --- GIAO DIỆN ĐĂNG NHẬP ---
def login_screen():
    st.title("🎓 HỆ THỐNG LUYỆN THI VÀO 10 - TUYÊN QUANG")
    tab1, tab2 = st.tabs(["Học sinh", "Quản trị viên"])
    
    with tab2:
        email = st.text_input("Email Admin", placeholder="nghihgtq@gmail.com")
        password = st.text_input("Mật khẩu", type="password")
        if st.form_submit_button("Đăng nhập Admin"):
            if email == ADMIN_CORE_EMAIL:
                st.session_state.role = "admin_core"
                st.success("Chào mừng Giám đốc hệ thống!")
                st.rerun()

# --- TÍNH NĂNG ADMIN LÕI: TẢI ĐỀ & AI CHẤM ĐIỂM ---
def admin_core_dashboard():
    st.header("🎛️ Bảng điều khiển Admin Lõi")
    uploaded_file = st.file_uploader("Tải lên đề thi PDF của Sở (001, 002...)", type="pdf")
    
    if uploaded_file is not None:
        if st.button("🚀 AI Bóc tách & Tạo phiếu trả lời"):
            with st.spinner("AI đang nghiên cứu đề thi..."):
                raw_text = extract_text_from_pdf(uploaded_file)
                # Gọi AI xử lý nội dung
                exam_data = ai_process_exam(raw_text)
                st.session_state.last_exam = exam_data
                st.success("Đã tạo phiếu trả lời trắc nghiệm tự động!")
                st.json(exam_data) # Hiển thị cấu trúc đề AI vừa bóc tách

# --- CHƯƠNG TRÌNH CHÍNH ---
if 'role' not in st.session_state:
    login_screen()
else:
    if st.session_state.role == "admin_core":
        admin_core_dashboard()
