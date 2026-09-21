"""La campagne va-t-elle au bout, et survit-elle a ce qu'elle doit survivre ?

Planificateur et analyste sont remplaces par des fonctions qui rendent des
reponses ecrites a l'avance : une campagne complete se teste sans consommer
un seul appel.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest
from pydantic import ValidationError

from agents.analysis import MAX_TENTATIVES
from agents.orchestration import conduire_campagne
from utils.run_logger import RunLogger


@pytest.fixture
def df():
    return pd.DataFrame({"Price": [0.0, 10.0, 20.0, 0.0]})


@pytest.fixture
def logger(tmp_path):
    return RunLogger(racine=tmp_path)


def plan_campagne(n: int = 3) -> str:
    return json.dumps(
        {
            "lecture_question": "on cherche ce qui separe les jeux gratuits des autres",
            "variables_cles": ["Price"],
            "sous_questions": [
                {
                    "question": f"sous-question {i}",
                    "colonnes_necessaires": ["Price"],
                    "pourquoi": "eclaire la question metier",
                }
                for i in range(1, n + 1)
            ],
            "hors_portee": "le dataset ne porte aucun chiffre d'affaires",
        }
    )


def plan_analyste(code: str) -> str:
    return json.dumps(
        {
            "intention": "compter les jeux gratuits",
            "colonnes_utilisees": ["Price"],
            "code": code,
            "limites": "aucune",
        }
    )


CODE_JUSTE = "resultat = int((df['Price'] == 0).sum())"
CODE_QUI_LEVE = "resultat = df['Prix'].sum()"
HORS_CONTRAT = '{"code": "x"}'


def analyste_scripte(reponses_par_numero: dict[int, list[str]]):
    """Pour chaque sous-question, rend ses reponses dans l'ordre, une par appel."""

    def fabriquer(numero: int):
        file_attente = list(reponses_par_numero[numero])
        return lambda _: file_attente.pop(0)

    return fabriquer


def etapes(logger: RunLogger) -> list[str]:
    return [
        json.loads(ligne)["etape"]
        for ligne in logger.trace.read_text(encoding="utf-8").splitlines()
    ]


def test_une_campagne_nominale_va_au_bout(df, logger):
    campagne = conduire_campagne(
        "pourquoi",
        df,
        lambda _: plan_campagne(3),
        analyste_scripte({n: [plan_analyste(CODE_JUSTE)] for n in (1, 2, 3)}),
        logger,
    )

    assert [issue.statut for issue in campagne.issues] == ["succes"] * 3
    assert all(issue.resultat.valeur == "2" for issue in campagne.issues)
    assert campagne.colonnes_inventees == {}
    assert campagne.variables_non_mobilisees == []


def test_chaque_issue_porte_sa_sous_question(df, logger):
    """Le synthetiseur a besoin du pourquoi, pas seulement du chiffre."""
    campagne = conduire_campagne(
        "pourquoi",
        df,
        lambda _: plan_campagne(3),
        analyste_scripte({n: [plan_analyste(CODE_JUSTE)] for n in (1, 2, 3)}),
        logger,
    )

    assert [issue.numero for issue in campagne.issues] == [1, 2, 3]
    assert campagne.issues[1].sous_question.question == "sous-question 2"
    assert campagne.issues[1].sous_question.pourquoi


def test_un_echec_d_execution_n_arrete_pas_la_campagne(df, logger):
    campagne = conduire_campagne(
        "pourquoi",
        df,
        lambda _: plan_campagne(3),
        analyste_scripte(
            {
                1: [plan_analyste(CODE_JUSTE)],
                2: [plan_analyste(CODE_QUI_LEVE)] * MAX_TENTATIVES,
                3: [plan_analyste(CODE_JUSTE)],
            }
        ),
        logger,
    )

    assert [issue.statut for issue in campagne.issues] == [
        "succes",
        "echec_execution",
        "succes",
    ]
    assert campagne.issues[1].resultat.valeur is None
    assert len(campagne.issues[1].resultat.tentatives) == MAX_TENTATIVES


def test_une_sortie_hors_contrat_de_l_analyste_n_arrete_pas_la_campagne(df, logger):
    """L'analyste leve, l'orchestrateur classe et continue."""
    campagne = conduire_campagne(
        "pourquoi",
        df,
        lambda _: plan_campagne(3),
        analyste_scripte(
            {
                1: [plan_analyste(CODE_JUSTE)],
                2: [HORS_CONTRAT],
                3: [plan_analyste(CODE_JUSTE)],
            }
        ),
        logger,
    )

    assert campagne.issues[1].statut == "hors_contrat"
    assert campagne.issues[1].resultat is None
    assert campagne.issues[1].erreur
    assert campagne.issues[2].statut == "succes"


def test_un_plan_hors_contrat_arrete_tout_avant_la_premiere_analyse(df, logger):
    """Sans plan il n'y a rien a executer, et aucune analyse n'a ete payee."""
    analyses = []

    def fabriquer(numero: int):
        analyses.append(numero)
        return lambda _: plan_analyste(CODE_JUSTE)

    with pytest.raises(ValidationError):
        conduire_campagne("pourquoi", df, lambda _: '{"sous_questions": []}', fabriquer, logger)

    assert analyses == []


def test_la_trace_distingue_le_plan_de_campagne_des_plans_de_l_analyste(df, logger):
    """Deux agents dans une meme trace : leurs evenements ne doivent pas se confondre."""
    conduire_campagne(
        "pourquoi",
        df,
        lambda _: plan_campagne(3),
        analyste_scripte({n: [plan_analyste(CODE_JUSTE)] for n in (1, 2, 3)}),
        logger,
    )

    trace = etapes(logger)

    assert trace.count("plan_campagne") == 1
    assert trace.count("plan") == 3
    assert trace.count("sous_question") == 3
    assert trace.index("plan_campagne") < trace.index("sous_question")
    assert trace[-1] == "campagne_terminee"


def test_le_resultat_de_campagne_se_serialise_et_se_relit(df, logger):
    """campagne.json est l'entree du synthetiseur : il doit se relire tel quel."""
    from schemas.contracts import ResultatCampagne

    campagne = conduire_campagne(
        "pourquoi",
        df,
        lambda _: plan_campagne(3),
        analyste_scripte(
            {
                1: [plan_analyste(CODE_JUSTE)],
                2: [HORS_CONTRAT],
                3: [plan_analyste(CODE_QUI_LEVE)] * MAX_TENTATIVES,
            }
        ),
        logger,
    )

    relue = ResultatCampagne.model_validate_json(campagne.model_dump_json())

    assert [i.statut for i in relue.issues] == ["succes", "hors_contrat", "echec_execution"]
