"""Tests du hub de secrets : recensement, collecte, push et pull."""

from __future__ import annotations

import yaml


def _setup(monkeypatch, tmp_path, *, tracked, projects_root=None):
    root = projects_root or (tmp_path / "projects")
    root.mkdir(parents=True, exist_ok=True)
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump({"projects_roots": [str(root)], "tracked_env_extra": list(tracked)}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setenv("ZAB_SECRET_MANAGER_PROJECT", "demo-projet")
    for name in tracked:
        monkeypatch.delenv(name, raising=False)
    return root, cfg_dir


def _tracked_only(monkeypatch, names):
    """Restreint le catalogue aux variables du test, sinon les 28 suivies polluent."""
    from zab import user_config

    monkeypatch.setattr(user_config, "tracked_env_names_for_security", lambda: tuple(names))
    from zab.services import secrets_hub

    monkeypatch.setattr(secrets_hub, "tracked_env_names_for_security", lambda: tuple(names))


def test_status_distingue_reference_clair_et_absent(monkeypatch, tmp_path):
    from zab.services import secrets_hub

    names = ["PLAIN_KEY", "REF_KEY", "ABSENT_KEY"]
    root, _ = _setup(monkeypatch, tmp_path, tracked=names)
    _tracked_only(monkeypatch, names)
    projet = root / "app"
    projet.mkdir()
    (projet / ".env").write_text(
        "PLAIN_KEY=valeur-en-clair\nREF_KEY=sm://demo-projet/deja-pose\n", encoding="utf-8"
    )

    scan = secrets_hub.scan_tracked_values(include_user_dotenv=False)
    par_nom = {row["name"]: row for row in scan["variables"]}

    assert par_nom["PLAIN_KEY"]["state"] == "plain"
    assert par_nom["REF_KEY"]["state"] == "referenced"
    assert par_nom["REF_KEY"]["reference"] == "sm://demo-projet/deja-pose"
    assert par_nom["ABSENT_KEY"]["state"] == "missing"
    assert scan["counts"] == {"referenced": 1, "plain": 1, "process": 0, "missing": 1}
    # Aucune valeur ne doit transiter par le recensement.
    assert "valeur-en-clair" not in str(scan)


def test_status_voit_une_variable_du_seul_environnement(monkeypatch, tmp_path):
    from zab.services import secrets_hub

    names = ["SHELL_ONLY_KEY"]
    _setup(monkeypatch, tmp_path, tracked=names)
    _tracked_only(monkeypatch, names)
    monkeypatch.setenv("SHELL_ONLY_KEY", "exporte-par-le-shell")

    scan = secrets_hub.scan_tracked_values(include_user_dotenv=False)
    assert scan["variables"][0]["state"] == "process"


def test_collect_fusionne_sans_ecraser_puis_avec_force(monkeypatch, tmp_path):
    from zab.services import secrets_hub

    names = ["ALPHA_KEY", "BETA_KEY"]
    root, cfg_dir = _setup(monkeypatch, tmp_path, tracked=names)
    _tracked_only(monkeypatch, names)
    (root / "un").mkdir()
    (root / "un" / ".env").write_text("ALPHA_KEY=depuis-projet\nBETA_KEY=beta\n", encoding="utf-8")
    (cfg_dir / ".env").write_text("ALPHA_KEY=valeur-deja-la\n", encoding="utf-8")

    resume = secrets_hub.collect_to_user_dotenv(apply=True)
    assert resume["keys_updated"] == ["BETA_KEY"]
    assert resume["keys_skipped_already_present"] == ["ALPHA_KEY"]
    contenu = (cfg_dir / ".env").read_text(encoding="utf-8")
    assert "ALPHA_KEY=valeur-deja-la" in contenu
    assert "BETA_KEY=beta" in contenu

    resume_force = secrets_hub.collect_to_user_dotenv(force=True, apply=True)
    assert "ALPHA_KEY" in resume_force["keys_updated"]
    assert "ALPHA_KEY=depuis-projet" in (cfg_dir / ".env").read_text(encoding="utf-8")


def test_collect_en_simulation_n_ecrit_rien(monkeypatch, tmp_path):
    from zab.services import secrets_hub

    names = ["GAMMA_KEY"]
    root, cfg_dir = _setup(monkeypatch, tmp_path, tracked=names)
    _tracked_only(monkeypatch, names)
    (root / "un").mkdir()
    (root / "un" / ".env").write_text("GAMMA_KEY=gamma\n", encoding="utf-8")

    resume = secrets_hub.collect_to_user_dotenv(apply=False)
    assert resume["keys_updated"] == ["GAMMA_KEY"]
    assert resume["applied"] is False
    assert not (cfg_dir / ".env").exists()


def test_push_remplace_la_valeur_par_sa_reference(monkeypatch, tmp_path):
    from zab.services import secrets_hub, security_secret_sync

    names = ["QONTO_API_KEY"]
    root, _ = _setup(monkeypatch, tmp_path, tracked=names)
    _tracked_only(monkeypatch, names)
    projet = root / "app"
    projet.mkdir()
    env_path = projet / ".env"
    env_path.write_text("AUTRE=intact\nQONTO_API_KEY=valeur-sensible\n", encoding="utf-8")

    pousse: dict[str, str] = {}

    def _fake_create(variable, *, value, project=None):
        pousse["name"] = variable["name"]
        pousse["value"] = value
        return {
            "ok": True,
            "status": "created",
            "secret_id": "zab-qonto-api-key",
            "secret_reference": "sm://demo-projet/zab-qonto-api-key",
        }

    monkeypatch.setattr(security_secret_sync, "create_secret", _fake_create)

    resume = secrets_hub.push_to_provider(apply=True)
    assert [r["status"] for r in resume["results"]] == ["pushed"]
    assert pousse == {"name": "QONTO_API_KEY", "value": "valeur-sensible"}

    ecrit = env_path.read_text(encoding="utf-8")
    assert "QONTO_API_KEY=sm://demo-projet/zab-qonto-api-key" in ecrit
    assert "valeur-sensible" not in ecrit
    # Le reste du fichier n'est pas touché, et rien ne traîne à côté.
    assert "AUTRE=intact" in ecrit
    assert not list(projet.glob(".env.zab-secret-tmp*"))


def test_push_en_simulation_ne_touche_pas_au_fichier(monkeypatch, tmp_path):
    from zab.services import secrets_hub

    names = ["QONTO_API_KEY"]
    root, _ = _setup(monkeypatch, tmp_path, tracked=names)
    _tracked_only(monkeypatch, names)
    projet = root / "app"
    projet.mkdir()
    env_path = projet / ".env"
    env_path.write_text("QONTO_API_KEY=valeur-sensible\n", encoding="utf-8")

    resume = secrets_hub.push_to_provider(apply=False)
    assert [r["status"] for r in resume["results"]] == ["would_push"]
    assert env_path.read_text(encoding="utf-8") == "QONTO_API_KEY=valeur-sensible\n"


def test_pull_resout_les_references_dans_la_cible(monkeypatch, tmp_path):
    from zab.services import secrets_hub, security_secret_sync

    names = ["REF_KEY"]
    root, _ = _setup(monkeypatch, tmp_path, tracked=names)
    _tracked_only(monkeypatch, names)
    projet = root / "app"
    projet.mkdir()
    (projet / ".env").write_text("REF_KEY=sm://demo-projet/le-secret\n", encoding="utf-8")

    monkeypatch.setattr(
        security_secret_sync,
        "read_secret",
        lambda reference, **_: ("valeur-restituee", "") if "le-secret" in reference else (None, "inconnue"),
    )

    cible = tmp_path / "neuf" / ".env"
    resume = secrets_hub.pull_from_provider(cible, apply=True)
    assert [r["status"] for r in resume["results"]] == ["pulled"]
    assert cible.read_text(encoding="utf-8") == "REF_KEY=valeur-restituee\n"
    # Le fichier reçoit des secrets : il ne doit pas être lisible par tous.
    assert (cible.stat().st_mode & 0o077) == 0


def test_pull_ne_recouvre_pas_une_valeur_deja_en_clair(monkeypatch, tmp_path):
    from zab.services import secrets_hub, security_secret_sync

    names = ["REF_KEY"]
    root, _ = _setup(monkeypatch, tmp_path, tracked=names)
    _tracked_only(monkeypatch, names)
    projet = root / "app"
    projet.mkdir()
    (projet / ".env").write_text("REF_KEY=sm://demo-projet/le-secret\n", encoding="utf-8")
    monkeypatch.setattr(security_secret_sync, "read_secret", lambda reference, **_: ("nouvelle", ""))

    cible = tmp_path / "cible.env"
    cible.write_text("REF_KEY=valeur-locale-choisie\n", encoding="utf-8")

    resume = secrets_hub.pull_from_provider(cible, apply=True)
    assert resume["results"][0]["status"] == "skipped"
    assert resume["results"][0]["reason"] == "deja_en_clair"
    assert cible.read_text(encoding="utf-8") == "REF_KEY=valeur-locale-choisie\n"


def test_pull_remonte_l_erreur_sans_ecrire(monkeypatch, tmp_path):
    from zab.services import secrets_hub, security_secret_sync

    names = ["REF_KEY"]
    root, _ = _setup(monkeypatch, tmp_path, tracked=names)
    _tracked_only(monkeypatch, names)
    projet = root / "app"
    projet.mkdir()
    (projet / ".env").write_text("REF_KEY=sm://demo-projet/le-secret\n", encoding="utf-8")
    monkeypatch.setattr(security_secret_sync, "read_secret", lambda reference, **_: (None, "acces_refuse"))

    cible = tmp_path / "cible.env"
    resume = secrets_hub.pull_from_provider(cible, apply=True)
    assert resume["results"][0]["status"] == "error"
    assert resume["results"][0]["reason"] == "acces_refuse"
    assert not cible.exists()


def test_reference_invalide_n_est_pas_prise_pour_une_reference():
    from zab.services import security_secret_sync as s

    assert s.is_secret_reference("sm://projet-demo/mon-secret")
    assert s.is_secret_reference("sm://mon-secret")
    # L'ancien schéma Dashlane ne doit plus être reconnu.
    assert not s.is_secret_reference("dl://Z_QONTO")
    assert not s.is_secret_reference("sm://")
    assert not s.is_secret_reference("une valeur qui contient sm:// au milieu")
    assert not s.is_secret_reference("")


def test_identifiant_de_secret_est_valide_pour_gcp(monkeypatch):
    from zab.services import security_secret_sync as s

    monkeypatch.setenv("ZAB_SECRET_MANAGER_PREFIX", "zab-")
    assert s.secret_id_for_name("QONTO_API_KEY") == "zab-qonto-api-key"
    assert s.secret_id_for_name("weird name!!") == "zab-weird-name"
    # Pas de double préfixe si le nom le porte déjà.
    assert s.secret_id_for_name("zab-deja-prefixe") == "zab-deja-prefixe"
    monkeypatch.setenv("ZAB_SECRET_MANAGER_PREFIX", "")
    assert s.secret_id_for_name("QONTO_API_KEY") == "qonto-api-key"


def test_le_commentaire_de_fin_de_ligne_survit_au_remplacement():
    from zab.services.security_secret_sync import _replace_dotenv_key

    cas = [
        # (ligne d'origine, ligne attendue)
        ("K=valeur   # rotation: scripts/rotate.py\n",
         "K=sm://p/s   # rotation: scripts/rotate.py\n"),
        ("export K=valeur # note\n", "export K=sm://p/s # note\n"),
        ("K=valeur\n", "K=sm://p/s\n"),
        # Un « # » collé à la valeur en fait partie : ce n'est pas un commentaire.
        ("K=valeur#pas-un-commentaire\n", "K=sm://p/s\n"),
        # Ni à l'intérieur de guillemets.
        ('K="valeur # dedans" # dehors\n', 'K=sm://p/s # dehors\n'),
    ]
    for origine, attendu in cas:
        obtenu, change = _replace_dotenv_key(origine, "K", "sm://p/s")
        assert change is True, origine
        assert obtenu == attendu, f"{origine!r} -> {obtenu!r} au lieu de {attendu!r}"
