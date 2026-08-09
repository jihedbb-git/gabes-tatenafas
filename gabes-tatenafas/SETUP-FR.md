# Nafass — Gabès Tatenafas · Guide d'installation

Plateforme de surveillance qualité de l'air + santé pour Gabès, Tunisie.

## ✅ Pré-requis

- **WAMP / XAMPP / MAMP** (ou stack équivalent : Apache + MySQL + PHP ≥ 7.4)
- **Navigateur moderne** : Chrome, Edge, Firefox, ou Safari
- *Optionnel* : clé API Groq (pour les recommandations IA) — voir étape 5

## 📦 Étape 1 — Extraire le ZIP

Décompresser `gabes-tatenafas-final.zip` dans le dossier `www` de WAMP (ou `htdocs` de XAMPP) :

- WAMP : `C:\wamp64\www\gabes-tatenafas\`
- XAMPP : `C:\xampp\htdocs\gabes-tatenafas\`

## 🗄️ Étape 2 — Créer la base de données

1. Ouvrir **phpMyAdmin** (http://localhost/phpmyadmin)
2. Créer une base nommée `gabes_tatenafas` (UTF-8 / utf8mb4)
3. Sélectionner la base → onglet **Importer** → choisir `db/schema.sql` → Exécuter
4. Importer ensuite **dans l'ordre** chacune des migrations :
   ```
   db/migrations/2026-05-01-chat-and-photos.sql
   db/migrations/2026-05-02-ai-image-analysis.sql
   db/migrations/2026-05-03-full-features.sql
   db/migrations/2026-05-04-iqair.sql
   db/migrations/2026-05-05-telemed-requests.sql
   db/migrations/2026-05-06-telemed-enrichment-and-learn.sql
   ```

> Ou en ligne de commande :
> ```bash
> mysql -uroot -p gabes_tatenafas < db/schema.sql
> for f in db/migrations/*.sql; do mysql -uroot -p gabes_tatenafas < "$f"; done
> ```

## ⚙️ Étape 3 — Vérifier la configuration

Ouvrir `backend/config/database.php` :

```php
const DB_HOST = '127.0.0.1';
const DB_PORT = 3306;
const DB_NAME = 'gabes_tatenafas';
const DB_USER = 'root';
const DB_PASS = '';
```

**Adapter** si votre MySQL utilise d'autres identifiants.

## 🌐 Étape 4 — Lancer l'application

1. Démarrer **WAMP** (icône verte dans la barre des tâches)
2. Ouvrir : **http://localhost/gabes-tatenafas/frontend/**
3. Se connecter avec un des comptes de démo :

| Rôle      | Identifiant | Mot de passe |
|-----------|-------------|--------------|
| Admin     | `admin`     | `admin123`   |
| Sanitaire | `health`    | `health123`  |
| Directeur | `school`    | `school123`  |
| Citoyen   | `citizen1`  | `citizen123` |

## 🤖 Étape 5 (optionnelle) — Activer l'IA Groq

Pour les recommandations IA personnalisées (page Daily Diary), ajouter une clé Groq :

1. Obtenir une clé gratuite sur https://console.groq.com/keys
2. Ouvrir `backend/config/groq.php`
3. Ajouter la clé :
   ```php
   const GROQ_API_KEY = 'gsk_xxxxxxxxxxxxx';
   ```

Si la clé est absente, l'IA utilise un **fallback local heuristique** (l'analyse fonctionne quand même mais sans LLM).

## 🚀 Étape 6 — Tester le système

| Page | Test rapide |
|------|-------------|
| **#/dashboard** | Voir les zones, recommandations personnalisées |
| **#/map** | Carte Leaflet avec marqueurs colorés |
| **#/diary** | Saisir une entrée → cliquer **Generate insights** → recommandations IA |
| **#/learn** | Cliquer une carte → modal s'ouvre → bouton X ferme |
| **#/settings** (citoyen) | Remplir le checklist + cliquer **Request Consultation** → salle d'attente avec timer 15:00 |

## 🛠️ Dépannage

**"Network error" sur consultation / IA** → vérifier que MySQL tourne et que la base `gabes_tatenafas` est bien importée.

**Modal qui reste ouvert / spinner figé** → vider le cache navigateur (Ctrl+Shift+R) — le service worker doit recharger la nouvelle version.

**Page blanche** → ouvrir la console du navigateur (F12) → onglet *Network* pour voir les requêtes échouées. Vérifier les permissions sur `frontend/uploads/`.

**Erreur PHP "Call to undefined function mb_substr"** → résolu (polyfill mbstring intégré). Mais pour de meilleures performances, activer l'extension `mbstring` dans `php.ini` (décommenter `extension=mbstring`).

## 📱 PWA (mode hors-ligne)

L'app s'installe comme une application native :
- **Chrome / Edge** : icône d'installation dans la barre d'adresse
- Une fois installée, fonctionne offline avec le dernier état connu

## 📂 Structure du projet

```
gabes-tatenafas-v-der/
├── backend/
│   ├── api/           ← endpoints REST (PHP)
│   ├── config/        ← configuration DB + Groq
│   └── lib/           ← bibliothèques internes
├── db/
│   ├── schema.sql     ← schéma initial
│   └── migrations/    ← migrations idempotentes
├── frontend/
│   ├── index.php      ← point d'entrée SPA
│   ├── pages/         ← templates HTML
│   ├── scripts/       ← JS (router, pages, PWA)
│   ├── styles/        ← CSS modulaires
│   ├── manifest.json  ← manifeste PWA
│   ├── sw.js          ← service worker
│   └── offline.html   ← page hors-ligne
└── SETUP-FR.md        ← ce fichier
```

## 📝 Fonctionnalités clés

- 🗺️ Carte interactive de Gabès (8 zones + IQAir)
- 📊 Dashboard avec recommandations IA
- 🔬 Triage symptômes (LLM Groq)
- 📷 Vision IA (analyse photos pollution)
- 🎙️ Chat vocal (Whisper)
- 📅 Journal santé personnel + insights IA 30 jours
- 🩺 Téléconsultation Jitsi (15 min, pré/post-consultation, e-prescription PDF)
- 📚 Module Apprendre & Prévenir (articles, vidéos, quizz, infographies)
- 📱 PWA installable + mode offline
- 🌐 Multi-rôles : citoyen, sanitaire, directeur école, admin

---

**Support** : si problème, vérifier les logs PHP (`logs/` ou console WAMP/XAMPP) et la console navigateur (F12).
