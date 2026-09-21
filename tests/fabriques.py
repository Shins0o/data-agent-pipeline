"""Campagnes et rapports construits a la main, partages par les tests du synthetiseur.

Aucune valeur n'est inventee pour l'occasion : les rendus reprennent ceux de
la campagne reelle du 21 septembre, pour que les tests exercent les controles
sur des formats que l'analyste produit vraiment.
"""

from __future__ import annotations

from schemas.contracts import (
    IssueSousQuestion,
    PlanCampagne,
    RapportFinal,
    ResultatAnalyse,
    ResultatCampagne,
    SousQuestion,
    TentativeExecution,
)



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
        tentatives=[
            TentativeExecution(
                numero=1,
                code="resultat = 1",
                erreur=None if aboutie else "KeyError: 'Prix'",
            )
        ],
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
