# VM-OPS : --build-arg BASE_IMAGE=ra/remediation-runner (Ansible, community.proxmox et client SSH déjà dedans).
# Local / CI : python:3.12-slim, éventuellement avec WITH_ANSIBLE=1 (ancien mode ssh).
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

# ra/remediation-runner tourne en non-root : pip doit installer en root (systeme), sinon uvicorn atterrit hors du PATH.
USER root

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Inutile avec ra/remediation-runner. Sur l'image Python seule, WITH_ANSIBLE=1 ajoute Ansible (remediation-ssh.yml).
ARG WITH_ANSIBLE=0
RUN if [ "$WITH_ANSIBLE" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends openssh-client \
      && pip install --no-cache-dir ansible-core==2.17.6 && rm -rf /var/lib/apt/lists/*; \
    fi

COPY app ./app
# Le journal d'incidents est un volume : le dossier doit appartenir a l'utilisateur non-root.
# Idem pour la liste de blocage partagee avec le WAF (mode local).
# /work (playbooks) et les cles sont montes en lecture seule par le compose de l'infra, pas copies dans l'image.
# VM-OPS : --build-arg APP_USER=runner (uid 10001, proprietaire des cles dans ra/remediation-runner, qui est non-root
# d'origine : il faut repasser root le temps de preparer les dossiers).
ARG APP_USER=remediation
USER root
RUN id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --no-create-home "$APP_USER"
RUN mkdir -p /var/lib/resilience/incidents /etc/waf/blocklist     && chown "$APP_USER" /var/lib/resilience/incidents /etc/waf/blocklist
USER ${APP_USER}

# Port d'ecoute reglable : l'infra publie le moteur sur :8080 (webhook Alertmanager), le mono-hote reste sur 8000.
ENV PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=3   CMD python -c "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'], timeout=2)"

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-access-log"]
