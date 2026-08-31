"""Socle de l'agent 2, l'analyste : question -> code -> execution -> reponse.

Comme pour l'agent 1, aucune dependance vers un SDK Anthropic ici. L'appel
au modele entre par une fonction passee en parametre, ce qui rend la boucle
testable sans consommer un seul appel.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pandas as pd
from pydantic import ValidationError

# nettoyer_json est partage avec l'agent 1 : les deux recoivent du JSON
# parfois enrobe de balises Markdown malgre la consigne.
from agents.profiling import nettoyer_json
from schemas.contracts import PlanAnalyse, ResultatAnalyse, TentativeExecution
from tools import PROJECT_ROOT
from tools.dataset import DERIVED_COLUMNS
from tools.execution import executer_code, rendre_valeur
from utils.run_logger import RunLogger

PROMPT_PATH = PROJECT_ROOT / "src" / "prompts" / "analyst.md"

# Trois passes au plus : la premiere ecriture, puis deux corrections. Au-dela,
# l'observation courante est qu'un analyste qui n'a pas corrige en deux fois
# ne corrige plus, il tourne. A revoir si la trace montre le contraire.
MAX_TENTATIVES = 3

# Signature d'une fonction qui envoie un prompt au modele et rend son texte.
AppelModele = Callable[[str], str]


def charger_prompt_systeme(chemin: Path = PROMPT_PATH) -> str:
    """Le prompt vit dans un fichier, jamais en double dans le code."""
    return chemin.read_text(encoding="utf-8")


def schema_pour_analyste(df: pd.DataFrame) -> dict:
    """Schema minimal pour ecrire du code : nom exact, type, origine, manquants.

    Volontairement plus pauvre que le profil de l'agent 1, qui porte en plus
    les statistiques descriptives et un extrait de lignes. L'analyste ecrit
    du code : ces deux blocs pesent l'essentiel du profil sans l'aider a
    ecrire une ligne, et ce prompt est renvoye a chaque tentative.
    """
    return {
        "n_lignes": len(df),
        "colonnes": [
            {
                "nom": nom,
                "type": str(df[nom].dtype),
                "origine": "derivee" if nom in DERIVED_COLUMNS else "brute",
                "n_manquants": int(df[nom].isna().sum()),
            }
            for nom in df.columns
        ],
    }


def construire_prompt(schema: dict, question: str) -> str:
    return (
        f"Schema du dataset :\n\n{json.dumps(schema, ensure_ascii=False)}\n\n"
        f"Question : {question}"
    )


def construire_prompt_correction(
    schema: dict, question: str, code: str, erreur: str
) -> str:
    """Prompt de reprise : le code fautif et sa stacktrace complete.

    Le schema est renvoye avec. La cause d'echec la plus frequente est un nom
    de colonne inexact, et sans le schema l'analyste corrige a l'aveugle.
    """
    return (
        f"{construire_prompt(schema, question)}\n\n"
        f"Ta tentative precedente a echoue.\n\n"
        f"Code execute :\n{code}\n\n"
        f"Erreur :\n{erreur}\n\n"
        f"Corrige la cause de cette erreur."
    )


def valider_plan(texte_brut: str) -> PlanAnalyse:
    """Frontiere du pipeline : la sortie du modele entre par ici ou pas du tout."""
    texte = nettoyer_json(texte_brut)
    try:
        return PlanAnalyse.model_validate_json(texte)
    except ValidationError:
        print("Plan non conforme au contrat. Texte brut :")
        print(texte)
        raise


def repondre(
    question: str,
    df: pd.DataFrame,
    appeler_modele: AppelModele,
    logger: RunLogger,
) -> ResultatAnalyse:
    """Boucle bornee : plan, execution, correction, au plus MAX_TENTATIVES fois.

    Les deux echecs possibles ne sont pas traites de la meme facon, et c'est
    delibere. Une erreur d'execution est rattrapable : on renvoie la
    stacktrace et l'analyste corrige. Une sortie hors contrat ne l'est pas,
    elle signale que la forme attendue n'a pas ete comprise ; relancer sur la
    meme consigne ne changerait rien, donc le pipeline s'arrete, apres avoir
    trace la reponse brute.
    """
    schema = schema_pour_analyste(df)
    logger.log("question", question=question, n_colonnes=len(schema["colonnes"]))

    tentatives: list[TentativeExecution] = []
    plan: PlanAnalyse | None = None
    erreur = ""

    for numero in range(1, MAX_TENTATIVES + 1):
        prompt = (
            construire_prompt(schema, question)
            if plan is None
            else construire_prompt_correction(schema, question, plan.code, erreur)
        )

        reponse_brute = appeler_modele(prompt)
        logger.log("reponse_brute", tentative=numero, texte=reponse_brute)

        plan = valider_plan(reponse_brute)
        logger.log(
            "plan",
            tentative=numero,
            intention=plan.intention,
            colonnes_utilisees=plan.colonnes_utilisees,
            code=plan.code,
            limites=plan.limites,
        )

        execution = executer_code(plan.code, df)

        if execution.a_reussi:
            tentatives.append(TentativeExecution(numero=numero, code=plan.code))
            valeur = rendre_valeur(execution.valeur)
            logger.log(
                "resultat",
                tentative=numero,
                valeur=valeur,
                sortie_standard=execution.sortie_standard,
            )
            return ResultatAnalyse(
                question=question,
                statut="succes",
                intention=plan.intention,
                limites=plan.limites,
                code_execute=plan.code,
                valeur=valeur,
                tentatives=tentatives,
            )

        erreur = execution.erreur
        tentatives.append(
            TentativeExecution(numero=numero, code=plan.code, erreur=erreur)
        )
        logger.log("echec_execution", tentative=numero, erreur=erreur)

    logger.log("abandon", tentatives=MAX_TENTATIVES)
    return ResultatAnalyse(
        question=question,
        statut="echec",
        intention=plan.intention,
        limites=plan.limites,
        code_execute=None,
        valeur=None,
        tentatives=tentatives,
    )
