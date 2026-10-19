# Règles GitHub et commandes Git

> **Merger tôt, merger souvent. Jamais de secret en clair dans un commit.**

## Règles

1. **Une branche par domaine** : `dev`, `ia`, `infra`, `cyber`. On travaille sur la sienne. Pas de sous-branches du type `ia/detector` (Git l'interdit tant que `ia` existe) : si besoin, `ia-detector-v2`.
2. **`main` est protégée** : pull request obligatoire, jobs de `ci.yml` verts, au moins une relecture, ni push direct ni force-push. Réglage : *Settings → Branches → Branch protection rule* sur `main`.
3. **Merger tôt, souvent** : petites PR, au moins une par demi-journée, resynchronisation chaque matin. Un gros merge le jeudi soir est la cause n°1 de démo cassée.
4. **Gel du code jeudi 17 h** : après, seulement des correctifs de la boucle, toujours par PR.
5. **Zéro secret en clair** : `.env` et `.secrets/` sont ignorés par Git, `gitleaks` tourne en CI. Si un secret a fuité : le **changer** immédiatement (le supprimer du commit ne suffit pas). Ne jamais en coller à un assistant IA.
6. **Messages de commit** : `domaine: action` (ex. `dev: ajoute l'endpoint /ledger/check`).

## Commandes

```bash
# 1. Avant de bosser : récupérer main
git switch main && git pull

# 2. Aller sur sa branche de domaine, vérifier où on est
git switch dev                      # ou ia / infra / cyber
git status

# 3. Enregistrer et envoyer
git add .                           # relire `git status` d'abord : aucun secret !
git commit -m "dev: ajoute l'endpoint /transactions"
git push                            # 1re fois : git push -u origin dev

# 4. Ouvrir une PR vers main (GitHub : Pull requests → New → base main ← ta branche)
gh pr create --base main --fill     # si `gh` est installé

# 5. Se resynchroniser avec main (chaque matin, et après chaque PR mergée par un autre)
git switch dev && git pull origin main
```

En cas de conflit : ouvrir les fichiers marqués `<<<<<<<` dans VS Code, garder la bonne version, puis `git add .` et `git commit`. Bloqué ? Demander avant de forcer quoi que ce soit.

Lancer la plateforme : voir le [README](../README.md).
