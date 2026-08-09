# CHANGELOG — Gabès Tatenafas

## 2026-05-13 — Final QA / delivery

### 1. Zones — real-world positions (Gabès)
- `db/schema.sql` — replaced default zone list with the **6 zones** explicitly
  requested by the project owner (Centre Ville, Chatt Salem, Ghannouche, Chenini,
  El Bled, Bouchamma) with the exact GPS coordinates from Google Maps:

  | # | Name        | Lat        | Lng         | Notes                              |
  |---|-------------|------------|-------------|------------------------------------|
  | 1 | Centre Ville  | 33.885889  | 10.107319   | Bab Bhar / downtown traffic        |
  | 2 | Chatt Salem   | 33.901649  | 10.100321   | Downwind of chemical complex       |
  | 3 | Ghannouche    | 33.943053  | 10.066739   | Industrial — phosphate complex     |
  | 4 | Chenini       | 33.879796  | 10.063941   | Semi-rural oasis west of Gabès     |
  | 5 | El Bled       | 33.891530  | 10.089126   | Old town, dense residential        |
  | 6 | Bouchamma     | 33.902802  | 10.052750   | Mixed residential west             |

- `db/migrations/2026-05-13-zones-real-positions.sql` — idempotent migration
  for **existing installs**: UPDATE rows 1..6 to the new spec, archive rows 7..8
  with population=0 so foreign keys stay valid. **Run it once after extracting**:
  ```
  mysql -u root gabes_tatenafas < db/migrations/2026-05-13-zones-real-positions.sql
  ```

### 2. Chatbot Nafass — SSL fix + better error reporting
- `backend/api/chatbot.php` — added `CURLOPT_SSL_VERIFYPEER => false` and
  `CURLOPT_SSL_VERIFYHOST => 0`. WAMP on Windows lacks a CA bundle by default
  which caused cURL error 60 (silent failure → "ne marche pas").
- Errors are now surfaced as `curl=NN:message` in `chatbot_logs.intent` instead
  of generic `groq-error`. Open phpMyAdmin → `chatbot_logs` to debug.
- `backend/lib/groq_client.php` already had `GROQ_CLIENT_INSECURE = true`
  (for recommendations / tips / diary / triage / weekly-summary endpoints).

### 3. System language — English by default
- `frontend/index.php`, `frontend/login.php`, `frontend/register.php` and
  `frontend/manifest.json` all use `lang="en"` / `"lang": "en"`.
- Seed labels (`users_roles`, `alerts`, `reports`, `symptoms`, `chatbot_logs`,
  `notifications`, `reports_pdf`, `school_status`) translated to English.
- The chatbot system prompt explicitly states *"Default language is English."*
  Replies still adapt if the user writes in FR / AR / Tunisian Darja.

### 4. Realistic pollution numbers
- `db/schema.sql` — seeded `pollution_level` values calibrated for the real
  pollution map of Gabès (industrial north-east 71–82, downtown 47–54,
  west residential 38, rural 27).
- `db/schema.sql` — `risk_scores` seeded with matching values so the
  dashboard has historical context on day 1.
- `backend/api/dashboard.php` — average risk is now returned with **1 decimal
  precision** (e.g. `57.4` instead of `57`) for a more realistic display.
- `backend/lib/iqair.php` — fixed undefined-variable bug when the multi-source
  verifier succeeds (was returning station=undef). All paths now safely fall
  back to `multi-source-fusion` station label.

### 5. Academic features confirmed active
The verification page `verify-install.php` now lists each artefact and runs a
live 5-epoch GAN test:

  - **Fuzzy Mamdani** — used in 7 endpoints (`dashboard`, `diary-ai`, `triage`,
    `tips`, `weekly-summary`, `recommendations`, `chatbot`).
  - **API verifier** — IQAir + WAQI fusion with IQR + Z-score outlier detection.
  - **Data augmentation** — statistical (PHP, always active) **and** GAN
    (PHP pur, no Python dependency).
  - **Hybrid forecast ML/DL** — AR(7) + Multi-EWMA sigmoid ensemble, with
    MAE / RMSE / MAPE / R² / SMAPE metrics in `forecast_metrics`.

Open `http://localhost/gabes-tatenafas-v2/verify-install.php` in the browser.
Every line should be **PASS** (or **WARN** for "Trained GAN weights present"
if you have not run `php scripts/train_gan.php` yet).

### 6. Bulletproof "Refresh from IQAir" button

The Settings → "Refresh from IQAir" button used to crash with
`Unexpected token '<', '<!DOCTYPE'... is not valid JSON` whenever a PHP
warning, notice or fatal error fired anywhere in the IQAir / WAQI stack
(WAMP with `display_errors=On` injects a styled HTML page into the
response, which is not JSON).

Fixes:
- `backend/api/iqair-refresh.php` — now ALWAYS returns JSON:
  - `display_errors=0` / `html_errors=0` set at the top
  - `register_shutdown_function` catches `E_ERROR / E_PARSE / E_CORE_ERROR /
    E_COMPILE_ERROR` and converts them into a JSON `{ok:false, error:"php-fatal: ..."}`
  - the whole endpoint is wrapped in `try / catch (Throwable)` so any
    runtime exception becomes a JSON error
  - the legacy `fn($r) => ...` arrow functions were replaced with
    traditional `function ($r) { ... }` closures for PHP 7.0 compatibility
    (defensive — `fn()` requires PHP 7.4+).
- `frontend/scripts/pages/settings.js` — the JS now reads the response as
  text first, attempts to `JSON.parse`, and on failure shows the actual
  server output (first 400 chars) so debugging on WAMP is straightforward.
  It also displays the new `trust=…` score returned by the multi-source
  verifier.
- `frontend/pages/settings.html` — copy fixed to "6 zones" (not 8) and now
  explicitly mentions the IQAir + WAQI dual-source fusion.
- `scripts/refresh_pollution.php` — its arrow functions were also replaced
  with traditional closures (PHP 7.0+ compatibility).

