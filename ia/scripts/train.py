import pandas as pd
import joblib
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

FICHIER = "data/normal_fake.csv"   # mardi, tu mettras "data/normal.csv"

df = pd.read_csv(FICHIER)
scaler = StandardScaler().fit(df)

modele = IsolationForest(n_estimators=200, contamination=0.01, random_state=42)
modele.fit(scaler.transform(df))

joblib.dump((scaler, modele, list(df.columns)), "models/iforest.joblib")
print("Modèle entraîné et sauvegardé dans models/iforest.joblib")
