"""Execution du code pandas produit par l'analyste.

Ce module n'est pas un bac a sable. `exec` donne au code genere l'acces
complet au process Python : imports, systeme de fichiers, reseau. C'est
acceptable ici parce que l'execution est locale, sur des donnees publiques,
et que le code est ecrit dans la trace avant de tourner. Ca ne l'est pas
dans un service expose.
"""

from __future__ import annotations

import io
import traceback
from contextlib import redirect_stdout
from dataclasses import dataclass

import numpy as np
import pandas as pd

from tools.dataset import explode_genres

# Le code genere communique son resultat par cette variable. C'est le
# contrat annonce dans le prompt de l'analyste, et la seule facon pour le
# pipeline de recuperer une valeur.
VARIABLE_RESULTAT = "resultat"

# Nombre de lignes rendues en texte pour un DataFrame ou une Series. Au-dela,
# la trace grossit sans rien apprendre de plus sur le resultat.
LIGNES_RENDUES = 20


@dataclass
class ResultatExecution:
    valeur: object | None
    sortie_standard: str
    erreur: str | None

    @property
    def a_reussi(self) -> bool:
        return self.erreur is None


def construire_namespace(df: pd.DataFrame) -> dict:
    """Les noms visibles par le code genere.

    explode_genres y figure volontairement : l'explosion des genres encode
    une decision metier (un jeu multi-genres est compte dans chacun). Sans
    elle, l'analyste la reecrit a sa facon a chaque question et les chiffres
    cessent d'etre comparables entre deux executions.
    """
    return {"df": df, "pd": pd, "np": np, "explode_genres": explode_genres}


def executer_code(code: str, df: pd.DataFrame) -> ResultatExecution:
    """Execute le code et renvoie soit sa valeur, soit de quoi le corriger.

    Deux echecs distincts remontent de la meme facon : le code leve, ou le
    code tourne mais n'assigne pas `resultat`. Dans les deux cas l'analyste
    a besoin du meme retour pour reessayer, et dans les deux cas le pipeline
    n'a pas de valeur a presenter.
    """
    namespace = construire_namespace(df)
    tampon = io.StringIO()

    try:
        with redirect_stdout(tampon):
            exec(code, namespace)
    except Exception:
        return ResultatExecution(None, tampon.getvalue(), traceback.format_exc())

    if VARIABLE_RESULTAT not in namespace:
        return ResultatExecution(
            None,
            tampon.getvalue(),
            f"Le code s'est execute sans erreur mais n'a defini aucune variable "
            f"'{VARIABLE_RESULTAT}'. Le pipeline n'a aucun resultat a lire.",
        )

    return ResultatExecution(namespace[VARIABLE_RESULTAT], tampon.getvalue(), None)


def rendre_valeur(valeur: object) -> str:
    """Rend la valeur en texte, pour la trace et pour l'etape suivante."""
    if isinstance(valeur, (pd.DataFrame, pd.Series)):
        return valeur.head(LIGNES_RENDUES).to_string()
    return str(valeur)
