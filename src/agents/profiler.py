"""Agent 1 : profilage du dataset Steam (implementation Client SDK).

Voie de reference du projet. Passe par une cle API, donc facturee, mais
reproductible par n'importe qui sans installer Claude Code.

Lancement : python -m agents.profiler
"""

from __future__ import annotations

import os

from anthropic import Anthropic
from dotenv import load_dotenv

from agents.profiling import (
    SYSTEM_PROMPT,
    charger_et_profiler,
    construire_prompt,
    ecrire_rapport,
    valider_reponse,
)
from agents.usage import UsageTracker
from schemas.contracts import LectureDataset
from tools import PROJECT_ROOT

load_dotenv()

OUTPUT_PATH = PROJECT_ROOT / "outputs" / "01_profile.json"
USAGE_PATH = PROJECT_ROOT / "outputs" / "usage_report.json"
MODEL = "claude-sonnet-5"
VOIE = "anthropic (cle API)"


def interroger_claude(
    client: Anthropic, profile: dict, tracker: UsageTracker
) -> LectureDataset:
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": construire_prompt(profile)}],
    )

    tracker.from_client_sdk("01_profilage", MODEL, response)
    return valider_reponse(response.content[0].text)


def main() -> None:
    profile = charger_et_profiler()

    tracker = UsageTracker()
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    analyse = interroger_claude(client, profile, tracker)
    print("Analyse recue et validee")

    ecrire_rapport(OUTPUT_PATH, profile, analyse, MODEL, VOIE)
    tracker.print_table()
    tracker.save(USAGE_PATH)


if __name__ == "__main__":
    main()
