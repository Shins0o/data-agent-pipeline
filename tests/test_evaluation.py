"""Le harnais juge-t-il correctement, et survit-il a ce qu'il doit survivre ?

Comme pour la boucle de l'analyste, le modele est remplace par une fonction
qui rend des reponses ecrites a l'avance : tout ce fichier tourne sans
consommer un appel.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from agents.usage import UsageTracker
from evaluation.harness import comparer, evaluer_une, extraire_nombres
from evaluation.reference import QuestionReference
from utils.run_logger import RunLogger


@pytest.fixture
def df():
    return pd.DataFrame({"Price": [0.0, 10.0, 20.0, 0.0]})


@pytest.fixture
def logger(tmp_path):
    return RunLogger(racine=tmp_path)


def reference_de_test(**surcharges) -> QuestionReference:
    """Une question de reference minimale : deux jeux gratuits, valeur exacte."""
    champs = {
        "id": "q_test",
        "question": "combien de jeux sont gratuits",
        "calculer": lambda df, df_genres: ((), (2.0,)),
        "libelles_attendus": (),
        "valeurs_attendues": (2.0,),
        "tolerance": 0.0,
        "note": "fixture de test",
    }
    return QuestionReference(**(champs | surcharges))


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
    file_attente = list(reponses)
    return lambda _: file_attente.pop(0)


CODE_JUSTE = "resultat = int((df['Price'] == 0).sum())"
CODE_FAUX = "resultat = 99"
CODE_QUI_LEVE = "resultat = df['Prix'].sum()"


def test_extraire_nombres_couvre_les_rendus_de_pandas():
    """Entier, decimal et notation scientifique sortent tous de to_string()."""
    assert extraire_nombres("14598") == [14598.0]
    assert extraire_nombres("Early Access    6.39") == [6.39]
    assert extraire_nombres("Action    6.677200e+09") == [6677200000.0]


def test_comparer_accepte_un_arrondi_dans_la_tolerance():
    reference = reference_de_test(valeurs_attendues=(6.39,), tolerance=0.002)
    assert comparer(reference, "6.3912") == ([], [])


def test_comparer_refuse_une_fraction_quand_un_pourcentage_est_attendu():
    """21,18 % et 0,2118 ne sont pas la meme reponse a la question posee."""
    reference = reference_de_test(valeurs_attendues=(21.18,), tolerance=0.005)
    assert comparer(reference, "0.2118") == ([], [21.18])


def test_comparer_signale_un_libelle_absent():
    reference = reference_de_test(
        libelles_attendus=("Early Access",), valeurs_attendues=(6.39,), tolerance=0.002
    )
    libelles, valeurs = comparer(reference, "Indie    6.39")
    assert libelles == ["Early Access"]
    assert valeurs == []


def test_verdict_correct_quand_le_code_repond_juste(df, logger):
    verdict = evaluer_une(
        reference_de_test(),
        df,
        modele_scripte(plan(CODE_JUSTE)),
        logger,
        UsageTracker(),
    )

    assert verdict.verdict == "correct"
    assert verdict.tentatives == 1
    assert verdict.valeurs_manquantes == []


def test_verdict_incorrect_quand_le_code_tourne_mais_repond_faux(df, logger):
    """Le cas qui compte : le pipeline n'a rien signale, et le chiffre est faux."""
    verdict = evaluer_une(
        reference_de_test(),
        df,
        modele_scripte(plan(CODE_FAUX)),
        logger,
        UsageTracker(),
    )

    assert verdict.verdict == "incorrect"
    assert verdict.valeurs_manquantes == [2.0]
    assert verdict.valeur_rendue == "99"


def test_verdict_echec_execution_apres_epuisement_des_tentatives(df, logger):
    verdict = evaluer_une(
        reference_de_test(),
        df,
        modele_scripte(*[plan(CODE_QUI_LEVE)] * 3),
        logger,
        UsageTracker(),
    )

    assert verdict.verdict == "echec_execution"
    assert verdict.valeur_rendue is None
    assert verdict.valeurs_manquantes == [2.0]


def test_sortie_hors_contrat_ne_fait_pas_tomber_la_campagne(df, logger):
    """Le pipeline leve, le harnais classe et continue : c'est tout l'interet."""
    verdict = evaluer_une(
        reference_de_test(),
        df,
        modele_scripte('{"code": "x"}'),
        logger,
        UsageTracker(),
    )

    assert verdict.verdict == "hors_contrat"
    assert verdict.tentatives == 0
    assert verdict.valeur_rendue is None
