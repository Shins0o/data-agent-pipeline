"""Socle partage de l'agent 1.

Contient tout ce qui est identique entre les deux implementations :
le calcul deterministe du profil, le prompt systeme, le nettoyage de sortie.
Aucune dependance vers un SDK Anthropic ici, volontairement.
"""

from __future__ import annotations

import json

import pandas as pd

SYSTEM_PROMPT = """Tu es un analyste de donnees senior.
On te fournit le profil technique d'un dataset (colonnes, types, taux de
valeurs manquantes, statistiques descriptives, exemples de lignes).

Ta mission : produire une lecture analytique de ce dataset.

Reponds UNIQUEMENT avec un objet JSON valide, sans texte avant ni apres,
sans balises Markdown, respectant exactement ce schema :

{
  "resume": "2 ou 3 phrases decrivant ce que contient le dataset",
  "colonnes_cles": ["liste des colonnes les plus exploitables"],
  "problemes_qualite": [
    {"colonne": "...", "probleme": "...", "gravite": "faible|moyenne|elevee"}
  ],
  "questions_analytiques": [
    {"question": "...", "colonnes_necessaires": ["..."]}
  ]
}

Propose 5 questions analytiques, orientees business, sans prediction ni
machine learning."""


def build_profile(df: pd.DataFrame) -> dict:
    """Calcule le profil technique du dataset. Aucun LLM implique."""
    return {
        "n_lignes": len(df),
        "n_colonnes": len(df.columns),
        "colonnes": [
            {
                "nom": col,
                "type": str(df[col].dtype),
                "taux_manquant": round(df[col].isna().mean(), 3),
                "n_valeurs_uniques": int(df[col].nunique()),
            }
            for col in df.columns
        ],
        "statistiques": json.loads(df.describe(include="number").round(2).to_json()),
        "extrait": json.loads(df.head(3).to_json(orient="records")),
    }


def nettoyer_json(texte: str) -> str:
    """Retire les balises Markdown que le modele ajoute parfois malgre la consigne."""
    texte = texte.strip()
    return texte.removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def construire_prompt(profile: dict) -> str:
    return f"Voici le profil du dataset :\n\n{json.dumps(profile, ensure_ascii=False)}"