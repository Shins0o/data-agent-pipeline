"""Socle du synthetiseur : campagne -> rapport final, puis controles.

Derniere des trois etapes ou le chemin ne s'ecrit pas a l'avance : relier
des resultats disperses en une reponse a la question metier, et decider ce
qu'ils permettent de recommander. Une fonction ne redige pas.

Tout ce qui l'entoure est deterministe : ce qu'il recoit
(vue_pour_synthetiseur), la validation de sa sortie (le contrat
RapportFinal), et les deux controles qui la suivent
(agents/verification_rapport.py).

Pas de boucle de reprise, pour l'instant. Contrairement au planificateur,
le synthetiseur a un retour objectif a qui on pourrait le renvoyer : la
liste de ses chiffres non sources. La reprise est donc legitime ici, mais
elle ne se justifiera que si les controles se declenchent sur la plupart
des rapports. On mesure d'abord.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from pydantic import ValidationError

from agents.profiling import nettoyer_json
from agents.verification_rapport import (
    ChiffreNonSource,
    chiffres_non_sources,
    constats_sans_donnee,
)
from schemas.contracts import (
    IssueSousQuestion,
    PlanCampagne,
    RapportFinal,
    ResultatCampagne,
)
from tools import PROJECT_ROOT
from utils.run_logger import RunLogger

PROMPT_PATH = PROJECT_ROOT / "src" / "prompts" / "synthetiseur.md"

AppelModele = Callable[[str], str]


@dataclass(frozen=True)
class SyntheseVerifiee:
    """Le rapport, et ce que les controles en disent. Les deux voyagent ensemble.

    Un rapport ne sort jamais sans ses controles : c'est ce qui permet au
    rendu de les afficher en tete, et au lecteur de savoir quoi croire.
    """

    rapport: RapportFinal
    qualite_colonnes: dict[str, dict]
    chiffres_non_sources: list[ChiffreNonSource]
    constats_sans_donnee: dict[str, list[int]]

    def en_dict(self) -> dict:
        return {
            "rapport": self.rapport.model_dump(),
            "qualite_colonnes": self.qualite_colonnes,
            "chiffres_non_sources": [asdict(c) for c in self.chiffres_non_sources],
            "constats_sans_donnee": self.constats_sans_donnee,
        }


def charger_prompt_systeme(chemin: Path = PROMPT_PATH) -> str:
    """Le prompt vit dans un fichier, jamais en double dans le code."""
    return chemin.read_text(encoding="utf-8")


def _vue_issue(issue: IssueSousQuestion) -> dict:
    vue = {
        "numero": issue.numero,
        "question": issue.sous_question.question,
        "pourquoi": issue.sous_question.pourquoi,
        "statut": issue.statut,
    }
    if issue.statut == "succes":
        vue["intention"] = issue.resultat.intention
        vue["valeur"] = issue.resultat.valeur
        vue["limites"] = issue.resultat.limites
    return vue


def vue_pour_synthetiseur(campagne: ResultatCampagne, qualite_colonnes: dict[str, dict]) -> dict:
    """Ce que le synthetiseur voit de la campagne, et ce qu'il ne voit pas.

    Pas le code genere : il ecrit des phrases, pas du pandas, et le code
    doublerait la taille du prompt sans l'aider a rediger. Il reste dans
    campagne.json, et le rapport rendu le reprend en annexe pour le lecteur.

    Rien d'une sous-question echouee hormis son statut. Il n'y a pas de
    valeur a lui montrer, et lui montrer les erreurs l'inviterait a en
    deviner le resultat.

    La fiche qualite, pour qu'une limite sur les donnees puisse etre chiffree
    avec un nombre que le controle sait retrouver.
    """
    return {
        "question_metier": campagne.question_metier,
        "lecture_question": campagne.plan.lecture_question,
        "hors_portee": campagne.plan.hors_portee,
        "qualite_colonnes": qualite_colonnes,
        "sous_questions": [_vue_issue(issue) for issue in campagne.issues],
    }


def colonnes_citees(plan: PlanCampagne, colonnes_du_dataset: list[str]) -> list[str]:
    """Les colonnes dont le plan parle, dans l'ordre du dataset.

    Celles qu'il decoupe (colonnes_necessaires, variables_cles), et celles
    qu'il nomme dans sa prose : c'est la que le planificateur ecarte une
    colonne inutilisable, "Metacritic url" dans hors_portee par exemple.
    Un nom se cherche en mot entier, pour que "Price" ne soit pas trouve
    dans "Prices" ni "Name" dans "Names".
    """
    decoupees = {c for sq in plan.sous_questions for c in sq.colonnes_necessaires}
    decoupees |= set(plan.variables_cles)
    prose = f"{plan.lecture_question}\n{plan.hors_portee}"

    def nommee(colonne: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(colonne)}(?!\w)", prose) is not None

    return [c for c in colonnes_du_dataset if c in decoupees or nommee(c)]


def fiche_qualite(profil: dict, colonnes: list[str]) -> dict[str, dict]:
    """Les manquants des colonnes citees, repris tels quels du profil.

    Aucun calcul ici : le profil est la seule source des comptes de
    manquants, pour que le chiffre du rapport et celui que le planificateur
    a lu soient le meme. Les colonnes completes sont omises : un 0 ne dit
    rien au lecteur, et chaque source en plus rend le controle des chiffres
    plus permissif.
    """
    return {
        c["nom"]: {"n_manquants": c["n_manquants"], "taux_manquant": c["taux_manquant"]}
        for c in profil["colonnes"]
        if c["nom"] in colonnes and c["n_manquants"] > 0
    }


def construire_prompt(vue: dict) -> str:
    return f"Campagne d'analyse :\n\n{json.dumps(vue, ensure_ascii=False, indent=1)}"


def valider_rapport(texte_brut: str) -> RapportFinal:
    """Frontiere du pipeline : la sortie du modele entre par ici ou pas du tout."""
    texte = nettoyer_json(texte_brut)
    try:
        return RapportFinal.model_validate_json(texte)
    except ValidationError:
        print("Rapport non conforme au contrat. Texte brut :")
        print(texte)
        raise


def synthetiser(
    campagne: ResultatCampagne,
    qualite_colonnes: dict[str, dict],
    appeler_modele: AppelModele,
    logger: RunLogger,
) -> SyntheseVerifiee:
    """Un appel, une validation, deux controles, tout trace.

    Un rapport hors contrat arrete tout : c'est la seule sortie de cette
    etape, et une chaine de preuve cassee n'a rien de recuperable.
    """
    logger.log(
        "synthese_demandee",
        question_metier=campagne.question_metier,
        n_sous_questions=len(campagne.issues),
        n_abouties=sum(1 for issue in campagne.issues if issue.statut == "succes"),
    )
    logger.log("fiche_qualite", colonnes=qualite_colonnes)

    reponse_brute = appeler_modele(
        construire_prompt(vue_pour_synthetiseur(campagne, qualite_colonnes))
    )
    logger.log("synthese_brute", texte=reponse_brute)

    rapport = valider_rapport(reponse_brute)
    logger.log(
        "rapport",
        reponse_courte=rapport.reponse_courte,
        n_constats=len(rapport.constats),
        n_interpretations=len(rapport.interpretations),
        n_recommandations=len(rapport.recommandations),
    )

    non_sources = chiffres_non_sources(rapport, campagne, qualite_colonnes)
    if non_sources:
        logger.log("chiffres_non_sources", detail=[asdict(c) for c in non_sources])

    sans_donnee = constats_sans_donnee(rapport, campagne)
    if sans_donnee:
        logger.log("constats_sans_donnee", detail=sans_donnee)

    return SyntheseVerifiee(rapport, qualite_colonnes, non_sources, sans_donnee)
