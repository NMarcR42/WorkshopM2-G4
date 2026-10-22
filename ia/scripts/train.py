import json

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

FICHIER = "data/normal.csv"
COLONNES = ["rps", "p95_ms", "err_5xx_ratio", "cpu_pct"]
# Largeur minimale de la plage normale de chaque mesure
EPS = {"rps": 1.0, "p95_ms": 5.0, "err_5xx_ratio": 0.2, "cpu_pct": 0.2}

df = pd.read_csv(FICHIER)[COLONNES].dropna().reset_index(drop=True)

# Etiquette utilisee SEULEMENT pour mesurer et pour apprendre la plage normale
incident = ((df["err_5xx_ratio"] > 0) | (df["p95_ms"] > 200)).to_numpy()
print(f"{len(df)} lignes dont {incident.sum()} incidents reels")

# 70 % entrainement / 30 % evaluation (lignes jamais vues)
rng = np.random.default_rng(42)
ordre = rng.permutation(len(df))
coupe = int(0.7 * len(df))
idx_train, idx_test = ordre[:coupe], ordre[coupe:]

# Etage 1 : Isolation Forest
scaler = StandardScaler().fit(df.iloc[idx_train])
modele = IsolationForest(n_estimators=300, contamination=0.03, random_state=42)
modele.fit(scaler.transform(df.iloc[idx_train]))


def brut(x):
    return np.clip(-modele.score_samples(scaler.transform(x)), 0, 1)


test = df.iloc[idx_test]
inc_test = incident[idx_test]
b_norm = brut(test[~inc_test])
b_inc = brut(test[inc_test])
lo = float(np.percentile(b_norm, 99.5))
hi = float(np.median(b_inc)) if len(b_inc) else lo + 0.1
if hi <= lo + 0.01:
    hi = lo + 0.05

# Etage 2 : enveloppe de securite (plage normale de chaque mesure)
normal_all = df[~incident]
enveloppe = {}
for c in COLONNES:
    med = float(normal_all[c].median())
    ub = float(np.percentile(normal_all[c], 99.5))
    enveloppe[c] = {"med": med, "spread": max(ub - med, EPS[c])}


def score_final(x):
    b = brut(x)
    s_if = np.where(b <= lo, b * 0.6 / lo, 0.6 + 0.3 * (b - lo) / (hi - lo))
    s_env = np.zeros(len(x))
    for c in COLONNES:
        z = (x[c].to_numpy() - enveloppe[c]["med"]) / enveloppe[c]["spread"]
        s_c = np.where(z <= 1, 0.5 * z, 0.5 + 0.3 * (z - 1))
        s_env = np.maximum(s_env, s_c)
    return np.clip(np.maximum(s_if, s_env), 0, 1)


s_norm = score_final(test[~inc_test])
s_inc = score_final(test[inc_test])
attaque = pd.DataFrame(
    [[300, 2300, 0.3, 95]], columns=COLONNES
)  # exemple d'attaque DoS (non vu a l'apprentissage)

print()
print("Evaluation sur %d lignes normales et %d incidents jamais vus :"
      % (len(s_norm), len(s_inc)))
print("  score NORMAL   : median %.2f | 99%% %.2f | max %.2f"
      % (np.median(s_norm), np.percentile(s_norm, 99), s_norm.max()))
if len(s_inc):
    print("  score INCIDENT : min %.2f | median %.2f | max %.2f"
          % (s_inc.min(), np.median(s_inc), s_inc.max()))
print()
print("Au seuil 0.8 :")
print("  fausses alertes (normal >= 0.8) : %.1f %%" % (100 * np.mean(s_norm >= 0.8)))
if len(s_inc):
    print("  incidents detectes              : %.1f %%" % (100 * np.mean(s_inc >= 0.8)))
print("  attaque DoS d'exemple           : score %.2f" % score_final(attaque)[0])

joblib.dump((scaler, modele, COLONNES), "models/iforest.joblib")
with open("models/calibration.json", "w") as f:
    json.dump({"lo": lo, "hi": hi, "enveloppe": enveloppe}, f, indent=2)
print("\nModele et calibrage sauvegardes dans models/")
