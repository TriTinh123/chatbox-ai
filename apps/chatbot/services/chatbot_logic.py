# ════════════════════════════════════════════════════════════════════════════
#  chatbot_logic.py — Intent detection & context memory helpers
#  Contains: INTENT_PATTERNS, FOLLOWUP_MAP, detect_intent(), QUICK_REPLIES
# ════════════════════════════════════════════════════════════════════════════

import re

# Each entry: (intent_name, [regex_patterns]).  First match wins.
# IMPORTANT: More specific intents (recommendation, quantity_or_price) come
# BEFORE overview_revenue to avoid "cải thiện doanh thu" matching doanh-thu first.
INTENT_PATTERNS = [
    ("greeting", [
        r"^(xin chào|chào|xin chao|chao|hello|hi|hey|hola)[\s\?!]*$",
        r"xin (chào|chao)",
        r"^(chào|chao) (bạn|ban)",
        r"^xin$",
        r"^chao$",
        r"^(hello|hi|hey)$",  # FIXED: Added grouping to prevent "hi" in "this" from matching
    ]),
    ("detailed_analysis", [
        r"tại sao.*doanh thu",   r"tai sao.*doanh thu",
        r"tại sao.*giảm",        r"tai sao.*giam",
        r"lí do.*giảm",           r"li do.*giam",
        r"nguyên nhân.*doanh",   r"nguyen nhan.*doanh",
        r"phân tích.*tại sao",   r"phan tich.*tai sao",
        r"phân tích.*lí do",     r"phan tich.*li do",
        r"phân tích.*nguyên nhân", r"phan tich.*nguyen nhan",
        # English patterns - expanded for better coverage
        r"why.*revenue.*declin",
        r"reason.*revenue.*declin",
        r"reasons.*revenue.*declin",  # Added plural
        r"analyze.*reason.*declin",
        r"why.*revenue.*drop",
        r"cause.*revenue.*declin",
        r"why.*sales.*declin",
        r"analyze.*why.*revenue",
        r"what.*cause.*revenue.*declin",
        r"why.*revenue.*decrease",    # Added "decrease" without "d"
        r"reason.*revenue.*decrease", # Added "decrease" without "d"
        r"reasons.*why.*revenue",     # Added "reasons why revenue"
        r"why.*revenue.*decreased",   # Added past tense
        r"reason.*revenue.*decreased", # Added past tense
        r"what.*reason.*revenue.*declin", # More flexible word order
    ]),
    ("forecast", [
        r"dự báo",              r"du bao",
        r"dự đoán",             r"du doan",
        r"tháng (4|5|6|sau|tới|next)",
        r"thang (4|5|6|sau|toi|next)",
        r"forecast",
        r"predict",
        r"tương lai",           r"tuong lai",
        r"xu hướng",            r"xu huong",
        r"linear regression",
        r"next month.*revenue",
        r"trend",
        r"projection",
    ]),
    ("recommendation", [
        r"(nên|cần) làm gì",   r"nen lam gi",
        r"giải pháp",           r"giai phap",
        r"khắc phục",           r"khac phuc",
        r"gợi ý",               r"goi y",
        r"đề xuất",             r"de xuat",
        r"recommendation",
        r"cải thiện",           r"cai thien",
        r"fix",
        r"what should i do",
        r"how to improve",
        r"improve.*revenue",
        r"solution",
        r"should.*do",
    ]),
    ("top_products", [
        r"top\s*3.*sản phẩm",
        r"vẽ biểu đồ top\s*3.*sản phẩm",
        r"top\s*3.*product",
        r"top products",
        r"top 3 sản phẩm",
        r"top 3 product",
        r"sản phẩm (nào|gì).*(bán\s*)?tốt",  # "Sản phẩm nào bán tốt"
        r"san pham (nao|gi).*(ban\s*)?tot",   # Không dấu version
        r"bán tốt nhất",
        r"ban tot nhat",
        r"sản phẩm tốt",
        r"san pham tot",
        r"best selling",
        r"top selling",
        r"most popular",
        r"best.*product",
        r"products.*best",
        r"which.*product.*best",
        r"what.*product.*best",
    ]),
    ("worst_product", [
        r"sản phẩm",            r"san pham",
        r"mặt hàng",            r"mat hang",
        r"nhóm hàng",           r"nhom hang",
        r"hàng (nào|gì)",       r"hang nao",
        r"product",
        r"worst.*product",
        r"declined.*product",
        r"product.*decline",
        r"product.*decrease",
        r"product.*drop",
        r"product.*failed",
        r"product.*struggle",
    ]),
    ("worst_channel", [
        r"kênh",                r"kenh",
        r"channel",
        r"online",
        r"offline",
        r"đối tác",             r"doi tac",
        r"social",
        r"worst.*channel",
        r"channel.*decline",
        r"channel.*decrease",
        r"channel.*drop",
        r"channel.*failed",
        r"channel.*struggle",
    ]),
    ("quantity_or_price", [
        r"số lượng",            r"so luong",
        r"giá (bán|cả)?",       r"gia ban",
        r"quantity",
        r"price",
        r"nguyên nhân",         r"nguyen nhan",
        r"lý do",               r"ly do",
        r"is.*due to.*quantity",
        r"is.*due to.*price",
        r"price change",
        r"volume.*decrease",
        r"vì sao",              r"vi sao",
        r"tại sao",             r"tai sao",
        r"do (đâu|gì)",         r"do dau",
    ]),
    ("worst_region", [
        r"khu vực",             r"khu vuc",
        r"vùng",                r"vung",
        r"region",
        r"hcm|hồ chí minh|ho chi minh",
        r"hà nội|ha noi",
        r"đà nẵng|da nang",
        r"worst.*region",
        r"which.*region",
        r"miền (nam|bắc|trung)|mien (nam|bac|trung)",
        r"địa (bàn|phương)|dia ban",
    ]),
    ("overview_revenue", [
        r"total revenue",
        r"this month.*revenue",
        r"month.*revenue",
        r"how much.*decrease",
        r"summary",
        r"doanh thu",
        r"tổng quan",           r"tong quan",
        r"tháng (này|trước|gần nhất)|thang nay",
        r"giảm bao nhiêu",      r"giam bao nhieu",
        r"tăng bao nhiêu",      r"tang bao nhieu",
        r"overview",
        r"tổng (doanh|hợp)",
        # English patterns for basic revenue questions
        r"revenue.*decrease",
        r"revenue.*drop",
        r"revenue.*decline",
        r"sales.*decrease",
        r"sales.*drop",
        r"sales.*decline",
        r"how much.*revenue",
        r"revenue.*this month",
        r"revenue.*last month",
        r"revenue.*change",
        r"revenue.*comparison",
    ]),
]

# Short follow-up phrases resolved with session context.
FOLLOWUP_MAP = {
    r"(nên|cần) làm gì|nen lam gi|giải pháp|giai phap|khắc phục|khac phuc|gợi ý|goi y": "recommendation",
    r"(vì |do )?sản phẩm (nào|gì)|san pham nao":     "worst_product",
    r"kênh (nào|gì)|kenh nao":                        "worst_channel",
    r"^(vì sao|tại sao|do đâu|sao vậy|vi sao|tai sao)\??$": "__keep__",
}

# Contextual quick-reply suggestions shown after each bot response.
QUICK_REPLIES = {
    "greeting":          ["📉 Doanh thu tháng này so với tháng trước?", "📦 Sản phẩm nào giảm mạnh nhất?", "🔍 Tại sao doanh thu giảm?"],
    "forecast":          ["📉 Xem tổng quan doanh thu", "📦 Sản phẩm nào giảm mạnh nhất?", "🛠️ Nên làm gì để khắc phục?"],
    "overview_revenue":  ["📦 Sản phẩm nào giảm mạnh nhất?", "📣 Kênh nào kém nhất?",       "🔍 Giảm do số lượng hay giá?"],
    "worst_product":     ["📣 Kênh nào kém nhất?",            "🔍 Giảm do số lượng hay giá?", "🛠️ Nên làm gì để khắc phục?"],
    "worst_channel":     ["📦 Sản phẩm nào giảm mạnh nhất?",  "🔍 Giảm do số lượng hay giá?", "🛠️ Nên làm gì để khắc phục?"],
    "quantity_or_price": ["📦 Sản phẩm nào giảm mạnh nhất?",  "📣 Kênh nào kém nhất?",        "🛠️ Nên làm gì để khắc phục?"],
    "worst_region":      ["📦 Sản phẩm nào giảm mạnh nhất?",  "🔍 Giảm do số lượng hay giá?", "🛠️ Nên làm gì để khắc phục?"],
    "recommendation":    ["📉 Xem lại tổng quan doanh thu",    "📦 Sản phẩm nào giảm mạnh nhất?", "🔍 Giảm do số lượng hay giá?"],
    "default":           [
        "📉 Doanh thu tháng này giảm bao nhiêu?",
        "📦 Sản phẩm nào giảm mạnh nhất?",
        "📣 Kênh nào kém nhất?",
        "🔍 Giảm do số lượng hay giá?",
    ],
}


def detect_intent(text: str, last_intent: str | None) -> str:
    """
    Step 1: Try direct regex match against INTENT_PATTERNS.
    Step 2: Try FOLLOWUP_MAP using last_intent as context.
    Step 3: Fall back to 'default'.
    """
    t = text.lower().strip()

    for intent_name, patterns in INTENT_PATTERNS:
        for pat in patterns:
            if re.search(pat, t):
                return intent_name

    for pat, resolved_intent in FOLLOWUP_MAP.items():
        if re.search(pat, t):
            if resolved_intent == "__keep__":
                return last_intent or "default"
            return resolved_intent

    return "default"
