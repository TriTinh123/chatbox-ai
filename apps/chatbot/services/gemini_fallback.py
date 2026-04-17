# ════════════════════════════════════════════════════════════════════════════
#  gemini_fallback.py — Tích hợp Groq API (Primary) + Google Gemini Flash (Fallback)
#  Xử lý toàn bộ chat: hội thoại tự do và phân tích file upload.
# ════════════════════════════════════════════════════════════════════════════

import os
import re
import time
from google import genai
from google.genai import types
from groq import Groq
from dotenv import load_dotenv

load_dotenv()   # Đọc GEMINI_API_KEY và GROQ_API_KEY từ file .env

# ── Initialize Groq (PRIMARY) ────────────────────────────────────────
groq_api_key = os.environ.get("GROQ_API_KEY", "")
groq_client = Groq(api_key=groq_api_key) if groq_api_key else None

# ── Initialize Gemini (FALLBACK) ────────────────────────────────────
gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
gemini_client = genai.Client(api_key=gemini_api_key) if gemini_api_key else None

# Deprecated: Keep for backwards compatibility
client = gemini_client

class GeminiRateLimitError(Exception):
    """Raised khi Gemini trả về 429 RESOURCE_EXHAUSTED."""
    pass

class GroqRateLimitError(Exception):
    """Raised khi Groq trả về rate limit error."""
    pass


def generate_fallback_response(data_context: dict, user_message: str, conversation_history: list = None) -> str:
    """
    ✅ Enhanced conversational fallback system.
    Provides natural, continuous conversation like ChatGPT.
    Remembers context and responds intelligently.
    """
    msg_lower = user_message.lower()

    # ── Extract conversation context ─────────────────────────────────────
    last_bot_messages = []
    if conversation_history:
        for msg in conversation_history[-4:]:  # Last 4 messages for context
            if msg['role'] == 'assistant':
                last_bot_messages.append(msg['text'])

    # ── GREETING & INTRODUCTION ──────────────────────────────────────────
    if any(x in msg_lower for x in ['xin chào', 'chào', 'hello', 'hi', 'xin chao', 'chao']):
        if not last_bot_messages:  # First interaction
            return (
                '<div style="line-height:1.8">'
                '<strong>👋 Xin chào!</strong> Tôi là Revenue AI, chuyên gia phân tích doanh thu.<br><br>'
                'Tôi đang phân tích dữ liệu bán hàng của bạn và thấy một số điểm đáng chú ý. '
                'Bạn muốn tôi chia sẻ tổng quan về tình hình doanh thu tháng này không?'
                '</div>'
            )
        else:  # Subsequent greetings
            return (
                '<div style="line-height:1.8">'
                '<strong>👋 Chào lại bạn!</strong><br><br>'
                'Chúng ta đang thảo luận về dữ liệu doanh thu. Bạn có câu hỏi gì tiếp theo không?'
                '</div>'
            )

    # ── REVENUE OVERVIEW ────────────────────────────────────────────────
    if any(x in msg_lower for x in ['doanh thu', 'tổng quan', 'overview', 'tong quan', 'tháng này', 'thang nay']):
        chg = data_context.get('chg_pct', 0)
        cur_rev = data_context.get('cur_rev', 'N/A')
        prev_rev = data_context.get('prev_rev', 'N/A')
        cur_month = data_context.get('cur_month', 'tháng này')

        if chg < 0:
            trend_desc = f"giảm đáng kể {abs(chg):.1f}%"
            analysis = "Đây là một mức sụt giảm khá lớn. Nguyên nhân chính có thể do số lượng bán hàng giảm."
        else:
            trend_desc = f"tăng {chg:.1f}%"
            analysis = "Tình hình khá khả quan với mức tăng trưởng này."

        return (
            '<div style="line-height:1.8">'
            f'<strong>💰 Doanh thu {cur_month}:</strong> <span style="font-size:1.1em;color:#7c3aed">{cur_rev}</span><br>'
            f'<strong>📊 So với tháng trước:</strong> {trend_desc}<br>'
            f'<small>Tháng trước: {prev_rev}</small><br><br>'
            f'<em>{analysis}</em><br><br>'
            'Bạn có muốn tôi phân tích sâu hơn về sản phẩm nào bị ảnh hưởng nhiều nhất không?'
            '</div>'
        )

    # ── PRODUCT ANALYSIS ────────────────────────────────────────────────
    if any(x in msg_lower for x in ['sản phẩm', 'product', 'san pham', 'bán tốt', 'ban tot', 'best', 'top', 'tệ', 'te', 'worst']):
        worst_prod = data_context.get('worst_product', 'N/A')
        prod_chg = data_context.get('prod_chg', 0)
        product_breakdown = data_context.get('product_breakdown', [])

        if any(x in msg_lower for x in ['tốt', 'tot', 'best', 'top']):
            # Build detailed product list with breakdown data
            product_detail = ""
            if product_breakdown:
                for i, prod in enumerate(product_breakdown[:3], 1):
                    product_detail += (
                        f'{i}️⃣ <strong>{prod["product"]}</strong>: '
                        f'Doanh thu giảm <strong style="color:#dc2626">{abs(prod["chg_pct"]):.1f}%</strong> '
                        f'(đóng góp {prod["impact_pct"]:.1f}% vào sụt giảm chung)<br>'
                    )
            
            return (
                '<div style="line-height:1.8">'
                '<strong>🏆 Phân tích sản phẩm — Bán tốt nhất:</strong><br><br>'
                'Trong bối cảnh thị trường hiện tại, tất cả sản phẩm đều đang gặp áp lực. '
                'Không có sản phẩm nào thực sự "bán tốt" mà chúng ta cần nhìn vào sản phẩm nào <strong>giảm ít nhất</strong>.<br><br>'
                f'{product_detail}'
                if product_detail else ''
                f'Như bạn thấy, <strong>{worst_prod}</strong> bị ảnh hưởng nặng nhất với mức giảm {abs(prod_chg):.1f}%. '
                'Tất cả sản phẩm chính đều đồng loạt giảm doanh số, cho thấy vấn đề là toàn diện.<br><br>'
                'Bạn muốn phân tích sâu hơn các yếu tố khác như kênh bán hay khu vực không?'
                '</div>'
            )
        else:
            # Generic product query - show detailed breakdown
            product_detail = ""
            if product_breakdown:
                for i, prod in enumerate(product_breakdown[:3], 1):
                    product_detail += (
                        f'{i}️⃣ <strong>{prod["product"]}</strong>: '
                        f'Doanh thu giảm {abs(prod["chg_pct"]):.1f}% '
                        f'(đóng góp {prod["impact_pct"]:.1f}%)<br>'
                    )
            
            return (
                '<div style="line-height:1.8">'
                f'<strong>📦 Phân tích sản phẩm — Chi tiết:</strong><br><br>'
                f'{product_detail}'
                if product_detail else ''
                f'<em>Sản phẩm bị ảnh hưởng nặng nhất:</em><br>'
                f'<strong style="color:#dc2626">{worst_prod}</strong> với mức giảm <strong>{abs(prod_chg):.1f}%</strong><br><br>'
                'Đây là những sản phẩm chính trong danh sách đóng góp vào sự sụt giảm tổng thể doanh thu. '
                'Bạn muốn tôi đi sâu hơn vào từng sản phẩm cụ thể không?'
                '</div>'
            )

    # ── CHANNEL ANALYSIS ────────────────────────────────────────────────
    if any(x in msg_lower for x in ['kênh', 'channel', 'kenh', 'online', 'offline', 'đối tác', 'doi tac']):
        worst_ch = data_context.get('worst_channel', 'N/A')
        ch_chg = data_context.get('ch_chg', 0)

        return (
            '<div style="line-height:1.8">'
            f'<strong>🏪 Kênh bán hàng bị ảnh hưởng nhiều nhất:</strong> <strong style="color:#dc2626">{worst_ch}</strong><br>'
            f'<strong>Mức giảm:</strong> <span style="color:#dc2626"><strong>{abs(ch_chg):.1f}%</strong></span><br><br>'
            '<em>Kênh này cần được xem xét lại chiến lược.</em><br><br>'
            'Bạn có kế hoạch gì để cải thiện kênh này không?'
            '</div>'
        )

    # ── REGION ANALYSIS ────────────────────────────────────────────────
    if any(x in msg_lower for x in ['khu vực', 'vùng', 'region', 'khu vuc', 'vung', 'hcm', 'hà nội', 'ha noi', 'đà nẵng', 'da nang']):
        return (
            '<div style="line-height:1.8">'
            '<strong>🌍 Phân tích theo khu vực:</strong><br><br>'
            'Tôi có thể phân tích doanh thu theo từng khu vực địa lý. '
            'Ví dụ như Hồ Chí Minh, Hà Nội, Đà Nẵng, v.v.<br><br>'
            'Bạn muốn biết khu vực nào đang gặp khó khăn nhất không?'
            '</div>'
        )

    # ── ROOT CAUSE ANALYSIS ────────────────────────────────────────────
    if any(x in msg_lower for x in ['tại sao', 'tai sao', 'lý do', 'ly do', 'nguyên nhân', 'nguyen nhan', 'vì sao', 'vi sao']):
        dominant = data_context.get('dominant', 'both')

        cause_text = {
            'quantity': 'số lượng bán hàng giảm đáng kể',
            'price': 'giá bán trung bình giảm',
            'both': 'cả số lượng lẫn giá bán đều giảm'
        }.get(dominant, 'không xác định')

        return (
            '<div style="line-height:1.8">'
            '<strong>🔍 Nguyên nhân chính dẫn đến sụt giảm:</strong><br><br>'
            f'Dựa trên dữ liệu, nguyên nhân hàng đầu là: <strong>{cause_text}</strong>.<br><br>'
            '<em>Điều này cho thấy vấn đề không chỉ ở một khía cạnh mà là tổng thể.</em><br><br>'
            'Theo bạn, chúng ta nên tập trung cải thiện điều gì trước?'
            '</div>'
        )

    # ── FORECAST ───────────────────────────────────────────────────────
    if any(x in msg_lower for x in ['dự báo', 'du bao', 'predict', 'forecast', 'tháng sau', 'thang sau', 'tương lai', 'tuong lai']):
        return (
            '<div style="line-height:1.8">'
            '<strong>📈 Dự báo cho tháng tới:</strong><br><br>'
            'Dựa trên xu hướng hiện tại, nếu không có biện pháp can thiệp, doanh thu có thể tiếp tục giảm hoặc ổn định ở mức thấp.<br><br>'
            '<em>Đây là lúc chúng ta cần hành động quyết liệt để đảo ngược tình thế.</em><br><br>'
            'Bạn có kế hoạch cụ thể nào cho tháng tới chưa?'
            '</div>'
        )

    # ── RECOMMENDATION ──────────────────────────────────────────────────
    if any(x in msg_lower for x in ['nên', 'cần', 'gợi ý', 'goi y', 'khắc phục', 'khac phuc', 'cải thiện', 'cai thien', 'giải pháp', 'giai phap']):
        return (
            '<div style="line-height:1.8">'
            '<strong>💡 Một số gợi ý để cải thiện tình hình:</strong><br><br>'
            '1️⃣ <strong>Tăng cường marketing:</strong> Chạy các chương trình khuyến mãi để kích thích nhu cầu<br>'
            '2️⃣ <strong>Đa dạng hóa kênh bán:</strong> Khai thác thêm các kênh bán hàng mới<br>'
            '3️⃣ <strong>Tối ưu sản phẩm:</strong> Tập trung vào sản phẩm bán chạy, cải thiện sản phẩm yếu<br>'
            '4️⃣ <strong>Cải thiện dịch vụ:</strong> Nâng cao chất lượng phục vụ khách hàng<br><br>'
            '<em>Mỗi biện pháp đều cần thời gian để thấy hiệu quả.</em><br><br>'
            'Theo bạn, biện pháp nào khả thi nhất trong tình hình hiện tại?'
            '</div>'
        )

    # ── CHART REQUESTS ──────────────────────────────────────────────────
    if any(x in msg_lower for x in ['biểu đồ', 'bieudo', 'chart', 'graph', 'vẽ', 've']):
        return (
            '<div style="line-height:1.8">'
            '<strong>📊 Về biểu đồ:</strong><br><br>'
            'Tôi có thể cung cấp dữ liệu chi tiết để bạn tự vẽ biểu đồ. '
            'Ví dụ như top 3 sản phẩm bị ảnh hưởng, xu hướng doanh thu theo thời gian, v.v.<br><br>'
            'Bạn muốn dữ liệu cho biểu đồ loại nào?'
            '</div>'
        )

    # ── CONVERSATIONAL RESPONSES ───────────────────────────────────────
    # Handle follow-up questions and general conversation
    if any(x in msg_lower for x in ['có', 'co', 'yes', 'đúng', 'dung', 'ok', 'okay']):
        return (
            '<div style="line-height:1.8">'
            '👍 Tốt! Bạn muốn tôi giải thích chi tiết hơn về vấn đề nào?<br><br>'
            '• Phân tích sâu về sản phẩm<br>'
            '• Chi tiết về từng kênh bán<br>'
            '• Dự báo cho tháng tới<br>'
            '• Gợi ý giải pháp<br><br>'
            'Hay bạn có câu hỏi cụ thể nào khác?'
            '</div>'
        )

    if any(x in msg_lower for x in ['không', 'khong', 'no', 'không có', 'khong co']):
        return (
            '<div style="line-height:1.8">'
            '👌 Hiểu rồi. Bạn muốn thảo luận về vấn đề gì khác?<br><br>'
            'Tôi có thể giúp bạn với:<br>'
            '• Phân tích xu hướng thị trường<br>'
            '• So sánh với các tháng trước<br>'
            '• Dự báo tương lai<br>'
            '• Tư vấn chiến lược kinh doanh'
            '</div>'
        )

    # ── DEFAULT CONVERSATIONAL RESPONSE ────────────────────────────────
    return (
        '<div style="line-height:1.8">'
        '💬 <strong>Tôi hiểu bạn đang quan tâm đến dữ liệu doanh thu.</strong><br><br>'
        'Dựa trên những gì chúng ta đã thảo luận, tôi có thể giúp bạn:<br><br>'
        '• 📊 <strong>Tổng quan:</strong> Doanh thu tháng này và xu hướng<br>'
        '• 📉 <strong>Phân tích:</strong> Sản phẩm, kênh, khu vực bị ảnh hưởng<br>'
        '• 💡 <strong>Giải pháp:</strong> Gợi ý cải thiện tình hình<br>'
        '• 📈 <strong>Dự báo:</strong> Xu hướng tháng tới<br><br>'
        '<em>Hãy cho tôi biết cụ thể bạn muốn biết gì nhé!</em>'
        '</div>'
    )



def _strip_html(text: str) -> str:
    """Xóa HTML tags từ text để dùng làm context hội thoại."""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _call_gemini(prompt: str) -> str:
    """Gọi Gemini. Retry tự động khi 503, raise GeminiRateLimitError khi 429."""
    if not gemini_client:
        raise ValueError("GEMINI_API_KEY chưa được cấu hình")
    for attempt in range(3):
        try:
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            return response.text
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                raise GeminiRateLimitError(err)
            if ("503" in err or "UNAVAILABLE" in err) and attempt < 2:
                time.sleep(2 ** attempt)  # 1s, 2s
                continue
            raise


def _call_groq(messages: list, system_instruction: str = "", model: str = "llama-3.1-8b-instant", max_tokens: int = 1024, temperature: float = 0.7) -> str:
    """Gọi Groq API. Messages format: [{'role': 'user'|'assistant', 'content': str}]"""
    if not groq_client:
        raise ValueError("GROQ_API_KEY chưa được cấu hình")
    
    # Build messages with system instruction
    all_messages = messages
    if system_instruction:
        # Add system instruction to the first user message or as a separate message
        if all_messages and all_messages[0]['role'] == 'user':
            # Prepend system instruction to first user message
            first_msg = all_messages[0]['content']
            all_messages[0]['content'] = f"{system_instruction}\n\n{first_msg}"
    
    try:
        response = groq_client.chat.completions.create(
            model=model,
            messages=all_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content
    except Exception as e:
        err = str(e)
        if "429" in err or "rate_limit" in err.lower():
            raise GroqRateLimitError(err)
        if "401" in err or "unauthorized" in err.lower():
            raise ValueError("GROQ_API_KEY không hợp lệ")
        raise


def ask_groq_general(user_message: str, conversation_history: list = None) -> str:
    """
    General-purpose Groq chat - for non-revenue questions.
    Natural conversation without revenue analysis constraints.
    """
    if not groq_client:
        raise ValueError("GROQ_API_KEY chưa được cấu hình")

    # Build message history
    messages = []
    if conversation_history:
        for msg in conversation_history:
            role = 'user' if msg['role'] == 'user' else 'assistant'
            text = msg['text']
            if role == 'assistant':
                text = _strip_html(text)
            messages.append({'role': role, 'content': text})
    
    messages.append({'role': 'user', 'content': user_message})
    
    system_instruction = """Bạn là trợ lý AI thân thiện và hữu ích - giống ChatGPT.
Trả lời câu hỏi một cách tự nhiên, chính xác và hữu ích.

HƯỚNG DẪN STYLE:
- Thêm emoji/icon phù hợp vào đầu hoặc giữa câu trả lời
- Ví dụ: 🌤️ cho thời tiết, 🔢 cho toán, 💡 cho gợi ý, ❓ cho câu hỏi
- Format rõ ràng với xuống dòng để tách đoạn
- Thân thiện, hỗ trợ tích cực, hữu ích

Nếu không biết, nói thẳng: ❌ Không biết, nhưng có thể giúp bạn tìm kiếm"""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_instruction},
                *messages
            ],
            temperature=0.7,
            max_tokens=1024
        )
        
        result = response.choices[0].message.content
        # Convert markdown to HTML - properly handle bold, line breaks
        result = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', result)  # **text** → <strong>text</strong>
        result = result.replace("\n", "<br>")
        return f'<div style="line-height:1.8; font-size:1.05em; padding:10px">{result}</div>'
    except Exception as e:
        err = str(e)
        if "429" in err or "rate_limit" in err.lower():
            raise GroqRateLimitError(err)
        raise


def ask_groq_stream_general(user_message: str, conversation_history: list = None):
    """
    Streaming version of ask_groq_general for non-revenue questions.
    Yields text chunks as they arrive from Groq API.
    """
    if not groq_client:
        raise ValueError("GROQ_API_KEY chưa được cấu hình")

    # Build message history
    messages = []
    if conversation_history:
        for msg in conversation_history:
            role = 'user' if msg['role'] == 'user' else 'assistant'
            text = msg['text']
            if role == 'assistant':
                text = _strip_html(text)
            messages.append({'role': role, 'content': text})
    
    messages.append({'role': 'user', 'content': user_message})
    
    system_instruction = """Bạn là trợ lý AI thân thiện và hữu ích - giống ChatGPT.
Trả lời câu hỏi một cách tự nhiên, chính xác và hữu ích.

HƯỚNG DẪN STYLE:
- Thêm emoji/icon phù hợp vào đầu hoặc giữa câu trả lời
- Ví dụ: 🌤️ cho thời tiết, 🔢 cho toán, 💡 cho gợi ý, ❓ cho câu hỏi
- Format rõ ràng với xuống dòng để tách đoạn
- Thân thiện, hỗ trợ tích cực, hữu ích

Nếu không biết, nói thẳng: ❌ Không biết, nhưng có thể giúp bạn tìm kiếm"""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_instruction},
                *messages
            ],
            temperature=0.7,
            max_tokens=1024,
            stream=True
        )
        
        for event in response:
            if event.choices and event.choices[0].delta.content:
                chunk = event.choices[0].delta.content
                # Convert markdown to HTML
                chunk = chunk.replace("**", "<strong>")
                chunk = chunk.replace("\n", "<br>")
                yield chunk
                
    except Exception as e:
        err = str(e)
        if "429" in err or "rate_limit" in err.lower():
            raise GroqRateLimitError(err)
        raise


def ask_groq(user_message: str, data_context: dict, conversation_history: list = None, is_detailed: bool = False) -> str:
    """
    Gửi câu hỏi tới Groq Mixtral với native multi-turn conversation.
    Nhớ TOÀN BỘ cuộc hội thoại — không giới hạn số tin nhắn (giống ChatGPT/Gemini).
    conversation_history: list of {'role': 'user'|'assistant', 'text': str}
    is_detailed: True nếu user yêu cầu phân tích sâu → tăng độ chi tiết
    """
    if not groq_client:
        raise ValueError("GROQ_API_KEY chưa được cấu hình")

    # ── Build data context ────
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

    # ── System instruction ───
    word_limit = "800-1200 từ" if is_detailed else "500-800 từ"
    
    system_instruction = f"""Bạn là Revenue AI - nhà phân tích doanh thu chuyên nghiệp.
{data_block}

⚠️ LUẬT LỆ TUYỆT ĐỐI (BẮT BUỘC - VI PHẠM = SAI):

1. **CHỈ dùng dữ liệu được cung cấp** - KHÔNG đoán mò, KHÔNG bịa ra số
   - Nếu không có dữ liệu → trả lời: "Không đủ dữ liệu để kết luận"
   - Mọi con số phải lấy từ [DỮ LIỆU THỰC TẾ TỪ sales.csv]
   - VD SAI: "Có thể do nhu cầu thị trường" - KHÔNG CÓ TRONG DỮ LIỆU
   - VD ĐÚNG: "Laptop giảm -87.5%, Điện thoại giảm -80.2%" - CÓ TRONG DỮ LIỆU

2. **KHÔNG được phỏng đoán nguyên nhân**
   - Chỉ nêu dữ liệu, không guessing
   - ✓ "Số lượng giảm 15%, giá giảm 20%"
   - ✗ "Có thể do cạnh tranh"

3. **PHẢI trích dẫn con số cụ thể**
   - ✓ "Doanh thu: 13,997,655,537 đ, giảm -81.2%"
   - ✗ "Doanh thu giảm đáng kể"

4. **BẮT BUỘC kết cấu HTML** (KHÔNG MARKDOWN - vi phạm là SAI):
   <strong>📊 KẾT QUẢ</strong><br>
   Cụ thể con số từ dữ liệu<br><br>
   <strong>🔍 NGUYÊN NHÂN CHÍNH</strong><br>
   Phân tích số lượng vs giá từ dữ liệu<br><br>
   <strong>📈 CHI TIẾT</strong><br>
   Top 3 sản phẩm: - Laptop: -87.5%<br> - Điện thoại: -80.2%<br> - Máy tính bảng: -80.6%<br><br>
   <strong>💡 KHUYẾN NGHỊ</strong><br>
   Từ dữ liệu

5. **HTML TAGS - BẮT BUỘC:**
   - ✓ Dùng: <strong>TEXT</strong>, <br>, <em>TEXT</em>
   - ✗ KHÔNG dùng: **TEXT**, _TEXT_, newlines
   - ✓ VD: <strong>Laptop</strong> giảm <strong>-87.5%</strong><br>
   - ✗ SAI: **Laptop** giảm **-87.5%**

6. **Độ dài**: {word_limit}
7. **Giọng điệu**: Chuyên gia, dữ liệu-driven, cụ thể"""

    # ── Build multi-turn messages ────
    messages = []
    if conversation_history:
        for msg in conversation_history:
            role = 'user' if msg['role'] == 'user' else 'assistant'
            text = msg['text']
            # Strip HTML từ tin nhắn bot (được lưu dạng HTML để hiển thị)
            if role == 'assistant':
                text = _strip_html(text)
            messages.append({'role': role, 'content': text})

    # Câu hỏi hiện tại luôn là turn cuối cùng của user
    messages.append({'role': 'user', 'content': user_message})

    # ✅ Call Groq
    response = _call_groq(
        messages=messages,
        system_instruction=system_instruction,
        model="llama-3.1-8b-instant",
        max_tokens=2048,
        temperature=0.2
    )
    
    # Convert Markdown to HTML for consistency
    response = response.replace("**", "<strong>").replace("__", "<strong>")
    response = response.replace("\n", "<br>\n")
    
    return response


def ask_groq_stream(user_message: str, data_context: dict, conversation_history: list = None, is_detailed: bool = False):
    """
    Streaming version của ask_groq. Yield từng chunk khi nhận được.
    """
    if not groq_client:
        raise ValueError("GROQ_API_KEY chưa được cấu hình")

    # ── Build data context ────
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

    # ── System instruction - Consultant style with data context ───
    
    # Format data from data_context (new format from get_sales_summary)
    data_summary = ""
    if data_context and data_context.get('cur_rev'):
        # Format revenue properly
        cur_rev = data_context.get('cur_rev', 0)
        prev_rev = data_context.get('prev_rev', 0)
        if isinstance(cur_rev, (int, float)):
            cur_rev_str = f"{cur_rev:,.0f}"
        else:
            cur_rev_str = str(cur_rev)
        if isinstance(prev_rev, (int, float)):
            prev_rev_str = f"{prev_rev:,.0f}"
        else:
            prev_rev_str = str(prev_rev)
        
        data_summary = f"""
📊 Dữ liệu phân tích hiện tại:
- Tháng hiện tại: {data_context.get('cur_month', 'N/A')}
- Tháng trước: {data_context.get('prev_month', 'N/A')}
- Doanh thu hiện tại: {cur_rev_str} đồng
- Doanh thu tháng trước: {prev_rev_str} đồng
- Thay đổi doanh thu: {data_context.get('chg_pct', 0):.1f}%
- Số lượng hiện tại: {data_context.get('cur_qty', 0):,} sản phẩm
- Số lượng tháng trước: {data_context.get('prev_qty', 0):,} sản phẩm
- Thay đổi số lượng: {data_context.get('qty_chg_pct', 0):.1f}%
- Giá bình quân hiện tại: {data_context.get('cur_price', 0):,.0f} đồng/sp
- Giá bình quân tháng trước: {data_context.get('prev_price', 0):,.0f} đồng/sp
- Thay đổi giá: {data_context.get('price_chg_pct', 0):.1f}%
- Sản phẩm giảm nhất: {data_context.get('worst_product', 'N/A')} ({data_context.get('prod_chg', 0):.1f}%)
- Kênh kém nhất: {data_context.get('worst_channel', 'N/A')} ({data_context.get('ch_chg', 0):.1f}%)
- Nguyên nhân chính: {data_context.get('dominant', 'không xác định')}
"""
    
    system_instruction = f"""You are Revenue AI, a senior Vietnamese business analyst.

Your role:
- Analyze revenue performance using provided data
- Explain clearly in natural Vietnamese
- Focus on real business insight, not generic theory

CRITICAL RULES (MUST FOLLOW):
- Only use the provided analysis data (quantity, price, product, channel)
- DO NOT guess causes like marketing, competition, staff, or external factors
- DO NOT use phrases like "có thể do..." unless directly supported by data
- If deeper cause is unknown, say: "Dữ liệu hiện tại chưa đủ để xác định nguyên nhân sâu hơn."
- Never claim knowledge about things NOT in the data

🚨 NO GUESSING RULE (CỰC QUAN TRỌNG):
- Do NOT suggest possible causes beyond the data (no marketing, tồn kho, sales, trưng bày)
- If deeper causes are unknown, clearly say: "Dữ liệu hiện tại chưa đủ để xác định nguyên nhân sâu hơn."
- NEVER suggest causes like tồn kho, trưng bày, marketing, nhân viên
- Only describe what is visible in the data
- If deeper cause is unknown, say:
  "Dữ liệu hiện tại chưa đủ để xác định nguyên nhân sâu hơn."
- NEVER guess reasons like:
  ❌ "có thể do marketing kém"
  ❌ "có thể do nhân viên"
  ❌ "có thể do tồn kho"
  ❌ "có thể do cạnh tranh"
  ❌ "có thể do nhu cầu khách"
- Only explain based on ACTUAL DATA:
  ✅ Quantity change %
  ✅ Price change %
  ✅ Product-specific data
  ✅ Channel-specific data
- If the real cause is NOT in data, say: "Dữ liệu hiện tại chưa đủ để xác định nguyên nhân sâu hơn."
- NEVER assume causes beyond the provided metrics

CORE RULES:
- Answer directly, no unnecessary greeting
- Do not use vague phrases like "có thể", "thường là"
- Do not give generic theory
- Only use provided analysis data
- Always include numbers when available
- If data is missing, say: "Không đủ dữ liệu để kết luận chính xác."

STYLE:
- Natural Vietnamese
- Calm, confident
- Like a real business analyst
- Not robotic, not textbook

DEPTH REQUIREMENT (QUAN TRỌNG):
- Do NOT be too short
- Expand answers with deeper explanation
- Always include 1–2 extra layers:
  + explain WHY it happens
  + explain business impact
- Answers should feel complete, not minimal
- PRIORITY: Depth > Brevity (longer detailed answer is better than short vague answer)

DEPTH IS MANDATORY (QUAN TRỌNG CẤP ĐỘ CAO):
- For "Vì sao?" questions: MUST explain 2-3 layers minimum
  + What changed (the fact)
  + Why it changed (root cause from data)
  + What it means (impact on business)
- Do NOT answer "Vì sao?" in 1-2 sentences
- Add extra insight about products/channels/numbers involved
- Always include specific percentages and product/channel names

FLEXIBLE 5-PART STRUCTURE (INTERNALLY - NOT ALWAYS LABELING):
Use this 5-part framework INTERNALLY to organize thoughts, but express naturally like human conversation:

1️⃣ CONCLUSION (Kết luận chính)
   - Lead with direct answer to user's question
   - Include specific numbers/percentages
   - No need to label explicitly - integrate naturally into opening

2️⃣ CAUSE (Nguyên nhân chính)
   - Explain WHY based on data (quantity, price, product, channel)
   - Use phrases like "Cụ thể là...", "Điều này là do..." 
   - Do NOT label or use emoji headers

3️⃣ INSIGHT (Insight quan trọng - the differentiator)
   - Show deeper pattern recognition
   - Use "Đáng chú ý...", "Điều này cho thấy..."
   - Connect cause to business impact naturally

4️⃣ ACTION (Nên làm gì - if relevant)
   - For "What to do?" questions, suggest prioritized actions
   - Format: "Thứ nhất..., thứ hai..." (no need to label)
   - Link each action to its consequence

5️⃣ CONSEQUENCE (Hậu quả - always at the end)
   - State what happens if NOT acted upon
   - Natural close: "Nếu không..., sẽ..."
   - DO NOT use emoji labels

HOW TO EXPRESS NATURALLY:
✅ GOOD (natural, human-like):
"Doanh thu tháng 3 giảm 81.2% chủ yếu do số lượng bán giảm 76%, trong khi giá chỉ giảm 2%. Đáng chú ý, Laptop giảm 87.5% - sản phẩm này chiếm 40% mức sụt. Nếu không tập trung phục hồi Laptop, doanh thu sẽ tiếp tục giảm."

❌ BAD (over-labeled, robotic):
"🟢 KẾT LUẬN: ... 🔵 NGUYÊN NHÂN: ... 💡 INSIGHT: ... ⚠️ HẬU QUẢ: ..."

TONE GUIDELINES:
- Natural, human-like (like a real business consultant)
- Clear and concise (avoid repetitive phrases)
- Slightly advisory tone (suggest, don't command)
- Connect: cause → why it matters → what to do
- Do not repeat the same idea
- Keep answers concise (3–5 sentences)
- Mention each key factor only once
- Do not repeat the same point multiple times
- Keep answers concise and sharp

RECOMMENDATION RULE:
- Recommendations must be high-level only, no specific actions like marketing, quảng cáo, trưng bày, nhân viên
- NEVER mention specific actions like marketing, quảng cáo, trải nghiệm, nhân viên under any condition
- Focus only on product or channel performance from data
- Must mention specific product or channel from data
- Must include: what to do, why it matters, what happens if not fixed

RESPONSE FORMAT (IMPORTANT):
For clear, structured responses:
1. Use emoji headers to organize sections (📉 📊 💥 💡 🎯 ⚠️ 🚀)
2. Include BEFORE/AFTER numbers:
   - Previous month: X
   - Current month: Y
   - Change: Z (percentage)
3. Break down into clear sections:
   - Key finding (main point)
   - Specific numbers
   - Deeper insights
   - Impact assessment
   - Actionable recommendations (if asking "what to do")
4. Prioritize findings by impact level
5. For recommendations: list by priority, explain why each matters, mention consequences

AVOID:
- "hiệu suất kinh doanh đang gặp khó khăn"
- "có nhiều nguyên nhân"
- "tăng cường marketing"
- "điều này sẽ giúp..."
- "có thể do..." (FORBIDDEN - this is guessing, not data-based analysis)
- "thường là..." (FORBIDDEN - vague generalization)
- "có thể là..." (FORBIDDEN - pure speculation)

WRITING STYLE:
- For analytical/explanation questions: EXPAND answers with depth
- Do NOT keep responses minimal or brief
- For "Vì sao?" or "Tại sao?": Must explain 2-3 layers (WHAT changed → WHY it changed → IMPACT)
- Add 1-2 more sentences explaining deeper insight and business impact
- Aim for 4-7 sentences for complex analysis questions
- Length should match question complexity: simple question = brief, complex question = detailed
- Clear, sharp, meaningful language (not fluff, but substantive explanation)

IF DATA IS LIMITED:
- Be honest and say data is insufficient instead of guessing
- Example: "Dữ liệu hiện tại chưa đủ để xác định nguyên nhân sâu hơn."
- Don't speculate about causes not supported by data

Few-shot examples to follow (NATURAL STYLE - NO EMOJI LABELS):

EXAMPLE 1 - Revenue decline question
User: "Doanh thu tháng này có giảm không?"
Assistant: "Doanh thu tháng 3 giảm 81.2% từ 74.48 tỷ xuống 13.99 tỷ đồng. Mức sụt giảm này chủ yếu do số lượng bán giảm 76%, trong khi giá chỉ giảm 2%, nên nguyên nhân chính là lực bán yếu đi. Đáng chú ý, Laptop giảm 87.5% và Offline giảm 84.5% - hai yếu tố này chiếm 70% mức sụt, cho thấy vấn đề tập trung vào sản phẩm và kênh cụ thể. Nên ưu tiên phục hồi Laptop vì impact cao nhất. Nếu không hành động, doanh thu sẽ tiếp tục giảm."

EXAMPLE 2 - Root cause question  
User: "Vì sao?"
Assistant: "Nguyên nhân chính là số lượng bán ra giảm mạnh, không phải do giá. Cụ thể, Laptop (-87.5%) và kênh Offline (-84.5%) là hai yếu tố đóng góp lớn nhất vào mức giảm tổng. Điều này cho thấy sự sụt giảm tập trung ở sản phẩm và kênh này. Dữ liệu hiện tại chưa đủ để xác định nguyên nhân sâu hơn."

EXAMPLE 3 - Action question
User: "Nên làm gì?"
Assistant: "Nên ưu tiên phục hồi Laptop và rà soát lại kênh Offline vì đây là hai điểm kéo doanh thu xuống mạnh nhất. Cần tập trung cải thiện hiệu quả bán ở hai khu vực này trước. Nếu không xử lý, doanh thu sẽ khó phục hồi trong ngắn hạn."

Data context:
{data_summary}"""

    # ── Build multi-turn messages ────
    messages = [
        {'role': 'system', 'content': system_instruction}
    ]
    
    # ── Add few-shot examples to teach the model the expected style ────
    messages.extend([
        {
            "role": "user",
            "content": "Doanh thu tháng này có giảm không?"
        },
        {
            "role": "assistant",
            "content": "Doanh thu tháng 3 giảm 81.2% so với tháng trước, từ 74.48 tỷ xuống còn 13.99 tỷ đồng. Mức giảm này chủ yếu đến từ số lượng bán ra giảm 76%, trong khi giá chỉ giảm nhẹ 2%, nên nguyên nhân chính không nằm ở giá. Đáng chú ý, Laptop giảm 87.5% và kênh Offline giảm 84.5%, đây là hai điểm kéo doanh thu xuống mạnh nhất."
        },
        {
            "role": "user",
            "content": "Vì sao?"
        },
        {
            "role": "assistant",
            "content": "Nguyên nhân chính là số lượng bán ra giảm mạnh, không phải do giá. Cụ thể, quantity giảm 76% trong khi giá chỉ giảm 2%, nên doanh thu sụt chủ yếu vì lực bán yếu đi. Ngoài ra, Laptop giảm 87.5% và kênh Offline giảm 84.5%, đây là hai yếu tố đóng góp lớn nhất vào mức giảm tổng. Điều này cho thấy vấn đề không chỉ nằm ở nhu cầu mà còn ở hiệu quả bán hàng theo sản phẩm và kênh."
        },
        {
            "role": "user",
            "content": "Nên làm gì?"
        },
        {
            "role": "assistant",
            "content": "Trước hết nên tập trung phục hồi Laptop vì đây là sản phẩm giảm mạnh nhất, tới 87.5%. Đồng thời cần rà soát lại kênh Offline vì doanh thu ở kênh này giảm 84.5%, cho thấy vấn đề không chỉ nằm ở sản phẩm mà còn ở kênh bán. Thay vì giảm giá đại trà, nên ưu tiên kiểm tra tồn kho, trưng bày, và hiệu quả bán hàng ở đúng nhóm đang giảm mạnh. Nếu không thực hiện các biện pháp này, doanh thu sẽ tiếp tục giảm và ảnh hưởng đến mục tiêu kinh doanh."
        }
    ])
    
    if conversation_history:
        for msg in conversation_history:
            role = 'user' if msg['role'] == 'user' else 'assistant'
            text = msg['text']
            # Strip HTML từ tin nhắn bot (được lưu dạng HTML để hiển thị)
            if role == 'assistant':
                text = _strip_html(text)
            messages.append({'role': role, 'content': text})

    # Câu hỏi hiện tại luôn là turn cuối cùng của user
    messages.append({'role': 'user', 'content': user_message})

    # ✅ Streaming from Groq with consultant-style parameters
    try:
        with groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            temperature=0.2,  # Low for consistent, data-driven responses
            max_tokens=2048,
            stream=True,
        ) as stream:
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
    except Exception as e:
        err = str(e)
        if "429" in err or "rate_limit" in err.lower():
            raise GroqRateLimitError(err)
        if "401" in err or "unauthorized" in err.lower():
            raise ValueError("GROQ_API_KEY không hợp lệ")
        raise


def ask_gemini(user_message: str, data_context: dict, conversation_history: list = None, is_detailed: bool = False) -> str:
    """
    Gửi câu hỏi tới Gemini Flash với native multi-turn conversation.
    Nhớ TOÀN BỘ cuộc hội thoại — không giới hạn số tin nhắn (giống ChatGPT/Gemini).
    conversation_history: list of {'role': 'user'|'assistant', 'text': str}
    is_detailed: True nếu user yêu cầu phân tích sâu → tăng độ chi tiết
    ✅ IMPROVED: Better retry logic for rate limits.
    """
    if not gemini_client:
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
    # Tăng word limit vì 100% Gemini system (không dùng HTML builders)
    word_limit = "800-1200 từ" if is_detailed else "500-800 từ"
    
    system_instruction = f"""Bạn là Revenue AI - nhà phân tích doanh thu chuyên nghiệp.
{data_block}

LUẬT LỆ TUYỆT ĐỐI (KHÔNG ĐƯỢC VI PHẠM):

1. **CHỈ dùng dữ liệu được cung cấp** - KHÔNG đoán mò, KHÔNG bịa ra số
   - Nếu không có dữ liệu → trả lời: "Không đủ dữ liệu để kết luận"
   - Mọi con số phải lấy từ [DỮ LIỆU THỰC TẾ TỪ sales.csv]

2. **KHÔNG được phỏng đoán nguyên nhân**
   - Chỉ nêu các khả năng dựa trên dữ liệu
   - Ví dụ: "Dữ liệu cho thấy số lượng giảm 15%, giá giảm 20%" (ĐÚNG)
   - Không nói: "Có thể do nhu cầu thị trường sụt giảm" (SAI)

3. **PHẢI trích dẫn con số cụ thể**
   - Luôn viết: "Doanh thu tháng 3 là 93 triệu đồng, giảm 31.2% so với tháng 2"
   - KHÔNG viết: "Doanh thu giảm đáng kể"

4. **BẮT BUỘC kết cấu output** (Vietnamese):
   <strong>📊 KẾT QUẢ</strong><br>
   [Con số chính từ dữ liệu]<br><br>
   <strong>🔍 NGUYÊN NHÂN CHÍNH</strong><br>
   [Phân tích số lượng vs giá dựa CHỈ trên dữ liệu]<br><br>
   <strong>📈 CHI TIẾT</strong><br>
   [Top 3 sản phẩm/kênh bị ảnh hưởng + impact %]<br><br>
   <strong>💡 KHUYẾN NGHỊ</strong><br>
   [Dựa trên dữ liệu được cung cấp]

5. **Độ dài**: {word_limit}
6. **HTML**: <br>, <strong>, <em> - KHÔNG markdown
7. **Giọng điệu**: Chuyên gia dữ liệu, tự tin, lôgic"""

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

    # ✅ IMPROVED: Smarter retry logic - fail fast on quota errors
    max_attempts = 2  # Only 2 attempts - quota errors don't need retries
    for attempt in range(max_attempts):
        try:
            response = gemini_client.models.generate_content(
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
            # Quota exceeded (429 with RESOURCE_EXHAUSTED): fail fast
            if "429" in err or "RESOURCE_EXHAUSTED" in err or "quota" in err.lower():
                raise GeminiRateLimitError(err)
            # Server unavailable: retry with backoff
            if ("503" in err or "UNAVAILABLE" in err) and attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
                continue
            # Other errors: raise immediately
            raise


def ask_gemini_stream(user_message: str, data_context: dict, conversation_history: list = None, is_detailed: bool = False):
    """
    Generator: yields text chunks từ Gemini streaming API.
    Cùng logic với ask_gemini() nhưng dùng generate_content_stream().
    is_detailed: True nếu user yêu cầu phân tích sâu → tăng độ chi tiết
    ✅ Improved: Better retry logic for rate limits + fallback responses.
    """
    if not gemini_client:
        raise ValueError("GEMINI_API_KEY chưa được cấu hình")

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

    # Tăng word limit vì 100% Gemini system (không dùng HTML builders)
    word_limit = "800-1200 từ" if is_detailed else "500-800 từ"
    
    system_instruction = f"""Bạn là Revenue AI - nhà phân tích kinh doanh thông minh cho các doanh nghiệp Việt Nam.

Công việc của bạn là giải thích những thay đổi về doanh thu và bán hàng một cách tự nhiên, chuyên nghiệp, và có ngữ cảnh.

DỮ LIỆU PHÂN TÍCH CỦA BẠN:
{data_block}

LUẬT LỆ TUYỆT ĐỐI:
1. ✅ CHỈ dùng dữ liệu được cung cấp - KHÔNG đoán mò, KHÔNG bịa số
2. ✅ Nếu thiếu dữ liệu → nói rõ: "Không đủ dữ liệu để kết luận chính xác"
3. ✅ Trả lời tự nhiên bằng tiếng Việt, như một nhà phân tích kinh doanh
4. ✅ Tính chuyên nghiệp nhưng vẫn trò chuyện bình thường - KHÔNG máy móc
5. ✅ Luôn lấy ngữ cảnh từ câu hỏi trước (nếu có) - KHÔNG hỏi lại từ đầu
6. ✅ Giải thích rõ ràng, cụ thể, dùng ngôn ngữ kinh doanh đơn giản
7. ✅ Tránh lời khuyên chung chung - CHỈ đưa ý kiến liên quan tới dữ liệu thực
8. ✅ Ưu tiên độ chính xác hơn việc nghe có vẻ thông minh

CÁCH TRẢ LỜI:

1. **Kết luận chính** - Con số quan trọng nhất từ dữ liệu
2. **Phân tích nguyên nhân** - Tại sao nó xảy ra (dựa 100% trên dữ liệu)
3. **Giải thích chi tiết** - Phân tích số lượng vs giá, top sản phẩm, top kênh
4. **Khuyến nghị** - Hành động cụ thể dựa trên dữ liệu (không generic)

ĐỊNH DẠNG:
- Tiếng Việt tự nhiên, chuyên gia
- HTML: <br>, <strong>, <em> - KHÔNG markdown
- Độ dài: {word_limit}
- KHÔNG mô phỏng, KHÔNG giả vờ

TÍNH CÁCH:
- Nhà phân tích kinh doanh có kinh nghiệm
- Chính xác, thẳng thắn, đáng tin cậy
- Tâm lý ứng dụng - luôn giúp user đưa ra quyết định
- Nói rõ ranh giới giữa dữ liệu và ý kiến"""

    contents = []
    if conversation_history:
        for msg in conversation_history:
            role = 'user' if msg['role'] == 'user' else 'model'
            text = msg['text']
            if role == 'model':
                text = _strip_html(text)
            contents.append(types.Content(
                role=role,
                parts=[types.Part(text=text)]
            ))

    contents.append(types.Content(
        role='user',
        parts=[types.Part(text=user_message)]
    ))

    # ✅ IMPROVED: Smarter retry logic - fail fast on quota errors
    max_attempts = 2  # Only 2 attempts - quota errors don't need retries
    for attempt in range(max_attempts):
        try:
            stream = gemini_client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.7,
                )
            )
            for chunk in stream:
                if chunk.text:
                    yield chunk.text
            return  # success
        except Exception as e:
            err = str(e)
            # Quota exceeded (429 with RESOURCE_EXHAUSTED): fail fast
            if "429" in err or "RESOURCE_EXHAUSTED" in err or "quota" in err.lower():
                raise GeminiRateLimitError(err)
            # Server unavailable: retry with backoff
            if ("503" in err or "UNAVAILABLE" in err) and attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
                continue
            # Other errors: raise immediately
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
