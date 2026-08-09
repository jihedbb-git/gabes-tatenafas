"""PART 5.5 - Anomaly detection: Autoencoder reconstruction error combined with
Isolation Forest. Trains on normal days only.

References: Liu et al. (2008) Isolation Forest; Goodfellow et al. (2016).
"""
from __future__ import annotations
import numpy as np
from sklearn.ensemble import IsolationForest


def build_autoencoder(n_features=27):
    from tensorflow import keras
    inp = keras.Input(shape=(n_features,))
    e = keras.layers.Dense(27, activation="relu")(inp)
    e = keras.layers.Dense(16, activation="relu")(e)
    z = keras.layers.Dense(8, activation="relu")(e)     # latent
    d = keras.layers.Dense(16, activation="relu")(z)
    out = keras.layers.Dense(n_features, activation="linear")(d)
    ae = keras.Model(inp, out)
    ae.compile(optimizer=keras.optimizers.Adam(1e-3), loss="mse")
    return ae


def classify_anomaly(feat):
    """feat: dict with so2, pm10, pm25, no2, wind. Returns anomaly type string.

    Ordre du plus specifique au moins specifique : on teste d'abord la tempete
    de sable et l'evenement chimique multi-polluants, puis seulement apres le
    pic industriel (SO2). Sinon un SO2 eleve -- frequent a Ghannouche -- ferait
    classer TOUTES les anomalies comme "pic industriel" et masquerait les
    tempetes de sable et les rejets chimiques.
    """
    so2 = feat.get("so2", 0)
    pm10 = feat.get("pm10", 0)
    wind = feat.get("wind", 0)
    high = sum(1 for k in ("so2", "pm25", "pm10", "no2") if feat.get(k, 0) > 150)
    # 1) Tempete de sable : PM10 tres eleve porte par un vent fort.
    if pm10 > 300 and wind > 35:
        return "sandstorm"
    # 2) Evenement chimique : au moins 3 polluants eleves simultanement.
    if high >= 3:
        return "chemical_event"
    # 3) Pic industriel : SO2 dominant (signature de Ghannouche).
    if so2 > 200:
        return "industrial_spike"
    return "data_error"


class AnomalyDetector:
    def __init__(self, n_features=27):
        self.n_features = n_features
        self.ae = None
        self.threshold = None
        self.iso = IsolationForest(n_estimators=100, contamination=0.05, random_state=42)

    def fit(self, X_normal, epochs=200):
        self.ae = build_autoencoder(self.n_features)
        self.ae.fit(X_normal, X_normal, epochs=epochs, batch_size=32, verbose=0)
        recon = self.ae.predict(X_normal, verbose=0)
        errs = np.mean((X_normal - recon) ** 2, axis=1)
        self.threshold = float(errs.mean() + 3 * errs.std())
        self.iso.fit(X_normal)
        return self

    def score(self, X):
        recon = self.ae.predict(X, verbose=0)
        ae_err = np.mean((X - recon) ** 2, axis=1)
        iso_score = self.iso.decision_function(X)
        detected = ae_err > self.threshold
        anomaly_score = ae_err / (self.threshold + 1e-9)
        return {"ae_error": ae_err, "iso_score": iso_score,
                "detected": detected, "anomaly_score": anomaly_score}


if __name__ == "__main__":
    print("anomaly_detector: Autoencoder + IsolationForest (needs TensorFlow to train AE).")
