"""Agent 1 : profilage du dataset Steam (implementation Client SDK).

Voie de reference du projet. Passe par une cle API, donc facturee, mais
reproductible par n'importe qui sans installer Claude Code.

Lancement : python -m agents.profiler
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
from anthropic import Anthropic
from dotenv import load_dotenv

from agents.profiling import SYSTEM_PROMPT, build_profile, construire_prompt, nettoyer_json
from agents.usage import UsageTracker

load_dotenv()

SAMPLE_PATH = Path("data/samples/games_sample.csv")
OUTPUT_PATH = Path("outputs/01_profile.json")
USAGE_PATH = Path("outputs/usage_report.json")
MODEL = "claude-sonnet-5"


def interroger_claude(client: Anthropic, profile: dict, tracker: UsageTracker) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": construire_prompt(profile)}],
    )

    tracker.from_client_sdk("01_profilage", MODEL, response)
    texte = nettoyer_json(response.content[0].text)

    try:
        return json.loads(texte)
    except json.JSONDecodeError:
        print("Le modele n'a pas renvoye du JSON valide. Reponse brute :")
        print(texte)
        raise


def main() -> None:
    df = pd.read_csv(SAMPLE_PATH)
    print(f"Dataset charge : {len(df)} lignes, {len(df.columns)} colonnes")

    profile = build_profile(df)
    print("Profil technique calcule")

    tracker = UsageTracker()
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    analyse = interroger_claude(client, profile, tracker)
    print("Analyse recue")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "source": str(SAMPLE_PATH),
                "modele": MODEL,
                "voie": "anthropic (cle API)",
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
    main()