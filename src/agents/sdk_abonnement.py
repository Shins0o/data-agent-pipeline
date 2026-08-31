"""Appel du CLI Claude Code via l'Agent SDK, sur l'abonnement.

Isole ici parce que la partie qui compte, le diagnostic d'un echec, ne
merite d'etre ecrite qu'une fois.

Note de dette : agents/profiler_agent.py porte encore sa propre copie de
cette plomberie. Elle sera migree ici une fois l'analyste valide, dans un
commit qui ne fait que ca.
"""

from __future__ import annotations

import os

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from agents.usage import UsageTracker

# Un nom nu retire l'outil du contexte. allowed_tools ne filtre pas, c'est une
# liste d'auto-approbation.
OUTILS_INTERDITS = ["Bash", "Read", "Write", "Edit", "WebSearch", "WebFetch"]

# Un tour n'est pas un appel au modele : le CLI en consomme un pour son
# initialisation. Avec 1, la limite tombe systematiquement.
MAX_TURNS = 3
BUDGET_MAX_USD = 0.50


def verifier_environnement() -> None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ATTENTION : ANTHROPIC_API_KEY est definie dans l'environnement.\n"
            "Cette execution sera facturee au lieu d'utiliser l'abonnement.\n"
            "Ouvre un terminal propre ou supprime la variable pour rester sur l'abonnement."
        )


def tracer_echec(resultat: ResultMessage | None, morceaux: list[str]) -> None:
    """Affiche tout ce que le CLI a renvoye avant de signaler l'erreur.

    Le ResultMessage arrive dans le flux juste avant l'exception : sans cet
    affichage, son contenu est perdu et une panne reseau, une limite atteinte
    et un CLI non authentifie produisent le meme message illisible.
    """
    print("\n--- Diagnostic de l'echec ---")
    if resultat is None:
        print("Aucun ResultMessage recu.")
    else:
        print(f"subtype          : {resultat.subtype}")
        print(f"is_error         : {resultat.is_error}")
        print(f"stop_reason      : {resultat.stop_reason}")
        print(f"api_error_status : {resultat.api_error_status}")
        print(f"errors           : {resultat.errors}")
        print(f"num_turns        : {resultat.num_turns}")
        print(f"session_id       : {resultat.session_id}")
        print(f"total_cost_usd   : {resultat.total_cost_usd}")
        print(f"usage            : {resultat.usage}")
        print(f"result           : {resultat.result!r}")
    print(f"texte assistant  : {''.join(morceaux)!r}")
    print("--- fin du diagnostic ---\n")


async def interroger(
    prompt: str,
    system_prompt: str,
    model: str,
    tracker: UsageTracker,
    etape: str,
) -> str:
    """Envoie un prompt et rend le texte assistant concatene, sans le valider.

    La validation appartient a l'appelant : ce module ne sait pas quel
    contrat la reponse doit respecter, et n'a pas a le savoir.
    """
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=model,
        max_turns=MAX_TURNS,
        max_budget_usd=BUDGET_MAX_USD,
        disallowed_tools=OUTILS_INTERDITS,
        # Ignore CLAUDE.md, skills et settings locaux : meme comportement partout.
        setting_sources=[],
    )

    morceaux: list[str] = []
    resultat: ResultMessage | None = None

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        morceaux.append(block.text)
            elif isinstance(message, ResultMessage):
                resultat = message
    except Exception as exc:
        tracer_echec(resultat, morceaux)
        raise RuntimeError(f"Echec de la requete Claude Code : {exc}") from exc

    if resultat is None:
        raise RuntimeError("Aucun ResultMessage recu, la session a echoue.")

    tracker.from_agent_sdk(etape, resultat)
    return "".join(morceaux)
