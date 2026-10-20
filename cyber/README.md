# cyber

`waf`, `attack` et gestion des secrets. Rôle de chacun : [Services](../doc/ARCHITECTURE.md#services). Choix de sécurité et privilèges de la remédiation : [ARCHITECTURE](../doc/ARCHITECTURE.md#sécurité--pourquoi-le-cloisonnement).

## waf

nginx + ModSecurity (CRS) devant l'API. Il pose `X-Forwarded-For` (utilisé par l'API et le SIEM pour désigner l'attaquant) et applique la liste de blocage écrite par `remediation`.

## attack

Scripts d'attaque lancés depuis le **PC attaquant**, uniquement vers notre plateforme. Hors périmètre : réseaux du campus, autres groupes, services tiers. Toute expérience susceptible de sortir du périmètre s'interrompt et se signale au coach.

## Secrets

Aucun secret en clair dans le dépôt.

- **Dev local (mono-hôte)** : `scripts/init-local.sh` génère des secrets aléatoires dans `.secrets/` (ignoré par git). Ni SOPS ni clé requis.
- **Déploiement partagé (VM, démo)** : SOPS + age.
  1. Chaque membre : `age-keygen -o ~/.config/sops/age/keys.txt`, puis ajoute sa clé **publique** dans `.sops.yaml`.
  2. Les secrets vivent dans `cyber/secrets/secrets.enc.yaml` (chiffré, versionnable). Édition : `sops cyber/secrets/secrets.enc.yaml`.
  3. `scripts/decrypt-secrets.sh` écrit un fichier par secret dans `.secrets/`, lu par `secrets:` du compose.
- Clés attendues : `db_password`, `jwt_secret`, `engine_token`, `grafana_admin_password`, `canary_password` (mot de passe du compte `canary`, lu par `auth` et par `canary`), et `ansible_ssh_key` **uniquement** en `REMEDIATION_MODE=ssh`.
