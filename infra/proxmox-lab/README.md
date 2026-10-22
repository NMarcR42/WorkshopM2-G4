# PROJECT RESILIENCE-ALPHA — Workshop EPSI 2026

Plateforme de paiement fictive capable de détecter un incident de sécurité et de se rétablir **sans intervention humaine**.

## Démarrage rapide

Prérequis : 5 VM Debian 13 sous Proxmox, avec un compte `ansible` (sudo, clé SSH), et vm-ops équipée d'Ansible, SOPS et age.
Le détail est dans [docs/infra/PROCEDURE-INFRA.md](docs/infra/PROCEDURE-INFRA.md).

```bash
ssh ansible@192.168.1.151
cd /opt/resilience/repo/ansible
ansible-playbook playbooks/site.yml      # déploie toute la plateforme (idempotent)
ansible-playbook playbooks/verify.yml    # recette automatique
```

| Interface | Adresse |
|---|---|
| SI de paiement (via WAF) | https://192.168.1.24 (puis pfSense WAN 192.168.137.2) |
| Grafana | http://192.168.1.142:3000 |
| Prometheus / Alertmanager | http://192.168.1.142:9090 / :9093 |

## Arborescence

```
ansible/
  inventory/              VM, variables globales (group_vars/all/main.yml)
  secrets/                secrets.sops.yml (chiffré SOPS + age)
  playbooks/site.yml      déploiement complet
  playbooks/verify.yml    recette
  roles/                  base, docker, agents, obs, app, ops, ia, backup, remediation_access
  remediation/            playbooks exécutés par le moteur de remédiation (restart, block_ip, rollback_vm...)
docs/infra/               procédure d'installation, contrats d'interface
```

Aucun secret n'est stocké en clair dans ce dépôt.
