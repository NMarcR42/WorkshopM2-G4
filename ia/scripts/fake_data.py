import numpy as np
import pandas as pd

rng = np.random.default_rng(42)

# 600 lignes de trafic NORMAL (une ligne = une fenêtre de 10 s)
normal = pd.DataFrame({
    "rps":           rng.normal(20, 5, 600).clip(0),
    "p95_ms":        rng.normal(80, 20, 600).clip(10),
    "err_5xx_ratio": rng.normal(0.005, 0.005, 600).clip(0, 1),
    "cpu_pct":       rng.normal(30, 10, 600).clip(0, 100),
})
normal.to_csv("data/normal_fake.csv", index=False)

# 60 lignes d'ATTAQUE simulée
attack = pd.DataFrame({
    "rps":           rng.normal(300, 50, 60).clip(0),
    "p95_ms":        rng.normal(2300, 500, 60).clip(10),
    "err_5xx_ratio": rng.normal(0.3, 0.1, 60).clip(0, 1),
    "cpu_pct":       rng.normal(95, 5, 60).clip(0, 100),
})
attack.to_csv("data/attack_fake.csv", index=False)

print("OK : fichiers créés avec les 4 variables du contrat")

