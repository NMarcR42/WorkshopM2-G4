# VM-OPS : --build-arg BASE_IMAGE=ra/remediation-runner (Ansible, community.proxmox et client SSH déjà dedans).
# Local / CI : python:3.12-slim, éventuellement avec WITH_ANSIBLE=1 (ancien mode ssh).
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

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
RUN useradd --system --no-create-home remediation \
    && mkdir -p /var/lib/resilience/incidents /etc/waf/blocklist \
    && chown remediation /var/lib/resilience/incidents /etc/waf/blocklist
USER remediation

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
