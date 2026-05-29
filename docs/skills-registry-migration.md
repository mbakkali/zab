# Migration vers `skills-registry.json`

Zab utilise désormais **`~/.config/zab/skills-registry.json`** comme inventaire unique des skills (statuts `candidate`, `adopted`, `mirrored`, `published`, `ignored`, `conflict`). L’ancienne clé YAML `skill_md_paths` est **obsolète** : au premier accès au registre, les chemins legacy sont importés puis la clé est retirée de `~/.config/zab/config.yaml` (sauvegarde horodatée possible).

## Rollback rapide

1. Arrêter les processus zab / dashboard.
2. Restaurer `config.yaml` depuis une sauvegarde `config.yaml.bak.<timestamp>` (créée lors du retrait de `skill_md_paths` si migration avec backup).
3. Supprimer ou renommer `~/.config/zab/skills-registry.json` si vous voulez forcer une nouvelle migration depuis le YAML restauré.

## Hermes

L’écriture de `~/.hermes/config.yaml` n’est plus implicite dans tous les flux : utilisez **`zab skill hermes-update --apply`**, l’API `POST /api/skills/hermes-update` avec `{"apply": true}`, ou activez `skills_sync.auto_hermes_update: true` pour l’auto-sync. Sinon, copiez le fragment renvoyé par **`zab skill hermes-export`** ou `POST /api/skills/hermes-export`.

## Broadcast cross-CLI (Claude, Kimi)

Pour exposer le même inventaire que Hermes vers **Claude Code** (symlinks) et **Kimi** (`extra_skill_dirs`), voir **[skills-broadcast.md](./skills-broadcast.md)** (`zab skill broadcast --apply`). Distinct du registre : le broadcast ne modifie pas `skills-registry.json`.

## CLI utile

- `zab skill registry-show [--status adopted]`
- `zab skill adopt <org:slug> [--canonical PATH]`
- `zab skill unadopt / ignore / unignore <org:slug>`
- `zab skill resolve-conflict <org:slug> --keep /abs/path/SKILL.md`

## Journal

Un log append-only peut être écrit sous `~/.local/share/zab/skills-registry-migration.log` lors du strip YAML.
