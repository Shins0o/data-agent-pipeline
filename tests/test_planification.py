"""Le plan respecte-t-il son contrat, et voit-on ses defauts ?

Modele remplace par une fonction qui rend une reponse ecrite a l'avance :
tout ce fichier tourne sans consommer un appel.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agents.planification import (
    colonnes_inventees,
    construire_prompt,
    planifier,
    valider_plan,
    variables_non_mobilisees,
)
from schemas.contracts import MAX_SOUS_QUESTIONS, MIN_SOUS_QUESTIONS
from utils.run_logger import RunLogger

PROFIL = {
    "n_lignes": 4,
    "colonnes": [{"nom": "Price"}, {"nom": "Genres"}, {"nom": "owners_mid"}],
}


@pytest.fixture
def logger(tmp_path):
    return RunLogger(racine=tmp_path)


def sous_question(numero: int, colonnes: list[str] | None = None) -> dict:
    return {
        "question": f"sous-question {numero}",
        # `is None` et non `or` : une liste vide est un cas de test, pas une absence.
        "colonnes_necessaires": ["Price"] if colonnes is None else colonnes,
        "pourquoi": "eclaire la question metier",
    }


def plan_json(n: int = MIN_SOUS_QUESTIONS, **surcharges) -> str:
    champs = {
        "lecture_question": "on cherche ce qui separe les jeux qui marchent",
        "variables_cles": ["Price"],
        "sous_questions": [sous_question(i) for i in range(n)],
        "hors_portee": "le dataset ne porte ni chiffre d'affaires ni budget marketing",
    }
    return json.dumps(champs | surcharges)


def modele_scripte(reponse: str):
    return lambda _: reponse


def test_un_plan_conforme_est_accepte():
    plan = valider_plan(plan_json())

    assert len(plan.sous_questions) == MIN_SOUS_QUESTIONS
    assert plan.sous_questions[0].pourquoi


def test_les_balises_markdown_sont_tolerees():
    """Le modele en ajoute parfois malgre la consigne, comme pour l'agent 1."""
    assert valider_plan(f"```json\n{plan_json()}\n```").hors_portee


def test_un_plan_trop_court_est_rejete():
    """En dessous de la borne basse, le planificateur n'a pas decoupe."""
    with pytest.raises(ValidationError):
        valider_plan(plan_json(MIN_SOUS_QUESTIONS - 1))


def test_un_plan_trop_long_est_rejete():
    """La borne haute est un garde-fou de consommation, pas une preference."""
    with pytest.raises(ValidationError):
        valider_plan(plan_json(MAX_SOUS_QUESTIONS + 1))


def test_une_cle_inattendue_est_rejetee():
    """extra=forbid : une cle en trop signale un modele sorti du schema."""
    with pytest.raises(ValidationError):
        valider_plan(plan_json(priorite="haute"))


def test_une_sous_question_sans_colonne_est_rejetee():
    with pytest.raises(ValidationError):
        valider_plan(
            plan_json(
                sous_questions=[
                    sous_question(0, colonnes=[]),
                    sous_question(1),
                    sous_question(2),
                ]
            )
        )


def test_les_colonnes_inventees_sont_detectees():
    plan = valider_plan(
        plan_json(
            sous_questions=[
                sous_question(0, colonnes=["Price", "Revenue"]),
                sous_question(1, colonnes=["Genres"]),
                sous_question(2, colonnes=["Budget"]),
            ]
        )
    )

    inventees = colonnes_inventees(plan, [c["nom"] for c in PROFIL["colonnes"]])

    assert inventees == {"sous-question 0": ["Revenue"], "sous-question 2": ["Budget"]}


def test_un_plan_sans_colonne_inventee_ne_signale_rien():
    plan = valider_plan(plan_json())
    assert colonnes_inventees(plan, [c["nom"] for c in PROFIL["colonnes"]]) == {}


def test_le_prompt_porte_le_profil_et_la_question():
    prompt = construire_prompt(PROFIL, "pourquoi certains jeux marchent")

    assert "owners_mid" in prompt
    assert "pourquoi certains jeux marchent" in prompt


def test_planifier_trace_le_brut_puis_le_plan(logger):
    """Noms distincts de ceux de l'analyste : une campagne met les deux dans la meme trace."""
    planifier("pourquoi", PROFIL, modele_scripte(plan_json()), logger)

    etapes = [
        json.loads(ligne)["etape"]
        for ligne in logger.trace.read_text(encoding="utf-8").splitlines()
    ]
    assert etapes == ["question_metier", "plan_campagne_brut", "plan_campagne"]


def test_planifier_trace_les_colonnes_inventees(logger):
    """La trace doit porter le defaut, sinon il n'est jamais mesure."""
    reponse = plan_json(
        sous_questions=[
            sous_question(0, colonnes=["Revenue"]),
            sous_question(1),
            sous_question(2),
        ]
    )
    planifier("pourquoi", PROFIL, modele_scripte(reponse), logger)

    trace = logger.trace.read_text(encoding="utf-8")
    assert "colonnes_inventees" in trace
    assert "Revenue" in trace


def test_une_sortie_hors_contrat_arrete_la_planification(logger):
    """Pas de reprise : relancer sur la meme consigne ne changerait rien."""
    with pytest.raises(ValidationError):
        planifier("pourquoi", PROFIL, modele_scripte('{"sous_questions": []}'), logger)


def test_une_variable_cle_mobilisee_ne_signale_rien():
    assert variables_non_mobilisees(valider_plan(plan_json())) == []


def test_une_variable_cle_annoncee_mais_jamais_utilisee_est_signalee():
    """Le defaut vu sur le vrai plan : deux proxys annonces, un seul decoupe."""
    plan = valider_plan(plan_json(variables_cles=["Price", "owners_mid"]))

    assert variables_non_mobilisees(plan) == ["owners_mid"]


def test_un_plan_sans_variable_cle_est_rejete():
    with pytest.raises(ValidationError):
        valider_plan(plan_json(variables_cles=[]))


def test_planifier_trace_les_variables_non_mobilisees(logger):
    reponse = plan_json(variables_cles=["Price", "owners_mid"])
    planifier("pourquoi", PROFIL, modele_scripte(reponse), logger)

    trace = logger.trace.read_text(encoding="utf-8")
    assert "variables_non_mobilisees" in trace
    assert "owners_mid" in trace
