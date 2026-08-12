"""Agent 1 : profilage du dataset Steam (implementation Agent SDK).

Variante de developpement. Passe par le CLI Claude Code, donc par
l'authentification de l'abonnement et non par une cle API facturee.

Prerequis : Node.js, le CLI Claude Code installe et authentifie.
Lancement : python -m agents.profiler_agent
"""

from __future__ import annotations

import asyncio
import json
import os

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

import pandas as pd

from agents import PROJECT_ROOT
from agents.profiling import SYSTEM_PROMPT, build_profile, construire_prompt, nettoyer_json
from agents.usage import UsageTracker

# Pas de load_dotenv ici, volontairement : si ANTHROPIC_API_KEY se retrouve
# dans l'environnement, le CLI la prioriserait sur l'abonnement et facturerait.

SAMPLE_PATH = PROJECT_ROOT / "data" / "samples" / "games_sample.csv"
OUTPUT_PATH = PROJECT_ROOT / "outputs" / "01_profile_agent.json"
USAGE_PATH = PROJECT_ROOT / "outputs" / "usage_report_agent.json"
MODEL = "claude-sonnet-5"
BUDGET_MAX_USD = 0.50
MAX_TURNS = 3


def verifier_environnement() -> None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ATTENTION : ANTHROPIC_API_KEY est definie dans l'environnement.\n"
            "Cette execution sera facturee au lieu d'utiliser l'abonnement.\n"
            "Ouvre un terminal propre ou supprime la variable pour rester sur l'abonnement."
        )


async def interroger_agent(profile: dict, tracker: UsageTracker) -> dict:
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=MODEL,
        # Un tour n'est pas un appel au modele : le CLI en consomme un pour
        # son initialisation. Avec 1, la limite tombe systematiquement.
        max_turns=MAX_TURNS,
        max_budget_usd=BUDGET_MAX_USD,
        # Un nom nu retire l'outil du contexte. allowed_tools ne filtre pas,
        # c'est une liste d'auto-approbation.
        disallowed_tools=["Bash", "Read", "Write", "Edit", "WebSearch", "WebFetch"],
        # Ignore CLAUDE.md, skills et settings locaux : meme comportement partout.
        setting_sources=[],
    )

    morceaux: list[str] = []
    resultat: ResultMessage | None = None

    try:
        async for message in query(prompt=construire_prompt(profile), options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        morceaux.append(block.text)
            elif isinstance(message, ResultMessage):
                resultat = message
    except Exception as exc:
        raise RuntimeError(f"Echec de la requete Claude Code : {exc}") from exc

    if resultat is None:
        raise RuntimeError("Aucun ResultMessage recu, la session a echoue.")

    tracker.from_agent_sdk("01_profilage", resultat)
    texte = nettoyer_json("".join(morceaux))

    try:
        return json.loads(texte)
    except json.JSONDecodeError:
        print("Le modele n'a pas renvoye du JSON valide. Reponse brute :")
        print(texte)
        raise


async def main() -> None:
    verifier_environnement()

    df = pd.read_csv(SAMPLE_PATH)
    print(f"Dataset charge : {len(df)} lignes, {len(df.columns)} colonnes")

    profile = build_profile(df)
    prompt = construire_prompt(profile)
    print(f"Profil technique calcule ({len(prompt):,} caracteres de prompt)")

    tracker = UsageTracker()
    analyse = await interroger_agent(profile, tracker)
    print("Analyse recue")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "source": str(SAMPLE_PATH.relative_to(PROJECT_ROOT)),
                "modele": MODEL,
                "voie": "claude-agent-sdk (abonnement)",
                "profil_technique": profile,
                "analyse_llm": analyse,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Rapport ecrit dans {OUTPUT_PATH}")

    print("\nQuestions proposees :")
    for q in analyse["questions_analytiques"]:
        print(f"  - {q['question']}")

    tracker.print_table()
    tracker.save(USAGE_PATH)


if __name__ == "__main__":
    asyncio.run(main())