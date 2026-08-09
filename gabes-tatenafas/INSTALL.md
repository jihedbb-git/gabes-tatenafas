# Installation — Gabès-Tatenafas v2

## Prérequis
- WAMP (ou XAMPP) avec PHP 8.1+ et MariaDB 10.6+
- Extensions PHP activées : `php_curl`, `php_fileinfo`, `php_mbstring`, `php_pdo_mysql`

## 3 étapes

### 1. Extraire le ZIP
Décompressez `gabes-tatenafas-v2.zip` dans :
```
C:\wamp64\www\gabes-tatenafas\
```
(remplacez par votre chemin WAMP si différent)

### 2. Migrer la base de données
Ouvrez phpMyAdmin → sélectionnez la base `gabes_tatenafas` → onglet **SQL** → collez le contenu de :
```
db/migrations/2026-05-03-full-features.sql
```
Puis cliquez **Exécuter**.

> Si c'est une **première installation** (BD vide), exécutez d'abord `db/schema.sql` qui contient déjà toutes les tables et colonnes.

La migration est **idempotente** — vous pouvez la relancer sans risque.

### 3. Redémarrer WAMP
Cliquez sur l'icône WAMP → **Restart All Services**.

## Vérifier que tout fonctionne

Ouvrez Chrome :
```
http://localhost/gabes-tatenafas/
```

Connectez-vous (citizen1 / citizen123 par exemple) et vérifiez :

- **Dashboard** : la carte « Astuce du jour » apparaît + recommandation personnalisée si citoyen
- **Citizen Reports** : bouton 🎤 « Dicter (FR/AR) » sous la zone de description
- **Symptoms** : bouton « Demander un avis IA » sur chaque symptôme
- **Settings** (citoyen) : carte « Mon profil de santé » + carte « Consultation médicale »
- **Map** : slider Timelapse en haut + sélecteur Prévision IA
- **Sidebar** : nouveaux liens « Health Diary », « Correlations », « Weekly AI Report »

## Troubleshooting

### « Analyse IA indisponible » sur les images
SSL non configuré. Le projet contient `GROQ_VISION_INSECURE = true` dans
`backend/lib/groq_vision.php` qui contourne ce problème pour le dev local.
Pour la production, configurez `curl.cainfo` et `openssl.cafile` dans
`php.ini` avec `cacert.pem` (téléchargeable sur https://curl.se/ca/cacert.pem).

### Triage / résumé hebdo n'arrivent pas
Mêmes prérequis SSL. Le client Groq partage la même configuration
(`GROQ_CLIENT_INSECURE = true` dans `backend/lib/groq_client.php`).

### Microphone refusé
Chrome bloque le micro sur HTTP autre que localhost. Si vous accédez via
une IP du réseau local, utilisez `localhost` ou activez HTTPS.

### Téléconsultation Jitsi ne s'ouvre pas
Le bouton ouvre une nouvelle fenêtre — vérifiez qu'aucun bloqueur de
popup n'est actif.
