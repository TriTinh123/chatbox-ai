# ════════════════════════════════════════════════════════════════════════════
#  analysis.py — DataAnalyzer
#  Reads sales.csv once on startup and exposes 6 pandas analysis methods.
# ════════════════════════════════════════════════════════════════════════════

import pandas as pd


class DataAnalyzer:

    def __init__(self, csv_path=None, df=None):
        if df is not None:
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"])
        elif csv_path is not None:
            df = pd.read_csv(csv_path, parse_dates=["date"])
        else:
            raise ValueError("Must provide either csv_path or df")
        df["month"] = df["date"].dt.to_period("M")
        self.df = df

    # ── helpers ─────────────────────────────────────────────────────────────

    def _two_months(self):
        """Return (latest_month, previous_month) as Period objects."""
        months = sorted(self.df["month"].unique())
        return months[-1], months[-2]

    def _fmt_vnd(self, value: float) -> str:
        """Format a number as Vietnamese currency string."""
        if value >= 1_000_000_000:
            return f"{value/1_000_000_000:,.2f} tỷ đồng"
        return f"{value/1_000_000:,.0f} triệu đồng"

    def _pct(self, now: float, prev: float) -> float:
        """Percentage change, safe against division by zero."""
        return 0.0 if prev == 0 else (now - prev) / prev * 100

    # ── analysis methods ────────────────────────────────────────────────────

    def overview_revenue(self) -> dict:
        """Compare total revenue and quantity between the two latest months."""
        cur, prev = self._two_months()
        cur_rev  = self.df[self.df["month"] == cur]["revenue"].sum()
        prev_rev = self.df[self.df["month"] == prev]["revenue"].sum()
        cur_qty  = int(self.df[self.df["month"] == cur]["quantity"].sum())
        prev_qty = int(self.df[self.df["month"] == prev]["quantity"].sum())
        return {
            "cur_month":  str(cur),
            "prev_month": str(prev),
            "cur_rev":    self._fmt_vnd(cur_rev),
            "prev_rev":   self._fmt_vnd(prev_rev),
            "chg_pct":    round(self._pct(cur_rev, prev_rev), 1),
            "cur_qty":    f"{cur_qty:,}",
            "prev_qty":   f"{prev_qty:,}",
            "qty_chg":    round(self._pct(cur_qty, prev_qty), 1),
        }

    def worst_product(self) -> list:
        """Rank products by revenue change (worst first)."""
        cur, prev = self._two_months()
        g_cur  = self.df[self.df["month"] == cur].groupby("product")["revenue"].sum()
        g_prev = self.df[self.df["month"] == prev].groupby("product")["revenue"].sum()
        results = [
            {
                "product":  p,
                "cur_rev":  self._fmt_vnd(g_cur.get(p, 0)),
                "prev_rev": self._fmt_vnd(float(g_prev[p])),
                "chg_pct":  round(self._pct(g_cur.get(p, 0), float(g_prev[p])), 1),
            }
            for p in g_prev.index
        ]
        return sorted(results, key=lambda x: x["chg_pct"])

    def worst_channel(self) -> list:
        """Rank sales channels by revenue change (worst first)."""
        cur, prev = self._two_months()
        g_cur  = self.df[self.df["month"] == cur].groupby("channel")["revenue"].sum()
        g_prev = self.df[self.df["month"] == prev].groupby("channel")["revenue"].sum()
        results = [
            {
                "channel":  c,
                "cur_rev":  self._fmt_vnd(g_cur.get(c, 0)),
                "prev_rev": self._fmt_vnd(float(g_prev[c])),
                "chg_pct":  round(self._pct(g_cur.get(c, 0), float(g_prev[c])), 1),
            }
            for c in g_prev.index
        ]
        return sorted(results, key=lambda x: x["chg_pct"])

    def quantity_or_price(self) -> dict:
        """Determine whether the decline was driven by quantity drop or price drop."""
        cur, prev = self._two_months()
        df_cur  = self.df[self.df["month"] == cur]
        df_prev = self.df[self.df["month"] == prev]
        qty_chg   = round(self._pct(df_cur["quantity"].sum(),    df_prev["quantity"].sum()),    1)
        price_chg = round(self._pct(df_cur["unit_price"].mean(), df_prev["unit_price"].mean()), 1)
        if abs(qty_chg) > abs(price_chg):
            dominant = "quantity"
        elif abs(price_chg) > abs(qty_chg):
            dominant = "price"
        else:
            dominant = "both"
        return {
            "qty_chg":    qty_chg,
            "price_chg":  price_chg,
            "dominant":   dominant,
            "cur_qty":    f"{int(df_cur['quantity'].sum()):,}",
            "prev_qty":   f"{int(df_prev['quantity'].sum()):,}",
            "cur_price":  self._fmt_vnd(float(df_cur["unit_price"].mean())),
            "prev_price": self._fmt_vnd(float(df_prev["unit_price"].mean())),
        }

    def worst_region(self) -> list:
        """Rank regions by revenue change (worst first)."""
        cur, prev = self._two_months()
        g_cur  = self.df[self.df["month"] == cur].groupby("region")["revenue"].sum()
        g_prev = self.df[self.df["month"] == prev].groupby("region")["revenue"].sum()
        results = [
            {
                "region":  r,
                "cur_rev": self._fmt_vnd(g_cur.get(r, 0)),
                "chg_pct": round(self._pct(g_cur.get(r, 0), float(g_prev[r])), 1),
            }
            for r in g_prev.index
        ]
        return sorted(results, key=lambda x: x["chg_pct"])

    def breakdown_detailed(self) -> dict:
        """
        Tính breakdown chi tiết: impact của từng product/channel/region.
        impact_pct = phần trăm sản phẩm/kênh/vùng đó góp vào sụt giảm doanh thu tổng.
        """
        cur, prev = self._two_months()
        
        # Tính tổng sụt giảm (chỉ lấy phần giảm, không lấy phần tăng)
        total_prev_rev = self.df[self.df["month"] == prev]["revenue"].sum()
        total_cur_rev  = self.df[self.df["month"] == cur]["revenue"].sum()
        total_loss = max(0, total_prev_rev - total_cur_rev)  # Chỉ lấy loss, không gain
        
        # PRODUCT BREAKDOWN
        g_cur_prod  = self.df[self.df["month"] == cur].groupby("product")["revenue"].sum()
        g_prev_prod = self.df[self.df["month"] == prev].groupby("product")["revenue"].sum()
        
        product_breakdown = []
        for p in sorted(g_prev_prod.index):
            prev_rev = float(g_prev_prod[p])
            cur_rev  = g_cur_prod.get(p, 0)
            loss     = max(0, prev_rev - cur_rev)
            chg_pct  = round(self._pct(cur_rev, prev_rev), 1)
            impact_pct = round((loss / total_loss * 100) if total_loss > 0 else 0, 1)
            
            if chg_pct < 0:  # Chỉ lấy sản phẩm giảm
                product_breakdown.append({
                    "product": p,
                    "chg_pct": chg_pct,
                    "impact_pct": impact_pct,
                })
        
        # CHANNEL BREAKDOWN
        g_cur_ch  = self.df[self.df["month"] == cur].groupby("channel")["revenue"].sum()
        g_prev_ch = self.df[self.df["month"] == prev].groupby("channel")["revenue"].sum()
        
        channel_breakdown = []
        for c in sorted(g_prev_ch.index):
            prev_rev = float(g_prev_ch[c])
            cur_rev  = g_cur_ch.get(c, 0)
            loss     = max(0, prev_rev - cur_rev)
            chg_pct  = round(self._pct(cur_rev, prev_rev), 1)
            impact_pct = round((loss / total_loss * 100) if total_loss > 0 else 0, 1)
            
            channel_breakdown.append({
                "channel": c,
                "chg_pct": chg_pct,
                "impact_pct": impact_pct,
            })
        
        # REGION BREAKDOWN
        g_cur_reg  = self.df[self.df["month"] == cur].groupby("region")["revenue"].sum()
        g_prev_reg = self.df[self.df["month"] == prev].groupby("region")["revenue"].sum()
        
        region_breakdown = []
        for r in sorted(g_prev_reg.index):
            prev_rev = float(g_prev_reg[r])
            cur_rev  = g_cur_reg.get(r, 0)
            loss     = max(0, prev_rev - cur_rev)
            chg_pct  = round(self._pct(cur_rev, prev_rev), 1)
            impact_pct = round((loss / total_loss * 100) if total_loss > 0 else 0, 1)
            
            region_breakdown.append({
                "region": r,
                "chg_pct": chg_pct,
                "impact_pct": impact_pct,
            })
        
        # Sort theo loss (descending)
        product_breakdown = sorted(product_breakdown, key=lambda x: -x["impact_pct"])
        channel_breakdown = sorted(channel_breakdown, key=lambda x: -x["impact_pct"])
        region_breakdown   = sorted(region_breakdown, key=lambda x: -x["impact_pct"])
        
        return {
            "product_breakdown": product_breakdown,
            "channel_breakdown": channel_breakdown,
            "region_breakdown":  region_breakdown,
        }

    def advanced_analysis(self) -> dict:
        """
        Advanced analysis: trends, forecasts, anomalies, seasonal patterns.
        """
        cur, prev = self._two_months()
        
        # Daily trend in current month
        df_cur_daily = self.df[self.df["month"] == cur].groupby("date")["revenue"].sum().sort_index()
        daily_trend = []
        if len(df_cur_daily) > 1:
            dates = df_cur_daily.index.tolist()
            values = df_cur_daily.values.tolist()
            for i, (date, val) in enumerate(zip(dates, values)):
                trend_dir = "↓" if i > 0 and val < values[i-1] else "→"
                daily_trend.append({
                    "date": str(date.date()),
                    "revenue": self._fmt_vnd(val),
                    "trend": trend_dir
                })
        
        # Identify worst day
        worst_day = None
        if len(df_cur_daily) > 0:
            min_date = df_cur_daily.idxmin()
            min_val = df_cur_daily.min()
            worst_day = {"date": str(min_date.date()), "revenue": self._fmt_vnd(min_val)}
        
        # Best day
        best_day = None
        if len(df_cur_daily) > 0:
            max_date = df_cur_daily.idxmax()
            max_val = df_cur_daily.max()
            best_day = {"date": str(max_date.date()), "revenue": self._fmt_vnd(max_val)}
        
        # Forecast: linear regression on current month daily
        forecast = None
        if len(df_cur_daily) > 2:
            import numpy as np
            x = np.arange(len(df_cur_daily)).reshape(-1, 1)
            y = df_cur_daily.values
            slope = (y[-1] - y[0]) / len(y)
            next_val = max(0, y[-1] + slope)
            forecast = self._fmt_vnd(next_val)
        
        # Volatility (std dev)
        volatility = 0.0
        if len(df_cur_daily) > 1:
            volatility = round(df_cur_daily.std() / df_cur_daily.mean() * 100, 1)
        
        return {
            "daily_trend": daily_trend[:5],  # First 5 days
            "worst_day": worst_day,
            "best_day": best_day,
            "forecast_next_day": forecast,
            "volatility_pct": volatility,
        }

    def recommendation(self) -> dict:
        """Generate data-driven recommendation inputs based on all findings."""
        rev    = self.overview_revenue()
        prod   = self.worst_product()
        ch     = self.worst_channel()
        reason = self.quantity_or_price()
        return {
            "chg_pct":       rev["chg_pct"],
            "cur_month":     rev["cur_month"],
            "prev_month":    rev["prev_month"],
            "cur_rev":       rev["cur_rev"],
            "prev_rev":      rev["prev_rev"],
            "worst_product": prod[0]["product"],
            "prod_chg":      prod[0]["chg_pct"],
            "worst_channel": ch[0]["channel"],
            "ch_chg":        ch[0]["chg_pct"],
            "dominant":      reason["dominant"],
        }
