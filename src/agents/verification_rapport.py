"""Controles deterministes d'un rapport final contre la campagne qui le fonde.

Deux questions, deux fonctions :
- chaque chiffre du rapport se retrouve-t-il dans une source ?
  -> chiffres_non_sources
- chaque constat s'appuie-t-il sur une sous-question qui a abouti ?
  -> constats_sans_donnee

Aucune n'arrete le pipeline. Ce sont des indicateurs, traces et affiches en
tete du rapport : un rapport ou un chiffre douteux est marque vaut mieux
qu'aucun rapport, a condition que le doute soit visible.

Ce qui compte comme source, et ce qui n'en est pas une :
- les valeurs rendues par l'analyste, calculees sur les donnees reelles ;
- le texte des sous-questions, parce qu'il porte les seuils ("500 jeux",
  "90e percentile") qui sont des definitions et non des mesures ;
- les numeros des sous-questions, parce qu'un rapport cite sa structure.
Ne sont PAS des sources : `lecture_question`, `hors_portee` et les `limites`
de l'analyste. C'est de la prose de modele. Les accepter blanchirait
exactement les chiffres qu'on cherche a attraper, comme le 96,6 % ecrit par
le planificateur sans l'avoir calcule.

Les trous du controle, connus d'avance :
- un petit entier trouve presque toujours une source : "2" passera meme
  invente. Faux negatif possible, et c'est la vraie limite.
- un multiplicateur en toutes lettres, "6,7 milliards", est lu 6,7 et
  signale a tort. Faux positif : un humain relit, c'est acceptable.
- un nombre repris des `limites` de l'analyste est signale, meme s'il vient
  du schema injecte. Meme nature, meme traitement.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from schemas.contracts import RapportFinal, ResultatCampagne

# Espace, espace insecable, espace fine insecable : les trois separateurs de
# milliers qu'un texte francais peut contenir.
_SEPARATEURS_MILLIERS = "   "

# Autour d'un nombre signale, de quoi le retrouver dans le texte.
_CONTEXTE = 40


@dataclass(frozen=True)
class NombreEcrit:
    """Un nombre tel qu'il est ecrit, avec la precision que son auteur lui a donnee.

    `decimales` est ce qui permet de juger un arrondi : "17,6" affirme une
    valeur a 0,05 pres, "18" a 0,5 pres. Negatif en notation scientifique,
    ou 6.6772e+09 ne dit rien en dessous du millier.
    """

    texte: str
    valeur: float
    decimales: int
    debut: int
    fin: int


@dataclass(frozen=True)
class ChiffreNonSource:
    """Un nombre du rapport sans source, et de quoi le retrouver.

    `debut` et `fin` situent le nombre dans le texte de son champ : le rendu
    marque le nombre signale, et pas une autre occurrence des memes chiffres.
    """

    champ: str
    nombre: str
    extrait: str
    debut: int
    fin: int


def _motif(milliers_espaces: bool) -> re.Pattern[str]:
    entier = (
        rf"\d{{1,3}}(?:[{_SEPARATEURS_MILLIERS}]\d{{3}})+|\d+"
        if milliers_espaces
        else r"\d+"
    )
    return re.compile(
        r"(?<![\w.,])"  # pas au milieu d'un mot ni d'un nombre : ni C1, ni p90
        r"(-?)"
        rf"({entier})"
        r"(?:[.,](\d+))?"  # virgule decimale francaise, ou point de pandas
        r"(?:[eE]([+-]?\d+))?"
        r"(?!\d)"
    )


_MOTIF_FRANCAIS = _motif(milliers_espaces=True)
_MOTIF_PANDAS = _motif(milliers_espaces=False)


def lire_nombres(texte: str, milliers_espaces: bool = True) -> list[NombreEcrit]:
    """Les nombres d'un texte, au format francais ou au format de pandas.

    Deux modes parce que les deux sources se contredisent sur un point. Un
    texte francais separe les milliers par une espace : "14 598". Un rendu
    pandas n'a jamais de separateur de milliers, mais aligne ses colonnes
    avec des espaces : lu en mode francais, "2596 457" deviendrait un seul
    nombre.
    """
    motif = _MOTIF_FRANCAIS if milliers_espaces else _MOTIF_PANDAS
    nombres = []
    for correspondance in motif.finditer(texte):
        signe, entier, decimales, exposant = correspondance.groups()
        entier = re.sub(f"[{_SEPARATEURS_MILLIERS}]", "", entier)
        chiffres_apres_virgule = len(decimales) if decimales else 0
        puissance = int(exposant) if exposant else 0
        valeur = float(f"{signe}{entier}.{decimales or 0}e{puissance}")
        nombres.append(
            NombreEcrit(
                texte=correspondance.group(0),
                valeur=valeur,
                decimales=chiffres_apres_virgule - puissance,
                debut=correspondance.start(),
                fin=correspondance.end(),
            )
        )
    return nombres


def _est_un_arrondi_de(valeur_ecrite: float, candidat: float, decimales: int) -> bool:
    """La valeur ecrite est-elle un arrondi legitime du candidat a cette precision ?

    Un demi-pas de tolerance plutot que round() : round() arrondit les
    demis au pair, 2,5 donne 2, et "3" serait signale a tort pour 2,5.
    """
    demi_pas = 0.5 * 10 ** (-decimales)
    return abs(candidat - valeur_ecrite) <= demi_pas * (1 + 1e-9)


def _zeros_de_fin(nombre: NombreEcrit) -> int:
    if nombre.decimales != 0 or nombre.valeur == 0:
        return 0
    chiffres = str(int(abs(nombre.valeur)))
    return len(chiffres) - len(chiffres.rstrip("0"))


def correspond(nombre: NombreEcrit, source: float) -> bool:
    """Le nombre ecrit peut-il venir de cette source ?

    Trois echelles, parce qu'une part s'ecrit en fraction ou en pourcentage
    selon qui l'ecrit : l'analyste rend 0.17604, le rapport dit 17,6 %.

    Un entier rond est lu comme un arrondi a la centaine ou au millier
    seulement s'il garde au moins deux chiffres significatifs : "14 600" pour
    14 598 passe, "20 000" pour 14 598 ne passe pas. Sans ce plancher, un
    nombre rond a un chiffre significatif trouverait une source dans une
    fourchette si large qu'il ne prouverait plus rien.
    """
    if math.isnan(source) or math.isinf(source):
        return False

    zeros = _zeros_de_fin(nombre)
    significatifs = len(str(int(abs(nombre.valeur)))) - zeros if zeros else 0

    for candidat in (source, source * 100, source / 100):
        if _est_un_arrondi_de(nombre.valeur, candidat, nombre.decimales):
            return True
        if zeros and significatifs >= 2 and _est_un_arrondi_de(
            nombre.valeur, candidat, -zeros
        ):
            return True
    return False


def sources_de_campagne(campagne: ResultatCampagne) -> list[float]:
    """Tout ce qu'un chiffre du rapport a le droit de reprendre."""
    sources = [float(numero) for numero in range(1, len(campagne.issues) + 1)]

    for issue in campagne.issues:
        sources += [n.valeur for n in lire_nombres(issue.sous_question.question)]
        if issue.statut == "succes":
            sources += [
                n.valeur
                for n in lire_nombres(issue.resultat.valeur, milliers_espaces=False)
            ]
    return sources


def champs_du_rapport(rapport: RapportFinal) -> list[tuple[str, str]]:
    """Chaque texte du rapport, avec de quoi le retrouver quand il est signale."""
    champs = [("reponse courte", rapport.reponse_courte)]
    champs += [(f"constat {c.id}", c.enonce) for c in rapport.constats]
    champs += [(f"interpretation {i.id}", i.enonce) for i in rapport.interpretations]
    champs += [
        (f"recommandation {n}", r.enonce)
        for n, r in enumerate(rapport.recommandations, start=1)
    ]
    champs += [(f"limite {n}", texte) for n, texte in enumerate(rapport.limites, start=1)]
    champs += [
        (f"non etabli {n}", texte) for n, texte in enumerate(rapport.non_etabli, start=1)
    ]
    return champs


def _extrait(texte: str, nombre: NombreEcrit) -> str:
    debut = max(0, nombre.debut - _CONTEXTE)
    fin = min(len(texte), nombre.fin + _CONTEXTE)
    return f"{'...' if debut else ''}{texte[debut:fin]}{'...' if fin < len(texte) else ''}"


def chiffres_non_sources(
    rapport: RapportFinal, campagne: ResultatCampagne
) -> list[ChiffreNonSource]:
    """Les nombres du rapport qu'aucune source de la campagne ne justifie."""
    sources = sources_de_campagne(campagne)
    return [
        ChiffreNonSource(
            champ=champ,
            nombre=nombre.texte,
            extrait=_extrait(texte, nombre),
            debut=nombre.debut,
            fin=nombre.fin,
        )
        for champ, texte in champs_du_rapport(rapport)
        for nombre in lire_nombres(texte)
        if not any(correspond(nombre, source) for source in sources)
    ]


def constats_sans_donnee(
    rapport: RapportFinal, campagne: ResultatCampagne
) -> dict[str, list[int]]:
    """Par constat, les sous-questions citees qui n'ont produit aucune valeur.

    Une sous-question en echec ou hors contrat n'a rien calcule. Un constat
    qui s'appuie dessus, ou sur un numero qui n'existe pas, est une
    affirmation sans donnee derriere : le cas le plus grave qu'un rapport
    puisse contenir.
    """
    abouties = {issue.numero for issue in campagne.issues if issue.statut == "succes"}
    return {
        constat.id: [n for n in constat.sous_questions if n not in abouties]
        for constat in rapport.constats
        if any(n not in abouties for n in constat.sous_questions)
    }
