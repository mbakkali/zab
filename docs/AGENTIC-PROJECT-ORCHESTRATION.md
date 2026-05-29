---
title: Orchestration agentique de projet — Symphony, AgentPipe, load balancer CLI et zab
tags: [agents, orchestration, project-management, cursor, zab, symphony]
---

# Orchestration agentique de projet

Ce document décrit l'architecture cible pour gérer un projet logiciel avec plusieurs agents de code, tout en gardant un pilotage humain clair. L'objectif n'est pas de remplacer le chef de projet ou le développeur, mais de passer d'une supervision de terminaux agent par agent à une gestion par **chantiers**, **priorités**, **preuves de travail** et **décisions humaines**.

Le cas d'usage de référence est `danmdata`, mais le modèle est volontairement portable vers un autre projet.

## Vision

On veut construire un cockpit de développement qui répond à quatre questions :

1. **Qu'est-ce qui est en cours ?** Features, tickets, branches, conversations agents, mémoire projet.
2. **Qu'est-ce qui compte maintenant ?** Priorités métier, blocages, risques de livraison.
3. **Qui exécute quoi ?** Cursor Agent, Claude Code, Codex, Kimi, Gemini via AgentPipe, fallback API.
4. **Qu'est-ce qui prouve que c'est fini ?** Tests, lint, CI, MR, review, notes de handoff, capture ou walkthrough si besoin.

La logique est inspirée de [OpenAI Symphony](https://github.com/openai/symphony), qui présente un modèle où un système surveille un board de travail, lance des runs autonomes isolés, demande des preuves, puis aide à intégrer les changements. Ici, on adapte ce principe aux briques locales existantes : Cursor, GitLab, `zab`, AgentPipe et un load balancer CLI.

## Briques

### Symphony — modèle d'orchestration

Symphony sert de référence conceptuelle :

- un item de travail devient un **run isolé** ;
- l'agent travaille sans supervision permanente ;
- le run produit des **preuves** : tests, CI, review, analyse, walkthrough ;
- l'humain accepte, réoriente ou rejette ;
- l'intégration reste safe : branche, MR, CI, merge contrôlé.

Dans notre contexte, il n'est pas nécessaire d'adopter Symphony tel quel au départ. Le plus utile est d'en reprendre le contrat de travail : **ticket → run → preuves → décision → intégration**.

### `zab` — mémoire et contexte transverse

`zab` joue le rôle de mémoire et d'index local-first entre les outils :

- `zab memory search "requête"` retrouve les conversations Cursor / Claude / Codex / Kimi et les artefacts agents ;
- `zab memory sync-agents` resynchronise les agents locaux vers la mémoire Postgres ;
- `zab search "requête"` élargit la recherche aux skills, projets, connecteurs, politiques et mémoire ;
- `zab context-pack --project "<repo>" -q "<sujet>" --stdout` génère un pack Markdown réutilisable pour un handoff ou une reprise de contexte ;
- `zab agent` peut servir de point d'entrée pour un contrat agent / handoff projet si le workflow l'utilise.

Dans le cockpit, `zab` ne sert pas à afficher toute l'histoire : il sert à **retrouver les décisions, conversations et intentions** qui expliquent l'état actuel.

### Règle `etat-actuel-dev` — cockpit humain

La règle `.cursor/rules/etat-actuel-dev.mdc` formalise la réponse attendue quand l'utilisateur demande où il en est :

- synthèse métier d'abord ;
- priorités P0/P1 ;
- features ou chantiers en cours ;
- blocages et risques ;
- prochaines actions humaines ;
- références courtes aux sources utilisées.

Cette règle ne doit pas devenir un inventaire de fichiers. Elle transforme Git, tickets, conversations, mémoire `zab` et terminaux en **vue actionnable**.

### AgentPipe — accès aux CLIs agents

AgentPipe est la couche pratique pour appeler des agents CLI comme fournisseurs de travail :

- Gemini via AgentPipe, utile quand la configuration locale donne accès au web ou à la recherche ;
- Claude Code pour des tâches robustes de refactor, analyse ou rédaction ;
- Codex CLI pour exécution non interactive et génération de code ;
- Kimi CLI comme fournisseur additionnel, avec timeouts stricts ;
- fallback API seulement si les CLIs échouent ou sont saturés.

AgentPipe doit rester un **transport d'exécution**, pas le cerveau du pilotage. Le cerveau du pilotage est le couple ticket / run / preuve.

### Load balancer CLI — moteur d'exécution multi-agents

Le projet `upfund-crm-enricher` contient une règle réutilisable : `.cursor/rules/cli-loadbalancer-agents.mdc`. Elle définit un pattern CLI-first :

- exploiter les abonnements CLI déjà disponibles ;
- éviter l'API payante sauf fallback ;
- journaliser chaque tentative en JSONL ;
- paralléliser par item métier, pas par modèle pour le même item ;
- conserver un writer unique pour les sorties finales ;
- utiliser des timeouts par provider ;
- reprendre uniquement depuis des checkpoints validés.

Pour `danmdata`, ce pattern devient le moteur pour les tâches répétables ou parallélisables : audit de tickets, analyse de diffs, génération de tests, exploration de conversations, proposition de plans, comparaison de solutions.

### Git / GitLab — vérité de livraison

Git reste la vérité du code :

- branche courante ;
- diff local ;
- commits récents ;
- état ahead / behind ;
- stash éventuel.

GitLab devient la vérité de coordination :

- issue = intention métier ;
- MR = proposition de livraison ;
- pipeline = preuve automatisée ;
- labels / milestone = priorisation ;
- discussion MR = feedback.

Le modèle cible est simple : **un chantier important doit être rattaché à un ticket ou une MR**.

### Cursor / terminaux / transcripts

Cursor fournit deux types d'artefacts utiles :

- terminaux intégrés : état des commandes longues, serveurs, logs récents ;
- transcripts agents Cursor : contexte de conversations passées.

Ces sources sont utiles pour reprendre le fil, mais elles ne doivent pas dominer la synthèse. Elles servent à reconstruire les décisions et les intentions.

## Architecture cible

```text
                   ┌──────────────────────────┐
                   │  Humain / Product Owner  │
                   │  priorise, accepte, stop │
                   └─────────────┬────────────┘
                                 │
                                 ▼
                   ┌──────────────────────────┐
                   │ Cockpit état actuel dev  │
                   │ etat-actuel-dev + zab    │
                   └─────────────┬────────────┘
                                 │
                ┌────────────────┴────────────────┐
                ▼                                 ▼
      ┌───────────────────┐             ┌───────────────────┐
      │ Git / GitLab      │             │ Mémoire zab       │
      │ tickets, MR, CI   │             │ conv, artefacts   │
      └─────────┬─────────┘             └─────────┬─────────┘
                │                                 │
                └────────────────┬────────────────┘
                                 ▼
                   ┌──────────────────────────┐
                   │ Orchestrateur type       │
                   │ Symphony                 │
                   │ ticket → run → preuves   │
                   └─────────────┬────────────┘
                                 │
           ┌─────────────────────┼─────────────────────┐
           ▼                     ▼                     ▼
  ┌────────────────┐    ┌────────────────┐    ┌────────────────┐
  │ Cursor Agent   │    │ Claude/Codex   │    │ Load balancer  │
  │ tâche ciblée   │    │ CLI direct     │    │ AgentPipe/CLI  │
  └───────┬────────┘    └───────┬────────┘    └───────┬────────┘
          │                     │                     │
          └─────────────────────┴─────────────────────┘
                                 ▼
                   ┌──────────────────────────┐
                   │ Preuves de travail       │
                   │ tests, lint, diff, MR    │
                   └─────────────┬────────────┘
                                 ▼
                   ┌──────────────────────────┐
                   │ Décision humaine         │
                   │ merge, rework, abandon   │
                   └──────────────────────────┘
```

## Workflow opérationnel

### 1. Snapshot humain

Déclencheur : "où j'en suis sur ce projet ?", "que dois-je faire maintenant ?", "reprends le contexte".

Actions :

- interroger `zab memory search` sur le projet et les sujets probables ;
- générer un `zab context-pack` si le contexte est dispersé ;
- lire Git local et remote ;
- regarder les tickets / MR liées ;
- lire seulement les conversations récentes utiles.

Sortie attendue :

- **Priorités** ;
- **Features en cours** ;
- **Blocages / risques** ;
- **Prochaines actions** ;
- **Références courtes**.

### 2. Sélection du chantier

L'humain choisit un chantier :

- "stabiliser le déploiement UAT" ;
- "reprendre les tests E2E PPM" ;
- "finir l'extraction Docusign" ;
- "clarifier les règles Cursor / Cloud Agents".

Chaque chantier doit être formulé avec :

- objectif métier ;
- critère de done ;
- fichiers ou zones probables ;
- ticket / MR si disponible ;
- niveau de risque.

### 3. Création d'un run isolé

Pour un chantier substantiel :

- créer ou vérifier une branche dédiée ;
- idéalement créer un worktree si plusieurs agents travaillent en parallèle ;
- associer le run à un ticket ;
- préparer un prompt de travail court, avec critères de done ;
- définir les preuves attendues.

Exemple de contrat de run :

```markdown
## Run

Chantier : Stabiliser la suite E2E PPM Dataviewer
Ticket : GitLab #...
Branche : feat/e2e-ppm-stability

Objectif :
Rendre les tests PPM fiables en local et en CI, sans contourner les assertions métier.

Preuves attendues :
- `npm run test:e2e -- ppm-performance.spec.ts` passe ou produit un diagnostic clair.
- Aucun secret en log.
- Résumé des causes racines et des fixes.
- MR prête ou liste explicite des blocages.
```

### 4. Choix du moteur d'exécution

Choisir le moteur selon la nature du travail :

| Type de travail | Moteur recommandé |
|---|---|
| Synthèse, priorisation, handoff | `etat-actuel-dev` + `zab context-pack` |
| Implémentation ciblée dans Cursor | Cursor Agent |
| Audit parallèle ou comparaison de solutions | load balancer CLI |
| Extraction / enrichissement par lots | load balancer AgentPipe |
| Diagnostic complexe | Claude Code ou Cursor avec méthode debugging |
| Exécution non interactive scriptée | Codex CLI |
| Travail nécessitant web/search local | Gemini via AgentPipe |

Le load balancer doit être utilisé quand on a plusieurs items indépendants ou quand on veut résilience et traçabilité entre providers.

### 5. Exécution et journalisation

Chaque tentative agent doit produire au minimum :

- `run_id` ;
- `work_item_id` ;
- `provider` ;
- `model` si disponible ;
- `status` ;
- `duration_sec` ;
- `branch` ou `worktree` ;
- `files_changed` résumé ;
- `tests_run` ;
- `proofs` ;
- `error` si échec.

Format recommandé : JSONL append-only.

Exemple :

```json
{"run_id":"danmdata-2026-05-15-ppm-e2e","work_item_id":"gitlab-87","provider":"claude","status":"success","duration_sec":742,"branch":"feat/e2e-ppm-stability","tests_run":["npm run test:e2e -- ppm-performance.spec.ts"],"proofs":["playwright report","git diff stat"],"error":null}
```

### 6. Preuves de fin

Un run ne doit pas être marqué terminé parce que l'agent "pense" avoir fini. Il faut au moins une preuve.

Preuves possibles :

- tests passants ;
- linter sans erreur ;
- build OK ;
- pipeline GitLab vert ;
- MR ouverte avec description claire ;
- screenshot ou walkthrough pour UI ;
- résumé de risque si les tests ne peuvent pas être lancés.

Pour `danmdata`, exemples :

- backend Python : `ruff check .`, pytest ciblé ;
- frontend Dataviewer : lint / typecheck / Playwright selon la zone ;
- déploiement : logs Cloud Run / Cloud Build, sans écrire en PRD ;
- BigQuery : requêtes UAT validées, PRD lecture seule.

### 7. Handoff et mémoire

À la fin du run :

- résumer le résultat en français ;
- citer ticket, branche, MR, tests ;
- indiquer ce qui reste à décider humainement ;
- pousser le résumé dans le canal de mémoire utilisé par l'équipe si disponible ;
- relancer `zab memory sync-agents` si nécessaire pour rendre le contexte retrouvable.

Un handoff utile doit permettre de reprendre le lendemain sans rouvrir dix terminaux.

## Application à `danmdata`

### Chantiers typiques

| Chantier | Pilotage | Exécution |
|---|---|---|
| Dataviewer frontend | Ticket GitLab + tests Playwright | Cursor Agent ou Claude Code |
| Backend FastAPI | pytest + ruff + logs Cloud Run | Cursor Agent |
| Pipelines Docusign / Eskare | preuve extraction + BigQuery UAT | Agent dédié ou load balancer pour audits |
| Déploiement Cloud Run | checklist deploy + logs | Cursor Agent, jamais écriture PRD |
| Règles / docs Cursor | doc + validation humaine | Cursor Agent |
| Reprise de contexte | `zab memory search` + Git + transcripts | `etat-actuel-dev` |

### Exemple de journée

1. Demander : "fais l'état métier de `danmdata`".
2. Le cockpit identifie :
   - P0 : finaliser le correctif déploiement UAT ;
   - P1 : stabiliser E2E PPM ;
   - P2 : documenter orchestration agentique.
3. L'humain choisit P0.
4. L'orchestrateur crée ou réutilise le ticket GitLab.
5. Un run isolé part sur une branche dédiée.
6. L'agent corrige et produit preuves.
7. L'humain accepte ou demande rework.
8. Le handoff est enregistré via `zab`.

## Règles de sécurité et de contrôle

- Ne jamais lancer des agents qui modifient la PRD Carrefour.
- Ne jamais exposer `.env`, clés JSON, tokens GitLab, clés API dans les prompts ou logs.
- Ne jamais force-push sans demande explicite.
- Ne jamais considérer un run comme fini sans preuve.
- Ne pas lancer plusieurs agents sur le même fichier sans isolation par branche / worktree.
- Garder l'humain responsable des décisions : priorité, merge, abandon, arbitrage métier.

## Portage vers un autre projet

Pour reprendre cette approche ailleurs :

1. Créer une règle ou doc locale "état actuel du dev" avec les sources du projet.
2. Brancher `zab` sur les conversations et artefacts agents du projet.
3. Définir le gestionnaire de tickets : GitLab, Linear, GitHub Issues, Notion.
4. Définir les preuves par stack : tests, lint, build, CI, screenshots.
5. Adapter le load balancer CLI : providers disponibles, timeouts, checkpoints, logs.
6. Choisir une stratégie d'isolation : branche simple, worktree, clone temporaire, cloud agent.
7. Standardiser le format de handoff.

## Livrable cible minimal

Un premier MVP doit suffire :

- une commande ou prompt "état métier du projet" ;
- une convention "1 chantier = 1 ticket = 1 branche = 1 run" ;
- un JSONL de runs ;
- une synthèse de fin obligatoire ;
- une preuve minimale par type de chantier ;
- une synchronisation régulière vers `zab`.

Le reste peut venir ensuite : dashboard, intégration GitLab complète, notifications, vidéos walkthrough, score de complexité, auto-merge conditionnel.

## Décision proposée

Pour `danmdata`, la bonne trajectoire est :

1. Garder `etat-actuel-dev.mdc` comme interface de **pilotage humain**.
2. Réutiliser le load balancer CLI pour les chantiers parallèles et répétables.
3. Utiliser Symphony comme **référence d'architecture**, pas comme dépendance obligatoire immédiate.
4. Faire de `zab` la mémoire transverse officielle.
5. Formaliser chaque run avec preuves avant merge ou livraison.

Cette approche donne un système réaliste : assez structuré pour piloter plusieurs agents, mais encore local-first et compatible avec les contraintes de `danmdata`.
