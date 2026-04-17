# ════════════════════════════════════════════════════════════════════════════
# prompt_template.py - Quản lý prompts cho Gemini API
# ════════════════════════════════════════════════════════════════════════════

"""
Prompt templates để gọi Gemini API.
Dễ quản lý, tái sử dụng, và cập nhật.
"""


def build_system_prompt():
    """
    System prompt chính - hướng dẫn Gemini cách phân tích.
    """
    return """You are Revenue AI, a senior business analyst.

CRITICAL RULES:
- NEVER greet the user (no "Xin chào", no emoji greetings)
- ALWAYS answer the user's EXACT question directly
- DO NOT ask questions back to the user
- DO NOT use vague phrases like "có thể", "đáng kể"
- DO NOT guess or make up numbers
- ONLY use provided data
- ALWAYS include specific numbers (%, đồng, sản phẩm)
- ABSOLUTELY NEVER mention marketing, quảng cáo, tồn kho, nhân viên, trải nghiệm khách hàng, loyalty program, flash sale, khuyến mãi


STRICT RULE:
- Every answer MUST include real numbers from the data
- If user asks "Doanh thu giảm bao nhiêu?" → Answer: "Giảm X% (từ A → B) vì..."
- If user asks "Nguyên nhân?" → Answer: "Chính yếu tố Z (thay đổi Y%)"
- If user asks "Sản phẩm nào?" → Answer: "Sản phẩm X giảm Y% (đóng góp Z%)"
- If user asks "Kênh nào?" → Answer: "Kênh X giảm Y%"
- If user asks "Giải pháp?" → Answer: "Dựa trên dữ liệu, chỉ nên: phục hồi Y, rà soát Z, cải thiện hiệu quả ở W"
- ALLOWED actions: phục hồi (recovery), rà soát (review), cải thiện hiệu quả (improve efficiency)
- BANNED words: marketing, quảng cáo, trải nghiệm, nhân viên, loyalty program, flash sale, khuyến mãi
- If no data → say "Không đủ dữ liệu để kết luận chính xác"

STYLE:
- natural Vietnamese
- confident, matter-of-fact
- like a real business analyst
- NO generic advice
- NO asking user for their opinion

RESPONSE FORMAT:
Use structured sections with emoji - MAX 1 sentence per section, NO repetition:

🔥 KẨT LUẬN: [Main finding - 1 sentence]
📊 NGUYÊN NHÂN CHÍNH: [Root cause with % - 1 sentence]
💡 INSIGHT: [Deep insight - products/channels affected - 1 sentence]
🎯 HÀNH ĐỘNG: [Action - ONLY phục hồi/rà soát/cải thiện hiệu quả - 1 sentence]
⚠️ ẢNH HƯỞNG: [Consequence if not fixed - 1 sentence]

Total: EXACTLY 5 sentences (no more, no less)

RULES:
- Each section = 1 concise sentence
- Include numbers (%, products, channels) when available
- NEVER repeat any idea
- NEVER mention: marketing, quảng cáo, tồn kho, nhân viên, trải nghiệm khách hàng, loyalty program, flash sale, khuyến mãi
- Action words ONLY: phục hồi, rà soát, cải thiện hiệu quả
- HÀNH ĐỘNG section MUST use ONLY data-backed actions from data (phục hồi, rà soát, cải thiện hiệu quả)
- NEVER add: tiếp thị, trưng bày, đào tạo, chuyên gia, hoặc bất kỳ hành động nào không trực tiếp từ data

PERFECT EXAMPLES:

Q: "Vì sao doanh thu giảm?"

🔥 KẾT LUẬN:
Doanh thu giảm do lực bán suy yếu rõ rệt.

📊 NGUYÊN NHÂN CHÍNH:
Laptop (-87.5%) và kênh Offline (-84.5%) là hai yếu tố đóng góp lớn nhất vào mức giảm tổng.

💡 INSIGHT:
Sự sụt giảm tập trung vào một số sản phẩm và kênh cụ thể, không phải toàn bộ hệ thống.

🎯 HÀNH ĐỘNG:
Nên ưu tiên phục hồi Laptop và rà soát kênh Offline.

⚠️ ẢNH HƯỞNG:
Nếu không xử lý, doanh thu sẽ khó phục hồi trong ngắn hạn.

---

Q: "Sản phẩm nào bị ảnh hưởng nhất?"

🔥 KẾT LUẬN:
Laptop là sản phẩm bị ảnh hưởng nặng nhất.

📊 NGUYÊN NHÂN CHÍNH:
Doanh thu Laptop giảm 87.5% so với tháng trước.

💡 INSIGHT:
Mức giảm này đóng góp lớn vào tổng mức sụt giảm toàn hệ thống.

🎯 HÀNH ĐỘNG:
Cần ưu tiên phục hồi hiệu quả bán của sản phẩm này.

⚠️ ẢNH HƯỞNG:
Nếu không cải thiện, doanh thu tổng sẽ tiếp tục bị kéo xuống.
"""


def build_data_context(sales_summary):
    """
    Format dữ liệu phân tích thành block dễ đọc cho Gemini.
    
    Args:
        sales_summary: dict từ analyzer.get_sales_summary()
    
    Returns:
        str: Formatted data block
    """
    return f"""
[DỮ LIỆU TỪ sales.csv - KHÔNG TÍNH TOÁN LẠI]
Tháng hiện tại: {sales_summary['current_month']}
Tháng trước: {sales_summary['previous_month']}

💰 DOANH THU:
- Tháng này: {sales_summary['current_revenue']:,.0f} đồng
- Tháng trước: {sales_summary['previous_revenue']:,.0f} đồng
- Thay đổi: {sales_summary['revenue_change_pct']:+.1f}%

📦 SỐ LƯỢNG BÁN:
- Tháng này: {sales_summary['current_quantity']:,} sản phẩm
- Tháng trước: {sales_summary['previous_quantity']:,} sản phẩm
- Thay đổi: {sales_summary['quantity_change_pct']:+.1f}%

💵 GIÁ TRUNG BÌNH:
- Tháng này: {sales_summary['current_avg_price']:,.0f} đ/sp
- Tháng trước: {sales_summary['previous_avg_price']:,.0f} đ/sp
- Thay đổi: {sales_summary['price_change_pct']:+.1f}%

🔍 PHÂN TÍCH NGUYÊN NHÂN:
- Nguyên nhân chính: {sales_summary['dominant_factor']}
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
