# ════════════════════════════════════════════════════════════════════════════
# prompt_template.py - Quản lý prompts cho Gemini API
# ════════════════════════════════════════════════════════════════════════════

"""
Prompt templates để gọi Gemini API.
Dễ quản lý, tái sử dụng, và cập nhật.
"""

import re


def detect_language(text: str) -> str:
    """
    Detect whether text is in English or Vietnamese.
    Returns 'en' for English or 'vi' for Vietnamese.
    Default: 'en' (English) - prefer English for short/ambiguous texts
    """
    if not text or len(text.strip()) < 2:
        return 'en'  # Default to English for short text
    
    # Vietnamese-specific characters (most reliable indicator)
    vietnamese_chars = r'[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]'
    vi_char_count = len(re.findall(vietnamese_chars, text.lower()))
    
    # If Vietnamese characters found (definitive - check for >= 1 instead of >= 2)
    if vi_char_count >= 1:
        return 'vi'
    
    # Common Vietnamese words
    vietnamese_words = ['và', 'là', 'có', 'cái', 'chiếc', 'tại', 'sao', 'vì', 'không', 'nào', 'được', 
                        'giảm', 'tăng', 'doanh', 'thu', 'sản', 'phẩm', 'kênh', 'tháng', 'lý', 'do',
                        'gì', 'nên', 'này', 'năm', 'tuần', 'ngày', 'giờ']
    text_lower = text.lower()
    vi_word_count = sum(1 for word in vietnamese_words if word in text_lower)
    
    # Common English words (expanded)
    english_words = ['the', 'is', 'and', 'to', 'of', 'why', 'what', 'how', 'revenue', 'product', 
                    'channel', 'month', 'reason', 'decrease', 'increase', 'analysis', 'data',
                    'did', 'do', 'does', 'drop', 'dropped', 'this', 'that', 'when', 'who', 'which',
                    'see', 'check', 'analyze', 'report', 'sales', 'down', 'up', 'year', 'day', 'week',
                    'a', 'an', 'by', 'in', 'on', 'for', 'from', 'with', 'as', 'hello', 'hi', 'hey',
                    'there', 'are', 'be', 'been', 'have', 'has', 'had', 'world', 'best', 'good',
                    'can', 'could', 'should', 'would', 'right', 'like', 'just', 'more', 'than']
    en_word_count = sum(1 for word in english_words if word in text_lower)
    
    # Decision logic
    # If only Vietnamese words found (no English)
    if vi_word_count > 0 and en_word_count == 0:
        return 'vi'
    
    # If both English and Vietnamese words are found, compare counts
    if en_word_count > 0 and vi_word_count > 0:
        return 'en' if en_word_count > vi_word_count else 'vi'
    
    # If only English words found (no Vietnamese)
    if en_word_count >= 1 and vi_word_count == 0:  # Lowered threshold to 1
        return 'en'
    
    # Default to English for ambiguous cases (changed from 'vi')
    return 'en'


def build_system_prompt(language: str = 'vi'):
    """
    System prompt chính - hướng dẫn Gemini cách phân tích.
    
    Args:
        language: 'vi' for Vietnamese, 'en' for English
    
    Returns:
        str: System prompt in the specified language
    """
    
    if language == 'en':
        return """You are Revenue AI, a professional business analyst.

Guidelines:
- Don't greet the user - answer their question directly
- Don't ask questions back - just provide the analysis
- Don't use vague language like "might" or "possibly" - be specific
- Don't guess numbers - only use the data provided
- Stay professional and conversational

When analyzing revenue changes:
1. Identify the main cause (quantity decline vs price change)
2. Name the biggest impact factor (product or channel)
3. Quantify the impact (what % of total loss does it represent)
4. Recommend 1-2 specific actions based on the data
5. Briefly note the risk if no action is taken

Response style:
- Natural and direct
- Use specific numbers and percentages
- Include product names, channel names, and amounts
- Don't repeat the same idea
- Keep answers concise but complete

Data constraints:
- Only mention the revenue, quantity, and price changes shown in the data
- If details are missing, say so - don't invent information
- Focus on the actual products and channels affected"""

    else:  # Vietnamese (default)
        return """Bạn là Revenue AI, chuyên gia phân tích doanh thu.

Hướng dẫn chính:
- Trả lời trực tiếp - không cần chào lại
- Không hỏi ngược lại người dùng
- Không dùng từ mơ hồ như "có thể", "đáng kể", "thường là"
- Dùng số liệu cụ thể, không bịa ra
- Chỉ phân tích dữ liệu được cung cấp

Cách phân tích:
1. Xác định nguyên nhân chính (giảm số lượng hay giá)
2. Nêu yếu tố tác động lớn nhất (sản phẩm hay kênh)
3. Tính toán impact (chiếm bao nhiêu % tổng mất mát)
4. Đề xuất 1-2 hành động cụ thể dựa trên dữ liệu
5. Nêu rủi ro nếu không hành động

Phong cách trả lời:
- Tự nhiên và trực tiếp
- Dùng số liệu và phần trăm cụ thể
- Nêu tên sản phẩm, tên kênh, các con số
- Không lặp lại ý kiến
- Trả lời đầy đủ nhưng ngắn gọn

Ràng buộc dữ liệu:
- Chỉ đề cập đến doanh thu, số lượng, giá được cung cấp
- Nếu thiếu thông tin, nói rõ - không bịa thêm
- Tập trung vào sản phẩm và kênh thực tế trong dữ liệu"""


def build_data_context(sales_summary):
    """
    Format dữ liệu phân tích thành block dễ đọc cho Gemini.
    
    Args:
        sales_summary: dict từ analyzer.get_sales_summary()
    
    Returns:
        str: Formatted data block
    """
    return f"""
[DATA FROM sales.csv - NO RECALCULATION]
Current month: {sales_summary['current_month']}
Previous month: {sales_summary['previous_month']}

REVENUE:
- This month: {sales_summary['current_revenue']:,.0f} VND
- Previous month: {sales_summary['previous_revenue']:,.0f} VND
- Change: {sales_summary['revenue_change_pct']:+.1f}%

SALES QUANTITY:
- This month: {sales_summary['current_quantity']:,} units
- Previous month: {sales_summary['previous_quantity']:,} units
- Change: {sales_summary['quantity_change_pct']:+.1f}%

AVERAGE PRICE:
- This month: {sales_summary['current_avg_price']:,.0f} VND/unit
- Previous month: {sales_summary['previous_avg_price']:,.0f} VND/unit
- Change: {sales_summary['price_change_pct']:+.1f}%

ROOT CAUSE ANALYSIS:
- Main cause: {sales_summary['dominant_factor']}
- Sản phẩm gặp khó nhất: {sales_summary['worst_product_name']} ({sales_summary['worst_product_change_pct']:+.1f}%)
- Kênh bán gặp khó nhất: {sales_summary['worst_channel_name']} ({sales_summary['worst_channel_change_pct']:+.1f}%)
[HẾT DỮ LIỆU]"""


def build_user_prompt(user_question, chat_history=None, sales_summary=None):
    """
    Build structured user prompt for Gemini API call.
    
    Args:
        user_question: str - câu hỏi của user
        chat_history: list - lịch sử cuộc hội thoại (optional)
        sales_summary: dict - analysis data from analyze_data()
    
    Returns:
        str: Prompt to send to Gemini
    """
    prompt = ""
    
    # Phần 1: Ngữ cảnh (Chat history)
    if chat_history and len(chat_history) > 0:
        prompt += "Ngữ cảnh:\n"
        for msg in chat_history[-3:]:  # Last 3 messages only
            role = "User" if msg.get('role') == 'user' else "Assistant"
            text = msg.get('text', '')[:100]
            prompt += f"{role}: {text}\n"
        prompt += "\n"
    
    # Phần 2: Câu hỏi
    prompt += f"Câu hỏi:\n{user_question}\n\n"
    
    # Phần 3: Dữ liệu phân tích
    if sales_summary:
        prompt += "Dữ liệu phân tích:\n"
        prompt += f"Doanh thu tháng này: {sales_summary.get('current_revenue', 0):,.0f} đ ({sales_summary.get('revenue_change_pct', 0):+.1f}%)\n"
        prompt += f"Lượng bán: {sales_summary.get('current_quantity', 0):,} sản phẩm ({sales_summary.get('quantity_change_pct', 0):+.1f}%)\n"
        prompt += f"Giá bình quân: {sales_summary.get('current_avg_price', 0):,.0f} đ/sp ({sales_summary.get('price_change_pct', 0):+.1f}%)\n"
        prompt += f"Nguyên nhân chính: {sales_summary.get('dominant_factor', 'N/A')}\n"
        prompt += f"Sản phẩm kém nhất: {sales_summary.get('worst_product_name', 'N/A')} ({sales_summary.get('worst_product_change_pct', 0):+.1f}%)\n"
        prompt += f"Kênh bán kém nhất: {sales_summary.get('worst_channel_name', 'N/A')} ({sales_summary.get('worst_channel_change_pct', 0):+.1f}%)\n\n"
    
    # Phần 4: Yêu cầu
    prompt += """Yêu cầu:
- TRẢ LỜI TRỰC TIẾP (không chào lại)
- KHÔNG hỏi ngược lại user
- KHÔNG nói chung chung
- PHẢI có số liệu cụ thể
- PHẢI giải thích nguyên nhân rõ ràng

Nếu hỏi "Doanh thu":
→ trả số + %

Nếu hỏi "Nguyên nhân":
→ dùng quantity / product / channel

Nếu hỏi "Sản phẩm":
→ nêu tên + %

Nếu hỏi "Kênh":
→ nêu kênh + %

Nếu hỏi "Giải pháp":
→ phải liên quan trực tiếp đến data"""
    
    return prompt


# ════════════════════════════════════════════════════════════════════════════
# Example usage
# ════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    # Test system prompt
    print("=" * 80)
    print("SYSTEM PROMPT:")
    print("=" * 80)
    print(build_system_prompt())
    
    # Test data context
    print("\n" + "=" * 80)
    print("DATA CONTEXT:")
    print("=" * 80)
    sample_data = {
        'current_month': '2024-03',
        'previous_month': '2024-02',
        'current_revenue': 93000000,
        'previous_revenue': 135000000,
        'revenue_change_pct': -31.2,
        'current_quantity': 12500,
        'previous_quantity': 18900,
        'quantity_change_pct': -33.8,
        'current_avg_price': 7440,
        'previous_avg_price': 7142,
        'price_change_pct': 4.2,
        'dominant_factor': 'quantity',
        'worst_product_name': 'Product A',
        'worst_product_change_pct': -45.3,
        'worst_channel_name': 'Direct',
        'worst_channel_change_pct': -38.5,
    }
    print(build_data_context(sample_data))
    
    # Test user prompt
    print("\n" + "=" * 80)
    print("USER PROMPT:")
    print("=" * 80)
    print(build_user_prompt("Phân tích lí do doanh thu giảm"))
