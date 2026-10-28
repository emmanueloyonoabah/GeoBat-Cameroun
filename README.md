# GeoBat Cameroun

Application Streamlit de **saisie, contrôle qualité et analyse des essais géotechniques et de matériaux** (béton, latérite, granulats) pour des chantiers de génie civil au Cameroun.

| Rôle | Ce qu'il peut faire |
|---|---|
| **Technicien Labo** | Saisir les essais (compression béton 28 j, Proctor, CBR, Los Angeles) avec comparaison automatique à la valeur cible, consulter ses propres saisies |
| **Ingénieur / Chef de Projet** | Tableau de bord (taux de conformité, graphiques Plotly), bandeau d'alerte, décisions sur les essais « en cours d'analyse », historique par lot, export CSV |

Statuts : 🟢 **Conforme** · 🟠 **En cours d'analyse** (résultat dans la zone de tolérance, décision de l'ingénieur requise) · 🔴 **Non conforme**.

## Contenu du dépôt

```
app.py                  # toute l'application
requirements.txt        # dépendances
assets/logo.svg         # logo de la barre latérale
.streamlit/config.toml  # thème (palette ardoise / blanc cassé)
data/essais.csv         # base d'essais (créée automatiquement au 1er enregistrement)
```

## 1. Lancer en local (Windows / PowerShell)

```powershell
cd "chemin\vers\le\dossier"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

> Si PowerShell refuse d'activer l'environnement : `Set-ExecutionPolicy -Scope Process Bypass`, puis relancer l'activation.

L'application s'ouvre sur <http://localhost:8501>.

**Comptes de démonstration** (affichés sur la page de connexion tant qu'aucun compte réel n'est configuré) :

| Identifiant | Mot de passe | Rôle |
|---|---|---|
| `tech` | `Labo@2025` | Technicien Labo |
| `ing` | `Chantier@2025` | Ingénieur / Chef de Projet |

Connectez-vous en **ing** : sur la base vide, le bouton « Charger des données de démonstration » crée 43 essais fictifs pour explorer le tableau de bord. Ils sont signalés *Démo (simulé)*. Pour repartir de zéro, supprimez `data/essais.csv`.

## 2. Pousser sur GitHub

1. Créez un dépôt **vide** sur <https://github.com/new> (par ex. `geobat-cameroun`), sans README ni `.gitignore`.
2. Dans le dossier du projet :

```powershell
git init
git add .
git commit -m "GeoBat Cameroun - version initiale"
git branch -M main
git remote add origin https://github.com/<votre-compte>/geobat-cameroun.git
git push -u origin main
```

Le `.gitignore` fourni exclut `.streamlit/secrets.toml` (vos comptes) et `data/essais.csv` : **ne les publiez jamais**.

## 3. Déployer sur Streamlit Community Cloud

1. Rendez-vous sur <https://share.streamlit.io> et connectez-vous avec GitHub.
2. **Create app** → *Deploy a public app from GitHub*.
3. Choisissez le dépôt, la branche `main` et le fichier principal `app.py`.
4. **Advanced settings** :
   - *Python version* : 3.12 ou 3.13 ;
   - *Secrets* : collez vos comptes (voir section 4). **Sans cela, l'application tourne en mode démo avec les comptes publics ci-dessus : n'importe qui pourrait se connecter.**
5. **Deploy**. Après quelques minutes, l'application est disponible sur `https://<nom>.streamlit.app`.

Toute modification poussée sur `main` redéploie automatiquement l'application.

## 4. Créer de vrais comptes

Générez le sel et l'empreinte du mot de passe (le mot de passe est saisi masqué) :

```powershell
python -c "import hashlib,getpass,secrets;s=secrets.token_hex(8);print('salt =',s);print('hash =',hashlib.pbkdf2_hmac('sha256',getpass.getpass().encode(),s.encode(),120000).hex())"
```

Puis déclarez les comptes dans `.streamlit/secrets.toml` en local, ou dans *Settings → Secrets* sur Streamlit Cloud :

```toml
[users.jmballa]
nom  = "Jean Mballa"
role = "technicien"          # ou "ingenieur"
salt = "<sel généré>"
hash = "<empreinte générée>"

[users.cprojet]
nom  = "Chef de Projet"
role = "ingenieur"
salt = "<sel généré>"
hash = "<empreinte générée>"
```

Dès que la section `[users]` existe, les comptes de démonstration sont désactivés.

## 5. Règles métier (à valider avec le CCTP)

Les seuils sont **indicatifs** : ils se modifient dans le dictionnaire `CATALOGUE` en haut de `app.py`. Alignez-les sur le CCTP de votre marché avant tout usage réel.

| Essai | Critère | Zone « en cours d'analyse » |
|---|---|---|
| Compression béton 28 j (moyenne de 3 éprouvettes) | ≥ fck,cube de la classe (C16/20 → 20 MPa … C35/45 → 45 MPa) | jusqu'à 4 MPa sous la cible |
| Proctor modifié (γd max) | ≥ 1,70 / 1,80 / 1,90 / 2,00 t/m³ (remblai / forme / fondation / base) | jusqu'à 0,05 t/m³ sous la cible |
| CBR à 95 % OPM | ≥ 15 / 25 / 30 / 60 % | jusqu'à 3 points sous la cible |
| Los Angeles | ≤ 30 % (béton) / 35 % (chaussée) | jusqu'à 3 points au-dessus |

Le critère béton est une version simplifiée de la NF EN 206 : il ne remplace pas le contrôle statistique de conformité d'une production.

## 6. Limites à connaître

- **Stockage éphémère sur Streamlit Cloud.** Le CSV est stocké sur le disque de l'application, qui est **réinitialisé à chaque redémarrage ou redéploiement**. Pour un usage réel, téléchargez régulièrement le rapport CSV, ou remplacez le stockage par une base externe (Google Sheets, Supabase, PostgreSQL) en réécrivant uniquement les fonctions `charger_essais`, `ajouter_essais` et `appliquer_decision`.
- **Authentification simple** (mots de passe hachés PBKDF2, sans verrouillage après échecs ni authentification à deux facteurs) : adaptée à un projet pédagogique ou à un prototype, pas à des données sensibles.
- **Écritures concurrentes** : un verrou protège les écritures au sein d'un même serveur, ce qui suffit pour quelques utilisateurs simultanés.
