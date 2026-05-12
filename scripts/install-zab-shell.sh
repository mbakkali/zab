#!/usr/bin/env bash
# Installe `zab` pour bash et zsh : fichier ~/.zab-shell.sh + une ligne source dans les rc.
# Sous macOS, Bash en « login shell » lit ~/.bash_profile (souvent pas ~/.bashrc) : on met aussi le source là.
# Fonctionne aussi en shell non-interactif : source ~/.zab-shell.sh
#
# Usage : ./scripts/install-zab-shell.sh [CHEMIN_REPO_ZAB]
# Défaut : répertoire parent du script (dépôt zab cloné).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${1:-$SCRIPT_DIR/..}"
REPO="$(cd "$REPO" && pwd)"

LOADER="$HOME/.zab-shell.sh"
MARKER="# zab-loader (source ~/.zab-shell.sh)"

cat >"$LOADER" <<EOF
# Généré par scripts/install-zab-shell.sh — ne pas commiter
export ZAB_REPO="$REPO"
# Racine skills : par défaut zab utilise le cwd (répertoire où tu lances la commande).
# Pour une racine fixe : export ZAB_SKILLS_ROOT=/chemin/vers/skills ou skills_root dans ~/.config/zab/config.yaml
zab() {
  local _zab_from="\$PWD"
  (cd "\$ZAB_REPO" && env ZAB_INVOCATION_CWD="\$_zab_from" uv run zab "\$@")
}
EOF
chmod 600 "$LOADER" 2>/dev/null || true
echo "Écrit : $LOADER"

append_source() {
  local rcfile="$1"
  [[ -f "$rcfile" ]] || touch "$rcfile"
  if grep -qF "$MARKER" "$rcfile" 2>/dev/null; then
    echo "Déjà référencé : $rcfile"
    return 0
  fi
  {
    echo ""
    echo "$MARKER"
    echo '[ -f "$HOME/.zab-shell.sh" ] && . "$HOME/.zab-shell.sh"'
  } >>"$rcfile"
  echo "Mis à jour : $rcfile"
}

append_source "$HOME/.bashrc"
append_source "$HOME/.bash_profile"
append_source "$HOME/.zshrc"

echo ""
echo "Configuration utilisateur (~/.config/zab/config.yaml)…"
(
  cd "$REPO"
  uv run python -c "from zab.user_config import ensure_user_config_exists; p = ensure_user_config_exists(); print('  Créé :', p) if p else print('  Déjà présent : ~/.config/zab/config.yaml')"
)

echo ""
echo "Nouveau terminal (ou : source ~/.bash_profile  /  source ~/.zshrc) : zab doctor"
echo "Immédiat dans ce terminal : source \"\$HOME/.zab-shell.sh\""
echo "Scripts non-interactifs : source \"\$HOME/.zab-shell.sh\" && zab doctor"
echo "Si la commande zab d'un autre .venv apparaît avant cette fonction : désinstalle-la (pip uninstall zab) ou vérifie votre PATH."
echo "Optionnel : export ZAB_SKILLS_ROOT=/chemin/fixe pour forcer la racine skills."
