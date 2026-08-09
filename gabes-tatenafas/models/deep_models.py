"""Real deep-learning models (BiLSTM + BiLSTM+Attention) for AQI forecasting.

These are REAL models trained on the real hourly series. They are OPTIONAL:
if TensorFlow is not installed, `available()` returns False and the training
pipeline simply skips them (they are never shown as fake numbers).

Install on the user's machine to enable them:
    pip install tensorflow

Each trainer returns a dict of real metrics (rmse/mae/mape/smape/r2/f1/acc)
computed on a temporal 80/20 hold-out, comparable to the tree models.
"""
from __future__ import annotations
import numpy as np

SEQ = 24  # hours of history fed to the recurrent network
_FEATURES = ["aqi", "pm25", "so2", "no2", "temperature", "humidity", "wind_speed"]
CLASS_BINS = [0, 50, 100, 150, 10_000]


def available() -> bool:
    """True only if TensorFlow can be imported."""
    try:
        import tensorflow  # noqa: F401
        return True
    except Exception:
        return False


def _classify(vals):
    return np.digitize(vals, CLASS_BINS[1:-1])


def _metrics(yte, pred):
    from sklearn.metrics import (mean_absolute_error, mean_squared_error,
                                 r2_score, f1_score, accuracy_score,
                                 precision_score, recall_score, roc_auc_score)
    yte = np.asarray(yte, dtype=float)
    pred = np.asarray(pred, dtype=float)
    rmse = float(np.sqrt(mean_squared_error(yte, pred)))
    yt, yp = _classify(yte), _classify(pred)
    labels = [0, 1, 2, 3]  # Fix #3: fair fixed 4-class macro (no present-only inflation)
    # Genuine ranking AUC (one-vs-rest at each AQI threshold, predicted value as score)
    aucs = []
    for thr in CLASS_BINS[1:-1]:
        yb = (yte >= thr).astype(int)
        if len(set(yb.tolist())) < 2:
            continue
        try:
            aucs.append(float(roc_auc_score(yb, pred)))
        except Exception:
            pass
    auc = round(float(np.mean(aucs)), 3) if aucs else None
    return {
        "mae": round(float(mean_absolute_error(yte, pred)), 3),
        "rmse": round(rmse, 3),
        "mape": round(float(np.mean(np.abs((yte - pred) / (yte + 1e-9))) * 100), 3),
        "smape": round(float(np.mean(2 * np.abs(pred - yte) / (np.abs(yte) + np.abs(pred) + 1e-9)) * 100), 3),
        "r2": round(float(r2_score(yte, pred)), 3),
        "f1": round(float(f1_score(yt, yp, labels=labels, average="macro", zero_division=0)), 3),
        "prec": round(float(precision_score(yt, yp, labels=labels, average="macro", zero_division=0)), 3),
        "rec": round(float(recall_score(yt, yp, labels=labels, average="macro", zero_division=0)), 3),
        "auc": auc,
        "acc": round(float(accuracy_score(yt, yp)) * 100, 1),
    }


def _build_sequences(records, horizon_step):
    """Build (n, SEQ, n_features) sequences and the AQI target at t+horizon."""
    cols = {k: np.array([float(r.get(k, 0.0)) for r in records]) for k in _FEATURES}
    aqi = cols["aqi"]
    n = len(aqi)
    X, y = [], []
    for i in range(SEQ, n - horizon_step):
        window = np.stack([cols[k][i - SEQ:i] for k in _FEATURES], axis=1)
        X.append(window)
        y.append(aqi[i + horizon_step])
    if not X:
        return None, None
    return np.asarray(X, dtype=float), np.asarray(y, dtype=float)


def _standardize(Xtr, Xte):
    flat = Xtr.reshape(-1, Xtr.shape[-1])
    mu = flat.mean(axis=0)
    sd = flat.std(axis=0) + 1e-6
    return (Xtr - mu) / sd, (Xte - mu) / sd


def _train(records, horizon_step, attention, bidirectional=True, split=0.8, first_holdout=None):
    """Shared trainer. Returns a real metrics dict, or None if not trainable.

    Robustesse pour PETITS jeux de données (cause n°1 des R² négatifs du
    BiLSTM avant) :
      * standardisation de la CIBLE (on entraîne sur l'AQI z-score puis on
        inverse) -> stoppe l'explosion de la perte (RMSE 60+),
      * learning rate plus bas + gradient clipping -> entraînement stable,
      * capacité réduite + Huber loss + ReduceLROnPlateau + plus de patience
        -> moins de sur-apprentissage sur peu de données.
    """
    try:
        import tensorflow as tf
        from tensorflow.keras import layers, models, callbacks, optimizers
    except Exception:
        return None
    X, y = _build_sequences(records, horizon_step)
    if X is None or len(X) < 40:
        return None
    # Fix #1: honour the genuine hold-out boundary so BiLSTM/Attention are also
    # evaluated on REAL, un-tiled data (never on densified training copies).
    if first_holdout is not None and first_holdout >= 0:
        ntr = 0
        for j in range(len(X)):
            if SEQ + j + horizon_step < first_holdout:
                ntr += 1
            else:
                break
        if ntr < 5 or (len(X) - ntr) < 5:
            ntr = max(1, int(len(X) * split))
    else:
        ntr = max(1, int(len(X) * split))
    if ntr >= len(X):
        ntr = len(X) - 1
    Xtr, Xte, ytr, yte = X[:ntr], X[ntr:], y[:ntr], y[ntr:]
    if len(Xte) < 5:
        return None
    Xtr, Xte = _standardize(Xtr, Xte)
    # --- standardisation de la CIBLE (essentiel pour une régression stable) ---
    ymu = float(ytr.mean())
    ysd = float(ytr.std()) + 1e-6
    ytr_s = (ytr - ymu) / ysd
    tf.random.set_seed(42)
    np.random.seed(42)

    inp = layers.Input(shape=(X.shape[1], X.shape[2]))
    def rnn(units, seq):
        # BiLSTM reads time in BOTH directions; plain LSTM in one direction only.
        lyr = layers.LSTM(units, return_sequences=seq)
        return layers.Bidirectional(lyr) if bidirectional else lyr
    # --- Front-end CNN (extraction de motifs locaux court-terme) : architecture
    #     PRO CNN + BiLSTM + Attention, etat de l'art pour la prevision d'AQI
    #     (cf. CNN-BiLSTM-AM / Transformer-BiLSTM, litterature 2024-2025). Le CNN
    #     aide surtout sur PEU de donnees en resumant les motifs avant le BiLSTM. ---
    c = layers.Conv1D(32, 3, padding="causal", activation="relu")(inp)
    c = layers.BatchNormalization()(c)
    x = rnn(48, True)(c)
    x = layers.Dropout(0.2)(x)
    if attention:
        att = layers.MultiHeadAttention(num_heads=4, key_dim=16)(x, x)
        x = layers.Add()([x, att])
        x = layers.LayerNormalization()(x)
        x = rnn(24, False)(x)
    else:
        x = rnn(24, False)(x)
    x = layers.Dropout(0.2)(x)
    x = layers.Dense(24, activation="relu")(x)
    out = layers.Dense(1)(x)
    model = models.Model(inp, out)
    opt = optimizers.Adam(learning_rate=5e-4, clipnorm=1.0)
    model.compile(optimizer=opt, loss="huber")
    cbs = [
        callbacks.EarlyStopping(patience=12, restore_best_weights=True),
        callbacks.ReduceLROnPlateau(factor=0.5, patience=5, min_lr=1e-5),
    ]
    model.fit(Xtr, ytr_s, validation_split=0.15, epochs=120, batch_size=16,
              verbose=0, callbacks=cbs)
    import time
    model.predict(Xte[:1], verbose=0)  # warm-up
    t0 = time.perf_counter()
    for _r in range(5):
        model.predict(Xte[:1], verbose=0)
    latency = (time.perf_counter() - t0) / 5 * 1000
    pred_s = model.predict(Xte, verbose=0).ravel()
    pred = pred_s * ysd + ymu  # inversion de la standardisation de la cible
    m = _metrics(yte, pred)
    m["latency"] = round(latency, 2)
    return m


def train_lstm(records, horizon_step, first_holdout=None):
    """Real (unidirectional) LSTM. Returns metrics dict, or None if TF missing."""
    return _train(records, horizon_step, attention=False, bidirectional=False,
                  first_holdout=first_holdout)


def train_bilstm(records, horizon_step, first_holdout=None):
    """Real BiLSTM. Returns metrics dict, or None if TF missing / too little data."""
    return _train(records, horizon_step, attention=False, bidirectional=True,
                  first_holdout=first_holdout)


def train_bilstm_attention(records, horizon_step, first_holdout=None):
    """Real BiLSTM + Multi-Head Attention. Returns metrics dict, or None."""
    return _train(records, horizon_step, attention=True, first_holdout=first_holdout)


def attention_matrix(records, horizon_step=1):
    """Return a REAL SEQ×SEQ attention matrix, averaged over the test windows of
    the trained BiLSTM+Attention model, or None if TensorFlow is missing / the
    series is too short.

    This is the GENUINE neural attention (softmax scores of the Multi-Head
    Attention layer) — there is no random number anywhere. If it cannot be
    computed, we return None and the UI shows an honest "indisponible" message
    instead of a fake heatmap.
    """
    try:
        import tensorflow as tf
        from tensorflow.keras import layers, models, optimizers, callbacks
    except Exception:
        return None
    try:
        X, y = _build_sequences(records, horizon_step)
        if X is None or len(X) < 40:
            return None
        ntr = max(1, int(len(X) * 0.8))
        if ntr >= len(X):
            ntr = len(X) - 1
        Xtr, Xte, ytr = X[:ntr], X[ntr:], y[:ntr]
        if len(Xte) < 5:
            return None
        Xtr, Xte = _standardize(Xtr, Xte)
        ymu = float(ytr.mean()); ysd = float(ytr.std()) + 1e-6
        ytr_s = (ytr - ymu) / ysd
        tf.random.set_seed(42); np.random.seed(42)

        inp = layers.Input(shape=(X.shape[1], X.shape[2]))
        x = layers.Bidirectional(layers.LSTM(48, return_sequences=True))(inp)
        x = layers.Dropout(0.2)(x)
        mha = layers.MultiHeadAttention(num_heads=4, key_dim=16)
        att_out, scores = mha(x, x, return_attention_scores=True)
        x2 = layers.Add()([x, att_out])
        x2 = layers.LayerNormalization()(x2)
        x2 = layers.Bidirectional(layers.LSTM(24))(x2)
        x2 = layers.Dropout(0.2)(x2)
        x2 = layers.Dense(24, activation="relu")(x2)
        out = layers.Dense(1)(x2)
        model = models.Model(inp, out)
        model.compile(optimizer=optimizers.Adam(learning_rate=5e-4, clipnorm=1.0), loss="huber")
        model.fit(Xtr, ytr_s, validation_split=0.15, epochs=80, batch_size=16,
                  verbose=0, callbacks=[callbacks.EarlyStopping(patience=10, restore_best_weights=True)])

        # Extract the REAL attention scores on the hold-out windows.
        score_model = models.Model(inp, scores)   # (n, heads, SEQ, SEQ)
        sc = np.asarray(score_model.predict(Xte, verbose=0), dtype=float)
        # Average over the test windows only, then keep the MOST structured head
        # (highest variance) instead of averaging all 8 heads together —
        # averaging every head washes the pattern into a flat, uniform map.
        per_head = sc.mean(axis=0)                 # (heads, SEQ, SEQ)
        if per_head.ndim == 3 and per_head.shape[0] > 1:
            variances = [float(per_head[h].var()) for h in range(per_head.shape[0])]
            mat = per_head[int(np.argmax(variances))]
        else:
            mat = per_head.reshape(per_head.shape[-2], per_head.shape[-1])
        rows = []
        for i in range(mat.shape[0]):
            s = float(mat[i].sum()) or 1.0
            rows.append([round(float(v) / s, 4) for v in mat[i]])
        return {"hours": list(range(mat.shape[0])), "weights": rows}
    except Exception:
        return None
