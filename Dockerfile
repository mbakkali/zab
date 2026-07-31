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
RUN useradd --create-home --uid 1001 app \
    && mkdir -p /home/app/.config/zab /home/app/.local/share/zab \
    && chown -R app:app /home/app
USER app
ENV HOME=/home/app

# Cloud Run impose le port par la variable PORT et exige une écoute sur 0.0.0.0.
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "exec zab vm serve --host 0.0.0.0 --port ${PORT}"]
