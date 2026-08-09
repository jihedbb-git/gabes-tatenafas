# قابس تتنفس — Gabes Tatenafas

> **Système intelligent d'alerte environnementale et sanitaire**
> Application desktop multi-plateforme (Windows / Linux / macOS) bâtie en **Electron + PHP + MySQL** avec **WAMP** pour la pile locale.

![status](https://img.shields.io/badge/status-prêt%20à%20présenter-success)
![stack](https://img.shields.io/badge/stack-Electron%20%2B%20PHP%20%2B%20MySQL-0d3b66)
![license](https://img.shields.io/badge/license-MIT-blue)

---

## ✨ Aperçu

Une application 100 % locale, sans authentification complexe, sans cloud, sans API externe, qui aide :

- les **citoyens** à connaître la qualité de l'air, signaler des incidents et déclarer leurs symptômes,
- les **autorités sanitaires** à suivre les tendances et générer des rapports PDF,
- les **directeurs d'école** à activer un *mode école* (vigilance / suspension / parents),
- les **administrateurs** à gérer les zones, alertes et signalements.

Design : **blanc cassé**, cartes arrondies, ombres douces, navigation fluide.

---

## 🗂️ Structure du projet

```
gabes-tatenafas/
├── electron/            # Process principal Electron
│   ├── main.js
│   ├── preload.js
│   ├── fallback.html
│   └── package.json
├── frontend/            # Interface utilisateur (HTML / CSS / JS vanilla)
│   ├── index.php        # Shell principal (sidebar + topbar + router)
│   ├── pages/           # 11 modules (dashboard, map, alerts, …)
│   ├── components/
│   ├── scripts/
│   │   ├── api.js       # wrapper fetch() vers PHP
│   │   ├── app.js       # state global (rôle, statut)
│   │   ├── router.js    # SPA hash router
│   │   └── pages/       # init<Page>() par module
│   ├── styles/          # theme.css, sidebar.css, roles.css
│   └── assets/
├── backend/             # PHP local
│   ├── config/database.php
│   ├── lib/helpers.php  # PDO, calcul Risk Score
│   └── api/             # endpoints JSON (dashboard, zones, alerts, …)
├── db/
│   └── schema.sql       # MySQL : tables + données de seed
├── assets/              # icônes générales
├── uploads/             # uploads citoyens (vide par défaut)
├── reports/             # PDF générés (vide par défaut)
├── package.json         # raccourci `npm start`
└── README.md
```

---

## 🧱 Tables MySQL

`users_roles`, `zones`, `alerts`, `reports`, `symptoms`, `school_status`, `risk_scores`, `chatbot_logs`, `reports_pdf`, `notifications`.
Voir `db/schema.sql` pour les définitions complètes et les données de démonstration (8 zones de Gabès, alertes, signalements, symptômes, écoles, scores, etc.).

---

## 🧭 Modules / Pages

| # | Module                | Route hash               | Rôles                    |
|---|-----------------------|--------------------------|--------------------------|
| 1 | Dashboard             | `#/dashboard`            | tous                     |
| 2 | Carte / Air Quality   | `#/map`                  | tous                     |
| 3 | Alertes               | `#/alerts`               | tous                     |
| 4 | Rapports (PDF)        | `#/reports`              | health, admin            |
| 5 | Signalements citoyens | `#/citizen-reports`      | citizen, admin           |
| 6 | Symptômes             | `#/symptoms`             | citizen, health          |
| 7 | Chatbot نفاس           | `#/chatbot`              | tous                     |
| 8 | Mode école            | `#/school`               | school, health, admin    |
| 9 | Zones à risque        | `#/zones`                | health, admin            |
|10 | Paramètres            | `#/settings`             | tous                     |
|11 | Aide                  | `#/help`                 | tous                     |

Le **sélecteur de rôle** (en haut à droite) change la couleur du bandeau et la vue par défaut sans authentification.

---

## ▶️ Installation et exécution

### 1. Prérequis

- **WAMP** (Windows) ou **MAMP / XAMPP / LAMP** (macOS / Linux) — Apache + PHP ≥ 7.4 + MySQL/MariaDB.
- **Node.js** ≥ 18 (pour Electron).

### 2. Placer le projet

#### Windows (WAMP)
Décompresser `gabes-tatenafas.zip` dans :
```
C:\wamp64\www\gabes-tatenafas
```

#### Linux (LAMP)
```
/var/www/html/gabes-tatenafas
```

#### macOS (MAMP)
```
/Applications/MAMP/htdocs/gabes-tatenafas
```

### 3. Importer la base de données

Ouvre **phpMyAdmin** → onglet **Importer** → sélectionne `db/schema.sql` → exécute.
Ou en CLI :
```bash
mysql -u root < db/schema.sql
```

> La base s'appelle `gabes_tatenafas`. L'utilisateur par défaut est `root` sans mot de passe (config WAMP/MAMP standard). Si différent, modifie `backend/config/database.php`.

### 4. Vérifier l'API PHP

Ouvre dans ton navigateur :
```
http://localhost/gabes-tatenafas/backend/api/dashboard.php
```
Tu dois voir un JSON contenant `global_status`, `counts`, `top_zones`, etc.

### 5. Lancer Electron

```bash
cd gabes-tatenafas
npm install
npm start
```

L'application s'ouvre, charge `http://localhost/gabes-tatenafas/frontend/index.php` et affiche le dashboard.

> 💡 Tu peux aussi simplement ouvrir `http://localhost/gabes-tatenafas/frontend/index.php` dans un navigateur — tout fonctionne pareil sans Electron.

---

## 🧮 Calcul du Risk Score

`backend/lib/helpers.php` — `compute_risk_score($zoneId)` :

```
risk = pollution_level × 0.5
     + min(100, reports_24h × 12) × 0.25
     + min(100, Σ severity_weight × 8) × 0.25
```
Niveaux : `safe < 40 ≤ warning < 70 ≤ critical`.
Bouton **« Recalculer scores »** disponible dans `Zones à risque` ou `Paramètres`.

---

## 🖨️ Export PDF

Les rapports sont générés en HTML imprimable (`backend/api/pdf.php?period=daily|weekly|monthly`).
Dans Electron ou navigateur : **Ctrl + P** → *Enregistrer en PDF*.

---

## 🎨 Thème

Variables CSS dans `frontend/styles/theme.css` :

| Token        | Valeur     | Usage                  |
|--------------|------------|------------------------|
| `--bg`       | `#f8f7f2`  | Fond global blanc cassé|
| `--primary`  | `#0d3b66`  | Bleu institutionnel    |
| `--safe`     | `#16a34a`  | Vert sécurité          |
| `--warning`  | `#d97706`  | Orange vigilance       |
| `--danger`   | `#dc2626`  | Rouge alerte           |

---

## 🐞 Dépannage

| Problème | Solution |
|----------|----------|
| Page blanche dans Electron | Vérifie que WAMP est démarré (icône verte). |
| Erreur `SQLSTATE[HY000] [1049]` | La base `gabes_tatenafas` n'existe pas → ré-importer `db/schema.sql`. |
| Erreur `Access denied for user` | Modifier `DB_USER` / `DB_PASS` dans `backend/config/database.php`. |
| Le port 80 est occupé | Arrête Skype/IIS, ou configure WAMP sur le port 8080 et corrige `electron/main.js` (`APP_URL`). |
| Caractères arabes en ?? | Vérifier que la table est bien en `utf8mb4_unicode_ci` (déjà fait dans le schéma). |

---

## 📝 Licence

MIT — projet pédagogique pour démonstration universitaire.

> *مدينة أذكى، هواء أنظف، وصحة أفضل* — *Une ville plus intelligente, un air plus pur, une meilleure santé.*
