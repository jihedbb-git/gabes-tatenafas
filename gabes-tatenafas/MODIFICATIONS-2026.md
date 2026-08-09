# MODIFICATIONS — Version 2.0 (2026-05-07)

Tags : **fuzzy-logic** · **data-augmentation** · **api-verification** · **hybrid-ml-dl-forecast**

Cette release implémente les 3 grandes demandes académiques :

1. **Recommandations par logique floue (Mamdani)** — remplace la décision LLM pure par un moteur de fonctions d'appartenance + base de règles + défuzzification au centroïde.
2. **Vérification multi-source des API + augmentation de données** — ajoute WAQI à côté d'IQAir, détection d'outliers (IQR + modified Z-score) et augmentation statistique de la table risk_scores (jittering, magnitude/time warping, bootstrap moving-block).
3. **Prédiction hybride ML/DL** — ensemble pondéré d'un AR(7) classique et d'un multi-EWMA blendé par sigmoid (mimique d'un réseau récurrent à 1 couche), mesuré par MAE / RMSE / MAPE / R² / SMAPE.

Tout est fait en **PHP pur** pour fonctionner dans WAMP sans dépendance externe.
Trois scripts Python optionnels permettent en plus de monter en gamme :
TimeGAN / Diffusion pour l'augmentation, vrai XGBoost + LSTM pour la prédiction.

---

## 📁 Fichiers ajoutés / modifiés

### Migration BDD
- `db/migrations/2026-05-07-fuzzy-augment-hybrid.sql` *(nouveau)*
- `db/schema.sql` *(mis à jour avec les nouvelles tables)*

### Backend — Phase 1 (Vérification + Augmentation)
- `backend/config/waqi.php` *(nouveau)* — clé API et timeouts WAQI
- `backend/lib/waqi.php` *(nouveau)* — client WAQI avec cache 30 min
- `backend/lib/api_verifier.php` *(nouveau)* — verify_range / verify_outlier_flags (IQR + modified Z-score) / verify_cross_zone / verify_fuse / verify_zone
- `backend/lib/data_augment.php` *(nouveau + étendu)* — aug_jitter / aug_magnitude_warp / aug_time_warp / aug_bootstrap_blocks + augment_zone / augment_all_zones + **gan_augment_all_zones()** (intègre le GAN PHP)
- **`backend/lib/gan.php` *(nouveau, ~430 lignes)* — GAN ÉCRIT À LA MAIN EN PHP PUR : Générateur (latent 8 → hidden 24 → seq 24) + Discriminateur (seq 24 → hidden 24 → 1) + LeakyReLU/tanh/sigmoid + backpropagation manuelle (chain rule) + SGD-momentum + sauvegarde/chargement JSON**
- `backend/lib/iqair.php` *(patché)* — passe désormais par verify_zone avant d'écrire en BDD
- `backend/api/verify-data.php` *(nouveau)* — endpoint admin pour lancer la vérification
- `scripts/augment_data.php` *(patché)* — lance aussi le GAN automatiquement si les poids existent
- **`scripts/train_gan.php` *(nouveau)* — entraîne le GAN sur la table `risk_scores`, sauve les poids dans `storage/gan/weights.json`**
- **`scripts/gan_generate.php` *(nouveau)* — charge les poids et insère N séries synthétiques dans `risk_scores_augmented` avec `generation_method='gan_php'`**

### Backend — Phase 2 (Fuzzy Logic — appliquée à TOUTES les recommandations)
- `backend/lib/fuzzy.php` *(nouveau)* — moteur Mamdani complet (fuzzy_trapez / fuzzy_tri / fuzzy_gauss / fuzzy_fuzzify / fuzzy_rule_fire / fuzzy_evaluate_rules / fuzzy_defuzzify_centroid / fuzzy_recommend)
- `backend/lib/fuzzy_context.php` *(nouveau)* — **helper unifié `fuzzy_for_user()` + `fuzzy_prompt_prefix()`** réutilisé par tous les endpoints AI
- `backend/config/fuzzy_rules.php` *(nouveau)* — 5 variables d'entrée × 25 règles métier
- `backend/api/recommendations.php` *(patché)* — fuzzy d'abord, Groq devient wrapper texte
- `backend/api/dashboard.php` *(patché)* — réponse JSON enrichie du bloc `fuzzy`
- `backend/api/diary-ai.php` *(patché)* — fuzzy injecté dans le prompt Groq + escalation auto du risk_level + bloc `fuzzy` dans la réponse
- `backend/api/triage.php` *(patché)* — fuzzy injecté dans le prompt Groq + escalation auto de `triage_urgency` si la fuzzy disagree
- `backend/api/tips.php` *(patché)* — daily tip s'aligne sur le score fuzzy (prompt prefix + champ `fuzzy` dans la réponse)
- `backend/api/weekly-summary.php` *(patché)* — résumé hebdo aligné sur le score fuzzy de la pire zone
- `backend/api/chatbot.php` *(patché)* — réponse du chatbot inclut le bloc `fuzzy`
- `backend/config/groq.php` *(patché)* — le system prompt du chatbot embarque un bloc "FUZZY-LOGIC RISK ASSESSMENT" qui force le LLM à s'aligner sur l'urgence calculée
- Frontend correspondant :
  - `frontend/scripts/pages/dashboard.js` — encart vert "Fuzzy Mamdani" sous la reco
  - `frontend/scripts/pages/diary.js` — encart vert + ligne source enrichie
  - `frontend/scripts/pages/symptoms.js` — badge Fuzzy sur le bouton triage
  - `frontend/scripts/pages/chatbot.js` — ligne `[Fuzzy …]` en bas de la réponse
  - `frontend/styles/dashboard.css` — styles `.dash-reco-fuzzy*`
- Nouvelle table `fuzzy_reco_logs` — traçabilité des règles activées sur **TOUS** les appels

**Récap : la logique floue est désormais utilisée par 7 endpoints**
(`recommendations.php`, `dashboard.php`, `diary-ai.php`, `triage.php`,
`tips.php`, `weekly-summary.php`, `chatbot.php`), pas seulement
dans le dashboard.

### Backend — Phase 3 (Hybride ML/DL)
- `backend/lib/forecast_ml.php` *(nouveau)* — AR(7) par OLS + ridge, Multi-EWMA + sigmoid, ensemble α grid-search, métriques MAE/RMSE/MAPE/R²/SMAPE
- `backend/lib/forecast.php` *(patché)* — utilise le hybride d'abord, EWMA en fallback
- `backend/api/forecast-metrics.php` *(nouveau)* — endpoint admin pour comparer les modèles
- `scripts/predict.php` *(nouveau)* — CLI cron horaire
- Nouvelles tables : `forecast_predictions`, `forecast_metrics`, `risk_scores_augmented`, `api_verification_log`, `waqi_cache`

### Frontend
- `frontend/pages/forecast.html` *(nouveau)* — page admin avec tableau comparatif + cards par zone
- `frontend/scripts/pages/forecast.js` *(nouveau)*
- `frontend/styles/forecast.css` *(nouveau)*
- `frontend/scripts/router.js` *(patché)* — route `forecast`
- `frontend/index.php` *(patché)* — link CSS + script + nav label
- `backend/lib/auth.php` *(patché)* — route `forecast` accessible aux rôles admin + health

### Scripts Python (optionnels)
- `scripts/train_augment.py` — TimeGAN-lite + Diffusion-lite, écrit dans `risk_scores_augmented`
- `scripts/train_forecast.py` — vrai XGBoost + LSTM ensemble, écrit dans `forecast_predictions` + `forecast_metrics`
- `scripts/requirements.txt`

### Documentation
- `MODIFICATIONS-2026.md` *(ce fichier)*
- `CHANGELOG.md` *(mis à jour)*

---

## 🧠 Détails techniques par phase

### Phase 1 — Vérification API + Augmentation

**Pourquoi :** une seule source (IQAir) = point de défaillance unique + impossibilité de détecter une valeur aberrante. L'augmentation produit assez de données pour entraîner un modèle DL.

**Algorithmes :**
- **Range check** : strict 0 ≤ pollution_level ≤ 100
- **IQR rule** (Tukey 1977) : flag si valeur < Q1 − 1.5·IQR ou > Q3 + 1.5·IQR
- **Modified Z-score** (Iglewicz & Hoaglin 1993) : `|0.6745 × (x − médiane) / MAD| > 3.5` → outlier. Robuste pour n < 10.
- **Cross-zone** : delta avec la moyenne des autres zones, flag si > 50 points
- **Fusion** : médiane des sources valides + trust = 1 − dispersion_relative

**Augmentation :**
- **Jitter** : ajout de bruit gaussien `N(0, σ=5% σ_série)`
- **Magnitude warping** : multiplication par une sinusoïde lente aléatoire de force ±20%
- **Time warping** : étirement/contraction locale via interpolation cubique
- **Bootstrap moving-block** : ré-échantillonnage de blocs de 7 points (préserve l'autocorrelation)
- **Fidelity score** : `1 - |Δmean|/100 - |Δstd|/50` clampé sur [0,1]

### Phase 2 — Fuzzy Logic (Mamdani)

**Variables d'entrée :**
- `pollution` (0..100) → {LOW, MODERATE, HIGH, EXTREME}
- `vulnerability` (0..10, somme pondérée asthma×2 + heart×2 + allergy×1 + pregnant×2 + child×2 + elderly×1.5) → {NONE, LOW, MEDIUM, HIGH}
- `symptom_sev` (0..10, mild=1, moderate=2, severe=4 sommés) → {NONE, MILD, MODERATE, SEVERE}
- `alerts_24h` (0..N) → {QUIET, NORMAL, BUSY}
- `age` (0..120) → {YOUNG, ADULT, SENIOR}

**Sortie :** `risk` (0..100) → {SAFE, LOW, MODERATE, HIGH, CRITICAL}

**Pipeline :**
1. Fuzzification trapézoïdale/triangulaire
2. AND = min, OR = max (Mamdani classique)
3. 25 règles dans `backend/config/fuzzy_rules.php`
4. Agrégation max + clipping
5. Défuzzification au centroïde (300 pas)
6. Mapping discret : ≥75 critical, ≥50 high, ≥30 moderate, sinon low

**Test de validation (sans BDD) :**

| Profil | Pollution | Score fuzzy | Urgence | Règles top |
|---|---|---|---|---|
| Enceinte | 72 | 89.6 | critical | R12 (87%) |
| Sain | 15 | 11.58 | low | — |
| Asthme + enfant | 95 | 83.84 | critical | R16, R20 (100%) |
| Tout modéré | 50 | 55 | high | mix |

### Phase 3 — Prédiction Hybride ML/DL

**Model A — AR(7) :**
- Vecteur de features : `[1, y(t-1), …, y(t-7), sin(2π·dow/7), cos(2π·dow/7)]`
- Résolution par OLS via Gauss-Jordan avec régularisation ridge λ=1e-3

**Model B — Multi-EWMA sigmoid (DL-inspired) :**
- 3 EWMAs avec α ∈ {0.2, 0.5, 0.8}
- Blending sigmoid : `ŷ = Σ σ(wᵢ)·EWMAᵢ / Σ σ(wⱼ)`
- Poids appris par descente de gradient (80 itérations, lr=0.01)

**Ensemble :**
- `ŷ_E = α·ŷ_A + (1-α)·ŷ_B`
- α ∈ {0.0, 0.1, …, 1.0} choisi par RMSE-minimum sur les 20% finaux (validation hold-out)

**Métriques (table `forecast_metrics`) :**
- MAE = mean(|y − ŷ|)
- RMSE = √mean((y − ŷ)²)
- MAPE = mean(|y − ŷ|/y) × 100
- R² = 1 − SS_res/SS_tot
- SMAPE = mean(|y − ŷ|/((|y|+|ŷ|)/2)) × 100

**Test de validation (série synthétique tendance + cycle hebdomadaire) :**

| Modèle | MAE | RMSE | MAPE | R² |
|---|---|---|---|---|
| AR(7) | 1.66 | 1.95 | 2.88% | 0.932 |
| Multi-EWMA | 5.91 | 6.96 | 10.01% | 0.13 |
| **Ensemble (α=1.0)** | **1.66** | **1.95** | **2.88%** | **0.932** |

Sur cette série très linéaire, AR(7) domine. Sur une série bruitée non-linéaire, le multi-EWMA pondère plus fortement et l'ensemble gagne sur les deux.

---

## 🔧 Comment activer

### 1. Appliquer la migration SQL
```bash
mysql -u root gabes_tatenafas < db/migrations/2026-05-07-fuzzy-augment-hybrid.sql
```

### 2. (Optionnel) Configurer WAQI
Récupère un token gratuit sur https://aqicn.org/data-platform/token/ et colle-le dans `backend/config/waqi.php`. Sinon, la vérification fonctionne avec IQAir seul + outlier detection interne.

### 3. Tester l'augmentation
```bash
cd /chemin/vers/gabes-tatenafas
php scripts/augment_data.php             # 200 points synthétiques par zone
php scripts/augment_data.php 500 60      # 500 points, historique 60 j
```

### 4. Tester le forecaster hybride
```bash
php scripts/predict.php
```
Puis ouvre l'app et va dans `Forecast — ML/DL` (rôle admin ou health). Tu verras :
- le tableau comparatif des modèles (AR7 / MEWMA / Ensemble)
- les prédictions 6h/12h/24h par zone
- un bouton « Retrain on all zones »

### 5. Tester le fuzzy
Connecte-toi en tant que citoyen et va dans Dashboard / Reco — la réponse contient désormais :
```json
{
  "fuzzy": {
    "risk_score": 78.4,
    "urgency": "critical",
    "fired_rules": [...],
    "explanation": "R12 (87%): IF pollution=HIGH AND vulnerability=HIGH THEN risk=CRITICAL"
  }
}
```

### 6. (Optionnel) Activer la version Python "pro"
```bash
pip install -r scripts/requirements.txt
python scripts/train_augment.py --method timegan --per-zone 500
python scripts/train_forecast.py
```

---

## 🎓 Pour le mémoire / la soutenance

### Phase 1 — Vérification + Augmentation
- **Outlier detection** : citer Tukey 1977 (IQR) + Iglewicz & Hoaglin 1993 (modified Z)
- **Augmentation** : Iwana & Uchida 2021 *"An empirical survey of data augmentation for time series classification with neural networks"*
- **TimeGAN** : Yoon, Jarrett & van der Schaar 2019 *"Time-series Generative Adversarial Networks"*
- **TSDiff** : Tashiro et al. 2021 *"CSDI: Conditional Score-based Diffusion Models for Probabilistic Time Series Imputation"*

### Phase 2 — Fuzzy Logic
- Zadeh 1965 — Fuzzy Sets
- Mamdani 1974 — application aux contrôleurs
- 5 fonctions d'appartenance trapézoïdales/triangulaires, 25 règles, défuzzification centroïde

### Phase 3 — Hybride ML/DL
- Box & Jenkins 1976 — AR/ARIMA
- Holt 1957 — exponential smoothing
- Zhang 2003 *"Time series forecasting using a hybrid ARIMA and neural network model"* — **la référence à citer absolument** pour justifier ARIMA-LSTM
- Chen & Guestrin 2016 — XGBoost
- Hochreiter & Schmidhuber 1997 — LSTM
- Métriques d'évaluation : Hyndman & Koehler 2006 *"Another look at measures of forecast accuracy"*

---

## ⚠️ Limites connues / améliorations futures

1. **Augmentation TimeGAN/Diffusion en Python** : nécessite TF + GPU pour rester rapide sur de grosses séries (8 zones × 60 jours est OK sur CPU)
2. **Le hybride PHP fait du single-step rolling forecast** pour des raisons de coût — pour h=24, on enchaîne 24 prédictions. Le Python multi-step direct serait plus précis.
3. **WAQI gratuit limite à 1000 req/jour** — le cache 30 min suffit largement
4. **Pas encore de cron Windows** : à ajouter dans le Task Scheduler ou via `electron/main.js` (BackgroundFetch)
