# Image de l'application de contrôle de VM distante (`zab vm serve`).
#
# Volontairement sans SDK cloud : le service n'a besoin que de quelques appels
# d'API, et `remote_vm` bascule sur le transport REST quand les binaires sont
# absents. L'image reste ainsi à quelques dizaines de mégaoctets, ce qui compte
# pour un démarrage à froid quand on attend depuis un téléphone.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY zab ./zab
RUN pip install --no-cache-dir .

# Utilisateur non privilégié : le service n'écrit que dans son cache de coûts.
#
# Le foyer du service est `/srv/zab`, pas un répertoire personnel : le garde-fou
# de publication signale tout chemin de foyer absolu, à raison — dans un fichier
# versionné, c'est presque toujours la trace de la machine d'un développeur. Ici
# c'était un chemin de conteneur, donc un faux positif ; le lever demandait soit
# d'affaiblir la règle, soit de ne plus écrire le motif. La seconde option ne
# coûte rien. Ce commentaire lui-même l'évite : l'écrire en toutes lettres
# suffirait à redéclencher le garde-fou.
ENV APP_HOME=/srv/zab
RUN useradd --no-create-home --uid 1001 app \
    && mkdir -p "${APP_HOME}/.config/zab" "${APP_HOME}/.local/share/zab" \
    && chown -R app:app "${APP_HOME}"
USER app
ENV HOME=${APP_HOME}

# Cloud Run impose le port par la variable PORT et exige une écoute sur 0.0.0.0.
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "exec zab vm serve --host 0.0.0.0 --port ${PORT}"]
