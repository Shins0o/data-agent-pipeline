"""Rendu du rapport final en markdown, controles en tete, preuves en annexe.

Deterministe de bout en bout : aucun mot de ce module ne vient d'un modele,
il met en forme ce que le synthetiseur et les controles ont produit.

Trois partis pris :
- les controles passent avant le rapport. Un lecteur doit savoir ce qu'il
  peut croire avant de lire ce qu'on lui affirme ;
- un chiffre non source est marque la ou il apparait, pas seulement liste
  a part : une liste en tete se saute, une marque dans la phrase non ;
- chaque sous-question figure en annexe avec sa valeur et le code qui l'a
  produite. C'est ce qui rend la chaine de preuve suivable sans le depot.
"""

from __future__ import annotations

import re
from collections import defaultdict

from agents.synthese import SyntheseVerifiee
from agents.verification_rapport import ChiffreNonSource
from schemas.contracts import IssueSousQuestion, ResultatCampagne

MARQUE = "[non source]"


def _marquer(texte: str, signalements: list[ChiffreNonSource]) -> str:
    """Accole la marque a chaque nombre signale, a sa position exacte.

    De la fin vers le debut, pour que les positions restent justes a mesure
    que le texte s'allonge.
    """
    for signalement in sorted(signalements, key=lambda s: s.debut, reverse=True):
        # "96,6 %" reste d'un seul tenant : la marque va apres le signe.
        suite = re.match(r"[ \u00a0\u202f]?%", texte[signalement.fin:])
        fin = signalement.fin + (suite.end() if suite else 0)
        texte = f"{texte[:fin]} {MARQUE}{texte[fin:]}"
    return texte


def _section_controles(synthese: SyntheseVerifiee, campagne: ResultatCampagne) -> list[str]:
    abouties = sum(1 for issue in campagne.issues if issue.statut == "succes")
    lignes = [
        "## Controles automatiques",
        "",
        f"- Sous-questions abouties : {abouties} sur {len(campagne.issues)}",
    ]

    if synthese.chiffres_non_sources:
        lignes.append(
            f"- **Chiffres sans source dans la campagne : "
            f"{len(synthese.chiffres_non_sources)}**, marques {MARQUE} dans le texte"
        )
        lignes += [
            f"  - {s.champ} : {s.nombre}, dans « {s.extrait} »"
            for s in synthese.chiffres_non_sources
        ]
    else:
        lignes.append("- Chiffres sans source dans la campagne : aucun")

    if synthese.constats_sans_donnee:
        lignes.append("- **Constats appuyes sur une sous-question sans resultat :**")
        lignes += [
            f"  - {constat} : sous-question(s) {', '.join(map(str, numeros))}"
            for constat, numeros in synthese.constats_sans_donnee.items()
        ]
    else:
        lignes.append("- Constats appuyes sur une sous-question sans resultat : aucun")

    if campagne.colonnes_inventees:
        lignes.append(f"- Colonnes citees par le plan et absentes du dataset : {campagne.colonnes_inventees}")
    if campagne.variables_non_mobilisees:
        lignes.append(
            f"- Variables annoncees par le plan et jamais mobilisees : "
            f"{', '.join(campagne.variables_non_mobilisees)}"
        )
    return lignes


def _annexe(issue: IssueSousQuestion) -> list[str]:
    lignes = [f"### {issue.numero}. {issue.sous_question.question}", "", f"Statut : {issue.statut}"]
    if issue.statut == "succes":
        lignes += [
            "",
            "Valeur obtenue :",
            "",
            "```",
            # strip("\n") et non strip() : les espaces de tete alignent
            # les colonnes d'un DataFrame rendu.
            issue.resultat.valeur.strip("\n"),
            "```",
            "",
            "Code execute :",
            "",
            "```python",
            issue.resultat.code_execute.strip(),
            "```",
            "",
            f"Limites declarees par l'analyste : {issue.resultat.limites}",
        ]
    elif issue.statut == "echec_execution":
        derniere = (issue.resultat.tentatives[-1].erreur or "").strip().splitlines()
        lignes += [
            "",
            f"Aucune valeur apres {len(issue.resultat.tentatives)} tentatives. "
            f"Derniere erreur : `{' '.join(derniere[-1:])}`",
        ]
    else:
        lignes += ["", "Aucune valeur : la reponse de l'analyste etait hors contrat."]
    return lignes + [""]


def rendre_markdown(synthese: SyntheseVerifiee, campagne: ResultatCampagne) -> str:
    rapport = synthese.rapport
    par_champ: dict[str, list[ChiffreNonSource]] = defaultdict(list)
    for signalement in synthese.chiffres_non_sources:
        par_champ[signalement.champ].append(signalement)

    def texte(champ: str, contenu: str) -> str:
        return _marquer(contenu, par_champ[champ])

    lignes = [
        f"# {campagne.question_metier}",
        "",
        texte("reponse courte", rapport.reponse_courte),
        "",
        *_section_controles(synthese, campagne),
        "",
        "## Ce que la donnee montre",
        "",
    ]
    lignes += [
        f"- **{c.id}** {texte(f'constat {c.id}', c.enonce)} "
        f"*(sous-question{'s' if len(c.sous_questions) > 1 else ''} "
        f"{', '.join(map(str, c.sous_questions))})*"
        for c in rapport.constats
    ]

    lignes += ["", "## Ce que le pipeline en deduit", ""]
    lignes += [
        f"- **{i.id}** {texte(f'interpretation {i.id}', i.enonce)} *(appui : {', '.join(i.constats)})*"
        for i in rapport.interpretations
    ] or ["Aucune interpretation."]

    lignes += ["", "## Ce qu'il recommande", ""]
    lignes += [
        f"- {texte(f'recommandation {n}', r.enonce)} *(appui : {', '.join(r.appuis)})*"
        for n, r in enumerate(rapport.recommandations, start=1)
    ] or ["Aucune recommandation : les resultats n'en portent pas de defendable."]

    lignes += ["", "## Limites", ""]
    lignes += [
        f"- {texte(f'limite {n}', limite)}" for n, limite in enumerate(rapport.limites, start=1)
    ]

    if rapport.non_etabli:
        lignes += ["", "## Ce qui n'a pas pu etre etabli", ""]
        lignes += [
            f"- {texte(f'non etabli {n}', element)}"
            for n, element in enumerate(rapport.non_etabli, start=1)
        ]

    lignes += ["", "## Annexe : les sous-questions et le code qui les a tranchees", ""]
    for issue in campagne.issues:
        lignes += _annexe(issue)

    return "\n".join(lignes)
