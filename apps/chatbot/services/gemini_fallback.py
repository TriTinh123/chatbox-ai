# ════════════════════════════════════════════════════════════════════════════
#  gemini_fallback.py — Tích hợp Google Gemini Flash
#  Xử lý toàn bộ chat: hội thoại tự do và phân tích file upload.
# ════════════════════════════════════════════════════════════════════════════

import os
import re
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()   # Đọc GEMINI_API_KEY từ file .env

api_key = os.environ.get("GEMINI_API_KEY", "")
client = genai.Client(api_key=api_key) if api_key else None

class GeminiRateLimitError(Exception):
    """Raised khi Gemini trả về 429 RESOURCE_EXHAUSTED."""
    pass


def _strip_html(text: str) -> str:
    """Xóa HTML tags từ text để dùng làm context hội thoại."""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _call_gemini(prompt: str) -> str:
    """Gọi Gemini. Raise GeminiRateLimitError khi gặp 429 để caller xử lý."""
    if not client:
        raise ValueError("GEMINI_API_KEY chưa được cấu hình")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return response.text
    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            raise GeminiRateLimitError(err)
        raise


def ask_gemini(user_message: str, data_context: dict, conversation_history: list = None) -> str:
    """
    Gửi câu hỏi tới Gemini Flash với native multi-turn conversation.
    Nhớ TOÀN BỘ cuộc hội thoại — không giới hạn số tin nhắn (giống ChatGPT/Gemini).
    conversation_history: list of {'role': 'user'|'assistant', 'text': str}
    """
    if not client:
        raise ValueError("GEMINI_API_KEY chưa được cấu hình")

    # ── Build data context (đưa vào system_instruction để luôn có sẵn) ────
    dominant_vn = {
        "quantity": "số lượng bán giảm",
        "price":    "giá bán giảm",
        "both":     "cả số lượng lẫn giá đều giảm",
    }.get(data_context.get("dominant", "both"), "không xác định")

    data_lines = ""
    if data_context:
        data_lines = (
            f"- Tháng hiện tại: {data_context.get('cur_month', 'N/A')}\n"
            f"- Doanh thu thay đổi: {data_context.get('chg_pct', 0)}% "
            f"so với tháng {data_context.get('prev_month', 'trước')}\n"
            f"- Doanh thu hiện tại: {data_context.get('cur_rev', 'N/A')}\n"
            f"- Doanh thu tháng trước: {data_context.get('prev_rev', 'N/A')}\n"
            f"- Sản phẩm giảm mạnh nhất: {data_context.get('worst_product', 'N/A')} "
            f"({data_context.get('prod_chg', 0)}%)\n"
            f"- Kênh kém nhất: {data_context.get('worst_channel', 'N/A')} "
            f"({data_context.get('ch_chg', 0)}%)\n"
            f"- Nguyên nhân chính: {dominant_vn}\n"
        )
        if "product_breakdown" in data_context:
            data_lines += "\nChi tiết sản phẩm (Top 3 ảnh hưởng lớn nhất):\n"
            for prod in data_context["product_breakdown"][:3]:
                data_lines += f"  + {prod['product']}: {prod['chg_pct']}% (đóng góp {prod['impact_pct']}% vào sụt giảm)\n"
        if "channel_breakdown" in data_context:
            data_lines += "\nChi tiết kênh bán:\n"
            for ch in data_context["channel_breakdown"]:
                data_lines += f"  + {ch['channel']}: {ch['chg_pct']}% (đóng góp {ch['impact_pct']}%)\n"
        if "region_breakdown" in data_context:
            data_lines += "\nChi tiết khu vực:\n"
            for reg in data_context["region_breakdown"]:
                data_lines += f"  + {reg['region']}: {reg['chg_pct']}% (đóng góp {reg['impact_pct']}%)\n"

    data_block = f"\n[DỮ LIỆU THỰC TẾ TỪ sales.csv]\n{data_lines}[HẾT DỮ LIỆU]\n" if data_lines else ""

    # ── System instruction — luôn available trong mọi turn ───────────────
    system_instruction = f"""Bạn là Revenue AI - chuyên gia phân tích doanh thu, trò chuyện tự nhiên như người thật.
{data_block}
NGUYÊN TẮC TRẢ LỜI:
- Luôn nhớ và tham chiếu TOÀN BỘ cuộc hội thoại trong session này (không bị giới hạn số tin)
- Trả lời ĐÚNG và ĐỦ câu hỏi được hỏi — không lạc đề, không lặp lại nội dung đã nói trước đó
- Nếu user hỏi "cái đó", "thêm chi tiết", "tại sao vậy", "cụ thể hơn" → tham chiếu ngữ cảnh trước đó, không giải thích lại từ đầu
- Nếu user đề cập điều đã thảo luận → nhận ra và tiếp tục mạch hội thoại tự nhiên
- Giọng điệu tự nhiên, mạch lạc — như đang nói chuyện trực tiếp với người thật
- Dùng số liệu thực từ dữ liệu để chứng minh luận điểm
- Trả lời bằng tiếng Việt

FORMAT OUTPUT:
- HTML thuần (KHÔNG markdown, KHÔNG ```, KHÔNG **)
- Dùng <br> xuống dòng, <strong> nhấn mạnh, <ul><li> khi cần liệt kê
- Tối đa 2-3 emoji, đặt hợp lý
- 200-400 từ mặc định (trừ khi user yêu cầu phân tích sâu/chi tiết)"""

    # ── Build multi-turn contents (toàn bộ lịch sử hội thoại) ────────────
    contents = []
    if conversation_history:
        for msg in conversation_history:
            role = 'user' if msg['role'] == 'user' else 'model'
            text = msg['text']
            # Strip HTML từ tin nhắn bot (được lưu dạng HTML để hiển thị)
            if role == 'model':
                text = _strip_html(text)
            contents.append(types.Content(
                role=role,
                parts=[types.Part(text=text)]
            ))

    # Câu hỏi hiện tại luôn là turn cuối cùng của user
    contents.append(types.Content(
        role='user',
        parts=[types.Part(text=user_message)]
    ))

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.7,
            )
        )
        return response.text
    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            raise GeminiRateLimitError(err)
        raise


def ask_gemini_file_mode(user_message: str, file_content: str, filename: str) -> str:
    """
    Chế độ hỏi đáp tự do về file đã upload.
    Gemini đọc toàn bộ nội dung file và trả lời tự nhiên theo ngữ cảnh câu hỏi.
    """
    prompt = f"""Bạn là Revenue AI — chuyên gia phân tích doanh thu, trò chuyện tự nhiên như người thật, không máy móc.

File đang phân tích: {filename}
=== DỮ LIỆU ===
{file_content}
===============

QUY TẮC:
1. Nếu người dùng chào hỏi / nói chuyện thông thường → trả lời tự nhiên đúng ngữ cảnh, ngắn gọn, thân thiện. KHÔNG liệt kê cấu trúc file hay số liệu khi họ chỉ chào.
2. Nếu người dùng hỏi phân tích dữ liệu → dùng số liệu thực từ file, phân tích rõ ràng, nhận xét như chuyên gia thực sự (không đọc lại dữ liệu thô, hãy tóm tắt thành insight có giá trị).
3. Trả lời bằng tiếng Việt tự nhiên, mạch lạc.
4. HTML thuần, KHÔNG markdown, KHÔNG ```.

Định dạng cho câu hỏi phân tích:
<div style="line-height:1.8">
  <div style="font-size:13px;font-weight:700;color:#10b981;margin-bottom:8px">[Tiêu đề ngắn]</div>
  [Nội dung phân tích tự nhiên, có thể dùng <br> hoặc <ul><li> khi cần]
</div>

Định dạng cho chào hỏi / hội thoại thông thường:
<div style="line-height:1.8">[câu trả lời ngắn, tự nhiên]</div>

Câu hỏi: {user_message}"""

    try:
        return _call_gemini(prompt)
    except Exception as e:
        return (
            '<div style="color:#f87171">'
            f'⚠️ Lỗi Gemini: {str(e)[:120]}'
            '</div>'
        )


def ask_gemini_free(user_message: str) -> str:
    """
    Chế độ chat tự do — không có file, không có data context.
    Gemini trả lời tự nhiên như một trợ lý AI thông thường.
    Nếu user hỏi về dữ liệu/phân tích → gợi ý upload file.
    """
    prompt = f"""Bạn là Revenue AI — trợ lý phân tích doanh thu thông minh, nói chuyện tự nhiên như người thật, thân thiện và ngắn gọn.

Hoàn cảnh: người dùng CHƯA upload bất kỳ file dữ liệu nào.

Quy tắc cứng:
- Nếu người dùng chào hỏi / hỏi thăm / nói chuyện thông thường → trả lời tự nhiên đúng ngữ cảnh đó, TUYỆT ĐỐI không nhắc gì đến file, CSV, upload hay dữ liệu.
- Nếu người dùng hỏi về phân tích doanh thu / số liệu / dữ liệu cụ thể → trả lời rằng bạn cần có dữ liệu, và gợi ý nhẹ họ upload file bằng nút "+ Công cụ" trong ô chat.
- Luôn viết tiếng Việt tự nhiên, không máy móc, không liệt kê gạch đầu dòng khi không cần thiết.
- Trả về HTML thuần, KHÔNG markdown, KHÔNG ```, KHÔNG **.
- Wrap bằng: <div style="line-height:1.8">[nội dung]</div>

Tin nhắn của người dùng: {user_message}"""

    try:
        return _call_gemini(prompt)
    except Exception as e:
        return (
            '<div style="color:#f87171">'
            f'⚠️ Lỗi kết nối Gemini: {str(e)[:120]}'
            '</div>'
        )
