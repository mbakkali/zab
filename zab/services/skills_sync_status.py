"""Statut multi-sources des skills + scan/import depuis Hermes / Cursor / Claude."""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from zab.services.hermes_config import discover_hermes_external_dirs, update_external_dirs
from zab.services import notifications, skills_registry, state_index
from zab.services.skills_scan import collect_skill_md_under_repo, iter_skill_md_recursive
from zab.services.skills_git_sync import _secret_like, commit_and_push
from zab.services.skills_scaffold import SkillScaffoldError, validate_skill_slug
from zab.services.workspace_projects import discover_projects
from zab.user_config import load_user_config, skills_sync_settings


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _frontmatter_name(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    try:
        raw = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    return name.strip() if isinstance(name, str) and name.strip() else None


_NON_SLUG = re.compile(r"[^a-z0-9-]+")


def coerce_import_slug(*, skill_md: Path, fm_name: str | None) -> str:
    """Produit un slug [a-z0-9-] utilisable comme dossier sous common/skills."""
    candidates = [fm_name or "", skill_md.parent.name]
    for raw in candidates:
        s = raw.strip().lower().replace(" ", "-")
        s = _NON_SLUG.sub("-", s)
        s = re.sub(r"-+", "-", s).strip("-")
        if not s:
            continue
        try:
            return validate_skill_slug(s)
        except SkillScaffoldError:
            continue
    # dernier recours : dossier parent nettoyé caractère par caractère
    base = "".join(ch.lower() if ch.isalnum() else "-" for ch in skill_md.parent.name).strip("-")
    base = re.sub(r"-+", "-", base) or "imported-skill"
    try:
        return validate_skill_slug(base)
    except SkillScaffoldError:
        return validate_skill_slug("imported-skill")


def infer_org_slug_from_path(skill_md: Path, repo_root: Path) -> str | None:
    """Si le SKILL.md est sous …/orgs/<org>/skills/… ou catégorie Hermes, retourne le slug org."""
    return skills_registry.infer_org_slug_for_skill_file(skill_md, repo_root)


def _collect_skill_md_under_repo(repo: Path) -> list[Path]:
    return collect_skill_md_under_repo(repo)


def _scan_agent_global_skills(root: Path) -> dict[str, Any]:
    skills_root = root / "skills"
    paths = iter_skill_md_recursive(skills_root)
    slugs = [p.parent.name for p in paths]
    return {
        "root": str(root.expanduser()),
        "skills_dir": str(skills_root.expanduser()),
        "present": skills_root.is_dir(),
        "skill_md_count": len(paths),
        "slugs": sorted(set(slugs), key=str.casefold),
    }


def _git(repo: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=check)


def _git_branch_status(repo: Path) -> dict[str, Any]:
    proc = _git(repo, "rev-parse", "--is-inside-work-tree")
    if proc.returncode != 0 or proc.stdout.strip() != "true":
        return {
            "is_git_repo": False,
            "branch": None,
            "dirty": None,
            "ahead": None,
            "behind": None,
            "upstream": None,
        }
    br = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    branch = br.stdout.strip() if br.returncode == 0 else None
    st = _git(repo, "status", "--porcelain")
    dirty = bool(st.stdout.strip()) if st.returncode == 0 else None
    up = _git(repo, "rev-parse", "--abbrev-ref", "@{u}")
    upstream = up.stdout.strip() if up.returncode == 0 else None
    ahead, behind = None, None
    if upstream:
        cnt = _git(repo, "rev-list", "--left-right", "--count", f"{upstream}...HEAD")
        if cnt.returncode == 0 and "\t" in cnt.stdout:
            left, right = cnt.stdout.strip().split("\t", 1)
            try:
                behind = int(left)
                ahead = int(right)
            except ValueError:
                pass
    remote_url: str | None = None
    ru = _git(repo, "remote", "get-url", "origin")
    if ru.returncode == 0:
        remote_url = ru.stdout.strip()
    return {
        "is_git_repo": True,
        "branch": branch,
        "dirty": dirty,
        "ahead": ahead,
        "behind": behind,
        "upstream": upstream,
        "remote_url": remote_url,
    }


def _hermes_configured_dirs(cfg_path: Path) -> list[str]:
    doc = _read_yaml(cfg_path)
    skills = doc.get("skills") if isinstance(doc.get("skills"), dict) else {}
    raw = skills.get("external_dirs") if isinstance(skills.get("external_dirs"), list) else []
    return [str(x) for x in raw if isinstance(x, str) and x.strip()]


def _resolved_dir_list(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        try:
            p = Path(raw).expanduser().resolve()
        except OSError:
            continue
        if p.is_dir():
            out.append(p)
    return out



def _path_under_any(p: Path, roots: list[Path]) -> bool:
    pr = p.resolve()
    for root in roots:
        try:
            pr.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _relative_under_repo(repo: Path, p: Path) -> str | None:
    try:
        rel = p.resolve().relative_to(repo.resolve())
    except ValueError:
        return None
    return str(rel).replace("\\", "/")


def _git_repo_path_index(repo: Path) -> tuple[set[str], set[str]]:
    """Chemins relatifs suivis par git vs modifiés (wt + index)."""

    tracked: set[str] = set()
    ls = _git(repo, "ls-files")
    if ls.returncode == 0:
        for line in ls.stdout.splitlines():
            s = line.strip().replace("\\", "/")
            if s:
                tracked.add(s)
    dirty: set[str] = set()
    for args in (
        ["diff-files", "--name-only", "-z"],
        ["diff-index", "--cached", "--name-only", "-z", "HEAD"],
    ):
        proc = _git(repo, *args)
        if proc.returncode != 0:
            continue
        for name in proc.stdout.split("\0"):
            if name.strip():
                dirty.add(name.strip().replace("\\", "/"))
    return tracked, dirty


def _skill_sync_hint_for_path(
    p: Path,
    *,
    repo: Path,
    hermes_dirs: list[Path],
    cursor_dir: Path,
    claude_dir: Path,
    kimi_dir: Path,
    cursor_slugs: set[str],
    claude_slugs: set[str],
    kimi_slugs: set[str],
    git_meta: dict[str, Any],
    tracked: set[str],
    dirty: set[str],
) -> dict[str, Any]:
    rel = _relative_under_repo(repo, p)
    in_global_repo = rel is not None
    under_cursor = _path_under_any(p, [cursor_dir]) if cursor_dir.is_dir() else False
    under_claude = _path_under_any(p, [claude_dir]) if claude_dir.is_dir() else False
    under_kimi = _path_under_any(p, [kimi_dir]) if kimi_dir.is_dir() else False
    slug_cf = p.parent.name.casefold()
    hermes_ok = _path_under_any(p, hermes_dirs) if hermes_dirs else False

    cursor_slug_parallel = bool(cursor_dir.is_dir() and cursor_slugs and slug_cf in cursor_slugs and not under_cursor)
    claude_slug_parallel = bool(claude_dir.is_dir() and claude_slugs and slug_cf in claude_slugs and not under_claude)
    kimi_slug_parallel = bool(kimi_dir.is_dir() and kimi_slugs and slug_cf in kimi_slugs and not under_kimi)

    github: dict[str, Any] = {"applicable": in_global_repo}
    if in_global_repo and rel and git_meta.get("is_git_repo"):
        is_tracked = rel in tracked
        file_dirty = rel in dirty
        upstream = bool(git_meta.get("upstream"))
        ahead = git_meta.get("ahead")
        pushed_ok = upstream and ahead == 0
        github.update(
            {
                "tracked": is_tracked,
                "file_clean": is_tracked and not file_dirty,
                "repo_ahead_commits": ahead,
                "remote_configured": bool(git_meta.get("remote_url")),
                "pushed_hint": bool(is_tracked and not file_dirty and pushed_ok),
            }
        )
    elif in_global_repo:
        github.update(
            {
                "tracked": False,
                "file_clean": False,
                "repo_ahead_commits": None,
                "remote_configured": False,
                "pushed_hint": False,
            }
        )

    return {
        "global_repo": in_global_repo,
        "hermes_external_dir": hermes_ok,
        "cursor_global_path": under_cursor,
        "claude_global_path": under_claude,
        "kimi_global_path": under_kimi,
        "cursor_global_slug_parallel": cursor_slug_parallel,
        "claude_global_slug_parallel": claude_slug_parallel,
        "kimi_global_slug_parallel": kimi_slug_parallel,
        "github": github,
    }


def skills_sync_hints_payload(*, limit: int = 500) -> dict[str, Any]:
    """Indices de synchro par chemin absolu de SKILL.md (aligné sur state.yaml skills)."""

    settings = skills_sync_settings()
    repo = Path(str(settings["repo_root"])).expanduser().resolve()
    hermes_cfg = Path(str(settings["hermes_config_path"])).expanduser().resolve()
    hermes_dirs = _resolved_dir_list(_hermes_configured_dirs(hermes_cfg))

    home = Path.home()
    cursor_dir = (home / ".cursor" / "skills").resolve()
    claude_dir = (home / ".claude" / "skills").resolve()
    kimi_dir = (home / ".kimi" / "skills").resolve()
    cursor_scan = _scan_agent_global_skills(home / ".cursor")
    claude_scan = _scan_agent_global_skills(home / ".claude")
    kimi_scan = _scan_agent_global_skills(home / ".kimi")
    cursor_slugs = {str(s).casefold() for s in (cursor_scan.get("slugs") or []) if isinstance(s, str)}
    claude_slugs = {str(s).casefold() for s in (claude_scan.get("slugs") or []) if isinstance(s, str)}
    kimi_slugs = {str(s).casefold() for s in (kimi_scan.get("slugs") or []) if isinstance(s, str)}

    git_meta = _git_branch_status(repo)
    tracked: set[str] = set()
    dirty: set[str] = set()
    if git_meta.get("is_git_repo"):
        tracked, dirty = _git_repo_path_index(repo)

    state = state_index.load_state()
    skills_raw = state.get("skills") if isinstance(state.get("skills"), dict) else {}
    hints: dict[str, dict[str, Any]] = {}
    n = 0
    for _k, row in sorted(skills_raw.items(), key=lambda x: str(x[0]).lower()):
        if not isinstance(row, dict):
            continue
        raw_path = str(row.get("path") or "")
        if not raw_path:
            continue
        try:
            p = Path(raw_path).expanduser().resolve()
        except OSError:
            continue
        if not p.is_file():
            continue
        key = str(p)
        hints[key] = _skill_sync_hint_for_path(
            p,
            repo=repo,
            hermes_dirs=hermes_dirs,
            cursor_dir=cursor_dir,
            claude_dir=claude_dir,
            kimi_dir=kimi_dir,
            cursor_slugs=cursor_slugs,
            claude_slugs=claude_slugs,
            kimi_slugs=kimi_slugs,
            git_meta=git_meta,
            tracked=tracked,
            dirty=dirty,
        )
        n += 1
        if n >= max(1, min(2000, limit)):
            break

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "hints": hints,
        "count": len(hints),
    }


def skills_sync_status_payload() -> dict[str, Any]:
    settings = skills_sync_settings()
    repo = Path(str(settings["repo_root"])).expanduser().resolve()
    hermes_cfg = Path(str(settings["hermes_config_path"])).expanduser().resolve()
    desired = discover_hermes_external_dirs(repo)
    configured = _hermes_configured_dirs(hermes_cfg)
    desired_set = set(desired)
    configured_set = set(configured)
    missing_in_hermes = sorted(desired_set - configured_set)
    extra_in_hermes = sorted(configured_set - desired_set)
    missing_on_disk: list[str] = []
    for d in configured:
        p = Path(d).expanduser()
        if not p.is_dir():
            missing_on_disk.append(d)

    skill_paths_repo = _collect_skill_md_under_repo(repo)
    git_meta = _git_branch_status(repo)

    home = Path.home()
    cursor_global = _scan_agent_global_skills(home / ".cursor")
    claude_global = _scan_agent_global_skills(home / ".claude")
    kimi_global = _scan_agent_global_skills(home / ".kimi")

    state = state_index.load_state()
    skills_raw = state.get("skills") if isinstance(state.get("skills"), dict) else {}
    zab_global = 0
    zab_project = 0
    for _k, row in skills_raw.items():
        if not isinstance(row, dict):
            continue
        if str(row.get("source") or "").lower() == "workspace":
            zab_project += 1
        else:
            zab_global += 1

    projects_raw = state.get("projects") if isinstance(state.get("projects"), dict) else {}
    project_skill_files = 0
    for _pk, proj in projects_raw.items():
        if not isinstance(proj, dict):
            continue
        skills_list = proj.get("skills") or []
        if isinstance(skills_list, list):
            project_skill_files += len(skills_list)

    cfg_skill_paths = load_user_config().get("skill_md_paths")
    legacy_count = len(cfg_skill_paths) if isinstance(cfg_skill_paths, list) else 0
    reg_counts = skills_registry.registry_counts()
    adopted_like = reg_counts.get("adopted", 0) + reg_counts.get("mirrored", 0) + reg_counts.get("published", 0)
    skill_paths_configured = max(adopted_like, legacy_count)

    github_synced_hint = bool(
        git_meta.get("is_git_repo")
        and git_meta.get("upstream")
        and git_meta.get("dirty") is False
        and git_meta.get("ahead") == 0
        and git_meta.get("behind") == 0
        and bool(git_meta.get("remote_url")),
    )

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "settings": {
            "repo_root": str(repo),
            "git_remote": settings["git_remote"],
            "hermes_config_path": str(hermes_cfg),
        },
        "global_repo": {
            "repo_root": str(repo),
            "skill_md_count": len(skill_paths_repo),
            "git": git_meta,
            "github_synced_hint": bool(github_synced_hint),
        },
        "zab_index": {
            "skills_total": len(skills_raw),
            "global": zab_global,
            "project": zab_project,
            "skill_md_paths_configured": skill_paths_configured,
            "registry_counts": reg_counts,
        },
        "hermes": {
            "config_path": str(hermes_cfg),
            "config_exists": hermes_cfg.is_file(),
            "desired_external_dirs": desired,
            "configured_external_dirs": configured,
            "missing_in_hermes": missing_in_hermes,
            "extra_in_hermes": extra_in_hermes,
            "configured_dirs_missing_on_disk": missing_on_disk,
        },
        "cursor_global": cursor_global,
        "claude_global": claude_global,
        "kimi_global": kimi_global,
        "projects": {
            "projects_indexed": len(projects_raw),
            "workspace_skill_md_count": project_skill_files,
        },
    }


def _gather_scan_candidates(
    *,
    repo_root: Path,
    hermes_config: Path,
) -> tuple[list[Path], list[str]]:
    """Liste des SKILL.md à considérer + messages d'erreur non bloquants."""
    errors: list[str] = []
    seen: set[str] = set()
    out: list[Path] = []

    def add_many(paths: list[Path]) -> None:
        for p in paths:
            k = str(p.resolve())
            if k not in seen:
                seen.add(k)
                out.append(p)

    for d in _hermes_configured_dirs(hermes_config):
        p = Path(d).expanduser()
        if not p.is_dir():
            errors.append(f"hermes external_dir absent ou non répertoire: {d}")
            continue
        add_many(iter_skill_md_recursive(p))

    home = Path.home()
    add_many(iter_skill_md_recursive(home / ".cursor" / "skills"))
    add_many(iter_skill_md_recursive(home / ".claude" / "skills"))
    add_many(iter_skill_md_recursive(home / ".kimi" / "skills"))

    # évite de « réimporter » le dépôt global lui-même
    try:
        root_r = repo_root.resolve()

        def _outside_repo(p: Path) -> bool:
            try:
                p.resolve().relative_to(root_r)
                return False
            except ValueError:
                return True

        out = [p for p in out if _outside_repo(p)]
    except OSError:
        pass

    return out, errors


def _import_target_path(repo_root: Path, slug: str, org: str | None) -> Path:
    org_slug = org or "common"
    if org_slug == "common":
        return (repo_root / "common" / "skills" / slug / "SKILL.md").resolve()
    return (repo_root / "orgs" / org_slug / "skills" / slug / "SKILL.md").resolve()


def _skill_path_outside_mirror(skill_md: Path, repo_root: Path) -> bool:
    try:
        skill_md.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return True
    return False


def _auto_sync_skip_noise_path(skill_md: Path) -> bool:
    parts_lower = {x.lower() for x in skill_md.parts}
    if "hermes-docker" in parts_lower:
        return True
    norm = str(skill_md.resolve()).replace("\\", "/").lower()
    if "/templates/skill/" in norm:
        return True
    return False


def _org_slug_for_import(org: str) -> str | None:
    o = (org or "").strip()
    if not o or o == "hors-org":
        return None
    try:
        return validate_skill_slug(o)
    except SkillScaffoldError:
        return None


def auto_sync_project_skills() -> dict[str, Any]:
    """
    Importe les SKILL.md découverts sous ``projects_roots`` (workspace) vers le miroir
    ``skills_sync.repo_root``, met à jour Hermes, l'index zab, puis notifie si demandé.
    """
    settings = skills_sync_settings()
    repo_root = Path(str(settings["repo_root"])).expanduser().resolve()
    hermes_config = Path(str(settings["hermes_config_path"])).expanduser().resolve()

    imported: list[dict[str, str]] = []
    skipped: list[str] = []
    conflicts: list[dict[str, str]] = []
    errors: list[str] = []
    detected: list[dict[str, str]] = []

    existing_slugs: set[str] = set()
    for p in _collect_skill_md_under_repo(repo_root):
        existing_slugs.add(p.parent.name.casefold())

    for proj in discover_projects():
        org_raw = str(proj.get("org") or "hors-org")
        project_name = str(proj.get("name") or "")
        for row in proj.get("skills") or []:
            if not isinstance(row, dict):
                continue
            raw_p = row.get("path")
            if not isinstance(raw_p, str) or not raw_p.strip():
                continue
            src = Path(raw_p).expanduser()
            if not src.is_file() or src.name != "SKILL.md":
                continue
            if not _skill_path_outside_mirror(src, repo_root):
                skipped.append(str(src))
                continue
            if _auto_sync_skip_noise_path(src):
                skipped.append(str(src))
                continue
            if _secret_like(src):
                errors.append(f"refus (fichier sensible): {src}")
                continue

            detected.append(
                {
                    "path": str(src.resolve()),
                    "org": org_raw,
                    "project": project_name,
                }
            )

            fm_name = _frontmatter_name(src)
            slug = coerce_import_slug(skill_md=src, fm_name=fm_name)
            org_for_target = _org_slug_for_import(org_raw)
            dst = _import_target_path(repo_root, slug, org_for_target)
            try:
                dst.relative_to(repo_root)
            except ValueError:
                errors.append(f"chemin cible invalide pour {src}")
                continue

            if dst.is_file():
                try:
                    if src.resolve() == dst.resolve():
                        skipped.append(str(src))
                        continue
                    if src.read_text(encoding="utf-8") == dst.read_text(encoding="utf-8"):
                        skipped.append(str(src))
                        continue
                    conflicts.append({"slug": slug, "path": str(dst), "source": str(src)})
                    continue
                except OSError as exc:
                    errors.append(f"lecture {dst}: {exc}")
                    continue

            if slug.casefold() in existing_slugs and not dst.is_file():
                conflicts.append(
                    {"slug": slug, "path": str(dst), "source": str(src), "reason": "slug_already_in_repo"}
                )
                continue

            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                skills_registry.register_mirror_skill_path(dst)
                rec: dict[str, str] = {"slug": slug, "path": str(dst), "source": str(src)}
                if org_raw:
                    rec["org"] = org_raw
                if project_name:
                    rec["project"] = project_name
                imported.append(rec)
                existing_slugs.add(slug.casefold())
            except OSError as exc:
                errors.append(f"import {src} -> {dst}: {exc}")

    _, state = state_index.sync_state()
    summary = state_index.state_summary(state)

    hermes_apply = bool(settings.get("auto_hermes_update"))
    hermes_result = update_external_dirs(
        config_path=str(hermes_config),
        repo_root=str(repo_root),
        apply=hermes_apply,
    )
    hermes_payload = {
        "config_path": hermes_result.config_path,
        "external_dirs": hermes_result.external_dirs,
        "changed": hermes_result.changed,
        "dry_run": hermes_result.dry_run,
        "backup_path": hermes_result.backup_path,
    }

    notify = bool(settings.get("notify"))
    channel = str(settings.get("notify_channel") or "evolution")
    notification = notifications.notify_skills_auto_sync(
        slugs=[str(x.get("slug") or "") for x in imported if x.get("slug")],
        notify=notify,
        channel=channel,
    )

    return {
        "imported": imported,
        "skipped": skipped,
        "conflicts": conflicts,
        "errors": errors,
        "detected": detected,
        "hermes": hermes_payload,
        "notification": notification,
        "state_summary": summary,
    }


def scan_external_dirs_import_and_sync() -> dict[str, Any]:
    """
    Importe les SKILL.md découverts via Hermes + ~/.cursor/skills + ~/.claude/skills
    vers le dépôt global (common/skills/<slug> ou orgs/<org>/skills/<slug>),
    met à jour ``skills-registry.json`` puis régénère l’index (pas d’écriture Hermes ici).
    """
    settings = skills_sync_settings()
    repo_root = Path(str(settings["repo_root"])).expanduser().resolve()
    hermes_config = Path(str(settings["hermes_config_path"])).expanduser().resolve()

    imported: list[dict[str, str]] = []
    skipped_existing: list[str] = []
    conflicts: list[dict[str, str]] = []
    errors: list[str] = []

    candidates, gather_errs = _gather_scan_candidates(repo_root=repo_root, hermes_config=hermes_config)
    errors.extend(gather_errs)

    existing_slugs: set[str] = set()
    for p in _collect_skill_md_under_repo(repo_root):
        existing_slugs.add(p.parent.name.casefold())

    for src in candidates:
        if _secret_like(src):
            errors.append(f"refus (fichier sensible): {src}")
            continue
        fm_name = _frontmatter_name(src)
        slug = coerce_import_slug(skill_md=src, fm_name=fm_name)
        org_hint = infer_org_slug_from_path(src, repo_root)
        org_for_target: str | None = None
        if org_hint:
            try:
                org_for_target = validate_skill_slug(org_hint)
            except SkillScaffoldError:
                org_for_target = None

        dst = _import_target_path(repo_root, slug, org_for_target)
        try:
            dst.relative_to(repo_root)
        except ValueError:
            errors.append(f"chemin cible invalide pour {src}")
            continue

        if dst.is_file():
            try:
                if src.resolve() == dst.resolve():
                    skipped_existing.append(str(src))
                    continue
                if src.read_text(encoding="utf-8") == dst.read_text(encoding="utf-8"):
                    skipped_existing.append(str(src))
                    continue
                conflicts.append({"slug": slug, "path": str(dst), "source": str(src)})
                continue
            except OSError as exc:
                errors.append(f"lecture {dst}: {exc}")
                continue

        if slug.casefold() in existing_slugs and not dst.is_file():
            # autre org avec même slug dossier — évite écrasement ambigu
            conflicts.append({"slug": slug, "path": str(dst), "source": str(src), "reason": "slug_already_in_repo"})
            continue

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            skills_registry.register_mirror_skill_path(dst)
            imported.append({"slug": slug, "path": str(dst), "source": str(src)})
            existing_slugs.add(slug.casefold())
        except OSError as exc:
            errors.append(f"import {src} -> {dst}: {exc}")

    _, state = state_index.sync_state()
    summary = state_index.state_summary(state)
    return {
        "imported": imported,
        "skipped_existing": skipped_existing,
        "conflicts": conflicts,
        "errors": errors,
        "state_summary": summary,
    }


def github_sync_explicit(*, message: str | None = None) -> dict[str, Any]:
    """Commit tout changement puis push explicite vers origin."""
    msg = (message or "skill: dashboard sync").strip() or "skill: dashboard sync"
    result = commit_and_push(None, msg, push=True)
    return {
        "repo_root": result.repo_root,
        "committed": result.committed,
        "pushed": result.pushed,
        "error": result.error,
    }
