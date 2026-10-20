# Image de base du moteur de remédiation : Ansible + client SSH, SANS socket Docker.
# Le moteur (pilier DEV) part de cette image : FROM ra/remediation-runner
FROM python:3.13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-client \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "ansible-core>=2.19,<2.20" proxmoxer requests \
 && ansible-galaxy collection install -p /usr/share/ansible/collections \
      community.general community.proxmox ansible.posix

RUN useradd -u 10001 -m runner
USER runner
WORKDIR /work
ENV ANSIBLE_CONFIG=/work/remediation/ansible.cfg
