"""Le profil technique porte-t-il ce qu'il annonce, et reste-t-il serialisable ?

Le profil part en JSON dans le prompt de deux agents. Une valeur non
serialisable ne casse pas ici, elle casse a l'appel, c'est-a-dire au moment
ou ca coute quelque chose.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from agents.profiling import build_profile


def profil_de(colonne: str, valeurs) -> dict:
    profil = build_profile(pd.DataFrame({colonne: valeurs}))
    return profil["colonnes"][0]


def test_une_colonne_numerique_porte_son_asymetrie():
    """Une queue lourde doit sortir tres au dessus du seuil de 2."""
    concentree = [1.0] * 100 + [10_000.0]

    assert profil_de("owners", concentree)["asymetrie"] > 2


def test_une_distribution_symetrique_reste_proche_de_zero():
    valeurs = list(np.linspace(-5, 5, 200))

    assert abs(profil_de("centree", valeurs)["asymetrie"]) < 0.5


def test_une_colonne_texte_n_a_pas_d_asymetrie():
    assert "asymetrie" not in profil_de("Name", ["a", "b", "c"])


def test_une_colonne_booleenne_n_a_pas_d_asymetrie():
    """Numerique pour pandas, mais son asymetrie ne dit rien de plus que son taux."""
    assert "asymetrie" not in profil_de("Windows", [True, False, True])


def test_une_asymetrie_indefinie_devient_none_et_non_nan():
    """json.dumps ecrit un NaN litteral, qui n'est pas du JSON valide."""
    profil = profil_de("deux_valeurs", [1.0, 2.0])

    assert profil["asymetrie"] is None
    assert "NaN" not in json.dumps(profil)


def test_le_profil_complet_reste_serialisable_en_json():
    df = pd.DataFrame(
        {
            "Name": ["a", "b"],
            "Price": [0.0, 10.0],
            "Windows": [True, False],
            "sortie": pd.to_datetime(["2023-01-01", "2024-01-01"]),
        }
    )

    assert "NaN" not in json.dumps(build_profile(df), default=str)
