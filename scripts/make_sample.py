import pandas as pd

df = pd.read_csv("data/raw/games.csv")
df.sample(500, random_state=42).to_csv("data/samples/games_sample.csv", index=False)
print(f"Échantillon créé : 500 lignes sur {len(df)} au total")