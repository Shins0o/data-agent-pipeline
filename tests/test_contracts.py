"""Le contrat de sortie de l'agent 1 rejette-t-il ce qu'il doit rejeter ?

Ces tests ne consomment aucun appel de modele : ils valident la frontiere,
pas l'agent.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.profiling import valider_reponse

REPONSE_VALIDE = """{
  "resume": "Un dataset de jeux.",
  "colonnes_cles": ["AppID", "Price"],
  "problemes_qualite": [
    {"colonne": "Movies", "probleme": "colonne vide", "gravite": "elevee"}
  ],
  "questions_analytiques": [
    {"question": "Quel est le prix median ?", "colonnes_necessaires": ["Price"]}
  ]
}"""


def test_reponse_conforme():
    analyse = valider_reponse(REPONSE_VALIDE)
    assert analyse.questions_analytiques[0].colonnes_necessaires == ["Price"]
    assert analyse.problemes_qualite[0].gravite == "elevee"


def test_balises_markdown_tolerees():
    """Le modele ajoute parfois ```json malgre la consigne."""
    analyse = valider_reponse(f"```json\n{REPONSE_VALIDE}\n```")
    assert analyse.resume == "Un dataset de jeux."


def test_cle_manquante_rejetee():
    ampute = REPONSE_VALIDE.replace('"resume"', '"synthese"')
    with pytest.raises(ValidationError):
        valider_reponse(ampute)


def test_gravite_hors_vocabulaire_rejetee():
    """'critique' n'est pas une valeur prevue : le pipeline doit s'arreter."""
    invalide = REPONSE_VALIDE.replace('"elevee"', '"critique"')
    with pytest.raises(ValidationError):
        valider_reponse(invalide)


def test_liste_de_questions_vide_rejetee():
    vide = REPONSE_VALIDE.replace(
        '{"question": "Quel est le prix median ?", "colonnes_necessaires": ["Price"]}',
        "",
    )
    with pytest.raises(ValidationError):
        valider_reponse(vide)


def test_json_invalide_rejete():
    with pytest.raises(ValidationError):
        valider_reponse("Not logged in - Please run /login")
