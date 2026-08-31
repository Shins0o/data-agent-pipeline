"""Contrats de donnees entre les etapes du pipeline.

Toute sortie d'agent qui alimente une etape suivante passe par un modele
pydantic. Un echec de validation est une erreur explicite : le pipeline
s'arrete, il ne comble jamais un champ manquant par une valeur par defaut.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProblemeQualite(BaseModel):
    colonne: str
    probleme: str
    gravite: Literal["faible", "moyenne", "elevee"]


class QuestionAnalytique(BaseModel):
    question: str
    colonnes_necessaires: list[str] = Field(min_length=1)


class LectureDataset(BaseModel):
    """Sortie de l'agent 1 : lecture analytique du profil technique.

    Le profil technique lui-meme est calcule par du code deterministe et n'a
    pas besoin de contrat. Ce modele ne valide que ce que le modele a produit.

    extra="forbid" : une cle inattendue signale que le modele s'est ecarte du
    schema demande. On veut le voir echouer, pas l'ignorer silencieusement.
    """

    model_config = ConfigDict(extra="forbid")

    resume: str
    colonnes_cles: list[str] = Field(min_length=1)
    problemes_qualite: list[ProblemeQualite]
    questions_analytiques: list[QuestionAnalytique] = Field(min_length=1)


class PlanAnalyse(BaseModel):
    """Sortie de l'agent 2 : ce qu'il compte calculer, et le code pour le faire.

    Le champ `code` n'est pas valide au-dela de sa presence : la seule
    validation qui ait un sens pour du code, c'est son execution.

    `limites` n'est pas un champ de politesse. C'est la ou l'analyste declare
    les arbitrages qu'il a pris faute de definition : quel filtre, quel
    traitement des manquants, quel double comptage.
    """

    model_config = ConfigDict(extra="forbid")

    intention: str
    colonnes_utilisees: list[str] = Field(min_length=1)
    code: str
    limites: str


class TentativeExecution(BaseModel):
    """Une passe de la boucle d'auto-correction, reussie ou non.

    `erreur` est None sur la tentative qui a abouti. Conserver les tentatives
    ratees avec leur code est ce qui rend le taux d'echec par etape mesurable
    plutot que devine.
    """

    numero: int
    code: str
    erreur: str | None = None


class ResultatAnalyse(BaseModel):
    """Reponse du pipeline a une question. Assemblee par le code, pas par le modele.

    Pas de extra="forbid" ici, contrairement aux sorties de modele : ce
    contrat n'est pas une frontiere de confiance, c'est la forme de ce que
    le pipeline produit.

    En statut "echec", `valeur` reste None : aucun chiffre ne sort d'une
    execution qui n'a pas abouti.
    """

    question: str
    statut: Literal["succes", "echec"]
    intention: str
    limites: str
    code_execute: str | None
    valeur: str | None
    tentatives: list[TentativeExecution] = Field(min_length=1)
