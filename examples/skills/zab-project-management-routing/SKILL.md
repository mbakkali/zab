---
name: zab-project-management-routing
description: Routage des outils de gestion de tâches (GitLab, Linear, Notion) par dépôt local — à utiliser quand l’utilisateur demande une vue globale du backlog ou « où sont mes issues ».
---

# Routage : gestion de projet par dépôt

Ce skill complète l’onglet **Tâches (multi-outils)** du dashboard zab (`GET /api/tasks/inbox`), qui lit la clé **`task_sources`** dans `~/.config/zab/config.yaml` et les jetons **`GITLAB_TOKEN`**, **`LINEAR_API_KEY`**, **`NOTION_TOKEN`** (processus ou `$ZAB_SKILLS_ROOT/.env`).

## Tableau projet → outil → règle / connexion

| Contexte | Dépôt / projet | Outil | Règle ou doc locale | Variables / MCP |
|----------|----------------|-------|---------------------|-------------------|
| Carrefour data | `danmdata` (ex. `~/projects/carrefour/danmdata`) | **GitLab** | `.cursor/rules/gitlab-project-danmdata.mdc` | `GITLAB_TOKEN` ; MCP GitLab ou CLI `glab` |
| Agile Immo | `agile-taskforce` (ex. `~/projects/agileimmo/agile-taskforce`) | **Linear** | `.cursor/rules/01-linear-agile.mdc` | `LINEAR_API_KEY` ; MCP Linear / API GraphQL |
| Perso / cowork | projets personnels | **Notion** | skills **mehdi-cowork** ou **mehdi-perso** (chemins selon votre dépôt skills) | `NOTION_TOKEN` (intégration interne) ; base Notion par `database_id` dans `task_sources` |

## Comportement agent

1. Identifier le **dossier projet** ou l’**organisation** (`carrefour`, `agileimmo`, perso).
2. Ouvrir la **règle `.mdc`** indiquée pour les URLs de groupe, boards, conventions de branches, etc.
3. Pour lister ou modifier des issues : utiliser le **MCP** correspondant (GitLab / Linear) ou Notion selon la config ; ne pas inventer d’IDs de projet.
4. Pour une **vue agrégée** sans charger tout le contexte d’une issue : privilégier le dashboard zab ou une requête API limitée (titres + liens).

## Copie dans votre dépôt skills

Ce fichier vit dans le dépôt **zab** sous `examples/skills/zab-project-management-routing/SKILL.md`. Copiez le dossier sous votre `skills_root` (ex. `orgs/flowmetrik/skills/zab-project-management-routing/SKILL.md`) et adaptez les chemins absolus si besoin.

## Exemple minimal `task_sources`

Voir le commentaire dans `~/.config/zab/config.yaml` (modèle créé par zab) ou le README du dépôt zab (section Configuration) — champs : `id`, `label`, `backend`, plus les clés spécifiques (`path_with_namespace`, `database_id`, `team_keys`, …).
