<?php
/**
 * Hybrid ML/DL pollution forecaster — PHP implementation.
 *
 * Architecture: ENSEMBLE of two complementary base models.
 *
 *   Model A (classical ML)
 *   ──────────────────────
 *     Auto-Regressive model of order 7  ─ AR(7)
 *     y(t) = β₀ + Σ_{i=1..7} βᵢ · y(t-i) + day_of_week_features
 *     Coefficients learned on-the-fly by ordinary least squares (Gauss-Jordan).
 *
 *   Model B (deep-learning-inspired)
 *   ────────────────────────────────
 *     Multi-EWMA stack — three exponential smoothers (α = 0.2, 0.5, 0.8)
 *     are combined non-linearly through a sigmoid blend whose weights
 *     are learned by gradient descent. This is mathematically equivalent
 *     to a tiny 1-layer recurrent network with 3 hidden units, hence
 *     "DL-inspired".
 *
 *   Ensemble
 *   ────────
 *     ŷ_final = α·ŷ_A + (1-α)·ŷ_B, with α selected by grid-search on the
 *     held-out validation portion (last 20 % of the series).
 *
 * Metrics
 * -------
 *   MAE, RMSE, MAPE, R², SMAPE — stored in `forecast_metrics`.
 *
 * Robustness
 * ----------
 *   If fewer than 14 points are available we fall back to the legacy
 *   EWMA estimator in forecast.php.
 *
 * Reference
 * ---------
 *   Box & Jenkins 1976 (AR models); Holt 1957 (exponential smoothing);
 *   Zhang 2003 "Time series forecasting using a hybrid ARIMA and neural
 *   network model" — Neurocomputing.
 */
declare(strict_types=1);

require_once __DIR__ . '/../config/database.php';

/* =====================================================================
 *  HELPERS
 * ===================================================================== */

/** Convert a numeric pollution_level into a discrete level enum. */
function ml_level_of(int $score): string
{
    return $score >= 70 ? 'critical' : ($score >= 40 ? 'warning' : 'safe');
}

/** Pull recent real points (most recent first). Optionally include augmented data. */
function ml_load_series(PDO $pdo, int $zoneId, int $days = 30, bool $withAugmented = true): array
{
    $real = $pdo->prepare(
        'SELECT computed_at AS ts, score FROM risk_scores
         WHERE zone_id = ? AND computed_at >= NOW() - INTERVAL ? DAY
         ORDER BY computed_at ASC'
    );
    $real->execute([$zoneId, $days]);
    $rows = $real->fetchAll();

    if ($withAugmented) {
        try {
            $aug = $pdo->prepare(
                'SELECT synthetic_at AS ts, score FROM risk_scores_augmented
                 WHERE zone_id = ? AND synthetic_at >= NOW() - INTERVAL ? DAY
                 ORDER BY synthetic_at ASC'
            );
            $aug->execute([$zoneId, $days]);
            foreach ($aug->fetchAll() as $r) $rows[] = $r;
        } catch (Throwable $e) { /* augmentation table optional */ }
    }
    usort($rows, fn($a, $b) => strtotime($a['ts']) <=> strtotime($b['ts']));
    return $rows;
}

/* =====================================================================
 *  MODEL A — AR(7) by ordinary least squares
 * ===================================================================== */

/**
 * Build the design matrix X (n × p) and target vector y (n) for AR(p).
 * Each row: [1, y(t-1), y(t-2), …, y(t-p), dow_sin, dow_cos]
 *           ^ intercept                       ^ Fourier encoding of weekday
 */
function ml_ar_build_design(array $series, int $p = 7): array
{
    $n = count($series);
    $X = []; $y = [];
    for ($t = $p; $t < $n; $t++) {
        $row = [1.0];
        for ($i = 1; $i <= $p; $i++) $row[] = (float)$series[$t - $i]['score'];
        $ts = strtotime($series[$t]['ts']);
        $dow = (int)date('N', $ts);                       // 1..7
        $row[] = sin(2 * M_PI * $dow / 7);
        $row[] = cos(2 * M_PI * $dow / 7);
        $X[] = $row;
        $y[] = (float)$series[$t]['score'];
    }
    return ['X' => $X, 'y' => $y];
}

/** Solve (Xᵀ X) β = Xᵀ y by Gauss-Jordan elimination. */
function ml_ols_fit(array $X, array $y): ?array
{
    $n = count($X);
    if ($n === 0) return null;
    $p = count($X[0]);

    // XtX (p×p) and Xty (p)
    $XtX = array_fill(0, $p, array_fill(0, $p, 0.0));
    $Xty = array_fill(0, $p, 0.0);
    for ($i = 0; $i < $n; $i++) {
        for ($j = 0; $j < $p; $j++) {
            $Xty[$j] += $X[$i][$j] * $y[$i];
            for ($k = 0; $k < $p; $k++) {
                $XtX[$j][$k] += $X[$i][$j] * $X[$i][$k];
            }
        }
    }
    // Augment matrix [XtX | Xty] for Gauss-Jordan
    for ($i = 0; $i < $p; $i++) $XtX[$i][] = $Xty[$i];

    // Ridge regularization: add λ to the diagonal for numerical stability
    $lambda = 1e-3;
    for ($i = 0; $i < $p; $i++) $XtX[$i][$i] += $lambda;

    // Gauss-Jordan
    for ($i = 0; $i < $p; $i++) {
        // Pivot
        $maxRow = $i;
        for ($k = $i + 1; $k < $p; $k++) {
            if (abs($XtX[$k][$i]) > abs($XtX[$maxRow][$i])) $maxRow = $k;
        }
        [$XtX[$i], $XtX[$maxRow]] = [$XtX[$maxRow], $XtX[$i]];
        $piv = $XtX[$i][$i];
        if (abs($piv) < 1e-12) return null;
        for ($k = 0; $k <= $p; $k++) $XtX[$i][$k] /= $piv;
        for ($k = 0; $k < $p; $k++) {
            if ($k === $i) continue;
            $f = $XtX[$k][$i];
            for ($j = 0; $j <= $p; $j++) $XtX[$k][$j] -= $f * $XtX[$i][$j];
        }
    }
    $beta = [];
    for ($i = 0; $i < $p; $i++) $beta[] = $XtX[$i][$p];
    return $beta;
}

/** Predict next value from AR(p) model given the last p observations + timestamp. */
function ml_ar_predict(array $beta, array $lastP, int $tsForDow): float
{
    $row = [1.0];
    foreach ($lastP as $v) $row[] = (float)$v;
    $dow = (int)date('N', $tsForDow);
    $row[] = sin(2 * M_PI * $dow / 7);
    $row[] = cos(2 * M_PI * $dow / 7);
    $yhat = 0.0;
    for ($i = 0; $i < count($beta); $i++) $yhat += $beta[$i] * $row[$i];
    return $yhat;
}

/* =====================================================================
 *  MODEL B — Multi-EWMA blended through a sigmoid (DL-inspired)
 * ===================================================================== */

function ml_sigmoid(float $x): float { return 1.0 / (1.0 + exp(-$x)); }

/**
 * Compute three EWMA series (α = 0.2 / 0.5 / 0.8) and blend them through
 * a sigmoid-weighted combination. The blending weights are learned by
 * 50 iterations of gradient descent against the training target.
 */
function ml_mewma_fit_predict(array $series, int $horizonSteps = 1): array
{
    $values = array_map(fn($r) => (float)$r['score'], $series);
    $n = count($values);
    if ($n < 4) return ['pred' => $values[$n - 1] ?? 0.0, 'weights' => [1/3,1/3,1/3]];

    // Build the three EWMAs
    $alphas = [0.2, 0.5, 0.8];
    $ewma = [];
    foreach ($alphas as $a) {
        $s = $values[0];
        $tr = [$s];
        for ($i = 1; $i < $n; $i++) {
            $s = $a * $values[$i] + (1 - $a) * $s;
            $tr[] = $s;
        }
        $ewma[] = $tr;
    }
    // Learn blending weights w₁ w₂ w₃ that minimize MSE on one-step-ahead
    $w = [0.0, 0.0, 0.0];   // sigmoid(0) = 0.5
    $lr = 0.01;
    $iters = 80;
    for ($it = 0; $it < $iters; $it++) {
        $grad = [0.0, 0.0, 0.0];
        for ($t = 1; $t < $n; $t++) {
            $denom = ml_sigmoid($w[0]) + ml_sigmoid($w[1]) + ml_sigmoid($w[2]);
            $pred = (ml_sigmoid($w[0]) * $ewma[0][$t - 1]
                   + ml_sigmoid($w[1]) * $ewma[1][$t - 1]
                   + ml_sigmoid($w[2]) * $ewma[2][$t - 1]) / max(1e-6, $denom);
            $err = $pred - $values[$t];
            for ($k = 0; $k < 3; $k++) {
                $sig = ml_sigmoid($w[$k]);
                $dpred_dw = ($ewma[$k][$t - 1] - $pred) * $sig * (1 - $sig) / max(1e-6, $denom);
                $grad[$k] += 2 * $err * $dpred_dw;
            }
        }
        for ($k = 0; $k < 3; $k++) $w[$k] -= $lr * $grad[$k] / max(1, $n - 1);
    }
    // Forecast horizonSteps ahead: assume EWMA continues at its last level
    $denom = ml_sigmoid($w[0]) + ml_sigmoid($w[1]) + ml_sigmoid($w[2]);
    $pred = (ml_sigmoid($w[0]) * end($ewma[0])
           + ml_sigmoid($w[1]) * end($ewma[1])
           + ml_sigmoid($w[2]) * end($ewma[2])) / max(1e-6, $denom);

    return [
        'pred'    => $pred,
        'weights' => array_map(fn($v) => round(ml_sigmoid($v), 3), $w),
        'series'  => $ewma,
    ];
}

/* =====================================================================
 *  ENSEMBLE + METRICS
 * ===================================================================== */

function ml_metrics(array $yTrue, array $yPred): array
{
    $n = count($yTrue);
    if ($n === 0) return ['mae'=>null,'rmse'=>null,'mape'=>null,'r2'=>null,'smape'=>null,'n'=>0];
    $sumAbs = 0.0; $sumSq = 0.0; $sumAbsPct = 0.0; $sumSmape = 0.0; $ssTot = 0.0;
    $meanY = array_sum($yTrue) / $n;
    for ($i = 0; $i < $n; $i++) {
        $err = $yTrue[$i] - $yPred[$i];
        $sumAbs += abs($err);
        $sumSq  += $err * $err;
        if ($yTrue[$i] != 0) $sumAbsPct += abs($err) / abs($yTrue[$i]);
        $sumSmape += abs($err) / max(1e-6, (abs($yTrue[$i]) + abs($yPred[$i])) / 2.0);
        $ssTot += ($yTrue[$i] - $meanY) ** 2;
    }
    $ssRes = $sumSq;
    return [
        'mae'   => round($sumAbs / $n, 3),
        'rmse'  => round(sqrt($sumSq / $n), 3),
        'mape'  => round(($sumAbsPct / $n) * 100, 3),
        'smape' => round(($sumSmape / $n) * 100, 3),
        'r2'    => $ssTot > 0 ? round(1 - $ssRes / $ssTot, 3) : null,
        'n'     => $n,
    ];
}

/**
 * Train both models on the first 80% of the series, evaluate on the last
 * 20 %, search for the best ensemble weight α ∈ {0, 0.1, …, 1.0}.
 *
 * @return array  {
 *     beta         : AR(7) coefficients  (or null)
 *     mewma_weights: sigmoid weights (Model B)
 *     alpha        : best ensemble weight α
 *     metrics      : per-model metrics + ensemble
 * }
 */
function ml_train_ensemble(array $series): array
{
    $n = count($series);
    if ($n < 14) {
        return ['error' => 'not_enough_data', 'n' => $n];
    }
    $split = (int)floor($n * 0.8);
    $train = array_slice($series, 0, $split);
    $valid = array_slice($series, $split);

    /* ---- Model A: AR(7) ---- */
    $design = ml_ar_build_design($train, 7);
    $beta = ml_ols_fit($design['X'], $design['y']);
    if (!$beta) {
        return ['error' => 'ar_fit_failed', 'n' => $n];
    }

    /* One-step-ahead predictions on the validation slice */
    $yTrue = []; $yA = []; $yB = [];
    for ($i = 0; $i < count($valid); $i++) {
        // For AR, use a rolling window of the previous 7 actuals
        $window = [];
        for ($k = 1; $k <= 7; $k++) {
            $idx = $split + $i - $k;
            $window[] = ($idx >= 0) ? (float)$series[$idx]['score'] : (float)$train[count($train) - 1]['score'];
        }
        $ts = strtotime($valid[$i]['ts']);
        $yA[] = ml_ar_predict($beta, $window, $ts);

        // For MEWMA, refit on the data seen so far for a fair rolling forecast
        $mb = ml_mewma_fit_predict(array_slice($series, 0, $split + $i));
        $yB[] = $mb['pred'];

        $yTrue[] = (float)$valid[$i]['score'];
    }

    /* ---- Search the best α ---- */
    $best = ['alpha' => 0.5, 'metrics' => ['rmse' => INF], 'yE' => []];
    for ($a = 0; $a <= 10; $a++) {
        $alpha = $a / 10.0;
        $yE = [];
        for ($i = 0; $i < count($yTrue); $i++) $yE[] = $alpha * $yA[$i] + (1 - $alpha) * $yB[$i];
        $m = ml_metrics($yTrue, $yE);
        if ($m['rmse'] !== null && $m['rmse'] < $best['metrics']['rmse']) {
            $best = ['alpha' => $alpha, 'metrics' => $m, 'yE' => $yE];
        }
    }

    $finalMewma = ml_mewma_fit_predict($series);

    return [
        'beta'          => $beta,
        'mewma_weights' => $finalMewma['weights'],
        'alpha'         => $best['alpha'],
        'split'         => $split,
        'metrics'       => [
            'ar7'      => ml_metrics($yTrue, $yA),
            'mewma'    => ml_metrics($yTrue, $yB),
            'ensemble' => $best['metrics'],
        ],
    ];
}

/* =====================================================================
 *  PUBLIC ENTRY POINT
 * ===================================================================== */

/**
 * Compute hybrid predictions at 6h / 12h / 24h horizons for one zone.
 * Persists each prediction in forecast_predictions and the metrics in
 * forecast_metrics, then returns the structured result.
 */
function ml_forecast_zone(PDO $pdo, int $zoneId, bool $persist = true): array
{
    $series = ml_load_series($pdo, $zoneId, 30, true);
    if (count($series) < 14) {
        return ['ok' => false, 'error' => 'not_enough_data', 'zone_id' => $zoneId];
    }
    $trained = ml_train_ensemble($series);
    if (isset($trained['error'])) {
        return ['ok' => false] + $trained + ['zone_id' => $zoneId];
    }

    /* Forecast 6/12/24 hours ahead (assume ≈ 1 sample/hour, fall back to last value otherwise) */
    $now = time();
    $alpha = $trained['alpha'];
    $window = [];
    for ($k = 1; $k <= 7; $k++) {
        $idx = count($series) - $k;
        $window[] = $idx >= 0 ? (float)$series[$idx]['score'] : (float)$series[0]['score'];
    }

    $finalPreds = [];
    foreach ([6, 12, 24] as $h) {
        $tsTarget = $now + $h * 3600;
        $yA = ml_ar_predict($trained['beta'], $window, $tsTarget);
        $mb = ml_mewma_fit_predict($series);
        $yE = $alpha * $yA + (1 - $alpha) * $mb['pred'];
        $yE = max(0, min(100, (int)round($yE)));
        $finalPreds[$h] = [
            'horizon_h' => $h,
            'score'     => $yE,
            'level'     => ml_level_of($yE),
            'method'    => 'ensemble_ar7_mewma',
            'confidence'=> max(0.4, min(0.95, 1.0 - ($trained['metrics']['ensemble']['rmse'] ?? 30) / 100.0)),
        ];
    }

    if ($persist) {
        $ins = $pdo->prepare(
            'INSERT INTO forecast_predictions
             (zone_id, horizon_hours, predicted_score, predicted_level, method, confidence)
             VALUES (?,?,?,?,?,?)'
        );
        foreach ($finalPreds as $p) {
            $ins->execute([
                $zoneId, $p['horizon_h'], $p['score'], $p['level'],
                $p['method'], $p['confidence'],
            ]);
        }
        // Per-model metrics
        $mins = $pdo->prepare(
            'INSERT INTO forecast_metrics
             (model_name, zone_id, mae, rmse, mape, r2, smape, sample_size)
             VALUES (?,?,?,?,?,?,?,?)'
        );
        foreach ($trained['metrics'] as $name => $m) {
            $mins->execute([
                $name, $zoneId,
                $m['mae'] ?? null, $m['rmse'] ?? null, $m['mape'] ?? null,
                $m['r2']  ?? null, $m['smape'] ?? null, $m['n'] ?? null,
            ]);
        }
    }

    return [
        'ok'        => true,
        'zone_id'   => $zoneId,
        'series_n'  => count($series),
        'alpha'     => $alpha,
        'metrics'   => $trained['metrics'],
        'mewma_w'   => $trained['mewma_weights'],
        'predictions' => $finalPreds,
    ];
}

/** Train hybrid forecasters for every zone. */
function ml_forecast_all_zones(PDO $pdo): array
{
    $zones = $pdo->query('SELECT id, name FROM zones')->fetchAll();
    $out = [];
    foreach ($zones as $z) {
        $r = ml_forecast_zone($pdo, (int)$z['id']);
        $out[] = ['zone' => $z['name']] + $r;
    }
    return $out;
}

/**
 * Read the most recent hybrid forecast for a single zone (no recompute).
 * Used by forecast.php as the primary source — falls back to legacy
 * EWMA when nothing has been pre-computed yet.
 */
function ml_load_cached_forecast(PDO $pdo, int $zoneId): ?array
{
    try {
        $st = $pdo->prepare(
            'SELECT horizon_hours, predicted_score, predicted_level, method,
                    confidence, computed_at
             FROM forecast_predictions
             WHERE zone_id = ? AND computed_at >= NOW() - INTERVAL 6 HOUR
             ORDER BY computed_at DESC'
        );
        $st->execute([$zoneId]);
        $rows = $st->fetchAll();
    } catch (Throwable $e) {
        return null;
    }
    if (!$rows) return null;

    $byH = [];
    foreach ($rows as $r) {
        $h = (int)$r['horizon_hours'];
        if (!isset($byH[$h])) $byH[$h] = $r;
    }
    return [
        'method'      => $rows[0]['method'],
        'confidence'  => (float)$rows[0]['confidence'],
        'horizons'    => [
            6  => $byH[6]['predicted_score']  ?? null,
            12 => $byH[12]['predicted_score'] ?? null,
            24 => $byH[24]['predicted_score'] ?? null,
        ],
        'levels'      => [
            6  => $byH[6]['predicted_level']  ?? null,
            12 => $byH[12]['predicted_level'] ?? null,
            24 => $byH[24]['predicted_level'] ?? null,
        ],
        'computed_at' => $rows[0]['computed_at'],
    ];
}
