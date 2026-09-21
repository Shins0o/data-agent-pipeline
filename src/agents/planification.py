"""Socle du planificateur : question metier -> plan de sous-questions.

C'est la premiere des deux etapes de la campagne ou le chemin ne peut pas
s'ecrire a l'avance. Decouper "quels facteurs determinent le succes
commercial d'un jeu" en calculs realisables sur 45 colonnes demande
d'interpreter la question et de choisir un angle : une fonction ne le fait
pas.

Ce que le planificateur recoit : le profil technique, calcule par du code
deterministe. Pas la lecture de l'agent 1. Brancher la sortie de l'agent 1
sur l'entree du planificateur ferait qu'une retouche du prompt de l'agent 1
deplacerait en silence ce que le planificateur voit, et l'interpretation
dont il a besoin, il la fait lui-meme a partir du meme profil.

Comme ailleurs, l'appel au modele entre par une fonction passee en
parametre : la boucle se teste sans consommer un seul appel.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable

from pydantic import ValidationError

from agents.profiling import nettoyer_json
from schemas.contracts import PlanCampagne
from tools import PROJECT_ROOT
from utils.run_logger import RunLogger

PROMPT_PATH = PROJECT_ROOT / "src" / "prompts" / "planificateur.md"

# Meme signature que chez l'analyste, definie ici plutot qu'importee : les
# deux modules n'ont aucune raison de dependre l'un de l'autre pour un alias.
AppelModele = Callable[[str], str]


def charger_prompt_systeme(chemin: Path = PROMPT_PATH) -> str:
    """Le prompt vit dans un fichier, jamais en double dans le code."""
    return chemin.read_text(encoding="utf-8")


def construire_prompt(profil: dict, question_metier: str) -> str:
    return (
        f"Profil du dataset :\n\n{json.dumps(profil, ensure_ascii=False)}\n\n"
        f"Question metier : {question_metier}"
    )


def valider_plan(texte_brut: str) -> PlanCampagne:
    """Frontiere du pipeline : la sortie du modele entre par ici ou pas du tout."""
    texte = nettoyer_json(texte_brut)
    try:
        return PlanCampagne.model_validate_json(texte)
    except ValidationError:
        print("Plan non conforme au contrat. Texte brut :")
        print(texte)
        raise


def colonnes_inventees(
    plan: PlanCampagne, colonnes_reelles: Iterable[str]
) -> dict[str, list[str]]:
    """Par sous-question, les colonnes citees qui n'existent pas dans le dataset.

    Mesure de qualite du plan, pas garde-fou de calcul. L'analyste ne lit
    jamais `colonnes_necessaires` : il recoit le schema reel et travaille
    dessus. Une colonne inventee ici ne fausse donc aucun chiffre, elle
    signale un planificateur qui a lu le profil de travers, ce qu'on veut
    voir dans la trace plutot qu'arreter la campagne.
    """
    reelles = set(colonnes_reelles)
    inventees = {
        sous_question.question: [
            colonne
            for colonne in sous_question.colonnes_necessaires
            if colonne not in reelles
        ]
        for sous_question in plan.sous_questions
    }
    return {question: manquantes for question, manquantes in inventees.items() if manquantes}


def variables_non_mobilisees(plan: PlanCampagne) -> list[str]:
    """Les variables de sortie annoncees qu'aucune sous-question n'utilise.

    Meme nature que `colonnes_inventees` : un indicateur de qualite du plan,
    pas un garde-fou de calcul. Il repond a un defaut precis, un plan qui
    annonce dans `lecture_question` un angle qu'il ne decoupe jamais. La
    prose ne se verifie pas, une liste de colonnes si.
    """
    mobilisees = {
        colonne
        for sous_question in plan.sous_questions
        for colonne in sous_question.colonnes_necessaires
    }
    return [variable for variable in plan.variables_cles if variable not in mobilisees]


def planifier(
    question_metier: str,
    profil: dict,
    appeler_modele: AppelModele,
    logger: RunLogger,
) -> PlanCampagne:
    """Un seul appel, sans reprise.

    Pas de boucle d'auto-correction ici, contrairement a l'analyste, et la
    raison est la meme que celle qui justifie la sienne. L'analyste reessaie
    parce qu'une stacktrace lui dit quoi corriger. Un plan valide au contrat
    n'echoue sur rien d'objectif : il n'y a pas de retour a lui renvoyer.
    Un plan hors contrat arrete la campagne, comme chez l'analyste.
    """
    logger.log("question_metier", question=question_metier)

    reponse_brute = appeler_modele(construire_prompt(profil, question_metier))
    # "plan_campagne" et non "plan" : l'analyste journalise deja un
    # evenement "plan" par tentative, et une campagne met les deux dans la
    # meme trace.
    logger.log("plan_campagne_brut", texte=reponse_brute)

    plan = valider_plan(reponse_brute)
    logger.log(
        "plan_campagne",
        lecture_question=plan.lecture_question,
        variables_cles=plan.variables_cles,
        n_sous_questions=len(plan.sous_questions),
        sous_questions=[s.question for s in plan.sous_questions],
        hors_portee=plan.hors_portee,
    )

    inventees = colonnes_inventees(plan, [c["nom"] for c in profil["colonnes"]])
    if inventees:
        logger.log("colonnes_inventees", detail=inventees)

    non_mobilisees = variables_non_mobilisees(plan)
    if non_mobilisees:
        logger.log("variables_non_mobilisees", detail=non_mobilisees)

    return plan
