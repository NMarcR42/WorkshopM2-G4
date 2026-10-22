# Partie IA — Détecter l'attaque et aider l'opérateur

## En bref

Notre plateforme de paiement doit **se rendre compte toute seule** qu'elle est attaquée, puis **aider l'opérateur** à comprendre la situation. L'IA joue ces deux rôles :

| | Le détecteur | L'assistant |
|---|---|---|
| **Sa question** | « Est-ce que quelque chose d'anormal se passe ? » | « Que se passe-t-il et que dois-je faire ? » |
| **Pour qui** | Le système (il déclenche l'alerte) | L'opérateur humain |
| **Technologie** | Machine learning (Isolation Forest) | Modèle de langage local (Ollama) + documents de l'équipe (RAG) |
| **Peut-il agir sur le système ?** | Non, il lève une alerte | Non, il donne des conseils (lecture seule) |

Tout fonctionne **en local**, sur notre propre machine : aucune donnée ne part sur Internet.

---

## 1. D'où viennent les informations ?

Pour détecter une attaque, il faut d'abord **observer** la plateforme. Deux sources sont utilisées :

- **Les métriques** (outil : Prometheus) : des chiffres mesurés en continu, par exemple le nombre de requêtes par seconde, le nombre d'erreurs ou le temps de réponse. C'est le « tableau de bord » de la plateforme.
- **Les journaux** (outil : Loki) : le texte que les services écrivent quand il se passe quelque chose, par exemple « connexion refusée ». C'est la « boîte noire » de la plateforme.

**Exemple réel observé pendant nos essais :** les journaux ont enregistré **7 connexions refusées en 20 secondes**, venant toutes du même ordinateur. Un humain ne tape pas 7 mauvais mots de passe en 20 secondes : c'est le signe d'un programme qui essaie des mots de passe à la chaîne.

---

## 2. Le détecteur : repérer ce qui sort de l'ordinaire

### L'idée

Plutôt que d'écrire des règles fixes (« au-delà de 100 requêtes, c'est une attaque »), on laisse le modèle **apprendre à quoi ressemble une journée normale**. Ensuite, tout ce qui s'en éloigne fortement est signalé.

C'est ce que le sujet demande : une détection qui **ne se réduit pas à des conditions codées en dur**.

### Pourquoi c'est mieux qu'une règle fixe

Une règle fixe est soit trop stricte (fausses alertes lors d'un pic normal d'activité), soit trop souple (une attaque discrète passe). Un modèle qui a appris le comportement normal s'adapte à la plateforme réelle.

### Comment ça marche (Isolation Forest)

1. On enregistre la plateforme pendant un fonctionnement **normal**.
2. On découpe ce temps en **petites périodes**, chacune décrite par ses chiffres (requêtes, erreurs, temps de réponse…).
3. Le modèle apprend la « forme » habituelle de ces périodes.
4. En direct, chaque nouvelle période reçoit une **note d'anomalie**. Une période très différente des autres (comme une avalanche de requêtes) est facile à **isoler**, d'où le nom de l'algorithme, et reçoit une note élevée.

### Ce qui se passe quand il détecte une attaque

```
Détecteur ─► alerte ─► moteur de remédiation ─► action (ex. bloquer l'attaquant)
                                              ─► vérification : un vrai paiement repasse
```

Le détecteur **ne répare rien lui-même** : il donne l'alerte, et c'est le moteur de remédiation qui agit.

### Nos choix concrets *[à compléter par l'équipe]*

- Mesures utilisées : …
- Durée d'apprentissage sur le trafic normal : …
- Résultat sur l'attaque de démonstration : détectée en … secondes, … fausses alertes observées.

---

## 3. Ollama : le modèle de langage sur notre machine

Ollama permet de faire tourner un modèle de langage (comme ChatGPT, mais en plus petit) **directement sur notre serveur**, sans envoyer nos données à une entreprise extérieure.

**Modèles installés :**

| Modèle | Taille | Pourquoi |
|---|---|---|
| `qwen2.5:7b` | 7,6 milliards de paramètres | Plus précis, utilisé par l'assistant |
| `llama3.2` | 3,2 milliards de paramètres | Plus léger et plus rapide, utile sur une machine sans carte graphique |

Le sujet limite la taille à **8 milliards de paramètres** : nos deux modèles respectent cette contrainte.

**Comment il répond :** on lui envoie une consigne et des faits, il renvoie une phrase.

> **Question envoyée :** « Tu es un analyste sécurité. Réponds en une phrase en commençant par ATTAQUE DETECTEE ou AUCUNE ATTAQUE. Données : 7 tentatives de connexion refusées en 20 secondes depuis le même ordinateur. »
>
> **Réponse type :** « ATTAQUE DETECTEE : plusieurs tentatives de connexion échouées en peu de temps indiquent une tentative de deviner un mot de passe. »

Sur notre machine, une réponse prend **environ 14 secondes**.

---

## 4. L'assistant : un aide-mémoire intelligent pour l'opérateur

### À quoi il sert

Pendant un incident, l'opérateur est sous pression et n'a pas le temps de fouiller toute la documentation. Il pose sa question en français, par exemple :

> « Que faire en cas de saturation du site ? »

et l'assistant lui répond **en s'appuyant sur les documents de l'équipe** : procédures, architecture, plan de reprise.

### Comment il trouve la bonne réponse (RAG)

1. **Chercher** : il retrouve dans nos documents les passages qui parlent du sujet de la question.
2. **Rédiger** : il donne ces passages au modèle de langage, qui rédige une réponse claire.

L'avantage : la réponse repose sur **nos propres procédures**, pas sur des connaissances générales que le modèle pourrait inventer.

Construit avec Ollama et LangChain, comme le demande le sujet. *[à vérifier par l'équipe]*

### Ce qu'il ne peut pas faire

- Il **ne touche à rien** : aucune commande, aucun accès privilégié au système (lecture seule).
- Il **ne remplace pas** la remédiation automatique : il conseille, il ne décide pas.

---

## 5. Difficultés rencontrées

| Difficulté | Ce qu'on a compris | Solution |
|---|---|---|
| L'assistant ne répondait pas (erreur « délai dépassé ») | Le modèle de 7,6 milliards de paramètres est trop lent sur une machine sans carte graphique, surtout à la première question | Passer au modèle plus léger `llama3.2`, ou laisser plus de temps à l'assistant pour répondre |

---

## 6. Limites honnêtes

- **Lenteur** : une réponse de l'assistant prend 10 à 30 secondes. C'est suffisant pour aider un humain, pas pour réagir en temps réel ; c'est pour ça que la réaction automatique passe par le détecteur, pas par le modèle de langage.
- **Un modèle de langage peut se tromper** : ses réponses sont des conseils, jamais des décisions.
- **Le détecteur connaît seulement ce qu'il a appris** : une attaque très différente de celle de la démonstration, ou une activité normale mais inhabituelle, peut être mal jugée.
- **Sécurité** : le service Ollama n'a pas de mot de passe ; il doit rester accessible uniquement depuis le réseau interne.

---

## Annexe technique

**Vérifier qu'Ollama fonctionne :** `http://192.168.1.152:11434` affiche « Ollama is running » ; `http://192.168.1.152:11434/api/tags` liste les modèles.

**Interroger Ollama :**

```bash
curl http://192.168.1.152:11434/api/generate -d '{"model":"llama3.2","stream":false,"prompt":"..."}'
```

**Interroger l'assistant** (documentation interactive : `http://192.168.1.152:8001/docs`) :

```bash
curl -X POST http://192.168.1.152:8001/ask -H 'Content-Type: application/json' \
     -d '{"question": "Que faire en cas de saturation HTTP ?"}'
```

**Compter les connexions SSH refusées dans Loki (dernière heure) :**

```logql
sum(count_over_time({syslog_identifier=~"sshd|sshd-session"} |~ "failed auth|Failed password|Invalid user" [1h])) or vector(0)
```
