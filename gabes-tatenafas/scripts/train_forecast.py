"""
train_forecast.py — Real ML+DL hybrid pollution forecaster.

Builds an ensemble of:

    * XGBoost regressor (gradient-boosted trees, classical ML)
    * LSTM             (recurrent deep network)

and combines them via a weighted average whose α is chosen on a held-out
validation split by minimising RMSE.

Outputs
-------
    1. forecast_predictions  — 6h / 12h / 24h predictions for every zone
    2. forecast_metrics      — MAE, RMSE, MAPE, R², SMAPE per model

This is the "pro" variant of the PHP implementation in
`backend/lib/forecast_ml.php`. Both produce structurally identical rows,
so the rest of the codebase consumes either transparently.

Usage
-----
    python scripts/train_forecast.py
    python scripts/train_forecast.py --window 14 --horizon 24
"""
from __future__ import annotations
import argparse
import os
import datetime as dt
import numpy as np
import pandas as pd
import pymysql

from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

try:
    from xgboost import XGBRegressor
except ImportError as e:
    raise SystemExit("Install: pip install xgboost") from e
try:
    import tensorflow as tf
    from tensorflow.keras import layers, Model
except ImportError as e:
    raise SystemExit("Install: pip install tensorflow") from e


# ────────────────────────────────────────────────────────────────────────
#  Database helpers (read real + augmented data)
# ────────────────────────────────────────────────────────────────────────
def db():
    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASS", ""),
        database=os.getenv("DB_NAME", "gabes_tatenafas"),
        charset="utf8mb4",
    )


def load_full_series(zone_id: int, days: int = 60) -> pd.Series:
    with db() as cx, cx.cursor() as cur:
        cur.execute(
            "SELECT computed_at, score FROM risk_scores "
            "WHERE zone_id=%s AND computed_at >= NOW() - INTERVAL %s DAY",
            (zone_id, days),
        )
        real = pd.DataFrame(list(cur.fetchall()), columns=["ts", "score"])

        cur.execute(
            "SELECT synthetic_at, score FROM risk_scores_augmented "
            "WHERE zone_id=%s AND synthetic_at >= NOW() - INTERVAL %s DAY",
            (zone_id, days),
        )
        aug = pd.DataFrame(list(cur.fetchall()), columns=["ts", "score"])

    df = pd.concat([real, aug], ignore_index=True)
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
    return df


def list_zones():
    with db() as cx, cx.cursor() as cur:
        cur.execute("SELECT id, name FROM zones")
        return list(cur.fetchall())


# ────────────────────────────────────────────────────────────────────────
#  Feature engineering — lag features + temporal Fourier encoding
# ────────────────────────────────────────────────────────────────────────
def make_features(df: pd.DataFrame, n_lags: int = 7) -> pd.DataFrame:
    df = df.copy()
    for k in range(1, n_lags + 1):
        df[f"lag{k}"] = df["score"].shift(k)
    df["hour_sin"] = np.sin(2 * np.pi * df["ts"].dt.hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["ts"].dt.hour / 24)
    df["dow_sin"]  = np.sin(2 * np.pi * df["ts"].dt.dayofweek / 7)
    df["dow_cos"]  = np.cos(2 * np.pi * df["ts"].dt.dayofweek / 7)
    return df.dropna().reset_index(drop=True)


# ────────────────────────────────────────────────────────────────────────
#  LSTM model
# ────────────────────────────────────────────────────────────────────────
def build_lstm(input_steps: int) -> Model:
    inp = layers.Input(shape=(input_steps, 1))
    x = layers.LSTM(32, return_sequences=False)(inp)
    x = layers.Dense(16, activation="relu")(x)
    out = layers.Dense(1)(x)
    m = Model(inp, out)
    m.compile(optimizer=tf.keras.optimizers.Adam(5e-3), loss="mse")
    return m


def lstm_dataset(series: np.ndarray, window: int = 7):
    X, y = [], []
    for i in range(window, len(series)):
        X.append(series[i - window:i])
        y.append(series[i])
    return np.array(X)[..., None], np.array(y)


# ────────────────────────────────────────────────────────────────────────
#  Metrics + persistence
# ────────────────────────────────────────────────────────────────────────
def smape(y_true, y_pred) -> float:
    return float(np.mean(np.abs(y_true - y_pred) /
                          np.maximum(1e-6, (np.abs(y_true) + np.abs(y_pred)) / 2))) * 100


def mape(y_true, y_pred) -> float:
    mask = y_true != 0
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask]))) * 100


def save_metrics(zone_id, model_name, y_true, y_pred):
    if len(y_true) == 0:
        return
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    mae  = float(mean_absolute_error(y_true, y_pred))
    r2   = float(r2_score(y_true, y_pred))
    with db() as cx, cx.cursor() as cur:
        cur.execute(
            "INSERT INTO forecast_metrics "
            "(model_name, zone_id, mae, rmse, mape, r2, smape, sample_size) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (model_name, zone_id, mae, rmse,
             mape(y_true, y_pred), r2, smape(y_true, y_pred), len(y_true)),
        )
        cx.commit()


def save_predictions(zone_id, predictions, method, confidence):
    """predictions: dict {horizon_h -> score}"""
    rows = []
    for h, s in predictions.items():
        level = "critical" if s >= 70 else ("warning" if s >= 40 else "safe")
        rows.append((zone_id, h, int(round(s)), level, method, confidence))
    with db() as cx, cx.cursor() as cur:
        cur.executemany(
            "INSERT INTO forecast_predictions "
            "(zone_id, horizon_hours, predicted_score, predicted_level, method, confidence) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            rows,
        )
        cx.commit()


# ────────────────────────────────────────────────────────────────────────
#  Main training loop
# ────────────────────────────────────────────────────────────────────────
def train_zone(zone_id: int, zname: str, window: int = 7, epochs: int = 100):
    df = load_full_series(zone_id)
    if len(df) < window * 4:
        print(f"  - {zname:25s}  SKIPPED ({len(df)} pts)")
        return

    feats = make_features(df, n_lags=window)
    feat_cols = [c for c in feats.columns if c.startswith("lag")] + \
                ["hour_sin", "hour_cos", "dow_sin", "dow_cos"]
    X = feats[feat_cols].values
    y = feats["score"].values

    split = int(len(X) * 0.8)
    X_tr, X_va = X[:split], X[split:]
    y_tr, y_va = y[:split], y[split:]

    # ─ XGBoost ─
    xgb = XGBRegressor(n_estimators=200, max_depth=4, learning_rate=0.05,
                       verbosity=0, n_jobs=-1)
    xgb.fit(X_tr, y_tr)
    y_pred_xgb = xgb.predict(X_va)
    save_metrics(zone_id, "xgboost", y_va, y_pred_xgb)

    # ─ LSTM ─
    series = df["score"].values.astype(np.float32) / 100.0
    Xs, ys = lstm_dataset(series, window=window)
    split_s = int(len(Xs) * 0.8)
    Xs_tr, Xs_va = Xs[:split_s], Xs[split_s:]
    ys_tr, ys_va = ys[:split_s], ys[split_s:]
    lstm = build_lstm(window)
    lstm.fit(Xs_tr, ys_tr, epochs=epochs, batch_size=16, verbose=0)
    y_pred_lstm = (lstm.predict(Xs_va, verbose=0).flatten() * 100)
    y_va_lstm = ys_va * 100
    save_metrics(zone_id, "lstm", y_va_lstm, y_pred_lstm)

    # ─ Ensemble alpha search ─
    n = min(len(y_pred_xgb), len(y_pred_lstm))
    if n == 0:
        return
    y_xgb_clipped  = np.clip(y_pred_xgb[:n], 0, 100)
    y_lstm_clipped = np.clip(y_pred_lstm[:n], 0, 100)
    y_true = y_va_lstm[:n]

    best = {"alpha": 0.5, "rmse": float("inf")}
    for a in np.arange(0, 1.01, 0.05):
        yE = a * y_xgb_clipped + (1 - a) * y_lstm_clipped
        rmse = float(np.sqrt(mean_squared_error(y_true, yE)))
        if rmse < best["rmse"]:
            best = {"alpha": float(a), "rmse": rmse, "yE": yE}

    save_metrics(zone_id, "ensemble", y_true, best["yE"])

    # ─ Forecast 6/12/24h ahead ─
    last_window = series[-window:]
    preds = {}
    for h in (6, 12, 24):
        x = last_window.copy()
        for _ in range(h):
            x_lstm = x.reshape(1, window, 1)
            yL = float(lstm.predict(x_lstm, verbose=0)[0][0]) * 100
            # XGB needs feature vector
            x_xgb = np.array([
                *([v * 100 for v in x[-window:][::-1]]),
                np.sin(2 * np.pi * dt.datetime.utcnow().hour / 24),
                np.cos(2 * np.pi * dt.datetime.utcnow().hour / 24),
                np.sin(2 * np.pi * dt.datetime.utcnow().weekday() / 7),
                np.cos(2 * np.pi * dt.datetime.utcnow().weekday() / 7),
            ]).reshape(1, -1)
            yX = float(xgb.predict(x_xgb)[0])
            yE = best["alpha"] * yX + (1 - best["alpha"]) * yL
            x = np.append(x[1:], yE / 100.0)
        preds[h] = float(np.clip(yE, 0, 100))

    confidence = max(0.4, min(0.95, 1 - best["rmse"] / 100))
    save_predictions(zone_id, preds, "ensemble_xgb_lstm", confidence)
    print(f"  - {zname:25s}  α={best['alpha']:.2f}  RMSE={best['rmse']:.2f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", type=int, default=7)
    parser.add_argument("--epochs", type=int, default=100)
    args = parser.parse_args()

    print("[forecast] training XGBoost + LSTM ensemble per zone")
    for zid, zname in list_zones():
        try:
            train_zone(zid, zname, args.window, args.epochs)
        except Exception as e:   # noqa: BLE001
            print(f"  - {zname:25s}  ERROR: {e}")
    print("[forecast] done.")


if __name__ == "__main__":
    main()
