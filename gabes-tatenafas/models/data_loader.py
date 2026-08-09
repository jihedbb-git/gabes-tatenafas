"""Load REAL training data from the Gabès-Tatenafas MySQL database.

v3 — Grounded on the REAL multivariate `api_readings` history.

ROOT-CAUSE FIX
--------------
The previous loader used only the LATEST `api_readings` snapshot, so every
pollutant/weather feature was CONSTANT across a zone's whole series, and the
target came from jittered risk scores (pure noise). The models had nothing to
learn -> negative R2, F1 ~0.31.

This version rebuilds each zone's training frame from the REAL time-varying
`api_readings` measurements (final_aqi + pm25/pm10/so2/no2/o3/co + weather),
interpolated onto an hourly grid so the pollutant<->AQI relationship is
preserved, then densified with correlation-preserving tiling so the ML/DL models
have enough samples. Zones without real readings fall back to a realistic
correlated synthetic series anchored on the zone category.

Output: dict zone_id -> pandas.DataFrame with an hourly 'aqi' column plus the
pollutant / weather columns needed to build the 27-feature vector.
"""
from __future__ import annotations
import datetime as dt
import math
import random
import numpy as np

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None

try:
    from . import db_config
except Exception:  # allow running as a plain script
    import db_config

# zone pollution factor by category (fallback + calibration)
CAT_FACTOR = {"industrial": 1.6, "urban": 1.1, "agricultural": 0.85,
              "coastal": 1.15, "residential": 1.2, "rural": 0.8}

# category -> typical baseline AQI (used only for zones with no real readings)
CAT_BASE_AQI = {"industrial": 150.0, "urban": 95.0, "coastal": 88.0,
                "agricultural": 70.0, "residential": 100.0, "rural": 62.0}

# real api_readings column -> frame key
API_FIELDS = {
    "final_aqi": "aqi",
    "final_pm25": "pm25", "final_pm10": "pm10",
    "final_so2": "so2", "final_no2": "no2",
    "final_o3": "o3", "final_co": "co",
    "final_temperature": "temperature", "final_humidity": "humidity",
    "final_wind_speed": "wind_speed", "final_wind_direction": "wind_direction",
    "final_pressure": "pressure", "accuw_uv_index": "uv_index",
    "accuw_forecast_3h": "forecast_3h", "accuw_forecast_6h": "forecast_6h",
}

DEFAULTS = {"aqi": 90, "pm25": 28, "pm10": 45, "so2": 30, "no2": 25, "o3": 55,
            "co": 1.2, "temperature": 26, "humidity": 54, "wind_speed": 15,
            "wind_direction": 180, "pressure": 1010, "uv_index": 6,
            "forecast_3h": 0, "forecast_6h": 0}

POLLUTANTS = ["aqi", "pm25", "pm10", "so2", "no2", "o3", "co"]
TARGET_LEN = 2016  # ~12 weeks of hourly rows per zone
HOLDOUT_FRAC = 0.2  # Fix #1: most-recent REAL, un-tiled tail reserved for eval
MAX_GAP_HOURS = 6   # Fix #2: interpolation beyond this gap is NOT a valid target


def _fetchall(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def load_zones(conn):
    cur = conn.cursor(); cur.execute(
        "SELECT id, name, name_ar, category, population, pollution_level, lat, lng FROM zones")
    rows = _fetchall(cur); cur.close(); return rows


def load_latest_readings(conn):
    """Latest api_readings row per city_id -> dict city_id -> row (kept for compat)."""
    cur = conn.cursor(); cur.execute(
        "SELECT * FROM api_readings ORDER BY timestamp DESC")
    rows = _fetchall(cur); cur.close()
    out = {}
    for r in rows:
        cid = str(r["city_id"])
        if cid not in out:
            out[cid] = r
    return out


def load_api_history(conn):
    """Full api_readings history grouped by city_id -> list of rows (time asc)."""
    cur = conn.cursor()
    cols = ", ".join(["city_id", "timestamp"] + list(API_FIELDS.keys()))
    cur.execute("SELECT " + cols + " FROM api_readings ORDER BY city_id, timestamp")
    rows = _fetchall(cur); cur.close()
    hist = {}
    for r in rows:
        hist.setdefault(str(r["city_id"]), []).append(r)
    return hist


def load_api_augmented(conn):
    """Synthetic MULTIVARIATE rows produced by models/augment_db.py (CGAN /
    statistical), grouped by city_id -> list of rows. Empty dict if the table
    is absent (augmentation not run yet)."""
    try:
        cur = conn.cursor()
        cols = ", ".join(["city_id", "timestamp"] + list(API_FIELDS.keys()))
        cur.execute("SELECT " + cols + " FROM api_readings_augmented ORDER BY city_id, timestamp")
        rows = _fetchall(cur); cur.close()
    except Exception:
        return {}
    hist = {}
    for r in rows:
        hist.setdefault(str(r["city_id"]), []).append(r)
    return hist


def load_zone_series(conn, zone_id):
    """Hourly score series for a zone from risk_scores_augmented (+ risk_scores).
    Kept for backward compatibility / secondary fallback."""
    cur = conn.cursor()
    cur.execute("SELECT synthetic_at AS t, score FROM risk_scores_augmented "
                "WHERE zone_id=%s ORDER BY synthetic_at", (zone_id,))
    rows = _fetchall(cur)
    cur.execute("SELECT computed_at AS t, score FROM risk_scores "
                "WHERE zone_id=%s ORDER BY computed_at", (zone_id,))
    rows += _fetchall(cur)
    cur.close()
    rows = [r for r in rows if r["t"] is not None]
    rows.sort(key=lambda r: r["t"])
    return rows


# --------------------------------------------------------------------------
# REAL api_readings -> dense hourly multivariate frame
# --------------------------------------------------------------------------
def _epoch(t):
    if isinstance(t, dt.datetime):
        return t.timestamp()
    try:
        return dt.datetime.strptime(str(t), "%Y-%m-%d %H:%M:%S").timestamp()
    except Exception:
        return dt.datetime.now().timestamp()


def _num(v, default):
    try:
        if v is None:
            return float(default)
        return float(v)
    except Exception:
        return float(default)


def _interp_hourly(rows):
    """Interpolate real readings onto a regular hourly grid (the real backbone).
    All variables are interpolated from the SAME real rows, so the physical
    pollutant<->AQI correlations are preserved."""
    ep = np.array([_epoch(r["timestamp"]) for r in rows], dtype=float)
    order = np.argsort(ep)
    ep = ep[order]
    rows = [rows[i] for i in order]
    # drop duplicate timestamps (np.interp requires strictly increasing x)
    keep = np.concatenate(([True], np.diff(ep) > 0))
    ep = ep[keep]
    rows = [r for r, k in zip(rows, keep) if k]
    if len(ep) < 2:
        return None
    n_hours = int((ep[-1] - ep[0]) // 3600) + 1
    n_hours = max(n_hours, 72)
    grid = np.linspace(ep[0], ep[-1], n_hours)
    frame = {}
    for col, key in API_FIELDS.items():
        vals = np.array([_num(r.get(col), DEFAULTS[key]) for r in rows], dtype=float)
        frame[key] = np.interp(grid, ep, vals)
    # Fix #2: flag each hourly grid point that sits within MAX_GAP_HOURS of a
    # REAL sample. Points far from any real reading are pure interpolation across
    # a large gap and must NOT be trusted as honest evaluation targets.
    near_real = np.array(
        [bool(np.min(np.abs(ep - g)) <= MAX_GAP_HOURS * 3600) for g in grid],
        dtype=bool,
    )
    return frame, near_real


def _clamp_record(rec):
    rec["aqi"] = max(5.0, rec["aqi"])
    for k in POLLUTANTS:
        if k != "aqi":
            rec[k] = max(0.0, rec[k])
    rec["humidity"] = min(100.0, max(0.0, rec["humidity"]))
    rec["wind_speed"] = max(0.0, rec["wind_speed"])
    rec["uv_index"] = max(0.0, rec["uv_index"])
    return rec


def _aug_rows_to_recs(rows):
    """Convert augmented api_readings rows into training records (same keys as
    the real densified frame)."""
    recs = []
    for r in rows:
        rec = {"timestamp": r.get("timestamp")}
        for col, key in API_FIELDS.items():
            rec[key] = _num(r.get(col), DEFAULTS[key])
        rec = _clamp_record(rec)
        rec["_holdout"] = False   # augmented rows are TRAIN-ONLY (Fix #1)
        rec["_synth"] = False
        recs.append(rec)
    return recs


def _retime(recs):
    """Reassign a clean sequential hourly timeline so lag features stay valid
    after concatenating augmented (older) + real (recent) records."""
    n = len(recs)
    t0 = dt.datetime.now() - dt.timedelta(hours=n)
    for i, rec in enumerate(recs):
        rec["timestamp"] = t0 + dt.timedelta(hours=i)
    return recs


def _densify(frame, target_len):
    """Tile the real hourly backbone with correlation-preserving variation until it
    reaches target_len rows. One multiplicative factor per tile scales the whole
    pollutant+AQI group together (keeps pm/so2<->AQI correlation); weather gets
    mild independent noise. Temporal order is preserved so lag features stay
    meaningful."""
    keys = list(frame.keys())
    H = len(frame["aqi"])
    cols = {k: [] for k in keys}
    tile = 0
    while len(cols["aqi"]) < target_len:
        f = 1.0 + 0.18 * math.sin(tile / 3.0) + random.gauss(0, 0.05)
        f = max(0.6, min(1.6, f))
        for i in range(H):
            for k in keys:
                base = float(frame[k][i])
                if k in POLLUTANTS:
                    val = base * f + random.gauss(0, max(1.0, abs(base) * 0.04))
                elif k == "wind_direction":
                    val = (base + random.gauss(0, 8)) % 360
                else:
                    val = base + random.gauss(0, max(0.5, abs(base) * 0.03))
                cols[k].append(val)
            if len(cols["aqi"]) >= target_len:
                break
        tile += 1
    n = min(target_len, len(cols["aqi"]))
    t0 = dt.datetime.now() - dt.timedelta(hours=n)
    recs = []
    for i in range(n):
        rec = {"timestamp": t0 + dt.timedelta(hours=i)}
        for k in keys:
            rec[k] = float(cols[k][i])
        rec = _clamp_record(rec)
        rec["_holdout"] = False   # densified data is TRAIN-ONLY (Fix #1)
        rec["_synth"] = False
        recs.append(rec)
    return recs


def _synthetic_zone_frame(zone, target_len):
    """Realistic correlated multivariate series for a zone with no real readings.
    Pollutants are derived from the AQI so pm/so2<->AQI stays correlated."""
    cat = (zone.get("category") or "urban").lower()
    base = CAT_BASE_AQI.get(cat, 95.0)
    so2_boost = 1.8 if cat == "industrial" else 1.0
    t0 = dt.datetime.now() - dt.timedelta(hours=target_len)
    prev = base
    recs = []
    for i in range(target_len):
        hour = i % 24
        day = (i // 24) % 7
        diurnal = 1.0 + 0.22 * math.sin((hour - 6) / 24 * 2 * math.pi) \
            + (0.12 if (6 <= hour <= 9 or 16 <= hour <= 19) else 0.0)
        weekly = 1.0 + 0.06 * math.sin(day / 7 * 2 * math.pi)
        target = base * diurnal * weekly
        aqi = 0.75 * prev + 0.25 * target + random.gauss(0, base * 0.05)
        aqi = max(10.0, aqi)
        prev = aqi
        rec = {
            "timestamp": t0 + dt.timedelta(hours=i),
            "aqi": aqi,
            "pm25": aqi * 0.30 + random.gauss(0, 2),
            "pm10": aqi * 0.48 + random.gauss(0, 3),
            "so2": aqi * 0.22 * so2_boost + random.gauss(0, 2),
            "no2": aqi * 0.20 + random.gauss(0, 2),
            "o3": aqi * 0.35 + random.gauss(0, 3),
            "co": aqi * 0.012 + random.gauss(0, 0.05),
            "temperature": 26 + 6 * math.sin((hour - 9) / 24 * 2 * math.pi) + random.gauss(0, 1),
            "humidity": 55 - 12 * math.sin((hour - 9) / 24 * 2 * math.pi) + random.gauss(0, 3),
            "wind_speed": 14 + random.gauss(0, 3),
            "wind_direction": (180 + random.gauss(0, 30)) % 360,
            "pressure": 1012 + random.gauss(0, 2),
            "uv_index": 6 * max(0.0, math.sin((hour - 6) / 12 * math.pi)) + random.gauss(0, 0.5),
            "forecast_3h": 0.0, "forecast_6h": 0.0,
        }
        recs.append(_clamp_record(rec))
    # Fix #4: zone has NO real readings -> mark synthetic; last slice is the
    # temporal hold-out so training still runs.
    cut = max(1, int(len(recs) * (1 - HOLDOUT_FRAC)))
    for j, rec in enumerate(recs):
        rec["_synth"] = True
        rec["_holdout"] = j >= cut
    return recs


def _split_and_densify(frame, near_real, target_len):
    """Fix #1 + #2: reserve the most-recent REAL hours as an un-tiled hold-out,
    and densify ONLY the older training portion. The evaluation tail therefore
    contains genuine (near-real) measurements that never leak into training."""
    H = len(frame["aqi"])
    cut = max(1, int(H * (1 - HOLDOUT_FRAC)))
    if cut >= H:
        cut = H - 1
    train_frame = {k: v[:cut] for k, v in frame.items()}
    train_recs = _densify(train_frame, target_len)   # tiled, TRAIN-ONLY
    t0 = dt.datetime.now()

    def _tail(require_near):
        out = []
        for i in range(cut, H):
            if require_near and not bool(near_real[i]):
                continue  # Fix #2: skip fabricated big-gap hours as eval targets
            rec = {"timestamp": t0 + dt.timedelta(hours=len(out))}
            for k in frame.keys():
                rec[k] = float(frame[k][i])
            rec = _clamp_record(rec)
            rec["_holdout"] = True
            rec["_synth"] = False
            out.append(rec)
        return out

    tail = _tail(require_near=True)
    if len(tail) < 8:                 # too sparse -> keep the full contiguous tail
        tail = _tail(require_near=False)
    return train_recs + tail


def build_frames(min_rows=48, target_len=TARGET_LEN):
    """Return dict zone_id -> DataFrame built from the REAL api_readings history
    (correlation-preserving densification), or a realistic synthetic/simulated
    fallback so training always has learnable data."""
    random.seed(42)
    np.random.seed(42)
    conn = db_config.try_connection()
    frames = {}
    if conn is not None:
        try:
            zones = load_zones(conn)
            hist = load_api_history(conn)
            aug_hist = load_api_augmented(conn)
            real_zones, synth_zones, aug_note = [], [], []
            for z in zones:
                zid = z["id"]
                rows = hist.get(str(zid)) or []
                backbone = _interp_hourly(rows) if len(rows) >= 6 else None
                if backbone is not None:
                    frame_cols, near_real = backbone
                    real_recs = _split_and_densify(frame_cols, near_real, target_len)
                    real_zones.append(zid)
                else:
                    real_recs = _synthetic_zone_frame(z, target_len)
                    synth_zones.append(zid)
                # CGAN / statistical augmented rows are OLDER (prepended), so the
                # recent tail used for the 80/20 hold-out stays REAL -> the
                # reported metrics remain honest (train on real+synthetic,
                # evaluate on real).
                aug_rows = aug_hist.get(str(zid)) or []
                if aug_rows:
                    aug_recs = _aug_rows_to_recs(aug_rows)
                    recs = _retime(aug_recs + real_recs)
                    aug_note.append(f"{zid}(+{len(aug_recs)})")
                else:
                    recs = real_recs
                frames[zid] = pd.DataFrame(recs) if pd is not None else recs
            conn.close()
            print("[data_loader] REAL api_readings backbone for zones", real_zones,
                  "| synthetic (no readings) for zones", synth_zones,
                  "| CGAN-augmented:", aug_note)
            if frames:
                return frames
        except Exception as e:
            print("[data_loader] real load failed, will simulate:", e)

    # ---- global fallback: simulate anchored on real zone factors ----
    print("[data_loader] Using simulated fallback anchored on zones.")
    try:
        from . import data_simulator as sim
    except Exception:
        import data_simulator as sim
    for cid, factor in sim.CITIES.items():
        rows = sim.simulate_city(cid, factor, hours=1500)
        recs = [{
            "timestamp": r["timestamp"], "aqi": r["final_aqi"],
            "pm25": r["final_pm25"], "pm10": r["final_pm10"], "so2": r["final_so2"],
            "no2": r["final_no2"], "temperature": r["final_temperature"],
            "humidity": r["final_humidity"], "wind_speed": r["final_wind_speed"],
            "wind_direction": 180, "pressure": 1010, "uv_index": 6,
            "forecast_3h": 0, "forecast_6h": 0,
        } for r in rows]
        # Fix #4: simulated fallback is synthetic; reserve a temporal hold-out.
        cut = max(1, int(len(recs) * (1 - HOLDOUT_FRAC)))
        for j, rec in enumerate(recs):
            rec["_synth"] = True
            rec["_holdout"] = j >= cut
        frames[cid] = pd.DataFrame(recs) if pd is not None else recs
    return frames


if __name__ == "__main__":
    fr = build_frames()
    for k, v in fr.items():
        n = len(v)
        print("zone", k, "rows", n)
