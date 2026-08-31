"""La boucle d'auto-correction se corrige-t-elle, et s'arrete-t-elle ?

Le modele est remplace par une fonction qui rend des reponses ecrites a
l'avance : la boucle se teste entierement sans consommer un appel.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest
from pydantic import ValidationError

from agents.analysis import MAX_TENTATIVES, repondre, schema_pour_analyste
from utils.run_logger import RunLogger


@pytest.fixture
def df():
    return pd.DataFrame({"Price": [0.0, 10.0, 20.0, 0.0]})


@pytest.fixture
def logger(tmp_path):
    return RunLogger(racine=tmp_path)


def plan(code: str) -> str:
    return json.dumps(
        {
            "intention": "compter les jeux gratuits",
            "colonnes_utilisees": ["Price"],
            "code": code,
            "limites": "aucune",
        }
    )


def modele_scripte(*reponses: str):
    """Rend les reponses fournies, dans l'ordre, une par appel."""
    file_attente = list(reponses)
    return lambda _: file_attente.pop(0)


CODE_BON = "resultat = int((df['Price'] == 0).sum())"
CODE_FAUX = "resultat = df['Prix'].sum()"


def test_succes_du_premier_coup(df, logger):
    resultat = repondre("combien de jeux gratuits", df, modele_scripte(plan(CODE_BON)), logger)

    assert resultat.statut == "succes"
    assert resultat.valeur == "2"
    assert len(resultat.tentatives) == 1
    assert resultat.tentatives[0].erreur is None


def test_correction_apres_un_echec(df, logger):
    """La deuxieme tentative reussit, et la premiere reste dans la trace."""
    modele = modele_scripte(plan(CODE_FAUX), plan(CODE_BON))
    resultat = repondre("combien de jeux gratuits", df, modele, logger)

    assert resultat.statut == "succes"
    assert len(resultat.tentatives) == 2
    assert "KeyError" in resultat.tentatives[0].erreur
    assert resultat.tentatives[1].erreur is None


def test_stacktrace_renvoyee_a_la_tentative_suivante(df, logger):
    """Sans la stacktrace dans le prompt de reprise, la boucle est aveugle."""
    prompts = []

    def modele(prompt: str) -> str:
        prompts.append(prompt)
        return plan(CODE_FAUX if len(prompts) == 1 else CODE_BON)

    repondre("combien de jeux gratuits", df, modele, logger)

    assert "KeyError" in prompts[1]
    assert CODE_FAUX in prompts[1]


def test_abandon_apres_trois_tentatives(df, logger):
    modele = modele_scripte(*[plan(CODE_FAUX)] * MAX_TENTATIVES)
    resultat = repondre("combien de jeux gratuits", df, modele, logger)

    assert resultat.statut == "echec"
    assert resultat.valeur is None
    assert resultat.code_execute is None
    assert len(resultat.tentatives) == MAX_TENTATIVES


def test_sortie_hors_contrat_arrete_le_pipeline(df, logger):
    """Un plan invalide n'est pas rejoue : c'est une erreur, pas un alea."""
    with pytest.raises(ValidationError):
        repondre("combien de jeux gratuits", df, modele_scripte('{"code": "x"}'), logger)


def test_trace_ecrite_etape_par_etape(df, logger):
    modele = modele_scripte(plan(CODE_FAUX), plan(CODE_BON))
    repondre("combien de jeux gratuits", df, modele, logger)

    etapes = [
        json.loads(ligne)["etape"]
        for ligne in logger.trace.read_text(encoding="utf-8").splitlines()
    ]
    assert etapes == [
        "question",
        "reponse_brute",
        "plan",
        "echec_execution",
        "reponse_brute",
        "plan",
        "resultat",
    ]


def test_schema_ne_porte_que_ce_qui_sert_a_ecrire_du_code(df):
    schema = schema_pour_analyste(df)
    assert schema["n_lignes"] == 4
    assert schema["colonnes"][0] == {
        "nom": "Price",
        "type": "float64",
        "origine": "brute",
        "n_manquants": 0,
    }
