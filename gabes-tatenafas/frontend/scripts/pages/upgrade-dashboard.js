/** Upgrade overview hub — links to every scientific module. */
window.initUpgradeDashboard = function () {
  const items = [
    ['fuzzy-type2', 'Fuzzy Logic Type-2', 'PART 1 · Karnik-Mendel + FOU'],
    ['cgan', 'Conditional GAN', 'PART 2 · augmentation de données'],
    ['forecast-ml', 'ML — SHAP / LIME / ROC', 'PART 4 · RF + XGBoost + Optuna'],
    ['deep-learning', 'Deep Learning BiLSTM', 'PART 5 · Multi-Head Attention'],
    ['anomaly', 'Détection d\'anomalies', 'PART 5.5 · Autoencoder + IsoForest'],
    ['health-impact', 'Impact Sanitaire', 'PART 6 · indice spécifique Gabès'],
    ['comparison', 'Comparaison des modèles', 'PART 7/8/9/18 · ablation + stats'],
    ['granger', 'Causalité de Granger', 'PART 10 · SO2 → PM2.5'],
    ['comparative-literature', 'Comparaison littérature', 'PART 11 · vs publications'],
    ['ensemble', 'Ensemble & Trust', 'PART 12/13 · résiduel + incertitude'],
    ['drift', 'Dérive & Auto-Optimisation', 'PART 14/16 · KL + Optuna'],
    ['spatial', 'Propagation spatiale', 'PART 15 · vent inter-villes'],
    ['smart-alerts', 'Alertes intelligentes', 'PART 17 · SHAP + LIME'],
    ['federated', 'Apprentissage fédéré', 'PART 20 · FedAvg'],
  ];
  const grid = document.getElementById('up-grid');
  if (!grid) return;
  grid.innerHTML = items.map(([route, title, sub]) => `
    <a class="card" href="#/${route}" style="display:block;text-decoration:none;color:inherit">
      <h3 style="color:var(--primary)">${title}</h3>
      <div class="muted small" style="margin-top:4px">${sub}</div>
      <div style="margin-top:10px;color:var(--primary);font-weight:600;font-size:13px">Ouvrir →</div>
    </a>`).join('');
};
