"""Le planificateur, lance seul (voie abonnement).

Decoupe une question metier en sous-questions calculables, sans les
executer. Sert a lire et corriger un plan avant que l'orchestrateur ne le
paie en analyses completes.

Lancement :
    python -m agents.planificateur_agent "quels facteurs determinent le succes
    commercial d'un jeu sur Steam, et quel positionnement recommanderiez-vous
    a un studio independant ?"
"""

from __future__ import annotations

import asyncio
import sys

from agents.planification import (
    charger_prompt_systeme,
    colonnes_inventees,
    planifier,
    variables_non_mobilisees,
)
from agents.profiling import build_profile
from agents.sdk_abonnement import interroger, verifier_environnement
from agents.usage import UsageTracker
from schemas.contracts import PlanCampagne
from tools.dataset import add_derived_columns, load_games
from utils.run_logger import RunLogger

MODEL = "claude-sonnet-5"
VOIE = "claude-agent-sdk (abonnement)"


def afficher(
    plan: PlanCampagne,
    inventees: dict[str, list[str]],
    non_mobilisees: list[str],
) -> None:
    print(f"\nLecture de la question :\n{plan.lecture_question}")
    print(f"\nVariables de sortie retenues : {', '.join(plan.variables_cles)}")

    print(f"\n{len(plan.sous_questions)} sous-questions :")
    for numero, sous_question in enumerate(plan.sous_questions, start=1):
        print(f"\n  {numero}. {sous_question.question}")
        print(f"     colonnes : {', '.join(sous_question.colonnes_necessaires)}")
        print(f"     pourquoi : {sous_question.pourquoi}")

    print(f"\nHors portee :\n{plan.hors_portee}")

    if inventees:
        print("\nColonnes citees qui n'existent pas dans le dataset :")
        for question, colonnes in inventees.items():
            print(f"  - {question}\n    {colonnes}")

    if non_mobilisees:
        print(
            "\nVariables de sortie annoncees mais mobilisees par aucune "
            f"sous-question :\n  {non_mobilisees}"
        )


def main() -> None:
    verifier_environnement()

    question_metier = " ".join(sys.argv[1:]).strip()
    if not question_metier:
        raise SystemExit(
            'Usage : python -m agents.planificateur_agent "ta question metier"'
        )

    df = add_derived_columns(load_games())
    print(f"Dataset charge : {len(df):,} lignes, {len(df.columns)} colonnes")

    profil = build_profile(df)
    prompt_systeme = charger_prompt_systeme()
    tracker = UsageTracker()
    logger = RunLogger()
    print(f"Execution tracee dans {logger.dossier}")

    def appeler_modele(prompt: str) -> str:
        return asyncio.run(
            interroger(prompt, prompt_systeme, MODEL, tracker, "03_plan")
        )

    plan = planifier(question_metier, profil, appeler_modele, logger)
    inventees = colonnes_inventees(plan, [c["nom"] for c in profil["colonnes"]])
    non_mobilisees = variables_non_mobilisees(plan)

    logger.ecrire_meta(
        modele=MODEL,
        voie=VOIE,
        question_metier=question_metier,
        n_sous_questions=len(plan.sous_questions),
        n_colonnes_inventees=sum(len(c) for c in inventees.values()),
        n_variables_non_mobilisees=len(non_mobilisees),
        usage=tracker.summary(),
    )

    afficher(plan, inventees, non_mobilisees)
    tracker.print_table()


if __name__ == "__main__":
    main()
