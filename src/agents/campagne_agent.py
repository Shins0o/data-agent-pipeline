"""Une campagne complete, lancee sur l'abonnement : plan, puis analyses.

Ecrit campagne.json dans le dossier de l'execution. C'est ce fichier que le
synthetiseur lira : une campagne se rejoue sans relancer une seule analyse.

Lancement :
    python -m agents.campagne_agent "quels facteurs determinent le succes
    commercial d'un jeu sur Steam, et quel positionnement recommanderiez-vous
    a un studio independant ?"

    python -m agents.campagne_agent --rejouer runs/20260921-122758

La seconde forme reprend le plan d'une campagne passee, sans appeler le
planificateur, et relance toutes les analyses. C'est ce qui permet de
mesurer une retouche de l'analyste ou du synthetiseur sur les memes
sous-questions : une nouvelle campagne replanifierait, et ne mesurerait plus
la meme chose.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from agents.analysis import charger_prompt_systeme as prompt_analyste
from agents.analyst_agent import MODEL as MODELE_ANALYSTE
from agents.orchestration import conduire_campagne, rejouer_plan
from agents.planificateur_agent import MODEL as MODELE_PLANIFICATEUR
from agents.planification import AppelModele
from agents.planification import charger_prompt_systeme as prompt_planificateur
from agents.sdk_abonnement import interroger, verifier_environnement
from agents.usage import UsageTracker
from schemas.contracts import IssueSousQuestion, ResultatCampagne
from tools.dataset import add_derived_columns, load_games
from utils.run_logger import RunLogger

VOIE = "claude-agent-sdk (abonnement)"
NOM_CAMPAGNE = "campagne.json"

# Longueur de valeur affichee au terminal. La valeur complete est dans
# campagne.json et dans la trace.
EXTRAIT_TERMINAL = 400


class Compteur:
    """Compte les appels au modele sur toute la campagne.

    Le tableau de consommation ne le dit pas : le CLI y ajoute ses propres
    lignes, un appel peut en produire deux. Le nombre d'appels est pourtant
    l'une des metriques que le projet veut rendre visibles.
    """

    def __init__(self) -> None:
        self.appels = 0


def brancher(
    prompt_systeme: str, modele: str, etiquette: str, tracker: UsageTracker, compteur: Compteur
) -> AppelModele:
    """Un appelant sur l'abonnement, etiquete, qui compte ses appels."""

    def appeler(prompt: str) -> str:
        compteur.appels += 1
        return asyncio.run(interroger(prompt, prompt_systeme, modele, tracker, etiquette))

    return appeler


def fabrique_analyste(tracker: UsageTracker, compteur: Compteur):
    """Pour chaque sous-question, un appelant dont l'etiquette porte la tentative."""
    systeme = prompt_analyste()

    def fabriquer(numero: int) -> AppelModele:
        tentative = 0

        def appeler(prompt: str) -> str:
            nonlocal tentative
            tentative += 1
            compteur.appels += 1
            return asyncio.run(
                interroger(
                    prompt, systeme, MODELE_ANALYSTE, tracker, f"04_sq{numero}_t{tentative}"
                )
            )

        return appeler

    return fabriquer


def afficher_issue(issue: IssueSousQuestion) -> None:
    tentatives = len(issue.resultat.tentatives) if issue.resultat else 0
    print(f"\n{issue.numero}. [{issue.statut}, {tentatives} tentative(s)]")
    print(f"   {issue.sous_question.question}")

    if issue.statut == "hors_contrat":
        print("   Sortie de l'analyste hors contrat, aucun resultat.")
        return

    if issue.statut == "echec_execution":
        derniere = (issue.resultat.tentatives[-1].erreur or "").strip().splitlines()
        print(f"   Echec apres {tentatives} tentatives : {' '.join(derniere[-1:])}")
        return

    print(f"\n   Resultat :\n{issue.resultat.valeur[:EXTRAIT_TERMINAL]}")
    print(f"\n   Limites : {issue.resultat.limites}")


def afficher(campagne: ResultatCampagne, compteur: Compteur) -> None:
    abouties = sum(1 for issue in campagne.issues if issue.statut == "succes")
    reprises = sum(
        1 for issue in campagne.issues if issue.resultat and len(issue.resultat.tentatives) > 1
    )

    print(f"\nLecture de la question :\n{campagne.plan.lecture_question}")
    for issue in campagne.issues:
        afficher_issue(issue)

    print(f"\nHors portee :\n{campagne.plan.hors_portee}")
    print(
        f"\n{abouties}/{len(campagne.issues)} sous-questions abouties, "
        f"{reprises} avec reprise, {compteur.appels} appels modele."
    )
    if campagne.colonnes_inventees:
        print(f"Colonnes inventees par le plan : {campagne.colonnes_inventees}")
    if campagne.variables_non_mobilisees:
        print(f"Variables annoncees non mobilisees : {campagne.variables_non_mobilisees}")


def lire_arguments(arguments: list[str] | None = None) -> argparse.Namespace:
    analyseur = argparse.ArgumentParser(
        prog="python -m agents.campagne_agent",
        description="Plan puis analyses, ou rejeu du plan d'une campagne passee.",
    )
    mode = analyseur.add_mutually_exclusive_group(required=True)
    mode.add_argument("question", nargs="?", help="la question metier, entre guillemets")
    mode.add_argument(
        "--rejouer",
        type=Path,
        metavar="DOSSIER",
        help="dossier de runs/ dont le plan est repris, sans replanifier",
    )
    return analyseur.parse_args(arguments)


def charger_campagne(dossier: Path) -> ResultatCampagne:
    chemin = dossier / NOM_CAMPAGNE
    if not chemin.exists():
        raise SystemExit(f"Aucun {NOM_CAMPAGNE} dans {dossier}.")
    return ResultatCampagne.model_validate_json(chemin.read_text(encoding="utf-8"))


def main() -> None:
    verifier_environnement()
    arguments = lire_arguments()

    df = add_derived_columns(load_games())
    print(f"Dataset charge : {len(df):,} lignes, {len(df.columns)} colonnes")

    tracker = UsageTracker()
    compteur = Compteur()
    logger = RunLogger()
    print(f"Campagne tracee dans {logger.dossier}")

    if arguments.rejouer:
        source = charger_campagne(arguments.rejouer)
        print(f"Plan repris de {arguments.rejouer}, sans appel au planificateur")
        campagne = rejouer_plan(source, df, fabrique_analyste(tracker, compteur), logger)
    else:
        campagne = conduire_campagne(
            arguments.question,
            df,
            brancher(prompt_planificateur(), MODELE_PLANIFICATEUR, "03_plan", tracker, compteur),
            fabrique_analyste(tracker, compteur),
            logger,
        )

    (logger.dossier / NOM_CAMPAGNE).write_text(
        campagne.model_dump_json(indent=2), encoding="utf-8"
    )
    logger.ecrire_meta(
        voie=VOIE,
        modele_planificateur=None if arguments.rejouer else MODELE_PLANIFICATEUR,
        plan_source=str(arguments.rejouer) if arguments.rejouer else None,
        modele_analyste=MODELE_ANALYSTE,
        question_metier=campagne.question_metier,
        n_sous_questions=len(campagne.issues),
        n_abouties=sum(1 for issue in campagne.issues if issue.statut == "succes"),
        appels_modele=compteur.appels,
        usage=tracker.summary(),
    )

    afficher(campagne, compteur)
    tracker.print_table()


if __name__ == "__main__":
    main()
