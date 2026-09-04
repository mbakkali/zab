# Zab sur deux machines

Zab tourne souvent sur deux machines — un poste de travail et une VM — avec le
même code et la même configuration. Jusqu'au 2026-09-04, il tenait aussi **deux magasins
séparés** : chaque machine écrivait son Conversation Ledger dans un SQLite
local que l'autre ne voyait pas. Une interaction relevée sur le Mac n'existait
pas pour la VM, et inversement.

Depuis, le ledger vit dans Postgres, dans un schéma par machine, réunis par des
vues en lecture. Ce document dit ce qui est commun, ce qui reste propre à
chaque machine, et comment brancher une machine neuve.

## Une base, un schéma par machine

Une seule base Postgres, et **trois familles de schémas** :

| Schéma | Contenu | Écriture |
|---|---|---|
| `zab_core` | Registres, état, tâches, méta, inventaires. Commun. | toutes les machines |
| `zab_mac`, `zab_vm`, … | Le Conversation Ledger de **cette** machine. | la machine seule |
| `zab_all` | Des vues qui font l'union de tous les schémas de machine. | **lecture seule** |

Le ledger est rangé par machine plutôt que mélangé. Deux zab écrivent alors
sans jamais se marcher dessus, et l'origine d'une ligne se lit dans son
emplacement — pas dans une colonne qu'on oublierait de remplir. Ce qu'on y perd,
la vue d'ensemble, revient par `zab_all`, dont chaque vue ajoute une colonne
`device` : sans elle, deux lignes venues de machines différentes seraient
indiscernables une fois réunies.

Le nom du schéma vient du **genre** de la machine (`mac`, `vm`), pas de son nom
d'hôte : un Mac renommé reste un Mac, là où des schémas nommés d'après des
hôtes changeants laisseraient un orphelin derrière chaque renommage. Une
machine qui n'est ni l'un ni l'autre retombe sur son nom d'hôte, assaini.
`ZAB_LEDGER_SCHEMA` force le choix.

```bash
zab db status --json | jq '{database, machine, shared, ledger}'
zab ledger db                       # moteur, schéma, comptes, autres machines
```

`machine` dit quelle machine répond. Sans lui, deux sorties côte à côte sont
indiscernables, et on répare la mauvaise.

## Lire une machine, ou toutes

Par défaut, une lecture ne voit que le schéma de la machine courante. Les
commandes et routes de lecture acceptent `--all-devices` (`all_devices=true`
côté API), qui bascule sur les vues de `zab_all` :

```bash
zab workpacket list                       # ce que cette machine a produit
zab workpacket list --all-devices         # les deux machines
zab interactions timeline --all-devices
```

Une écriture en portée `all` échoue : une vue d'union n'est pas modifiable, et
c'est voulu — mieux vaut une erreur bruyante qu'une ligne écrite silencieusement
dans le mauvais schéma.

## Ce qui reste propre à chaque machine

Tout ce qui décrit **où en est cette machine**, jamais la donnée elle-même.

| Quoi | Pourquoi ce n'est pas partagé |
|---|---|
| Le ledger lui-même (`zab_<machine>`) | Chaque machine écrit dans son schéma. `zab_all` les réunit en lecture. |
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

3. **Les schémas** — `zab db migrate` pour le commun, puis n'importe quelle
   commande du ledger crée le schéma de la machine et régénère les vues
   d'union. Tout est idempotent. Si un ledger traîne encore dans le schéma
   commun (état d'avant le rangement par machine) :

   ```bash
   zab ledger migrate-schema          # simulation
   zab ledger migrate-schema --apply  # copie vers le schéma de la machine
   ```

   Les tables d'origine sont laissées en place ; les vider est une décision
   séparée, une fois la bascule vérifiée.

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
