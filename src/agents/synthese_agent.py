"""Le synthetiseur, lance sur une campagne deja executee (voie abonnement).

Relit un campagne.json et n'execute aucune analyse. C'est ce qui permet de
retoucher le synthetiseur autant de fois qu'il faut pour le prix d'un seul
appel, sur une entree identique d'un essai a l'autre : relancer la campagne
replanifierait, donc changerait ce qu'on cherche a comparer.

Chaque synthese est une execution a part, dans son propre dossier de runs/,
dont le meta.json pointe vers la campagne source.

Lancement :
    python -m agents.synthese_agent                      # derniere campagne
    python -m agents.synthese_agent runs/20260921-122758 # une campagne donnee
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from agents.rendu_rapport import rendre_markdown
from agents.sdk_abonnement import interroger, verifier_environnement
from agents.synthese import SyntheseVerifiee, charger_prompt_systeme, synthetiser
from agents.usage import UsageTracker
from schemas.contracts import ResultatCampagne
from utils.run_logger import RUNS_DIR, RunLogger

MODEL = "claude-sonnet-5"
VOIE = "claude-agent-sdk (abonnement)"
NOM_CAMPAGNE = "campagne.json"


def campagne_a_lire(arguments: list[str], racine: Path = RUNS_DIR) -> Path:
    """Le campagne.json designe, ou a defaut le plus recent.

    Les dossiers de runs/ sont horodates, donc l'ordre alphabetique est
    l'ordre chronologique.
    """
    if arguments:
        chemin = Path(arguments[0]) / NOM_CAMPAGNE
        if not chemin.exists():
            raise SystemExit(f"Aucun {NOM_CAMPAGNE} dans {arguments[0]}.")
        return chemin

    campagnes = sorted(racine.glob(f"*/{NOM_CAMPAGNE}"))
    if not campagnes:
        raise SystemExit(
            f"Aucun {NOM_CAMPAGNE} dans {racine}. "
            'Lancer d\'abord : python -m agents.campagne_agent "ta question metier"'
        )
    return campagnes[-1]


def afficher(synthese: SyntheseVerifiee, rapport_md: Path) -> None:
    rapport = synthese.rapport
    print(f"\nReponse courte :\n{rapport.reponse_courte}")
    print(
        f"\n{len(rapport.constats)} constats, {len(rapport.interpretations)} interpretations, "
        f"{len(rapport.recommandations)} recommandations, {len(rapport.limites)} limites."
    )

    if synthese.chiffres_non_sources:
        print(f"\nChiffres sans source dans la campagne : {len(synthese.chiffres_non_sources)}")
        for signalement in synthese.chiffres_non_sources:
            print(f"  - {signalement.champ} : {signalement.nombre}")
            print(f"    {signalement.extrait}")
    else:
        print("\nChiffres sans source dans la campagne : aucun")

    if synthese.constats_sans_donnee:
        print(f"Constats appuyes sur une sous-question sans resultat : {synthese.constats_sans_donnee}")

    print(f"\nRapport complet : {rapport_md}")


def main() -> None:
    verifier_environnement()

    chemin = campagne_a_lire(sys.argv[1:])
    campagne = ResultatCampagne.model_validate_json(chemin.read_text(encoding="utf-8"))
    print(f"Campagne lue : {chemin}")

    prompt_systeme = charger_prompt_systeme()
    tracker = UsageTracker()
    logger = RunLogger()
    print(f"Synthese tracee dans {logger.dossier}")

    def appeler_modele(prompt: str) -> str:
        return asyncio.run(interroger(prompt, prompt_systeme, MODEL, tracker, "05_synthese"))

    synthese = synthetiser(campagne, appeler_modele, logger)

    (logger.dossier / "synthese.json").write_text(
        json.dumps(synthese.en_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    rapport_md = logger.dossier / "rapport.md"
    rapport_md.write_text(rendre_markdown(synthese, campagne), encoding="utf-8")

    logger.ecrire_meta(
        modele=MODEL,
        voie=VOIE,
        campagne_source=str(chemin.parent),
        n_constats=len(synthese.rapport.constats),
        n_chiffres_non_sources=len(synthese.chiffres_non_sources),
        n_constats_sans_donnee=len(synthese.constats_sans_donnee),
        usage=tracker.summary(),
    )

    afficher(synthese, rapport_md)
    tracker.print_table()


if __name__ == "__main__":
    main()
