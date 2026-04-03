# ════════════════════════════════════════════════════════════════════════════
#  forecasting.py — Mô hình Machine Learning dự báo doanh thu
#  Dùng: Linear Regression (scikit-learn) train trên dữ liệu tháng thật
#  Trả về: dự báo tháng tiếp theo + R² score + độ tin cậy
# ════════════════════════════════════════════════════════════════════════════

import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score, mean_absolute_error


class RevenueForecaster:
    """
    Train một Linear Regression model trên dữ liệu doanh thu theo tháng.
    X = chỉ số tháng (1, 2, 3, ...)
    y = tổng doanh thu tháng đó
    """

    def __init__(self, csv_path: str = None, df=None):
        if df is not None:
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"])
        elif csv_path is not None:
            df = pd.read_csv(csv_path, parse_dates=["date"])
        else:
            raise ValueError("Must provide either csv_path or df")
        df["month"] = df["date"].dt.to_period("M")

        # Tổng doanh thu theo tháng, sắp xếp tăng dần
        monthly = (
            df.groupby("month")["revenue"]
            .sum()
            .sort_index()
            .reset_index()
        )
        monthly["month_idx"] = range(1, len(monthly) + 1)

        self._monthly     = monthly
        self._model       = LinearRegression()
        self._is_trained  = False
        self._X           = None
        self._y           = None

    # ── Training ─────────────────────────────────────────────────────────────

    def train(self):
        """Train mô hình Linear Regression."""
        X = self._monthly[["month_idx"]].values   # shape (n, 1)
        y = self._monthly["revenue"].values        # shape (n,)

        self._model.fit(X, y)
        self._X          = X
        self._y          = y
        self._is_trained = True
        return self

    # ── Prediction ───────────────────────────────────────────────────────────

    def predict_next(self) -> dict:
        """
        Dự báo doanh thu tháng tiếp theo.
        Trả về dict với đầy đủ số liệu để hiển thị lên chatbot.
        """
        if not self._is_trained:
            self.train()

        months         = self._monthly
        last_idx       = int(months["month_idx"].iloc[-1])
        last_month     = months["month"].iloc[-1]
        next_month     = last_month + 1

        # Predict
        next_idx       = np.array([[last_idx + 1]])
        predicted_rev  = float(self._model.predict(next_idx)[0])

        # Model metrics
        y_pred_train   = self._model.predict(self._X)
        r2             = float(r2_score(self._y, y_pred_train))
        mae            = float(mean_absolute_error(self._y, y_pred_train))

        # Coefficient: hướng xu thế
        coef           = float(self._model.coef_[0])
        trend          = "tăng" if coef > 0 else "giảm"

        # Percent change vs last month
        last_rev       = float(months["revenue"].iloc[-1])
        chg_pct        = round((predicted_rev - last_rev) / last_rev * 100, 1) if last_rev else 0.0

        # Confidence label dựa trên R²
        if r2 >= 0.9:
            confidence = "Cao (R²≥0.9)"
        elif r2 >= 0.7:
            confidence = "Trung bình (R²≥0.7)"
        else:
            confidence = "Thấp — cần thêm dữ liệu"

        # All months history để vẽ chart
        history = [
            {
                "month": str(row["month"]),
                "revenue": float(row["revenue"]),
                "idx": int(row["month_idx"]),
            }
            for _, row in months.iterrows()
        ]

        return {
            "next_month":    str(next_month),
            "predicted_rev": predicted_rev,
            "last_month":    str(last_month),
            "last_rev":      last_rev,
            "chg_pct":       chg_pct,
            "trend":         trend,
            "r2":            round(r2, 3),
            "mae":           mae,
            "confidence":    confidence,
            "n_months":      len(months),
            "history":       history,
            "coef":          round(coef, 0),
            "unreliable":    predicted_rev < 0 or len(months) < 6,
        }
