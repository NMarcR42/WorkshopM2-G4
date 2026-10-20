# Mode d'emploi — démonstration de la reprise autonome

Ce qu'il faut montrer au jury : le service **avant** l'incident, **pendant** la perturbation,
et **après** la remédiation **automatique** (sans qu'une personne répare). Deux scénarios prêts,
tous deux **autonomes** : vous lancez l'attaque, vous ne touchez plus à rien.

> ⚠️ Règle du sujet : si une intervention corrective humaine est nécessaire pendant le live,
> l'axe remédiation reçoit 0/5. Donc **on déclenche l'incident, puis on regarde le système se réparer seul.**

---

## Avant de commencer (checklist, 2 min)

```bash
# Depuis vm-ops (ou un poste qui atteint le LAN)
cd /opt/resilience/repo/ansible && ansible-playbook playbooks/verify.yml   # tout doit être vert sauf ml-detector
```

Ouvrir en grand sur l'écran de démo :
1. **Grafana** → http://192.168.1.142:3000 → dashboard « Resilience-Alpha — Vue d'ensemble » (rafraîchi toutes les 5 s).
2. **UI BunkerWeb** → http://192.168.1.24:7000 (onglet *Bans* / logs), pour le scénario A.

Vérifier que tout est au vert (disponibilité = OK, aucune alerte), et que le trafic de fond tourne
(le panneau « requêtes WAF » n'est pas à zéro).

---

## Scénario A — Attaque applicative, blocage automatique

**Histoire** : un attaquant tente des injections SQL. Le WAF les bloque, puis **bannit l'attaquant tout seul**.
Le service reste disponible pour les vrais clients.

**Depuis le PC Attaquant (vm-attack)**, PowerShell ou navigateur :
```powershell
# 15 requêtes malveillantes vers l'API
for ($i=0; $i -lt 15; $i++) {
  curl.exe -sk -o NUL "https://192.168.1.24/api/x?q=1' OR 1=1 UNION SELECT password FROM users--"
}
```
(Depuis Linux : `for i in $(seq 1 15); do curl -sk -o /dev/null "https://192.168.1.24/api/x?q=1%27%20OR%201=1--"; done`)

**À montrer, en direct** :
- Grafana, panneau « WAF : requêtes bloquées » → pic immédiat ; alerte `AttaqueApplicativeBloqueeParWAF`.
- UI BunkerWeb → onglet *Bans* → l'**IP de l'attaquant apparaît bannie** (réponse automatique native, 1 h).
- Panneau « Actions de remédiation » → le récepteur a aussi lancé `block_ip` (défense en profondeur).
- **Preuve que le service tient** : depuis un poste légitime, `https://192.168.1.24/api/health` répond **200**,
  et l'attaquant, lui, ne passe plus (connexion refusée).

**Reset** (entre deux passages) :
```bash
ssh ansible@192.168.1.24 'sudo docker exec ra-bw-scheduler bwcli unban <IP_attaquant>'
```

---

## Scénario B — Service hors service, reprise automatique (le scénario phare)

**Histoire** : un incident rend l'API indisponible (effet d'un exploit / panne provoquée — injection de
défaillance, cf. chaos engineering du sujet). La détection le voit, la remédiation **redémarre le service
toute seule**, et une **nouvelle transaction fictive réussit**.

**Déclenchement de l'incident** (une seule commande, puis on ne touche plus à rien) :
```bash
# Représente l'effet d'une attaque réussie sur l'API
ssh ansible@192.168.1.24 'sudo docker stop ra-api'
```

**Ce qui se passe tout seul, à commenter en direct sur Grafana** :
| Temps | Événement | Où le voir |
|---|---|---|
| T+0 | API arrêtée | panneau « Disponibilité » passe au **rouge** (KO) |
| ~T+20 s | Détection : sonde `probe_success=0` → alerte `ServiceIndisponible` | panneau « Alertes en cours » |
| ~T+30 s | Décision + action : le moteur lance `restart.yml` | panneau « Actions de remédiation » |
| ~T+35 s | **Service rétabli** et **vérifié** (transaction de contrôle) | disponibilité repasse au **vert** |

Mesuré le 20/10 : **reprise complète en ~37 s, sans intervention humaine.**

**Preuve de reprise** (le jury y tient — un conteneur relancé ne suffit pas) :
```bash
curl -sk https://192.168.1.24/api/health       # -> 200 : nouvelle transaction fictive OK
```

**Reset** : aucun. Le service est déjà remonté par lui-même.

### Variante plus forte : compromission de la VM (rollback Proxmox)
Pour montrer la distinction « disponibilité » vs « compromission » :
```bash
# depuis vm-ops : rejoue le retour à l'état sain via snapshot Proxmox (jeton restreint)
sudo docker run --rm --network host -v /opt/resilience/repo/ansible:/work:ro \
  -v /opt/resilience/ops/keys:/opt/resilience/ops/keys:ro ra/remediation-runner \
  ansible-playbook remediation/rollback_vm.yml
```
Reprise vérifiée en ~65 s (VM entière restaurée depuis le snapshot `baseline-sain`).

---

## Le Clip Chrono (60 s max) — plan de tournage

Une seule prise, sans coupe (le sujet l'exige). Suggestion sur le scénario B :
1. **0–8 s** : Grafana tout vert + une transaction qui passe (l'état normal).
2. **8–15 s** : sur le PC Attaquant, lancer l'incident (montrer la commande).
3. **15–40 s** : Grafana passe au rouge (détection), puis l'action de remédiation s'affiche.
4. **40–55 s** : Grafana repasse au vert ; relancer une transaction → 200.
5. **55–60 s** : titre « Reprise automatique en 37 s — zéro intervention ».

Sous-titres autorisés pour expliquer chaque étape.

---

## Rappel du principe (pour répondre au jury)

- **Détection** : sondes blackbox (disponibilité, transaction fictive) + règles Prometheus + règles SIEM
  sur les logs Loki + (à venir) score d'anomalie ML. Pas de simple condition codée en dur.
- **Décision** : Alertmanager route les alertes portant un label `remediation` vers le moteur (webhook authentifié).
- **Action** : le moteur lance un playbook Ansible via un compte `remediator` **sans droits Docker directs**
  (liste blanche `ra-remediate`), puis **vérifie** le service (santé + transaction).
- **Limites à assumer** : le moteur de remédiation est aujourd'hui un récepteur minimal d'infra ; le DEV
  le remplace par le sien (même contrat). Services métier = bouchons tant que le DEV n'a pas livré.
