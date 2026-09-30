"""Le synthetiseur voit-il ce qu'il doit voir, et le rapport rendu montre-t-il ses doutes ?

Le modele est remplace par une fonction qui rend un rapport ecrit a
l'avance : ni appel, ni dataset.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest
from pydantic import ValidationError

from agents.rendu_rapport import MARQUE, rendre_markdown
from agents.profiling import build_profile
from agents.synthese import (
    colonnes_citees,
    construire_prompt,
    fiche_qualite,
    synthetiser,
    vue_pour_synthetiseur,
)
from agents.synthese_agent import campagne_a_lire
from fabriques import CAMPAGNE, rapport
from utils.run_logger import RunLogger


@pytest.fixture
def logger(tmp_path):
    return RunLogger(racine=tmp_path)


def modele_rendant(**surcharges):
    texte = rapport(**surcharges).model_dump_json()
    return lambda _: texte


def etapes(logger: RunLogger) -> list[str]:
    return [
        json.loads(ligne)["etape"]
        for ligne in logger.trace.read_text(encoding="utf-8").splitlines()
    ]


# --- ce que le synthetiseur recoit ---------------------------------------------


def test_le_synthetiseur_voit_les_valeurs_et_les_limites_d_une_analyse_aboutie():
    vue = vue_pour_synthetiseur(CAMPAGNE)["sous_questions"][2]

    assert vue["valeur"] == "14598"
    assert vue["limites"] == "owners_mid est un proxy"
    assert vue["pourquoi"]


def test_le_synthetiseur_ne_voit_d_une_sous_question_echouee_que_son_statut():
    """Lui montrer les erreurs l'inviterait a deviner le resultat."""
    vue = vue_pour_synthetiseur(CAMPAGNE)["sous_questions"][0]

    assert vue["statut"] == "hors_contrat"
    assert "valeur" not in vue


def test_le_code_genere_n_entre_pas_dans_le_prompt():
    """Il ecrit des phrases, pas du pandas : le code doublerait le prompt pour rien."""
    prompt = construire_prompt(vue_pour_synthetiseur(CAMPAGNE))

    assert "resultat = 1" not in prompt
    assert "14598" in prompt


# --- la synthese et ses controles ------------------------------------------------


def test_une_synthese_propre_ne_signale_rien(logger):
    synthese = synthetiser(CAMPAGNE, modele_rendant(), logger)

    assert synthese.chiffres_non_sources == []
    assert synthese.constats_sans_donnee == {}
    assert etapes(logger) == ["synthese_demandee", "synthese_brute", "rapport"]


def test_un_chiffre_recopie_du_hors_portee_est_signale_et_trace(logger):
    synthese = synthetiser(
        CAMPAGNE,
        modele_rendant(limites=["Metacritic score vaut 0 pour 96,6 % des jeux."]),
        logger,
    )

    assert [s.nombre for s in synthese.chiffres_non_sources] == ["96,6"]
    assert "chiffres_non_sources" in etapes(logger)


def test_un_constat_sans_donnee_est_signale_et_trace(logger):
    synthese = synthetiser(
        CAMPAGNE,
        modele_rendant(
            constats=[
                {"id": "C1", "enonce": "Le sommet concentre tout.", "sous_questions": [1]},
                {"id": "C2", "enonce": "14 598 jeux en 2023.", "sous_questions": [3]},
            ]
        ),
        logger,
    )

    assert synthese.constats_sans_donnee == {"C1": [1]}
    assert "constats_sans_donnee" in etapes(logger)


def test_un_rapport_hors_contrat_arrete_la_synthese(logger):
    with pytest.raises(ValidationError):
        synthetiser(CAMPAGNE, lambda _: '{"reponse_courte": "x"}', logger)


def test_la_synthese_se_serialise(logger):
    synthese = synthetiser(
        CAMPAGNE, modele_rendant(limites=["Metacritic vaut 0 pour 96,6 % des jeux."]), logger
    )

    relue = json.loads(json.dumps(synthese.en_dict(), ensure_ascii=False))

    assert relue["chiffres_non_sources"][0]["nombre"] == "96,6"


# --- le rendu ------------------------------------------------------------------


def rendu(logger, **surcharges) -> str:
    return rendre_markdown(synthetiser(CAMPAGNE, modele_rendant(**surcharges), logger), CAMPAGNE)


def test_les_controles_passent_avant_le_rapport(logger):
    """Un lecteur doit savoir ce qu'il peut croire avant de lire ce qu'on affirme."""
    texte = rendu(logger)

    assert texte.index("## Controles automatiques") < texte.index("## Ce que la donnee montre")


def test_un_chiffre_non_source_est_marque_a_sa_place_et_seulement_lui(logger):
    """Marque apres le signe pourcent : "96,6 %" reste d'un seul tenant."""
    texte = rendu(logger, limites=["Sur 2 596 jeux MMO, Metacritic vaut 0 pour 96,6 % des jeux."])

    assert f"96,6 % {MARQUE}" in texte
    assert f"2 596 {MARQUE}" not in texte


def test_un_tableau_rendu_garde_l_alignement_de_ses_colonnes(logger):
    """Les espaces de tete d'un DataFrame rendu portent l'alignement."""
    assert "\n                       n_jeux" in rendu(logger)


def test_l_annexe_porte_le_code_qui_a_tranche_chaque_sous_question(logger):
    texte = rendu(logger)

    assert "```python\nresultat = 1\n```" in texte
    assert "hors contrat" in texte


def test_un_rapport_sans_recommandation_le_dit(logger):
    assert "Aucune recommandation" in rendu(logger, recommandations=[])


# --- le choix de la campagne -------------------------------------------------------


def test_sans_argument_la_campagne_la_plus_recente_est_lue(tmp_path):
    for horodatage in ["20260914-160240", "20260921-122758", "20260915-090000"]:
        (tmp_path / horodatage).mkdir()
        (tmp_path / horodatage / "campagne.json").write_text("{}", encoding="utf-8")

    assert campagne_a_lire([], racine=tmp_path).parent.name == "20260921-122758"


def test_un_dossier_sans_campagne_est_refuse(tmp_path):
    with pytest.raises(SystemExit):
        campagne_a_lire([str(tmp_path)])


# --- fiche qualite : les manquants des colonnes dont le plan parle ------------

# Extrait reel du plan de la campagne du 21 septembre (runs/20260921-122758).
HORS_PORTEE_REELLE = (
    "owners_mid n'est qu'une estimation par tranche et non un chiffre de ventes, "
    "et Price est le prix actuel. Metacritic score et Metacritic url sont quasi "
    "inutilisables (respectivement presque toujours a 0 et manquants a 96.6%), "
    "et Score rank est manquant a 100%."
)

COLONNES = ["AppID", "Name", "Price", "Metacritic score", "Metacritic url", "Score rank", "Genres", "owners_mid"]


def plan_avec(hors_portee: str):
    return CAMPAGNE.plan.model_copy(update={"hors_portee": hors_portee})


def test_les_colonnes_ecartees_dans_la_prose_du_plan_sont_citees():
    assert colonnes_citees(plan_avec(HORS_PORTEE_REELLE), COLONNES) == [
        "Price",
        "Metacritic score",
        "Metacritic url",
        "Score rank",
        "owners_mid",
    ]


def test_un_nom_de_colonne_se_cherche_en_mot_entier():
    """"Prices" ne cite pas la colonne Price."""
    assert colonnes_citees(plan_avec("Prices vary a lot"), ["Price"]) == []


def test_la_fiche_reprend_le_profil_et_omet_les_colonnes_completes():
    df = pd.DataFrame(
        {
            "Metacritic url": [None, None, None, "https://x"],
            "Score rank": [None] * 4,
            "Price": [0.0, 4.99, 9.99, 19.99],
        }
    )
    fiche = fiche_qualite(build_profile(df), ["Metacritic url", "Score rank", "Price"])

    assert fiche == {
        "Metacritic url": {"n_manquants": 3, "taux_manquant": 0.75},
        "Score rank": {"n_manquants": 4, "taux_manquant": 1.0},
    }


def test_la_fiche_ignore_les_colonnes_non_citees():
    df = pd.DataFrame({"Score rank": [None, None], "Notes": [None, "x"]})
    assert list(fiche_qualite(build_profile(df), ["Score rank"])) == ["Score rank"]
