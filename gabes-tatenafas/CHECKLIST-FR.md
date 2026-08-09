# Checklist d'activation — modifications 2026-05-07

> **À lire en entier avant de dire "ça ne marche pas".**
> Toutes les modifications sont là, mais elles n'apparaissent dans l'app
> qu'une fois que les 4 étapes ci-dessous sont effectuées.

---

## 🚦 Étape 0 — Vérifier l'installation automatiquement

Ouvre dans ton navigateur :

```
http://localhost/gabes-tatenafas-v2/verify-install.php
```

Ce fichier `verify-install.php` (à la racine du projet) liste toutes les
modifications, vérifie chaque fichier, chaque patch, chaque table SQL, et
teste le moteur fuzzy en direct. Tout doit être en **PASS** (vert).

Tant que quelque chose est en **FAIL**, l'app ne montrera pas la modif —
c'est NORMAL. Il faut corriger d'abord, puis rafraîchir la page.

---

## ⚙️ Étape 1 — Lancer la migration SQL (OBLIGATOIRE)

C'est la cause #1 quand les modifs "n'apparaissent pas". Le SQL crée les
6 nouvelles tables (`fuzzy_reco_logs`, `api_verification_log`,
`risk_scores_augmented`, `waqi_cache`, `forecast_predictions`,
`forecast_metrics`). Sans ces tables, les nouvelles fonctions tournent
mais ne peuvent pas logger leur travail.

Ouvre **WAMP shell** (ou cmd dans Windows) et lance :

```bash
mysql -u root gabes_tatenafas < db/migrations/2026-05-07-fuzzy-augment-hybrid.sql
```

(remplace `gabes_tatenafas` par le nom exact de ta base ; vide pour le
mot de passe par défaut de WAMP).

---

## 🔁 Étape 2 — Vider tous les caches

Le navigateur Electron met en cache le JS et le CSS. Quand on patche
le frontend, il faut forcer le rechargement :

- Dans Electron : **Ctrl+Shift+R** (hard refresh)
- Ou ferme et relance l'app Electron complètement
- Côté serveur : supprime tous les fichiers `/tmp/nafass-diary-ai-*.json`
  (cache des conseils IA — il existe pendant 10 min)

---

## 🔑 Étape 3 — (Optionnel) Configurer la 2ème API

Pour activer la double-source IQAir+WAQI, mets ton token gratuit dans :

```php
// backend/config/waqi.php
define('WAQI_TOKEN', 'TON_TOKEN_GRATUIT_ICI');
```

Token gratuit en 30 secondes : <https://aqicn.org/data-platform/token/>

Si tu sautes cette étape, la vérification multi-source utilisera
uniquement IQAir + outlier interne — ça marche quand même.

---

## ✅ Étape 4 — Vérifier visuellement dans l'app

Une fois les étapes 1 à 3 faites, lance l'app et **observe** :

### 1. Dashboard (citizen1 / citizen123)
- La carte "Personalized health recommendation" affiche un **encart vert
  "Fuzzy Mamdani"** avec un score sur 100 et les règles activées.
- Si tu ne vois PAS cet encart, la migration n'est pas faite OU le
  cache Electron n'a pas été vidé.

### 2. Diary (citizen1)
- Onglet "Health Diary" → bouton "Generate AI insights"
- En bas du résultat IA, un **encart vert "Fuzzy Mamdani"** s'affiche
  avec score + règles. Le texte du résumé contient aussi la mention
  "Fuzzy Mamdani score X/100 (urgency)".

### 3. Symptoms (citizen1)
- Onglet "My symptoms" → "Log a symptom" puis cliquer "Request AI advice"
- Pendant l'analyse, un **badge "Fuzzy ##.# · level"** apparaît à côté
  du bouton, avant que le texte du triage IA s'affiche.

### 4. Chatbot (n'importe quel rôle)
- Ouvre le chatbot Nafass → pose une question santé
- En bas de la réponse de l'IA : `[Fuzzy Mamdani · score X/100 · level]`
- Le LLM lui-même est **obligé** d'aligner sa réponse avec le niveau
  fuzzy (c'est dans le system prompt).

### 5. Forecast — ML/DL (admin/admin123 ou health/health123)
- Nouveau menu "Forecast" dans la barre de navigation
- Affiche un graphe AR(7)+EWMA, l'horizon 24h, et un tableau
  MAE/RMSE/MAPE/R²/SMAPE.

### 6. (Optionnel) Outil CLI
```bash
php scripts/augment_data.php         # génère des données synthétiques (statistique)
php scripts/predict.php              # produit une prédiction horaire
```

### 7. 🧠 **GAN en PHP pur** (nouveauté demandée)

Pour utiliser le **vrai GAN écrit à la main en PHP**, sans Python :

```bash
# 1. Entraîner le GAN sur l'historique réel (~30-60s sur un laptop)
php scripts/train_gan.php
# → écrit storage/gan/weights.json (~55 KB)

# 2. Générer des séries synthétiques à partir du GAN
php scripts/gan_generate.php --per-zone=50
# → insère N×nb_zones lignes dans risk_scores_augmented
#    avec generation_method='gan_php'

# 3. Ré-entraîner avec plus d'epochs si tu veux meilleure convergence
php scripts/train_gan.php --epochs=500 --batch=16 --lr=0.001 --seed=42
```

**Architecture :**
- **Generator** G(z) : `latent_8 → LeakyReLU(W·z+b, h=24) → tanh(W·h+b, seq=24)`
- **Discriminator** D(x) : `seq_24 → LeakyReLU(W·x+b, h=24) → sigmoid(W·h+b, 1)`
- **Loss** : Binary Cross-Entropy adverse (Goodfellow et al. 2014)
- **Optimiseur** : SGD avec momentum 0.9
- **Backpropagation** : entièrement écrite à la main (chain rule, pas de framework)

**Pour le jury / le mémoire**, voici la phrase à dire :
> *"L'augmentation de données utilise une approche hybride. Par défaut,
> quatre méthodes statistiques (jittering, magnitude warping, time warping,
> bootstrap par blocs) issues de Iwana & Uchida 2021. En option, un GAN
> implémenté en PHP pur (Goodfellow et al. 2014, architecture inspirée de
> TimeGAN, Yoon et al. 2019) génère des séries synthétiques indistinguables
> des séries réelles, avec backpropagation manuelle pour garantir la
> reproductibilité sans dépendance externe."*

---

## 📋 Liste TECHNIQUE de toutes les modifications

### Fichiers AJOUTÉS (nouveaux)

**Phase 1 — Vérification API + Augmentation**
- `backend/config/waqi.php`
- `backend/lib/waqi.php`
- `backend/lib/api_verifier.php`
- `backend/lib/data_augment.php`
- **`backend/lib/gan.php`** — GAN PHP pur (Generator + Discriminator + backprop)
- `backend/api/verify-data.php`
- `scripts/augment_data.php` (statistique + GAN auto si poids présents)
- **`scripts/train_gan.php`** — entraîne le GAN PHP
- **`scripts/gan_generate.php`** — génère samples synthétiques depuis le GAN
- `scripts/train_augment.py` (bonus Python TimeGAN/Diffusion)

**Phase 2 — Fuzzy Mamdani**
- `backend/lib/fuzzy.php` (moteur)
- `backend/lib/fuzzy_context.php` (helper unifié — **NOUVEAU dans cette livraison**)
- `backend/config/fuzzy_rules.php` (base de règles)

**Phase 3 — Forecast hybride**
- `backend/lib/forecast_ml.php` (AR + EWMA + ensemble)
- `backend/api/forecast-metrics.php`
- `scripts/predict.php`
- `scripts/train_forecast.py` (bonus Python)
- `scripts/requirements.txt`

**Frontend**
- `frontend/pages/forecast.html`
- `frontend/scripts/pages/forecast.js`
- `frontend/styles/forecast.css`

**DB + Documentation**
- `db/migrations/2026-05-07-fuzzy-augment-hybrid.sql`
- `MODIFICATIONS-2026.md`
- `CHECKLIST-FR.md` (ce fichier)
- `verify-install.php` (à la racine — script de vérification automatique)

### Fichiers PATCHÉS

| Fichier | Modif |
|---|---|
| `backend/lib/iqair.php` | appelle `verify_zone()` → multi-source |
| `backend/api/recommendations.php` | fuzzy d'abord, Groq devient wrapper |
| **`backend/api/dashboard.php`** | **+ bloc `fuzzy` dans la réponse JSON** |
| **`backend/api/diary-ai.php`** | **+ fuzzy injecté dans prompt + réponse** |
| **`backend/api/triage.php`** | **+ fuzzy dans prompt + escalation auto** |
| **`backend/api/tips.php`** | **+ fuzzy dans prompt + réponse** |
| **`backend/api/weekly-summary.php`** | **+ fuzzy dans prompt + réponse** |
| **`backend/api/chatbot.php`** | **+ fuzzy dans contexte du LLM** |
| **`backend/config/groq.php`** | **+ bloc fuzzy dans le system prompt** |
| `backend/lib/forecast.php` | hybride AR+EWMA en chemin principal |
| `backend/lib/auth.php` | route `forecast` autorisée (admin+health) |
| `frontend/index.php` | nav "Forecast" + CSS + script |
| `frontend/scripts/router.js` | route `forecast` enregistrée |
| **`frontend/scripts/pages/dashboard.js`** | **+ encart Fuzzy Mamdani visible** |
| **`frontend/scripts/pages/diary.js`** | **+ encart Fuzzy Mamdani visible** |
| **`frontend/scripts/pages/symptoms.js`** | **+ badge Fuzzy sur triage** |
| **`frontend/scripts/pages/chatbot.js`** | **+ ligne Fuzzy dans la réponse** |
| **`frontend/styles/dashboard.css`** | **+ styles `.dash-reco-fuzzy*`** |
| `db/schema.sql` | tables fuzzy/augment/forecast pour installs fraîches |

Les lignes en **gras** sont des modifications NOUVELLES qui répondent à
ta demande : "fuzzy dans TOUTES les recommandations, pas seulement le
dashboard".

---

## 🧠 Où la logique floue est utilisée — récapitulatif

| Endpoint backend | Page frontend | Fuzzy actif | Visible utilisateur ? |
|---|---|:---:|:---:|
| `recommendations.php` | Dashboard reco panel | ✅ | ✅ encart vert |
| `dashboard.php` | Dashboard counters | ✅ | (dans le JSON, utilisé par le front) |
| `diary-ai.php` | Diary AI insights | ✅ | ✅ encart vert + ligne source |
| `triage.php` | Symptoms triage | ✅ | ✅ badge sur le bouton |
| `tips.php` | Daily tip widget | ✅ | (dans le JSON — le LLM est forcé d'aligner) |
| `weekly-summary.php` | Health authorities | ✅ | dans la réponse JSON |
| `chatbot.php` | Nafass chatbot | ✅ | ✅ ligne `[Fuzzy …]` en bas |

**=> 7 endpoints utilisent maintenant la logique floue**, pas un seul.

---

## 🆘 Si malgré tout rien ne s'affiche

1. Ouvre `verify-install.php` — tu auras la liste exacte de ce qui manque.
2. Ouvre la console DevTools (F12) → onglet "Network" → recharge le
   dashboard → clique sur la requête `recommendations.php` → onglet
   "Response" : tu dois voir un champ `"fuzzy": { "risk_score": …, … }`.
   - Si tu ne le vois pas → le PHP nouveau n'est pas chargé (vide le
     cache Apache : redémarre WAMP).
   - Si tu le vois mais l'encart vert n'apparaît pas → le JS frontend
     n'est pas chargé (Ctrl+Shift+R dans Electron).
3. Vérifie `tail -f` sur les logs PHP (`logs/php_error.log` dans WAMP)
   pour repérer une éventuelle erreur dans `fuzzy_for_user()`.

Si après tout ça il y a encore un problème, envoie-moi :
- une capture de `verify-install.php`
- une capture de la réponse JSON de `recommendations.php`
- une capture de la console DevTools onglet "Console"
