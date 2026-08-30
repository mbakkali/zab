#!/usr/bin/env python3
"""Régénère `src/styles/tokens.css` depuis les tokens de charte.

Source de vérité : `flowmetrik-cowork/assets/brand/tokens/` — jamais ce fichier.
La whiteapp ne redéfinit aucune couleur : elle en **traduit** les rôles vers le
vocabulaire attendu par shadcn (`--background`, `--primary`, `--border`…), pour
qu'un `npx shadcn add <composant>` tombe juste sans retouche.

    python3 scripts/sync_tokens.py [--check]

`--check` échoue si le fichier sur disque diffère — c'est la gate qui empêche
qu'on édite la traduction à la main et qu'elle dérive de la charte.

Trois choses ne se devinent pas :

- le CSS de charte n'est **pas** synchronisé (`dist/` est exclu du miroir) : ce
  script le reconstruit d'abord, sinon il lit un fichier absent ou périmé ;
- shadcn raisonne en paires `X` / `X-foreground`. La charte, elle, nomme des
  rôles (`surface.raised`, `text.primary`). La table `BRIDGE` ci-dessous est
  cette traduction, et c'est le seul endroit où elle existe ;
- le thème sombre n'est pas dans la charte, qui ne décrit que le papier. Les
  valeurs sombres viennent de flowstart, qui les avait mesurées.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
ASSETS = pathlib.Path.home() / "projects" / "flowmetrik-cowork" / "assets"
OUT = REPO / "src" / "styles" / "tokens.css"

# --- La traduction charte → shadcn. Le seul endroit où elle vit. ---------------
# clé shadcn : (variable de charte en clair, valeur en sombre)
# Le sombre est repris de flowstart, où il avait été mesuré contre l'encre #0B0B0C.
BRIDGE: dict[str, tuple[str, str]] = {
    "background":            ("var(--color-surface-sunken)", "#0B0B0C"),
    "foreground":            ("var(--color-text-primary)",   "#F2F2F2"),
    "card":                  ("var(--color-surface-raised)", "#141416"),
    "card-foreground":       ("var(--color-text-primary)",   "#F2F2F2"),
    "popover":               ("var(--color-surface-raised)", "#1A1A1D"),
    "popover-foreground":    ("var(--color-text-primary)",   "#F2F2F2"),
    # `primary` est un RÔLE d'emphase maximale, pas une teinte : encre sur
    # papier, papier sur encre. Reprise de la décision flowstart du 20/07/2026.
    "primary":               ("var(--color-text-primary)",   "#FFFFFF"),
    "primary-foreground":    ("var(--color-surface-page)",   "#111112"),
    "secondary":             ("var(--color-surface-sunken)", "#1A1A1D"),
    "secondary-foreground":  ("var(--color-text-primary)",   "#F2F2F2"),
    "muted":                 ("var(--color-surface-sunken)", "#1A1A1D"),
    "muted-foreground":      ("var(--color-text-muted)",     "#8A8A90"),
    # `accent` au sens shadcn est la surface de survol, PAS l'accent de filiale.
    # Les confondre peindrait tous les survols en jaune FlowImmo.
    "accent":                ("var(--color-surface-sunken)", "#212124"),
    "accent-foreground":     ("var(--color-text-primary)",   "#F2F2F2"),
    "destructive":           ("var(--color-signal-danger)",  "#FF8080"),
    "destructive-foreground":("var(--color-surface-page)",   "#111112"),
    "border":                ("var(--color-border-hairline)","rgba(255,255,255,0.12)"),
    "input":                 ("var(--color-border-hairline)","rgba(255,255,255,0.18)"),
    "ring":                  ("var(--color-focus)",          "#FFFFFF"),
    "sidebar":               ("var(--color-surface-sunken)", "#0F0F11"),
    "sidebar-foreground":    ("var(--color-text-secondary)", "#C7C7CC"),
    "sidebar-primary":       ("var(--color-text-primary)",   "#FFFFFF"),
    "sidebar-primary-foreground": ("var(--color-surface-page)", "#111112"),
    "sidebar-accent":        ("var(--color-surface-page)",   "#1A1A1D"),
    "sidebar-accent-foreground":  ("var(--color-text-primary)", "#F2F2F2"),
    "sidebar-border":        ("var(--color-border-hairline)","rgba(255,255,255,0.10)"),
    "sidebar-ring":          ("var(--color-focus)",          "#FFFFFF"),
}

# Les statuts ne s'inversent pas : sur fond sombre un vert à 4.5:1 sur papier
# tombe sous le seuil. Les valeurs sombres sont les `accentOnDark` de la charte.
SIGNALS = {
    "success": ("var(--color-signal-success)", "#4FD69B"),
    "warning": ("var(--color-signal-warning)", "#E3B341"),
    "danger":  ("var(--color-signal-danger)",  "#FF8080"),
    "info":    ("var(--color-signal-info)",    "#6FA1FF"),
}


def charte_css() -> str:
    """Le CSS de charte, reconstruit d'abord : `dist/` n'arrive pas par la synchro."""
    build = ASSETS / "tools" / "build_css.py"
    if not build.exists():
        sys.exit(f"charte introuvable : {build}\n"
                 "La whiteapp se construit à côté du cowork, pas sans lui.")
    subprocess.run([sys.executable, str(build)], check=True, capture_output=True)
    return (ASSETS / "brand" / "dist" / "flowmetrik.css").read_text(encoding="utf-8")


def bloc(nom: str, paires: list[tuple[str, str]], indent: str = "  ") -> str:
    return "\n".join(f"{indent}--{k}: {v};" for k, v in paires)


def rendre() -> str:
    src = charte_css()
    # On garde le `:root` de la charte tel quel — traçable, diffable, non retouché.
    root = re.search(r":root \{\n(.*?)\n\}", src, re.S)
    if not root:
        sys.exit("le CSS de charte n'expose pas de :root — build_css.py a changé de forme")
    unites = re.findall(r'/\* (\w+) — .*?\*/\n\[data-unit="([\w-]+)"\] \{\n(.*?)\n\}', src, re.S)

    clair = bloc("light", [(k, v[0]) for k, v in BRIDGE.items()]
                 + [(f"signal-{k}", v[0]) for k, v in SIGNALS.items()])
    sombre = bloc("dark", [(k, v[1]) for k, v in BRIDGE.items()]
                  + [(f"signal-{k}", v[1]) for k, v in SIGNALS.items()])

    unites_css = "\n\n".join(
        f'/* {nom} */\n[data-unit="{slug}"] {{\n{corps}\n}}'
        for nom, slug, corps in unites)

    return f"""/* ============================================================
   Whiteapp Flowmetrik — CSS GÉNÉRÉ. Ne pas éditer à la main.
   Source     : flowmetrik-cowork/assets/brand/tokens/
   Générateur : scripts/sync_tokens.py
   Gate       : python3 scripts/sync_tokens.py --check

   Trois couches, dans cet ordre :
     1. les variables de charte, recopiées sans retouche depuis le CSS généré ;
     2. la traduction vers le vocabulaire shadcn — la seule chose inventée ici ;
     3. les accents de filiale, qui ne surchargent QUE des accents.
   ============================================================ */

/* --- 1. Charte, verbatim ------------------------------------------------- */
:root {{
{root.group(1)}
}}

/* --- 2. Traduction vers shadcn ------------------------------------------- */
/* shadcn raisonne en paires surface / `-foreground`. La charte nomme des rôles.
   Cette table est le pont : elle laisse `npx shadcn add <x>` tomber juste. */
:root, .light {{
  --radius: var(--radius-soft);
{clair}
}}

.dark {{
{sombre}
}}

/* --- 3. Filiales : un data-unit ne surcharge QUE les accents -------------- */
{unites_css}

/* Le mode `operate` est le défaut d'une application : densité forte, rayon 6px. */
:root {{
  --mode-radius-control: 6px;
  --mode-radius-container: 6px;
  --mode-radius-badge: 999px;
  --mode-density-sectionGap: 32px;
  --mode-density-blockGap: 16px;
  --mode-density-controlPadY: 9px;
  --mode-density-controlPadX: 14px;
  --mode-motion-interaction: 120ms;
  --mode-motion-entrance: 220ms;
}}
"""


def main() -> None:
    css = rendre()
    check = "--check" in sys.argv
    if check:
        actuel = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if actuel != css:
            sys.exit("tokens.css diverge de la charte — lancer `pnpm tokens`")
        print("OK — tokens.css est à jour.")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(css, encoding="utf-8")
    n = len(re.findall(r"^\s+--", css, re.M))
    print(f"OK — {OUT.relative_to(REPO)} : {n} variables.")


if __name__ == "__main__":
    main()
