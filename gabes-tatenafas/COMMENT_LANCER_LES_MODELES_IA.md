# 🧠 GABÈS-TATENAFAS v2.0 — Comment lancer les modèles IA (sur données réelles)

Ce guide explique, étape par étape, comment entraîner et faire tourner tous les
modèles IA (Fuzzy Type-2, Random Forest, XGBoost+Optuna, BiLSTM, Autoencoder,
Ensemble, Granger, Wilcoxon, WebSocket temps réel) **à partir de votre vraie
base de données** `gabes_tatenafas`.

> Architecture : **Python (modèles)** ↔ **PHP (web)** ↔ **MySQL (données)**
> Les pages PHP affichent des données de démo tant que les modèles ne sont pas
> entraînés ; une fois l'entraînement fait, elles basculent automatiquement sur
> les **vrais résultats** écrits dans la base.

---

## 0. Prérequis

- **WAMP** (Apache + MySQL/MariaDB + PHP 7.4+) déjà utilisé par le projet.
- **Python 3.10+** installé (`python --version`).
- Le projet placé dans `C:\wamp64\www\gabes-tatenafas` (ou votre chemin habituel).

---

## 1. Importer / mettre à jour la base de données

1. Ouvrez **phpMyAdmin** (`http://localhost/phpmyadmin`).
2. S'il n'existe pas encore, créez la base **`gabes_tatenafas`** puis importez
   votre dump réel : `db/gabes_tatenafas_real.sql`.
3. Appliquez la mise à niveau v2 (ajoute les colonnes/tables scientifiques,
   **sans rien casser**) : importez `db/upgrade_v2_real.sql`.

> `upgrade_v2_real.sql` est idempotent (`ADD COLUMN IF NOT EXISTS`,
> `CREATE TABLE IF NOT EXISTS`) — vous pouvez le relancer sans risque.

---

## 2. Installer les dépendances Python

Dans un terminal, à la racine du projet :

```bash
cd models
python -m pip install -r requirements.txt
```

(Si l'installation de TensorFlow est trop lourde, les modèles classiques
RF / XGBoost fonctionnent quand même ; le BiLSTM/Autoencoder sont simplement
ignorés si TensorFlow est absent.)

---

## 3. (Optionnel) Vérifier la connexion à la base

Les identifiants par défaut correspondent à WAMP (`127.0.0.1`, user `root`, mot de
passe vide, base `gabes_tatenafas`) — voir `models/db_config.py`.
Pour changer : définissez les variables d'environnement `GT_DB_HOST`, `GT_DB_USER`,
`GT_DB_PASS`, `GT_DB_NAME`.

```bash
python -c "from db_config import try_connection; print('OK' if try_connection() else 'NO DB')"
```

---

## 3.5 (RECOMMANDÉ) Augmenter la base avec le CGAN

Vos zones n'ont qu'~150 lignes réelles — trop peu pour un bon entraînement.
Ce script génère des données synthétiques réalistes et les **insère dans la base**
(`risk_scores_augmented`) :

```bash
python -m models.augment_db --per-zone 1200
```

- Si **TensorFlow** est installé → génération par **CGAN** (méthode `timegan`, version `cgan-v2`).
- Sinon → repli statistique (jitter + magnitude-warp + bootstrap) qui préserve
  la distribution et le rythme journalier (pics industriels 6-8h & 14-16h).
- Forcer le repli : `python -m models.augment_db --per-zone 2000 --force-fallback`

Après cette étape, chaque zone possède ~1350 lignes → l'entraînement ci-dessous
devient bien plus solide.

---

## 4. Entraîner TOUS les modèles sur les données réelles

Depuis la **racine du projet** :

```bash
python -m models.train_all
```

ou depuis le dossier `models` :

```bash
cd models
python train_all.py
```

Ce script :
1. charge les **vraies données** (`risk_scores_augmented` + `risk_scores` +
   `zones` + `api_readings`) via `data_loader.py` ;
2. construit le vecteur de **27 features** (lags + Fuzzy Type-2 + météo/polluants + temps) ;
3. entraîne **AR(7)**, **Random Forest**, **XGBoost** (+Optuna si dispo) pour
   **+1h / +6h / +24h** ;
4. évalue MAE/RMSE/MAPE/SMAPE/R² + F1 + test de **Wilcoxon** vs baseline ;
5. sauvegarde les modèles dans `models/saved/*.pkl` (et `.h5`) ;
6. écrit les résultats dans la base : `model_performance`, `model_predictions`,
   `fuzzy_assessments`, `health_impact`.

> Un récapitulatif est aussi écrit dans `models/saved/training_summary.json`.

### Entraîner un module précis (facultatif)
```bash
python fuzzy_type2.py         # démo Type-2 + Karnik-Mendel
python data_simulator.py      # génère un jeu de secours si besoin
python ensemble.py            # poids softmax + trust
python statistical_tests.py   # Wilcoxon / Friedman
```

---

## 5. Lancer l'API Python (pour que PHP appelle les modèles)

```bash
cd models
python api_server.py          # Flask REST  -> http://localhost:5000
```

Laissez ce terminal ouvert. Les pages PHP peuvent alors appeler
`http://localhost:5000/predict`, `/attention_heatmap`, `/granger`, etc.

---

## 6. Lancer le serveur temps réel WebSocket (badge 🟢 LIVE)

Dans un **deuxième** terminal :

```bash
cd models
python websocket_server.py    # Flask-SocketIO -> http://localhost:5001
```

Le badge en haut à droite de l'interface passe à **🟢 LIVE** et les valeurs AQI
se mettent à jour automatiquement.

---

## 7. Ouvrir l'application web

```
http://localhost/gabes-tatenafas/frontend/index.php
```

Connectez-vous (rôle **admin** ou **health**) puis ouvrez les nouvelles pages dans
la sidebar :
- Fuzzy Logic Type-2, Conditional GAN, ML (SHAP/LIME/ROC), Deep Learning (BiLSTM),
  Anomalies, Comparaison des modèles, Granger, Impact Sanitaire, Dérive & AutoOpt,
  Propagation spatiale, Ensemble & Trust, Alertes intelligentes, Fédéré,
  Comparaison littérature, Vue d'ensemble des upgrades.

> Avant l'étape 4, les pages montrent un badge « Données démo ».
> Après l'étape 4, elles affichent les **vrais** résultats issus de la base.

---

## 8. (Optionnel) Boucle d'auto-optimisation quotidienne

```bash
python -m models.auto_optimizer
```
Détecte la dérive de concept (KL), re-tune via Optuna et ré-entraîne si la RMSE
s'améliore, puis met à jour `optimization_history`.

---

## Récapitulatif des ports
| Service | Commande | URL |
|--------|----------|-----|
| API REST modèles | `python models/api_server.py` | http://localhost:5000 |
| Temps réel WebSocket | `python models/websocket_server.py` | http://localhost:5001 |
| Interface web | WAMP/Apache | http://localhost/gabes-tatenafas/frontend/index.php |

## Dépannage
- **« NO DB » / connexion refusée** : démarrez MySQL dans WAMP, vérifiez `models/db_config.py`.
- **TensorFlow ne s'installe pas** : ce n'est pas bloquant ; RF + XGBoost suffisent pour un premier entraînement.
- **Les pages restent en « démo »** : relancez `python -m models.train_all` et vérifiez que `model_performance` contient des lignes avec une colonne `horizon`.
- **Pas assez de données réelles** : le loader complète automatiquement avec un jeu simulé ancré sur les facteurs de pollution réels des 7 zones.
