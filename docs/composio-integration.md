# Intégration Composio dans zab — état au 2026-05-14

## Vision

Composio sert de **couche de portabilité** pour les connecteurs : au lieu de
maintenir manuellement chaque MCP/API local, on s'appuie sur Composio pour
linker les comptes (Gmail, Notion, Slack, etc.) et zab agit comme façade
unifiée (UI dashboard + CLI + MCP) qui mélange MCP locaux, proxies API et
connexions Composio dans une même vue.

## Ce qui est livré

### 1. Source de connecteurs Composio (live)

- `zab/services/composio_connectors.py`
  - `fetch_connected_accounts()` : appelle d'abord REST `/api/v3/connected_accounts`,
    fallback automatique sur la **CLI** `composio connections list` quand la clé
    REST échoue (le cas actuel, voir « Multi-compte » plus bas).
  - `composio_forms()` : mappe chaque `connected_account` vers une `ConnectorForm`
    (kind=`composio`, transport=`http`, meta avec `toolkit_slug`, `auth_scheme`,
    `connected_account_id`, `account_email`, `user_id`, `mcp_url`).
  - **Cache mémoire TTL 90 s** (`_FORMS_CACHE_TTL_SECONDS`) pour amortir le
    dashboard et les appels MCP rapprochés. `clear_forms_cache()` exposé et
    branché dans `clear_connectors_cache()` (`zab sync`).
- `zab/services/connectors_aggregate.py` — intègre `composio_forms()` après les
  proxies, **fusion par slug** : un toolkit `gmail` Composio s'agrège avec un
  MCP `gmail` local sur la même `ConnectorRow` (forms multiples).
- **Multi-comptes par toolkit** : si tu as 3 comptes Gmail Composio, ils
  apparaissent comme 3 `forms` distinctes sous une seule ligne « gmail » dans
  le dashboard. La card affiche « 3 comptes » au lieu de « 3 formes » quand
  toutes les forms viennent de Composio.

### 2. Frontend (dashboard `/connecteurs`)

- `zab-ui/src/components/connectors-view.tsx`
  - Filtre chip **Composio** (envoie `?tag=composio` à l'API).
  - Badge tag `composio` sur chaque card.
  - Dans le dialog détail : bloc dédié pour `kind=composio` montrant
    `toolkit_slug`, `Compte (email/label)`, `User ID`, `Auth`, `Account ID`,
    `Statut`, `MCP URL`.
- `zab-ui/src/lib/connector-meta.ts` — cas `composio` dans `kindMeta`.

### 3. CLI `zab composio`

- `zab composio connections [--toolkit gmail] [--active] [--json]` — liste les
  comptes Composio connectés via la CLI locale.
- `zab composio execute <SLUG> -d '{...}'` — passthrough vers `composio execute`.
- `zab composio execute <SLUG> --get-schema --required-only` — schéma filtré
  aux **champs requis seulement** (avec premier exemple). Évite de lire un
  schéma de 200 lignes pour trouver le `file_name` requis (cas concret : c'est
  exactement ce qui m'a fait perdre 2 itérations sur `GMAIL_GET_ATTACHMENT`).
- `zab composio call <SLUG> -d '{...}' --account <word_id>` — wrapper REST
  `POST /api/v3/tools/execute/<slug>` qui devrait permettre de cibler un
  compte précis (multi-compte Gmail). **Actuellement bloqué côté Composio**,
  voir section dédiée.
- `zab composio search "..."` — passthrough vers `composio search`.
- `zab composio hint <slug>` — affiche les patterns CLI/REST/zab pour un
  connecteur.
- `zab inspect connectors <slug>` détecte les rows taggués `composio` et
  affiche un rappel pointant vers `zab composio hint`.

### 4. MCP surface réduite (token saving)

`zab/services/agent_context.py:run_mcp_stdio()` n'expose plus que :

- **`search`** : recherche dans l'index zab (skills, connecteurs, projets,
  modèles, mémoire), avec param optionnel `section` pour filtrer.
- **`inspect`** : détail complet d'un item indexé.

Les 5 tools précédents (`bootstrap`, `context_pack`, `project_handoff`,
`memory_status`, `security_status`) sont supprimés du MCP mais restent
disponibles via la CLI (`zab agent`, `zab security`, `zab context-pack`).

Gain : ~50 % de tokens fixes en moins par session MCP.

### 5. Skill ↔ env vars dans `state.yaml`

- `zab/services/skill_env_vars.py` (nouveau)
  - `extract_env_var_names(text)` : heuristique ALL_CAPS avec blocklist
    (TODO, HTTP, JSON…) + filtre underscore/KEY/TOKEN/SECRET/URL/ID.
  - `build_env_index(roots)` : scanne récursivement les `.env` sous
    `projects_roots` + `skills_roots` + `skills_repo_root`, ignore les
    `node_modules`, `.venv`, `dist`, etc.
  - `env_vars_for_skill(path, index)` : pour chaque var détectée dans le
    SKILL.md, renvoie `{name, files: [paths], present: bool}`.
- `state_index._skill_record()` persiste `env_vars` sur chaque skill.
- **Vérifié** : `zab inspect skills flowmetrik-flowmetrik-bank-sync` affiche
  maintenant `QONTO_ID` et `QONTO_SECRET_KEY` avec les **2 `.env`** qui les
  portent (`.env` files under project-specific cowork folders).

### 6. Secrets catalog

`zab/secrets_catalog.py` — `COMPOSIO_MCP` et `COMPOSIO_X_CONSUMER_API_KEY`
ajoutés à `CONNECTOR_VARS` pour apparaître dans `/security/env`.

---

## Test end-to-end : compta Qonto + Gmail (exemple de référence)

**Demande** : « sur Qonto j'ai plusieurs transactions injustifiées, va sur
mes comptes Gmail et télécharge les justificatifs ; passe au suivant si
impossible ; j'ai plusieurs comptes Gmail ; prends les 20 dernières
transactions. »

**Script** : `/tmp/compta_match.py` (à promouvoir dans `scripts/` ou comme
sous-commande zab si on industrialise).

**Pipeline exécuté** :

1. `zab search qonto` → trouve `flowmetrik-bank-sync` (skill avec
   `QONTO_ID`/`QONTO_SECRET_KEY` documentées). **Avec la feature #5, on
   verrait directement les `.env` à charger.**
2. **Qonto REST** `GET /v2/transactions?bank_account_id=…&per_page=20&sort_by=settled_at:desc`
   avec header `Authorization: ORG:SECRET` (format custom Qonto, **pas HTTP
   Basic**) → 20 dernières transactions du compte `bootly-7780-bank-account-1`.
3. Filtre `attachment_ids == []` → **15/20 débits sans justificatif**.
4. Pour chaque tx : `zab composio execute GMAIL_FETCH_EMAILS -d '{...}'`
   avec query Gmail composée :
   `{vendor} (facture OR receipt OR invoice OR confirmation) after:D-14 before:D+7 has:attachment`
   + filtre de pertinence post-process (vendor dans sender/subject/body).
5. Pour le premier match : `GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID` puis
   `GMAIL_GET_ATTACHMENT` avec `file_name` requis (cf. feature #3 qui aurait
   évité le faux départ).

**Résultats** :

```
total_tx           : 20
unjustified        : 15
with_match (after relevance filter) : 1   (HubSpot — billing@hubspot.com)
downloaded          : 0
```

**Pourquoi seulement 1 match / 0 téléchargement** (limites réelles, pas
bugs zab) :

- HubSpot, Cursor, Fireflies, Free Mobile, Orange, Staycation, Qonto fees :
  reçus envoyés **avec un lien vers le portail**, pas d'attachment Gmail.
  Gmail `has:attachment` les exclut. Sans `has:attachment` on les trouve,
  mais le téléchargement devient du **scraping web** (à faire via
  `composio firecrawl` qui est déjà actif chez toi).
- CAMPUS CARREFOUR, LA COUDRAIE, LA TAVERNE : restaurants → tickets papier,
  pas d'email du tout.
- HPY\*DEMARCHECARTEGR : libellé bancaire opaque (HiPay) → vendor `hpy` ne
  match rien.
- **Multi-comptes Gmail** : tu as 3 Gmail Composio actifs (`gmail_piend-damara`,
  `gmail_dun-bound`, `gmail_betail-apse`). La CLI `composio execute` ne route
  que vers UN seul compte par toolkit (celui lié au `test_user_id` global).
  D'où le wrapper `zab composio call --account <word_id>` (feature #3, voir
  bloqueur ci-dessous).

**Détails techniques découverts pendant le test** :

- L'API Qonto exige `Authorization: ORG:SECRET` **littéral** (pas Basic Auth).
  Erreur `unauthorized` muette sinon — facile à louper. À documenter dans
  `flowmetrik-bank-sync` ou exposer via `zab composio hint qonto`.
- `GMAIL_GET_ATTACHMENT` exige `file_name` (non documenté dans la signature
  CLI standard) — feature #3 (`--required-only`) le révèle en 15 lignes.
- Les query Gmail naïves matchent des faux positifs (`free` → emails AWS).
  Le filtre `is_relevant(message, vendor)` post-process est nécessaire.

---

## Bloqueur en cours : multi-compte Gmail via REST

### Symptôme

`zab composio call GMAIL_FETCH_EMAILS --account gmail_dun-bound -d '...'`
échoue, plus largement la REST `/api/v3/connected_accounts` retourne 0 items
alors que `composio connections list` (CLI) en voit 18 toolkits dont 3 Gmail
actifs.

### Diagnostic

- **The API key used during development was valid** (REST auth succeeded).
- **The correct HTTP header is `x-user-api-key`** (not `x-api-key`) — discovered by
  inspecting the Composio CLI binary strings (`~/.composio/composio`).
- With `x-user-api-key` + `x-org-id: ok_XXXX` + `x-project-id: pr_XXXX` : auth OK but **0 items**.
  With a `user_ids` filter: same result.
- Conclusion: some Composio connections exist in a "consumer" namespace managed by the
  CLI but are **invisible from the public REST `/api/v3/...`** API.
  The public REST is calibrated for **developer projects** (created via `composio dev init`).
- The exact endpoint the CLI uses for `connections list` was not identified without
  intercepting HTTPS traffic. The binary uses minified Bun ESNext; API names are obfuscated.

### Why we initially suspected a bad API key

That was a wrong hypothesis: the `uak_` key **was valid**. The real issue
est l'asymétrie consumer vs developer projects côté Composio.

### Pistes de résolution

1. **`composio dev init` dans un dossier dédié** (ex. `~/projects/zab/.composio-dev`)
   pour créer un developer project, puis re-link Gmail via `composio link gmail`
   sous ce contexte. Le `project_id` créé sera utilisable en REST avec
   `x-api-key` (clé de projet) + `x-project-id`. **Effort faible**, mais
   sépare les 3 Gmail actuels du contexte CLI courant.
2. **Modifier `zab composio call` pour fallback CLI** : si REST renvoie 0, on
   appelle `~/.composio/composio execute` en sous-processus. Inconvénient :
   on perd le `--account` ciblé (CLI = un seul compte par toolkit).
3. **Intercepter le trafic CLI** une fois mitmproxy installé proprement, pour
   identifier l'endpoint réel utilisé par `connections list` et `execute`
   côté consumer. Effort moyen, à faire avec ton accord.

### Recommandation

Option (1) est la plus propre et débloque le scénario compta complet :
- `composio dev init -y` dans un répertoire stable
- `composio link gmail` pour chaque compte (3 fois) sous ce projet
- Récupérer la clé projet (`pk_…`) via `composio dev` et la coller dans
  `.env` ou `~/.composio/user_data.json`
- Mettre à jour `zab composio call` pour utiliser cette clé en mode
  `x-api-key` + `x-project-id`

---

## Tests automatisés

- `zab/tests/test_composio_connectors.py` (10 tests) — fetch REST, dégradation
  silencieuse, CLI fallback, mapping multi-compte, agrégation, cache TTL.
- `zab/tests/test_skill_env_vars.py` (3 tests) — extraction ALL_CAPS,
  indexation .env, filtres bruit (`node_modules`, `.venv`).
- Suite complète : **124/124 passing**.

---

## Fichiers modifiés / créés

```
zab/services/composio_connectors.py     (nouveau)
zab/services/skill_env_vars.py           (nouveau)
zab/services/connectors_aggregate.py     (intégration composio_forms + cache invalidation)
zab/services/state_index.py              (env_vars sur chaque skill)
zab/services/agent_context.py            (MCP surface réduite)
zab/secrets_catalog.py                   (COMPOSIO_* vars)
zab/cli.py                               (groupe `zab composio` + `inspect` hint)
zab-ui/src/components/connectors-view.tsx (filtre composio + détail multi-compte)
zab-ui/src/lib/connector-meta.ts          (icône kind=composio)
zab/tests/test_composio_connectors.py     (nouveau)
zab/tests/test_skill_env_vars.py          (nouveau)
docs/composio-integration.md              (ce document)
scripts probants:
  /tmp/compta_match.py                   (orchestration Qonto + Gmail)
  /tmp/compta_report.json                (rapport JSON 15 tx + matches)
```

## Prochaines étapes possibles

1. **Débloquer multi-compte Gmail** (voir piste 1 ci-dessus).
2. **Scraping reçus via firecrawl** pour HubSpot/Cursor/Free/Orange (toolkit
   firecrawl actif chez toi) — boucler le scénario compta complet.
3. **Déplacer `compta_match.py` hors de `/tmp`** vers le projet/skill métier
   concerné si on veut le conserver. `zab` doit rester le middleware de
   découverte des skills/connecteurs, pas porter ce workflow.
4. **`zab composio hint <slug>` connector-specific** : aujourd'hui le hint
   est générique. Lui ajouter les patterns d'auth/headers spécifiques
   (ex. Qonto `Authorization: ORG:SECRET`, pas Basic).
5. **Audit log des appels Composio** dans `~/.config/zab/audit.jsonl` (slug,
   latence, succès) pour budgeter les usages.

---

## Relance exercice Qonto/factures — 2026-05-14

Tâche créée pour suivre l'exercice : Linear
`AGI-59` — "Audit Zab: rapprochement Qonto factures via Gmail + Firecrawl".

### Ce qui a été rejoué

1. `zab search qonto --json` trouve bien `flowmetrik-compta` et
   `flowmetrik-bank-sync`; le second expose directement les `.env` portant
   `QONTO_ID` et `QONTO_SECRET_KEY`.
2. `zab inspect connectors gmail --json` confirme 3 comptes Gmail Composio
   actifs.
3. `zab inspect connectors firecrawl --json` confirme un compte Firecrawl
   Composio actif.
4. `/tmp/compta_match.py` a été relancé sur les 20 dernières transactions
   Qonto : 15 débits sans justificatif, 0 match Gmail avec la requête actuelle
   basée sur `has:attachment`.
5. En ciblant explicitement le compte Gmail via la CLI Composio
   (`--account gmail_betail-apse`), le reçu HubSpot exact a été retrouvé et
   téléchargé :
   `/tmp/compta_attachments/2026-05-14_225.88EUR_HubSpot-RECEIPT-47263158.0.pdf`.
6. Firecrawl a été vérifié côté CLI locale et côté Composio :
   `FIRECRAWL_SCRAPE` fonctionne; `FIRECRAWL_SEARCH` fonctionne avec l'input
   `q`, pas `query`.

### Constats d'audit

- **Le principal blocage n'était pas Gmail, mais le routage compte** :
  avant cet exercice, `zab composio execute` ne permettait pas de passer
  `--account`, alors que la CLI Composio le supporte. Résultat : le script
  utilisait le compte par défaut et ratait le reçu HubSpot présent dans un
  autre Gmail. Correction appliquée dans `zab/cli.py` pendant l'exercice.
- **Le wrapper REST `zab composio call --account` reste utile**, mais il ne
  remplace pas le support `--account` du passthrough CLI tant que l'API REST
  v3 ne voit pas les comptes consumer.
- **La fenêtre Gmail `before:D+7` est dangereuse le jour du test** :
  Composio/Gmail considère `before:2026/05/15` comme futur le 2026-05-14 et
  renvoie une erreur métier dans un résultat `successful: true`. Le script
  doit plafonner `before` à aujourd'hui ou supprimer `before` quand la borne
  calculée est future.
- **`has:attachment` est trop restrictif comme première passe** : pour
  HubSpot, le reçu était bien attaché, mais il a été manqué uniquement à cause
  du mauvais compte. Pour d'autres fournisseurs, il faudra une seconde passe
  sans `has:attachment` et extraction de liens.
- **Firecrawl est prêt mais pas encore intégré au flux compta** : on peut
  scraper ou chercher, mais il manque une étape structurée "extraire les liens
  de facture depuis l'email, puis Firecrawl scrape/interact".
- **Les sorties Composio sont trop brutes pour un agent** : `FIRECRAWL_SCRAPE`
  renvoie un gros JSON complet; `GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID` bascule
  parfois en fichier temporaire quand la sortie dépasse le budget. Zab devrait
  proposer un mode résumé/artefacts.

### Améliorations produit à prioriser

1. Promouvoir le support `--account` ajouté à `zab composio execute` dans le
   hint Gmail.
2. Exposer les informations utiles aux agents directement dans
   `zab inspect connectors <slug> --json` :
   - comptes/forms disponibles,
   - commandes de découverte utiles,
   - warning multi-compte,
   - variables d'environnement déclarées par les forms.
   Le rapprochement Qonto, la récupération de justificatifs et les éventuelles
   automatisations navigateur doivent rester dans les skills/projets métier, pas
   dans le middleware `zab`.
3. Ajouter un mode `--summary` ou `--select` à `zab composio execute` pour
   extraire uniquement les champs utiles (`messageId`, `sender`, `subject`,
   `attachmentList`, `file.s3url`, etc.).
4. Transformer les erreurs métier Composio (`successful: true` avec
   `composio_execution_message` d'erreur) en statut zab explicite
   `warning`/`query_error`.
5. Enrichir `zab composio hint gmail` et `zab composio hint firecrawl` avec
   des recettes concrètes :
   - Gmail multi-compte : `zab composio execute ... --account <word_id>`.
   - Firecrawl search : champ requis `q`.
   - Firecrawl scrape : champ requis `url`.
6. Ajouter un audit log local des appels Composio/Firecrawl avec slug, compte,
   latence, taille de sortie, fichier temporaire éventuel, succès métier et
   coût/crédits quand disponible.

### Middleware livré

`zab sync` enrichit maintenant les connecteurs avec un bloc `agent_hints`.
Exemple attendu :

```bash
zab inspect connectors gmail --json
```

Le bloc aide un agent à décider quoi faire ensuite sans que `zab` embarque un
workflow métier : inspecter le connecteur, lister les comptes Composio,
découvrir les tools, lire les schémas requis, puis déléguer l'exécution à la
skill ou au projet concerné.
