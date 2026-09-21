"""Contrats de donnees entre les etapes du pipeline.

Toute sortie d'agent qui alimente une etape suivante passe par un modele
pydantic. Un echec de validation est une erreur explicite : le pipeline
s'arrete, il ne comble jamais un champ manquant par une valeur par defaut.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


# Bornes du plan de campagne. La consommation est lineaire en sous-questions,
# de l'ordre de 16 000 tokens chacune : un planificateur non borne est la
# facon la plus simple d'epuiser un abonnement. La borne vit dans le contrat,
# donc un plan qui deborde est une erreur de validation, pas une facture.
MIN_SOUS_QUESTIONS = 3
MAX_SOUS_QUESTIONS = 6


class SousQuestion(BaseModel):
    """Un maillon du plan : une question que l'analyste traite en une passe.

    Proche de QuestionAnalytique, sans en heriter. Les deux ont un producteur
    different, l'agent 1 pour l'une, le planificateur pour l'autre. Les lier
    ferait qu'une evolution du prompt de l'agent 1 deplacerait en silence le
    contrat du planificateur.

    `colonnes_necessaires` est indicatif. L'analyste ne le recoit pas, il
    travaille sur le schema reel du dataset. Une colonne inventee ici est donc
    un defaut de qualite du plan, pas une cause d'erreur de calcul.
    """

    model_config = ConfigDict(extra="forbid")

    question: str
    colonnes_necessaires: list[str] = Field(min_length=1)
    pourquoi: str


class PlanCampagne(BaseModel):
    """Sortie du planificateur : une question metier decoupee en sous-questions.

    `hors_portee` n'est pas un champ de politesse, c'est le pendant de
    `limites` chez l'analyste. Une question metier deborde presque toujours ce
    qu'un dataset permet d'etablir, et le planificateur doit le dire au lieu
    de laisser croire que son decoupage couvre toute la question.

    `variables_cles` existe parce que `lecture_question` est de la prose, et
    que la prose n'engage a rien : un plan peut annoncer deux facons de
    mesurer ce qu'on cherche et n'en decouper qu'une, sans que rien ne le
    signale. En listant les colonnes retenues comme variable de sortie, le
    plan rend sa propre annonce verifiable par du code.
    """

    model_config = ConfigDict(extra="forbid")

    lecture_question: str
    variables_cles: list[str] = Field(min_length=1)
    sous_questions: list[SousQuestion] = Field(
        min_length=MIN_SOUS_QUESTIONS, max_length=MAX_SOUS_QUESTIONS
    )
    hors_portee: str


class IssueSousQuestion(BaseModel):
    """Ce qu'est devenue une sous-question du plan, une fois passee a l'analyste.

    Porte la sous-question avec son resultat, et non le resultat seul. Le
    synthetiseur a besoin du `pourquoi` pour relier un chiffre a la question
    metier, et sans lui un resultat n'est qu'un nombre sans raison d'exister.

    Trois issues, et chacune dit au synthetiseur quelque chose de different :
    - succes : `resultat` porte une valeur calculee sur les donnees reelles.
    - echec_execution : `resultat` porte les tentatives et leurs erreurs, mais
      aucune valeur. Ce point n'a pas pu etre etabli.
    - hors_contrat : pas de `resultat` du tout, l'analyste n'a produit aucun
      plan valide. `erreur` dit pourquoi.

    Pas de extra="forbid" : comme ResultatAnalyse, ce contrat est assemble par
    le code et n'est pas une frontiere de confiance.
    """

    numero: int
    sous_question: SousQuestion
    statut: Literal["succes", "echec_execution", "hors_contrat"]
    resultat: ResultatAnalyse | None
    erreur: str | None = None


class ResultatCampagne(BaseModel):
    """Sortie de l'orchestrateur et entree du synthetiseur. Assemblee par le code.

    Les deux indicateurs de qualite du plan voyagent avec la campagne : un
    rapport final ecrit sur un plan qui annoncait des variables qu'il n'a
    jamais decoupees doit pouvoir le dire.
    """

    question_metier: str
    plan: PlanCampagne
    issues: list[IssueSousQuestion]
    colonnes_inventees: dict[str, list[str]]
    variables_non_mobilisees: list[str]


class Constat(BaseModel):
    """Ce que la donnee montre. Premier des trois niveaux de confiance du rapport.

    `sous_questions` relie le constat aux analyses qui le fondent, donc a un
    code execute sur les donnees reelles. Un constat sans sous-question serait
    une affirmation du modele, et c'est exactement ce que le pipeline interdit.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^C\d+$")
    enonce: str
    sous_questions: list[int] = Field(min_length=1)


class Interpretation(BaseModel):
    """Ce que le pipeline deduit des constats. Deuxieme niveau de confiance."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^I\d+$")
    enonce: str
    constats: list[str] = Field(min_length=1)


class Recommandation(BaseModel):
    """Ce que le pipeline recommande. Troisieme niveau, le moins sur des trois."""

    model_config = ConfigDict(extra="forbid")

    enonce: str
    appuis: list[str] = Field(min_length=1)


class RapportFinal(BaseModel):
    """Sortie du synthetiseur : la reponse a la question metier, et sa preuve.

    Chaque recommandation remonte a des interpretations, chaque
    interpretation a des constats, chaque constat a des sous-questions, et
    chaque sous-question a un code execute, conserve dans campagne.json. Un
    lecteur peut suivre n'importe quelle phrase du rapport jusqu'a la ligne
    de pandas qui la fonde.

    L'integrite de cette chaine est une regle du contrat : une interpretation
    qui cite un constat inexistant rend le raisonnement invalide, le rapport
    est rejete. La reference aux sous-questions, elle, se verifie contre la
    campagne et vit dans agents/verification_rapport.py, parce que le contrat
    ne connait pas la campagne.

    Au moins une limite, parce que la regle du projet en fait une partie du
    livrable et non une annexe. Zero recommandation est accepte : exiger une
    recommandation quand la donnee n'en porte aucune, c'est demander au
    modele d'en inventer une.
    """

    model_config = ConfigDict(extra="forbid")

    reponse_courte: str
    constats: list[Constat] = Field(min_length=1)
    interpretations: list[Interpretation]
    recommandations: list[Recommandation]
    limites: list[str] = Field(min_length=1)
    non_etabli: list[str]

    @model_validator(mode="after")
    def chaine_de_preuve_intacte(self) -> RapportFinal:
        ids_constats = [constat.id for constat in self.constats]
        ids_interpretations = [interp.id for interp in self.interpretations]

        for nom, ids in (("constat", ids_constats), ("interpretation", ids_interpretations)):
            doublons = sorted({i for i in ids if ids.count(i) > 1})
            if doublons:
                raise ValueError(f"Identifiants de {nom} en double : {doublons}")

        constats_orphelins = [
            (interp.id, ref)
            for interp in self.interpretations
            for ref in interp.constats
            if ref not in ids_constats
        ]
        if constats_orphelins:
            raise ValueError(
                f"Interpretations citant un constat inexistant : {constats_orphelins}"
            )

        appuis_orphelins = [
            ref
            for recommandation in self.recommandations
            for ref in recommandation.appuis
            if ref not in ids_interpretations
        ]
        if appuis_orphelins:
            raise ValueError(
                f"Recommandations citant une interpretation inexistante : {appuis_orphelins}"
            )

        return self
