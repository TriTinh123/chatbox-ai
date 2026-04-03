# ════════════════════════════════════════════════════════════════════════════
#  recommendations.py — Gợi ý hành động kinh doanh
#  Chứa: build_recommendation() và QUICK_REPLIES
#  Đây là phần giúp dự án "ra chất business": trả lời "nên làm gì tiếp theo?"
# ════════════════════════════════════════════════════════════════════════════

from .insights import _section


def build_recommendation(d: dict) -> str:
    """
    Generate a 3-horizon action roadmap from aggregated analysis data.
    d = DataAnalyzer.recommendation() output dict.
    """
    dir_word = "giảm" if d["chg_pct"] < 0 else "tăng"
    color    = "#f87171" if d["chg_pct"] < 0 else "#4ade80"

    summary = (
        f'Doanh thu <span style="color:{color}">{dir_word} {abs(d["chg_pct"])}%</span>. '
        f'Sản phẩm tệ nhất: <strong>{d["worst_product"]}</strong> ({d["prod_chg"]}%). '
        f'Kênh tệ nhất: <strong>{d["worst_channel"]}</strong> ({d["ch_chg"]}%). '
        f'Nguyên nhân chính: <strong>'
        f'{"số lượng giảm" if d["dominant"] == "quantity" else "giá giảm" if d["dominant"] == "price" else "cả hai"}'
        f'</strong>.'
    )

    actions = (
        f'<ul style="margin-top:8px;">'
        f'<li>⚡ <strong>Ngắn hạn (0–4 tuần):</strong> Chạy flash sale cho '
        f'<strong>{d["worst_product"]}</strong>, tăng ngân sách cho kênh đang tốt nhất.</li>'
        f'<li>📈 <strong>Trung hạn (1–3 tháng):</strong> Đào tạo lại đội ngũ kênh '
        f'<strong>{d["worst_channel"]}</strong>, A/B test chương trình khuyến mãi mới.</li>'
        f'<li>🚀 <strong>Dài hạn (3–6 tháng):</strong> Xây dựng loyalty program, '
        f'mở rộng sản phẩm thay thế cho <strong>{d["worst_product"]}</strong>.</li>'
        f'</ul>'
    )

    kpis = (
        f'Theo dõi hàng tuần: '
        f'<span style="color:#a78bfa">Conversion Rate</span> · '
        f'<span style="color:#a78bfa">Churn Rate</span> · '
        f'<span style="color:#a78bfa">Revenue per Channel</span> · '
        f'<span style="color:#a78bfa">Avg Order Value</span>'
    )

    return (
        f'<div class="tag">🛠️ Khuyến nghị hành động</div>'
        + _section("📊", "Tóm tắt tình hình", summary)
        + _section("📋", "Lộ trình hành động", actions)
        + _section("📌", "KPI cần theo dõi", kpis)
    )


# Context-aware follow-up suggestions shown after each bot response.
# Key = intent just answered.  Value = list of next suggested questions.
QUICK_REPLIES = {
    "forecast":          [
        "📉 Xem tổng quan doanh thu",
        "📦 Sản phẩm nào giảm mạnh nhất?",
        "🛠️ Nên làm gì để khắc phục?",
    ],
    "overview_revenue":  [
        "📦 Sản phẩm nào giảm mạnh nhất?",
        "📣 Kênh nào kém nhất?",
        "🔍 Giảm do số lượng hay giá?",
    ],
    "worst_product":     [
        "📣 Kênh nào kém nhất?",
        "🔍 Giảm do số lượng hay giá?",
        "🛠️ Nên làm gì để khắc phục?",
    ],
    "worst_channel":     [
        "📦 Sản phẩm nào giảm mạnh nhất?",
        "🔍 Giảm do số lượng hay giá?",
        "🛠️ Nên làm gì để khắc phục?",
    ],
    "quantity_or_price": [
        "📦 Sản phẩm nào giảm mạnh nhất?",
        "📣 Kênh nào kém nhất?",
        "🛠️ Nên làm gì để khắc phục?",
    ],
    "worst_region":      [
        "📦 Sản phẩm nào giảm mạnh nhất?",
        "🔍 Giảm do số lượng hay giá?",
        "🛠️ Nên làm gì để khắc phục?",
    ],
    "recommendation":    [
        "📉 Xem lại tổng quan doanh thu",
        "📦 Sản phẩm nào giảm mạnh nhất?",
        "🔍 Giảm do số lượng hay giá?",
    ],
    "default":           [
        "📉 Doanh thu tháng này giảm bao nhiêu?",
        "📦 Sản phẩm nào giảm mạnh nhất?",
        "📣 Kênh nào kém nhất?",
        "🔍 Giảm do số lượng hay giá?",
    ],
}
