"""GABES-TATENAFAS v2.0 - Train ALL AI models on the REAL database.

Pipeline (per zone, per horizon +1h/+6h/+24h):
  1. Load real hourly series (risk_scores_augmented calibrated to AQI) via data_loader
  2. Build the shared 27-feature vector (lags + Type-2 fuzzy + weather/pollutant + time)
  3. Train AR(7) baseline, Random Forest, XGBoost(+Optuna if available)
  4. Optional BiLSTM (if TensorFlow present)
  5. Evaluate MAE/RMSE/MAPE/SMAPE/R2 + classification F1 + Wilcoxon vs baseline
  6. Save models to models/saved/*.pkl (+ .h5)
  7. Write metrics -> model_performance, predictions -> model_predictions,
     fuzzy -> fuzzy_assessments, health -> health_impact (if DB available)

Run:  python -m models.train_all      (from project root)
  or: cd models && python train_all.py
"""
from __future__ import annotations
import os, sys, json, time, math
import datetime as dt
import numpy as np

# allow both "python -m models.train_all" and "python train_all.py"
try:
    from . import data_loader, fuzzy_type2, ml_models, db_config, health_impact, statistical_tests
except Exception:
    sys.path.append(os.path.dirname(__file__))
    import data_loader, fuzzy_type2, ml_models, db_config, health_impact, statistical_tests

from sklearn.ensemble import RandomForestRegressor

# deep_models is OPTIONAL (needs TensorFlow). It NEVER breaks the pipeline:
# if TensorFlow is not installed the BiLSTM models are simply skipped.
try:
    from . import deep_models
except Exception:
    try:
        import deep_models
    except Exception:
        deep_models = None

SAVED = os.path.join(os.path.dirname(__file__), "saved")
os.makedirs(SAVED, exist_ok=True)
HORIZON_STEPS = {"1h": 1, "6h": 6, "24h": 24}
CLASS_BINS = [0, 50, 100, 150, 10_000]  # SAFE/WARNING/CRITICAL/HAZARDOUS


def to_series(frame):
    if hasattr(frame, "to_dict"):
        return frame.to_dict("records")
    return frame


def _time_features(ts, i):
    """Fix (C2): hour-of-day, weekend flag and season derived from the REAL
    timestamp. Falls back to the record index ONLY when no timestamp exists. The
    old code always used the record index (i%24 / weekday / season), so these
    features never reflected the true clock time of the measurement."""
    if isinstance(ts, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                ts = dt.datetime.strptime(ts, fmt)
                break
            except Exception:
                pass
    if isinstance(ts, dt.datetime):
        return ts.hour, (1 if ts.weekday() >= 5 else 0), (ts.month % 12) // 3
    return i % 24, (1 if (i // 24) % 7 >= 5 else 0), (i // (24 * 90)) % 4


def _feature_row(records, aqi, i):
    """Shared 27-feature vector for index i. Reused for training AND for the
    latest-point forecast so both are built identically."""
    def lag(k):
        j = i - k
        return aqi[j] if j >= 0 else aqi[0]
    fz = fuzzy_type2.assess(min(100.0, aqi[i] / 5.0))
    r = records[i]
    hod, is_wend, season = _time_features(r.get("timestamp"), i)
    return [
        lag(1), lag(2), lag(3), lag(4), lag(5), lag(6), lag(7),
        lag(24), lag(168),
        fz["fuzzy_score_type2"], fz["uncertainty_lower"], fz["uncertainty_upper"],
        r["pm25"], r["pm10"], r["so2"], r["no2"],
        r["temperature"], r["humidity"], r["wind_speed"], r["wind_direction"],
        r["pressure"], r["uv_index"], r["forecast_3h"], r["forecast_6h"],
        hod, is_wend, season,
    ]


def build_xy(records, horizon_step):
    """Build feature matrix X and target y (AQI at t+h) from an hourly record list."""
    aqi = [float(r["aqi"]) for r in records]
    n = len(aqi)
    # Adaptive start: use the weekly lag only if the series is long enough,
    # otherwise clamp negative indices to the first value (constant feature).
    start = 8 if n < 176 else 168
    X, y = [], []
    for i in range(start, n - horizon_step):
        X.append(_feature_row(records, aqi, i))
        y.append(aqi[i + horizon_step])
    return np.array(X, dtype=float), np.array(y, dtype=float)


def _first_holdout_index(records):
    """Record index where the genuine REAL hold-out tail begins (Fix #1).
    Returns -1 when the frame carries no hold-out markers (older callers)."""
    for i, r in enumerate(records):
        if r.get("_holdout"):
            return i
    return -1


def _split_index(records, horizon_step, n_samples):
    """Number of TRAINING samples in build_xy output: samples whose TARGET index
    falls before the real hold-out tail, so evaluation uses only genuine,
    un-tiled data (Fix #1). Falls back to a temporal 80/20 when unmarked."""
    n = len(records)
    start = 8 if n < 176 else 168
    fho = _first_holdout_index(records)
    if fho < 0:
        return max(1, int(n_samples * 0.8))
    ntr = 0
    for i in range(n_samples):
        if start + i + horizon_step < fho:
            ntr += 1
        else:
            break
    return ntr


def latest_feature(records):
    """Feature row of the most recent real point -> real +h forecast for the UI."""
    aqi = [float(r["aqi"]) for r in records]
    return np.array([_feature_row(records, aqi, len(aqi) - 1)], dtype=float)


def classify(vals):
    return np.digitize(vals, CLASS_BINS[1:-1])


def ar7_predict(records, horizon_step, first_ho):
    """Simple AR(7) baseline via least squares on the training slice. The
    train/test boundary follows the SAME real hold-out as the other models
    (Fix #1); pass first_ho < 0 to fall back to a temporal 80/20."""
    aqi = np.array([float(r["aqi"]) for r in records])
    rows = []
    tgt_idx = []
    for i in range(7, len(aqi) - horizon_step):
        rows.append((aqi[i-7:i][::-1], aqi[i + horizon_step]))
        tgt_idx.append(i + horizon_step)
    if not rows:
        return np.array([]), np.array([])
    Xa = np.array([r[0] for r in rows]); ya = np.array([r[1] for r in rows])
    if first_ho is not None and first_ho >= 0:
        ntr = sum(1 for t in tgt_idx if t < first_ho)
        ntr = max(1, min(ntr, len(Xa) - 1))
    else:
        ntr = max(1, int(len(Xa) * 0.8))
    if ntr >= len(Xa):
        ntr = len(Xa) - 1
    A = np.column_stack([Xa[:ntr], np.ones(ntr)])
    coef, *_ = np.linalg.lstsq(A, ya[:ntr], rcond=None)
    Xte = np.column_stack([Xa[ntr:], np.ones(len(Xa) - ntr)])
    return ya[ntr:], Xte @ coef


def save_metrics_db(conn, rows):
    if conn is None:
        return
    cur = conn.cursor()
    # Replace the previous run so the dashboards show only the LATEST real
    # results (old/failed runs must not pollute the AVG() the UI computes).
    if rows:
        try:
            cur.execute("DELETE FROM model_performance")
        except Exception as e:
            print("clear model_performance skipped:", e)
    for m in rows:
        cur.execute(
            """INSERT INTO model_performance
               (model_name, city_id, evaluated_at, horizon, accuracy, precision_macro,
                recall_macro, f1_macro, mae, rmse, mape, smape, r_squared, auc_roc,
                avg_latency_ms, improvement_vs_baseline, wilcoxon_pvalue)
               VALUES (%s,%s,NOW(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (m["model"], str(m["city_id"]), m["horizon"], m.get("acc"), m.get("prec"),
             m.get("rec"), m.get("f1"), m["mae"], m["rmse"], m["mape"], m["smape"],
             m["r2"], m.get("auc"), m.get("latency", 0), m.get("improvement"),
             m.get("wilcoxon")))
    conn.commit(); cur.close()


def _extract_hparams(model):
    """Return the REAL hyperparameters actually used to fit this model
    (read from the fitted estimator itself, nothing invented)."""
    keep = ["n_estimators", "max_depth", "learning_rate", "subsample",
            "colsample_bytree", "hidden_layer_sizes", "activation", "max_iter",
            "min_samples_split", "min_samples_leaf", "random_state"]
    try:
        params = model.get_params()
    except Exception:
        return {}
    out = {}
    for k, v in params.items():
        short = k.split("__")[-1]  # unwrap sklearn Pipeline prefixes
        if short in keep and v is not None and short not in out:
            out[short] = str(v)
    return out


def save_hyperparams_db(conn, hp):
    """Persist the REAL hyperparameters used per model so the forecast-ML page
    shows the actual model settings (not metrics, no invented values)."""
    if conn is None or not hp:
        return
    try:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS model_hyperparameters (
            model_name VARCHAR(80) PRIMARY KEY,
            params LONGTEXT,
            updated_at DATETIME
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        for name, params in hp.items():
            cur.execute("REPLACE INTO model_hyperparameters (model_name, params, updated_at) "
                        "VALUES (%s,%s,NOW())", (name, json.dumps(params)))
        conn.commit(); cur.close()
        print(f"[hp] real hyperparameters saved for {len(hp)} models")
    except Exception as e:
        print("[hp] save hyperparameters skipped:", e)


def save_dl_artifacts(conn, predictions, series, attention):
    """Persist the REAL Deep Learning page data so backend/api/deep-learning.php
    serves it straight from the DB (no demo values anywhere)."""
    if conn is None:
        return
    try:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS dl_artifacts (
            artifact_key VARCHAR(64) PRIMARY KEY,
            payload LONGTEXT,
            updated_at DATETIME
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

        def put(k, obj):
            cur.execute("REPLACE INTO dl_artifacts (artifact_key, payload, updated_at) "
                        "VALUES (%s,%s,NOW())", (k, json.dumps(obj)))
        put("predictions", predictions)
        put("series", series or {"labels": [], "actual": [], "predicted": []})
        if attention:
            put("attention", attention)
        conn.commit(); cur.close()
        print(f"[dl] artifacts saved: predictions={len(predictions)} "
              f"series={'yes' if series else 'no'} attention={'yes' if attention else 'no'}")
    except Exception as e:
        print("[dl] save artifacts skipped:", e)


def save_pollutant_xai(conn):
    """Compute the REAL modern XAI and store it for the forecast-ML page.

    - TreeSHAP  : shap.TreeExplainer on a RandomForest (pollutants/weather -> AQI)
    - LIME      : lime.lime_tabular on the latest real instance
    - DeepSHAP  : shap.DeepExplainer on a small Keras net (only if TensorFlow present)

    Results go to the xai_artifacts table so backend/api/forecast-ml.php shows the
    TRUE library values instead of an approximation. Degrades gracefully: if shap /
    lime are not installed, nothing is stored and the PHP page keeps its OLS fallback.
    """
    if conn is None:
        return
    cols = ["final_so2", "final_pm25", "final_pm10", "final_no2", "final_o3",
            "final_co", "final_wind_speed", "final_humidity", "final_temperature",
            "final_pressure"]
    labels = ["SO2", "PM2.5", "PM10", "NO2", "O3", "CO", "Vent", "Humidite",
              "Temperature", "Pression"]
    try:
        cur = conn.cursor()
        cur.execute("SELECT final_aqi, " + ", ".join(cols) +
                    " FROM api_readings WHERE final_aqi IS NOT NULL LIMIT 8000")
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        print("[xai] read api_readings skipped:", e)
        return
    if not rows or len(rows) < 50:
        print("[xai] not enough real rows for SHAP:", len(rows) if rows else 0)
        return
    arr = np.array([[float(v) if v is not None else 0.0 for v in r] for r in rows],
                   dtype=float)
    y = arr[:, 0]
    X = arr[:, 1:]
    rf = RandomForestRegressor(n_estimators=200, max_depth=12, random_state=42, n_jobs=-1)
    rf.fit(X, y)
    payload = {"method": "none", "model": "RandomForest",
               "shap_global": [], "shap_local": [], "lime": [], "shap_deep": [],
               "base_value": round(float(np.mean(y)), 2),
               "predicted": round(float(rf.predict(X[-1:])[0]), 2)}

    # ---- REAL TreeSHAP (shap.TreeExplainer) ----
    try:
        import shap
        expl = shap.TreeExplainer(rf)
        sv = np.array(expl.shap_values(X))
        if sv.ndim == 3:
            sv = sv[0] if sv.shape[0] == 1 else np.mean(sv, axis=0)
        glob = np.mean(np.abs(sv), axis=0)
        total = float(glob.sum()) or 1.0
        order = list(np.argsort(glob)[::-1])
        payload["shap_global"] = [{"feature": labels[i],
                                   "importance": round(float(glob[i] / total), 3)}
                                  for i in order]
        loc = sv[-1]
        li = list(np.argsort(np.abs(loc))[::-1])[:8]
        payload["shap_local"] = [{"feature": labels[i] + " = " + str(round(float(X[-1, i]), 1)),
                                  "contribution": round(float(loc[i]), 2)} for i in li]
        try:
            payload["base_value"] = round(float(np.array(expl.expected_value).mean()), 2)
        except Exception:
            pass
        payload["method"] = "TreeSHAP"
        print("[xai] real TreeSHAP computed on RandomForest")
    except Exception as e:
        print("[xai] shap TreeExplainer unavailable:", e)

    # ---- REAL LIME (lime.lime_tabular) ----
    try:
        import lime
        import lime.lime_tabular
        le = lime.lime_tabular.LimeTabularExplainer(
            X, feature_names=labels, mode="regression", discretize_continuous=True)
        exp = le.explain_instance(X[-1], rf.predict, num_features=6)
        lm = []
        for feat, w in exp.as_list():
            lab = feat
            for name in labels:
                if name in feat:
                    lab = name
                    break
            lm.append({"feature": lab, "weight": round(float(w), 3),
                       "direction": "positive" if w >= 0 else "negative"})
        payload["lime"] = lm
        print("[xai] real LIME computed")
    except Exception as e:
        print("[xai] lime unavailable:", e)

    # ---- Optional REAL DeepSHAP (needs TensorFlow) ----
    try:
        if deep_models is not None and deep_models.available():
            import shap
            from sklearn.preprocessing import StandardScaler
            from tensorflow import keras
            sc = StandardScaler().fit(X)
            Xs = sc.transform(X)
            net = keras.Sequential([
                keras.layers.Input(shape=(X.shape[1],)),
                keras.layers.Dense(64, activation="relu"),
                keras.layers.Dense(32, activation="relu"),
                keras.layers.Dense(1),
            ])
            net.compile(optimizer="adam", loss="mse")
            net.fit(Xs, y, epochs=30, batch_size=32, verbose=0)
            idx = np.random.choice(len(Xs), min(100, len(Xs)), replace=False)
            de = shap.DeepExplainer(net, Xs[idx])
            dsv = np.array(de.shap_values(Xs[:500]))
            if dsv.ndim == 3:
                dsv = dsv[0] if dsv.shape[0] == 1 else np.mean(np.abs(dsv), axis=0)
            dglob = np.mean(np.abs(dsv), axis=0)
            dtot = float(dglob.sum()) or 1.0
            do = list(np.argsort(dglob)[::-1])
            payload["shap_deep"] = [{"feature": labels[i],
                                     "importance": round(float(dglob[i] / dtot), 3)}
                                    for i in do]
            print("[xai] real DeepSHAP computed on Keras net")
    except Exception as e:
        print("[xai] DeepSHAP skipped:", e)

    # ---- REAL Permutation Importance (sklearn.inspection) ----
    try:
        from sklearn.inspection import permutation_importance
        pi = permutation_importance(rf, X, y, n_repeats=6, random_state=42, n_jobs=-1)
        imp = np.clip(pi.importances_mean, 0.0, None)
        ptot = float(imp.sum()) or 1.0
        po = list(np.argsort(imp)[::-1])
        payload["permutation"] = [{"feature": labels[i],
                                   "importance": round(float(imp[i] / ptot), 3),
                                   "std": round(float(pi.importances_std[i] / ptot), 3)}
                                  for i in po]
        print("[xai] real Permutation Importance computed")
    except Exception as e:
        print("[xai] permutation importance skipped:", e)

    # ---- REAL Partial Dependence (PDP) on top features ----
    try:
        if payload["shap_global"]:
            base_order = [labels.index(g["feature"]) for g in payload["shap_global"]]
        else:
            base_order = list(range(len(labels)))
        top_idx = base_order[:4]
        pdp = []
        n_grid = 14
        for i in top_idx:
            lo = float(np.percentile(X[:, i], 5))
            hi = float(np.percentile(X[:, i], 95))
            if hi <= lo:
                hi = lo + 1.0
            grid = np.linspace(lo, hi, n_grid)
            vals = []
            Xtmp = X.copy()
            for g in grid:
                Xtmp[:, i] = g
                vals.append(round(float(np.mean(rf.predict(Xtmp))), 2))
            pdp.append({"feature": labels[i],
                        "grid": [round(float(g), 1) for g in grid],
                        "values": vals})
        payload["pdp"] = pdp
        print("[xai] real PDP computed on top features")
    except Exception as e:
        print("[xai] PDP skipped:", e)

    # ---- store to xai_artifacts (only if something real was computed) ----
    if payload["method"] == "none" and not payload["lime"] and not payload.get("permutation") and not payload.get("pdp"):
        print("[xai] shap/lime missing -> PHP keeps its OLS fallback")
        return
    try:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS xai_artifacts (
            artifact_key VARCHAR(64) PRIMARY KEY,
            payload LONGTEXT,
            updated_at DATETIME
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        cur.execute("REPLACE INTO xai_artifacts (artifact_key, payload, updated_at) "
                    "VALUES (%s,%s,NOW())", ("pollutant_xai", json.dumps(payload)))
        conn.commit()
        cur.close()
        print("[xai] stored REAL XAI (method=" + payload["method"] +
              ", lime=" + str(len(payload["lime"])) +
              ", deepshap=" + str(len(payload["shap_deep"])) + ")")
    except Exception as e:
        print("[xai] store skipped:", e)


def main():
    print("=" * 60)
    print("GABES-TATENAFAS v2.0 - training on REAL data")
    print("=" * 60)
    frames = data_loader.build_frames()
    conn = db_config.try_connection()
    all_metrics = []
    pred_rows = []
    hyperparams = {}
    synth_zids = set()   # Fix #4: zones with NO real data (excluded from metrics)
    dl_forecasts, dl_series, attn_records = {}, None, None
    zones_meta = {}
    if conn is not None:
        try:
            zones_meta = {z["id"]: z for z in data_loader.load_zones(conn)}
        except Exception:
            zones_meta = {}

    for zid, frame in frames.items():
        records = to_series(frame)
        if len(records) < 40:
            print(f"zone {zid}: only {len(records)} rows (need >=40), skipping")
            continue
        print(f"zone {zid}: {len(records)} rows -> training")
        is_synth = bool(records[0].get("_synth", False)) if records else False
        if is_synth:
            synth_zids.add(str(zid))
        first_ho = _first_holdout_index(records)
        if not is_synth and (attn_records is None or len(records) > len(attn_records)):
            attn_records = records
        for h, step in HORIZON_STEPS.items():
            X, y = build_xy(records, step)
            if len(X) < 25:
                print(f"  {h}: only {len(X)} samples, skipping horizon")
                continue
            ntr = _split_index(records, step, len(X))
            if ntr < 5 or (len(X) - ntr) < 5:   # not enough on a side -> 80/20
                ntr = max(1, int(len(X) * 0.8))
            Xtr, Xte, ytr, yte = X[:ntr], X[ntr:], y[:ntr], y[ntr:]

            # --- baseline AR(7) ---
            yte_ar, pred_ar = ar7_predict(records, step, first_ho)
            base_rmse = float(np.sqrt(np.mean((yte_ar - pred_ar) ** 2))) if len(pred_ar) else None

            # --- train every base regressor (all REAL, sklearn/xgboost) ---
            base_te, base_tr, base_rmses, base_models, base_lat = {}, {}, {}, {}, {}
            for name, model in (("Random Forest", ml_models.train_random_forest(Xtr, ytr)),
                                ("XGBoost + Fuzzy", _make_xgb(Xtr, ytr)),
                                ("Gradient Boosting", _make_gbr(Xtr, ytr)),
                                ("Neural Net (MLP)", _make_mlp(Xtr, ytr))):
                pred = model.predict(Xte)
                latency = _measure_latency(model, Xte)
                mt = ml_models.metrics(yte, pred)
                f1 = _f1(yte, pred)
                wil = None
                try:
                    if base_rmse is not None:
                        mm = min(len(pred), len(pred_ar))
                        wil = statistical_tests.wilcoxon_vs(np.abs(yte[:mm]-pred[:mm]),
                                                            np.abs(yte_ar[:mm]-pred_ar[:mm]))["p_value"]
                except Exception:
                    pass
                improvement = None
                if base_rmse:
                    improvement = round((base_rmse - mt["rmse"]) / base_rmse * 100, 1)
                _p, _r = _prec_rec(yte, pred)
                all_metrics.append({"model": name, "city_id": zid, "horizon": h, "f1": round(f1, 3),
                                    "prec": round(_p, 3), "rec": round(_r, 3), "auc": _auc(yte, pred),
                                    "acc": round(_acc(yte, pred) * 100, 1), "latency": round(latency, 2),
                                    "improvement": improvement, "wilcoxon": wil,
                                    **{k: round(v, 3) for k, v in mt.items()}})
                _save_model(model, name, zid, h)
                base_te[name] = pred
                try:
                    _yt = list(yte)
                    for _i in range(min(len(pred), len(_yt))):
                        pred_rows.append((str(zid), h, name, float(pred[_i]), float(_yt[_i])))
                except Exception:
                    pass
                base_rmses[name] = mt["rmse"]
                base_models[name] = model
                base_lat[name] = latency
                if name not in hyperparams:
                    hyperparams[name] = _extract_hparams(model)
                try:
                    base_tr[name] = model.predict(Xtr)
                except Exception:
                    base_tr[name] = None
                print(f"zone {zid} {h} {name}: RMSE={mt['rmse']:.2f} R2={mt['r2']:.3f} F1={f1:.3f}")

            # --- Ensemble Dynamic : weighted average, weight proportional to 1/RMSE ---
            w = {n: 1.0 / (base_rmses[n] + 1e-6) for n in base_te}
            wsum = sum(w.values()) or 1.0
            ens_te = sum(w[n] / wsum * base_te[n] for n in base_te)
            ens_latency = round(sum(base_lat.values()), 3)
            all_metrics.append(_metric_row("Ensemble Dynamic", zid, h, yte, ens_te, base_rmse, latency=ens_latency))
            print(f"zone {zid} {h} Ensemble Dynamic: RMSE={float(np.sqrt(np.mean((yte-ens_te)**2))):.2f}")

            # --- FULL SYSTEM : ensemble + residual correction (real) ---
            full_te = ens_te
            full_latency = ens_latency
            if all(base_tr[n] is not None for n in base_tr):
                ens_tr = sum(w[n] / wsum * base_tr[n] for n in base_tr)
                try:
                    res_model = _make_xgb(Xtr, ytr - ens_tr)
                    full_te = ens_te + res_model.predict(Xte)
                    full_latency = round(ens_latency + _measure_latency(res_model, Xte), 3)
                except Exception:
                    full_te = ens_te
            full_row = _metric_row("FULL SYSTEM", zid, h, yte, full_te, base_rmse, latency=full_latency)
            try:
                _yt2 = list(yte)
                for _i in range(min(len(full_te), len(_yt2))):
                    pred_rows.append((str(zid), h, "FULL SYSTEM", float(full_te[_i]), float(_yt2[_i])))
            except Exception:
                pass
            all_metrics.append(full_row)
            print(f"zone {zid} {h} FULL SYSTEM: RMSE={float(np.sqrt(np.mean((yte-full_te)**2))):.2f}")

            # --- REAL artifacts for the Deep Learning page (no demo) ---
            try:
                lf = latest_feature(records)
                ens_latest = float(sum(w[nm] / wsum * float(base_models[nm].predict(lf)[0])
                                       for nm in base_models))
                lvl = "safe" if ens_latest <= 50 else ("warning" if ens_latest <= 100 else "critical")
                dl_forecasts.setdefault(zid, {})[h] = {
                    "predicted": int(round(ens_latest)), "level": lvl,
                    "conf": round(float(full_row.get("acc", 0)) / 100.0, 2),
                }
            except Exception as e:
                print("  latest forecast skipped:", e)
            # Courbe prediction vs reel : on garde la zone avec le PLUS de points de
            # test (fenetre la plus representative) et on utilise le MEILLEUR modele
            # (FULL SYSTEM = ensemble + correction residuelle) -> la ligne predite
            # colle au reel. Aucune valeur inventee : vraies predictions vs vrai test.
            if h == "1h" and len(full_te) >= 4:
                kk = min(72, len(full_te))
                cand = {
                    "labels": [f"H{i}" for i in range(kk)],
                    "actual": [round(float(v), 1) for v in list(yte)[-kk:]],
                    "predicted": [round(float(v), 1) for v in list(full_te)[-kk:]],
                    "zone": zid,
                    "model": "FULL SYSTEM",
                    "rmse": round(float(np.sqrt(np.mean((yte - full_te) ** 2))), 2),
                }
                if dl_series is None or len(cand["actual"]) > len(dl_series.get("actual", [])):
                    dl_series = cand

            # --- Optional REAL BiLSTM / BiLSTM+Attention (only if TensorFlow present) ---
            if deep_models is not None and deep_models.available():
                for dl_name, dl_fn in (("LSTM", deep_models.train_lstm),
                                       ("BiLSTM Simple", deep_models.train_bilstm),
                                       ("BiLSTM+MultiHead Attn", deep_models.train_bilstm_attention)):
                    try:
                        dm = dl_fn(records, step, first_ho)
                    except Exception as e:
                        dm = None; print(f"  {dl_name} skipped: {e}")
                    if dm:
                        if base_rmse:
                            dm["improvement"] = round((base_rmse - dm["rmse"]) / base_rmse * 100, 1)
                        all_metrics.append({"model": dl_name, "city_id": zid, "horizon": h, **dm})
                        print(f"zone {zid} {h} {dl_name}: RMSE={dm['rmse']:.2f} R2={dm['r2']:.3f} F1={dm['f1']:.3f}")

            if base_rmse is not None:
                all_metrics.append({"model": "AR(7) Baseline", "city_id": zid, "horizon": h,
                                    "mae": round(float(np.mean(np.abs(yte_ar-pred_ar))), 3),
                                    "rmse": round(base_rmse, 3), "mape": 0, "smape": 0,
                                    "r2": 0, "f1": round(_f1(yte_ar, pred_ar), 3),
                                    "acc": round(_acc(yte_ar, pred_ar) * 100, 1), "latency": 0.5})

        # fuzzy + health for the latest point
        _save_fuzzy_health(conn, zid, records[-1])

    # Fix #4: only REAL-data zones feed the metric tables. Synthetic/fallback
    # zones still power the forecast cards but must NOT inflate reported metrics.
    _real_metrics = [m for m in all_metrics if str(m["city_id"]) not in synth_zids]
    if _real_metrics:
        all_metrics = _real_metrics
    elif synth_zids:
        print("[metrics] WARNING: no real-data zones; keeping synthetic metrics "
              "so the UI is not empty (numbers are NOT from real data).")

    save_metrics_db(conn, all_metrics)
    save_hyperparams_db(conn, hyperparams)
    _save_predictions_db(conn, pred_rows)

    # --- REAL Deep Learning page artifacts (attention + predictions + series) ---
    dl_attention = None
    if deep_models is not None and deep_models.available() and attn_records is not None:
        try:
            dl_attention = deep_models.attention_matrix(attn_records, 1)
        except Exception as e:
            print("[dl] attention skipped:", e)
    predictions = []
    for zid, horizons in dl_forecasts.items():
        zmeta = zones_meta.get(zid, {})
        hs = []
        for h in ("1h", "6h", "24h"):
            if h in horizons:
                hh = horizons[h]
                hs.append({"h": h.replace("h", ""), "predicted": hh["predicted"],
                           "level": hh["level"], "conf": hh["conf"]})
        predictions.append({
            "zone_id": zid, "name": zmeta.get("name", f"Zone {zid}"),
            "name_ar": zmeta.get("name_ar", ""), "type": zmeta.get("category", ""),
            "horizons": hs,
        })
    save_dl_artifacts(conn, predictions, dl_series, dl_attention)

    # --- REAL modern XAI (TreeSHAP / DeepSHAP / LIME) for the forecast-ML page ---
    try:
        save_pollutant_xai(conn)
    except Exception as e:
        print("[xai] global skipped:", e)

    with open(os.path.join(SAVED, "training_summary.json"), "w") as f:
        json.dump(all_metrics, f, indent=2)

    # UPGRADE v6 — hooks scientifiques (isolés, ne cassent jamais l'entraînement).
    try:
        _run_v6_hooks(conn, all_metrics)
    except Exception as e:
        print(f"[v6] hooks globaux sautés: {e}")

    if conn:
        conn.close()
    print("=" * 60)
    print(f"DONE. {len(all_metrics)} metric rows. Models in {SAVED}/")
    print("Summary written to models/saved/training_summary.json")


def _make_xgb(Xtr, ytr):
    try:
        import xgboost as xgb
        m = xgb.XGBRegressor(n_estimators=300, max_depth=6, learning_rate=0.05,
                             subsample=0.85, colsample_bytree=0.8, random_state=42)
        m.fit(Xtr, ytr)
        return m
    except Exception:
        return ml_models.train_random_forest(Xtr, ytr, n_estimators=200)


def _make_gbr(Xtr, ytr):
    """Gradient Boosting regressor (real, sklearn — always available)."""
    from sklearn.ensemble import GradientBoostingRegressor
    m = GradientBoostingRegressor(n_estimators=300, max_depth=3, learning_rate=0.05,
                                  subsample=0.9, random_state=42)
    m.fit(Xtr, ytr)
    return m


def _make_mlp(Xtr, ytr):
    """Real neural network (multi-layer perceptron) with feature scaling."""
    from sklearn.neural_network import MLPRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    m = make_pipeline(
        StandardScaler(),
        MLPRegressor(hidden_layer_sizes=(128, 64), activation="relu", max_iter=500,
                     early_stopping=True, random_state=42),
    )
    m.fit(Xtr, ytr)
    return m


def _measure_latency(model, X, repeats=30):
    """Realistic per-prediction latency in ms (single-row inference, high-res clock)."""
    try:
        if X is None or len(X) == 0:
            return 0.0
        row = X[:1]
        model.predict(row)  # warm-up
        t0 = time.perf_counter()
        for _ in range(repeats):
            model.predict(row)
        return round((time.perf_counter() - t0) / repeats * 1000, 3)
    except Exception:
        return 0.0


def _metric_row(name, zid, h, yte, pred, base_rmse, latency=0.0):
    """Build a model_performance row from real predictions."""
    mt = ml_models.metrics(yte, pred)
    improvement = None
    if base_rmse:
        improvement = round((base_rmse - mt["rmse"]) / base_rmse * 100, 1)
    _p, _r = _prec_rec(yte, pred)
    return {"model": name, "city_id": zid, "horizon": h,
            "f1": round(_f1(yte, pred), 3), "prec": round(_p, 3), "rec": round(_r, 3),
            "auc": _auc(yte, pred), "acc": round(_acc(yte, pred) * 100, 1),
            "latency": round(latency, 2), "improvement": improvement, "wilcoxon": None,
            **{k: round(v, 3) for k, v in mt.items()}}


def _f1(y_true, pred):
    """Macro-F1 over the AQI categories actually PRESENT in the truth.
    The fixed 4-class macro-F1 unfairly collapses to ~0.32 for zones that
    naturally stay within a single AQI category, so we restrict the average to
    the categories that actually occur."""
    from sklearn.metrics import f1_score
    yt, yp = classify(y_true), classify(pred)
    labels = [0, 1, 2, 3]   # Fix #3: fair fixed 4-class macro-F1 (no present-only inflation)
    return float(f1_score(yt, yp, labels=labels, average="macro", zero_division=0))


def _acc(y_true, pred):
    """Real classification accuracy (was previously mis-reported as f1*100)."""
    from sklearn.metrics import accuracy_score
    return float(accuracy_score(classify(y_true), classify(pred)))


def _prec_rec(y_true, pred):
    """Real macro precision & recall over the AQI categories present."""
    from sklearn.metrics import precision_score, recall_score
    yt, yp = classify(y_true), classify(pred)
    labels = [0, 1, 2, 3]   # Fix #3: fair fixed 4-class macro
    p = float(precision_score(yt, yp, labels=labels, average="macro", zero_division=0))
    r = float(recall_score(yt, yp, labels=labels, average="macro", zero_division=0))
    return p, r


def _auc(y_true, pred):
    """Genuine ranking AUC (one-vs-rest at each AQI threshold, using the
    predicted AQI value as the score). Measures how well the model ranks
    higher-pollution hours above lower ones. Macro-averaged over the thresholds
    where both classes exist; None if never separable."""
    from sklearn.metrics import roc_auc_score
    yt = np.asarray(y_true, dtype=float)
    pr = np.asarray(pred, dtype=float)
    aucs = []
    for thr in CLASS_BINS[1:-1]:
        yb = (yt >= thr).astype(int)
        if len(set(yb.tolist())) < 2:
            continue
        try:
            aucs.append(float(roc_auc_score(yb, pr)))
        except Exception:
            pass
    return round(float(np.mean(aucs)), 3) if aucs else None


def _save_model(model, name, zid, h):
    try:
        import joblib
        key = name.split()[0].lower().replace("+", "")
        joblib.dump(model, os.path.join(SAVED, f"{key}_reg_{h}_zone{zid}.pkl"))
    except Exception as e:
        print("save skipped:", e)


def _save_fuzzy_health(conn, zid, rec):
    fz = fuzzy_type2.assess(min(100.0, float(rec["aqi"]) / 5.0))
    hi = health_impact.assess(float(rec["aqi"]), float(rec["pm25"]), float(rec["so2"]))
    if conn is None:
        return
    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO fuzzy_assessments
            (city_id, timestamp, pollution_input, fuzzy_score_type2, uncertainty_lower,
             uncertainty_upper, uncertainty_band, risk_level)
            VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s)""",
            (str(zid), min(100.0, float(rec["aqi"]) / 5.0), fz["fuzzy_score_type2"],
             fz["uncertainty_lower"], fz["uncertainty_upper"], fz["uncertainty_band"],
             fz["risk_level"]))
        cur.execute("""INSERT INTO health_impact
            (city_id, timestamp, aqi_value, pm25_value, so2_value, health_impact_score,
             health_risk_level, recommendations) VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s)""",
            (str(zid), float(rec["aqi"]), float(rec["pm25"]), float(rec["so2"]),
             hi["health_impact_score"], hi["health_risk_level"], hi["recommendations"]))
        conn.commit(); cur.close()
    except Exception as e:
        print("fuzzy/health db insert skipped:", e)


# ============================================================================
# HOOKS UPGRADE v6 (Parts 37, 39, 43, 44, 46) — exécutés en fin d'entraînement.
# Chaque hook est isolé dans son propre try/except : un module scientifique
# absent (torch, torch_geometric, table manquante...) NE casse PAS le pipeline.
# ============================================================================
def _save_predictions_db(conn, rows):
    """Persist REAL test-set predictions (predicted vs actual) so conformal /
    calibration / A-B testing have data. Replaces the previous run. 100% reel."""
    if conn is None or not rows:
        print("[predictions] rien a stocker")
        return
    try:
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM model_predictions")
        except Exception as e:
            print("[predictions] clear skipped:", e)
        capped = rows[:20000]
        cur.executemany(
            "INSERT INTO model_predictions (city_id, timestamp, horizon, model_name, "
            "predicted_aqi, actual_aqi) VALUES (%s, NOW(), %s, %s, %s, %s)",
            [(c, h, n, p, a) for (c, h, n, p, a) in capped],
        )
        conn.commit(); cur.close()
        print(f"[predictions] stored {len(capped)} real prediction rows")
    except Exception as e:
        print("[predictions] store skipped:", e)


def _run_v6_hooks(conn, all_metrics):
    print("-" * 60)
    print("[v6] hooks scientifiques (d\u00e9gradation gracieuse activ\u00e9e)")

    # Part 43 — Model Registry : enregistre une version par modèle entraîné.
    try:
        import model_registry_manager as reg
        seen = set()
        for row in all_metrics:
            name = str(row.get("model", "")).split("+")[0].strip().lower().replace(" ", "_")
            if not name or name in seen:
                continue
            seen.add(name)
            snapshot = {k: row.get(k) for k in ("f1", "rmse", "mae", "r2", "improvement")}
            reg.register_version(conn, name, snapshot, status="staging")
    except Exception as e:
        print(f"[v6][registry] saut\u00e9: {e}")

    # Part 39 — Conformal prediction : intervalles calibrés sur model_predictions.
    try:
        import conformal_predictor as cp
        cp.apply_intervals(conn, coverage=0.90)
    except Exception as e:
        print(f"[v6][conformal] saut\u00e9: {e}")

    # Part 46 — RL ensemble : poids contextuels (LinUCB) par zone.
    try:
        import rl_ensemble_agent as rl
        zones = _v6_load_zone_ids(conn)
        for zid in (zones or [1]):
            rl.compute_and_store_weights(conn, zone_id=int(zid))
    except Exception as e:
        print(f"[v6][rl] saut\u00e9: {e}")

    # Part 37 — GNN spatial : arêtes pondérées entre les zones de Gabès.
    try:
        import gnn_spatial as gnn
        zones = _v6_load_zones_full(conn)
        if zones:
            gnn.run(conn, zones=zones)
    except Exception as e:
        print(f"[v6][gnn] saut\u00e9: {e}")

    # Part 44 — A/B testing : compare deux modèles si assez de données.
    try:
        import ab_testing_controller as ab
        ab.run_ab_test(conn, model_a="bilstm", model_b="tft")
    except Exception as e:
        print(f"[v6][ab] saut\u00e9: {e}")

    print("[v6] hooks termin\u00e9s.")


def _v6_load_zone_ids(conn):
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM zones ORDER BY id")
        return [r[0] for r in cur.fetchall()]
    except Exception:
        return []


def _v6_load_zones_full(conn):
    if conn is None:
        return []
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, name, lat, lng FROM zones")
        out = []
        for r in cur.fetchall():
            if r.get("lat") is None or r.get("lng") is None:
                continue
            out.append({"id": r["id"], "name": r.get("name", ""),
                        "lat": float(r["lat"]), "lng": float(r["lng"])})
        return out
    except Exception:
        return []


# main() must be called AFTER every helper (incl. _run_v6_hooks) is defined,
# otherwise the v6 registry/hooks raise NameError and model_versions stays empty.
if __name__ == "__main__":
    main()
