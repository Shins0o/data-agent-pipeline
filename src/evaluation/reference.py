"""Jeu de questions de reference : la source unique de la verite terrain.

Les valeurs attendues viennent de notebooks/01_exploration_steam.ipynb,
section 5, ou elles ont ete calculees a la main sur le dataset complet.

Deux consommateurs lisent ce module, et c'est toute la raison de son
existence :

- tests/test_ground_truth.py verifie que le chargement et les colonnes
  derivees produisent toujours ces valeurs. Aucun appel modele, donc gratuit.
- le harnais d'evaluation rejoue `question` a travers l'analyste et compare
  sa reponse a `valeurs_attendues`. Un appel modele par tentative.

Les deux comparent avec `valeur_proche`. Reussir le test et reussir
l'evaluation veulent donc dire exactement la meme chose, ce qui n'est pas
garanti quand la regle de comparaison est ecrite deux fois.

Les formulations de `question` embarquent deliberement l'arbitrage : les dix
genres les plus frequents, le seuil de 500 jeux, la coupure de prix a 15.
Ce qui est mesure ici, c'est si l'analyste ecrit du code juste pour une
question posee, pas s'il devine le meme arbitrage que l'analyse manuelle.
Mesurer la qualite d'un arbitrage declare demanderait un second jeu de
questions volontairement floues, et ce n'est pas le meme exercice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

# Ce qu'une fonction de calcul observe : les libelles attendus puis les
# valeurs numeriques, dans l'ordre ou la question les demande.
Constat = tuple[tuple[str, ...], tuple[float, ...]]

CalculReference = Callable[[pd.DataFrame, pd.DataFrame], Constat]


def valeur_proche(obtenue: float, attendue: float, tolerance: float) -> bool:
    """Ecart relatif a la valeur attendue, sous la tolerance de la question.

    La tolerance est relative et non absolue parce qu'elle couvre deux
    ecarts de nature differente avec la meme regle : l'arrondi de la valeur
    transcrite depuis le notebook, et l'arrondi que l'analyste applique en
    presentant son resultat. Une tolerance absolue unique n'aurait aucun sens
    entre un prix de 6,39 et un cumul de 6,7 milliards.
    """
    if attendue == 0:
        return abs(obtenue) <= tolerance
    return abs(obtenue - attendue) / abs(attendue) <= tolerance


@dataclass(frozen=True)
class QuestionReference:
    """Une question dont la reponse est connue.

    `calculer` recoit le dataset et sa version explosee par genre, et rend
    ce que la donnee dit reellement. `libelles_attendus` et
    `valeurs_attendues` sont ce que l'analyse manuelle a trouve. Les deux
    doivent coincider : c'est ce que le test verifie.

    `note` porte l'arbitrage encode dans la question. Il apparait dans le
    rapport d'evaluation, pour qu'un ecart puisse etre lu sans rouvrir le
    notebook.
    """

    id: str
    question: str
    calculer: CalculReference
    libelles_attendus: tuple[str, ...]
    valeurs_attendues: tuple[float, ...]
    tolerance: float
    note: str


def _q1_prix_median_top10(df: pd.DataFrame, df_genres: pd.DataFrame) -> Constat:
    top10 = df_genres["genre"].value_counts().head(10).index
    medianes = (
        df_genres[df_genres["genre"].isin(top10) & (df_genres["Price"] > 0)]
        .groupby("genre")["Price"]
        .median()
        .sort_values(ascending=False)
    )
    return (str(medianes.index[0]),), (float(medianes.iloc[0]),)


def _q2_sorties_2023(df: pd.DataFrame, df_genres: pd.DataFrame) -> Constat:
    return (), (float((df["release_year"] == 2023).sum()),)


def _q3_meilleur_review_ratio(df: pd.DataFrame, df_genres: pd.DataFrame) -> Constat:
    effectifs = df_genres["genre"].value_counts()
    genres_500 = effectifs[effectifs >= 500].index
    medianes = (
        df_genres[df_genres["genre"].isin(genres_500)]
        .groupby("genre")["review_ratio"]
        .median()
        .sort_values(ascending=False)
    )
    return (str(medianes.index[0]),), (float(medianes.iloc[0]),)


def _q4_part_jeux_gratuits(df: pd.DataFrame, df_genres: pd.DataFrame) -> Constat:
    return (), (float((df["Price"] == 0).mean() * 100),)


def _q5_owners_par_tranche_de_prix(
    df: pd.DataFrame, df_genres: pd.DataFrame
) -> Constat:
    payants = df[df["Price"] > 0]
    sous_15 = payants[payants["Price"] < 15]
    quinze_et_plus = payants[payants["Price"] >= 15]
    return (), (
        float((sous_15["owners_mid"] > 50_000).mean() * 100),
        float((quinze_et_plus["owners_mid"] > 50_000).mean() * 100),
    )


def _q6_genre_par_owners_cumules(
    df: pd.DataFrame, df_genres: pd.DataFrame
) -> Constat:
    totaux = df_genres.groupby("genre")["owners_mid"].sum().sort_values(ascending=False)
    return (str(totaux.index[0]),), (float(totaux.iloc[0]),)


QUESTIONS_REFERENCE: tuple[QuestionReference, ...] = (
    QuestionReference(
        id="q1_prix_median_top10",
        question=(
            "Parmi les dix genres les plus representes du catalogue, lequel a "
            "le prix median le plus eleve en ne comptant que les jeux payants, "
            "et quel est ce prix median ?"
        ),
        calculer=_q1_prix_median_top10,
        libelles_attendus=("Early Access",),
        valeurs_attendues=(6.39,),
        tolerance=0.002,
        note=(
            "Les dix genres les plus representes sont determines sur le "
            "catalogue explose par genre. Les jeux gratuits sont exclus, "
            "sinon la mediane de tout genre a forte part de gratuit tombe a 0."
        ),
    ),
    QuestionReference(
        id="q2_sorties_2023",
        question="Combien de jeux sont sortis en 2023 ?",
        calculer=_q2_sorties_2023,
        libelles_attendus=(),
        valeurs_attendues=(14_598.0,),
        tolerance=0.0,
        note=(
            "Comptage exact sur release_year, colonne derivee de 'Release "
            "date'. Aucune tolerance : un ecart d'une unite est une erreur."
        ),
    ),
    QuestionReference(
        id="q3_meilleur_review_ratio",
        question=(
            "Parmi les genres comptant au moins 500 jeux, lequel a le "
            "review_ratio median le plus eleve, et quelle est cette valeur ?"
        ),
        calculer=_q3_meilleur_review_ratio,
        libelles_attendus=("Casual",),
        valeurs_attendues=(0.83,),
        tolerance=0.012,
        note=(
            "Le seuil de 500 jeux ecarte les genres marginaux, dont la "
            "mediane serait portee par quelques titres. review_ratio est NaN "
            "pour les jeux sans avis, donc exclu de la mediane."
        ),
    ),
    QuestionReference(
        id="q4_part_jeux_gratuits",
        question=(
            "Quelle part du catalogue est gratuite, c'est a dire affichee a "
            "un prix nul ? Reponds en pourcentage."
        ),
        calculer=_q4_part_jeux_gratuits,
        libelles_attendus=(),
        valeurs_attendues=(21.18,),
        tolerance=0.005,
        note=(
            "Price a zero est une borne superieure du free to play : un jeu "
            "temporairement offert y figure aussi."
        ),
    ),
    QuestionReference(
        id="q5_owners_par_tranche_de_prix",
        question=(
            "Parmi les jeux payants, quelle part depasse 50 000 proprietaires "
            "estimes, d'une part pour les jeux a moins de 15, d'autre part "
            "pour les jeux a 15 ou plus, dans l'unite de la colonne Price ? "
            "Reponds en pourcentage pour chacune des deux tranches."
        ),
        calculer=_q5_owners_par_tranche_de_prix,
        libelles_attendus=(),
        valeurs_attendues=(11.61, 17.02),
        tolerance=0.009,
        note=(
            "owners_mid est le point median d'une tranche estimee, pas une "
            "mesure de ventes. Le seuil de 15 est une coupure arbitraire, "
            "posee dans la question pour que la reponse soit comparable."
        ),
    ),
    QuestionReference(
        id="q6_genre_par_owners_cumules",
        question=(
            "Quel genre cumule le plus de proprietaires estimes sur "
            "l'ensemble du catalogue, et quel est ce total ? Un jeu "
            "multi-genres compte dans chacun de ses genres."
        ),
        calculer=_q6_genre_par_owners_cumules,
        libelles_attendus=("Action",),
        valeurs_attendues=(6_677_200_000.0,),
        tolerance=1e-6,
        note=(
            "Le double comptage est assume et annonce dans la question. Un "
            "total par genre n'est donc pas une part de marche : la somme des "
            "genres depasse le total du catalogue."
        ),
    ),
)
