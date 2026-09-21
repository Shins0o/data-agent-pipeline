"""Socle partage de l'agent 1.

Contient tout ce qui est identique entre les deux implementations : le calcul
deterministe du profil, le prompt systeme, la validation de la reponse et
l'ecriture du rapport. Seul l'appel au modele differe d'une voie a l'autre.

Aucune dependance vers un SDK Anthropic ici, volontairement.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype
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

Le champ "asymetrie" n'apparait que sur les colonnes numeriques. Au dela de
2 en valeur absolue, une poignee de lignes pese l'essentiel du total : toute
moyenne sur cette colonne est alors trompeuse, et c'est un point a signaler.

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


def _asymetrie(serie: pd.Series) -> float | None:
    """Coefficient d'asymetrie d'une colonne numerique, arrondi.

    Mesure deterministe d'une propriete qu'on laissait jusqu'ici a un agent
    le soin de deviner en lisant describe(). Au dela de 2 en valeur absolue,
    une poignee de lignes pese l'essentiel du total : une tendance centrale
    par segment decrit alors la masse ordinaire et masque ce qui fait la
    difference.

    Retenu contre deux indicateurs plus parlants mais faux hors de leur
    domaine. Le rapport moyenne sur mediane et la part du top 1 % ne veulent
    rien dire sur une colonne centree ou a mediane nulle. L'asymetrie se
    comporte sur n'importe quelle colonne numerique, ce qui compte pour un
    profil cense servir a n'importe quel dataset.

    None et non NaN : le profil part en JSON dans le prompt, et json.dumps
    ecrit un NaN litteral, qui n'est pas du JSON valide. Une colonne a moins
    de trois valeurs n'a pas d'asymetrie definie.
    """
    valeur = serie.skew()
    return None if pd.isna(valeur) else round(float(valeur), 2)


def _profil_colonne(serie: pd.Series, nom: str) -> dict:
    """Profil d'une colonne. n_manquants est exact, taux_manquant est arrondi."""
    n_manquants = int(serie.isna().sum())
    profil = {
        "nom": nom,
        "type": str(serie.dtype),
        "origine": "derivee" if nom in DERIVED_COLUMNS else "brute",
        "n_manquants": n_manquants,
        "taux_manquant": round(n_manquants / len(serie), 3),
        "n_valeurs_uniques": int(serie.nunique()),
    }

    # Les booleens sont numeriques pour pandas, et leur asymetrie ne dit rien
    # de plus que leur taux. Dates et texte levent sur skew().
    if is_numeric_dtype(serie) and not is_bool_dtype(serie):
        profil["asymetrie"] = _asymetrie(serie)

    return profil


def build_profile(df: pd.DataFrame) -> dict:
    """Calcule le profil technique du dataset. Aucun LLM implique.

    Les statistiques descriptives sont vides quand aucune colonne n'est
    numerique. `describe(include="number")` leve dans ce cas, et un dataset
    entierement categoriel, un corpus ou un journal d'evenements, n'a rien
    d'aberrant pour un pipeline cense fonctionner sur n'importe quel jeu de
    donnees.
    """
    extrait = json.loads(df.head(3).to_json(orient="records", date_format="iso"))
    numeriques = df.select_dtypes(include="number")

    return {
        "n_lignes": len(df),
        "n_colonnes": len(df.columns),
        "colonnes": [_profil_colonne(df[col], col) for col in df.columns],
        "statistiques": (
            json.loads(numeriques.describe().round(2).to_json())
            if not numeriques.empty
            else {}
        ),
        "extrait": [
            {col: _tronquer(valeur) for col, valeur in ligne.items()}
            for ligne in extrait
        ],
    }


def _sans_accent(texte: str) -> str:
    """'colonnes_utilisées' -> 'colonnes_utilisees'."""
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c))


def _desaccentuer_cles(valeur):
    """Retire les accents des cles, a toute profondeur. Les valeurs ne sont pas touchees.

    Si deux cles d'un meme objet se confondent une fois desaccentuees, l'objet
    est rendu tel quel : choisir laquelle garder serait une correction
    silencieuse, et le contrat rejettera la cle accentuee comme inattendue.
    """
    if isinstance(valeur, list):
        return [_desaccentuer_cles(element) for element in valeur]
    if not isinstance(valeur, dict):
        return valeur

    cles = [_sans_accent(cle) for cle in valeur]
    if len(set(cles)) != len(cles):
        return valeur
    return {cle: _desaccentuer_cles(v) for cle, v in zip(cles, valeur.values())}


def nettoyer_json(texte: str) -> str:
    """Retire les derives de forme connues avant validation, jamais le fond.

    Deux derives observees en execution reelle. Des balises Markdown autour du
    JSON, malgre la consigne. Et des cles accentuees, "colonnes_utilisées" au
    lieu de "colonnes_utilisees", quand le modele ecrit en francais accentue :
    deux sous-questions d'une campagne ont ete perdues ainsi, avec un code
    pourtant juste. Le modele avait compris le contrat, il a derive sur
    l'orthographe d'une cle.

    Seules les cles sont normalisees. Les valeurs, le code genere compris,
    passent intactes. Et la reponse brute reste dans la trace avant toute
    normalisation, donc la derive reste mesurable.

    Un JSON invalide est rendu tel quel : c'est au contrat de le rejeter, avec
    la meme erreur qu'avant, pour que les appelants qui la rattrapent
    continuent de la rattraper.
    """
    texte = texte.strip()
    texte = texte.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        donnees = json.loads(texte)
    except json.JSONDecodeError:
        return texte
    return json.dumps(_desaccentuer_cles(donnees), ensure_ascii=False)


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
