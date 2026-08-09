# 📘 GABÈS-TATENAFAS v2.0 — GUIDE COMPLET (installation → IA réelle)

Système intelligent de prédiction et de surveillance de la pollution (AQI) à Gabès.
Architecture : **Python (modèles IA)** ↔ **PHP (web)** ↔ **MySQL (données)**.

Ce guide vous mène de zéro jusqu'à des pages qui affichent des résultats **réels**
(entraînés sur votre base), avec le CGAN, le temps réel WebSocket, etc.

---

## 0) Ce qu'il vous faut

- **WAMP** (Apache + MySQL/MariaDB + PHP 7.4+).
- **Python 3.10 – 3.12** (`python --version`).
- Le dossier du projet dans : `C:\wamp64\www\gabes-tatenafas-v2`
- Navigateur (Chrome/Edge).

> Toute l'IA marche même sans TensorFlow (RF + XGBoost). Mais **BiLSTM,
> Autoencoder et le CGAN** ont besoin de TensorFlow (voir étape 2).

---

## 1) Installer le projet + la base de données

1. Copiez le dossier `gabes-tatenafas-v2` dans `C:\wamp64\www\`.
2. Démarrez WAMP (icône verte).
3. Ouvrez **phpMyAdmin** : `http://localhost/phpmyadmin` (user `root`, mot de passe vide).
4. Créez la base **`gabes_tatenafas`** (si elle n'existe pas) et importez :
   - `db/gabes_tatenafas_real.sql`  ← votre vraie base
5. Appliquez la mise à niveau v2 (ajoute les colonnes/tables scientifiques, **sans rien casser**) :
   - `db/upgrade_v2_real.sql`

> `upgrade_v2_real.sql` est **idempotent** : vous pouvez le relancer sans risque.

Vérification rapide (onglet SQL de phpMyAdmin) :
```sql
SHOW TABLES;                 -- doit inclure model_performance, anomaly_events, ...
SELECT COUNT(*) FROM zones;   -- 7 (ou 8) zones
```

---

## 2) Installer Python + les dépendances IA

Dans un terminal (invite de commandes) :
```bash
cd C:\wamp64\www\gabes-tatenafas-v2\models
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Cela installe : numpy, scipy, scikit-learn, pandas, xgboost, optuna, shap, lime,
statsmodels, flask, flask-socketio, flask-cors, mysql-connector-python, **tensorflow**.

> Si TensorFlow est trop lourd à installer : le reste fonctionne quand même
> (RF + XGBoost + Fuzzy + Granger + ...). Seuls BiLSTM / Autoencoder / CGAN
> exigent TensorFlow.

Test de connexion à la base (doit afficher `OK`) :
```bash
python -c "from db_config import try_connection; print('OK' if try_connection() else 'NO DB')"
```

---

## 3) Augmenter la base avec le CGAN (données synthétiques)

Vos zones n'ont qu'~150 lignes réelles → trop peu. On agrandit la base :

```bash
cd C:\wamp64\www\gabes-tatenafas-v2
python -m models.augment_db --per-zone 1200
```

- **Avec TensorFlow** → génération par **CGAN** (méthode `timegan`, version `cgan-v2`).
  Vous verrez : `zone X: +1200 synthetic rows (cgan-v2)`.
- **Sans TensorFlow** → repli statistique (`stat-v1`).

Pour repartir proprement en CGAN si vous aviez généré du statistique avant :
```sql
DELETE FROM risk_scores_augmented WHERE generator_version = 'stat-v1';
```
puis relancez la commande ci-dessus.

Vérifier ce qui a été généré :
```sql
SELECT generator_version, COUNT(*) FROM risk_scores_augmented GROUP BY generator_version;
```

---

## 4) Entraîner TOUS les modèles sur les données réelles ⭐

```bash
cd C:\wamp64\www\gabes-tatenafas-v2
python -m models.train_all
```

Ce script :
1. charge les **vraies données** (`risk_scores_augmented` + `risk_scores` + `zones` + `api_readings`) ;
2. construit le vecteur de **27 features** (lags + Fuzzy Type-2 + météo/polluants + temps) ;
3. entraîne **AR(7)**, **Random Forest**, **XGBoost** (+ BiLSTM si TensorFlow) pour **+1h / +6h / +24h** ;
4. évalue MAE / RMSE / MAPE / SMAPE / R² + F1 + **Wilcoxon** ;
5. sauvegarde les modèles dans `models/saved/*.pkl` (et `.h5`) ;
6. **écrit les résultats dans la base** (`model_performance`, `model_predictions`,
   `fuzzy_assessments`, `health_impact`).

Sortie attendue (exemple) :
```
zone 1: 1358 rows -> training
zone 1 1h Random Forest: RMSE=... R2=... F1=...
...
DONE. N metric rows. Models in .../models/saved/
```

> C'est cette étape qui fait passer les pages de **« Données démo »** → **« réel »**.

Vérifier (doit renvoyer un nombre > 0) :
```sql
SELECT COUNT(*) FROM model_performance WHERE horizon IS NOT NULL;
```

---

## 5) Lancer l'API Python (PHP → modèles)

Ouvrez un terminal dédié (laissez-le ouvert) :
```bash
cd C:\wamp64\www\gabes-tatenafas-v2\models
python api_server.py         # Flask REST -> http://localhost:5000
```

---

## 6) Lancer le temps réel WebSocket (badge 🟢 LIVE)

Ouvrez un **2e** terminal dédié :
```bash
cd C:\wamp64\www\gabes-tatenafas-v2\models
python websocket_server.py   # Flask-SocketIO -> http://localhost:5001
```
Le badge en haut à droite passe à **🟢 LIVE** et les valeurs AQI se mettent à jour seules.

---

## 7) Ouvrir l'application web

```
http://localhost/gabes-tatenafas-v2/frontend/index.php
```
Connectez-vous avec un compte **admin** ou **health** (ce sont les rôles qui voient
les pages scientifiques).

### Les nouvelles pages (sidebar)
| Page | Contenu | Réel après… |
|------|---------|-------------|
| Fuzzy Logic Type-2 | Karnik-Mendel, FOU, score clé | étape 4 |
| Conditional GAN | courbes G/D, réel vs généré, augmentation | étape 3-4 |
| ML — SHAP / LIME / ROC | RF + XGBoost + Optuna | étape 4 |
| Deep Learning — BiLSTM | BiLSTM + attention | étape 4 **+ TensorFlow** |
| Détection d'anomalies | Autoencoder + IsolationForest | étape 4 **+ TensorFlow** |
| Comparaison des modèles | métriques, ablation, Wilcoxon, ROC | étape 4 |
| Causalité de Granger | SO2→PM2.5, vent→AQI | étape 4 |
| Impact Sanitaire | indice spécifique Gabès | étape 4 |
| Dérive & Auto-Optimisation | KL + Optuna | étape 4 |
| Propagation spatiale | vent inter-villes | temps réel |
| Ensemble & Trust | poids + incertitude | étape 4 |
| Alertes intelligentes | SHAP + LIME + reco | étape 4 |
| Apprentissage fédéré | FedAvg | étape 4 |
| Comparaison littérature | vs publications | étape 4 |
| Vue d'ensemble | hub de tous les modules | toujours |

---

## 8) (Optionnel) Auto-optimisation quotidienne
```bash
python -m models.auto_optimizer
```
Détecte la dérive (KL), re-tune via Optuna, ré-entraîne si la RMSE s'améliore.

---

## 🔁 Ordre récapitulatif (à copier-coller)
```bash
# une seule fois : importer db/gabes_tatenafas_real.sql puis db/upgrade_v2_real.sql dans phpMyAdmin
cd C:\wamp64\www\gabes-tatenafas-v2\models
python -m pip install -r requirements.txt
cd C:\wamp64\www\gabes-tatenafas-v2
python -m models.augment_db --per-zone 1200
python -m models.train_all
# terminal 2 :
python models\api_server.py
# terminal 3 :
python models\websocket_server.py
# navigateur : http://localhost/gabes-tatenafas-v2/frontend/index.php
```

---

## 🔌 Ports
| Service | Commande | URL |
|--------|----------|-----|
| API REST modèles | `python models/api_server.py` | http://localhost:5000 |
| Temps réel WebSocket | `python models/websocket_server.py` | http://localhost:5001 |
| Interface web | WAMP/Apache | http://localhost/gabes-tatenafas-v2/frontend/index.php |

---

## 🧯 Fichiers importants
```
db/gabes_tatenafas_real.sql   base réelle
db/upgrade_v2_real.sql        mise à niveau v2 (ALTER + nouvelles tables)
models/db_config.py           connexion MySQL (root / vide / gabes_tatenafas)
models/data_loader.py         chargement des données réelles
models/augment_db.py          CGAN -> insère dans risk_scores_augmented
models/train_all.py           entraîne tout + écrit les résultats en base
models/cgan_trainer.py        Conditional GAN (PART 2)
models/fuzzy_type2.py         Fuzzy Type-2 (Karnik-Mendel)
models/ml_models.py           RF + XGBoost + Optuna + SHAP + LIME + ROC
models/dl_models.py           BiLSTM + Multi-Head Attention
models/anomaly_detector.py    Autoencoder + IsolationForest
models/api_server.py          Flask REST (port 5000)
models/websocket_server.py    SocketIO (port 5001)
backend/lib/sci_status.php    détecte si l'IA a été entraînée (badge réel/démo)
frontend/scripts/websocket_client.js  client temps réel (badge LIVE)
```

---

## 🛠️ Dépannage

| Symptôme | Cause / Solution |
|----------|------------------|
| Les pages affichent **« Données démo »** | L'IA n'est pas encore entraînée. Lancez `python -m models.train_all`. Vérifiez `SELECT COUNT(*) FROM model_performance WHERE horizon IS NOT NULL;` > 0. |
| `CGAN failed (No module named 'cgan_trainer')` | Ancienne version d'`augment_db.py`. Utilisez le dossier `models/` du dernier zip (import corrigé). |
| `NO DB` / connexion refusée | MySQL non démarré (WAMP) ou identifiants différents → voir `models/db_config.py` (ou variables `GT_DB_*`). |
| `train_all` dit *« only X rows, skipping »* | Pas assez de données. Lancez d'abord `python -m models.augment_db --per-zone 1200`. |
| `training_summary.json` vide | Idem : augmentez la base puis relancez `train_all`. |
| Deep Learning / Anomalies restent en démo | Ces modèles exigent **TensorFlow** : `pip install tensorflow`, puis `python -m models.train_all`. |
| Badge WebSocket **🔴 OFFLINE** | Lancez `python models/websocket_server.py` (port 5001). |
| `ModuleNotFoundError: sklearn/xgboost/...` | `python -m pip install -r models/requirements.txt`. |

---

## 🎯 Objectifs qualité (Springer / Soft Computing)
Meilleur modèle (+1h) : RMSE < 6.0 · R² > 0.90 · F1 > 0.87 · AUC > 0.93.
vs AR(7) : RMSE −≥30% · F1 +≥25% · AUC +≥20%. Wilcoxon p < 0.05.

> Astuce : plus vous augmentez la base (étape 3, ex. `--per-zone 3000`) et plus
> Optuna fait d'essais, meilleurs seront les résultats.
