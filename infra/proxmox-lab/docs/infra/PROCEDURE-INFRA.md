# Procédure d'installation de l'infrastructure — PROJECT RESILIENCE-ALPHA

> Pilier INFRASTRUCTURE · Proxmox VE 9.2 · Debian 13 · Docker Compose · Ansible · Prometheus / Grafana / Loki
> Cette procédure permet de **reconstruire toute la plateforme** à partir du dépôt.
> État au 19/10/2026 : phases 0 à 9 **réalisées et vérifiées**, phases 10 à 12 **à faire** (dépendent de pfSense et de la VM-SIEM).

---

## Sommaire

| Phase | Contenu | État |
|---|---|---|
| 0 | Prérequis, inventaire Proxmox | ✅ |
| 1 | Préparation des VM dans Proxmox | ✅ |
| 2 | Amorçage des VM (compte `ansible`, clés SSH) | ✅ |
| 3 | Nœud de contrôle vm-ops (Ansible, SOPS, age) | ✅ |
| 4 | Secrets chiffrés (SOPS + age) | ✅ |
| 5 | Jeton API Proxmox restreint pour la remédiation | ✅ |
| 6 | Déploiement complet (`site.yml`) | ✅ |
| 7 | Redémarrage : IP statiques, IPv6 coupé, agent QEMU | ✅ |
| 8 | Recette de l'infrastructure (`verify.yml`) | ✅ |
| 9 | Snapshot de référence et tests de remédiation | ✅ |
| 10 | Réseau v2 : pfSense (WAN / LAN / DMZ) — **Yohan** ; 2e carte de vm-app — infra | ⏳ |
| 11 | Pare-feu Proxmox (filtrage entre VM) | ➖ non appliqué (décision équipe) |
| 12 | Intégration VM-SIEM (Graylog) | ⏳ |
| — | Exploitation courante, dépannage | 📘 |

---

## Architecture déployée

```
                        PC ATTAQUANT 192.168.137.x
                                  │ WAN (Wi-Fi hôte 192.168.137.0/24)
                         ┌────────┴────────┐
                         │  FW-PFSENSE     │  WAN 192.168.137.2 · LAN 192.168.1.1 · DMZ 192.168.10.1
                         └───┬─────────┬───┘  NAT WAN:443 -> 192.168.10.24:443          (phase 10)
                       LAN   │         │ DMZ 192.168.10.0/24
 ┌───────────────────────────┴──┐   ┌──┴──────────────────────────────┐
 │ LAN 192.168.1.0/24 (vmbr0)   │   │ vm-app eth1 192.168.10.24 (WAF) │
 └──────────────────────────────┘   └─────────────────────────────────┘

 vm-app  192.168.1.24   WAF BunkerWeb (+ scheduler) :80→:443 · gateway · frontend:8080 · api:8000 · auth:8001 · PostgreSQL
 vm-obs  192.168.1.142  Prometheus :9090 · Alertmanager :9093 · Loki :3100 · Grafana :3000 · blackbox
 vm-ops  192.168.1.151  Ansible · exécuteur de remédiation · Vault :8200 · (moteur :8080, dashboard :5173 = DEV)
 vm-ia   192.168.1.152  Ollama :11434 · (détecteur ML :8500, RAG :8501 = IA)
 vm-sauv 192.168.1.9    Réception des sauvegardes en écriture seule
 Sur chaque VM : node-exporter :9100 · cAdvisor :8081 · Grafana Alloy :12345 (logs + métriques)

 Hors périmètre défensif (non gérés par Ansible) :
 vm-attack 209  Windows 11 · PC Attaquant Red Team · à basculer sur le bridge WAN
 vm-siem   206  Graylog (SIEM) · configuré par le pilier Cyber
```

> **vm-attack et vm-siem ne sont pas dans l'inventaire Ansible.** L'inventaire ne contient que les
> VM défensives Linux pilotées par SSH. vm-attack est un poste Windows **adverse** : l'instrumenter
> serait un contresens (on ne défend pas la machine qui attaque). vm-siem relève du pilier Cyber.
> Les deux sont documentées ici et sur le schéma, mais Ansible ne les touche jamais.

**Rôle de chaque outil**

| Outil | Rôle dans le déploiement | Rôle dans la reprise |
|---|---|---|
| **Proxmox** | Héberge les VM, isole les réseaux (bridges) | Snapshot `baseline-sain`, rollback de vm-app en ~65 s |
| **Docker Compose** | Décrit chaque stack (app, obs, agents, ops, ia) | `restart` / `recreate` d'un service, conteneurs relancés au boot |
| **Ansible** | Installe et configure les 5 VM de façon idempotente (`site.yml`) | Playbooks de remédiation exécutés par le moteur, puis vérification métier |
| **Prometheus + blackbox** | Métriques des VM, conteneurs, base, sondes HTTPS via le WAF | Règles d'alerte qui déclenchent la remédiation |
| **Loki + Alloy** | Centralise les logs Docker et le journal systemd de toutes les VM | Règles SIEM (WAF, rafales, SSH, actions refusées) |
| **Alertmanager** | — | Envoie les alertes `remediation=*` au moteur (webhook authentifié) |
| **Grafana** | Dashboard « Resilience-Alpha — Vue d'ensemble » | Montre l'état avant / pendant / après l'incident |

---

## Phase 0 — Prérequis

| Élément | Valeur |
|---|---|
| Hyperviseur | Proxmox VE 9.2, nœud `pve`, `https://192.168.1.89:8006` |
| Ressources hôte | 12 cœurs, ~157 Go RAM, stockage `local-lvm` (thin, snapshots possibles) |
| Réseau | `vmbr0` sur `nic0`, LAN 192.168.1.0/24, passerelle actuelle 192.168.1.254 (Freebox) |
| Carte libre | `nic1` (prévue pour le WAN pfSense / lien PC Hôte) |
| VM | 200 vm-app · 201 vm-obs · 202 vm-ops · 203 vm-ia · 204 vm-sauv (Debian 13.5) |
| Poste d'admin | Accès par WireGuard (192.168.27.0/24), clé SSH ed25519 |

Inventaire rapide via l'API (depuis le poste d'admin) :

```bash
# Ticket d'authentification (le mot de passe n'est jamais écrit dans un fichier du dépôt)
curl -sk -d 'username=root@pam' --data-urlencode "password=$PVE_PASS" \
  https://192.168.1.89:8006/api2/json/access/ticket
curl -sk -H "Cookie: PVEAuthCookie=$TICKET" \
  https://192.168.1.89:8006/api2/json/cluster/resources?type=vm
```

---

## Phase 1 — Préparation des VM dans Proxmox

Dans **Proxmox > VM > Matériel / Options** (ou via l'API) :

1. **Agent QEMU** activé sur 200 à 204 (`Options > QEMU Guest Agent = Oui`). Il permet des snapshots cohérents.
2. **vm-ia (203)** : passage à **6 vCPU / 16 Go**, nécessaires pour un LLM de 7 à 8 milliards de paramètres sur CPU.
3. Carte réseau `net0` sur `vmbr0` avec `firewall=1`, déjà le cas sur toutes les VM.

```bash
# Équivalent shell Proxmox
qm set 200 --agent 1   # idem 201 202 204
qm set 203 --agent 1 --cores 6 --memory 16384
```

> Ces changements ne s'appliquent qu'après un **redémarrage depuis Proxmox** (phase 7) : un reboot lancé depuis l'invité ne suffit pas.

⚠️ **À faire** : retirer les mots de passe écrits dans le champ *Notes* des VM. Ils sont lisibles par toute personne ayant accès à Proxmox.

---

## Phase 2 — Amorçage des VM

L'objectif est d'obtenir, sur chaque VM, un compte `ansible` avec `sudo` sans mot de passe, accessible **uniquement par clé**.
C'est la seule étape manuelle. Tout le reste passe par Ansible.

Sur chaque VM (console Proxmox ou SSH avec le compte créé à l'installation), **en root** :

```bash
apt-get update && apt-get install -y sudo python3
useradd -m -s /bin/bash ansible
install -d -m700 -o ansible -g ansible /home/ansible/.ssh
cat >> /home/ansible/.ssh/authorized_keys <<'EOF'
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIElkJ1vo6jtMWvQckSmcIUbqhjDmZDHMS88TUn1CkhCk papis@pc
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDQxHiR+W4sFO/Oz7JRSNgFKxfy3MFgr8wbhu/6qw2ML ansible@vm-ops
EOF
chown ansible: /home/ansible/.ssh/authorized_keys && chmod 600 /home/ansible/.ssh/authorized_keys
echo 'ansible ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/ansible && chmod 440 /etc/sudoers.d/ansible
```

La clé `ansible@vm-ops` est générée sur vm-ops (`ssh-keygen -t ed25519`, phase 3). Pour ajouter un membre de l'équipe, mettez sa clé publique dans `ssh_admin_keys` (`inventory/group_vars/all/main.yml`) puis relancez `site.yml`.

✅ **Vérification** (depuis vm-ops) : `for h in 24 142 152 9; do ssh ansible@192.168.1.$h hostname; done`

---

## Phase 3 — Nœud de contrôle vm-ops

```bash
ssh ansible@192.168.1.151
sudo apt-get install -y ansible git age openssl curl python3-proxmoxer
curl -fsSLo /tmp/sops.deb https://github.com/getsops/sops/releases/download/v3.13.3/sops_3.13.3_amd64.deb
sudo dpkg -i /tmp/sops.deb
ssh-keygen -t ed25519 -N "" -C ansible@vm-ops -f ~/.ssh/id_ed25519   # si absente

# Dépôt
sudo mkdir -p /opt/resilience/repo && sudo chown ansible: /opt/resilience/repo
git clone <URL_DU_DEPOT> /opt/resilience/repo        # ou copie : tar | ssh
```

Versions validées : ansible-core 2.19.11 (paquet Debian `ansible` 12), SOPS 3.13.3, age 1.2.1.

---

## Phase 4 — Secrets chiffrés (SOPS + age)

Aucun secret n'est en clair dans le dépôt : `ansible/secrets/secrets.sops.yml` est chiffré.
Ansible le déchiffre **à la demande**, avec `lookup('community.sops.sops')` dans `group_vars`.

```bash
# 1. Clé age de vm-ops (À SAUVEGARDER dans le coffre de l'équipe : sans elle, secrets irrécupérables)
mkdir -p ~/.config/sops/age && age-keygen -o ~/.config/sops/age/keys.txt
grep 'public key' ~/.config/sops/age/keys.txt     # -> à mettre dans .sops.yaml

# 2. Génération des secrets aléatoires puis chiffrement
cd /opt/resilience/repo/ansible/secrets
r(){ openssl rand -base64 32 | tr -d '/+=' | cut -c1-32; }
umask 077; cat > secrets.sops.yml <<EOF
postgres_password: $(r)
grafana_admin_password: $(r)
alert_webhook_token: $(r)
synthetic_probe_token: $(r)
pve_remediation_token_id: remediation@pve!ops
pve_remediation_token_secret: <secret du jeton créé en phase 5>
EOF
sops -e -i secrets.sops.yml

# Consulter / modifier
sops -d secrets.sops.yml          # affichage en clair (ne pas copier ailleurs)
sops secrets.sops.yml             # édition
```

Pour donner l'accès à un autre membre, ajoutez sa clé publique age dans `.sops.yaml`, puis lancez `sops updatekeys ansible/secrets/secrets.sops.yml`.

---

## Phase 5 — Jeton API Proxmox restreint

Le moteur de remédiation peut ramener vm-app à un snapshot sain, **et rien d'autre**.

```bash
# Shell du nœud Proxmox (ou équivalent API)
pveum role add RARemediation -privs "VM.Audit VM.Snapshot VM.Snapshot.Rollback VM.PowerMgmt"
pveum user add remediation@pve --comment "Moteur de remediation Resilience-Alpha"
pveum user token add remediation@pve ops --privsep 1        # noter le secret -> phase 4
pveum acl modify /vms/200 --roles RARemediation --users remediation@pve --tokens 'remediation@pve!ops'
```

✅ Le jeton n'a de droits que sur `/vms/200` : il ne peut ni lire ni toucher les autres VM, ni Proxmox lui-même.

---

## Phase 6 — Déploiement complet

```bash
cd /opt/resilience/repo/ansible
ansible-playbook playbooks/site.yml              # ~8 min la 1re fois, ~2 min ensuite
ansible-playbook playbooks/site.yml --limit app  # une seule VM
```

| Play | Rôle | Ce qu'il fait |
|---|---|---|
| toutes | `base` | Nom d'hôte, `/etc/hosts`, DNS, fuseau, chrony, journal persistant, IPv6 coupé, IP statique, durcissement SSH |
| toutes | `docker` | Dépôt officiel Docker, Engine + Compose, logs limités (10 Mo × 3), `live-restore` |
| toutes | `agents` | node-exporter, cAdvisor (:8081), Grafana Alloy (logs Docker et journal vers Loki ; métriques des conteneurs vers Prometheus) |
| vm-ops | `ops` | Clé SSH `remediator`, jetons, image `ra/remediation-runner`, Vault |
| vm-obs | `obs` | Prometheus, Alertmanager, Loki (+ ruler SIEM), Grafana (provisionné), blackbox |
| vm-app | `app` | WAF **BunkerWeb 1.6** (ModSecurity + CRS v4, bannissement auto, anti-DoS, HTTPS), gateway nginx, frontend/api/auth, PostgreSQL + exporter |
| vm-ia | `ia` | Ollama (modèles listés dans `ollama_models`) |
| vm-app + vm-sauv | `backup` | Dump PostgreSQL validé toutes les 5 min, copie en **écriture seule** vers vm-sauv |
| vm-app | `remediation_access` | Compte `remediator`, script `ra-remediate` (liste blanche), sudo limité |

Le playbook est **idempotent** : le relancer ne change rien si la configuration n'a pas bougé (vérifié).

---

## Phase 7 — Redémarrage depuis Proxmox

Ce redémarrage applique l'IP statique (DHCP vers statique, vm-ops passe en .151), la coupure d'IPv6 (la Freebox distribuait de l'IPv6 public), l'agent QEMU et les ressources de vm-ia.

```bash
for id in 200 201 203 204 202; do qm reboot $id; done     # vm-ops en dernier
```

✅ Vérification : `ssh ansible@192.168.1.151 'hostname -I; nproc'`. Tous les conteneurs repartent seuls (`restart: unless-stopped`).

> **Piège rencontré** : ne jamais recharger un conteneur avec `docker kill -s HUP`. Docker le considère alors comme arrêté manuellement et ne le relance plus au boot. Le rôle `obs` utilise `docker exec <c> kill -HUP 1`.

---

## Phase 8 — Recette de l'infrastructure

```bash
ansible-playbook playbooks/verify.yml
```

Contrôles automatiques :
1. Prometheus, Alertmanager, Loki et Grafana prêts.
2. Toutes les cibles Prometheus `up` (seul `ml-detector` est attendu en échec tant que l'IA n'a pas livré).
3. Le SI répond **via le WAF en HTTPS** (`/`, `/api/health`, `/auth/health`).
4. Le WAF **bloque une injection SQL** (HTTP 403).
5. Loki reçoit des journaux des 5 VM.
6. Le compte `remediator` peut lancer `ra-remediate` mais **pas** `docker`.

Accès manuels :

| Interface | URL | Identifiants |
|---|---|---|
| Grafana | http://192.168.1.142:3000 | `admin` / `sops -d ... grafana_admin_password` |
| Prometheus | http://192.168.1.142:9090 | — (réservé admin, phase 11) |
| Alertmanager | http://192.168.1.142:9093 | — |
| SI (via WAF) | https://192.168.1.24 | certificat auto-signé |
| UI BunkerWeb | http://192.168.1.24:7000 | admin / voir coffre |
| Vault | http://192.168.1.151:8200 | token (voir coffre) |

---

## Phase 9 — Snapshot de référence et tests de remédiation

### 9.1 Snapshot `baseline-sain`

À refaire **après chaque changement validé** de vm-app, et en tout cas jeudi avant le gel du code :

```bash
qm delsnapshot 200 baseline-sain ; qm snapshot 200 baseline-sain --description "Etat sain de reference"
```

### 9.2 Chaîne de remédiation

```
Alertmanager --webhook Bearer--> moteur (vm-ops:8080, DEV) --ansible-playbook--> SSH remediator@vm-app
                                                                                   └─ sudo ra-remediate <action> (liste blanche, journalisée)
                                                                                   └─ vérification HTTPS via le WAF (+ transaction fictive)
```

L'exécuteur `ra/remediation-runner` contient Ansible, mais **ni socket Docker, ni secret d'administration**. Il ne dispose que de :
- la clé `remediator` (refusée si elle ne vient pas de vm-ops) ;
- le jeton Proxmox restreint à la VM 200.

```bash
R="sudo docker run --rm --network host -v /opt/resilience/repo/ansible:/work:ro \
   -v /opt/resilience/ops/keys:/opt/resilience/ops/keys:ro ra/remediation-runner"
$R ansible-playbook remediation/restart.yml   -e service=api
$R ansible-playbook remediation/recreate.yml  -e service=gateway
$R ansible-playbook remediation/isolate.yml   -e service=api       # preuves + conteneur neuf
$R ansible-playbook remediation/block_ip.yml  -e ip=192.168.137.42
$R ansible-playbook remediation/unblock_ip.yml -e ip=192.168.137.42
$R ansible-playbook remediation/restore_db.yml                      # dernier dump validé
$R ansible-playbook remediation/rollback_vm.yml                     # snapshot baseline-sain
```

| Playbook | Type d'incident | Résultat du test (19/10) |
|---|---|---|
| `restart` | Disponibilité | ✅ api rétablie, HTTP 200 vérifié |
| `restart -e service=vault` | Action non autorisée | ✅ refusée par l'assertion |
| `block_ip` / `unblock_ip` | DoS, injection | ✅ bannissement / levée via `bwcli` (API BunkerWeb), sans coupure |
| `recreate -e service=gateway` | Conteneur corrompu | ✅ gateway neuf, BunkerWeb le rejoint sans redémarrage |
| `ra-remediate block-ip 192.168.1.142` | Blocage d'une IP interne | ✅ refusé et journalisé (`REFUS`) |
| `rollback_vm` | Compromission de l'hôte | ✅ VM restaurée et service vérifié en **65 s** |

Correspondance alertes → actions (labels posés dans `alerts.yml` / `securite.yml`) :

| Alerte | Source | `remediation` |
|---|---|---|
| ServiceIndisponible, PostgresIndisponible, TauxErreurs5xxEleve | Prometheus | `restart` |
| TransactionSynthetiqueEnEchec | blackbox (transaction fictive) | `restart` |
| ConteneurDisparu | cAdvisor | `recreate` |
| AttaqueApplicativeBloqueeParWAF, RafaleDeRequetes | Loki (logs WAF) | `block_ip` |
| AnomalieDetecteeML | détecteur ML | `auto` (le moteur choisit selon `scenario`) |
| SauvegardeTropAncienne, CPU, mémoire, disque, SSH | Prometheus / Loki | `none` (information) |

### 9.3 Sauvegardes

- `ra-backup-db.timer` sur vm-app, toutes les **5 min** (RPO 5 min). Chaque dump est **relu** (`pg_restore --list`) avant d'être conservé.
- Copie vers `vm-sauv:/srv/backups/vm-app` avec `rrsync -wo -no-del` : vm-app **peut écrire mais ne peut ni lire ni effacer** les sauvegardes. Un attaquant qui contrôle vm-app ne peut donc pas détruire l'historique.
- Métrique `ra_backup_last_success_timestamp_seconds`, avec l'alerte `SauvegardeTropAncienne` au-delà de 15 min.

```bash
ssh ansible@192.168.1.24 'sudo systemctl list-timers ra-backup-db.timer; sudo ls /var/backups/resilience/db'
ssh ansible@192.168.1.9  'sudo ls /srv/backups/vm-app'
```

---

## Phase 10 — Réseau v2 : pfSense, WAN, DMZ ⏳

Objectif (schéma v2) : PC Attaquant → pfSense WAN `192.168.137.2:443` → NAT → WAF `192.168.10.24:443` (DMZ).
Avantage : le WAF voit la **vraie IP de l'attaquant**, donc `block_ip` est efficace.

1. **Bridges Proxmox** (`Système > Réseau`) :
   - `vmbr1` : **DMZ**, sans port physique ;
   - `vmbr2` : **WAN**, sur `nic1`, relié au réseau du PC Hôte et du point d'accès 192.168.137.0/24.
2. **pfSense** : `net0` WAN → `vmbr2` (192.168.137.2), `net1` LAN → `vmbr0` (192.168.1.1), `net2` OPT1/DMZ → `vmbr1` (192.168.10.1).
   - ⚠️ **Désactiver le serveur DHCP de pfSense sur le LAN** (*Services > DHCP Server > LAN > Enable* décoché) : 192.168.1.0/24 est aussi le réseau de la Freebox. Contrôle du 19/10 : seule la Freebox (.254) répond aux requêtes DHCP. Commande de vérification :
     `sudo docker run --rm --net host instrumentisto/nmap --script broadcast-dhcp-discover`
3. **vm-app** : ajouter `net1` sur `vmbr1` (`qm set 200 --net1 virtio,bridge=vmbr1,firewall=1`), puis dans `main.yml` :
   ```yaml
   waf_dmz_enabled: true      # le WAF écoute aussi sur 192.168.10.24:443
   ```
   puis ajouter l'interface `ens19` en 192.168.10.24/24 **sans passerelle** dans le rôle `base`, et relancer `site.yml --limit app`.
4. **Règles pfSense** : NAT WAN:443 → 192.168.10.24:443 ; DMZ → LAN interdit ; LAN → DMZ:443 autorisé ; envoi des logs vers Graylog :1514.
5. **Passerelle du LAN** : ne passer `lan_gateway` à `192.168.1.1` qu'une fois pfSense routé vers Internet **et** vers le tunnel WireGuard (sinon on perd l'accès distant aux VM).
6. Refaire le snapshot `baseline-sain` (phase 9.1).

---

## WAF BunkerWeb (vm-app)

BunkerWeb a remplacé l'image ModSecurity seule. Il se compose de deux conteneurs :
- `ra-waf` : l'instance nginx durcie, exposée en :80 (redirection) et :443 ;
- `ra-bw-scheduler` : il porte **toute** la configuration (variables d'environnement) et la pousse à l'instance par son API interne :5000, sur le réseau `ra_bw_universe` (10.20.30.0/24).

| Protection | Réglage | Effet |
|---|---|---|
| ModSecurity + OWASP CRS v4 | `USE_MODSECURITY=yes` | Injections SQL, XSS... bloquées (403), log `ModSecurity: Access denied ... [client IP]` |
| Bad behavior | 10 erreurs 4xx en 60 s, ban 1 h | **Réponse automatique native** : l'attaquant est banni par le WAF lui-même |
| Limitation de débit | `20r/s` par IP | Atténue le DoS (HTTP 429) |
| Liste blanche | vm-obs | Les sondes de supervision ne sont jamais bannies |
| HTTPS | certificat auto-signé | Redirection HTTP→HTTPS |

Les réglages sont dans `main.yml` (`bw_*`, `waf_server_names`) et dans `roles/app/templates/docker-compose.yml.j2`. Commandes utiles :

```bash
ssh ansible@192.168.1.24 'sudo docker exec ra-bw-scheduler bwcli bans'          # IP bannies
ssh ansible@192.168.1.24 'sudo docker exec ra-bw-scheduler bwcli unban <ip>'    # levée manuelle
```

Test réalisé le 19/10 : 25 injections SQL depuis vm-ia. Résultat : 403, puis 429, puis **ban automatique** ; l'alerte Loki `AttaqueApplicativeBloqueeParWAF` arrive dans Alertmanager avec `client_ip=192.168.1.152` et `remediation=block_ip`.

---

## Phase 11 — Pare-feu Proxmox (filtrage entre VM) — décision : non appliqué

Matrice des flux à autoriser (tout le reste refusé en entrée de chaque VM) :

| Vers ↓ / port | Autorisé depuis |
|---|---|
| vm-app :443 | tous (pfSense DMZ, sondes, PC Hôte) |
| vm-app :22 | admin, vm-ops |
| vm-obs :3000 (Grafana) | admin, PC Hôte |
| vm-obs :9090 (Prometheus) | admin, vm-ops, toutes les VM (remote_write d'Alloy) |
| vm-obs :3100 (Loki) | toutes les VM (Alloy), vm-ops |
| vm-obs :9093 | admin, vm-ops |
| vm-ops :8080 (moteur) | vm-obs (Alertmanager), admin |
| vm-ops :5173 (dashboard) | admin, PC Hôte |
| vm-ops :8200 (Vault) | vm-app |
| vm-ia :11434 (Ollama) | vm-ops |
| vm-ia :8500 (ML) | vm-obs |
| vm-ia :8501 (RAG) | admin, PC Hôte |
| vm-sauv :22 | vm-app, admin |
| toutes :9100, :8081, :12345 | vm-obs |
| toutes :22 | admin, vm-ops |

**Décision de l'équipe (19/10)** : l'accès d'administration reste **ouvert à tous** pendant le workshop. Le pare-feu Proxmox n'est donc pas activé, et le filtrage d'entrée est assuré par pfSense (Yohan).
La matrice ci-dessus reste la **recommandation pour un contexte industriel**, à présenter au jury comme une limite connue du prototype.
Le filtrage se fait au niveau Proxmox, en dehors des VM : Docker ne peut donc pas le contourner, contrairement à `ufw`.

---

## Phase 12 — VM-SIEM (Graylog) ⏳

Cette phase revient au pilier Cyber. Côté infra, une piste : Alloy envoie déjà tous les logs vers Loki, et peut **en plus** les transmettre à Graylog (syslog :1514) sans agent supplémentaire.

---

## Exploitation courante

| Besoin | Commande |
|---|---|
| Redéployer / corriger la configuration | `ansible-playbook playbooks/site.yml` |
| Recette | `ansible-playbook playbooks/verify.yml` |
| État de la stack app | `ssh ansible@192.168.1.24 'cd /opt/resilience/app && sudo docker compose ps'` |
| Actions de remédiation tracées | Grafana > panneau « Actions de remédiation » ou `{syslog_identifier="ra-remediate"}` dans Loki |
| Recharger Prometheus | `curl -X POST http://192.168.1.142:9090/-/reload` |
| Brancher les images du dev | `app_images` + `app_placeholder: false` dans `main.yml`, puis `site.yml --limit app` |
| Activer la transaction de contrôle | `synthetic_probe_enabled: true` (et `synthetic_check: true` dans `remediation/inventory.yml`) |

## Dépannage

| Symptôme | Cause / solution |
|---|---|
| `apt` : « Erreur temporaire de résolution » après reboot | `/etc/resolv.conf` vidé par dhcpcd lors du passage en IP statique ; relancer `site.yml` (la tâche DNS passe en premier) |
| Conteneur non relancé au boot | Il a été arrêté ou tué manuellement : `docker compose up -d` dans la stack |
| Loki répond 503 au démarrage | Normal pendant ~15 s (`Ingester not ready`) |
| Cible `ml-detector` down | Le détecteur IA n'est pas encore déployé sur vm-ia:8500 |
| `ServiceIndisponible` alors que le site répond | Tester `curl -k https://192.168.1.24/api/health` depuis vm-obs ; vérifier les bannissements : `ra-remediate bans` |
