# ════════════════════════════════════════════════════════════════════════════
#  insights.py — AI Explainability Engine
#  Biến số liệu từ analysis.py thành ngôn ngữ business dễ hiểu.
#  Chứa: _bar(), _section(), _expand_btn() và các hàm build_*
# ════════════════════════════════════════════════════════════════════════════


def build_greeting() -> str:
    """Simple greeting response."""
    return (
        '<div style="line-height:1.8; font-size:14px;">'
        'Chào bạn! 👋 Tôi là <strong>Revenue AI</strong>, chuyên gia phân tích doanh thu. '
        'Tôi có thể giúp bạn:<br><br>'
        '<strong>📊 Phân tích chi tiết:</strong> Tại sao doanh thu giảm? Sản phẩm nào bị ảnh hưởng?<br>'
        '<strong>📈 Dự báo:</strong> Doanh thu tháng tới sẽ ra sao?<br>'
        '<strong>🛠️ Khuyến nghị:</strong> Nên làm gì để khắc phục?<br><br>'
        'Hãy <strong>upload file CSV</strong> để bắt đầu phân tích, hoặc hỏi tôi bất cứ điều gì! 💡'
        '</div>'
    )


def _expand_btn(title: str, chart_html: str) -> str:
    """Bọc biểu đồ trong div có thể click để mở full-screen modal."""
    safe_title = title.replace('"', '&quot;')
    return (
        f'<div class="bar-chart-expandable" data-chart-title="{safe_title}">'
        f'{chart_html}'
        f'<div class="expand-hint">🔍 Click để xem to hơn</div>'
        f'</div>'
    )


def _bar(label: str, pct: float, is_worst: bool = False) -> str:
    """Render a single horizontal bar-chart row as HTML."""
    fill  = max(4, min(100, 100 + pct))
    color = "#f87171" if pct < -20 else ("#fbbf24" if pct < 0 else "#4ade80")
    sign  = "+" if pct >= 0 else ""
    warn  = "⚠️ " if is_worst else ""
    return (
        f'<div class="bar-row">'
        f'<span class="bar-label">{warn}{label}</span>'
        f'<div class="bar-track">'
        f'<div class="bar-fill" style="width:{fill}%;background:{color}"></div>'
        f'</div>'
        f'<span class="bar-pct" style="color:{color}">{sign}{pct}%</span>'
        f'</div>'
    )


def _section(icon: str, title: str, body: str) -> str:
    """Wrap content in a labeled section block."""
    return (
        f'<div style="margin-top:10px;">'
        f'<div style="font-size:11px;color:#a78bfa;font-weight:700;'
        f'text-transform:uppercase;letter-spacing:.6px;margin-bottom:5px;">'
        f'{icon} {title}</div>'
        f'{body}'
        f'</div>'
    )


# ── Response builders ────────────────────────────────────────────────────────
# Each function receives a data dict/list from DataAnalyzer and returns
# structured HTML with labelled sections.

def build_overview_revenue(d: dict) -> str:
    color    = "#4ade80" if d["chg_pct"] >= 0 else "#f87171"
    sign     = "+" if d["chg_pct"] >= 0 else ""
    qsign    = "+" if d["qty_chg"]  >= 0 else ""
    dir_word = "tăng" if d["chg_pct"] >= 0 else "giảm"

    result = (
        f'<div class="metric-expandable" data-chart-title="📊 Tổng quan doanh thu">'
        f'<div class="metrics-grid">'
        f'<div class="metric-card">'
        f'<span class="metric-label">Doanh thu {d["cur_month"]}</span>'
        f'<span class="metric-value" style="color:{color}">{d["cur_rev"]}</span>'
        f'<span class="metric-change">{sign}{d["chg_pct"]}% so tháng trước</span>'
        f'</div>'
        f'<div class="metric-card">'
        f'<span class="metric-label">Doanh thu {d["prev_month"]}</span>'
        f'<span class="metric-value" style="color:#94a3b8">{d["prev_rev"]}</span>'
        f'<span class="metric-change">Tháng so sánh</span>'
        f'</div>'
        f'<div class="metric-card">'
        f'<span class="metric-label">Sản lượng {d["cur_month"]}</span>'
        f'<span class="metric-value" style="color:{color}">{d["cur_qty"]}</span>'
        f'<span class="metric-change">{qsign}{d["qty_chg"]}% so tháng trước</span>'
        f'</div>'
        f'<div class="metric-card">'
        f'<span class="metric-label">Sản lượng {d["prev_month"]}</span>'
        f'<span class="metric-value" style="color:#94a3b8">{d["prev_qty"]}</span>'
        f'<span class="metric-change">Tháng so sánh</span>'
        f'</div>'
        f'</div>'
        f'<div class="expand-hint">🔍 Click để xem to hơn</div>'
        f'</div>'
    )

    cause = (
        f'Doanh thu tháng <strong>{d["cur_month"]}</strong> '
        f'<span style="color:{color}">{dir_word} {abs(d["chg_pct"])}%</span> '
        f'và sản lượng {dir_word} {abs(d["qty_chg"])}% — '
        f'cả hai chỉ số đều '
        f'{"sụt giảm đồng thời." if d["chg_pct"] < 0 else "cải thiện tích cực."}'
    )

    tip = (
        "Bấm vào gợi ý bên dưới để xem sản phẩm & kênh nào chịu trách nhiệm chính."
        if d["chg_pct"] < 0
        else "Tiếp tục duy trì chiến lược hiện tại và mở rộng sang kênh mới."
    )

    return (
        f'<div class="tag">📉 Tổng quan doanh thu</div>'
        + _section("📊", "Kết quả", result)
        + _section("🔍", "Nhận xét", cause)
        + _section("💡", "Gợi ý tiếp theo", tip)
    )


def build_worst_product(items: list) -> str:
    worst = items[0]
    bars  = "".join(_bar(x["product"], x["chg_pct"], i == 0) for i, x in enumerate(items))

    cause = (
        f'<strong>{worst["product"]}</strong> là sản phẩm giảm mạnh nhất: '
        f'<span class="danger">{worst["chg_pct"]}%</span> '
        f'({worst["prev_rev"]} → {worst["cur_rev"]}). '
        f'Có thể do mất nhu cầu thị trường, đối thủ tung sản phẩm thay thế, '
        f'hoặc tồn kho cao từ tháng trước.'
    )

    tip = (
        f'Ưu tiên kiểm tra lại chiến dịch cho <strong>{worst["product"]}</strong>: '
        f'xem lại giá, chương trình khuyến mãi, và phản hồi khách hàng.'
    )

    chart_html = f'<div class="bar-chart">{bars}</div>'
    return (
        f'<div class="tag">📦 Phân tích theo sản phẩm</div>'
        + _section("📊", "Kết quả", _expand_btn("📦 Sản phẩm theo doanh thu", chart_html))
        + _section("🔍", "Nguyên nhân chính", cause)
        + _section("💡", "Khuyến nghị", tip)
    )


def build_worst_channel(items: list) -> str:
    worst = items[0]
    bars  = "".join(_bar(x["channel"], x["chg_pct"], i == 0) for i, x in enumerate(items))

    cause = (
        f'Kênh <strong>{worst["channel"]}</strong> kém nhất: '
        f'<span class="danger">{worst["chg_pct"]}%</span> '
        f'({worst["prev_rev"]} → {worst["cur_rev"]}). '
        f'Nguyên nhân thường gặp: ít đầu tư ngân sách, thiếu nhân sự, '
        f'hoặc kênh không còn phù hợp với hành vi mua của khách hàng.'
    )

    tip = (
        f'Xem xét tái phân bổ ngân sách từ kênh <strong>{worst["channel"]}</strong> '
        f'sang kênh đang tăng trưởng. '
        f'Nếu kênh này chiến lược, cần có kế hoạch phục hồi 90 ngày.'
    )

    chart_html = f'<div class="bar-chart">{bars}</div>'
    return (
        f'<div class="tag">📣 Phân tích theo kênh bán</div>'
        + _section("📊", "Kết quả", _expand_btn("📣 Kênh bán theo doanh thu", chart_html))
        + _section("🔍", "Nguyên nhân chính", cause)
        + _section("💡", "Khuyến nghị", tip)
    )


def build_quantity_or_price(d: dict) -> str:
    label_map = {
        "quantity": ("📦 Số lượng bán giảm là nguyên nhân chính", "#f87171"),
        "price":    ("🏷️ Giá bán giảm là nguyên nhân chính",      "#fbbf24"),
        "both":     ("⚠️ Cả số lượng lẫn giá đều giảm",           "#f87171"),
    }
    label, color = label_map[d["dominant"]]

    if d["dominant"] == "quantity":
        explain = (
            f'Số lượng giảm <span class="danger">{d["qty_chg"]}%</span> '
            f'({d["prev_qty"]} → {d["cur_qty"]} sản phẩm) trong khi giá chỉ thay đổi '
            f'<span style="color:#fbbf24">{d["price_chg"]}%</span>. '
            f'Điều này cho thấy <strong>nhu cầu giảm</strong> chứ không phải do định giá sai.'
        )
        tip = (
            "Tập trung vào <strong>kích cầu</strong>: chạy khuyến mãi, "
            "tăng hoạt động marketing, mở rộng tệp khách hàng mới."
        )
    elif d["dominant"] == "price":
        explain = (
            f'Giá bán trung bình giảm <span class="danger">{d["price_chg"]}%</span> '
            f'({d["prev_price"]} → {d["cur_price"]}) trong khi sản lượng thay đổi '
            f'<span style="color:#fbbf24">{d["qty_chg"]}%</span>. '
            f'Điều này cho thấy <strong>áp lực giá từ cạnh tranh</strong> hoặc chiết khấu quá nhiều.'
        )
        tip = (
            "Xem lại chính sách giá. Thay vì giảm giá, hãy tăng "
            "<strong>giá trị cảm nhận</strong> (bundle, bảo hành, dịch vụ kèm theo)."
        )
    else:
        explain = (
            f'Cả số lượng (<span class="danger">{d["qty_chg"]}%</span>) lẫn giá '
            f'(<span class="danger">{d["price_chg"]}%</span>) đều giảm — '
            f'đây là dấu hiệu của <strong>sụt giảm toàn diện</strong>, cần hành động ngay.'
        )
        tip = (
            "Đây là trường hợp nghiêm trọng. Cần kiểm tra toàn bộ funnel: "
            "từ marketing đến sản phẩm, giá cả và dịch vụ."
        )

    grid_html = (
        f'<div class="metrics-grid">'
        f'<div class="metric-card">'
        f'<span class="metric-label">Thay đổi số lượng</span>'
        f'<span class="metric-value" style="color:#f87171">{d["qty_chg"]}%</span>'
        f'<span class="metric-change">{d["prev_qty"]} → {d["cur_qty"]} sp</span>'
        f'</div>'
        f'<div class="metric-card">'
        f'<span class="metric-label">Thay đổi giá TB</span>'
        f'<span class="metric-value" style="color:#fbbf24">{d["price_chg"]}%</span>'
        f'<span class="metric-change">{d["prev_price"]} → {d["cur_price"]}</span>'
        f'</div>'
        f'</div>'
    )
    result = (
        f'<div class="metric-expandable" data-chart-title="📊 Số liệu chi tiết">'
        f'{grid_html}'
        f'<div class="expand-hint">🔍 Click để xem to hơn</div>'
        f'</div>'
    )

    return (
        f'<div class="tag">🔍 Nguyên nhân sụt giảm</div>'
        f'<strong style="color:{color}">{label}</strong>'
        + _section("📊", "Số liệu", result)
        + _section("💬", "Giải thích", explain)
        + _section("💡", "Khuyến nghị", tip)
    )


def build_worst_region(items: list) -> str:
    worst = items[0]
    bars  = "".join(_bar(x["region"], x["chg_pct"], i == 0) for i, x in enumerate(items))

    cause = (
        f'Khu vực <strong>{worst["region"]}</strong> giảm mạnh nhất: '
        f'<span class="danger">{worst["chg_pct"]}%</span> '
        f'(còn {worst["cur_rev"]}). '
        f'Nguyên nhân tiềm năng: năng lực đội ngũ địa phương, '
        f'điều kiện thị trường khu vực, '
        f'hoặc sự cạnh tranh mạnh từ đối thủ tại địa bàn.'
    )

    tip = (
        f'Đánh giá lại năng lực và nguồn lực tại <strong>{worst["region"]}</strong>. '
        f'Xem liệu đây là vấn đề thực thi hay vấn đề thị trường.'
    )

    chart_html = f'<div class="bar-chart">{bars}</div>'
    return (
        f'<div class="tag">🗺️ Phân tích theo khu vực</div>'
        + _section("📊", "Kết quả", _expand_btn("🗺️ Khu vực theo doanh thu", chart_html))
        + _section("🔍", "Nguyên nhân chính", cause)
        + _section("💡", "Khuyến nghị", tip)
    )


def build_forecast(d: dict) -> str:
    """
    Hiển thị kết quả dự báo doanh thu từ Linear Regression model.
    d = RevenueForecaster.predict_next()
    """
    # ── History bar chart ────────────────────────────────────────────────────
    max_rev = max(h["revenue"] for h in d["history"]) or 1
    history_bars = ""
    for h in d["history"]:
        pct   = round(h["revenue"] / max_rev * 100, 1)
        color = "#4ade80" if h["revenue"] == max_rev else "#a78bfa"
        history_bars += (
            f'<div class="bar-row">'
            f'<span class="bar-label">{h["month"]}</span>'
            f'<div class="bar-track">'
            f'<div class="bar-fill" style="width:{pct}%;background:{color}"></div>'
            f'</div>'
            f'<span class="bar-pct" style="color:{color}">'
            f'{round(h["revenue"]/1e9, 2)} tỷ</span>'
            f'</div>'
        )

    # ── Predicted bar ────────────────────────────────────────────────────────
    if d["unreliable"]:
        pred_color   = "#fbbf24"
        pred_display = "⚠️ Xu hướng tiếp tục giảm"
        pred_bar_pct = 5
    else:
        pred_color   = "#60a5fa" if d["predicted_rev"] > d["last_rev"] else "#f87171"
        pred_display = f'{round(d["predicted_rev"]/1e9, 2)} tỷ đồng'
        pred_bar_pct = max(4, min(100, round(d["predicted_rev"] / max_rev * 100, 1)))

    history_bars += (
        f'<div class="bar-row" style="border-top:1px dashed #4b5563;margin-top:6px;padding-top:6px;">'
        f'<span class="bar-label">📍 {d["next_month"]} (dự báo)</span>'
        f'<div class="bar-track">'
        f'<div class="bar-fill" style="width:{pred_bar_pct}%;background:{pred_color};opacity:0.7;'
        f'background-image:repeating-linear-gradient(45deg,transparent,transparent 4px,'
        f'rgba(255,255,255,.15) 4px,rgba(255,255,255,.15) 8px)"></div>'
        f'</div>'
        f'<span class="bar-pct" style="color:{pred_color}">{pred_display}</span>'
        f'</div>'
    )

    # ── Model info card ──────────────────────────────────────────────────────
    model_info = (
        f'<div class="metric-expandable" data-chart-title="🤖 Thông số mô hình AI">'
        f'<div class="metrics-grid">'
        f'<div class="metric-card">'
        f'<span class="metric-label">Mô hình AI</span>'
        f'<span class="metric-value" style="color:#a78bfa;font-size:14px;">Linear Regression</span>'
        f'<span class="metric-change">scikit-learn 1.8</span>'
        f'</div>'
        f'<div class="metric-card">'
        f'<span class="metric-label">R² Score</span>'
        f'<span class="metric-value" style="color:#4ade80">{d["r2"]}</span>'
        f'<span class="metric-change">Độ khớp mô hình</span>'
        f'</div>'
        f'<div class="metric-card">'
        f'<span class="metric-label">Dữ liệu train</span>'
        f'<span class="metric-value" style="color:#60a5fa">{d["n_months"]} tháng</span>'
        f'<span class="metric-change">sales.csv thực tế</span>'
        f'</div>'
        f'<div class="metric-card">'
        f'<span class="metric-label">Độ tin cậy</span>'
        f'<span class="metric-value" style="color:#fbbf24;font-size:13px;">{d["confidence"]}</span>'
        f'<span class="metric-change">Dựa trên R²</span>'
        f'</div>'
        f'</div>'
        f'<div class="expand-hint">🔍 Click để xem to hơn</div>'
        f'</div>'
    )

    # ── Explanation & Tip ────────────────────────────────────────────────────
    if d["unreliable"]:
        explain = (
            f'Mô hình dự báo xu hướng <strong style="color:#f87171">tiếp tục giảm</strong> '
            f'dựa trên đà giảm tháng 3. '
            f'Tuy nhiên với chỉ <strong>{d["n_months"]} tháng</strong> dữ liệu, '
            f'độ tin cậy chưa cao — cần ít nhất <strong>6 tháng</strong> để dự báo chính xác.'
        )
        tip = (
            "Hành động ngay để ngăn xu hướng giảm: tập trung kích cầu tháng 4, "
            "đồng thời thu thập thêm dữ liệu để cải thiện độ chính xác dự báo."
        )
    else:
        sign = "+" if d["chg_pct"] >= 0 else ""
        explain = (
            f'Linear Regression dự báo tháng <strong>{d["next_month"]}</strong> '
            f'sẽ <strong style="color:{pred_color}">{d["trend"]} {sign}{d["chg_pct"]}%</strong> '
            f'so với tháng trước. '
            f'Mô hình train trên {d["n_months"]} tháng dữ liệu thực từ sales.csv, R² = {d["r2"]}.'
        )
        tip = (
            f'Điều chỉnh kế hoạch bán hàng tháng <strong>{d["next_month"]}</strong> '
            f'dựa trên dự báo này để chủ động ứng phó.'
        )

    forecast_chart = f'<div class="bar-chart">{history_bars}</div>'
    return (
        f'<div class="tag">🤖 Dự báo doanh thu — Linear Regression</div>'
        + _section("📊", "Kết quả & Dự báo", _expand_btn("🤖 Dự báo — Linear Regression", forecast_chart))
        + _section("🧠", "Thông số mô hình AI", model_info)
        + _section("💬", "Giải thích", explain)
        + _section("💡", "Khuyến nghị", tip)
    )
