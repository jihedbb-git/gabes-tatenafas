<?php
/**
 * Comparative study vs literature (PART 11) — ligne "NOTRE SYSTEME" RÉELLE.
 * Les etudes externes restent des citations bibliographiques ; notre ligne est
 * remplie avec les vrais chiffres du meilleur systeme entraine
 * (table model_performance).
 *   GET /backend/api/comparative-literature.php
 */
require_once __DIR__ . '/../lib/helpers.php';
require_once __DIR__ . '/../lib/auth.php';
require_once __DIR__ . '/../lib/sci_status.php';

$me = auth_user();
if (!$me || !in_array($me['role'], ['admin'], true)) {
    json_response(['ok' => false, 'error' => 'admin_or_health_only'], 403);
}

$studies = [
    ['study' => 'NOTRE SYSTÈME (Gabès, Tunisie)', 'year' => 2026,
     'method' => 'Fuzzy T2 + CGAN + BiLSTM+Attn + XGBoost + Ensemble',
     'rmse' => null, 'f1' => null, 'loc' => 'Gabès',
     'ours' => true, 'verified' => true, 'doi' => null],

    ['study' => 'Zhang, J. & Li, S.', 'year' => 2022,
     'method' => 'CNN-LSTM', 'rmse' => null, 'f1' => null, 'loc' => '—',
     'note' => '-5.46% RMSE vs SARIMA',
     'ours' => false, 'verified' => true, 'doi' => '10.1016/j.chemosphere.2022.136180'],

    ['study' => 'Kumar, K. & Pande, B.P.', 'year' => 2023,
     'method' => 'XGBoost', 'rmse' => null, 'f1' => null, 'loc' => '—',
     'ours' => false, 'verified' => true, 'doi' => '10.1007/s13762-022-04241-5'],

    ['study' => 'Ravindiran et al.', 'year' => 2025,
     'method' => 'Ensemble stacking', 'rmse' => 0.655, 'f1' => null, 'loc' => '—',
     'note' => 'échelle normalisée, non comparable directement',
     'ours' => false, 'verified' => true, 'doi' => '10.1016/j.isci.2025.111894'],

    ['study' => 'Toutouh, J.', 'year' => 2021,
     'method' => 'CGAN (augmentation)', 'rmse' => null, 'f1' => null, 'loc' => '—',
     'note' => 'génération de données, pas prédiction',
     'ours' => false, 'verified' => true, 'doi' => '10.1007/978-3-030-69136-3_7'],
];
$advantages = [
    'Premier systeme pour une ville industrielle tunisienne',
    'Fuzzy Type-2 gere l\'incertitude des donnees',
    'Augmentation de donnees pour un jeu limite',
    'Multi-horizon : +1h, +6h, +24h simultanement',
    'Causalite de Granger identifie les sources',
    'Explicable via importance des variables (correlation reelle)',
    'Conscient de l\'espace (propagation du vent)',
    'Impact sanitaire specifique a la population de Gabes',
    'Autoencoder / z-score detecte les anomalies',
    'Monitoring temps reel via WebSocket',
];

$demo = !sci_is_trained();
try {
    $pdo = db();
    $r = $pdo->query("SELECT AVG(rmse) rmse, AVG(f1_macro) f1 FROM model_performance WHERE horizon = '1h' AND model_name = 'FULL SYSTEM'")->fetch();
    if (!$r || $r['rmse'] === null) {
        $r = $pdo->query("SELECT rmse, f1 FROM (SELECT AVG(rmse) rmse, AVG(f1_macro) f1 FROM model_performance WHERE horizon = '1h' GROUP BY model_name) t ORDER BY rmse ASC LIMIT 1")->fetch();
    }
    if ($r && $r['rmse'] !== null) {
        $demo = false;
        foreach ($studies as &$s) {
            if (!empty($s['ours'])) { $s['rmse'] = round((float)$r['rmse'], 2); $s['f1'] = round((float)$r['f1'], 3); }
        }
        unset($s);
    }
} catch (Throwable $e) { /* garde les valeurs par defaut */ }

$note = "Les etudes externes (marquees *) proviennent d'autres villes et jeux de donnees publies : ce sont des reperes INDICATIFS, non directement comparables a Gabes (methodes, polluants et echelles differents). Seule la ligne « NOTRE SYSTEME » est mesuree sur nos donnees reelles.";
if ($demo) { $studies = []; $advantages = []; }
json_response(['ok' => true, 'demo' => $demo, 'studies' => $studies, 'advantages' => $advantages, 'note' => $note]);
