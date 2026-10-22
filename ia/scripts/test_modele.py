import pandas as pd
import joblib

scaler, modele, colonnes = joblib.load("models/iforest.joblib")

for nom in ["normal_fake", "attack_fake"]:
    df = pd.read_csv(f"data/{nom}.csv")[colonnes]
    resultat = modele.predict(scaler.transform(df))   # 1 = normal, -1 = anomalie
    pourcentage = (resultat == -1).mean() * 100
    print(f"{nom} : {pourcentage:.1f} % de lignes jugées anormales")
    