"""Point d'entrée Typer pour la commande `zab`."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
import subprocess
import webbrowser
from typing import Any

import typer
import uvicorn
import yaml

from zab.system_open import open_os_path
from zab.paths import (
    config_dir,
    data_dir,
    mehdi_context_root,
    resolve_skills_root,
    scripts_dir,
    skills_root,
    skills_root_from_config_file_only,
    dashboard_local_tools_config_path,
    zab_package_dir,
    zab_repo_root,
    zab_ui_dist_dir,
)
from zab.user_config import load_user_config, merge_scan_inventory_into_config, merge_skills_roots_into_config, user_config_path
from zab.services.scan_persist import persist_workspace_scan
from zab.services.inventory_config import collect_plugin_roots_from_skill_paths
from zab.services.skills_roots_infer import (
    claude_plugin_paths_from_proposal,
    infer_skills_repo_roots,
    load_proposed_roots,
    persist_proposed_roots,
    roots_from_proposal,
    skill_md_paths_from_proposal,
)
from zab.services.cli_add import (
    McpTarget,
    add_api_proxy,
    add_cli_watchlist,
    add_mcp_server,
    add_tracked_env,
    parse_args_option,
    parse_env_flags,
)
from zab.services.memory_scan import resolve_mehdi_memory_database_url
from zab.services.scanner import resolve_optional_scan_root, workspace_scan
from zab.services.pm_env_sync import sync_pm_tokens_to_user_dotenv

app = typer.Typer(no_args_is_help=True, help="CLI zab — dashboard, scan workspace et jobs du dépôt skills.")
add_app = typer.Typer(help="Ajouter MCP (skills/configs), CLI watchlist, proxy API ou variable suivie (Sécurité).")
app.add_typer(add_app, name="add")
pm_env_app = typer.Typer(help="Jetons gestion de projet (GitLab / Linear / Notion) depuis les .env locaux.")
app.add_typer(pm_env_app, name="pm-env")


def _tilde_path(path: Path) -> str:
    try:
        home = Path.home().resolve()
        p = path.resolve()
        if p == home:
            return "~"
        rel = p.relative_to(home)
        return "~/" + str(rel).replace("\\", "/")
    except ValueError:
        return str(path)


def _open_path(path: Path) -> None:
    open_os_path(path)


def _local_tools_origin() -> tuple[Path, str]:
    user_cfg = config_dir() / "local-tools.yaml"
    if user_cfg.is_file():
        return user_cfg.resolve(), "utilisateur (~/.config/zab/local-tools.yaml)"
    pkg = zab_package_dir() / "local-tools.yaml"
    if pkg.is_file():
        return pkg.resolve(), "dépôt zab (exemple embarqué)"
    return user_cfg.resolve(), "emplacement par défaut (fichier absent)"


def _pretty_user_yaml(cfg: dict[str, Any]) -> str:
    clean = {k: v for k, v in cfg.items() if not str(k).startswith("_")}
    if not clean:
        return "(aucune clé ; fichier absent ou vide)"
    return yaml.safe_dump(clean, allow_unicode=True, sort_keys=False).rstrip()


@app.command("config")
def config_cmd(
    *,
    open_user_config: bool = typer.Option(False, "--open", "-o", help="Ouvrir ~/.config/zab/config.yaml"),
    open_tools: bool = typer.Option(False, "--open-tools", help="Ouvrir le fichier local-tools.yaml effectif"),
    paths_only: bool = typer.Option(False, "--paths", "-p", help="Afficher uniquement les chemins (une paire clé=chem par ligne)"),
) -> None:
    """Affiche la configuration résolue (chemins, variables, contenu de config.yaml)."""
    sr_path, sr_rule = resolve_skills_root()
    cfg_path = user_config_path()
    cfg_raw = load_user_config()
    lt_path, lt_origin = _local_tools_origin()
    dd = data_dir()

    if paths_only:
        typer.echo(f"skills_root={sr_path}")
        typer.echo(f"skills_root_source={sr_rule}")
        typer.echo(f"config_yaml={cfg_path.resolve()}")
        typer.echo(f"local_tools_yaml={lt_path.resolve()}")
        typer.echo(f"config_dir={config_dir().resolve()}")
        typer.echo(f"data_dir={dd.resolve()}")
        typer.echo(f"zab_repo={zab_repo_root().resolve()}")
        return

    if open_user_config:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        _open_path(cfg_path)
    if open_tools:
        lt_path.parent.mkdir(parents=True, exist_ok=True)
        _open_path(lt_path)

    typer.echo(typer.style(" ╭────────────────────────────────────────────────────╮", fg=typer.colors.WHITE))
    typer.echo(typer.style(" │", fg=typer.colors.WHITE) + "  zab — configuration                               " + typer.style("│", fg=typer.colors.WHITE))
    typer.echo(typer.style(" ╰────────────────────────────────────────────────────╯", fg=typer.colors.WHITE))
    typer.echo("")

    if open_user_config or open_tools:
        typer.echo(typer.style("  (fichiers ouverts dans l’application par défaut)", fg=typer.colors.GREEN))
        typer.echo("")

    typer.echo(typer.style("  Racine skills (effectif)", bold=True))
    typer.echo(f"    {_tilde_path(sr_path)}")
    typer.echo(typer.style(f"    ← {sr_rule}", dim=True))
    typer.echo("")
    typer.echo(typer.style("  Dashboard (données API)", bold=True))
    dash_sr = skills_root_from_config_file_only()
    if dash_sr is not None:
        typer.echo(f"    ancrage : {_tilde_path(dash_sr)}")
        typer.echo(typer.style("    ← skill_md_paths / skills_roots / plugins (premier chemin résolu)", dim=True))
    else:
        typer.echo(
            typer.style(
                "    Définissez skill_md_paths dans config.yaml (zab scan --propose-config puis --apply-config).",
                dim=True,
            )
        )
    typer.echo(f"    local-tools UI : {_tilde_path(dashboard_local_tools_config_path())}")
    typer.echo("")

    typer.echo(typer.style("  Variables d'environnement", bold=True))
    for name in ("ZAB_SKILLS_ROOT", "ZAB_INVOCATION_CWD", "ZAB_REPO", "ZAB_UI_DIST", "XDG_CONFIG_HOME"):
        raw = os.environ.get(name)
        if raw:
            typer.echo(f"    {typer.style(name, fg=typer.colors.CYAN)}={raw}")
        else:
            typer.echo(typer.style(f"    {name} (non défini)", dim=True))
    typer.echo("")

    typer.echo(typer.style("  Fichiers", bold=True))
    cfg_exists = cfg_path.is_file()
    typer.echo(
        f"    {'●' if cfg_exists else '○'} "
        f"{typer.style('config.yaml', fg=typer.colors.CYAN)}  {_tilde_path(cfg_path)}"
        + ("" if cfg_exists else typer.style("  (absent)", dim=True))
    )
    lt_exists = lt_path.is_file()
    typer.echo(
        f"    {'●' if lt_exists else '○'} "
        f"{typer.style('local-tools.yaml', fg=typer.colors.CYAN)}  {_tilde_path(lt_path)}"
    )
    typer.echo(typer.style(f"       origine : {lt_origin}", dim=True))
    typer.echo(
        f"    ● {typer.style('répertoire données', fg=typer.colors.CYAN)}  {_tilde_path(dd)}"
    )
    typer.echo(
        f"    ● {typer.style('dépôt zab (code)', fg=typer.colors.CYAN)}  {_tilde_path(zab_repo_root())}"
    )
    typer.echo("")

    if cfg_raw.get("_error") == "yaml_invalid":
        typer.echo(typer.style("  ⚠ YAML invalide dans config.yaml — corrigez le fichier.", fg=typer.colors.RED))
        typer.echo(typer.style(f"     {cfg_raw.get('path', '')}", dim=True))
        typer.echo("")
    else:
        typer.echo(typer.style("  Contenu de config.yaml", bold=True))
        block = _pretty_user_yaml(cfg_raw)
        for line in block.splitlines():
            typer.echo(typer.style("  │ ", dim=True) + line)
        typer.echo("")

    typer.echo(typer.style("  Édition", bold=True))
    typer.echo(f"    {typer.style('zab config --open', fg=typer.colors.GREEN)}        → config.yaml")
    typer.echo(f"    {typer.style('zab config --open-tools', fg=typer.colors.GREEN)} → local-tools.yaml")
    typer.echo(typer.style(f"    ou ouvrez directement : {_tilde_path(cfg_path)}", dim=True))


@app.command()
def doctor() -> None:
    """Vérifie uv, node, chemins du repo."""
    root = skills_root()
    typer.echo(f"SKILLS_ROOT = {root}")
    checks: list[tuple[str, object, str]] = [
        ("orgs", root / "orgs", "dir"),
        ("mcps/flowmetrik-gateway", root / "mcps" / "flowmetrik-gateway", "dir"),
        ("configs/cursor-mcp.json", root / "configs" / "cursor-mcp.json", "file"),
        ("~/.mehdi-context", mehdi_context_root(), "dir"),
    ]
    for name, path, kind in checks:
        p = Path(path)
        ok = p.is_dir() if kind == "dir" else p.is_file()
        typer.echo(f"  [{'OK' if ok else '!!'}] {name}: {p}")
    for bin_name in ("uv", "node", "npm"):
        loc = shutil.which(bin_name)
        typer.echo(f"  [{'OK' if loc else '!!'}] {bin_name}: {loc or 'absent'}")
    mp = shutil.which("mempalace")
    typer.echo(f"  [{'OK' if mp else '!!'}] mempalace: {mp or 'absent'}")
    if mp:
        try:
            proc = subprocess.run([mp, "--version"], capture_output=True, text=True, timeout=5)
            ver = (proc.stdout or proc.stderr or "").strip().splitlines()
            if ver:
                typer.echo(typer.style(f"      {ver[0][:120]}", dim=True))
        except (OSError, subprocess.TimeoutExpired):
            pass
    anchor = skills_root_from_config_file_only()
    dsn_ok = bool(resolve_mehdi_memory_database_url(anchor))
    typer.echo(f"  [{'OK' if dsn_ok else '!!'}] MEHDI_MEMORY_DATABASE_URL (env ou skills/.env): {'présent' if dsn_ok else 'absent'}")


@app.command("dashboard")
def dashboard_cmd(
    host: str = typer.Option("127.0.0.1", help="Bind API"),
    port: int = typer.Option(8742, help="Port API"),
    dev: bool = typer.Option(False, "--dev", help="Affiche la commande pour lancer Vite en parallèle"),
    reload: bool = typer.Option(False, "--reload", "-r", help="Redémarrage automatique si le code Python change"),
    no_open: bool = typer.Option(False, "--no-open", help="Ne pas ouvrir le navigateur"),
) -> None:
    """Démarre le serveur FastAPI (dashboard API + SPA dist si buildée)."""
    if dev:
        typer.echo(
            "Mode dev : dans un second terminal, exécute :\n"
            f"  cd {zab_repo_root() / 'zab-ui'} && npm install && npm run dev\n"
            f"Le proxy Vite pointe vers http://{host}:{port}/api"
        )
    url = f"http://{host}:{port}/"
    if not no_open:
        if (zab_ui_dist_dir() / "index.html").is_file():
            webbrowser.open(url)
        else:
            webbrowser.open(f"http://{host}:{port}/api/health")
    uvicorn.run(
        "zab.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


@app.command("run")
def run_cmd(
    smoke: bool = typer.Option(False, "--smoke", help="Exécute scripts/smoke_test_all_mcps.sh"),
) -> None:
    """Lance un script prédéfini (stdout/stderr hérités du terminal)."""
    root = skills_root()
    if smoke:
        script = scripts_dir() / "smoke_test_all_mcps.sh"
        if not script.is_file():
            typer.echo(f"Script absent : {script}", err=True)
            raise typer.Exit(1)
        proc = subprocess.run(["bash", str(script)], cwd=str(root))
        raise typer.Exit(proc.returncode)
    typer.echo("Indique une action, ex. : zab run --smoke", err=True)
    raise typer.Exit(1)


@app.command()
def scan(
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON (machine)"),
    root: str | None = typer.Option(None, "--root", help="Sous-chemin sous ~ (HOME), ou chemin absolu contenu dans ~"),
    dir_path: str | None = typer.Option(
        None,
        "--dir",
        help="Dossier quelconque à scanner (SKILL.md + déduction des racines avec --propose-config)",
    ),
    persist: bool = typer.Option(False, "--persist", help="Enregistrer le rapport dans ~/.local/share/zab/scan-last.yaml"),
    propose_config: bool = typer.Option(
        False,
        "--propose-config",
        help="Enregistrer la proposition (skill_md_paths + claude_plugin_paths + métadonnées) dans ~/.local/share/zab/scan-proposed-skills-roots.yaml",
    ),
    apply_config: bool = typer.Option(
        False,
        "--apply-config",
        help="Écrire l’inventaire (skill_md_paths, claude_plugin_paths) depuis la dernière proposition dans ~/.config/zab/config.yaml",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Sans confirmation interactive (avec --apply-config)"),
) -> None:
    """Scan SKILL.md, CLIs, Agentpipe/Codexbar ; optionnellement enregistrer l’inventaire dans config.yaml."""
    allow_any = bool(dir_path and str(dir_path).strip())
    scan_root_opt = Path(dir_path).expanduser() if allow_any else resolve_optional_scan_root(root)
    report = workspace_scan(scan_root_opt, allow_any_path=allow_any)

    roots_this_run: list[str] = []
    inventory_skill_abs: list[str] = []
    inventory_plugin_abs: list[str] | None = None

    if json_out:
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
        return

    for w in report.get("warnings") or []:
        typer.echo(typer.style(w, fg=typer.colors.YELLOW))

    typer.echo(f"Répertoire ~     : {report.get('user_home', '')}")
    typer.echo(f"Dépôt skills ref : {report['skills_root']}")
    typer.echo(f"Scan depuis      : {report['scan_root_resolved']}")
    typer.echo(f"Nb SKILL.md      : {report['skill_md_count']}")

    skills = report.get("skill_md_files") or []
    preview = skills[:60]
    for row in preview:
        typer.echo(f"  · {row['path']}")
    if len(skills) > len(preview):
        typer.echo(f"  … ({len(skills) - len(preview)} supplémentaires)")

    clis = report.get("clis") or {}
    zab_cmds = clis.get("zab_commands") or []
    typer.echo("Commandes zab    :")
    for c in zab_cmds[:30]:
        typer.echo(f"  · {c.get('name', '')}")

    scripts = clis.get("repo_scripts") or []
    typer.echo(f"Scripts repo     : {len(scripts)}")

    ap = report.get("agentpipe") or {}
    ap_cli = ap.get("cli_agentpipe_binary")
    typer.echo(
        f"Agentpipe        : présent={'oui' if ap.get('present') else 'non'} ({ap.get('path', '')})"
        + (f"\n  binaire agentpipe: {ap_cli}" if ap_cli else "\n  binaire agentpipe: (absent du PATH)")
    )
    nt = ap.get("agents_total")
    no = ap.get("agents_on_path")
    if isinstance(nt, int):
        typer.echo(f"  agents déclarés/sur PATH : {nt} / {no if isinstance(no, int) else '—'}")
    for agent in ap.get("agents") or []:
        state = typer.style("PATH", fg=typer.colors.GREEN) if agent.get("on_path") else "absent"
        typer.echo(f"  · {agent.get('id')} [{state}] probe={agent.get('probe_binary')}")

    cb = report.get("codexbar") or {}
    cb_cli = cb.get("cli_codexbar_binary")
    typer.echo(
        f"Codexbar JSON    : présent={'oui' if cb.get('present') else 'non'} ({cb.get('path', '')})"
        + (f"\n  binaire codexbar: {cb_cli}" if cb_cli else "\n  binaire codexbar: (absent du PATH)")
    )

    if not (persist or propose_config or apply_config):
        typer.echo("")
        typer.echo(
            typer.style(
                "ℹ Ce scan n’écrit pas dans ~/.config/zab/config.yaml (comportement volontaire).",
                fg=typer.colors.CYAN,
            )
        )
        typer.echo(typer.style("  Enregistrer la proposition (chemins SKILL.md + plugins) : ", dim=True) + typer.style("zab scan --propose-config", fg=typer.colors.GREEN))
        typer.echo(typer.style("  Écrire dans config.yaml : ", dim=True) + typer.style("zab scan --apply-config", fg=typer.colors.GREEN))
        typer.echo(
            typer.style("  Ou en une fois (avec confirmation) : ", dim=True)
            + typer.style("zab scan --propose-config --apply-config", fg=typer.colors.GREEN)
        )
        typer.echo(
            typer.style(
                "  Pour ne scanner qu’un dépôt : ajoutez --dir ~/chemin/vers/le/repo",
                dim=True,
            )
        )

    if persist:
        p_saved = persist_workspace_scan(report)
        typer.echo(typer.style(f"\nScan persisté : {p_saved}", fg=typer.colors.GREEN))

    if propose_config:
        rels = [str(x.get("path", "")) for x in skills if isinstance(x, dict) and x.get("path")]
        scan_base = Path(report["scan_root_resolved"])
        roots_paths = infer_skills_repo_roots(scan_base, rels)
        if not roots_paths:
            roots_paths = [scan_base.resolve()]
        roots_this_run = [str(r.resolve()) for r in roots_paths]
        inventory_skill_abs = []
        for rel in rels:
            try:
                full = (scan_base / rel).resolve()
                if full.is_file():
                    inventory_skill_abs.append(str(full))
            except OSError:
                continue
        inventory_skill_abs = sorted(set(inventory_skill_abs))
        inventory_plugin_abs = [
            str(p) for p in collect_plugin_roots_from_skill_paths([Path(s) for s in inventory_skill_abs])
        ]
        prop_file = persist_proposed_roots(
            scan_root=scan_base,
            roots=roots_paths,
            skill_md_abs_paths=inventory_skill_abs,
            claude_plugin_abs_paths=inventory_plugin_abs,
            skill_md_count=int(report.get("skill_md_count") or 0),
            skill_samples=rels,
        )
        typer.echo(typer.style(f"\nProposition enregistrée : {prop_file}", fg=typer.colors.CYAN))
        typer.echo(f"SKILL.md détectés : {len(inventory_skill_abs)} · Plugins Claude : {len(inventory_plugin_abs)}")
        typer.echo(typer.style("(aperçu racines dépôt — non écrites si vous appliquez l’inventaire)", dim=True))
        for r in roots_paths[:12]:
            typer.echo(f"  · {r}")
        if len(roots_paths) > 12:
            typer.echo(typer.style(f"  … {len(roots_paths) - 12} autres", dim=True))

    if apply_config:
        doc = load_proposed_roots()
        skills_use = list(inventory_skill_abs)
        plugins_use: list[str] | None = inventory_plugin_abs if inventory_plugin_abs is not None else None
        if not skills_use and doc:
            skills_use = skill_md_paths_from_proposal(doc)
            if plugins_use is None:
                pl = claude_plugin_paths_from_proposal(doc)
                plugins_use = pl if pl else None

        if skills_use:
            if not yes:
                typer.echo("\nÉcriture dans ~/.config/zab/config.yaml :")
                typer.echo(f"  · skill_md_paths : {len(skills_use)} entrée(s)")
                n_pl = "déduit des SKILL.md" if plugins_use is None else str(len(plugins_use))
                typer.echo(f"  · claude_plugin_paths : {n_pl}")
                if not typer.confirm("Remplacer l’inventaire et vider skills_roots ?", default=False):
                    raise typer.Exit(0)
            cfg_path, summary = merge_scan_inventory_into_config(skills_use, claude_plugin_abs_paths=plugins_use)
            typer.echo(typer.style(f"\nConfig mise à jour : {cfg_path}", fg=typer.colors.GREEN))
            typer.echo(f"skill_md_paths ({len(summary['skill_md_paths'])}) dont aperçu :")
            for m in summary["skill_md_paths"][:15]:
                typer.echo(f"  · {m}")
            if len(summary["skill_md_paths"]) > 15:
                typer.echo(typer.style(f"  … {len(summary['skill_md_paths']) - 15} autres", dim=True))
            typer.echo(f"claude_plugin_paths ({len(summary['claude_plugin_paths'])}) :")
            for m in summary["claude_plugin_paths"][:15]:
                typer.echo(f"  · {m}")
            if len(summary["claude_plugin_paths"]) > 15:
                typer.echo(typer.style(f"  … {len(summary['claude_plugin_paths']) - 15} autres", dim=True))
        else:
            to_merge = list(roots_this_run)
            if not to_merge and doc:
                to_merge = roots_from_proposal(doc) if doc else []
            if not to_merge:
                typer.echo(
                    typer.style(
                        "\nAucun inventaire à appliquer — lancez : zab scan --propose-config (évent. --dir CHEMIN)",
                        fg=typer.colors.RED,
                    ),
                    err=True,
                )
                raise typer.Exit(1)
            if not yes:
                typer.echo("\nAncienne proposition (sans liste SKILL.md) — fusion dans skills_roots :")
                for pth in to_merge:
                    typer.echo(f"  · {pth}")
                if not typer.confirm("Écrire dans config.yaml ?", default=False):
                    raise typer.Exit(0)
            cfg_path, merged = merge_skills_roots_into_config(to_merge)
            typer.echo(typer.style(f"\nConfig mise à jour : {cfg_path}", fg=typer.colors.GREEN))
            typer.echo(f"skills_roots ({len(merged)} entrée(s)) :")
            for m in merged:
                typer.echo(f"  · {m}")


def _parse_mcp_target(raw: str) -> McpTarget:
    t = raw.strip().lower().replace("-", "_")
    if t in ("cursor",):
        return "cursor"
    if t in ("desktop", "claude", "claude_desktop"):
        return "desktop"
    raise ValueError(f"cible MCP inconnue : {raw!r} — utiliser cursor ou desktop")


@add_app.command("mcp")
def add_mcp_cmd(
    name: str = typer.Argument(..., help="Nom du serveur (clé dans mcpServers)"),
    target: str = typer.Option("cursor", "--target", "-t", help="cursor ou desktop (claude-desktop-mcp.json)"),
    url: str | None = typer.Option(None, "--url", help="URL du serveur MCP (HTTP)"),
    command: str | None = typer.Option(None, "--command", "-c", help="Commande stdio (ex. npx)"),
    args: str | None = typer.Option(None, "--args", help="Arguments (quoting shell, ex. -y @scope/mcp)"),
    env: list[str] = typer.Option([], "--env", "-e", help="KEY=value pour le bloc env (stdio)"),
    force: bool = typer.Option(False, "--force", "-f", help="Remplacer une entrée existante"),
) -> None:
    """Ajoute une entrée dans configs/cursor-mcp.json ou claude-desktop-mcp.json du dépôt skills."""
    try:
        mcp_target = _parse_mcp_target(target)
        env_map = parse_env_flags(env) if env else None
        arg_list = parse_args_option(args)
        path = add_mcp_server(
            target=mcp_target,
            name=name,
            url=url,
            command=command,
            args=arg_list,
            env_pairs=env_map,
            force=force,
        )
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"Écrit : {path}")


@add_app.command("cli")
def add_cli_cmd(
    binary: str = typer.Argument(..., help="Nom du binaire (ex. gh)"),
    where: str = typer.Option(
        "local",
        "--where",
        "-w",
        help="local → local-tools.yaml ; config → ~/.config/zab/config.yaml",
    ),
) -> None:
    """Ajoute un binaire à cli_watchlist (scan which)."""
    w = where.strip().lower()
    try:
        if w in ("local", "local_tools", "yaml", "tools"):
            path = add_cli_watchlist(binary, where="local_tools")
        elif w in ("config", "user", "user_config", "global"):
            path = add_cli_watchlist(binary, where="user_config")
        else:
            typer.echo(f"Valeur --where inconnue : {where} (local ou config)", err=True)
            raise typer.Exit(code=1)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"Écrit : {path}")


@add_app.command("api")
def add_api_cmd(
    key: str = typer.Argument(..., help="Identifiant du proxy (ex. litellm)"),
    base_url: str = typer.Option(..., "--url", "-u", help="URL de base de l'API"),
    api_key_env: str | None = typer.Option(None, "--key-env", help="Variable d'environnement pour la clé API"),
) -> None:
    """Ajoute une entrée proxies.* dans local-tools.yaml."""
    try:
        path = add_api_proxy(key, base_url, api_key_env)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"Écrit : {path}")


@add_app.command("env")
def add_env_cmd(
    name: str = typer.Argument(..., help="Nom de variable (ex. MY_SERVICE_TOKEN)"),
) -> None:
    """Enregistre une variable supplémentaire suivie dans l'onglet Sécurité (merged avec le catalogue zab)."""
    try:
        path = add_tracked_env(name)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"Écrit tracked_env_extra dans : {path}")


@pm_env_app.command("sync")
def pm_env_sync_cmd(
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Remplace les jetons dans ~/.config/zab/.env même s’ils sont déjà renseignés",
    ),
) -> None:
    """Scanne projects_roots (+ skills/.env) et écrit GITLAB_TOKEN / LINEAR_API_KEY / NOTION_TOKEN dans ~/.config/zab/.env."""
    summary = sync_pm_tokens_to_user_dotenv(force=force)
    typer.echo(typer.style("Fusion ~/.config/zab/.env", bold=True))
    typer.echo(f"  Fichier : {summary['path']}")
    typer.echo(f"  Fichiers .env candidats lus : {summary['scanned_env_files']}")
    typer.echo(f"  Clés trouvées au scan : {', '.join(summary['keys_found_by_scan']) or '(aucune)'}")
    typer.echo(f"  Clés écrites / mises à jour : {', '.join(summary['keys_updated']) or '(aucune)'}")
    if summary.get("keys_skipped_already_present"):
        typer.echo(
            typer.style(
                f"  Ignorées (déjà présentes, sans --force) : {', '.join(summary['keys_skipped_already_present'])}",
                dim=True,
            )
        )
    typer.echo(typer.style("  Redémarrez le dashboard pour recharger le fichier si besoin.", dim=True))


def main() -> None:
    from zab.user_config import ensure_user_config_exists

    ensure_user_config_exists()
    app()


if __name__ == "__main__":
    main()
