# Migration Guide — 2026-05-13

After extracting the new ZIP over your existing folder, run **2 SQL migrations**
in this order:

```bash
# 1. The fuzzy / augment / hybrid migration (if not already run from previous ZIP)
mysql -u root gabes_tatenafas < db/migrations/2026-05-07-fuzzy-augment-hybrid.sql

# 2. The new zones migration — replaces seed zones with the 6 real Gabès locations
mysql -u root gabes_tatenafas < db/migrations/2026-05-13-zones-real-positions.sql
```

That's it. Open the application — the map should now show the 6 real positions:

| Zone        | Lat        | Lng         |
|-------------|------------|-------------|
| Centre Ville  | 33.885889  | 10.107319   |
| Chatt Salem   | 33.901649  | 10.100321   |
| Ghannouche    | 33.943053  | 10.066739   |
| Chenini       | 33.879796  | 10.063941   |
| El Bled       | 33.891530  | 10.089126   |
| Bouchamma     | 33.902802  | 10.052750   |

## Refresh live pollution from IQAir + WAQI (optional, recommended)

If you want **truly live numbers**, log in as `admin` and call:

```
http://localhost/gabes-tatenafas-v2/backend/api/iqair-refresh.php?force=1
```

This:
1. Calls IQAir + WAQI for each zone (using the new GPS coords).
2. Validates the data (IQR + modified Z-score outlier detection).
3. Fuses the sources via median (robust to one broken source).
4. Writes the fused `pollution_level` back into `zones`.
5. Recomputes `risk_scores` accordingly.

Trust score and outlier flags are journalled in `api_verification_log`.

## Chatbot

The chatbot now uses:
- `CURLOPT_SSL_VERIFYPEER = false` (WAMP has no CA bundle by default).
- Clearer error reporting — failures appear in `chatbot_logs.intent` as
  `groq-error|fb:curl=NN:message`.

If you see a curl=60 error in the logs, that's an SSL CA bundle issue. The
current configuration already bypasses it; if not, edit your `php.ini`:
```
curl.cainfo = "C:/wamp64/bin/php/php8.x.x/cacert.pem"
```
and download `cacert.pem` from <https://curl.se/docs/caextract.html>.

## Verify everything is OK

Open in your browser:
```
http://localhost/gabes-tatenafas-v2/verify-install.php
```

Each row should be **PASS**. A **WARN** on *"Trained GAN weights present"*
is normal until you run:
```
php scripts/train_gan.php
```

## Train and use the GAN (optional)

```bash
# 1. Augment training data (statistical, always works)
php scripts/augment_data.php

# 2. Train the pure-PHP GAN (~30-60s on a normal laptop)
php scripts/train_gan.php
# Output: storage/gan/weights.json (~55 KB)

# 3. Generate 50 synthetic series per zone, write to risk_scores_augmented
php scripts/gan_generate.php --per-zone=50
```

You do **NOT** need to run `pip install -r scripts/requirements.txt` — that
file is for the optional Python escalation only. Skip it.

## Forecast metrics

The forecast page (Admin / Health roles) calls `forecast-metrics.php` which
returns the 5 academic metrics (MAE / RMSE / MAPE / R² / SMAPE) for the
AR(7) + Multi-EWMA hybrid model, plus the optimal weight α found by grid
search. Numbers are stored in `forecast_metrics` for historical comparison.
