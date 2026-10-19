FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Ansible (lourd) n'est installe que pour le mode ssh : remediation-ssh.yml passe WITH_ANSIBLE=1.
ARG WITH_ANSIBLE=0
RUN if [ "$WITH_ANSIBLE" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends openssh-client \
      && pip install --no-cache-dir ansible-core==2.17.6 && rm -rf /var/lib/apt/lists/*; \
    fi

COPY app ./app
# Le journal d'incidents est un volume : le dossier doit appartenir a l'utilisateur non-root.
# Idem pour la liste de blocage partagee avec le WAF (mode local).
RUN useradd --system --no-create-home remediation \
    && mkdir -p /var/lib/resilience/incidents /etc/waf/blocklist \
    && chown remediation /var/lib/resilience/incidents /etc/waf/blocklist
USER remediation

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
