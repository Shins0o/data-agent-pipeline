"""Chargement du dataset Steam et construction des colonnes derivees.

Source unique de verite pour lire games.csv. Le fichier a un en-tete
defectueux que tout chargement naif decale silencieusement : voir load_games.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from tools import PROJECT_ROOT

RAW_PATH = PROJECT_ROOT / "data" / "raw" / "games.csv"

# Les 40 noms reels, dans l'ordre des champs du fichier.
COLS = [
    "AppID", "Name", "Release date", "Estimated owners", "Peak CCU",
    "Required age", "Price", "Discount", "DLC count", "About the game",
    "Supported languages", "Full audio languages", "Reviews", "Header image",
    "Website", "Support url", "Support email", "Windows", "Mac", "Linux",
    "Metacritic score", "Metacritic url", "User score", "Positive", "Negative",
    "Score rank", "Achievements", "Recommendations", "Notes",
    "Average playtime forever", "Average playtime two weeks",
    "Median playtime forever", "Median playtime two weeks", "Developers",
    "Publishers", "Categories", "Genres", "Tags", "Screenshots", "Movies",
]

# Signature de l'en-tete defectueux : les noms 8 et 9 y sont colles.
MARQUEUR_ENTETE_DEFECTUEUX = "DiscountDLC count"

DERIVED_COLUMNS = [
    "owners_mid", "release_dt", "release_year", "review_total", "review_ratio",
]


def load_games(path: Path = RAW_PATH) -> pd.DataFrame:
    """Charge les 40 colonnes brutes de games.csv.

    L'en-tete du fichier ne declare que 39 noms pour 40 champs. Un
    pd.read_csv(path) naif absorbe alors AppID comme index et decale les huit
    premieres colonnes : le champ etiquete Price contient en realite Discount.
    On ignore donc l'en-tete et on impose COLS.

    Si le fichier source est un jour republie corrige, l'en-tete ne portera
    plus le marqueur et la fonction leve plutot que de forcer des noms
    devenus faux.
    """
    with path.open(encoding="utf-8") as fichier:
        entete = fichier.readline()

    if MARQUEUR_ENTETE_DEFECTUEUX not in entete:
        raise ValueError(
            f"En-tete inattendu dans {path}. Le correctif applique ici suppose "
            f"l'en-tete defectueux contenant '{MARQUEUR_ENTETE_DEFECTUEUX}'. "
            "Verifier le fichier source avant de forcer les noms de colonnes."
        )

    return pd.read_csv(path, skiprows=1, names=COLS)


def _owners_midpoint(plage: str) -> float:
    """Convertit la plage '20000 - 50000' en son point median (35000.0)."""
    if pd.isna(plage):
        return np.nan
    bas, haut = plage.replace(",", "").split(" - ")
    return (int(bas) + int(haut)) / 2


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les colonnes construites, listees dans DERIVED_COLUMNS.

    owners_mid   : point median de 'Estimated owners'. Proxy grossier de
                   volume de ventes, pas une mesure : la donnee source est
                   une estimation par tranche.
    release_dt   : 'Release date' parsee. release_year : son annee.
    review_total : Positive + Negative, proxy de visibilite.
    review_ratio : Positive / review_total, proxy de qualite percue.
                   NaN quand le jeu n'a aucun avis, jamais 0.
    """
    df = df.copy()
    df["owners_mid"] = df["Estimated owners"].apply(_owners_midpoint)
    df["release_dt"] = pd.to_datetime(
        df["Release date"], errors="coerce", format="mixed"
    )
    df["release_year"] = df["release_dt"].dt.year
    df["review_total"] = df["Positive"] + df["Negative"]
    df["review_ratio"] = df["Positive"] / df["review_total"].replace(0, np.nan)
    return df


def explode_genres(df: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par couple (jeu, genre), dans une colonne 'genre'.

    'Genres' contient plusieurs valeurs separees par des virgules. Toute
    statistique par genre passe par cette explosion.

    Attention : un jeu multi-genres apparait sur plusieurs lignes. Une
    mediane par genre est licite, une somme compte le jeu dans chacun de ses
    genres. C'est un choix assume, a mentionner dans tout resultat agregé.
    """
    exploded = df.assign(genre=df["Genres"].str.split(",")).explode("genre")
    exploded["genre"] = exploded["genre"].str.strip()
    return exploded
