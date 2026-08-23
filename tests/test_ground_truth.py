"""Verite terrain : les 6 questions de reference calculees a la main.

Les valeurs attendues viennent de notebooks/01_exploration_steam.ipynb,
section 5. Ce fichier est le filet de securite du projet : il verifie que
le chargement et les colonnes derivees produisent les memes chiffres que
l'EDA manuelle. Toute etape structurante du pipeline se rejoue contre lui.

Lancement : pytest tests/ -v
"""

from __future__ import annotations

import pytest

from tools.dataset import (
    MARQUEUR_ENTETE_DEFECTUEUX,
    add_derived_columns,
    explode_genres,
    load_games,
)

# Le dataset complet est charge une seule fois pour toute la session (~6 s).
pytestmark = pytest.mark.filterwarnings("ignore::FutureWarning")


@pytest.fixture(scope="session")
def df():
    return add_derived_columns(load_games())


@pytest.fixture(scope="session")
def df_genres(df):
    return explode_genres(df)


def test_dimensions(df):
    """40 colonnes brutes + 5 derivees, sur 125 855 jeux."""
    assert df.shape == (125_855, 45)
    assert df["AppID"].is_unique


def test_q1_prix_median_early_access(df_genres):
    """Q1 : prix median du genre Early Access, jeux payants."""
    top10 = df_genres["genre"].value_counts().head(10).index
    medianes = (
        df_genres[df_genres["genre"].isin(top10) & (df_genres["Price"] > 0)]
        .groupby("genre")["Price"]
        .median()
        .sort_values(ascending=False)
    )
    assert medianes.index[0] == "Early Access"
    assert medianes.iloc[0] == pytest.approx(6.39, abs=0.01)


def test_q2_sorties_2023(df):
    """Q2 : nombre de sorties en 2023."""
    assert (df["release_year"] == 2023).sum() == 14_598


def test_q3_meilleur_review_ratio(df_genres):
    """Q3 : genre au meilleur review_ratio median, parmi les genres >= 500 jeux."""
    effectifs = df_genres["genre"].value_counts()
    genres_500 = effectifs[effectifs >= 500].index
    medianes = (
        df_genres[df_genres["genre"].isin(genres_500)]
        .groupby("genre")["review_ratio"]
        .median()
        .sort_values(ascending=False)
    )
    assert medianes.index[0] == "Casual"
    assert medianes.iloc[0] == pytest.approx(0.83, abs=0.01)


def test_q4_part_jeux_gratuits(df):
    """Q4 : part des jeux a prix nul."""
    assert (df["Price"] == 0).mean() * 100 == pytest.approx(21.18, abs=0.1)


def test_q5_owners_par_tranche_de_prix(df):
    """Q5 : part des jeux depassant 50 000 owners, par tranche de prix (payants)."""
    payants = df[df["Price"] > 0]
    sous_15 = payants[payants["Price"] < 15]
    quinze_et_plus = payants[payants["Price"] >= 15]

    assert (sous_15["owners_mid"] > 50_000).mean() * 100 == pytest.approx(11.61, abs=0.1)
    assert (quinze_et_plus["owners_mid"] > 50_000).mean() * 100 == pytest.approx(
        17.02, abs=0.1
    )


def test_q6_genre_par_owners_cumules(df_genres):
    """Q6 : premier genre par proprietaires estimes cumules (double comptage assume)."""
    totaux = df_genres.groupby("genre")["owners_mid"].sum().sort_values(ascending=False)
    assert totaux.index[0] == "Action"
    assert totaux.iloc[0] == pytest.approx(6_677_200_000.0, rel=1e-6)


def test_load_games_refuse_un_entete_corrige(tmp_path):
    """Le garde-fou du chargement : un en-tete sain doit lever, pas etre force.

    Si le CSV source est un jour republie sans le defaut, imposer COLS
    recreerait un decalage silencieux dans l'autre sens.
    """
    fichier = tmp_path / "games.csv"
    fichier.write_text("AppID,Name,Discount,DLC count\n1,Jeu,0,0\n", encoding="utf-8")

    with pytest.raises(ValueError, match=MARQUEUR_ENTETE_DEFECTUEUX):
        load_games(fichier)
