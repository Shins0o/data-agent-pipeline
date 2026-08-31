"""Socle partage de l'agent 1.

Contient tout ce qui est identique entre les deux implementations : le calcul
deterministe du profil, le prompt systeme, la validation de la reponse et
l'ecriture du rapport. Seul l'appel au modele differe d'une voie a l'autre.

Aucune dependance vers un SDK Anthropic ici, volontairement.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

from schemas.contracts import LectureDataset
from tools import PROJECT_ROOT
from tools.dataset import DERIVED_COLUMNS, RAW_PATH, add_derived_columns, load_games

# Au-dela, une valeur d'exemple est tronquee : 'About the game' depasse
# souvent 2 000 caracteres et n'apprend rien sur la structure du dataset.
LONGUEUR_MAX_EXEMPLE = 200

SYSTEM_PROMPT = """Tu es un analyste de donnees senior.
On te fournit le profil technique d'un dataset (colonnes, types, nombre et
taux de valeurs manquantes, statistiques descriptives, exemples de lignes).

Chaque colonne porte un champ "origine" : "brute" si elle provient du fichier
source, "derivee" si le pipeline l'a construite. Une colonne derivee est un
proxy, pas une mesure : signale-le quand tu t'appuies dessus.

Le champ "taux_manquant" est arrondi : c'est "n_manquants", un compte exact,
qui fait foi. N'affirme jamais qu'une colonne est entierement vide sans que
"n_manquants" soit egal a "n_lignes".

Les valeurs d'exemple trop longues sont tronquees, cela ne reflete pas la
donnee reelle.

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


def _tronquer(valeur):
    """Raccourcit une valeur texte trop longue pour un exemple de ligne."""
    if isinstance(valeur, str) and len(valeur) > LONGUEUR_MAX_EXEMPLE:
        return valeur[:LONGUEUR_MAX_EXEMPLE] + " [...tronque]"
    return valeur


def _profil_colonne(serie: pd.Series, nom: str) -> dict:
    """Profil d'une colonne. n_manquants est exact, taux_manquant est arrondi."""
    n_manquants = int(serie.isna().sum())
    return {
        "nom": nom,
        "type": str(serie.dtype),
        "origine": "derivee" if nom in DERIVED_COLUMNS else "brute",
        "n_manquants": n_manquants,
        "taux_manquant": round(n_manquants / len(serie), 3),
        "n_valeurs_uniques": int(serie.nunique()),
    }


def build_profile(df: pd.DataFrame) -> dict:
    """Calcule le profil technique du dataset. Aucun LLM implique."""
    extrait = json.loads(df.head(3).to_json(orient="records", date_format="iso"))

    return {
        "n_lignes": len(df),
        "n_colonnes": len(df.columns),
        "colonnes": [_profil_colonne(df[col], col) for col in df.columns],
        "statistiques": json.loads(df.describe(include="number").round(2).to_json()),
        "extrait": [
            {col: _tronquer(valeur) for col, valeur in ligne.items()}
            for ligne in extrait
        ],
    }


def nettoyer_json(texte: str) -> str:
    """Retire les balises Markdown que le modele ajoute parfois malgre la consigne."""
    texte = texte.strip()
    return texte.removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def construire_prompt(profile: dict) -> str:
    return f"Voici le profil du dataset :\n\n{json.dumps(profile, ensure_ascii=False)}"


def valider_reponse(texte_brut: str) -> LectureDataset:
    """Frontiere du pipeline : la sortie du modele entre par ici ou pas du tout.

    JSON invalide et JSON valide mais hors contrat levent la meme exception,
    apres affichage du texte brut : sans lui, l'erreur est indebuggable.
    """
    texte = nettoyer_json(texte_brut)
    try:
        return LectureDataset.model_validate_json(texte)
    except ValidationError:
        print("Reponse du modele non conforme au contrat. Texte brut :")
        print(texte)
        raise


def charger_et_profiler() -> dict:
    """Charge le dataset complet et calcule son profil technique."""
    df = add_derived_columns(load_games())
    print(f"Dataset charge : {len(df):,} lignes, {len(df.columns)} colonnes")

    profile = build_profile(df)
    taille = len(construire_prompt(profile))
    print(f"Profil technique calcule ({taille:,} caracteres de prompt)")
    return profile


def ecrire_rapport(
    chemin: Path, profile: dict, analyse: LectureDataset, modele: str, voie: str
) -> None:
    """Ecrit le rapport d'execution et affiche les questions proposees."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(
            {
                "source": str(RAW_PATH.relative_to(PROJECT_ROOT)),
                "modele": modele,
                "voie": voie,
                "profil_technique": profile,
                "analyse_llm": analyse.model_dump(),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Rapport ecrit dans {chemin}")

    print("\nQuestions proposees :")
    for q in analyse.questions_analytiques:
        print(f"  - {q.question}")
