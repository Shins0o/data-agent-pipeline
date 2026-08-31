"""L'execution du code genere renvoie-t-elle de quoi corriger quand elle rate ?

Aucun appel de modele ici : on teste le bac a exec, pas l'analyste.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tools.execution import VARIABLE_RESULTAT, executer_code, rendre_valeur


@pytest.fixture
def df():
    return pd.DataFrame(
        {
            "Price": [0.0, 9.99, 19.99, 0.0],
            "Genres": ["Action,Indie", "Action", "Casual", "Indie,Casual"],
        }
    )


def test_code_valide_rend_sa_valeur(df):
    execution = executer_code("resultat = (df['Price'] == 0).mean()", df)
    assert execution.a_reussi
    assert execution.valeur == 0.5


def test_code_qui_leve_rend_sa_stacktrace(df):
    execution = executer_code("resultat = df['Prix'].mean()", df)
    assert not execution.a_reussi
    assert "KeyError" in execution.erreur
    assert execution.valeur is None


def test_code_sans_variable_resultat_est_un_echec(df):
    """Un code qui tourne mais ne pose rien n'est pas un succes silencieux."""
    execution = executer_code("df['Price'].mean()", df)
    assert not execution.a_reussi
    assert VARIABLE_RESULTAT in execution.erreur


def test_sortie_standard_capturee(df):
    execution = executer_code("print('trace interne')\nresultat = 1", df)
    assert execution.a_reussi
    assert "trace interne" in execution.sortie_standard


def test_explode_genres_disponible(df):
    """L'helper metier est expose au code genere, il ne doit pas le reecrire."""
    execution = executer_code(
        "resultat = explode_genres(df)['genre'].value_counts()", df
    )
    assert execution.a_reussi
    assert execution.valeur["Action"] == 2


def test_rendu_dataframe_tronque():
    valeur = pd.Series(range(100))
    assert len(rendre_valeur(valeur).splitlines()) <= 20
