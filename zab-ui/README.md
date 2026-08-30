# zab-ui — le dashboard

React + TypeScript + Vite, bâti sur le socle **flowmetrik-whiteapp**
(`~/projects/flowmetrik-whiteapp`, `github.com/flowmetrik/flowmetrik-whiteapp`).

## La charte n'est pas dans ce dépôt

`src/styles/tokens.css` est **généré** depuis
`flowmetrik-cowork/assets/brand/tokens/` :

```bash
npm run tokens            # régénère
npm run tokens -- --check # échoue si le fichier a été édité à la main
```

Une couleur se corrige dans la charte, jamais ici. Deux conséquences :

- **`assets/brand/dist/` n'est pas synchronisé** entre le Mac et la VM.
  Reconstruire d'abord — `python3 assets/tools/build_css.py` dans le cowork —
  sinon `sync_tokens.py` lit un CSS absent ou périmé et les couleurs sortent
  fausses sans que rien ne le dise.
- Aucune classe de palette Tailwind (`bg-zinc-100`, `text-emerald-700`) ne doit
  réapparaître. Le contrôle :

```bash
python3 ~/projects/flowmetrik-whiteapp/scripts/audit_migration.py .
```

Il doit rendre « 0 occurrences ». Le seul hex admis hors `styles/` est le teal
Dashlane : une marque tierce désigne un service, pas une intention de design.

## Le vocabulaire

| Rôle | Classe |
|---|---|
| surfaces | `bg-background`, `bg-card`, `bg-muted`, `bg-secondary` |
| encre | `text-foreground`, `text-muted-foreground` |
| aplat fort | `bg-primary` + `text-primary-foreground` |
| statut | `bg-succes/10 text-succes`, idem `alerte`, `danger`, `info` |
| filets | `border-border`, `ring-ring/40` |

**Un statut se nomme par son sens, jamais par sa teinte.** `emerald` se renomme
le jour où la charte change de vert ; `succes`, non.

**Pas de variante `dark:` sur une couleur de charte.** Les tokens basculent
seuls avec le thème ; en ajouter une produit deux règles concurrentes dont la
seconde gagne, au hasard de l'ordre de compilation.

**Une teinte sans état est une faute.** Un compteur « Plugins : 0 » peint en
vert annonce un succès qui n'existe pas. Décoratif ⇒ `bg-muted`.

`scripts/migration_charte.py` a fait la bascule de 1 424 occurrences le
2026-08-30. Il est gardé pour que la transformation reste relisible ; il n'a
pas vocation à resservir.

## Servir le dashboard — Mac comme VM

`zab dashboard` sert cette application **si elle est construite**, et c'est là
que ça se joue. `zab_ui_dist_dir()` cherche dans l'ordre :

1. `$ZAB_UI_DIST` ;
2. le dossier frère `<dépôt zab>/zab-ui/dist` ;
3. le `ui_dist` empaqueté dans le wheel.

**Piège, identique sur les deux machines :** quand `zab` est installé en outil
uv (`~/.local/share/uv/tools/zab`), le point 2 pointe vers `site-packages` et ne
trouve rien, et le point 3 n'existe pas dans ce wheel. Le dashboard sert alors
son API et **une page blanche**, sans une erreur. `dist/` n'étant pas
synchronisé entre le Mac et la VM, chaque machine doit le construire.

```bash
npm ci && npm run build
ZAB_UI_DIST="$PWD/dist" zab dashboard --port 8742 --no-open
```

Sur la VM, c'est ce que fait l'entrée `zab` de
`flowmetrik-cowork/deploy/flowhub/apps.yaml` :

- tailnet `https://cowork-linux.tailef30ea.ts.net:8464/`
- nom : `https://zab.cowork.flowmetrik.com/`
- service : `flowapp-zab.service`

`public: false`, et c'est une décision : le dashboard expose la configuration,
les journaux et les noms de variables du coffre. L'appartenance au tailnet tient
lieu d'authentification.

## Avant de livrer

```bash
npm run tokens -- --check
npm run build          # compile aussi les types
npm run lint
```

react-doctor reste à **38/100** sur cet arbre : composants géants, dépendances
d'effet, accessibilité. C'est de la dette antérieure à la migration de charte —
le score était identique avant — et un chantier distinct.
