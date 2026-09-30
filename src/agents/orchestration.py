"""Orchestrateur de campagne : question metier -> plan -> une analyse par sous-question.

Ce module n'est pas un agent, et c'est la decision la plus structurante du
pipeline. Une fois le plan etabli, le chemin s'ecrit entierement a l'avance :
pour chaque sous-question, appeler l'analyste. Un orchestrateur agentique
ajouterait une boucle de tours, une couche d'outils et une trace qui vit dans
la machinerie du SDK, pour zero decision qu'il prendrait reellement.

Ce qui retournerait la conclusion : une campagne ou la sous-question suivante
depend du resultat de la precedente, et pas seulement de sa lecture. Le plan
est fige a dessein, et c'est le synthetiseur qui dira s'il lui manque quelque
chose pour conclure.

Aucune dependance vers un SDK ici. Les appels au modele entrent par des
fonctions passees en parametre, comme partout ailleurs dans le pipeline.
"""

from __future__ import annotations

from typing import Callable

import pandas as pd
from pydantic import ValidationError

from agents.analysis import repondre
from agents.planification import (
    AppelModele,
    colonnes_inventees,
    planifier,
    variables_non_mobilisees,
)
from agents.profiling import build_profile
from schemas.contracts import (
    IssueSousQuestion,
    PlanCampagne,
    ResultatCampagne,
    SousQuestion,
)
from utils.run_logger import RunLogger

# Une fonction qui, pour le numero d'une sous-question, rend l'appelant a
# utiliser pour elle. Une fabrique plutot qu'un appelant unique : chaque
# sous-question doit porter sa propre etiquette dans le tableau de
# consommation, et son propre compteur de tentatives.
FabriqueAppel = Callable[[int], AppelModele]


def traiter_sous_question(
    numero: int,
    sous_question: SousQuestion,
    df: pd.DataFrame,
    appeler_modele: AppelModele,
    logger: RunLogger,
) -> IssueSousQuestion:
    """Passe une sous-question a l'analyste et classe ce qu'il en revient.

    Une sortie hors contrat arrete l'analyste, c'est le comportement voulu et
    teste. Elle n'arrete pas la campagne : sur six sous-questions, perdre la
    quatrieme ne doit pas priver le synthetiseur des cinq autres. Le manque
    est trace et transmis, jamais passe sous silence.

    Un echec du SDK, lui, n'est pas rattrape. Limite d'abonnement atteinte ou
    CLI non authentifie : continuer produirait des sous-questions vides qui
    ressemblent a des resultats.
    """
    logger.log(
        "sous_question",
        numero=numero,
        question=sous_question.question,
        pourquoi=sous_question.pourquoi,
    )

    try:
        resultat = repondre(sous_question.question, df, appeler_modele, logger)
    except ValidationError as exc:
        logger.log("sous_question_hors_contrat", numero=numero, erreur=str(exc))
        return IssueSousQuestion(
            numero=numero,
            sous_question=sous_question,
            statut="hors_contrat",
            resultat=None,
            erreur=str(exc),
        )

    return IssueSousQuestion(
        numero=numero,
        sous_question=sous_question,
        statut="succes" if resultat.statut == "succes" else "echec_execution",
        resultat=resultat,
    )


def executer_plan(
    question_metier: str,
    plan: PlanCampagne,
    df: pd.DataFrame,
    fabriquer_appel_analyste: FabriqueAppel,
    logger: RunLogger,
) -> ResultatCampagne:
    """Une analyse par sous-question, dans l'ordre du plan. Aucun appel au planificateur.

    Separe de conduire_campagne pour pouvoir rejouer un plan deja valide. Le
    planificateur est l'etape la plus variable du pipeline : deux campagnes
    sur la meme question n'ont pas le meme plan, donc ne mesurent pas la meme
    chose. Rejouer le plan fige d'une campagne passee isole ce qu'on veut
    comparer, l'analyste et le synthetiseur, de ce qu'on ne veut pas.
    """
    issues = [
        traiter_sous_question(
            numero, sous_question, df, fabriquer_appel_analyste(numero), logger
        )
        for numero, sous_question in enumerate(plan.sous_questions, start=1)
    ]

    abouties = sum(1 for issue in issues if issue.statut == "succes")
    logger.log("campagne_terminee", abouties=abouties, total=len(issues))

    return ResultatCampagne(
        question_metier=question_metier,
        plan=plan,
        issues=issues,
        colonnes_inventees=colonnes_inventees(plan, list(df.columns)),
        variables_non_mobilisees=variables_non_mobilisees(plan),
    )


def conduire_campagne(
    question_metier: str,
    df: pd.DataFrame,
    appeler_planificateur: AppelModele,
    fabriquer_appel_analyste: FabriqueAppel,
    logger: RunLogger,
) -> ResultatCampagne:
    """Profil, plan, puis une analyse par sous-question, dans l'ordre du plan.

    Le profil est calcule ici a partir de `df`, et non recu en parametre :
    le planificateur et l'analyste doivent voir le meme dataset, et le seul
    moyen de le garantir est de ne pas laisser l'appelant fournir les deux.

    Un plan hors contrat leve et arrete tout : sans plan, il n'y a rien a
    executer, et aucun appel a l'analyste n'a encore ete paye.

    Le profil est trace tel que le planificateur l'a lu : c'est l'entree qui
    explique son plan, et le seul endroit ou relire d'ou vient un chiffre
    qu'il aurait repris dans sa prose.
    """
    profil = build_profile(df)
    logger.log("profil", profil=profil)
    plan = planifier(question_metier, profil, appeler_planificateur, logger)
    return executer_plan(question_metier, plan, df, fabriquer_appel_analyste, logger)


def rejouer_plan(
    campagne_source: ResultatCampagne,
    df: pd.DataFrame,
    fabriquer_appel_analyste: FabriqueAppel,
    logger: RunLogger,
) -> ResultatCampagne:
    """Rejoue le plan d'une campagne passee, sans rien reprendre de ses resultats.

    Le profil est trace ici aussi : les donnees ont pu changer depuis la
    campagne source, et c'est sur celles du rejeu que les analyses tournent.
    """
    logger.log(
        "plan_rejoue",
        question_metier=campagne_source.question_metier,
        n_sous_questions=len(campagne_source.plan.sous_questions),
    )
    logger.log("profil", profil=build_profile(df))
    return executer_plan(
        campagne_source.question_metier,
        campagne_source.plan,
        df,
        fabriquer_appel_analyste,
        logger,
    )
