"""Agent 2 : l'analyste (voie abonnement).

Repond a une question posee en argument, en generant puis executant du code
pandas sur le dataset. Toute l'execution est tracee dans runs/.

Lancement : python -m agents.analyst_agent "part des jeux gratuits"
"""

from __future__ import annotations

import asyncio
import sys

from agents.analysis import charger_prompt_systeme, repondre
from agents.sdk_abonnement import interroger, verifier_environnement
from agents.usage import UsageTracker
from schemas.contracts import ResultatAnalyse
from tools.dataset import add_derived_columns, load_games
from utils.run_logger import RunLogger

MODEL = "claude-sonnet-5"
VOIE = "claude-agent-sdk (abonnement)"


def afficher(resultat: ResultatAnalyse) -> None:
    """Separe ce que la donnee montre de ce que le calcul suppose."""
    print(f"\nQuestion   : {resultat.question}")
    print(f"Statut     : {resultat.statut} ({len(resultat.tentatives)} tentative(s))")

    if resultat.statut == "echec":
        print("\nAucun resultat : les tentatives ont toutes echoue.")
        for tentative in resultat.tentatives:
            premiere_ligne = (tentative.erreur or "").strip().splitlines()[-1:]
            print(f"  tentative {tentative.numero} : {' '.join(premiere_ligne)}")
        return

    print(f"\nIntention  : {resultat.intention}")
    print(f"\nCode execute :\n{resultat.code_execute}")
    print(f"\nResultat :\n{resultat.valeur}")
    print(f"\nLimites    : {resultat.limites}")


def main() -> None:
    verifier_environnement()

    question = " ".join(sys.argv[1:]).strip()
    if not question:
        raise SystemExit('Usage : python -m agents.analyst_agent "ta question"')

    df = add_derived_columns(load_games())
    print(f"Dataset charge : {len(df):,} lignes, {len(df.columns)} colonnes")

    prompt_systeme = charger_prompt_systeme()
    tracker = UsageTracker()
    logger = RunLogger()
    print(f"Execution tracee dans {logger.dossier}")

    tentative = 0

    def appeler_modele(prompt: str) -> str:
        # Chaque tentative ouvre sa propre session CLI, donc renvoie le schema.
        # C'est le cout assume de la boucle deterministe : il apparait
        # tentative par tentative dans le tableau de consommation, ce qui
        # permet de decider plus tard s'il justifie une session persistante.
        nonlocal tentative
        tentative += 1
        return asyncio.run(
            interroger(prompt, prompt_systeme, MODEL, tracker, f"02_analyse_t{tentative}")
        )

    resultat = repondre(question, df, appeler_modele, logger)

    logger.ecrire_meta(
        modele=MODEL,
        voie=VOIE,
        question=question,
        statut=resultat.statut,
        tentatives=len(resultat.tentatives),
        usage=tracker.summary(),
    )

    afficher(resultat)
    tracker.print_table()


if __name__ == "__main__":
    main()
