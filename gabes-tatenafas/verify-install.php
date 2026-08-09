<?php
/**
 * verify-install.php
 * ─────────────────────────────────────────────────────────────────
 * Place this file at the project root (next to electron/, frontend/,
 * backend/) and open it in your browser:
 *   http://localhost/gabes-tatenafas-v2/verify-install.php
 *
 * It checks, one by one, EVERY modification of the 2026-05-07 release
 * (fuzzy logic, multi-source verification, hybrid forecast) and prints
 * PASS / FAIL with the reason. NO DATA is modified.
 *
 * Use this to confirm the PR was correctly extracted and the SQL
 * migration was run before complaining the modifications "don't appear".
 */

declare(strict_types=1);
error_reporting(E_ALL);
ini_set('display_errors', '1');

header('Content-Type: text/html; charset=utf-8');

$ROOT = __DIR__;

/* ────────────────────────────── helpers ────────────────────────── */
$pass = $fail = $warn = 0;
$rows = [];

function row(string $section, string $check, bool $ok, string $detail = '', bool $isWarn = false): void
{
    global $rows, $pass, $fail, $warn;
    $rows[] = ['section' => $section, 'check' => $check, 'ok' => $ok, 'detail' => $detail, 'warn' => $isWarn];
    if ($isWarn) $warn++;
    elseif ($ok) $pass++;
    else $fail++;
}

function file_contains(string $path, string $needle): bool
{
    if (!is_file($path)) return false;
    $content = (string)@file_get_contents($path);
    return strpos($content, $needle) !== false;
}

/* ────────────────────────────── 1. FILES ───────────────────────── */
$newFiles = [
    /* Phase 1 — API verification + augmentation */
    'backend/config/waqi.php'                            => 'WAQI config',
    'backend/lib/waqi.php'                               => 'WAQI client',
    'backend/lib/api_verifier.php'                       => 'Multi-source verifier (IQR + Z-score)',
    'backend/lib/data_augment.php'                       => 'Data augmentation (jittering/warping/bootstrap)',
    'backend/lib/gan.php'                                => 'Pure-PHP GAN (Generator + Discriminator + backprop)',
    'backend/api/verify-data.php'                        => 'Admin endpoint to trigger verification',
    'scripts/augment_data.php'                           => 'CLI: augment training data',
    'scripts/train_gan.php'                              => 'CLI: train the pure-PHP GAN',
    'scripts/gan_generate.php'                           => 'CLI: generate samples from trained GAN',
    'scripts/train_augment.py'                           => 'Optional Python: TimeGAN/Diffusion',
    /* Phase 2 — Fuzzy Mamdani engine */
    'backend/lib/fuzzy.php'                              => 'Mamdani fuzzy engine',
    'backend/lib/fuzzy_context.php'                      => 'Shared fuzzy helper for ALL endpoints',
    'backend/config/fuzzy_rules.php'                     => 'Fuzzy rule base (5 vars × 25 rules)',
    /* Phase 3 — Hybrid forecast */
    'backend/lib/forecast_ml.php'                        => 'AR(7) + multi-EWMA + ensemble',
    'backend/api/forecast-metrics.php'                   => 'Forecast metrics endpoint',
    'scripts/predict.php'                                => 'CLI: hybrid forecast prediction',
    'scripts/train_forecast.py'                          => 'Optional Python: XGBoost+LSTM',
    'scripts/requirements.txt'                           => 'Python dependencies',
    /* Frontend — admin Forecast page */
    'frontend/pages/forecast.html'                       => 'Forecast admin HTML',
    'frontend/scripts/pages/forecast.js'                 => 'Forecast admin JS',
    'frontend/styles/forecast.css'                       => 'Forecast admin CSS',
    /* DB + docs */
    'db/migrations/2026-05-07-fuzzy-augment-hybrid.sql'  => 'SQL migration (NEW TABLES)',
    'MODIFICATIONS-2026.md'                              => 'Full modifications documentation',
];

foreach ($newFiles as $rel => $label) {
    $full = $ROOT . DIRECTORY_SEPARATOR . $rel;
    $ok   = is_file($full);
    row('Files added', $rel, $ok, $ok ? "✓ $label (".filesize($full)." bytes)" : "MISSING — copy from .zip");
}

/* ────────────────────────────── 2. PATCHED FILES ───────────────── */
$patches = [
    ['backend/lib/iqair.php',           "api_verifier.php",        'iqair.php now calls verify_zone() (multi-source)'],
    ['backend/api/recommendations.php', "fuzzy_recommend",          'Recommendations call fuzzy_recommend() FIRST'],
    ['backend/api/dashboard.php',       "fuzzy_for_user",           'Dashboard endpoint includes fuzzy block'],
    ['backend/api/diary-ai.php',        "fuzzy_for_user",           'Diary AI is fuzzy-aware'],
    ['backend/api/triage.php',          "fuzzy_for_user",           'Symptom triage is fuzzy-aware'],
    ['backend/api/tips.php',            "fuzzy_for_user",           'Daily tips are fuzzy-aware'],
    ['backend/api/weekly-summary.php',  "fuzzy_for_user",           'Weekly summary is fuzzy-aware'],
    ['backend/api/chatbot.php',         "fuzzy_for_user",           'Chatbot system prompt is fuzzy-aware'],
    ['backend/config/groq.php',         "FUZZY-LOGIC RISK",         'Groq system prompt embeds fuzzy block'],
    ['backend/lib/forecast.php',        "forecast_ml",              'Forecast uses AR(7) + EWMA ensemble'],
    ['backend/lib/auth.php',            "'forecast'",               'Forecast route allowed for admin/health'],
    ['frontend/index.php',              "forecast.css",             'Forecast nav + CSS included'],
    ['frontend/scripts/router.js',      "forecast",                 'Router knows the forecast route'],
    ['frontend/scripts/pages/dashboard.js', "renderFuzzyDetails",   'Dashboard renders fuzzy panel'],
    ['frontend/scripts/pages/diary.js', "Fuzzy Mamdani",            'Diary page renders fuzzy panel'],
    ['frontend/scripts/pages/symptoms.js', "Fuzzy",                 'Symptoms triage shows fuzzy badge'],
    ['frontend/styles/dashboard.css',   "dash-reco-fuzzy",          'CSS for fuzzy panel'],
    ['db/schema.sql',                   "fuzzy_reco_logs",          'Schema includes fuzzy_reco_logs table'],
];
foreach ($patches as [$rel, $needle, $label]) {
    $full = $ROOT . DIRECTORY_SEPARATOR . $rel;
    $ok = file_contains($full, $needle);
    row('Files patched', $rel, $ok, $ok ? "✓ $label" : "PATCH MISSING — re-extract the .zip over your project");
}

/* ────────────────────────────── 3. DB ──────────────────────────── */
$dbFile = $ROOT . '/backend/config/database.php';
$pdo = null; $dbName = '?';
if (is_file($dbFile)) {
    try {
        require_once $dbFile;
        if (function_exists('db')) $pdo = db();
        if ($pdo) {
            $dbName = (string)$pdo->query("SELECT DATABASE()")->fetchColumn();
            row('Database', 'Connection', true, "✓ Connected to `$dbName`");
        }
    } catch (Throwable $e) {
        row('Database', 'Connection', false, 'PDO error: ' . $e->getMessage());
    }
} else {
    row('Database', 'database.php', false, 'backend/config/database.php is missing');
}

/* Tables created by the 2026-05-07 migration */
$tables = [
    'fuzzy_reco_logs'         => 'fuzzy decision audit log (point 1)',
    'api_verification_log'    => 'multi-source verification log (point 2)',
    'risk_scores_augmented'   => 'synthetic samples from augmentation (point 2)',
    'waqi_cache'              => 'WAQI API cache (point 2)',
    'forecast_predictions'    => 'hybrid forecast outputs (point 3)',
    'forecast_metrics'        => 'MAE/RMSE/MAPE/R²/SMAPE (point 3)',
];
if ($pdo) {
    foreach ($tables as $t => $why) {
        try {
            $exists = (int)$pdo->query("SELECT COUNT(*) FROM information_schema.TABLES
                                          WHERE TABLE_SCHEMA = DATABASE()
                                            AND TABLE_NAME   = ".$pdo->quote($t))->fetchColumn() > 0;
            row('DB tables', $t, $exists,
                $exists
                    ? "✓ $why"
                    : "MISSING — run:  mysql -u root $dbName < db/migrations/2026-05-07-fuzzy-augment-hybrid.sql");
        } catch (Throwable $e) {
            row('DB tables', $t, false, $e->getMessage());
        }
    }
}

/* ============================================================== *
 *  UPGRADE v6 (2026-07-15) — Scientific ML upgrade checks
 * ============================================================== */
$v6Files = [
    'db/migrations/2026-07-15-upgrade-v6.sql'      => 'v6 SQL migration',
    'backend/lib/anomaly_correlation.php'          => 'Part 32 — anomaly × citizen-report correlation',
    'backend/lib/rule_calibration.php'             => 'Part 33 — rule auto-calibration',
    'backend/lib/school_forecast.php'              => 'Part 35 — predictive school mode',
    'backend/lib/data_quality_validator.php'       => 'Part 45 — upstream data validation',
    'backend/lib/rag_context.php'                  => 'Part 47 — RAG context builder',
    'backend/api/school-forecast.php'              => 'Part 35 — school forecast endpoint',
    'backend/api/model-registry.php'               => 'Part 43/44 — registry & A/B endpoint',
    'backend/api/digital-twin.php'                 => 'Part 48 — digital twin endpoint',
    'frontend/pages/model-registry.html'           => 'Part 43 — registry page',
    'frontend/pages/digital-twin.html'             => 'Part 48 — digital twin page',
    'frontend/scripts/pages/model-registry.js'     => 'Part 43 — registry JS',
    'frontend/scripts/pages/digital-twin.js'       => 'Part 48 — digital twin JS',
    'models/tft_forecaster.py'                     => 'Part 36 — TFT',
    'models/gnn_spatial.py'                        => 'Part 37 — GNN spatial',
    'models/pinn_dispersion.py'                    => 'Part 38 — PINN gaussian plume',
    'models/conformal_predictor.py'                => 'Part 39 — conformal prediction',
    'models/xai_counterfactual.py'                 => 'Part 40 — counterfactual (DiCE)',
    'models/calibration_eval.py'                   => 'Part 42 — calibration / Brier',
    'models/model_registry_manager.py'             => 'Part 43 — model registry',
    'models/ab_testing_controller.py'              => 'Part 44 — A/B testing',
    'models/rl_ensemble_agent.py'                  => 'Part 46 — RL ensemble (LinUCB)',
    'models/digital_twin.py'                       => 'Part 48 — digital twin sim',
];
foreach ($v6Files as $rel => $label) {
    $abs = $ROOT . '/' . $rel;
    row('v6 Files', $rel, is_file($abs), is_file($abs) ? "OK — $label" : "MISSING — $label");
}

/* v6 functions inside patched files */
$v6Fn = [
    ['backend/lib/groq_vision.php', 'classify_pollution_photo', 'Part 31 — photo pollution classifier'],
    ['backend/lib/notify.php',      'should_send_notification', 'Part 34 — anti-fatigue throttle'],
    ['backend/lib/rag_context.php', 'build_rag_context',        'Part 47 — RAG context'],
    ['backend/lib/school_forecast.php', 'predict_school_status', 'Part 35 — school forecast'],
    ['backend/lib/anomaly_correlation.php', 'link_anomalies_to_reports', 'Part 32 — anomaly link'],
    ['backend/lib/rule_calibration.php', 'recalibrate_rules',   'Part 33 — rule calibration'],
    ['backend/lib/data_quality_validator.php', 'validate_reading', 'Part 45 — data validation'],
];
foreach ($v6Fn as [$file, $fn, $label]) {
    row('v6 Functions', "$fn()", file_contains($ROOT . '/' . $file, "function $fn"), $label);
}

/* v6 patched wiring */
row('v6 Wiring', 'chatbot uses RAG', file_contains($ROOT.'/backend/api/chatbot.php', 'build_rag_context'), 'Part 47 — chatbot grounded on retrieved facts');
row('v6 Wiring', 'groq prompt ragBlock', file_contains($ROOT.'/backend/config/groq.php', 'ragBlock'), 'Part 47 — RAG injected in system prompt');
row('v6 Wiring', 'reports classify photo', file_contains($ROOT.'/backend/api/reports.php', 'photo_classifications'), 'Part 31 — photo classified on upload');
row('v6 Wiring', 'risk score photo signal', file_contains($ROOT.'/backend/lib/helpers.php', 'photoBoost'), 'Part 31 — photo signal in risk score');
row('v6 Wiring', 'admin routes (registry/twin)', file_contains($ROOT.'/backend/lib/auth.php', 'model-registry'), 'Part 43/48 — admin-only pages');
row('v6 Wiring', 'router v6 pages', file_contains($ROOT.'/frontend/scripts/router.js', 'initDigitalTwin'), 'Part 43/48 — front routing');
row('v6 Wiring', 'train_all v6 hooks', file_contains($ROOT.'/models/train_all.py', '_run_v6_hooks'), 'Parts 37/39/43/44/46 — training hooks');
row('v6 Wiring', 'school predictive encart', file_contains($ROOT.'/frontend/pages/school.html', 'school-forecast-encart'), 'Part 35 — suggestion encart');

/* v6 tables */
$v6Tables = [
    'photo_classifications', 'anomaly_citizen_links', 'recommendation_rules',
    'recommendation_feedback', 'recommendations_log', 'notification_throttle',
    'school_predictions', 'gnn_spatial_edges', 'counterfactual_explanations',
    'xai_interactions', 'calibration_metrics', 'model_versions', 'ab_test_runs',
    'data_quality_checks', 'digital_twin_scenarios',
];
if ($pdo) {
    foreach ($v6Tables as $t) {
        try {
            $exists = (int)$pdo->query("SELECT COUNT(*) FROM information_schema.TABLES
                                          WHERE TABLE_SCHEMA = DATABASE()
                                            AND TABLE_NAME   = ".$pdo->quote($t))->fetchColumn() > 0;
            row('v6 DB tables', $t, $exists,
                $exists ? 'OK' : "MISSING — run:  mysql -u root $dbName < db/migrations/2026-07-15-upgrade-v6.sql");
        } catch (Throwable $e) {
            row('v6 DB tables', $t, false, $e->getMessage());
        }
    }
}

/* ==============================================================
 *  UPGRADE v8 + v9 (2026-07-20 / 2026-07-25) — Intelligence & Carte
 * ============================================================== */
$v89Files = [
    'db/migrations/2026-07-20-upgrade-v8.sql'      => 'v8 SQL migration',
    'db/migrations/2026-07-25-upgrade-v9.sql'      => 'v9 SQL migration',
    'backend/lib/report_dedup.php'                 => 'Part 49.1 — report deduplication',
    'backend/lib/report_nlp_classifier.php'        => 'Part 49.2 — NLP text classifier',
    'backend/lib/symptom_pattern_detector.php'     => 'Part 50.1 — personal pattern (Pearson/lag)',
    'backend/lib/symptom_forecast.php'             => 'Part 50.2 — personal symptom forecast',
    'backend/lib/chatbot_emergency_detector.php'   => 'Part 51.2/51.3 — emergency + language register',
    'backend/api/ai-dashboard-data.php'            => 'Part 53 — unified AI dashboard aggregator',
    'backend/api/map-layers.php'                   => 'Part 55 — map layers data',
    'frontend/pages/ai-dashboard.html'             => 'Part 53 — AI dashboard page',
    'frontend/scripts/pages/ai-dashboard.js'       => 'Part 53 — AI dashboard JS',
    'frontend/styles/ai-dashboard.css'             => 'Part 53 — AI dashboard CSS',
    'frontend/lib/timelapse_export.js'             => 'Part 54.3 — time-lapse GIF export',
];
foreach ($v89Files as $rel => $label) {
    $abs = $ROOT . '/' . $rel;
    row('v8/v9 Files', $rel, is_file($abs), is_file($abs) ? "OK — $label" : "MISSING — $label");
}

/* v8/v9 functions inside new/patched files */
$v89Fn = [
    ['backend/lib/report_dedup.php',               'find_duplicate_cluster',    'Part 49.1 — dedup'],
    ['backend/lib/report_nlp_classifier.php',      'classify_report_text',      'Part 49.2 — NLP classify'],
    ['backend/lib/symptom_pattern_detector.php',   'detect_personal_pattern',   'Part 50.1 — personal pattern'],
    ['backend/lib/symptom_forecast.php',           'personal_symptom_forecast', 'Part 50.2 — personal forecast'],
    ['backend/lib/chatbot_emergency_detector.php', 'detect_emergency_signal',   'Part 51.2 — emergency'],
    ['backend/lib/chatbot_emergency_detector.php', 'detect_language_register',  'Part 51.3 — language register'],
];
foreach ($v89Fn as [$file, $fn, $label]) {
    row('v8/v9 Functions', "$fn()", file_contains($ROOT . '/' . $file, "function $fn"), $label);
}

/* v8/v9 patched wiring */
row('v8/v9 Wiring', 'reports dedup+NLP',       file_contains($ROOT.'/backend/api/reports.php', 'find_duplicate_cluster'), 'Part 49 — dedup+classify on insert');
row('v8/v9 Wiring', 'symptoms triage',         file_contains($ROOT.'/backend/api/symptoms.php', 'suggest_telemed'),        'Part 50.3 — intelligent triage');
row('v8/v9 Wiring', 'chatbot memory',          file_contains($ROOT.'/backend/api/chatbot.php', 'chatbot_user_memory'),    'Part 51.1 — persistent memory');
row('v8/v9 Wiring', 'groq memory/lang block',  file_contains($ROOT.'/backend/config/groq.php', 'memoryBlock'),           'Part 51 — memory+lang in prompt');
row('v8/v9 Wiring', 'risk score trust weight', file_contains($ROOT.'/backend/lib/helpers.php', 'trustFactor'),           'Part 49.3 — trust-weighted reports');
row('v8/v9 Wiring', 'ai-dashboard admin/health', file_contains($ROOT.'/backend/lib/auth.php', 'ai-dashboard'),          'Part 53 — restricted page');
row('v8/v9 Wiring', 'router ai-dashboard',     file_contains($ROOT.'/frontend/scripts/router.js', 'initAiDashboard'),    'Part 53 — front routing');
row('v8/v9 Wiring', 'timelapse granularity',   file_contains($ROOT.'/backend/api/timelapse.php', 'granularity'),         'Part 54.1 — hourly granularity');
row('v8/v9 Wiring', 'map v9 layers',           file_contains($ROOT.'/frontend/scripts/pages/map.js', 'map-layers.php'),  'Part 55 — new map layers');
row('v8/v9 Wiring', 'map speed control',       file_contains($ROOT.'/frontend/scripts/pages/map.js', 'playSpeed'),       'Part 54.2 — playback speed');
row('v8/v9 Wiring', 'index ai-dashboard.js',   file_contains($ROOT.'/frontend/index.php', 'pages/ai-dashboard.js'),      'Part 53 — script include');

/* v8/v9 tables */
$v89Tables = [
    'report_duplicate_clusters', 'trust_score_history', 'personal_patterns',
    'chatbot_user_memory', 'parent_child_alerts', 'schools', 'safe_points',
];
if ($pdo) {
    foreach ($v89Tables as $t) {
        try {
            $exists = (int)$pdo->query("SELECT COUNT(*) FROM information_schema.TABLES
                                          WHERE TABLE_SCHEMA = DATABASE()
                                            AND TABLE_NAME   = ".$pdo->quote($t))->fetchColumn() > 0;
            row('v8/v9 DB tables', $t, $exists,
                $exists ? 'OK' : "MISSING — run the v8/v9 migrations in db/migrations/");
        } catch (Throwable $e) {
            row('v8/v9 DB tables', $t, false, $e->getMessage());
        }
    }
    try {
        $col = (int)$pdo->query("SELECT COUNT(*) FROM information_schema.COLUMNS
                                   WHERE TABLE_SCHEMA = DATABASE()
                                     AND TABLE_NAME = 'users' AND COLUMN_NAME = 'trust_score'")->fetchColumn() > 0;
        row('v8/v9 DB tables', 'users.trust_score', $col, $col ? 'OK' : 'MISSING — run v8 migration');
    } catch (Throwable $e) {
        row('v8/v9 DB tables', 'users.trust_score', false, $e->getMessage());
    }
}

/* ────────────────────────────── 4. RUNTIME ─────────────────────── */
$fz = null;
try {
    require_once $ROOT . '/backend/lib/fuzzy.php';
    if (function_exists('fuzzy_recommend')) {
        $fz = fuzzy_recommend([
            'pollution' => 70, 'vulnerability' => 7, 'symptom_sev' => 6,
            'alerts_24h' => 2, 'age' => 65,
        ]);
        $ok = isset($fz['risk_score']) && $fz['risk_score'] >= 50;
        row('Runtime', 'Fuzzy engine inference (test case)', $ok,
            $ok ? sprintf("✓ score=%.1f urgency=%s rules_fired=%d",
                $fz['risk_score'], $fz['urgency_level'], count($fz['fired_rules']))
                : 'fuzzy_recommend() returned an unexpected value');
    } else {
        row('Runtime', 'fuzzy_recommend()', false, 'Function not defined — backend/lib/fuzzy.php missing or broken');
    }
} catch (Throwable $e) {
    row('Runtime', 'fuzzy_recommend()', false, $e->getMessage());
}

try {
    require_once $ROOT . '/backend/lib/forecast_ml.php';
    $ok = function_exists('forecast_hybrid');
    row('Runtime', 'forecast_hybrid()', $ok, $ok ? '✓ defined' : 'function missing');
} catch (Throwable $e) {
    row('Runtime', 'forecast_hybrid()', false, $e->getMessage());
}

try {
    require_once $ROOT . '/backend/lib/api_verifier.php';
    $ok = function_exists('verify_zone');
    row('Runtime', 'verify_zone()', $ok, $ok ? '✓ defined' : 'function missing');
} catch (Throwable $e) {
    row('Runtime', 'verify_zone()', false, $e->getMessage());
}

try {
    require_once $ROOT . '/backend/lib/fuzzy_context.php';
    $ok = function_exists('fuzzy_for_user');
    row('Runtime', 'fuzzy_for_user() — universal helper', $ok, $ok ? '✓ defined' : 'function missing');
} catch (Throwable $e) {
    row('Runtime', 'fuzzy_for_user()', false, $e->getMessage());
}

/* GAN runtime check: train a tiny GAN for 5 epochs and generate one sample. */
try {
    require_once $ROOT . '/backend/lib/gan.php';
    gan_seed(7);
    $real = [];
    for ($k = 0; $k < 4; $k++) {
        $w = [];
        for ($t = 0; $t < GAN_SEQ_LEN; $t++) $w[] = sin($t * 0.5 + $k);
        $real[] = $w;
    }
    $r = gan_train($real, ['epochs' => 5, 'batch' => 2, 'lr' => 0.001]);
    $samples = gan_sample($r['G'], 1);
    $denorm  = array_map('gan_denorm', $samples[0]);
    $ok = is_array($samples) && count($samples) === 1 && count($denorm) === GAN_SEQ_LEN;
    row('Runtime', 'gan_train() + gan_sample() (5-epoch test)', $ok,
        $ok ? sprintf('✓ generated 1 series, range %d..%d', min($denorm), max($denorm))
            : 'GAN returned an unexpected shape');
} catch (Throwable $e) {
    row('Runtime', 'GAN', false, $e->getMessage());
}

/* Optional: detect if a trained weights file has been saved. */
$ganWeights = $ROOT . '/storage/gan/weights.json';
$hasWeights = is_file($ganWeights);
row('GAN', 'Trained GAN weights present', $hasWeights,
    $hasWeights
        ? '✓ ' . $ganWeights . ' (' . filesize($ganWeights) . ' bytes)'
        : 'No weights yet — run:  php scripts/train_gan.php',
    !$hasWeights /* mark as warn only */);

/* ────────────────────────────── 5. RENDER ──────────────────────── */
$bySection = [];
foreach ($rows as $r) $bySection[$r['section']][] = $r;

$total = $pass + $fail + $warn;
?>
<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Nafass · verify-install</title>
<style>
 body { font-family: ui-sans-serif, system-ui, sans-serif; background:#f8fafc; color:#0f172a; padding:24px; }
 h1 { margin:0 0 6px; color:#0d3b66; }
 .sub { color:#475569; margin-bottom: 22px; }
 .summary { display:flex; gap:14px; margin-bottom: 24px; flex-wrap: wrap; }
 .pill { padding:8px 14px; border-radius:999px; font-weight:700; font-size:14px; }
 .pill.ok { background:#dcfce7; color:#166534; }
 .pill.ko { background:#fee2e2; color:#991b1b; }
 .pill.tot { background:#e0e7ff; color:#3730a3; }
 h2 { margin: 22px 0 8px; color:#0d3b66; border-bottom: 2px solid #e2e8f0; padding-bottom: 6px; }
 table { width:100%; border-collapse: collapse; background:#fff; }
 th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #e2e8f0; font-size: 13.5px; }
 th { background:#0d3b66; color:#fff; }
 td.status { width: 80px; text-align: center; font-weight: 700; }
 td.ok { color:#166534; }
 td.ko { color:#991b1b; }
 td.warn { color:#92400e; }
 td.detail { color:#475569; font-family: ui-monospace, monospace; font-size: 12.5px; }
 .ko-bar { background:#fef2f2; border-left: 4px solid #ef4444; padding: 12px 16px;
           border-radius: 6px; margin: 14px 0; color:#7f1d1d; font-size: 14px; }
 .ok-bar { background:#f0fdf4; border-left: 4px solid #22c55e; padding: 12px 16px;
           border-radius: 6px; margin: 14px 0; color:#14532d; font-size: 14px; }
 .code  { background:#0f172a; color:#e2e8f0; padding: 10px 14px; border-radius: 8px;
          font-family: ui-monospace, monospace; font-size: 13px; margin: 6px 0; }
</style></head><body>
<h1>Nafass — verify-install</h1>
<div class="sub">Click each section to confirm the v2 modifications (fuzzy / multi-source / hybrid forecast) are correctly installed.</div>
<div class="summary">
  <span class="pill tot">Checks total: <?= $total ?></span>
  <span class="pill ok">PASS <?= $pass ?></span>
  <span class="pill ko">FAIL <?= $fail ?></span>
  <?php if ($warn > 0): ?><span class="pill" style="background:#fef3c7;color:#92400e;">WARN <?= $warn ?></span><?php endif; ?>
</div>

<?php if ($fail === 0): ?>
  <div class="ok-bar"><b>All checks PASS.</b> Every modification of the 2026-05-07 release is correctly installed.
    Fuzzy logic is active in all of: dashboard, recommendations, diary AI, symptoms triage, tips, weekly summary, chatbot.</div>
<?php else: ?>
  <div class="ko-bar">
    <b>Some checks FAILED.</b> The most common reasons are listed below — fix them, refresh this page until everything is green.
    <ol style="margin: 8px 0 0 18px;">
      <li>The .zip was not extracted on top of your project (files missing).</li>
      <li>The SQL migration was not run. Open a shell and execute:
        <div class="code">mysql -u root <?= htmlspecialchars($dbName) ?> &lt; db/migrations/2026-05-07-fuzzy-augment-hybrid.sql</div></li>
      <li>You opened your OLD project URL — make sure WAMP serves the v2 folder.</li>
    </ol>
  </div>
<?php endif; ?>

<?php foreach ($bySection as $sec => $entries): ?>
  <h2><?= htmlspecialchars($sec) ?></h2>
  <table>
    <thead><tr><th>Check</th><th>Status</th><th>Detail</th></tr></thead>
    <tbody>
    <?php foreach ($entries as $r): ?>
      <?php
        $cls = $r['warn'] ? 'warn' : ($r['ok'] ? 'ok' : 'ko');
        $lbl = $r['warn'] ? 'WARN' : ($r['ok'] ? 'PASS' : 'FAIL');
      ?>
      <tr>
        <td><?= htmlspecialchars($r['check']) ?></td>
        <td class="status <?= $cls ?>"><?= $lbl ?></td>
        <td class="detail"><?= htmlspecialchars($r['detail']) ?></td>
      </tr>
    <?php endforeach; ?>
    </tbody>
  </table>
<?php endforeach; ?>

<?php if ($fz && isset($fz['fired_rules'])): ?>
  <h2>Sample fuzzy decision (live test)</h2>
  <table>
    <thead><tr><th>Variable</th><th>Activation</th><th>Rule</th></tr></thead>
    <tbody>
    <?php foreach ($fz['fired_rules'] as $rule): ?>
      <tr>
        <td>R<?= (int)$rule['id'] ?></td>
        <td><?= number_format(($rule['activation'] ?? 0) * 100, 1) ?>%</td>
        <td><?= htmlspecialchars((string)($rule['label'] ?? $rule['consequent'] ?? '')) ?></td>
      </tr>
    <?php endforeach; ?>
    </tbody>
  </table>
  <div class="sub" style="margin-top:8px;">
    Inputs: pollution=70, vulnerability=7, symptoms=6, alerts=2, age=65 →
    score=<b><?= number_format($fz['risk_score'], 1) ?>/100</b>,
    urgency=<b><?= htmlspecialchars($fz['urgency_level']) ?></b>.
  </div>
<?php endif; ?>

<h2>Next steps</h2>
<ol>
  <li>If anything is FAIL: re-extract <code>gabes-tatenafas-v2.zip</code> over your project (let it overwrite), then run the migration.</li>
  <li>Log in as <code>citizen1 / citizen123</code> and open the dashboard — the recommendation card now shows a green <b>Fuzzy Mamdani</b> panel below the LLM text.</li>
  <li>Open <b>Diary</b> → click "Generate AI insights" — the diary card now also shows the fuzzy badge + rules.</li>
  <li>Open <b>Symptoms</b>, log a symptom, click "Request AI advice" — a small Fuzzy badge appears next to the triage button.</li>
  <li>Open <b>Chatbot</b> — the system prompt now includes the fuzzy-logic block invisibly (the LLM is forced to align with it).</li>
  <li>Optional (admin): open the <b>Forecast — ML/DL</b> menu to see the hybrid AR(7)+EWMA forecast with MAE/RMSE/MAPE/R²/SMAPE metrics.</li>
</ol>

</body></html>
