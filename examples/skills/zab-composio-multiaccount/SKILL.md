---
name: zab-composio-multiaccount
description: Guide d'utilisation de Composio via ZAB quand plusieurs comptes du même toolkit sont connectés (ex. Gmail ×3). Privilégie le CLI Composio natif pour l'exécution ; utilise ZAB pour la découverte, le routage et l'itération multi-comptes.
tags: [composio, multi-account, gmail, connectors, discovery]
uses_connectors: [composio]
uses_code_tools: [composio]
---

# ZAB + Composio : Multi-compte & Discovery

## Philosophie : ZAB guide, Composio exécute

ZAB n'est **pas** un remplacement du CLI Composio. Il est un **middleware de discovery** qui te dit :
- Quels comptes sont disponibles
- Quel compte correspond à quel email / domaine
- Comment itérer sur plusieurs comptes quand tu ne sais pas où chercher

**Règle d'or** : pour exécuter un tool une fois que tu sais lequel et sur quel compte → utilise `composio execute` directement.  
Pour découvrir, router, ou balayer plusieurs comptes → utilise `zab composio …`.

---

## 1. Découverte des comptes

### Lister les comptes avec leurs identités
```bash
# ZAB — affiche les comptes avec email résolu quand possible
zab composio connections --toolkit gmail --active

# Composio natif — brut, sans mapping email
composio connections list
```

### Identifier un compte inconnu (whoami)
Quand plusieurs comptes ont des noms opaques (`gmail_dun-bound`, `gmail_betail-apse`) :
```bash
# ZAB — exécute un tool léger pour récupérer l'email associé
zab composio whoami --toolkit gmail --account gmail_dun-bound
zab composio whoami --toolkit gmail --account gmail_betail-apse
```
Résultat typique :
```json
{
  "account": "gmail_dun-bound",
  "email": "user@example.com",
  "method": "GMAIL_FETCH_EMAILS"
}
```

---

## 2. Routage multi-comptes

### Scénario : "Dans quel Gmail est ce mail ?"

**Mauvais** (manuel, lent) :
```bash
composio execute GMAIL_FETCH_EMAILS -d '{"query": "from:orange"}' --account gmail_piend-damara
composio execute GMAIL_FETCH_EMAILS -d '{"query": "from:orange"}' --account gmail_dun-bound
composio execute GMAIL_FETCH_EMAILS -d '{"query": "from:orange"}' --account gmail_betail-apse
```

**Bon** (ZAB itère pour toi) :
```bash
zab composio execute GMAIL_FETCH_EMAILS \
  --toolkit gmail \
  --all-accounts \
  -d '{"query": "from:orange", "max_results": 5}'
```

Résultat : un tableau JSON avec, pour chaque compte, soit les données, soit `"error": "no_match"` / `"error": "account_failed"`.

### Scénario : "Liste les derniers mails de chaque compte"
```bash
zab composio gmail last --limit 3
```

---

## 3. Helpers Gmail spécifiques

```bash
# Liste tous les comptes Gmail avec email résolu
zab composio gmail accounts

# Recherche un query Gmail sur tous les comptes (query = argument positionnel)
zab composio gmail search "from:hubspot subject:invoice" --limit 5

# Derniers messages par compte
zab composio gmail last --limit 5 --account gmail_piend-damara
```

---

## 4. Résolution d'identité — stratégie de l'agent

Quand l'utilisateur mentionne un email (ex. `user@example.com`) et que tu ne sais pas quel compte Composio l'héberge :

1. **Vérifie le state ZAB** : `zab inspect connectors gmail --json` → regarde `agent_hints.accounts`
2. **Si l'email est connu** → utilise directement `composio execute … --account <word_id>`
3. **Si l'email est inconnu / manquant** → `zab composio whoami --toolkit gmail` sur chaque compte inconnu
4. **Mets à jour ton contexte** : note le mapping `word_id → email` pour la suite de la conversation

---

## 5. Asymétrie API REST vs CLI (bloquant connu)

| Méthode | Multi-compte ? | Quand l'utiliser |
|---------|---------------|------------------|
| `zab composio call <SLUG>` (REST) | ❌ Non — ne voit pas les comptes consumer | Jamais pour les comptes Gmail actuels |
| `zab composio execute <SLUG>` (CLI passthrough) | ✅ Oui — `--account` fonctionne | Exécution ciblée d'un tool |
| `zab composio execute --all-accounts` | ✅ Itération auto | Recherche / balayage multi-compte |
| `composio execute <SLUG> --account <id>` | ✅ Oui | Quand tu connais déjà le compte (préférable) |

> **Note** : La REST Composio ne voit pas les comptes liés en mode "consumer". Le seul moyen fiable est le CLI local. ZAB encapsule cette complexité.

---

## 6. Anti-patterns à éviter

- **Ne pas** réimplémenter la logique Composio dans ZAB (pas de parsing d'IMAP, pas de refresh token manuel).
- **Ne pas** exécuter un tool sur un compte au hasard sans vérifier l'identité quand l'utilisateur mentionne un email spécifique.
- **Ne pas** proposer à l'utilisateur de "choisir parmi 3 comptes" si ZAB peut `whoami` ou itérer `--all-accounts` à sa place.
