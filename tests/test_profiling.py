"""Le profil technique porte-t-il ce qu'il annonce, et reste-t-il serialisable ?

Le profil part en JSON dans le prompt de deux agents. Une valeur non
serialisable ne casse pas ici, elle casse a l'appel, c'est-a-dire au moment
ou ca coute quelque chose.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from agents.analysis import valider_plan as valider_plan_analyste
from agents.profiling import build_profile, nettoyer_json


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


# --- nettoyer_json : derives de forme tolerees, fond intact ---


# Reponse reelle de l'analyste, campagne du 21 septembre, sous-question 1.
# Code juste, rejetee pour une seule cle accentuee.
REPONSE_REELLE_ACCENTUEE = json.dumps(
    {
        "intention": "Calculer la part du total de owners_mid détenue par le top 5 %",
        "colonnes_utilisées": ["owners_mid"],
        "code": "seuil_95 = df['owners_mid'].quantile(0.95)\nresultat = seuil_95",
        "limites": "owners_mid est une colonne dérivée",
    },
    ensure_ascii=False,
)


def test_une_cle_accentuee_ne_fait_plus_perdre_une_analyse():
    plan = valider_plan_analyste(REPONSE_REELLE_ACCENTUEE)
    assert plan.colonnes_utilisees == ["owners_mid"]


def test_les_valeurs_gardent_leurs_accents():
    """Seules les cles sont normalisees : le fond ne doit jamais bouger."""
    plan = valider_plan_analyste(REPONSE_REELLE_ACCENTUEE)
    assert "détenue" in plan.intention
    assert "dérivée" in plan.limites


def test_les_cles_imbriquees_sont_aussi_normalisees():
    texte = json.dumps({"sous_questions": [{"colonnes_nécessaires": ["Price"]}]}, ensure_ascii=False)
    assert json.loads(nettoyer_json(texte)) == {"sous_questions": [{"colonnes_necessaires": ["Price"]}]}


def test_deux_cles_qui_se_confondent_ne_sont_pas_fusionnees_en_silence():
    """Garder l'une ou l'autre serait une correction silencieuse : le contrat tranchera."""
    texte = json.dumps({"limites": "a", "limités": "b"}, ensure_ascii=False)
    assert json.loads(nettoyer_json(texte)) == {"limites": "a", "limités": "b"}


def test_un_json_invalide_passe_tel_quel_et_reste_rejete_par_le_contrat():
    """Les appelants rattrapent une ValidationError : elle ne doit pas devenir une autre exception."""
    assert nettoyer_json("pas du json") == "pas du json"
    with pytest.raises(ValidationError):
        valider_plan_analyste("pas du json")


def test_les_balises_markdown_restent_tolerees_avec_une_cle_accentuee():
    assert valider_plan_analyste(f"```json\n{REPONSE_REELLE_ACCENTUEE}\n```").code
