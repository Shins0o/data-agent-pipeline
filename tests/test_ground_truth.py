"""Verite terrain : les 6 questions de reference rejouees sur le dataset reel.

Les valeurs attendues ne vivent plus ici mais dans evaluation/reference.py,
partage avec le harnais d'evaluation. Ce fichier ne porte plus que la
mecanique du test : charger une fois, boucler, comparer.

Ce test est le filet de securite du projet. Il verifie que le chargement et
les colonnes derivees produisent les memes chiffres que l'EDA manuelle.
Toute etape structurante du pipeline se rejoue contre lui.

Lancement : pytest tests/ -v
"""

from __future__ import annotations

import pytest

from evaluation.reference import QUESTIONS_REFERENCE, valeur_proche
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


@pytest.mark.parametrize(
    "reference", QUESTIONS_REFERENCE, ids=[q.id for q in QUESTIONS_REFERENCE]
)
def test_question_de_reference(reference, df, df_genres):
    """La donnee dit toujours ce que l'analyse manuelle avait trouve."""
    libelles, valeurs = reference.calculer(df, df_genres)

    assert libelles == reference.libelles_attendus
    assert len(valeurs) == len(reference.valeurs_attendues)

    for obtenue, attendue in zip(valeurs, reference.valeurs_attendues):
        assert valeur_proche(obtenue, attendue, reference.tolerance), (
            f"{reference.id} : obtenu {obtenue}, attendu {attendue} "
            f"a {reference.tolerance:.3%} pres"
        )


def test_load_games_refuse_un_entete_corrige(tmp_path):
    """Le garde-fou du chargement : un en-tete sain doit lever, pas etre force.

    Si le CSV source est un jour republie sans le defaut, imposer COLS
    recreerait un decalage silencieux dans l'autre sens.
    """
    fichier = tmp_path / "games.csv"
    fichier.write_text("AppID,Name,Discount,DLC count\n1,Jeu,0,0\n", encoding="utf-8")

    with pytest.raises(ValueError, match=MARQUEUR_ENTETE_DEFECTUEUX):
        load_games(fichier)
