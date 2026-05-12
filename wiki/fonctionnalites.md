# zab — Fonctionnalités du projet

**zab** est une CLI Python (Typer) et un **dashboard web** local : inventaire et pilotage autour des **skills**, des **serveurs MCP**, des **CLIs**, du scan **Cursor / Cody**, et des connecteurs déclarés dans votre dépôt **skills** et votre configuration locale.

Le projet est **autonome** : clonez-le où vous voulez, installez les dépendances avec `uv` et construisez l’UI ; il se branche sur votre dépôt **skills** via des chemins configurables (voir ci-dessous).

---

## 1. Rôle du dépôt skills

zab ne contient pas vos skills métier : il **référence** un arbre de fichiers (souvent un clone Git « skills ») pour :

- lire les `SKILL.md`, les orgs, les plugins Claude ;
- lire / proposer des scripts (smoke MCP, sync LiteLLM, etc.) ;
- charger `$ZAB_SKILLS_ROOT/.env` au démarrage de l’API **sans écraser** les variables déjà définies dans le shell.

**Résolution du répertoire skills** (dans l’ordre) :

1. Variable d’environnement **`ZAB_SKILLS_ROOT`**
2. Fichier **`~/.config/zab/config.yaml`** → clé `skills_root` (ou chemins avancés type `skill_md_paths` / `skills_roots` selon votre config)
3. Défaut **`~/skills`** si rien n’est défini

Les données propres à zab suivent les conventions **XDG** : `~/.config/zab/`, `~/.local/share/zab/`.

---

## 2. Installation

### Dépendances Python et build UI

```bash
cd /chemin/vers/zab
uv sync
cd zab-ui && npm install && npm run build && cd ..
```

Le binaire **`zab`** est exposé par `[project.scripts]` dans `pyproject.toml` (usage typique : `uv run zab …`).

### Shell global (variables pratiques)

Le script `scripts/install-zab-shell.sh` génère `~/.zab-shell.sh` avec notamment `ZAB_REPO` et `ZAB_SKILLS_ROOT` (défaut `$HOME/skills`). Vous pouvez passer le chemin du clone en argument.

### Surcharge du build statique de l’UI

**`ZAB_UI_DIST`** permet de pointer vers un répertoire de build autre que `zab-ui/dist` à côté du package.

---

## 3. Configuration

### `~/.config/zab/config.yaml` (recommandé)

Exemple documenté dans le README racine :

- **`skills_root`** — racine du dépôt skills
- **`cli_watchlist`** — liste de binaires suivis par le scan (`which`)
- **`projects_roots`** — racines où zab liste les dossiers « un niveau » (projets avec skills à la racine, `.cursor/**`, `.claude/**`). Omis : défaut `~/projects` s’il existe ; `[]` désactive cette découverte
- **`tracked_env_extra`** — variables affichées en plus du catalogue zab dans la vue sécurité (API `GET /api/security/env`)

### `~/.config/zab/local-tools.yaml`

Copiez `zab/local-tools.example.yaml` puis adaptez (proxies LiteLLM / OpenRouter, `cli_watchlist` pour le scan, etc.). Le dashboard peut lire / éditer ce fichier via les routes de snapshot de config.

### Commande `zab config`

Affiche la configuration résolue (chemins, règles de résolution, contenu YAML utile). Options : `--open` / `--open-tools`, `--paths` pour des sorties minimales orientées scripts.

---

## 4. Commandes CLI

| Commande | Description |
|----------|-------------|
| `uv run zab doctor` | Vérifie chemins et binaires attendus |
| `uv run zab dashboard` | Lance l’API **http://127.0.0.1:8742** et sert la SPA si `zab-ui/dist` est buildé |
| `uv run zab dashboard --dev` | Affiche la commande Vite pour développer `zab-ui` depuis la racine du dépôt zab |
| `uv run zab scan` | Scan du workspace (home), `SKILL.md`, CLIs, Agentpipe, Codexbar, Cursor/Cody (au mieux selon les versions) |
| `uv run zab scan --json` | Même scan, sortie JSON |
| `uv run zab add mcp NAME --url …` ou `--command … [--args '…']` | Ajoute un serveur MCP dans `skills/configs/cursor-mcp.json` (`--target desktop` → configuration type Claude Desktop) |
| `uv run zab add cli BIN` | Ajoute un binaire à `cli_watchlist` (`--where local` = `local-tools.yaml`, `config` = `~/.config/zab`) |
| `uv run zab add api KEY --url … [--key-env VAR]` | Ajoute un proxy API dans `local-tools.yaml` (visible côté dashboard Connecteurs) |
| `uv run zab add env VAR` | Ajoute une variable à `tracked_env_extra` (vue Sécurité) |
| `uv run zab run --smoke` | Exécute le smoke tests MCP si votre dépôt skills expose `scripts/smoke_test_all_mcps.sh` |

Le sous-groupe **`zab add`** centralise les ajouts récurrents (MCP, CLI, API, variables suivies).

---

## 5. Dashboard et API HTTP

Quand vous lancez `zab dashboard`, une application **FastAPI** écoute sur le port **8742** (par défaut). L’interface est une **SPA** React servie depuis le build statique `zab-ui/dist` lorsqu’il est présent.

### Familles de fonctionnalités côté API

- **Santé** — `GET /api/health`
- **Découverte** — `GET /api/overview`, `/api/orgs`, `/api/plugins`, `/api/mcp`
- **Connecteurs** — `GET /api/connectors` (liste paginée, filtres `q`, `kind`, `tag`), `GET /api/connectors/{slug}`
- **Fichiers de configuration** — listes et contenus via `GET /api/config/files`, `GET /api/config/file?key=…`, écriture contrôlée `PUT /api/config/file` (clés éditables comme `local_tools_actual`, `user_zab_config`)
- **Racines projets** — `PUT /api/config/projects-roots` pour persister `projects_roots` dans `config.yaml`
- **Jobs** — `POST /api/jobs/start` avec presets (`smoke_mcps`, `gateway_pytest`, `sync_mcps_litellm`, `build_plugins`, `google_oauth_mehdi_context`, `memory_import`, …), statut `GET /api/jobs/{id}`, annulation, flux SSE `GET /api/jobs/{id}/stream`
- **Sécurité / secrets** — `GET /api/security/env` (variables suivies, valeurs masquées), lecture / écriture du fichier `skills/.env` via `GET|PUT /api/security/env-file` (sauvegarde horodatée à l’écriture)
- **Skills** — lecture / écriture de fichiers `SKILL.md` autorisés via `GET|PUT /api/skills/file` (chemins relatifs sous le dépôt skills ou absolus explicitement autorisés / sous `projects_roots`)
- **Scan workspace** — `GET /api/scan` (option `persist=1` pour écrire `~/.local/share/zab/scan-last.yaml` et mettre à jour `last_scan_at_utc` + découverte de modèles dans la config), `GET /api/scan/last`
- **Modèles / discovery** — `GET /api/config/models-discovery`
- **Outils locaux** — `GET /api/tools/local`, `GET /api/tools/scan`, sondes `GET /api/tools/probe?kind=litellm|openrouter`
- **Aide CLI dans l’UI** — `GET /api/cli/help` (sortie de `zab --help`)
- **Indices pour exports / scripts** — `GET /api/exports/hints` (chemins type `sync-mcps-to-litellm.sh`, `build-plugins.sh`, résumé de config plugins)

Ces routes reflètent le fichier `zab/api/routes.py` ; le détail des corps JSON peut évoluer avec les versions.

---

## 6. Scan et persistance

- **`GET /api/scan?persist=1`** enregistre le résultat dans **`~/.local/share/zab/scan-last.yaml`** et met à jour la configuration utilisateur (`last_scan_at_utc`, fusion avec la découverte de modèles issue du scan).
- **`GET /api/scan/last`** renvoie le dernier snapshot enregistré s’il existe.

Le scan **Cursor / Cody** s’appuie au mieux sur `settings.json` de Cursor et sur la présence du CLI `cursor` ; le comportement exact peut varier selon les versions — le README invite à compléter via YAML ou l’éditeur du dashboard.

---

## 7. Tests

```bash
uv run pytest zab/tests -v
cd zab-ui && npm run test:e2e
```

---

## 8. Vision produit (référence interne)

Le fichier `zab/CONNECTORS-PLAN.md` décrit une vision plus large : **centre de commande IA local-first**, inventaire unifié (skills, connecteurs MCP/API/CLI, outils de code, modèles, secrets), modèle YAML / filesystem. Certaines parties sont **roadmap** ou en cours d’alignement avec l’UI ; la doc ci-dessus décrit surtout ce qui est **déjà exposé** par la CLI et l’API actuelles.

---

## 9. Licence / dépendances du dépôt skills

Les jobs (smoke MCP, sync LiteLLM, etc.) supposent un clone **skills** cohérent pointé par votre configuration (`ZAB_SKILLS_ROOT` ou équivalent). Consultez le README racine pour les détails d’installation et les chemins par défaut.
