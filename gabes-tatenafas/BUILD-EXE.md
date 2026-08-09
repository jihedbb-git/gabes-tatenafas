# 📦 Nafass — Build Windows .exe

## Prérequis (à vérifier une seule fois)

- **Node.js** v18 ou supérieur → https://nodejs.org/  (vérifie avec `node -v`)
- **WAMP** installé (déjà fait pour `npm start`)
- Connexion internet (pour télécharger electron-builder, ~150 Mo la première fois)

---

## 🚀 Build du `.exe` (3 étapes)

Ouvre **CMD** ou **PowerShell** dans `C:\wamp64\www\gabes-tatenafas\` puis lance :

### 1) Installer electron-builder (une seule fois)

```cmd
npm install
```

> Cette commande installe `electron` + `electron-builder`. Ça prend ~3 minutes la première fois.

### 2) Générer le `.exe`

```cmd
npm run dist:win
```

> Construit l'installeur Windows. Ça prend ~2 minutes.

### 3) Récupérer le fichier

Tu trouveras dans `C:\wamp64\www\gabes-tatenafas\dist\` :

| Fichier | Description |
|---|---|
| `Nafass-1.0.0-x64.exe` | **Installeur Windows** (recommandé pour la soutenance) |
| `Nafass-1.0.0-portable.exe` | Version portable (zéro installation, lance direct) |

---

## 📋 Pour la soutenance

### Sur ton PC de démo

1. Lance **WAMP** (icône verte)
2. Double-clique `Nafass-1.0.0-portable.exe` (ou installe via l'installeur)
3. L'app s'ouvre comme une vraie application Windows native, **sans navigateur**

### ⚠️ À savoir

- Le `.exe` **doit tourner sur ton PC** (celui où WAMP est installé avec la base `gabes_tatenafas`)
- Sur le PC du jury sans WAMP, l'app affiche une page d'erreur expliquant qu'il faut WAMP — c'est normal
- Pour vraiment marcher partout : voir l'option **B (cross-platform avec backend cloud)** dans nos messages

---

## 🐛 Résolution de problèmes

### `electron-builder` n'est pas reconnu

```cmd
npm install electron-builder --save-dev
```

### Erreur de signature / SmartScreen Windows

C'est normal : ton `.exe` n'est pas signé numériquement (signer coûte ~300€/an).
Pour la soutenance : Windows affichera "Application non vérifiée" → clique **"Plus d'infos" → "Exécuter quand même"**.

### Erreur "cannot find icon"

Vérifie que `assets/icon.ico` existe (il est inclus dans ce ZIP).

### Le build échoue avec "EPERM"

Ferme tout antivirus / Windows Defender pendant le build (il bloque parfois electron-builder). Réactive-le après.

---

## 📝 Configuration du build (déjà faite)

Dans `package.json`, la section `"build"` contient :

- `appId` : `com.nafass.gabes`
- `productName` : `Nafass`
- Cibles Windows : `nsis` (installeur) + `portable` (lance direct)
- Icône : `assets/icon.ico`
- Création de raccourci bureau & menu démarrer
- Choix du dossier d'installation par l'utilisateur

Pour modifier la version : édite la ligne `"version": "1.0.0"` en haut du `package.json`.

---

## 🎯 Commandes rapides

```cmd
npm install          # installer dépendances
npm start            # lancer en mode développement
npm run dist:win     # build installeur + portable Windows
npm run dist:portable  # build seulement le portable
```

Le dossier `dist/` est ignoré par git (déjà dans `.gitignore`).

---

## ✅ Checklist soutenance

- [ ] WAMP démarré sur le PC de démo
- [ ] Base `gabes_tatenafas` importée
- [ ] `.exe` testé au moins une fois avant le jour J
- [ ] Backup du `.exe` sur clé USB
- [ ] Adaptateur HDMI / câble VGA pour le projecteur
