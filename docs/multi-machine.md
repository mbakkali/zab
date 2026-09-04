# Zab sur deux machines

Zab tourne souvent sur deux machines — un poste de travail et une VM — avec le
même code et la même configuration. Jusqu'au 2026-09-04, il tenait aussi **deux magasins
séparés** : chaque machine écrivait son Conversation Ledger dans un SQLite
local que l'autre ne voyait pas. Une interaction relevée sur le Mac n'existait
pas pour la VM, et inversement.

Depuis, le ledger vit dans Postgres, partagé. Ce document dit ce qui est
commun, ce qui reste propre à chaque machine, et comment brancher une machine
neuve.

## Ce qui est partagé

Tout ce qui est une **donnée** : les interactions (`ledger_events`), les work
packets, les organisations, les chantiers, l'état, les registres, les tâches.
Une seule base Postgres, schéma `zab_core`, sur une instance partagée.

```bash
zab db status --json | jq '{database, machine, shared, schema, ok}'
```

`machine` dit quelle machine répond. Sans lui, deux sorties côte à côte sont
indiscernables, et on répare la mauvaise.

## Ce qui reste propre à chaque machine

Tout ce qui décrit **où en est cette machine**, jamais la donnée elle-même.

| Quoi | Pourquoi ce n'est pas partagé |
|---|---|
| Curseurs de synchronisation (`ledger.source_cursors.<machine>`) | Le Mac lit iMessage, la VM ne peut pas. Un curseur commun ferait croire à chacun que l'autre a déjà tout lu, et les messages arrivés entre-temps seraient sautés. |
| Journal `events-<machine>.jsonl` | Trace d'appoint, rejouable. Un seul fichier partagé mêlerait deux flux d'écriture que rien ne réconcilierait. |
| Inventaire des clés (`security.inventory.<machine>`) | Une clé n'existe pas au même endroit des deux côtés. C'est justement la question à laquelle il faut pouvoir répondre. |
| Sessions OAuth, trousseau, coffres `.env` | Propres à la machine par nature. |

```bash
zab ledger cursors                      # ici
zab ledger cursors --machine <autre-machine>  # là-bas
zab security machines                   # quelle clé vit où
```

## Brancher une machine

1. **L'accès à la base.** Si elle est derrière un proxy — Cloud SQL ou autre —
   zab ne le lance pas et n'en sait rien : il ne connaît qu'un DSN. Il faut
   donc que le proxy écoute en local (`127.0.0.1:5432` par convention), lancé
   par un service au démarrage.

2. **Le DSN**, dans `~/.config/zab/.env` :

   ```
   ZAB_MEMORY_DATABASE_URL=postgresql://<utilisateur>:<mot de passe>@127.0.0.1:5432/zab
   ```

   Sans DSN, zab **ne casse pas** : il retombe sur le SQLite local, comme le
   fait déjà le reste du magasin. C'est utile pour une machine qui n'a pas
   encore son proxy — mais elle travaille alors seule, et
   `zab db status` le dit (`shared: false`).

3. **Le schéma** — `zab db migrate`. Il est idempotent.

4. **La reprise du SQLite local**, s'il y en a un :

   ```bash
   zab ledger import-sqlite          # simulation
   zab ledger import-sqlite --apply  # écrit, y compris les curseurs
   ```

   Rien n'est supprimé côté SQLite : le fichier reste la sauvegarde tant que
   la bascule n'est pas prouvée.

5. **Le registre de connecteurs**, si l'organisation en a un — clé
   `connectors_registry` dans `~/.config/zab/config.yaml`. Il donne à
   `zab security status` la liste des variables attendues et les coffres où
   les chercher. Puis :

   ```bash
   zab security scan
   ```

## Deux pièges

**`systemctl is-active` ne prouve rien.** Un proxy Cloud SQL affiche
« ready for new connections » même sans aucun droit ; le refus n'arrive qu'à la
première connexion réelle. Seul `zab db status` tranche.

**Les sources qui n'existent que d'un côté ne sont pas des pannes.**
`zab.services.machine` liste ce qui ne peut pas fonctionner ici — iMessage et
le carnet Apple hors macOS. Un canal rouge pour cette raison n'appelle aucune
réparation. Depuis le 2026-09-04, un canal réellement en échec écrit sa raison
et son compte d'échecs consécutifs dans son curseur : c'est ce qui permet de
répondre à « depuis quand ce canal ne remonte plus rien », sans rejouer une
synchronisation.
