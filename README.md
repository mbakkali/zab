# zab — CLI et dashboard (skills, MCP, scan Cursor/Cody)

Projet **autonome** : installez-le où vous voulez (`git clone …`, `uv sync`). Il référence votre dépôt **skills** via :

1. Variable d’environnement **`ZAB_SKILLS_ROOT`**
2. Fichier **`~/.config/zab/config.yaml`** → clé `skills_root`
3. Défaut **`~/skills`** si rien n’est défini

Les données utilisateur suivent XDG : `~/.config/zab/`, `~/.local/share/zab/`.

## Installation

```bash
cd /chemin/vers/zab
uv sync
cd zab-ui && npm install && npm run build && cd ..
```

Le binaire **`zab`** est exposé par `[project.scripts]` dans `pyproject.toml`.

Au démarrage, l’API charge **`$ZAB_SKILLS_ROOT/.env`** (si présent) sans écraser les variables déjà définies dans le shell.

### Shell global

```bash
./scripts/install-zab-shell.sh
# ou avec un chemin explicite vers le clone zab :
./scripts/install-zab-shell.sh /chemin/vers/zab
```

Le script génère `~/.zab-shell.sh` avec `ZAB_REPO` et `ZAB_SKILLS_ROOT` (défaut `$HOME/skills`). Ajustez ou définissez `skills_root` dans `~/.config/zab/config.yaml`.

## Configuration

### `~/.config/zab/config.yaml` (recommandé)

```yaml
skills_root: /Users/vous/projets/skills
cli_watchlist:
  - gh
  - kubectl
# Racines où zab liste les dossiers « un niveau » = projets (skills à la racine, .cursor/**, .claude/**).
# Clé omise : défaut ~/projects s’il existe. Liste vide [] : désactive cette découverte.
projects_roots:
  - ~/projects
# Variables affichées en plus du catalogue zab (GET /api/security/env)
tracked_env_extra:
  - MY_CUSTOM_TOKEN

# Tâches agrégées (onglet « Tâches (multi-outils) », GET /api/tasks/inbox).
# Jetons : GITLAB_TOKEN, LINEAR_API_KEY, NOTION_TOKEN (processus ou $ZAB_SKILLS_ROOT/.env).
# task_sources:
#   - id: example-gitlab
#     label: Exemple GitLab
#     backend: gitlab
#     host: gitlab.com
#     path_with_namespace: groupe/projet
#     assignee_username: moi
#     routing_doc: ~/projects/carrefour/danmdata/.cursor/rules/gitlab-project-danmdata.mdc
#     mcp_hint: MCP GitLab ou glab
#   - id: example-linear
#     label: Exemple Linear
#     backend: linear
#     team_keys: [ENG]
#     routing_doc: ~/projects/agileimmo/agile-taskforce/.cursor/rules/01-linear-agile.mdc
#   - id: example-notion
#     label: Exemple Notion
#     backend: notion
#     database_id: votre-uuid-de-base
#     notion_title_prop: Name
```

### `~/.config/zab/local-tools.yaml`

Copiez `zab/local-tools.example.yaml` puis adaptez (proxies LiteLLM / OpenRouter, `cli_watchlist` pour le scan `which`).

## Commandes

| Commande | Description |
|----------|-------------|
| `uv run zab doctor` | Vérifie chemins skills, uv, node, npm, **mempalace**, présence du DSN **MEHDI_MEMORY_DATABASE_URL** |
| `uv run zab dashboard` | API **http://127.0.0.1:8742** + SPA si `zab-ui/dist` buildé |
| `uv run zab dashboard --dev` | Affiche la commande Vite (`zab-ui` à la racine du **dépôt zab**) |
| `uv run zab scan` | Scan workspace (~), SKILL.md, CLIs, Agentpipe, Codexbar, Cursor/Cody (best-effort) |
| `uv run zab scan --json` | Sortie JSON |
| `uv run zab add mcp NAME --url …` ou `--command … [--args '…']` | Ajoute un serveur dans `skills/configs/cursor-mcp.json` (`--target desktop` → Claude) |
| `uv run zab add cli BIN` | Ajoute à `cli_watchlist` (`--where local` = local-tools.yaml, `config` = ~/.config/zab) |
| `uv run zab add api KEY --url … [--key-env VAR]` | Ajoute un proxy dans local-tools.yaml (dashboard Connecteurs) |
| `uv run zab add env VAR` | Ajoute `VAR` à `tracked_env_extra` (vue Sécurité) |
| `uv run zab pm-env sync` | Copie les jetons PM depuis les `.env` des projets (`projects_roots`) vers `~/.config/zab/.env` (`--force` pour écraser) |
| `uv run zab run --smoke` | Nécessite un repo skills avec `scripts/smoke_test_all_mcps.sh` |

Variable **`ZAB_UI_DIST`** : surcharge du répertoire du build statique (défaut : `zab-ui/dist` à côté du package).

## Scan et persistance

- **`GET /api/scan?persist=1`** : enregistre le résultat dans **`~/.local/share/zab/scan-last.yaml`** et pose **`last_scan_at_utc`** dans `config.yaml`.
- **`GET /api/scan/last`** : dernier snapshot enregistré.

Le scan **Cursor / Cody** lit au mieux `settings.json` de Cursor et la présence du CLI `cursor` ; les détails varient selon les versions — complétez via YAML ou l’éditeur.

## Mémoire MCP (MemPalace → Postgres)

1. Créez une base PostgreSQL logique **`mehdi_mcp_memory`** (ex. instance locale sur le port 5432).
2. Appliquez les migrations du gateway Flowmetrik : dans le dépôt **skills**, avec `MEHDI_MEMORY_DATABASE_URL` pointant vers cette base, exécutez le script  
   `mcps/flowmetrik-gateway/apply_migrations.sh` (fichiers SQL dans `mcps/flowmetrik-gateway/migrations/`, dont `001_init_mehdi_memory.sql`).
3. Définissez **`MEHDI_MEMORY_DATABASE_URL`** dans l’environnement du processus `zab dashboard` ou dans **`$ZAB_SKILLS_ROOT/.env`** (fichier chargé au démarrage de l’API sans écraser les variables déjà exportées).
4. Pour l’aperçu lecture seule dans le dashboard : `uv sync --extra memory` (installe `psycopg`).
5. **MemPalace** : CLI officiel sur [PyPI `mempalace`](https://pypi.org/project/mempalace/) ; installation typique `uv tool install mempalace`. Produisez un fichier JSONL (voir `skills/scripts/README_MEMORY_EXPORT.md` dans le dépôt skills) puis importez via l’onglet **Mémoire** ou `python scripts/import_memory_jsonl.py`.

API : `GET /api/memory/status`, `GET /api/memory/documents?limit=&offset=`, `GET /api/memory/chunks?document_id=`. Le scan workspace inclut un bloc **`memory_stack`** (CLI MemPalace, DSN configuré, sonde Postgres).

## Dashboard API (extraits)

- **`PUT /api/config/projects-roots`** : corps JSON `{ "roots": ["~/projects", ...] }` — écrit `projects_roots` dans `~/.config/zab/config.yaml` (forme `~/…` sous le home).
- **`GET /api/tasks/inbox`** : agrège les tâches (GitLab / Linear / Notion) selon `task_sources` dans `config.yaml` ; ne renvoie jamais les secrets.
- **`POST /api/tasks/pm-env/sync`** : corps `{"force": false}` — parcourt les `.env` sous `projects_roots` (et `skills/.env`), fusionne `GITLAB_TOKEN` / `LINEAR_API_KEY` / `NOTION_TOKEN` dans `~/.config/zab/.env` (équivalent `zab pm-env sync`).

## Tests

```bash
uv run pytest zab/tests -v
cd zab-ui && npm run test:e2e
```

## Licence / suite

Les jobs (smoke MCP, sync Litellm, etc.) supposent un clone **skills** complet pointé par `ZAB_SKILLS_ROOT`.
