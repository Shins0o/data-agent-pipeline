"""Harnais d'evaluation : rejoue les questions de reference via l'analyste.

Une execution reussie ne prouve rien. Ce module repond a la seule question
qui vaille avant de construire par-dessus l'analyste : sur des questions
dont la reponse est connue, combien de fois tombe-t-il juste, en combien de
tentatives, et pour quelle consommation.

Ce qu'il mesure, question par question :
- le verdict, compare a la verite terrain d'evaluation/reference.py
- le nombre de tentatives, donc le taux de recours a l'auto-correction
- la duree et les tokens, attribues a la question et non au total

La comparaison se fait sur la valeur rendue en texte. Chaque nombre attendu
doit se retrouver dans ce texte, a la tolerance de la question, et chaque
libelle attendu doit y apparaitre. C'est faillible dans un sens et un seul :
sur un resultat tabulaire, un nombre peut coincider par hasard et faire
passer une reponse fausse pour juste. Le rapport affiche donc toujours
l'attendu et l'obtenu, et un verdict `correct` sur une reponse tabulaire se
verifie a l'oeil.

Une campagne consomme un appel modele par tentative, soit six au minimum.
Ce n'est pas un test, ca ne tourne pas a chaque commit.

Lancement : python -m evaluation.harness
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ValidationError

from agents.analysis import AppelModele, charger_prompt_systeme, repondre
from agents.analyst_agent import MODEL, VOIE
from agents.sdk_abonnement import interroger, verifier_environnement
from agents.usage import Usage, UsageTracker
from evaluation.reference import (
    QUESTIONS_REFERENCE,
    QuestionReference,
    valeur_proche,
)
from tools.dataset import add_derived_columns, load_games
from utils.run_logger import RunLogger

Verdict = Literal["correct", "incorrect", "echec_execution", "hors_contrat"]

# Un nombre tel que Python et pandas les ecrivent : ni separateur de milliers,
# ni virgule decimale. La valeur comparee vient de rendre_valeur(), donc d'un
# str() ou d'un to_string(), jamais d'un formatage localise.
MOTIF_NOMBRE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")

# Longueur de l'extrait conserve dans le rapport. La valeur complete reste
# dans la trace : c'est le rapport qu'on veut lisible, pas tronque a la source.
EXTRAIT_MAX = 600


class VerdictQuestion(BaseModel):
    """Ce que la campagne a observe sur une question, et de quoi l'arbitrer."""

    id: str
    question: str
    verdict: Verdict
    note: str
    tolerance: float
    libelles_attendus: list[str]
    libelles_manquants: list[str]
    valeurs_attendues: list[float]
    valeurs_manquantes: list[float]
    valeur_rendue: str | None
    code_execute: str | None
    limites: str | None
    tentatives: int
    duree_s: float
    tokens: int
    cout_usd: float


class RapportEvaluation(BaseModel):
    """Synthese d'une campagne. C'est le fichier qu'on relit dans six mois."""

    debut: str
    modele: str
    voie: str
    n_lignes: int
    n_questions: int
    n_correct: int
    taux_justesse: float
    appels_modele: int
    duree_s: float
    verdicts: list[VerdictQuestion]
    usage: dict


def extraire_nombres(texte: str) -> list[float]:
    """Tous les nombres presents dans la valeur rendue."""
    return [float(brut) for brut in MOTIF_NOMBRE.findall(texte)]


def _nombres_rattaches(libelle: str, valeur_rendue: str) -> list[float]:
    """Les nombres qu'un libelle attendu a le droit de justifier.

    Ceux de sa ligne, quand elle en porte : dans un classement, la valeur
    attendue doit etre sur la ligne du libelle attendu, pas n'importe ou
    dans le tableau. Sinon tous les nombres du rendu, parce qu'une Series
    rendue en enregistrement met le libelle et la valeur sur deux lignes :
    "genre   Early Access" puis "prix_median   6.39".
    """
    lignes = [
        ligne for ligne in valeur_rendue.splitlines() if libelle.lower() in ligne.lower()
    ]
    nombres_de_ligne = [n for ligne in lignes for n in extraire_nombres(ligne)]
    return nombres_de_ligne or extraire_nombres(valeur_rendue)


def comparer(
    reference: QuestionReference, valeur_rendue: str
) -> tuple[list[str], list[float]]:
    """Rend ce qui manque : libelles absents, puis valeurs introuvables.

    Deux listes vides valent `correct`. Rendre ce qui manque plutot qu'un
    booleen est ce qui permet au rapport de dire pourquoi une reponse est
    refusee, et a un humain de trancher quand le refus est discutable.

    Quand la question attend un libelle, la valeur attendue se cherche sur
    la ligne de ce libelle. Depuis que l'analyste rend le haut d'un
    classement, chercher partout faisait passer une valeur voisine : sur q3,
    Indie a 0.826 tombe dans la tolerance de 0.83 attendu pour Casual. Le
    controle ne portait plus sur la bonne ligne.

    Ce que ce controle ne verifie toujours pas : que le libelle attendu soit
    en tete du classement rendu.
    """
    rendu = valeur_rendue.lower()
    libelles_manquants = [
        libelle
        for libelle in reference.libelles_attendus
        if libelle.lower() not in rendu
    ]

    if reference.libelles_attendus:
        nombres = [
            n
            for libelle in reference.libelles_attendus
            for n in _nombres_rattaches(libelle, valeur_rendue)
        ]
    else:
        nombres = extraire_nombres(valeur_rendue)

    valeurs_manquantes = [
        attendue
        for attendue in reference.valeurs_attendues
        if not any(
            valeur_proche(nombre, attendue, reference.tolerance) for nombre in nombres
        )
    ]
    return libelles_manquants, valeurs_manquantes


def consommation(entrees: list[Usage]) -> tuple[int, float]:
    return (
        sum(entree.total_tokens for entree in entrees),
        round(sum(entree.cost_usd for entree in entrees), 4),
    )


def evaluer_une(
    reference: QuestionReference,
    df: pd.DataFrame,
    appeler_modele: AppelModele,
    logger: RunLogger,
    tracker: UsageTracker,
) -> VerdictQuestion:
    """Rejoue une question et rend son verdict.

    Une sortie hors contrat arrete le pipeline pour cette question, c'est le
    comportement voulu et teste. Elle n'arrete pas la campagne : le harnais
    la classe `hors_contrat` et passe a la suivante, sinon une seule reponse
    malformee prive de mesure les cinq questions restantes.

    Un echec du SDK, lui, n'est pas rattrape. Limite d'abonnement atteinte ou
    CLI non authentifie : continuer produirait un rapport de zeros qui
    ressemble a une mesure.
    """
    debut = time.monotonic()
    depart = len(tracker.entries)
    logger.log("evaluation_question", id=reference.id)

    commun = {
        "id": reference.id,
        "question": reference.question,
        "note": reference.note,
        "tolerance": reference.tolerance,
        "libelles_attendus": list(reference.libelles_attendus),
        "valeurs_attendues": list(reference.valeurs_attendues),
    }

    try:
        resultat = repondre(reference.question, df, appeler_modele, logger)
    except ValidationError as exc:
        logger.log("evaluation_hors_contrat", id=reference.id, erreur=str(exc))
        tokens, cout = consommation(tracker.entries[depart:])
        return VerdictQuestion(
            **commun,
            verdict="hors_contrat",
            libelles_manquants=list(reference.libelles_attendus),
            valeurs_manquantes=list(reference.valeurs_attendues),
            valeur_rendue=None,
            code_execute=None,
            limites=None,
            tentatives=0,
            duree_s=round(time.monotonic() - debut, 1),
            tokens=tokens,
            cout_usd=cout,
        )

    if resultat.statut == "echec":
        verdict: Verdict = "echec_execution"
        libelles_manquants = list(reference.libelles_attendus)
        valeurs_manquantes = list(reference.valeurs_attendues)
    else:
        libelles_manquants, valeurs_manquantes = comparer(reference, resultat.valeur)
        verdict = (
            "correct" if not libelles_manquants and not valeurs_manquantes else "incorrect"
        )

    logger.log(
        "evaluation_verdict",
        id=reference.id,
        verdict=verdict,
        libelles_manquants=libelles_manquants,
        valeurs_manquantes=valeurs_manquantes,
    )

    tokens, cout = consommation(tracker.entries[depart:])
    return VerdictQuestion(
        **commun,
        verdict=verdict,
        libelles_manquants=libelles_manquants,
        valeurs_manquantes=valeurs_manquantes,
        valeur_rendue=(resultat.valeur or "")[:EXTRAIT_MAX] or None,
        code_execute=resultat.code_execute,
        limites=resultat.limites,
        tentatives=len(resultat.tentatives),
        duree_s=round(time.monotonic() - debut, 1),
        tokens=tokens,
        cout_usd=cout,
    )


def fabriquer_appel(
    reference: QuestionReference, prompt_systeme: str, tracker: UsageTracker
) -> AppelModele:
    """Un appelant par question, pour que la consommation porte son etiquette.

    L'etiquette `eval_<id>_t<n>` est ce qui rend le tableau de consommation
    lisible : sans elle, six questions et leurs reprises se confondent en une
    colonne de lignes anonymes.
    """
    tentative = 0

    def appeler(prompt: str) -> str:
        nonlocal tentative
        tentative += 1
        return asyncio.run(
            interroger(
                prompt,
                prompt_systeme,
                MODEL,
                tracker,
                f"eval_{reference.id}_t{tentative}",
            )
        )

    return appeler


def lancer_campagne(
    df: pd.DataFrame, logger: RunLogger, tracker: UsageTracker
) -> RapportEvaluation:
    prompt_systeme = charger_prompt_systeme()
    debut = time.monotonic()

    verdicts = [
        evaluer_une(
            reference,
            df,
            fabriquer_appel(reference, prompt_systeme, tracker),
            logger,
            tracker,
        )
        for reference in QUESTIONS_REFERENCE
    ]

    n_correct = sum(1 for verdict in verdicts if verdict.verdict == "correct")
    return RapportEvaluation(
        debut=logger.debut.isoformat(timespec="seconds"),
        modele=MODEL,
        voie=VOIE,
        n_lignes=len(df),
        n_questions=len(verdicts),
        n_correct=n_correct,
        taux_justesse=round(n_correct / len(verdicts), 3),
        appels_modele=sum(verdict.tentatives for verdict in verdicts),
        duree_s=round(time.monotonic() - debut, 1),
        verdicts=verdicts,
        usage=tracker.summary(),
    )


def afficher(rapport: RapportEvaluation) -> None:
    """Le tableau d'abord, puis le detail des seules questions a arbitrer."""
    print(f"\n{'Question':<32} {'Verdict':<16} {'Tent.':>6} {'Duree':>8} {'Tokens':>9}")
    print("-" * 75)
    for verdict in rapport.verdicts:
        print(
            f"{verdict.id:<32} {verdict.verdict:<16} {verdict.tentatives:>6} "
            f"{verdict.duree_s:>7.1f}s {verdict.tokens:>9,}"
        )
    print("-" * 75)
    print(
        f"{rapport.n_correct}/{rapport.n_questions} correctes "
        f"({rapport.taux_justesse:.0%}), {rapport.appels_modele} appels modele, "
        f"{rapport.duree_s:.0f}s"
    )

    for verdict in rapport.verdicts:
        if verdict.verdict == "correct":
            continue
        print(f"\n--- {verdict.id} : {verdict.verdict} ---")
        print(f"Question  : {verdict.question}")
        print(f"Arbitrage : {verdict.note}")
        if verdict.libelles_manquants:
            print(f"Libelles introuvables : {verdict.libelles_manquants}")
        if verdict.valeurs_manquantes:
            # :g et non :.2% : une tolerance de 1e-06 s'afficherait 0,00 %,
            # ce qui se lit comme une egalite stricte alors qu'elle n'en est pas.
            print(
                f"Valeurs introuvables  : {verdict.valeurs_manquantes} "
                f"(tolerance relative {verdict.tolerance:g})"
            )
        print(f"Valeur rendue :\n{verdict.valeur_rendue}")


def main() -> None:
    verifier_environnement()

    df = add_derived_columns(load_games())
    print(f"Dataset charge : {len(df):,} lignes, {len(df.columns)} colonnes")

    tracker = UsageTracker()
    logger = RunLogger()
    print(f"Campagne tracee dans {logger.dossier}")

    rapport = lancer_campagne(df, logger, tracker)

    (logger.dossier / "evaluation.json").write_text(
        rapport.model_dump_json(indent=2), encoding="utf-8"
    )
    logger.ecrire_meta(
        modele=rapport.modele,
        voie=rapport.voie,
        campagne="questions de reference",
        n_correct=rapport.n_correct,
        n_questions=rapport.n_questions,
        appels_modele=rapport.appels_modele,
        usage=rapport.usage,
    )

    afficher(rapport)
    tracker.print_table()


if __name__ == "__main__":
    main()
