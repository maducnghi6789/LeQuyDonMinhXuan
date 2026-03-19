import matplotlib
matplotlib.use('Agg')
import streamlit as st
import pandas as pd
import sqlite3
import json
import time
import unicodedata
import random
import re
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
# 1. TIỆN ÍCH XỬ LÝ DỮ LIỆU & TOÁN HỌC
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
    res = json_str.strip()
    for marker in ["```json", "```"]:
        if res.startswith(marker): res = res[len(marker):]
        if res.endswith("
http://googleusercontent.com/immersive_entry_chip/0

**Những điểm cải tiến sống còn:**
* **`safe_ai_generate` cho giáo viên:** Tab giao đề của giáo viên giờ đây dùng chung thuật toán thông minh nhất, tự nhảy sang mô hình dự phòng nếu mô hình chính bị 404.
* **`format_math` toàn diện:** Tôi đã dán bộ lọc này vào mọi ngóc ngách: từ đề bài, radio chọn đáp án đến phần giải chi tiết. Hình ảnh `\sqrt[3]{8}` của bạn sẽ biến thành biểu thức toán học đẹp đẽ.
* **Hybrid Logic:** AI được "nhắc nhở" về 20 câu APP đã lấy để tránh trùng lặp, tạo nên đề thi 40 câu phong phú và chuẩn ma trận.

Bạn hãy thử cập nhật ngay, chúng ta sẽ kết thúc chuỗi lỗi 404 tại đây!
