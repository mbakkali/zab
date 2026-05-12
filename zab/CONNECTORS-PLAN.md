# Plan — `zab` : centre de commande IA local

## 0. Vision

`zab` n'est pas (plus) qu'un dashboard d'inventaire — c'est un **centre de commande IA local-first**, pensé pour devenir un **outil natif** que tout utilisateur d'IA (terminaux, MCP, modèles, skills) peut installer pour reprendre le contrôle de sa stack :

- **Local-first** : tout vit dans `~/.zab/` + le repo de skills de l'utilisateur. Aucun service distant requis.
- **Source de vérité = filesystem + YAML** ; le fichier d'index `~/.zab/state.yaml` est un index dénormalisé reconstruisible à tout moment via `zab sync`.
- **Inventaire unifié** : Skills, Connecteurs (MCP / API / CLI), Outils de code (agents CLI : Claude Code, Kimi, Gemini, Cursor…), Models (endpoints API : LiteLLM, OpenRouter, Anthropic…), Secrets — tous indexés, tagués, observables au même endroit.
- **Open source à terme** : architecture vendor-neutral (pas de chemins en dur vers `/Users/mbakkali`, pas d'hypothèse sur les orgs `flowmetrik`/`carrefour`/…), config par YAML, indexers pluggables. Le repo `skills` privé de Mehdi n'est qu'**une instance** parmi d'autres.

Public cible OSS : devs qui empilent Claude Code + Cursor + agents CLI (kimi, qwen, gemini), gèrent une dizaine de MCP, jonglent entre LiteLLM/OpenRouter/direct, et veulent **un seul écran** pour voir « qu'est-ce que j'ai, où c'est branché, est-ce que ça répond ».

Différenciateurs vs alternatives :

| Outil existant | Ce qu'il fait | Ce qui manque vs `zab` |
|---|---|---|
| Claude Desktop / Cursor settings UI | Active/désactive MCP par client | Pas de vue cross-client, pas de skills, pas de models |
| `mcp-inspector` (Anthropic) | Debug 1 MCP à la fois | Pas un inventaire |
| LiteLLM proxy UI | Liste des modèles routés | Ne couvre ni MCP ni CLI ni skills |
| Cherry Studio, LobeChat | Front de chat multi-modèles | Pas un command center sur la stack locale |

→ Niche libre : **observabilité + pilotage de la stack IA personnelle**, pas une UI de chat.

---

## 1. Constat

Aujourd'hui dans `zab` :

- `services/discovery.list_mcp_configs()` lit uniquement `configs/cursor-mcp.json` et `configs/claude-desktop-mcp.json`.
- L'UI `connectors-view.tsx` n'affiche **que des MCP** (champs `name`, `kind` ∈ `stdio|http|sse`, `target`, `enabled`, `note`).
- Les API HTTP (Linear, Notion, Gmail…) et les CLI locaux (`gh`, `gcloud`, `aws`, `uv`, `node`…) ne sont pas modélisés comme connecteurs.
- Les **agents CLI de code** (`claude`, `kimi`, `gemini`, `cursor` via Agentpipe) sont indexés comme "Models" (à corriger : section dédiée "Outils de code").
- Un même service (ex. **Linear**) peut exister sous plusieurs formes : MCP stdio (`npx mcp-remote https://mcp.linear.app/mcp`), API REST (token), CLI éventuel.
- `orgs/` agit déjà comme un système de tags (chaque org regroupe ses skills), et `claude-plugins/<plugin>/skills/` contient les skills bundlés.

→ Il faut une représentation unifiée d'un **connecteur** indépendante de sa forme, avec ses occurrences (formes) et un détail adapté par forme.

---

## 2. Modèle de données YAML

### 2.1 Principe : filesystem = source de vérité

**Pas de base de données.** L'index est un fichier YAML `~/.zab/state.yaml` (ou `<repo>/.zab/state.yaml`) généré par `zab sync`. Il est :
- **100 % régénérable** depuis le filesystem (`configs/`, `orgs/`, `~/.cursor/mcp.json`, etc.).
- **Gitignoré par défaut** (l'utilisateur peut choisir de le versionner s'il veut persister ses tags manuels).
- **Lecture seule pour l'API** : l'API lit ce YAML, elle ne l'écrit jamais directement. Seule la CLI `zab sync` le réécrit.

**Overrides utilisateur** : les tags manuels, notes et descriptions custom sont stockés dans `~/.zab/overrides.yaml` (séparé de `state.yaml`). Le merge est fait en mémoire au chargement :
```yaml
# ~/.zab/overrides.yaml
connectors:
  linear:
    note: "Utilisé uniquement pour les tickets flowmetrik"
    tags: ["critical"]
skills:
  cockpit:
    tags: ["archived"]
```
Ainsi, `state.yaml` reste jetable (on peut le `rm` et refaire `zab sync`), mais `overrides.yaml` persiste les préférences utilisateur.

### 2.2 Concepts

```
Connector             # service logique (ex. "Linear", "Qonto", "GitHub")
 ├─ Form (1..n)       # forme concrète : MCP | API | CLI
 │   └─ source        # fichier / chemin / URL d'enregistrement
 └─ Tag (n..n)        # orgs (flowmetrik, perso…) + libres

Skill                 # SKILL.md sur disque
 ├─ Tag (n..n)        # orgs
 └─ uses Connector*   # référence facultative
 └─ uses CodeTool*    # référence facultative (agents CLI)
 └─ uses Model*       # référence facultative (endpoints API)

Plugin                # claude-plugins/<bundle>
 └─ contient Skill*
```

### 2.3 Schéma YAML (`~/.zab/state.yaml`)

```yaml
version: "2.0"                # schema version du fichier
last_sync_at: "2026-05-02T10:00:00Z"
generated_by: "zab sync v0.5.0"

connectors:
  linear:
    id: "linear"
    display_name: "Linear"
    description: "Issue tracking"
    icon_key: "linear"
    forms:
      - kind: "mcp"
        source_kind: "cursor-mcp"
        source_ref: "configs/cursor-mcp.json#linear"
        enabled: true
        meta:
          transport: "stdio"
          command: "npx"
          args: ["-y", "mcp-remote", "https://mcp.linear.app/mcp"]
          env_vars: ["LINEAR_API_KEY"]
        last_seen_at: "2026-05-02T10:00:00Z"
      - kind: "api"
        source_kind: "env-file"
        source_ref: "/Users/mbakkali/projects/skills/.env#LINEAR_API_KEY"
        enabled: true
        meta:
          base_url: "https://api.linear.app"
          auth: "bearer"
          env_var: "LINEAR_API_KEY"
          docs_url: "https://developers.linear.app/docs/graphql/working-with-the-graphql-api"
    tags: ["flowmetrik"]

  qonto:
    id: "qonto"
    display_name: "Qonto"
    forms:
      - kind: "api"
        source_kind: "env-file"
        source_ref: "/Users/mbakkali/projects/skills/.env#QONTO_API_KEY"
        enabled: true
        meta:
          base_url: "https://thirdparty.qonto.com/v2"
          auth: "bearer"
          env_var: "QONTO_API_KEY"
    tags: ["flowmetrik", "finance"]

skills:
  cockpit:
    rel_path: "orgs/flowmetrik/skills/cockpit/SKILL.md"
    skill_id: "cockpit"
    org_slug: "flowmetrik"
    plugin_slug: null
    description: "Dashboard de supervision"
    updated_at: "2026-04-28T14:30:00Z"
    tags: ["flowmetrik"]
    uses_connectors: ["linear", "qonto"]
    uses_code_tools: ["claude"]
    uses_models: ["litellm-hosted"]

code_tools:
  claude:
    id: "claude"
    display_name: "Claude Code"
    kind: "agent"
    provider: "anthropic"
    source_kind: "agentpipe"
    source_ref: "/Users/mbakkali/.agentpipe.yaml#claude"
    enabled: true
    meta:
      binary: "/Users/mbakkali/.nvm/versions/node/v22.14.0/bin/claude"
      version: "2.1.126"
      install_hint: "npm install -g @anthropic-ai/claude-code"
      used_via: ["agentpipe", "direct"]
    tags: ["perso"]

  kimi:
    id: "kimi"
    display_name: "Kimi"
    kind: "agent"
    provider: "moonshot"
    source_kind: "agentpipe"
    source_ref: "/Users/mbakkali/.agentpipe.yaml#kimi"
    enabled: true
    meta:
      binary: "/Users/mbakkali/.local/bin/kimi"
      version: "1.40.0"
      install_hint: "pip install kimi-cli"
      used_via: ["agentpipe", "direct"]
    tags: ["perso"]

  gemini:
    id: "gemini"
    display_name: "Gemini CLI"
    kind: "agent"
    provider: "google"
    source_kind: "agentpipe"
    source_ref: "/Users/mbakkali/.agentpipe.yaml#gemini"
    enabled: true
    meta:
      binary: "/Users/mbakkali/.nvm/versions/node/v22.14.0/bin/gemini"
      version: "0.40.1"
      install_hint: "npm install -g @google/gemini-cli"
      used_via: ["agentpipe"]
    tags: ["perso"]

  cursor:
    id: "cursor"
    display_name: "Cursor"
    kind: "ide"
    provider: "cursor"
    source_kind: "agentpipe"
    source_ref: "/Users/mbakkali/.agentpipe.yaml#cursor"
    enabled: true
    meta:
      binary: "/usr/local/bin/cursor"
      version: "3.2.11"
      install_hint: "brew install --cask cursor"
      used_via: ["agentpipe", "direct"]
    tags: ["perso"]

  factory:
    id: "factory"
    display_name: "Factory"
    kind: "agent"
    provider: "factory"
    source_kind: "agentpipe"
    source_ref: "/Users/mbakkali/.agentpipe.yaml#factory"
    enabled: true
    meta:
      binary: null
      version: null
      install_hint: "Voir https://factory.ai"
      used_via: ["agentpipe"]
    tags: ["perso"]

  qwen:
    id: "qwen"
    display_name: "Qwen"
    kind: "agent"
    provider: "alibaba"
    source_kind: "agentpipe"
    source_ref: "/Users/mbakkali/.agentpipe.yaml#qwen"
    enabled: true
    meta:
      binary: null
      version: null
      install_hint: "pip install qwen-agent"
      used_via: ["agentpipe"]
    tags: ["perso"]

  continue:
    id: "continue"
    display_name: "Continue"
    kind: "ide-extension"
    provider: "continue"
    source_kind: "agentpipe"
    source_ref: "/Users/mbakkali/.agentpipe.yaml#continue"
    enabled: true
    meta:
      binary: null
      version: null
      install_hint: "VS Code extension: Continue.continue"
      used_via: ["agentpipe"]
    tags: ["perso"]

models:
  litellm-hosted:
    id: "litellm-hosted"
    display_name: "LiteLLM (hosted)"
    kind: "api"
    provider: "litellm"
    source_kind: "local-tools-yaml"
    source_ref: "/Users/mbakkali/projects/skills/zab/local-tools.yaml#proxies.litellm_hosted"
    enabled: true
    meta:
      base_url: "https://litellm.fmetrik.com"
      api_key_env: "OPENAI_API_KEY"
      auth: "bearer"
      models_cache: ["claude-opus-4-6", "gemini-3-1-pro"]
    tags: ["flowmetrik"]

tags:
  flowmetrik:
    slug: "flowmetrik"
    kind: "org"
    description: "Organisation Flowmetrik"
  perso:
    slug: "perso"
    kind: "org"
  finance:
    slug: "finance"
    kind: "free"
    description: "Tag libre"

sync_log:
  - scope: "all"
    started_at: "2026-05-02T09:59:00Z"
    ended_at: "2026-05-02T10:00:00Z"
    status: "success"           # success | partial | failed
    indexers:
      skills:
        status: "success"
        records: 42
        duration_ms: 120
      connectors_mcp:
        status: "success"
        records: 8
        duration_ms: 340
      connectors_api:
        status: "success"
        records: 5
        duration_ms: 50
    error_message: null
```

### 2.4 Validation

Le fichier YAML est validé à l'écriture et à la lecture par un schéma Pydantic côté Python :
- `zab/models/state.py` — classes Pydantic `ZabState`, `Connector`, `ConnectorForm`, `Skill`, `CodeTool`, `ModelEndpoint`, `Tag`, `SyncLogEntry`.
- Le schéma est versionné (`version` dans le YAML). Si `zab` lit un `state.yaml` avec une version incompatible, il refuse de démarrer et demande `zab sync --force`.
- Pas de migration de schéma complexe : `state.yaml` est jetable. En cas de changement de schéma majeur, on bump la version et on force un reindex au prochain démarrage.

### 2.5 Avantages du YAML vs SQLite

| Critère | YAML | SQLite |
|---|---|---|
| Lisible / debug | ✅ `cat ~/.zab/state.yaml` | ❌ `sqlite3` requis |
| Reconstruction | ✅ `rm && zab sync` | ✅ `rm && zab sync` |
| Pas de serveur | ✅ fichier texte | ✅ fichier binaire |
| Concurrence | ⚠️ file lock simple suffit | ⚠️ WAL requis |
| Requêtes complexes | ❌ filtre en Python | ✅ SQL |
| Multi-process | ❗ lock fichier | ✅ WAL |
| Versionnable (git) | ✅ diff lisible | ❌ binaire |
| Tooling externe | ✅ jq/yq | ❌ |

**Verdict** : pour un index dénormalisé < 10 Mo, la simplicité du YAML l'emporte. Les filtres se font en Python (list comprehensions sur un dict en mémoire). Si l'index dépasse 50 000 entrées, on reconsidèrera SQLite.

---

## 3. Stockage : `~/.zab/` (fichiers)

```
~/.zab/
  config.yaml          # configuration utilisateur (chemins, whitelist, proxies)
  state.yaml           # index généré (gitignored par défaut)
  overrides.yaml       # tags manuels, notes custom (optionnel, gitignorable)
  sync.lock            # verrou pendant le sync (empêche les syncs simultanés)
  sync.log             # historique des N derniers syncs (rotatif, max 50 entrées)
```

- **Config** : versionnée ou non au choix de l'utilisateur. `zab init` la génère.
- **State** : jetable. Ne pas versionner par défaut (évite les conflits de merge).
- **Overrides** : à versionner si l'utilisateur veut partager ses tags entre machines.

### 3.1 Concurrence et verrouillage

Un sync global est une opération atomique :
1. Acquérir un lock fichier (`~/.zab/sync.lock` via `filelock`).
2. Lire le `state.yaml` existant en mémoire.
3. Exécuter les indexers (en mémoire, pas d'écriture intermédiaire).
4. Écrire le nouveau `state.yaml` via un write temporaire + rename atomique (`state.yaml.tmp` → `state.yaml`).
5. Libérer le lock.

Si un sync est déjà en cours, le nouveau sync retourne immédiatement :
```bash
$ zab sync
Error: sync already in progress (pid 1234, started 2 min ago)
Use --force to kill the previous sync.
```

L'API FastAPI lit le `state.yaml` au démarrage et le garde en mémoire. Elle le relit sur `SIGHUP` ou toutes les 5 secondes (check du mtime du fichier). Aucune concurrence écrivain/lecteur pendant le sync grâce au rename atomique.

---

## 4. Sources d'enregistrement à indexer

Le job `zab sync` (idempotent) parcourt :

| Source | Donne |
|---|---|
| `configs/cursor-mcp.json` | formes MCP (cursor) |
| `configs/claude-desktop-mcp.json` | formes MCP (desktop) |
| `~/.cursor/mcp.json` (lecture seule, optionnel) | formes MCP installées localement |
| `~/Library/Application Support/Claude/claude_desktop_config.json` | idem |
| `mcps/<server>/` | MCP custom du repo (lit `pyproject.toml`/README) |
| `skills/.env` + `secrets_catalog.ALL_TRACKED` | formes API (var env présente → connector "api") |
| `zab/local-tools.yaml` (proxies LiteLLM, OpenRouter…) | formes API |
| `common/mcp-registry/SKILL.md` | description & cas d'usage des MCP (markdown parsé en sections) |
| `which <bin>` pour une whitelist `cli-tools.yaml` (gh, gcloud, aws, uv, node, npm, claude…) | formes CLI |
| `orgs/<org>/skills/*/SKILL.md` + `claude-plugins/<plugin>/skills/*/SKILL.md` | skills + tags org/plugin |

Détection « même connecteur sous plusieurs formes » : par **slug normalisé** (`linear`, `qonto`, `notion`…) déjà calculé dans `connector-meta.ts` via la fonction `connectorMeta()`. À factoriser côté Python (module `zab/normalize.py` partagé avec le frontend via un JSON généré).

### 4.1 Formats des fichiers de config

#### `zab/local-tools.yaml`
```yaml
proxies:
  litellm_hosted:
    base_url: "https://litellm.fmetrik.com"
    api_key_env: "OPENAI_API_KEY"
  litellm_local:
    base_url: "http://localhost:4000"
    api_key_env: "LITELLM_LOCAL_KEY"
  openrouter:
    base_url: "https://openrouter.ai/api/v1"
    api_key_env: "OPENROUTER_API_KEY"
```

#### `zab/cli-tools.yaml`
```yaml
whitelist:
  - name: "gh"
    doc_url: "https://cli.github.com/manual/"
    install_hint: "brew install gh"
  - name: "gcloud"
    doc_url: "https://cloud.google.com/sdk/docs"
    install_hint: "brew install --cask google-cloud-sdk"
  - name: "aws"
    doc_url: "https://aws.amazon.com/cli/"
    install_hint: "brew install awscli"
  - name: "uv"
    doc_url: "https://docs.astral.sh/uv/"
    install_hint: "brew install uv"
  - name: "node"
    doc_url: "https://nodejs.org/"
    install_hint: "brew install node"
  - name: "npm"
    install_hint: "bundled with node"
  - name: "claude"
    doc_url: "https://docs.anthropic.com/claude-code"
    install_hint: "brew install claude"
  - name: "kimi"
    install_hint: "pip install kimi-cli"
```

#### Frontmatter SKILL.md (étendu)
Chaque `SKILL.md` peut contenir en frontmatter YAML :
```yaml
---
name: cockpit
description: Dashboard de supervision
version: "1.2.0"
tags: ["observability", "custom-tag"]
uses_connectors: ["linear", "qonto"]
uses_code_tools: ["claude"]
uses_models: ["litellm-hosted"]
---
```
- `name`, `description` : obligatoires.
- `version` : optionnel.
- `tags` : tags libres (en plus du tag org inféré du chemin).
- `uses_connectors` : liste de slugs de connecteurs utilisés.
- `uses_code_tools` : liste de slugs d'agents CLI utilisés (claude, kimi, gemini, cursor…).
- `uses_models` : liste de slugs d'endpoints API utilisés (litellm, openrouter…).

---

## 5. API HTTP

```
GET  /api/connectors                     # liste + filtres (?kind, ?tag, ?q, ?page, ?limit)
GET  /api/connectors/{slug}              # détail (toutes les formes)
GET  /api/connectors/{slug}/forms/{id}   # détail d'une forme + payload typé
POST /api/connectors/{slug}/forms/{id}/probe
       # MCP  → tente list_tools (spawn stdio/HTTP, timeout 5s max)
       # API  → GET /v1/models ou ping documenté
       # CLI  → which + --version
GET  /api/tags                           # toutes les tags (orgs + libres)
POST /api/reindex                        # déclenche un sync (scope=all), retourne job_id
GET  /api/reindex/{job_id}               # statut du job (SSE ou polling)
GET  /api/code-tools                    # liste agents CLI (?kind, ?provider, ?q, ?page, ?limit)
GET  /api/code-tools/{slug}              # détail
POST /api/code-tools/{slug}/probe        # which + --version
GET  /api/models                         # liste endpoints API (?kind, ?provider, ?q, ?page, ?limit)
GET  /api/models/{slug}                  # détail
POST /api/models/{slug}/probe            # API : GET /v1/models
GET  /api/models/sources                 # chemins absolus des configs source
GET  /api/skills                         # liste (?org, ?plugin, ?tag, ?q, ?page, ?limit)
GET  /api/skills/{id}                    # détail + connecteurs utilisés
GET  /api/sync/status                    # dernier sync (date, scope, statut)
POST /api/sync                           # déclenche sync (scope: all | skills | connectors | code-tools | models | secrets)
```

Routes existantes (`/api/mcp`, `/api/orgs`, `/api/plugins`) **gardées** mais réimplémentées au-dessus du YAML (rétro-compat UI).

### 5.1 Pagination

Toutes les routes liste supportent :
- `?page` (défaut 1) + `?limit` (défaut 50, max 200)
- Réponse enveloppée :
```json
{
  "data": [...],
  "pagination": {
    "page": 1,
    "limit": 50,
    "total": 127,
    "total_pages": 3
  }
}
```

### 5.2 Rate limiting sur les probes

Les probes sont limitées pour éviter le spam :
- Max 5 probes par minute par IP (localhost donc mono-user, mais protège quand même contre un script bouclé).
- Timeout strict : 5 secondes max, kill du processus après.

---

## 6. UI — changements

### 6.1 Connecteurs (`connectors-view.tsx`)

1. La carte affiche déjà nom + kind + cible. **Ajouter sous le badge kind** : badge `MCP | API | CLI` (form-level), badge `n formes` si > 1.
2. **Bouton « Voir »** ouvre un drawer (`<Sheet>` shadcn) :
   - **MCP** → onglets *Cible* (commande/URL), *Outils* (cache `meta.tools_cache` + bouton « Probe »), *Env requis*, *Source* (chemin du fichier de config + bouton ouvrir VSCode `vscode://file/...`).
   - **API** → *Auth* (env var, présence/masqué), *Base URL*, *Doc* (lien externe), *Probe* (status code + body preview), *Source*.
   - **CLI** → *Binaire* (`which`), *Version*, *Doc* (lien officiel), *Install hint* (brew/pip/npm), bouton « Lancer terminal » (copie commande).
3. **Filtre par tag/org** : chips horizontaux au-dessus de la grille (existe pour les sources, ajouter une seconde rangée tags).
4. **Multi-formes** : la carte connecteur agrège les formes ; cliquer ouvre le drawer qui les liste toutes.

### 6.2 Skills (`skills-view.tsx`)

5. Ajouter chip de tags (org + plugin) sur chaque skill, cliquables → filtre.
6. Section « Connecteurs utilisés » dans le détail d'un skill (lecture du frontmatter).

### 6.3 Outils de code (nouvel onglet)

Nouvelle entrée dans `sidebar-nav.tsx` : **« Code Tools »** (icône `CodeSquareIcon` ou `TerminalBrowserIcon`).

Composant `code-tools-view.tsx` :
- Sections collapsées par source : *Agentpipe*, *CodexBar*, *Installés*, *Manquants*.
- Chaque carte affiche : nom + badge `agent|ide|ide-extension` + provider + **chemin absolu du binaire** (`which`, copiable) + version + bouton « Probe » (which + --version) + bouton « Ouvrir source » (vscode://file/…).
- Pour les outils sans binaire détecté (factory, qwen, continue) : badge "⚠️ not installed" + install hint cliquable.
- Bouton global « Reindex code tools » → POST `/api/sync?scope=code-tools`.

**Scan actuel (machine de dev)** :
| Outil | Binaire | Version | Installé |
|---|---|---|---|
| Claude Code | `/Users/mbakkali/.nvm/versions/node/v22.14.0/bin/claude` | 2.1.126 | ✅ |
| Kimi | `/Users/mbakkali/.local/bin/kimi` | 1.40.0 | ✅ |
| Gemini CLI | `/Users/mbakkali/.nvm/versions/node/v22.14.0/bin/gemini` | 0.40.1 | ✅ |
| Cursor | `/usr/local/bin/cursor` | 3.2.11 | ✅ |
| Factory | — | — | ❌ (agentpipe only) |
| Qwen | — | — | ❌ (agentpipe only) |
| Continue | — | — | ❌ (agentpipe only) |

### 6.4 Models (onglet)

Entrée dans `sidebar-nav.tsx` : **« Models »** (icône `AiBrain02Icon`).

Composant `models-view.tsx` :
- Sections collapsées par source : *LiteLLM hosted*, *LiteLLM local*, *OpenRouter*, *Direct*.
- Chaque carte affiche : nom + badge `api` + provider + **chemin absolu de la source** (`local-tools.yaml`, copiable) + bouton « Probe » (GET /v1/models) + bouton « Ouvrir » (vscode://file/…).
- Pour LiteLLM local : champ éditable `base_url` (sauvegardé dans `local-tools.yaml`, jamais en state YAML).
- Bouton global « Reindex models » → POST `/api/sync?scope=models`.

### 6.4 Sécurité (onglet existant)

Ajouter colonne « Source » avec :
- chemin absolu cliquable (copy + ouvrir dans VSCode)
- pastille ⚠ si `source_url` est `null` (variable présente en RAM mais introuvable sur disque → probablement injectée par un launcher).

### 6.5 SourceRef partagé

Composant partagé `<SourceRef path={...} />` dans `zab-ui/src/components/ui/source-ref.tsx` :
- icône **copier**
- icône **ouvrir** (`vscode://file/{abs}` pour les fichiers, lien externe pour `https://`)
- tooltip avec le chemin complet si tronqué

Utilisé dans toutes les vues : Connecteurs, Code Tools, Models, Secrets, Skills, Plugins, Orgs.

### 6.6 Recherche globale (⌘K)

Ajouter une **Command Palette** (react-cmdk ou shadcn Command) accessible par `Cmd+K` :
- Recherche cross-section : skills, connecteurs, code-tools, models, tags.
- Navigation rapide : "aller à Linear", "voir skill cockpit".
- Actions rapides : "Sync now", "Probe Linear".

---

## 7. Étapes d'implémentation

### Phase 0 — Fondations (pré-requis)

1. **Dépaternalisation préalable** : extraire tous les chemins hardcodés (`/Users/mbakkali`, `~/.mehdi-context`, etc.) dans une fonction `zab/paths.py` qui lit `~/.zab/config.yaml`.
2. **Pydantic models** : `zab/models/state.py` avec les classes `ZabState`, `Connector`, `ConnectorForm`, `Skill`, `CodeTool`, `ModelEndpoint`, `Tag`, `SyncLogEntry`.
3. **State persistence** : `zab/state_persistence.py` (lecture/écriture YAML, merge avec `overrides.yaml`, file lock, validation schema version).
4. **CLI `zab init`** : génère `~/.zab/config.yaml` en mode interactif (détecte ce qui existe).

### Phase 1 — Skills (valeur immédiate)

5. **Indexer skills** : `zab/services/indexer/skills.py` (walk `orgs/`, `claude-plugins/`, `common/`, parse frontmatter).
6. **CLI** : `zab sync skills`.
7. **API** : `GET /api/skills`, `GET /api/skills/{id}`.
8. **UI** : chips tags, section connecteurs utilisés.
9. **Tests** : `zab/tests/test_indexer_skills.py` (fixtures FS temporaire), `test_routes_skills.py`.

### Phase 2 — Connecteurs MCP (remplace discovery)

10. **Indexer MCP** : `zab/services/indexer/connectors_mcp.py` (parse JSON configs cursor + desktop + `~/.cursor` + `~/.claude`).
11. **API connectors** : `GET /api/connectors`, `GET /api/connectors/{slug}`.
12. **UI connectors** : badges form-kind, drawer Voir, filtres tags.
13. **Tests** : e2e Playwright sur le drawer.

### Phase 3 — Connecteurs API + CLI

14. **Indexer API** : `zab/services/indexer/connectors_api.py` (scan `.env`, `local-tools.yaml`).
15. **Indexer CLI** : `zab/services/indexer/connectors_cli.py` (`which` sur whitelist).
16. **API** : probe connectors.

### Phase 4 — Code Tools

17. **Indexer code-tools** : agentpipe (`~/.agentpipe.yaml`), codexbar (`~/.codexbar/config.json`), `which` sur PATH.
18. **API code-tools** : `GET /api/code-tools`, probe.
19. **UI** : onglet Code Tools.

### Phase 5 — Models

20. **Indexer models** : litellm hosted/local (`local-tools.yaml`), openrouter, anthropic direct (`ENV`).
21. **API models** : `GET /api/models`, probe.
22. **UI** : onglet Models.

### Phase 6 — Secrets + Polish

23. **Secrets `source_url`** : `_locate_var()` + colonne Source dans l'UI Sécurité.
24. **Sync log** : bandeau UI « Last synced 3 min ago — [Sync now] ».
25. **Command Palette** : recherche globale ⌘K.

### Phase 7 — Préparation OSS (plus tard)

26. **Packaging** : `pipx install zab`, wheel avec UI embarquée.
27. **Licence** : Apache 2.0, repo public séparé.
28. **README OSS** : use case générique, screenshots non identifiants.

---

## 8. Onglet « Outils de code » (détail)

### 8.1 Distinction avec « Models »

| Concept | Outils de code | Models |
|---|---|---|
| **Quoi** | Agents CLI (Claude Code, Kimi, Gemini CLI, Cursor IDE…) | Endpoints API (LiteLLM, OpenRouter, Anthropic direct…) |
| **Rôle** | Application que l'utilisateur **lance** pour coder | Service que les outils **appellent** pour inférer |
| **Probe** | `which + --version` | `GET /v1/models` |
| **Source** | `~/.agentpipe.yaml`, `~/.codexbar/config.json`, `which` | `local-tools.yaml`, `.env` |

### 8.2 Modèle de données (YAML)

```yaml
code_tools:
  claude:
    id: "claude"
    display_name: "Claude Code"
    kind: "agent"                   # agent | ide | ide-extension
    provider: "anthropic"
    source_kind: "agentpipe"
    source_ref: "/Users/mbakkali/.agentpipe.yaml#claude"
    enabled: true
    meta:
      binary: "/Users/mbakkali/.nvm/versions/node/v22.14.0/bin/claude"
      version: "2.1.126"
      install_hint: "npm install -g @anthropic-ai/claude-code"
      used_via: ["agentpipe", "direct"]
    tags: ["perso"]

  cursor:
    id: "cursor"
    display_name: "Cursor"
    kind: "ide"
    provider: "cursor"
    source_kind: "agentpipe"
    source_ref: "/Users/mbakkali/.agentpipe.yaml#cursor"
    enabled: true
    meta:
      binary: "/usr/local/bin/cursor"
      version: "3.2.11"
      install_hint: "brew install --cask cursor"
      used_via: ["agentpipe", "direct"]
    tags: ["perso"]

  factory:
    id: "factory"
    display_name: "Factory"
    kind: "agent"
    provider: "factory"
    source_kind: "agentpipe"
    source_ref: "/Users/mbakkali/.agentpipe.yaml#factory"
    enabled: true
    meta:
      binary: null
      version: null
      install_hint: "Voir https://factory.ai"
      used_via: ["agentpipe"]
    tags: ["perso"]
```

### 8.3 Sources à indexer

| Source | Localisation | Donne |
|---|---|---|
| **Agentpipe** | `~/.agentpipe.yaml` | 7 agents (claude, gemini, kimi, cursor, factory, qwen, continue) → un `code_tool` par item. `which(type)` détecte si binaire installé. |
| **CodexBar** | `~/.codexbar/config.json` | mapping CLI ↔ raccourcis (`meta.codexbar_id`). Lecture défensive `dict[str, Any]`. |
| **Which fallback** | `PATH` | pour chaque agentpipe entry, si `which(agent.type)` trouve un binaire → enrichit `meta.binary` + `meta.version`. Sinon `binary: null`. |

→ Le chemin `~/.agentpipe.yaml` est **absolu et stable** (vérifié : existe, version "1.0", 7 agents). Le mettre dans `paths.py` sous `agentpipe_config_path()`.

### 8.4 Kind mapping

| Agentpipe `type` | `kind` | Binaire attendu |
|---|---|---|
| `claude` | `agent` | `claude` |
| `kimi` | `agent` | `kimi` |
| `gemini` | `agent` | `gemini` |
| `cursor` | `ide` | `cursor` |
| `factory` | `agent` | `factory` (souvent web-only) |
| `qwen` | `agent` | `qwen-agent` |
| `continue` | `ide-extension` | VS Code extension (pas de binaire) |

---

## 9. Onglet « Models » (détail)

### 9.1 Modèle de données (YAML)

```yaml
models:
  litellm-hosted:
    id: "litellm-hosted"
    display_name: "LiteLLM (hosted)"
    kind: "api"
    provider: "litellm"
    source_kind: "local-tools-yaml"
    source_ref: "/Users/mbakkali/projects/skills/zab/local-tools.yaml#proxies.litellm_hosted"
    enabled: true
    meta:
      base_url: "https://litellm.fmetrik.com"
      api_key_env: "OPENAI_API_KEY"
      auth: "bearer"
      models_cache: ["claude-opus-4-6", "gemini-3-1-pro"]
    tags: ["flowmetrik"]

  openrouter:
    id: "openrouter"
    display_name: "OpenRouter"
    kind: "api"
    provider: "openrouter"
    source_kind: "local-tools-yaml"
    source_ref: "/Users/mbakkali/projects/skills/zab/local-tools.yaml#proxies.openrouter"
    enabled: true
    meta:
      base_url: "https://openrouter.ai/api/v1"
      api_key_env: "OPENROUTER_API_KEY"
      auth: "bearer"
    tags: ["perso"]
```

### 9.2 Sources à indexer

| Source | Localisation (URL/chemin) | Donne |
|---|---|---|
| **LiteLLM hosted** | `zab/local-tools.yaml#proxies.litellm_hosted` | model (kind=`api`), probe `/v1/models` |
| **LiteLLM local** | idem mais avec `base_url` `http://localhost:4000/...` | idem (entrée séparée) |
| **OpenRouter** | `zab/local-tools.yaml#proxies.openrouter` (`OPENROUTER_API_KEY`) | model (kind=`api`), probe `/v1/models` |
| **Anthropic direct** | `ENV:ANTHROPIC_API_KEY` | model (kind=`api`, provider=`anthropic`) |

### 9.3 LiteLLM : hosted vs local

**Deux entrées distinctes** (`litellm-hosted` + `litellm-local`) car :
- C'est plus clair pour l'UI (deux cartes distinctes avec leurs propres probes).
- L'utilisateur peut avoir l'un sans l'autre.
- Le `local-tools.yaml` les définit comme deux clés séparées sous `proxies:`.

---

## 10. Onglet Sécurité — afficher l'URL de chaque variable

**Problème actuel** : `routes.security_env()` renvoie `{name, present, masked}` — pas l'origine.

### 10.1 Descripteur enrichi

Dans `secrets_catalog.py` :

```python
@dataclass(frozen=True)
class TrackedVar:
    name: str
    category: str          # "connector" | "google" | "llm"
    source_url: str | None # chemin absolu où elle est définie/attendue
    doc_url: str | None    # lien externe (Anthropic console, OpenRouter dashboard…)
    description: str
```

Sources types :

| Variable | `source_url` (où elle vit) |
|---|---|
| `QONTO_API_KEY`, `PENNYLANE_API_KEY`, `EVOLUTION_*` | `<repo>/.env` (résolu en absolu via `skills_root() / ".env"`) |
| `GOOGLE_REFRESH_TOKEN`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | `~/.mehdi-context/.env` |
| `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `LITELLM_MASTER_KEY` | `~/.zshrc` ou `<repo>/.env` (selon le shell — résolu via `_locate_var(name)`) |
| `MEHDI_MEMORY_DATABASE_URL`, `FLOWMETRIK_MCP_ID_TOKEN` | `<repo>/.env` |

### 10.2 Helper `_locate_var(name)`

```python
def _locate_var(name: str) -> str | None:
    candidates = [
        skills_root() / ".env",
        Path.home() / ".mehdi-context" / ".env",
        Path.home() / ".zshrc",
        Path.home() / ".zprofile",
        Path.home() / ".bashrc",
    ]
    for p in candidates:
        try:
            if p.is_file() and re.search(rf"^\s*(export\s+)?{re.escape(name)}=", p.read_text(), re.M):
                return str(p)
        except OSError:
            continue
    return None
```

→ Renvoyé dans la réponse API : `{name, present, masked, source_url, doc_url, category}`.

**Si une variable est définie dans plusieurs fichiers** : on retourne la **première source trouvée** dans l'ordre de priorité ci-dessus (`.env` > `~/.mehdi-context/.env` > shell rc). L'UI affiche un tooltip "aussi défini dans ~/.zshrc" si une seconde source est détectée (helper `_locate_all_sources` pour l'UI, `_locate_var` pour la valeur canonique).

---

## 11. CLI `zab sync` — réindexation FS → YAML

La commande `zab sync` est le **chemin canonique** entre la source de vérité (FS) et l'index YAML. Idempotente, observable, scopable.

### 11.1 Sous-commandes

```bash
zab sync                       # sync global (skills + connectors + code-tools + models + secrets)
zab sync skills                # ne réindexe que orgs/, claude-plugins/, common/
zab sync connectors            # configs MCP + .env + cli-tools.yaml + ~/.cursor + Claude Desktop
zab sync code-tools            # ~/.agentpipe.yaml, ~/.codexbar/config.json, which sur PATH
zab sync models                # local-tools.yaml proxies + ENV direct
zab sync secrets               # secrets_catalog → résolution source_url
zab sync --dry-run             # affiche le diff sans écrire en state.yaml
zab sync --since <iso>         # ne touche que les fichiers modifiés après <iso>
zab sync --json                # machine-readable (intégrations agents)
zab sync --force               # kill un sync en cours et relance
```

**Hors scope v1** (reporté v2) :
- `--watch` : trop complexe (inotify limits, reindex incrémental). Remplacé par un polling côté UI.

### 11.2 Pipeline d'un `zab sync skills`

1. **Walk** `orgs/*/skills/*/SKILL.md` + `claude-plugins/*/skills/*/SKILL.md` + `common/*/SKILL.md`.
2. **Parse** frontmatter YAML (`name`, `description`, `version`, `tags`, `uses_connectors`, `uses_code_tools`, `uses_models`).
3. **Hash** contenu (sha1) → upsert si différent (`updated_at = mtime`).
4. **Tags** : org inféré du chemin (`orgs/<org>/...`) + plugin (`claude-plugins/<plugin>/...`) + tags libres du frontmatter.
5. **Liens** : pour chaque mention dans le frontmatter, ajouter à `uses_connectors` / `uses_code_tools` / `uses_models`.
6. **GC** : skill présent dans l'ancien state mais absent du FS → suppression du state (pas de soft-delete, le state est régénéré).
7. **Stats** : `+12 skills, ~3 modifiés, -1 supprimé` (TTY) ou JSON.

### 11.3 Architecture indexers

```
zab/services/indexer/
  __init__.py         # registre + orchestrateur
  base.py             # class Indexer(Protocol): name, sync(scope, dry_run) -> Diff
  skills.py           # SkillsIndexer
  connectors_mcp.py   # MCPIndexer (cursor + desktop + ~/.cursor + ~/.claude…)
  connectors_api.py   # APIIndexer (env vars → connecteurs api)
  connectors_cli.py   # CLIIndexer (which sur whitelist)
  code_tools_agentpipe.py # AgentpipeIndexer (agents CLI)
  code_tools_codexbar.py  # CodexBarIndexer (raccourcis CLI)
  models_litellm.py       # LiteLLMIndexer (hosted + local)
  secrets.py          # SecretsIndexer
```

→ Chaque indexer est **autonome** (échec d'un n'invalide pas les autres).
→ Le registre est **pluggable** : un user OSS peut déposer `~/.zab/indexers/<mon_indexer>.py` chargé dynamiquement (import avec restrictions).

### 11.4 Gestion des échecs partiels

Si un indexer échoue (ex: `~/.agentpipe.yaml` illisible) :
- Les autres indexers continuent.
- Le state est quand même écrit, mais les sections en échec sont marquées dans `sync_log`.
- L'UI affiche un avertissement : "⚠️ Agentpipe index failed — state may be incomplete".
- Pas de rollback (le state est un snapshot, pas une transaction DB).

### 11.5 Intégration UI

- Bandeau dans le dashboard : « Dernier sync il y a 3 min — [Sync now] ». Le bouton POSTe `/api/sync?scope=all` qui retourne un `job_id`.
- Polling toutes les 2 secondes sur `GET /api/sync/status`.
- Indicateur par section (Skills / Connecteurs / Models) avec son `last_synced_at` propre.

---

## 12. Probes (sécurisés)

### 12.1 Timeout strict

Tous les probes sont exécutés avec un timeout de **5 secondes maximum** :
- MCP stdio : `subprocess.run(timeout=5)` + kill forcé après (`process.kill()`).
- API : `httpx.get(timeout=5)`.
- CLI : `subprocess.run([binary, "--version"], timeout=5)`.

### 12.2 Sandboxing minimal

- Les probes MCP tournent dans un **thread pool** (`concurrent.futures.ThreadPoolExecutor(max_workers=4)`) pour ne pas bloquer l'event loop FastAPI.
- Aucun accès réseau arbitraire : les URLs de probe API sont whitelistées (seules les URLs déclarées dans `meta.base_url` sont appelées).
- Les arguments CLI sont figés (`--version`, `--help`) — jamais de commande arbitraire.

### 12.3 Cache des résultats

Les résultats de probe sont stockés en mémoire (TTL 60 secondes) pour éviter de re-spammer les services. L'UI affiche un badge "Probed 30s ago" avec un bouton "Re-probe".

---

## 13. Cap open-source (préparation)

À faire **dès la v1** pour ne pas avoir à refactorer plus tard :

### 13.1 Dépaternalisation

- **Aucun chemin en dur** vers `/Users/mbakkali`, `~/.mehdi-context`, `flowmetrik`, etc. dans le code.
- Toute config dans `~/.zab/config.yaml` (créée par `zab init`) :

```yaml
skills_roots:
  - ~/projects/skills              # repo principal (équivalent ZAB_SKILLS_ROOT)
  - ~/work/other-skills            # multi-repo
ide_configs:
  cursor:    ~/.cursor/mcp.json
  claude:    ~/Library/Application Support/Claude/claude_desktop_config.json
  agentpipe: ~/.agentpipe.yaml
  codexbar:  ~/.codexbar/config.json
proxies:
  litellm_hosted:
    base_url: https://litellm.example.com
    api_key_env: OPENAI_API_KEY
  litellm_local:
    base_url: http://localhost:4000
    api_key_env: LITELLM_LOCAL_KEY
  openrouter:
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
db:
  path: ~/.zab/state.yaml         # ou <repo>/.zab/state.yaml
code_tools:
  agentpipe_config: ~/.agentpipe.yaml
  codexbar_config: ~/.codexbar/config.json
  # Les outils détectés automatiquement via agentpipe + which
  # Pas de whitelist — tous les agents listés dans agentpipe sont indexés
cli_tools:
  whitelist: [gh, gcloud, aws, uv, node, npm]
secrets:
  scan_paths: [./.env, ~/.mehdi-context/.env, ~/.zshrc, ~/.zprofile]
```

- `zab init` génère ce fichier en mode interactif (détecte ce qui existe).
- Le repo `skills` actuel devient **un usage parmi d'autres** ; les chemins spécifiques (`mehdi-context`, `flowmetrik-gateway`) restent dans `local-tools.yaml` privé, gitignored.

### 13.2 Multi-repo skills

`skills_roots` est une liste. En cas de collision de `skill_id` entre deux repos :
- Le **dernier repo dans la liste l'emporte** (override).
- L'UI affiche un badge "⚠️ duplicate" sur les skills en conflit.
- En v1, on documente cette limitation. Pas de namespace automatique.

### 13.3 Packaging

- Renommer le PyPI package `zab` → namespace neutre (à choisir, `zab` libre sur PyPI ?). Sinon `zabctl`, `aistack`, `aimux`.
- `pipx install zab` → binaire global, pas besoin du repo skills.
- Le dashboard (zab-ui) embarqué dans la wheel via `importlib.resources`.
- Migration `uv` → laisser `pyproject.toml` compatible `pip`/`pipx`/`uv`.

### 13.4 Licence + repo

- Licence **Apache 2.0** ou MIT (à choisir).
- Repo public séparé `github.com/<user>/zab`, le repo `skills` privé reste consommateur.
- README OSS centré sur le use case générique (« local AI command center »), screenshots non identifiants.
- Issues / RFCs pour les indexers tiers.

### 13.5 Sécurité

- Code path : aucun secret loggé, valeurs masquées partout (déjà fait dans `routes.security_env`).
- `zab sync` ne **transmet jamais** les valeurs de secrets — il enregistre uniquement `name`, `present`, `source_url`, `masked`.
- Aucune télémétrie sortante par défaut. Si ajoutée plus tard, opt-in explicite.
- **Pas de hooks post-sync en v1** (trop risqué : exécution arbitraire via YAML). Reporté v2 si demandé.

### 13.6 Compatibilité

- Linux + macOS Day 1. Windows : nice-to-have (les chemins `~/.cursor`, `~/Library/...` à abstraire via `platformdirs`).

---

## 14. Roadmap (ordre tranché)

1. **Phase 0** : `zab init` + `~/.zab/config.yaml` + Pydantic models + YAML persistence (state + overrides).
2. **Phase 1** : Indexer skills + `zab sync skills` + API skills + UI skills (tags, connecteurs utilisés).
3. **Phase 2** : Indexer connectors MCP + API connectors + drawer Voir + filtres tags.
4. **Phase 3** : Indexer connectors API + CLI + probes connectors.
5. **Phase 4** : Indexer code-tools (agentpipe/codexbar + which) + onglet Code Tools.
6. **Phase 5** : Indexer models (litellm/openrouter/anthropic direct) + onglet Models.
7. **Phase 6** : Secrets `source_url` + colonne Source + Command Palette ⌘K.
8. **Phase 7** : Polish OSS (licence, README générique, `pipx`, repo public).

**Hors scope v1 (reporté v2)** :
- `--watch` (fsnotify)
- Hooks post-sync
- Pluggable indexers entry-point (seulement `~/.zab/indexers/*.py` en v1)
- Mode chat / REPL
- Windows support
- Multi-user / collaboratif

---

## 15. Questions ouvertes (tranchées)

| # | Question | Décision |
|---|---|---|
| 1 | DB 100% régénérable ou champs éditables UI ? | **Régénérable pour `state.yaml`, overrides dans `overrides.yaml` séparé.** |
| 2 | CLI tools : whitelist statique ou auto-discover ? | **Whitelist dans `cli-tools.yaml` (prévisible, contrôlable).** |
| 3 | MCP probe : autoriser le spawn ? | **Oui, avec timeout 5s, thread pool, kill forcé, et cache 60s.** |
| 4 | Configs Cursor/Claude Desktop hors repo ? | **Lire en lecture seule les deux** (`configs/` ET `~/.cursor` / `~/Library`). |
| 5 | Tags libres en v1 ? | **Oui, mais simple** : tags libres dans frontmatter skills + `overrides.yaml`. Pas d'éditeur de tags dans l'UI en v1 (lecture seule). |
| 6 | Localisation DB/state : `~/.zab/` ou `<repo>/` ? | **`~/.zab/state.yaml` par défaut** (global, partagé entre clones). Option `<repo>/.zab/state.yaml` via config. |
| 7 | Skills ↔ connecteurs/code-tools/models : détection auto ou explicite ? | **Explicite** via frontmatter `uses_connectors` / `uses_code_tools` / `uses_models`. Pas de regex sur le markdown en v1. |
| 8 | CodexBar : format inconnu ? | **Lecture défensive `dict[str, Any]`**. Skip silencieux si illisible. |
| 9 | LiteLLM local vs hosted : une ou deux entrées ? | **Deux entrées distinctes** (`litellm-hosted`, `litellm-local`). |
| 10 | Secrets multi-sources : lister toutes ou première ? | **Première trouvée** (priorité `.env` > shell rc). Tooltip si seconde source détectée. |
| 11 | Nom OSS final ? | **À décider avant Phase 6** (`zab` est un nom de code interne). Candidats : `aistack`, `aimux`, `pilote`, `cockpit-cli`. |
| 12 | Multi-repo skills : collision de noms ? | **Dernier repo l'emporte** en v1. Badge "duplicate" dans l'UI. |
| 13 | Pluggable indexers : entry-point ou dossier ? | **Dossier `~/.zab/indexers/*.py`** en v1 (plus accessible). Entry-point setuptools en v2. |
| 14 | Hooks post-sync en v1 ? | **Non** (risque sécurité). Reporté v2. |
| 15 | Mode chat / REPL ? | **Non**. `zab` reste observabilité. Les agents consomment via l'API. |
| 16 | Pagination ? | **Oui, dès la v1** (page + limit sur toutes les routes liste). |
| 17 | Soft-delete ? | **Non**. Le state est régénéré, pas de soft-delete. Les overrides YAML persistent les préférences. |
| 18 | Distinction code-tools vs models ? | **Oui, deux sections distinctes**. Code Tools = agents CLI que l'utilisateur lance. Models = endpoints API que les outils appellent. |
