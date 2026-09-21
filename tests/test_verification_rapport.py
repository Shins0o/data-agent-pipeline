"""Le rapport final tient-il sa chaine de preuve, et ses chiffres ont-ils une source ?

Tout est deterministe ici : aucun appel modele, aucune donnee reelle. Les
campagnes et les rapports sont construits a la main.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.verification_rapport import (
    chiffres_non_sources,
    constats_sans_donnee,
    correspond,
    lire_nombres,
)
from schemas.contracts import (
    IssueSousQuestion,
    PlanCampagne,
    RapportFinal,
    ResultatAnalyse,
    ResultatCampagne,
    SousQuestion,
    TentativeExecution,
)


# --- fabriques --------------------------------------------------------------


def issue(numero: int, question: str, valeur: str | None = None, statut: str = "succes"):
    sous_question = SousQuestion(
        question=question, colonnes_necessaires=["owners_mid"], pourquoi="eclaire la question"
    )
    if statut == "hors_contrat":
        return IssueSousQuestion(
            numero=numero,
            sous_question=sous_question,
            statut="hors_contrat",
            resultat=None,
            erreur="cle inattendue",
        )
    aboutie = statut == "succes"
    resultat = ResultatAnalyse(
        question=question,
        statut="succes" if aboutie else "echec",
        intention="calcul",
        limites="owners_mid est un proxy",
        code_execute="resultat = 1" if aboutie else None,
        valeur=valeur if aboutie else None,
        tentatives=[TentativeExecution(numero=1, code="resultat = 1")],
    )
    return IssueSousQuestion(
        numero=numero, sous_question=sous_question, statut=statut, resultat=resultat
    )


def campagne(*issues: IssueSousQuestion) -> ResultatCampagne:
    return ResultatCampagne(
        question_metier="qu'est-ce qui fait le succes d'un jeu",
        plan=PlanCampagne(
            lecture_question="succes approxime par owners_mid",
            variables_cles=["owners_mid"],
            sous_questions=[i.sous_question for i in issues],
            hors_portee="Metacritic score vaut 0 pour 96,6 % des jeux",
        ),
        issues=list(issues),
        colonnes_inventees={},
        variables_non_mobilisees=[],
    )


# Inspiree de la campagne reelle du 21 septembre.
CAMPAGNE = campagne(
    issue(
        1,
        "Quelle part du total de owners_mid detiennent les 5% de jeux au sommet ?",
        statut="hors_contrat",
    ),
    issue(
        2,
        "Parmi les genres comptant au moins 500 jeux, lequel a la plus forte part "
        "de jeux au dessus du 90e percentile ?",
        valeur="                       n_jeux  n_depasse  proportion_depasse_p90\n"
        "genre\nMassively Multiplayer    2596        457                 0.17604",
    ),
    issue(
        3,
        "Combien de jeux sont sortis en 2023 ?",
        valeur="14598",
    ),
)


def rapport(**surcharges) -> RapportFinal:
    champs = {
        "reponse_courte": "Massively Multiplayer place 17,6 % de ses jeux au sommet.",
        "constats": [
            {"id": "C1", "enonce": "17,6 % des jeux MMO depassent le seuil.", "sous_questions": [2]},
            {"id": "C2", "enonce": "14 598 jeux sont sortis en 2023.", "sous_questions": [3]},
        ],
        "interpretations": [
            {"id": "I1", "enonce": "Le multijoueur massif concentre les succes.", "constats": ["C1"]}
        ],
        "recommandations": [
            {"enonce": "Etudier le multijoueur avant de s'y lancer.", "appuis": ["I1"]}
        ],
        "limites": ["owners_mid est une estimation par tranche."],
        "non_etabli": ["La concentration au sommet (sous-question 1) n'a pas ete calculee."],
    }
    return RapportFinal.model_validate(champs | surcharges)


# --- contrat : la chaine de preuve --------------------------------------------


def test_un_rapport_conforme_est_accepte():
    assert rapport().constats[0].id == "C1"


def test_une_interpretation_citant_un_constat_inexistant_est_rejetee():
    with pytest.raises(ValidationError, match="constat inexistant"):
        rapport(interpretations=[{"id": "I1", "enonce": "x", "constats": ["C9"]}])


def test_une_recommandation_citant_une_interpretation_inexistante_est_rejetee():
    with pytest.raises(ValidationError, match="interpretation inexistante"):
        rapport(recommandations=[{"enonce": "x", "appuis": ["I4"]}])


def test_un_identifiant_en_double_est_rejete():
    with pytest.raises(ValidationError, match="en double"):
        rapport(
            constats=[
                {"id": "C1", "enonce": "a", "sous_questions": [2]},
                {"id": "C1", "enonce": "b", "sous_questions": [3]},
            ]
        )


def test_un_identifiant_mal_forme_est_rejete():
    with pytest.raises(ValidationError):
        rapport(constats=[{"id": "X1", "enonce": "a", "sous_questions": [2]}])


def test_un_rapport_sans_limite_est_rejete():
    """Les limites font partie du livrable, pas d'une annexe optionnelle."""
    with pytest.raises(ValidationError):
        rapport(limites=[])


def test_un_rapport_sans_recommandation_est_accepte():
    """Exiger une recommandation que la donnee ne porte pas, c'est en faire inventer une."""
    assert rapport(recommandations=[]).recommandations == []


# --- lecture des nombres -----------------------------------------------------


def valeurs(texte: str, **options) -> list[float]:
    return [n.valeur for n in lire_nombres(texte, **options)]


def test_les_formats_francais_sont_lus():
    assert valeurs("17,6 % des jeux") == [17.6]
    assert valeurs("14 598 jeux") == [14598]
    assert valeurs("14 598 jeux") == [14598]
    assert valeurs("6 677 200 000 proprietaires") == [6_677_200_000]
    assert valeurs("une correlation de -0,02") == [-0.02]


def test_une_plage_d_annees_n_est_pas_lue_comme_un_nombre_negatif():
    assert valeurs("entre 2017-2026") == [2017, 2026]


def test_les_identifiants_ne_sont_pas_des_nombres():
    assert valeurs("voir C1, I2 et le seuil p90") == []


def test_un_rendu_pandas_ne_colle_pas_ses_colonnes():
    """En mode francais, "2596 457" serait un seul nombre : 2 596 457."""
    assert valeurs("2596 457 0.17604", milliers_espaces=False) == [2596, 457, 0.17604]
    assert valeurs("6.677200e+09", milliers_espaces=False) == [6_677_200_000]


def test_la_precision_ecrite_est_conservee():
    assert [n.decimales for n in lire_nombres("17,6 et 18 et 0,176")] == [1, 0, 3]


# --- correspondance par arrondi ----------------------------------------------


def premier(texte: str):
    return lire_nombres(texte)[0]


@pytest.mark.parametrize("ecrit", ["17,6 %", "18 %", "0,18", "0,176"])
def test_un_arrondi_legitime_de_la_source_passe(ecrit):
    assert correspond(premier(ecrit), 0.17604)


def test_un_arrondi_faux_est_signale():
    assert not correspond(premier("17,7 %"), 0.17604)


def test_un_entier_rond_a_deux_chiffres_significatifs_est_un_arrondi():
    assert correspond(premier("14 600"), 14598)


def test_un_entier_rond_a_un_seul_chiffre_significatif_doit_etre_exact():
    """Sans ce plancher, "20 000" trouverait une source entre 15 000 et 25 000."""
    assert not correspond(premier("20 000"), 14598)
    assert correspond(premier("10 000"), 10000.0)


def test_un_demi_n_est_pas_arrondi_au_pair():
    """round(2.5) donne 2 en Python : "3" doit pourtant passer pour 2,5."""
    assert correspond(premier("3"), 2.5)


# --- controles contre la campagne ----------------------------------------------


def test_un_rapport_entierement_source_ne_signale_rien():
    assert chiffres_non_sources(rapport(), CAMPAGNE) == []


def test_le_96_6_recopie_du_hors_portee_est_signale():
    """Le cas reel : un chiffre ecrit par le planificateur sans l'avoir calcule."""
    signales = chiffres_non_sources(
        rapport(limites=["Metacritic score vaut 0 pour 96,6 % des jeux."]), CAMPAGNE
    )

    assert [(s.champ, s.nombre) for s in signales] == [("limite 1", "96,6")]
    assert "Metacritic" in signales[0].extrait


def test_un_seuil_ecrit_dans_une_sous_question_est_une_source():
    """500 jeux est une definition posee par le plan, pas une mesure."""
    assert chiffres_non_sources(
        rapport(limites=["Seuls les genres d'au moins 500 jeux sont retenus."]), CAMPAGNE
    ) == []


def test_un_chiffre_invente_dans_un_constat_est_signale():
    signales = chiffres_non_sources(
        rapport(
            constats=[
                {"id": "C1", "enonce": "42,3 % des jeux MMO depassent le seuil.", "sous_questions": [2]},
                {"id": "C2", "enonce": "14 598 jeux sont sortis en 2023.", "sous_questions": [3]},
            ]
        ),
        CAMPAGNE,
    )
    assert [(s.champ, s.nombre) for s in signales] == [("constat C1", "42,3")]


def test_un_constat_appuye_sur_une_sous_question_sans_resultat_est_signale():
    signales = constats_sans_donnee(
        rapport(
            constats=[
                {"id": "C1", "enonce": "Le sommet concentre tout.", "sous_questions": [1, 2]},
                {"id": "C2", "enonce": "14 598 jeux en 2023.", "sous_questions": [3]},
            ]
        ),
        CAMPAGNE,
    )
    assert signales == {"C1": [1]}


def test_un_constat_citant_une_sous_question_inexistante_est_signale():
    signales = constats_sans_donnee(
        rapport(constats=[{"id": "C1", "enonce": "x", "sous_questions": [9]}], interpretations=[], recommandations=[]),
        CAMPAGNE,
    )
    assert signales == {"C1": [9]}
