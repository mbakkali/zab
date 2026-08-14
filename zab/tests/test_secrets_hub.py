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


def test_mirror_ne_touche_jamais_au_fichier_local(monkeypatch, tmp_path):
    from zab.services import secrets_hub, security_secret_sync

    names = ["QONTO_API_KEY"]
    root, cfg_dir = _setup(monkeypatch, tmp_path, tracked=names)
    _tracked_only(monkeypatch, names)
    projet = root / "app"
    projet.mkdir()
    env_projet = projet / ".env"
    env_projet.write_text("AUTRE=intact\nQONTO_API_KEY=valeur-sensible\n", encoding="utf-8")
    (cfg_dir / ".env").write_text(
        "# collecteur\nQONTO_API_KEY=valeur-sensible   # commentaire\n", encoding="utf-8"
    )
    avant_projet = env_projet.read_text(encoding="utf-8")
    avant_hub = (cfg_dir / ".env").read_text(encoding="utf-8")

    envoye: dict[str, str] = {}

    def _fake_create(variable, *, value, project=None, **_extra):
        envoye["name"] = variable["name"]
        envoye["value"] = value
        return {"ok": True, "status": "created", "secret_id": "zab-qonto-api-key"}

    monkeypatch.setattr(security_secret_sync, "create_secret", _fake_create)
    monkeypatch.setattr(security_secret_sync, "read_secret", lambda ref, **_: (None, "absent"))

    resume = secrets_hub.mirror_to_provider(apply=True)
    assert [r["status"] for r in resume["results"]] == ["mirrored"]
    assert envoye == {"name": "QONTO_API_KEY", "value": "valeur-sensible"}
    # Le point central du modèle : rien ne quitte le disque, rien n'est réécrit.
    assert env_projet.read_text(encoding="utf-8") == avant_projet
    assert (cfg_dir / ".env").read_text(encoding="utf-8") == avant_hub


def test_mirror_ne_repousse_pas_une_valeur_deja_a_jour(monkeypatch, tmp_path):
    from zab.services import secrets_hub, security_secret_sync

    names = ["QONTO_API_KEY"]
    _, cfg_dir = _setup(monkeypatch, tmp_path, tracked=names)
    _tracked_only(monkeypatch, names)
    (cfg_dir / ".env").write_text("QONTO_API_KEY=identique\n", encoding="utf-8")

    monkeypatch.setattr(security_secret_sync, "read_secret", lambda ref, **_: ("identique", ""))

    def _refuse(*_a, **_k):
        raise AssertionError("create_secret ne doit pas être appelé")

    monkeypatch.setattr(security_secret_sync, "create_secret", _refuse)
    resume = secrets_hub.mirror_to_provider(apply=True)
    assert [r["status"] for r in resume["results"]] == ["deja_a_jour"]


def test_restore_comble_un_trou_sans_ecraser_l_existant(monkeypatch, tmp_path):
    from zab.services import secrets_hub, security_secret_sync

    names = ["PRESENTE", "MANQUANTE"]
    _, cfg_dir = _setup(monkeypatch, tmp_path, tracked=names)
    _tracked_only(monkeypatch, names)
    (cfg_dir / ".env").write_text(
        "# en-tête\nPRESENTE=valeur-locale   # gardée\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        security_secret_sync, "read_secret",
        lambda ref, **_: ("depuis-le-miroir", "") if "manquante" in ref else ("autre", ""),
    )

    resume = secrets_hub.restore_from_provider(apply=True)
    par_nom = {r["name"]: r for r in resume["results"]}
    assert par_nom["PRESENTE"]["status"] == "skipped"
    assert par_nom["MANQUANTE"]["status"] == "restored"

    contenu = (cfg_dir / ".env").read_text(encoding="utf-8")
    assert "PRESENTE=valeur-locale   # gardée" in contenu   # ni la valeur ni le commentaire
    assert "# en-tête" in contenu                            # ni la structure
    assert "MANQUANTE=depuis-le-miroir" in contenu


def test_collect_preserve_commentaires_et_ordre(monkeypatch, tmp_path):
    from zab.services import secrets_hub

    names = ["DEJA_LA", "NOUVELLE"]
    root, cfg_dir = _setup(monkeypatch, tmp_path, tracked=names)
    _tracked_only(monkeypatch, names)
    (root / "app").mkdir()
    (root / "app" / ".env").write_text(
        "DEJA_LA=version-projet\nNOUVELLE=valeur-neuve\n", encoding="utf-8"
    )
    (cfg_dir / ".env").write_text(
        "# bloc du haut\nZZZ_AUTRE=intact\nDEJA_LA=version-collecteur   # ne pas perdre\n",
        encoding="utf-8",
    )

    secrets_hub.collect_to_user_dotenv(apply=True)
    contenu = (cfg_dir / ".env").read_text(encoding="utf-8")
    lignes = contenu.splitlines()
    assert lignes[0] == "# bloc du haut"
    assert lignes[1] == "ZZZ_AUTRE=intact"                      # l'ordre d'origine tient
    assert "DEJA_LA=version-collecteur   # ne pas perdre" in contenu
    assert "NOUVELLE=valeur-neuve" in contenu

    # Avec --force, la valeur est mise à jour mais le commentaire reste.
    secrets_hub.collect_to_user_dotenv(force=True, apply=True)
    contenu = (cfg_dir / ".env").read_text(encoding="utf-8")
    assert "DEJA_LA=version-projet   # ne pas perdre" in contenu


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


def test_mirror_couvre_tout_le_collecteur_pas_seulement_le_catalogue(monkeypatch, tmp_path):
    from zab.services import secrets_hub, security_secret_sync

    # Le catalogue suivi ne connaît qu'une des deux clés.
    _, cfg_dir = _setup(monkeypatch, tmp_path, tracked=["SUIVIE"])
    _tracked_only(monkeypatch, ["SUIVIE"])
    (cfg_dir / ".env").write_text("SUIVIE=a\nHORS_CATALOGUE=b\n", encoding="utf-8")

    vus: list[str] = []
    monkeypatch.setattr(security_secret_sync, "read_secret", lambda ref, **_: (None, "absent"))
    monkeypatch.setattr(
        security_secret_sync, "create_secret",
        lambda variable, *, value, project=None, **_extra: (
            vus.append(variable["name"]),
            {"ok": True, "status": "created", "secret_id": "x"},
        )[1],
    )

    secrets_hub.mirror_to_provider(apply=True)
    assert sorted(vus) == ["HORS_CATALOGUE", "SUIVIE"]


def test_provenance_deduite_du_chemin(monkeypatch, tmp_path):
    from zab.services import secrets_hub

    root, _ = _setup(monkeypatch, tmp_path, tracked=[])
    cas = [
        ("agileimmo-cowork/Projet_Agile/backend/.env", "agileimmo", "Projet_Agile"),
        ("flowmetrik-cowork/.env", "flowmetrik", "flowmetrik-cowork"),
        ("ipmvp/app/.env", "", "ipmvp"),
    ]
    for relatif, org, projet in cas:
        chemin = root / relatif
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text("", encoding="utf-8")
        pr = secrets_hub.provenance_de(chemin)
        assert (pr["org"], pr["project"]) == (org, projet), relatif
        assert pr["path"].endswith(relatif)


def test_le_miroir_etiquette_avec_la_provenance(monkeypatch, tmp_path):
    from zab.services import secrets_hub, security_secret_sync

    names = ["UNE_CLE"]
    root, _cfg = _setup(monkeypatch, tmp_path, tracked=names)
    _tracked_only(monkeypatch, names)
    projet = root / "acme-cowork" / "portail"
    projet.mkdir(parents=True)
    (projet / ".env").write_text("UNE_CLE=valeur\n", encoding="utf-8")

    secrets_hub.collect_to_user_dotenv(apply=True)
    assert secrets_hub.provenance_path().is_file()

    recu: dict = {}
    monkeypatch.setattr(security_secret_sync, "read_secret", lambda ref, **_: (None, "absent"))
    monkeypatch.setattr(
        security_secret_sync, "create_secret",
        lambda variable, *, value, project=None, labels=None, annotations=None: (
            recu.update(labels=labels, annotations=annotations),
            {"ok": True, "status": "created", "secret_id": "x"},
        )[1],
    )
    secrets_hub.mirror_to_provider(apply=True)

    assert recu["labels"]["zab-org"] == "acme"
    assert recu["labels"]["zab-project"] == "portail"
    assert len(recu["labels"]["zab-collected"]) == 10          # AAAA-MM-JJ
    assert recu["annotations"]["zab-source"].endswith("acme-cowork/portail/.env")
    assert recu["annotations"]["zab-mirrored-at"].endswith("Z")


def test_les_etiquettes_respectent_le_jeu_de_caracteres_gcp():
    from zab.services.security_secret_sync import sanitize_label

    assert sanitize_label("Projet_Agile") == "projet_agile"
    assert sanitize_label("suivi réglementaire") == "suivi-r-glementaire"
    assert sanitize_label("--bords--") == "bords"
    assert len(sanitize_label("x" * 200)) == 63


def test_le_filtre_retient_les_noms_de_secrets_et_annonce_le_reste(monkeypatch, tmp_path):
    from zab.services import secrets_hub

    root, _ = _setup(monkeypatch, tmp_path, tracked=[])
    _tracked_only(monkeypatch, [])
    projet = root / "acme-cowork" / "api"
    projet.mkdir(parents=True)
    (projet / ".env").write_text(
        "DB_PASSWORD=p\nSTRIPE_API_KEY=k\nDB_HOST=localhost\nDB_PORT=5432\n", encoding="utf-8"
    )

    resume = secrets_hub.mirror_projects_to_provider(apply=False)
    retenus = sorted(r["name"] for r in resume["results"])
    ecartes = sorted(e["name"] for e in resume["skipped"])
    assert retenus == ["DB_PASSWORD", "STRIPE_API_KEY"]
    # Ce qui est écarté doit être visible, pas silencieusement absent.
    assert ecartes == ["DB_HOST", "DB_PORT"]

    tout = secrets_hub.mirror_projects_to_provider(apply=False, sensitive_only=False)
    assert len(tout["results"]) == 4
    assert tout["skipped"] == []


def test_le_motif_sensible_est_surchargeable(monkeypatch, tmp_path):
    from zab.services import secrets_hub

    _setup(monkeypatch, tmp_path, tracked=[])
    assert secrets_hub.ressemble_a_un_secret("STRIPE_API_KEY") is True
    assert secrets_hub.ressemble_a_un_secret("DB_HOST") is False

    cfg = tmp_path / ".config" / "zab" / "config.yaml"
    cfg.write_text(
        yaml.safe_dump({"secret_manager": {"sensitive_name_pattern": "HOST"}}), encoding="utf-8"
    )
    assert secrets_hub.ressemble_a_un_secret("DB_HOST") is True
    assert secrets_hub.ressemble_a_un_secret("STRIPE_API_KEY") is False

    # Un motif invalide ne doit pas faire tomber la commande.
    cfg.write_text(
        yaml.safe_dump({"secret_manager": {"sensitive_name_pattern": "(unclosed"}}), encoding="utf-8"
    )
    assert secrets_hub.ressemble_a_un_secret("STRIPE_API_KEY") is True


def test_le_miroir_projet_nomme_par_projet_et_ne_confond_pas_deux_memes_cles(monkeypatch, tmp_path):
    from zab.services import secrets_hub, security_secret_sync

    root, _cfg = _setup(monkeypatch, tmp_path, tracked=[])
    _tracked_only(monkeypatch, [])
    for projet in ("api", "portail"):
        d = root / "acme-cowork" / projet
        d.mkdir(parents=True)
        (d / ".env").write_text(f"SECRET_KEY=valeur-{projet}\n", encoding="utf-8")

    recus: list[tuple[str, str]] = []
    monkeypatch.setattr(security_secret_sync, "read_secret", lambda ref, **_: (None, "absent"))
    monkeypatch.setattr(
        security_secret_sync, "create_secret",
        lambda variable, *, value, project=None, secret_id=None, labels=None, annotations=None: (
            recus.append((secret_id, value)),
            {"ok": True, "status": "created", "secret_id": secret_id},
        )[1],
    )
    secrets_hub.mirror_projects_to_provider(apply=True)

    # Deux SECRET_KEY de valeurs différentes doivent aboutir à deux secrets
    # distincts : c'est toute la raison d'être du miroir par projet.
    assert sorted(recus) == [
        ("zab-acme-api-secret-key", "valeur-api"),
        ("zab-acme-portail-secret-key", "valeur-portail"),
    ]
