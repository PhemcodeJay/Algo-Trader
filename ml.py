import os
import numpy as np
import pandas as pd
import joblib
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from dotenv import load_dotenv

load_dotenv()

from db import db  # Your SQLAlchemy DatabaseManager

MODEL_PATH = "ml_models/profit_xgb_model.pkl"


class MLFilter:
    def __init__(self):
        self.model = self._load_model()
        self.db = db

    def _load_model(self):
        if os.path.exists(MODEL_PATH):
            print("[ML] ✅ Loaded trained model.")
            return joblib.load(MODEL_PATH)
        else:
            print("[ML] ⚠️ No trained model found. Using fallback scoring.")
            return None

    def extract_features(self, signal: dict) -> np.ndarray:
        return np.array([
            signal.get("entry", 0),
            signal.get("tp", 0),
            signal.get("sl", 0),
            signal.get("trail", 0),
            signal.get("score", 0),
            signal.get("confidence", 0),
            1 if signal.get("side") == "LONG" else 0,
            1 if signal.get("trend") == "Up" else -1 if signal.get("trend") == "Down" else 0,
            1 if signal.get("regime") == "Breakout" else 0,
        ])

    def enhance_signal(self, signal: dict) -> dict:
        if self.model:
            features = self.extract_features(signal).reshape(1, -1)
            prob = self.model.predict_proba(features)[0][1]
            signal["score"] = round(prob * 100, 2)
            signal["confidence"] = int(min(signal["score"] + np.random.uniform(0, 10), 100))
        else:
            signal["score"] = signal.get("score", np.random.uniform(55, 70))
            signal["confidence"] = int(min(signal["score"] + np.random.uniform(5, 20), 100))

        try:
            entry_price = float(signal.get("entry", 0))
            leverage = int(signal.get("leverage", 20))
            capital = float(signal.get("capital", 100))

            if entry_price > 0 and leverage > 0:
                margin = capital / leverage
                signal["margin_usdt"] = round(margin, 2)
            else:
                signal["margin_usdt"] = None
        except (ValueError, TypeError):
            signal["margin_usdt"] = None

        return signal

    def load_data_from_db(self, limit=1000) -> list:
        combined = []

        trades = self.db.get_trades(limit=limit)
        for trade in trades:
            t = trade.to_dict()
            if t.get("entry") is not None and t.get("exit") is not None:
                direction = 1 if t["side"] == "LONG" else -1
                profit = 1 if direction * (t["exit"] - t["entry"]) > 0 else 0

                combined.append({
                    "entry": t["entry"],
                    "tp": t.get("tp", 0),
                    "sl": t.get("sl", 0),
                    "trail": t.get("trail", 0),
                    "score": t.get("score", 60),
                    "confidence": t.get("confidence", 60),
                    "side": t.get("side", "LONG"),
                    "trend": t.get("trend", "Neutral"),
                    "regime": t.get("regime", "Breakout"),
                    "profit": profit,
                })

        signals = self.db.get_signals(limit=limit)
        for sig in signals:
            s = sig.to_dict()
            indicators = s.get("indicators", {}) or {}
            combined.append({
                "entry": s.get("entry") or indicators.get("entry", 0),
                "tp": s.get("tp") or indicators.get("tp", 0),
                "sl": s.get("sl") or indicators.get("sl", 0),
                "trail": s.get("trail", 0),
                "score": s.get("score", 60),
                "confidence": s.get("confidence", 60),
                "side": s.get("side", "LONG"),
                "trend": s.get("trend", "Neutral"),
                "regime": s.get("regime", "Breakout"),
                "profit": 1 if s.get("score", 0) > 70 else 0,
            })

        print(f"[ML] ✅ Loaded {len(combined)} total training records from DB.")
        return combined

    def train_from_db(self):
        all_data = self.load_data_from_db()
        df = pd.DataFrame(all_data)

        if df.empty or len(df) < 30:
            print(f"[ML] ❌ Not enough data to train. Found only {len(df)} rows.")
            return

        df["side_enc"] = df["side"].map({"LONG": 1, "SHORT": 0}).fillna(0)
        df["trend_enc"] = df["trend"].map({"Up": 1, "Down": -1, "Neutral": 0}).fillna(0)
        df["regime_enc"] = df["regime"].map({"Breakout": 1, "Mean": 0}).fillna(0)

        X = df[["entry", "tp", "sl", "trail", "score", "confidence", "side_enc", "trend_enc", "regime_enc"]]
        y = df["profit"]

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        model = XGBClassifier(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            use_label_encoder=False,
            base_score=0.5,
            eval_metric="logloss"
        )
        model.fit(X_train, y_train)

        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        joblib.dump(model, MODEL_PATH)
        self.model = model

        acc = model.score(X_test, y_test)
        print(f"[ML] ✅ Trained model on {len(df)} records. Accuracy: {acc:.2%}")
        model = XGBClassifier(use_label_encoder=False, eval_metric='logloss')  # You can adjust eval_metric as needed
        model.fit(X_train, y_train)

# === CLI Entrypoint ===
if __name__ == "__main__":
    ml = MLFilter()
    ml.train_from_db()
