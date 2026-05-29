# Diffusion cross-CLI des skills (`zab skill broadcast`)

Zab maintient un inventaire unifié de skills (Hermes, `external_dirs`, secondbrain) et peut le **répliquer** vers d'autres CLIs qui ne partagent pas le même mécanisme de découverte qu'Hermes ou Cursor.

## Objectif

| CLI | Mécanisme zab | Fichiers touchés |
|-----|---------------|------------------|
| **Hermes** | Natif (`~/.hermes/skills` + `external_dirs`) | Aucun broadcast nécessaire |
| **Cursor** | Skills du workspace + MCP zab | Aucun broadcast nécessaire |
| **Claude Code** | Symlinks plats + marqueur `.zab-managed.json` | `~/.claude/skills/<name>` → dossier source |
| **Kimi** | Liste `extra_skill_dirs` dans TOML | `~/.kimi/config.toml` |
| **Gemini CLI / Antigravity** | MCP zab (pas de répertoire SKILL.md) | `~/.gemini/settings.json` → `mcpServers.zab` |

Le broadcast **ne remplace pas** le registre `skills-registry.json` ni `zab skill hermes-update` : il cible uniquement Claude et Kimi. Pour Gemini/Antigravity, voir [MCP zab](#gemini-cli-et-antigravity-mcp-zab).

## Sources scannées

`discover_skill_roots()` agrège, dans l'ordre :

1. `~/.hermes/skills/`
2. Chaque entrée de `skills.external_dirs` dans `~/.hermes/config.yaml`
3. `~/.config/secondbrain/skills/` (skills perso versionnés)

`enumerate_skills()` parcourt chaque root (récursif `SKILL.md`), déduplique par **nom de dossier** (first-wins). Les collisions sont listées en log interne, pas bloquantes.

## Commande CLI

```bash
# Aperçu sans écriture (défaut)
uv run zab skill broadcast

# Appliquer vers Claude + Kimi
uv run zab skill broadcast --apply

# Une seule cible
uv run zab skill broadcast --apply --targets claude
uv run zab skill broadcast --apply --targets kimi

# Sortie machine (cron, agents)
uv run zab skill broadcast --apply --json
```

### Cible `claude`

- Crée des **symlinks** `~/.claude/skills/<skill-name>` → répertoire parent du `SKILL.md`.
- Écrit `~/.claude/skills/.zab-managed.json` : liste des symlinks posés par zab (`version`, `updated_at_utc`, `symlinks`).
- **Ne modifie pas** : entrées préexistantes absentes du marqueur (skills perso, liens vers `~/.agents/skills`, vrais dossiers).
- **Nettoie** : symlinks encore dans le marqueur mais plus présents dans l'inventaire source.

### Cible `kimi`

- Remplace la ligne `extra_skill_dirs = [...]` dans `~/.kimi/config.toml` par la liste des **roots** (pas des skills individuels).
- Préserve le reste du fichier via regex (commentaires hors ligne `extra_skill_dirs` conservés autant que possible).
- Si `config.toml` absent : dry-run / apply sans erreur, `changed: false`.

## Cron quotidien (macOS launchd)

Job utilisateur recommandé :

| Élément | Valeur |
|---------|--------|
| Label | `ai.zab.skills-broadcast` |
| Plist | `~/Library/LaunchAgents/ai.zab.skills-broadcast.plist` |
| Horaire | 08:00 locale (`StartCalendarInterval`) |
| Commande | `zab skill broadcast --apply --json` |
| Logs | `~/.local/state/zab/logs/skills-broadcast.out.log` (append JSON par run) |

Vérification :

```bash
launchctl print "gui/$(id -u)/ai.zab.skills-broadcast"
tail -3 ~/.local/state/zab/logs/skills-broadcast.out.log
```

Contenu attendu après un run idempotent stable : `created: []`, `changed: false` (kimi), pas de `removed` massif.

## Gemini CLI et Antigravity (MCP zab)

Ces CLIs n'ont pas de dossier « skills » à scanner. Zab expose déjà un serveur MCP stdio :

```bash
uv run zab mcp serve
```

Outils utiles : `skills_manifest`, `search`, `inspect`, `context_pack`.

Configuration type (Hermes utilise déjà ce pattern) :

```yaml
# ~/.hermes/config.yaml (référence)
mcp_servers:
  zab:
    command: /chemin/vers/zab/.venv/bin/zab
    args: [mcp, serve]
```

Pour **Gemini CLI** (~0.40), ajouter dans `~/.gemini/settings.json` (clé à confirmer selon version : `mcpServers` ou variante documentée) :

```json
{
  "mcpServers": {
    "zab": {
      "command": "/Users/VOTRE_USER/projects/zab/.venv/bin/zab",
      "args": ["mcp", "serve"],
      "timeout": 30000
    }
  }
}
```

Documenter dans `~/.gemini/GEMINI.md` que le modèle peut appeler `zab.skills_manifest` pour découvrir les skills sans les charger en contexte.

Antigravity partage souvent `~/.gemini/` ; si une config séparée existe sous `~/Library/Application Support/Antigravity/`, dupliquer le bloc MCP.

## Configuration (à venir)

Le plan de suivi prévoit dans `~/.config/zab/config.yaml` :

```yaml
skills_broadcast:
  exclude_orgs:
    kimi: [carrefour, celeste]
    claude: []
  exclude_skill_globs:
    kimi: ["*-internal-*"]
```

Filtrage par target au prochain chantier — voir [Plan de suivi](#plan-de-suivi).

## Dashboard (à venir)

Endpoints prévus :

- `GET /api/skills/broadcast/status` — dernière exécution, compteurs par target, prochain cron
- `POST /api/skills/broadcast/run` — déclenchement manuel (`targets`, `dry_run`)

UI : bandeau dans l'onglet Skills + entrée dans Crons.

## Module Python

- **Service** : `zab/services/skills_broadcast.py`
- **Entrées** : `broadcast()`, `discover_skill_roots()`, `enumerate_skills()`, `broadcast_claude()`, `broadcast_kimi()`
- **CLI** : `zab/cli.py` → `skill_app` commande `broadcast`

## Plan de suivi

Chantiers restants (tests, commit, exclude orgs, validation cron, UI) :

**[.hermes/plans/2026-05-28_153031-skills-broadcast-followups.md](../.hermes/plans/2026-05-28_153031-skills-broadcast-followups.md)**

Ordre recommandé : tests + commit → validation cron → MCP Gemini/Antigravity → `exclude_orgs` → dashboard.

## Voir aussi

- [skills-registry-migration.md](./skills-registry-migration.md) — registre `skills-registry.json`, adopt/ignore
- `zab skill hermes-update` — sync `external_dirs` Hermes uniquement
- `zab mcp serve` — exposition MCP pour tous les agents compatibles
- Skill Cursor `zab-orchestrator` — commandes CLI générales
- Skill `zab-hermes-bridge` — pont Hermes ↔ zab
