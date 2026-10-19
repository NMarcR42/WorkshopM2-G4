# infra

Déploiement reproductible et observabilité. Modes de déploiement et rôles : [ARCHITECTURE](../doc/ARCHITECTURE.md#modes-de-déploiement). Outils : [STACK](../doc/STACK.md).

| Dossier / fichier | Contenu |
|---|---|
| `compose/` | Un fichier par rôle de machine (`front`, `back`, `ops`, `ai`), `agents.yml` (présent partout), et un fichier par mode de remédiation (`remediation-local.yml`, `remediation-ssh.yml`). Toujours lancés via `scripts/compose.sh`. |
| `ansible/` | `inventory/` (`local.yml` : un hôte via SSH ; `lab.yml` : multi-machines) et `playbooks/` (un playbook = une action de remédiation). Mode `ssh` uniquement. |
| `monitoring/` | `prometheus.yml`, `targets.yml` (cibles par machine), `promtail.yml`, `grafana/provisioning/`. |
| `../scripts/` | `compose.sh`, `init-local.sh` (dev), `decrypt-secrets.sh` (partagé). |
| `../.github/workflows/` | `ci.yml` (PR : secrets, composes, tests, Ansible, build) ; `deploy.yml` (manuel, runner self-hosted). |

Le `.env` documente les variables, le mode mono-hôte (défaut) et la section multi-machines à décommenter.
