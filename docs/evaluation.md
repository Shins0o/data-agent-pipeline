# Evaluation du pipeline

Campagne du 2026-09-14T17:00:41, modele `claude-sonnet-5` via claude-agent-sdk (abonnement), sur 125 855 lignes.

Les questions ci-dessous ont une reponse connue, calculee a la main dans `notebooks/01_exploration_steam.ipynb` et figee dans `src/evaluation/reference.py`. Le harnais les rejoue a travers l'analyste, qui produit du code pandas, et compare la valeur obtenue a la valeur attendue.

Ce que cette page ne mesure pas : les questions sont bien specifiees et leur arbitrage leur est donne. C'est un filet de non-regression, pas une mesure de la capacite de l'analyste a trancher une question ambigue.

Regenerer : `python -m evaluation.harness` puis `python -m evaluation.publication`.

## Resultat

| Mesure | Valeur |
| --- | --- |
| Questions correctes | 6 / 6 (100 %) |
| Appels modele | 6 |
| Questions ayant demande une reprise | 0 |
| Sorties hors contrat | 0 |
| Duree | 55 s |
| Tokens | 129 939 |
| Cout equivalent | 0.1166 USD |

## Par question

| Question | Verdict | Tentatives | Duree | Tokens |
| --- | --- | ---: | ---: | ---: |
| `q1_prix_median_top10` | correct | 1 | 17.8 s | 32 053 |
| `q2_sorties_2023` | correct | 1 | 4.2 s | 16 354 |
| `q3_meilleur_review_ratio` | correct | 1 | 7.5 s | 16 691 |
| `q4_part_jeux_gratuits` | correct | 1 | 4.9 s | 16 471 |
| `q5_owners_par_tranche_de_prix` | correct | 1 | 11.2 s | 31 676 |
| `q6_genre_par_owners_cumules` | correct | 1 | 9.5 s | 16 694 |

## Detail

### q1_prix_median_top10

**Verdict** : correct, en 1 tentative.

**Question posee** : Parmi les dix genres les plus representes du catalogue, lequel a le prix median le plus eleve en ne comptant que les jeux payants, et quel est ce prix median ?

**Arbitrage encode dans la question** : Les dix genres les plus representes sont determines sur le catalogue explose par genre. Les jeux gratuits sont exclus, sinon la mediane de tout genre a forte part de gratuit tombe a 0.

**Attendu** : Early Access | 6.39 (tolerance relative 0.002)

**Obtenu**

```
genre                 Early Access
prix_median_payant            6.39
```

**Code execute**

```python
exploded = explode_genres(df)
top10_genres = exploded['genre'].value_counts().head(10).index
paid = exploded[exploded['Price'] > 0]
paid_top10 = paid[paid['genre'].isin(top10_genres)]
median_prices = paid_top10.groupby('genre')['Price'].median().sort_values(ascending=False)
best_genre = median_prices.index[0]
best_price = median_prices.iloc[0]
resultat = pd.Series({'genre': best_genre, 'prix_median_payant': best_price})
```

**Limites declarees par l'analyste** : Le top 10 des genres est defini par leur frequence brute apres explosion multi-genres (un jeu avec plusieurs genres est compte dans chacun) sur l'ensemble du catalogue, jeux payants et gratuits confondus, ce qui reflete la representation globale plutot que la seule population payante. Les jeux gratuits (Price == 0) sont explicitement exclus du calcul du prix median, conformement a la consigne 'jeux payants'; les lignes sans genre (Genres manquant, 8423 jeux) sont ecartees par explode_genres et n'entrent ni dans le comptage ni dans le calcul median. Aucune valeur de Price n'est manquante donc pas de biais lie a des NaN sur cette colonne.

### q2_sorties_2023

**Verdict** : correct, en 1 tentative.

**Question posee** : Combien de jeux sont sortis en 2023 ?

**Arbitrage encode dans la question** : Comptage exact sur release_year, colonne derivee de 'Release date'. Aucune tolerance : un ecart d'une unite est une erreur.

**Attendu** : 14598 (tolerance relative 0)

**Obtenu**

```
14598
```

**Code execute**

```python
resultat = int((df['release_year'] == 2023).sum())
```

**Limites declarees par l'analyste** : release_year est une colonne derivee, calculee a partir de 'Release date' (proxy de la date reelle de sortie). Aucune valeur manquante sur release_year donc pas de filtrage silencieux necessaire. Chaque ligne du dataset correspond a un jeu (AppID unique), donc le comptage se fait directement sur df sans passer par explode_genres.

### q3_meilleur_review_ratio

**Verdict** : correct, en 1 tentative.

**Question posee** : Parmi les genres comptant au moins 500 jeux, lequel a le review_ratio median le plus eleve, et quelle est cette valeur ?

**Arbitrage encode dans la question** : Le seuil de 500 jeux ecarte les genres marginaux, dont la mediane serait portee par quelques titres. review_ratio est NaN pour les jeux sans avis, donc exclu de la mediane.

**Attendu** : Casual | 0.83 (tolerance relative 0.012)

**Obtenu**

```
genre                    Casual
review_ratio_median    0.833333
```

**Code execute**

```python
exploded = explode_genres(df)
grouped = exploded.groupby('genre')['review_ratio']
counts = grouped.size()
medians = grouped.median()
eligible = counts[counts >= 500].index
medians_eligible = medians.loc[eligible].dropna().sort_values(ascending=False)
top_genre = medians_eligible.index[0]
top_value = medians_eligible.iloc[0]
resultat = pd.Series({'genre': top_genre, 'review_ratio_median': top_value})
```

**Limites declarees par l'analyste** : review_ratio est une colonne derivee (proxy du ratio d'avis positifs), avec 42899 valeurs manquantes au niveau des jeux ; ces jeux sont exclus du calcul de la mediane sans imputation. Le seuil de 500 jeux est applique sur le nombre de lignes apres explosion par genre (un jeu multi-genres compte dans chacun de ses genres), ce qui est l'approche standard pour des stats par genre mais peut sur-representer les jeux multi-genres. La mediane est choisie plutot que la moyenne car plus robuste aux valeurs extremes du ratio d'avis.

### q4_part_jeux_gratuits

**Verdict** : correct, en 1 tentative.

**Question posee** : Quelle part du catalogue est gratuite, c'est a dire affichee a un prix nul ? Reponds en pourcentage.

**Arbitrage encode dans la question** : Price a zero est une borne superieure du free to play : un jeu temporairement offert y figure aussi.

**Attendu** : 21.18 (tolerance relative 0.005)

**Obtenu**

```
21.18
```

**Code execute**

```python
part_gratuit = (df['Price'] == 0).mean() * 100
resultat = round(part_gratuit, 2)
```

**Limites declarees par l'analyste** : Le prix affiche (colonne Price) n'a aucune valeur manquante, donc aucune ligne n'est exclue par absence de donnee. On considere comme gratuit tout jeu dont Price == 0, sans tenir compte des remises (Discount) ni du fait qu'un jeu puisse etre gratuit-avec-achats-integres ou payant mais temporairement solde a 0 : la colonne Price est le prix catalogue affiche, pas necessairement le prix reellement paye par tous les utilisateurs.

### q5_owners_par_tranche_de_prix

**Verdict** : correct, en 1 tentative.

**Question posee** : Parmi les jeux payants, quelle part depasse 50 000 proprietaires estimes, d'une part pour les jeux a moins de 15, d'autre part pour les jeux a 15 ou plus, dans l'unite de la colonne Price ? Reponds en pourcentage pour chacune des deux tranches.

**Arbitrage encode dans la question** : owners_mid est le point median d'une tranche estimee, pas une mesure de ventes. Le seuil de 15 est une coupure arbitraire, posee dans la question pour que la reponse soit comparable.

**Attendu** : 11.61, 17.02 (tolerance relative 0.009)

**Obtenu**

```
tranche_prix
15 ou plus     17.02
moins de 15    11.61
```

**Code execute**

```python
paid = df[df['Price'] > 0].copy()
paid['tranche_prix'] = np.where(paid['Price'] < 15, 'moins de 15', '15 ou plus')
resultat = (paid.assign(depasse_50000=paid['owners_mid'] > 50000)
            .groupby('tranche_prix')['depasse_50000']
            .mean()
            .mul(100)
            .round(2)
            .rename('pct_depasse_50000_proprietaires'))
```

**Limites declarees par l'analyste** : owners_mid est une colonne derivee : c'est le point milieu de la fourchette textuelle 'Estimated owners', donc un proxy du nombre reel de proprietaires, pas une mesure exacte. Un jeu est considere 'payant' si Price > 0 (Price n'a aucune valeur manquante, donc aucun jeu n'est exclu par manque de donnee sur le prix). Le seuil de la tranche est pris au sens 'strictement inferieur a 15' vs '15 ou superieur', conformement a la formulation de la question ('moins de 15' / '15 ou plus'). Le pourcentage 'depasse 50000' est calcule au sens strict (owners_mid > 50000, pas >=), une autre lecture incluant l'egalite a 50000 donnerait un resultat legerement different si des jeux ont un owners_mid exactement egal a 50000 (peu probable vu les paliers de la colonne source, mais non verifie ici).

### q6_genre_par_owners_cumules

**Verdict** : correct, en 1 tentative.

**Question posee** : Quel genre cumule le plus de proprietaires estimes sur l'ensemble du catalogue, et quel est ce total ? Un jeu multi-genres compte dans chacun de ses genres.

**Arbitrage encode dans la question** : Le double comptage est assume et annonce dans la question. Un total par genre n'est donc pas une part de marche : la somme des genres depasse le total du catalogue.

**Attendu** : Action | 6.6772e+09 (tolerance relative 1e-06)

**Obtenu**

```
genre                     Action
total_owners_mid    6677200000.0
```

**Code execute**

```python
df_exp = explode_genres(df)
somme_par_genre = df_exp.groupby('genre')['owners_mid'].sum().sort_values(ascending=False)
top_genre = somme_par_genre.index[0]
top_total = somme_par_genre.iloc[0]
resultat = pd.Series({'genre': top_genre, 'total_owners_mid': top_total})
```

**Limites declarees par l'analyste** : owners_mid est une colonne derivee, calculee probablement comme le milieu de la fourchette textuelle 'Estimated owners' (ex: '0 - 20000' -> 10000) : c'est un proxy approximatif du nombre reel de proprietaires, pas une mesure exacte. Les 8423 jeux sans genre (valeurs manquantes dans 'Genres') sont exclus du calcul via explode_genres, ce qui sous-estime legerement les totaux sans le signaler autrement qu'ici. Un jeu present dans plusieurs genres est compte integralement dans chacun (pas de ponderation), conformement a la consigne de la question.
