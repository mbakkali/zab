#!/usr/bin/env python3
"""Traduit les classes de palette Tailwind de zab-ui vers les tokens de charte.

    python3 scripts/migration_charte.py            # le plan, rien d'écrit
    python3 scripts/migration_charte.py --apply

Script **d'un seul usage**, gardé pour que la transformation de ~1 400
occurrences reste relisible. Il n'est pas dans la boucle de build : une fois la
migration faite, c'est `audit_migration.py` de la whiteapp qui vérifie qu'on
n'a pas régressé.

Trois principes portent tout le fichier :

1. **On ne réécrit QUE l'intérieur des chaînes de classes.** Un premier jet
   appliquait ses expressions régulières au fichier entier, dont un nettoyage
   d'espaces après guillemet — il a mangé des sauts de ligne et collé
   `'sync_secrets'function DashlaneLogo()`. Le code ne compilait plus. Depuis :
   on isole la chaîne, on la retraite entière, on la repose. Rien hors des
   guillemets n'est touché.

2. **Un token sémantique bascule tout seul en sombre.** `bg-succes/10` est
   correct dans les deux thèmes. Une paire `bg-emerald-50 dark:bg-emerald-950`
   ne devient donc pas deux classes : la variante `dark:` est **supprimée**.

3. **Un statut se nomme par son sens, jamais par sa teinte.** `emerald` devient
   `succes` : le jour où la charte change la couleur, rien à réécrire.
"""

from __future__ import annotations

import pathlib
import re
import sys

RACINE = pathlib.Path(__file__).resolve().parent.parent / "src"

SENS = {
    "succes": ("emerald", "green", "teal", "lime"),
    "alerte": ("amber", "yellow", "orange"),
    "danger": ("red", "rose"),
    "info": ("sky", "blue", "indigo", "cyan"),
}
NEUTRES = ("zinc", "slate", "gray", "neutral", "stone")
# Ni statut ni neutre : elles servaient aux pastilles de connecteurs, où la
# couleur reprenait la marque du service. Elles rejoignent le neutre — l'icône
# identifie déjà le service, et la charte plafonne l'accent à ~5 % de surface.
CATEGORIELLES = ("violet", "purple", "fuchsia", "pink")

TEINTE_VERS_SENS = {t: s for s, teintes in SENS.items() for t in teintes}
PALETTES = NEUTRES + CATEGORIELLES + tuple(TEINTE_VERS_SENS)

JETON = re.compile(
    r"^((?:[a-z][\w-]*:)*)"                       # variantes : dark:, hover:…
    r"(bg|text|border|ring|divide|outline|fill|stroke|from|via|to|shadow)-"
    rf"({'|'.join(PALETTES)})-(\d{{2,3}})(/\d+)?$"
)

LITTERALES = {
    "bg-white": "bg-card",
    "bg-black": "bg-foreground",
    "text-black": "text-foreground",
    "hover:bg-white": "hover:bg-muted",
    "text-white/65": "text-primary-foreground/65",
    "dark:bg-white": "",
    "dark:bg-black": "",
    "dark:text-white": "",
    "dark:text-black": "",
    "dark:hover:bg-white": "",
}


def cible(prefixe: str, teinte: str, niveau: int) -> str | None:
    """La classe de charte qui remplace `<prefixe>-<teinte>-<niveau>`."""
    if teinte in NEUTRES or teinte in CATEGORIELLES:
        if prefixe == "text":
            return "text-foreground" if niveau >= 700 else "text-muted-foreground"
        if prefixe == "bg":
            # ≥ 800, c'est une surface ENCRE, pas un gris clair : `bg-zinc-900
            # text-white` est la pastille GitHub. La rendre en `bg-secondary`
            # donnerait du blanc sur gris clair — illisible, et invisible à
            # tout test qui ne regarde pas l'écran.
            if niveau >= 800:
                return "bg-primary"
            return "bg-muted" if niveau <= 200 else "bg-secondary"
        if prefixe in ("border", "divide"):
            return f"{prefixe}-border"
        if prefixe in ("ring", "outline"):
            return f"{prefixe}-ring/40"
        if prefixe in ("fill", "stroke"):
            return f"{prefixe}-muted-foreground"
        return None

    sens = TEINTE_VERS_SENS.get(teinte)
    if not sens:
        return None
    if prefixe == "text":
        return f"text-{sens}"
    if prefixe == "bg":
        # TOUJOURS un aplat teinté, quel que soit le niveau d'origine : c'est
        # l'idiome de la whiteapp. Un `bg-sky-500` plein n'a pas d'équivalent —
        # la charte n'a pas de token de texte à poser dessus, et on retomberait
        # sur `text-white` en dur.
        return f"bg-{sens}/10"
    if prefixe in ("border", "divide", "ring", "outline"):
        return f"{prefixe}-{sens}/35"
    if prefixe in ("fill", "stroke"):
        return f"{prefixe}-{sens}"
    return None


def traduire_jeton(jeton: str, journal: dict[str, int], inconnues: dict[str, int]) -> str | None:
    """La classe traduite, ou `None` si elle doit disparaître."""
    if jeton in LITTERALES:
        apres = LITTERALES[jeton]
        journal[f"{jeton} → {apres or '(retirée)'}"] = journal.get(
            f"{jeton} → {apres or '(retirée)'}", 0) + 1
        return apres or None

    m = JETON.match(jeton)
    if not m:
        return jeton
    variantes, prefixe, teinte, niveau, opacite = m.groups()
    if "dark:" in variantes:
        journal["dark: supprimées"] = journal.get("dark: supprimées", 0) + 1
        return None
    remplacante = cible(prefixe, teinte, int(niveau))
    if not remplacante:
        inconnues[jeton] = inconnues.get(jeton, 0) + 1
        return jeton
    if opacite and "/" not in remplacante:
        remplacante += opacite
    apres = variantes + remplacante
    journal[f"{jeton} → {apres}"] = journal.get(f"{jeton} → {apres}", 0) + 1
    return apres


def accorder_texte(jetons: list[str], journal: dict[str, int]) -> list[str]:
    """Accorder `text-white` au fond qui l'accompagne.

    Une table de correspondance ne peut pas trancher : `bg-zinc-900 text-white`
    veut `text-primary-foreground`, mais `bg-sky-500 text-white` — devenu
    `bg-info/10`, un fond CLAIR — veut `text-info`. Traduire les deux pareil
    rendait du blanc sur fond pâle une fois sur deux.
    """
    if "text-white" not in jetons:
        return jetons
    if "bg-primary" in jetons or "bg-foreground" in jetons:
        remplacante = "text-primary-foreground"
    else:
        teinte = next(
            (m.group(1) for j in jetons if (m := re.match(r"bg-(succes|alerte|danger|info)/", j))),
            None,
        )
        remplacante = f"text-{teinte}" if teinte else "text-foreground"
    journal[f"text-white → {remplacante}"] = journal.get(f"text-white → {remplacante}", 0) + 1
    return [remplacante if j == "text-white" else j for j in jetons]


# Une chaîne de classes : que des caractères de classe, et au moins un espace
# OU une classe cible. Le `[^'"`\\\n]` interdit tout saut de ligne — une chaîne
# de classes n'en contient jamais, et l'exclure évite d'avaler du code.
CHAINE = re.compile(r"(['\"`])([^'\"`\\\n]*)\1")
INTERESSANTE = re.compile(
    rf"\b(?:[a-z][\w-]*:)*(?:bg|text|border|ring|divide|outline|fill|stroke|from|via|to|shadow)-"
    rf"(?:{'|'.join(PALETTES)})-\d{{2,3}}\b|\b(?:bg|text)-(?:white|black)\b"
)


def traduire(texte: str, journal: dict[str, int], inconnues: dict[str, int]) -> str:
    def par_chaine(m: re.Match[str]) -> str:
        guillemet, contenu = m.group(1), m.group(2)
        if not INTERESSANTE.search(contenu):
            return m.group(0)
        # Les espaces de tête et de queue sont significatifs : `cn()` colle les
        # arguments, et une chaîne comme ' ml-2' compte sur son espace.
        tete = contenu[: len(contenu) - len(contenu.lstrip())]
        queue = contenu[len(contenu.rstrip()):]
        jetons = contenu.split()
        traduits = [t for j in jetons if (t := traduire_jeton(j, journal, inconnues)) is not None]
        traduits = accorder_texte(traduits, journal)
        # Dédoublonner en gardant l'ordre : retirer les `dark:` fait souvent
        # apparaître deux fois la même classe (`bg-muted bg-muted`).
        vus: dict[str, None] = {}
        for j in traduits:
            vus.setdefault(j, None)
        return f"{guillemet}{tete}{' '.join(vus)}{queue}{guillemet}"

    return CHAINE.sub(par_chaine, texte)


def main() -> int:
    applique = "--apply" in sys.argv
    journal: dict[str, int] = {}
    inconnues: dict[str, int] = {}
    touches = 0

    for fichier in sorted(RACINE.rglob("*.ts*")):
        avant = fichier.read_text(encoding="utf-8")
        apres = traduire(avant, journal, inconnues)
        if apres != avant:
            touches += 1
            if applique:
                fichier.write_text(apres, encoding="utf-8")

    total = sum(journal.values())
    print(f"{touches} fichiers · {total} remplacements"
          f"{'' if applique else ' (simulation — rien écrit)'}\n")
    for cle, n in sorted(journal.items(), key=lambda kv: -kv[1])[:20]:
        print(f"{n:>5}  {cle}")
    if inconnues:
        print(f"\n{sum(inconnues.values())} occurrences SANS correspondance — "
              "à trancher à la main :")
        for cle, n in sorted(inconnues.items(), key=lambda kv: -kv[1])[:20]:
            print(f"{n:>5}  {cle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
