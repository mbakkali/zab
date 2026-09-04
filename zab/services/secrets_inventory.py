"""L'inventaire des clés : où la donnée est, et sur quelle machine.

`zab security status` répondait juste, mais seulement pour l'instant présent et
seulement pour la machine qui posait la question. Rien n'était conservé. Deux
questions restaient donc sans réponse, et ce sont les deux qu'on se pose :

  · « la clé X existe-t-elle ? » — oui **ici**, mais le Mac ? La VM ? Un agent
    concluait « pas d'accès » alors que la clé vivait sur l'autre machine ;
  · « depuis quand manque-t-elle ? » — sans trace, une clé révoquée ressemble à
    une clé qui n'a jamais existé.

L'inventaire répond aux deux : il est **daté**, **rangé par machine**, et
stocké dans la base partagée. Chaque machine y écrit le sien ; toutes les
lisent. Aucune valeur n'y entre — uniquement des noms de variables, des chemins
de fichiers, et le fait qu'une valeur non vide s'y trouve.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from zab.services import ledger_db, postgres_store, secrets_registry

PREFIXE_META = "security.inventory"
CONTRAT = "zab-security-inventory"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def meta_key(machine: str | None = None) -> str:
    return f"{PREFIXE_META}.{machine or ledger_db.machine_id()}"


def build(*, persist: bool = False) -> dict[str, Any]:
    """Relève les `.env` de cette machine et dit ce qui s'y trouve.

    Le relevé s'appuie sur `security_status`, qui sait déjà balayer les
    fichiers sans lire une valeur ; on y ajoute la machine, le connecteur que
    chaque variable sert, et la date. C'est ce triplet qui rend la réponse
    utilisable : « FULLENRICH_API_KEY, présente dans le coffre zab, relevée sur
    la VM le 4 septembre ».
    """
    from zab.services.agent_context import security_status

    statut = security_status()
    par_connecteur = secrets_registry.connectors_by_env()

    variables: dict[str, Any] = {}
    for var in statut.get("variables") or []:
        nom = str(var.get("name") or "")
        if not nom:
            continue
        variables[nom] = {
            "present": bool(var.get("present")),
            "in_process": bool(var.get("in_process")),
            # Les chemins et le nom **réellement** rencontré, jamais la
            # valeur : c'est ce qui permet de dire « la donnée est là » sans la
            # sortir du coffre. Le nom compte — `QONTO_API_KEY` se trouve sous
            # `QONTO_SECRET_KEY`, et chercher le premier ne donne rien.
            "sources": [
                {"path": str(f.get("path")), "key": str(f.get("key") or nom)}
                for f in (var.get("in_files") or [])
                if f.get("path")
            ],
            "connectors": par_connecteur.get(nom, []),
        }

    inventaire = {
        "contract": CONTRAT,
        "contract_version": "1.0",
        "machine": ledger_db.machine_id(),
        "generated_at_utc": _now(),
        "files_scanned": [str(p) for p in (statut.get("env_files_scanned") or [])],
        "tracked_count": len(variables),
        "present": sorted(n for n, v in variables.items() if v["present"]),
        "missing": sorted(n for n, v in variables.items() if not v["present"]),
        "variables": variables,
        "registry": secrets_registry.summary(),
        "policy": {
            "secrets": "never_stored",
            "stored": "variable_names_and_file_paths_only",
        },
    }
    if persist:
        postgres_store.set_meta(meta_key(), inventaire)
    return inventaire


def load(machine: str | None = None) -> dict[str, Any] | None:
    """Le dernier relevé d'une machine, tel qu'il a été enregistré."""
    valeur = postgres_store.get_meta(meta_key(machine), None)
    return valeur if isinstance(valeur, dict) else None


def machines() -> list[str]:
    """Les machines qui ont déposé un inventaire."""
    with postgres_store.transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT key FROM {postgres_store.SCHEMA}.sync_meta "
                "WHERE key LIKE %s ORDER BY key",
                (f"{PREFIXE_META}.%",),
            )
            lignes = cur.fetchall()
    noms: list[str] = []
    for ligne in lignes:
        cle = ligne["key"] if isinstance(ligne, dict) else ligne[0]
        noms.append(str(cle)[len(PREFIXE_META) + 1 :])
    return noms


def compare() -> dict[str, Any]:
    """Ce que chaque machine détient, et ce qu'elle est seule à détenir.

    C'est la vue qui évite le faux « pas d'accès » : une clé absente ici mais
    présente ailleurs n'appelle pas la même réponse qu'une clé introuvable
    partout.
    """
    releves = {m: load(m) for m in machines()}
    releves = {m: r for m, r in releves.items() if r}
    toutes: set[str] = set()
    for r in releves.values():
        toutes |= set(r.get("variables") or {})

    lignes: dict[str, Any] = {}
    for nom in sorted(toutes):
        ou = [
            m
            for m, r in releves.items()
            if (r.get("variables") or {}).get(nom, {}).get("present")
        ]
        lignes[nom] = {
            "present_sur": ou,
            "absente_sur": sorted(set(releves) - set(ou)),
            "connectors": next(
                (
                    (r.get("variables") or {}).get(nom, {}).get("connectors") or []
                    for r in releves.values()
                    if nom in (r.get("variables") or {})
                ),
                [],
            ),
        }
    return {
        "contract": f"{CONTRAT}-compare",
        "machines": {
            m: {
                "generated_at_utc": r.get("generated_at_utc"),
                "present": len(r.get("present") or []),
                "missing": len(r.get("missing") or []),
            }
            for m, r in releves.items()
        },
        "variables": lignes,
        "introuvables_partout": sorted(
            n for n, d in lignes.items() if not d["present_sur"]
        ),
    }
