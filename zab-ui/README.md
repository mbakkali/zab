# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend updating the configuration to enable type-aware lint rules:

```js
export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...

      // Remove tseslint.configs.recommended and replace with this
      tseslint.configs.recommendedTypeChecked,
      // Alternatively, use this for stricter rules
      tseslint.configs.strictTypeChecked,
      // Optionally, add this for stylistic rules
      tseslint.configs.stylisticTypeChecked,

      // Other configs...
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```

You can also install [eslint-plugin-react-x](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-x) and [eslint-plugin-react-dom](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-dom) for React-specific lint rules:

```js
// eslint.config.js
import reactX from 'eslint-plugin-react-x'
import reactDom from 'eslint-plugin-react-dom'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...
      // Enable lint rules for React
      reactX.configs['recommended-typescript'],
      // Enable lint rules for React DOM
      reactDom.configs.recommended,
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```

## Onglet Skills (registre)

- Fichier source : `~/.config/zab/skills-registry.json` (voir `docs/skills-registry-migration.md` à la racine du dépôt zab).
- Onglets **Adoptées / Candidats / Ignorées / Conflits / Toutes** filtrent l’index API (`GET /api/skills?status=…`).
- **Mettre à jour Hermes** envoie `POST /api/skills/hermes-update` avec `{ "apply": true }` ; **Copier fragment Hermes** appelle `POST /api/skills/hermes-export` et place le YAML dans le presse-papiers.

## Tests Playwright (dashboard Zab)

Depuis `zab-ui`, après build :

```bash
npm run build && npx playwright test
```

Le serveur API + assets statiques est démarré via `scripts/zab-e2e-dashboard.sh` (port `18742` par défaut, surcharge avec `ZAB_E2E_PORT`).

### Cibler une instance déjà déployée (prod / préprod)

Sans lancer le serveur local :

```bash
PLAYWRIGHT_BASE_URL=https://votre-hote-zab npm run build && npx playwright test
```

Les scénarios **recherche conversations / détail / filtre provider** nécessitent Postgres configuré (`MEHDI_MEMORY_DATABASE_URL`) et des données synchronisées ; sinon ils sont ignorés (`test.skip`). Pour forcer un terme de recherche : `PLAYWRIGHT_CONVERSATIONS_SEARCH_TERM="..."`.

Dry-run sync long (optionnel) : `PLAYWRIGHT_CONVERSATIONS_JOB=dry-run`.
