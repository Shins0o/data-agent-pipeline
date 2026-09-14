"""Publie la derniere campagne d'evaluation dans docs/evaluation.md.

runs/ est ignore par git : une campagne produit ses mesures et elles restent
sur la machine qui l'a lancee. Ce module rend visible dans le depot ce que le
harnais mesure, sans quoi un lecteur du depot doit croire sur parole qu'une
evaluation existe.

Separe du harnais a dessein, pour deux raisons. Le rendu est deterministe :
il se rejoue autant de fois qu'on veut sans consommer un appel. Et publier
reste un acte volontaire, plutot qu'un effet de bord d'une campagne dont on
ne connait pas encore le resultat.

Le document porte le code execute de chaque question. C'est ce qui le rend
verifiable : la regle du projet est qu'aucun chiffre ne vient du modele, et
un lecteur doit pouvoir rejouer le calcul plutot que de faire confiance.

Lancement : python -m evaluation.publication
"""

from __future__ import annotations

from pathlib import Path

from evaluation.harness import RapportEvaluation, VerdictQuestion
from tools import PROJECT_ROOT
from utils.run_logger import RUNS_DIR

DOC_PATH = PROJECT_ROOT / "docs" / "evaluation.md"
NOM_RAPPORT = "evaluation.json"


def derniere_campagne(racine: Path = RUNS_DIR) -> Path:
    """Le rapport de campagne le plus recent.

    Les dossiers de runs/ sont horodates au format %Y%m%d-%H%M%S, donc l'ordre
    alphabetique est l'ordre chronologique. Pas de tri par date de fichier :
    une copie ou un checkout changerait le resultat.
    """
    rapports = sorted(racine.glob(f"*/{NOM_RAPPORT}"))
    if not rapports:
        raise FileNotFoundError(
            f"Aucun {NOM_RAPPORT} dans {racine}. "
            "Lancer une campagne avec : python -m evaluation.harness"
        )
    return rapports[-1]


def charger(chemin: Path) -> RapportEvaluation:
    """Frontiere de lecture de fichier : le rapport repasse par son contrat.

    Un rapport ecrit par une version anterieure du harnais, a qui il manque
    un champ, doit echouer ici plutot que produire un document incomplet.
    """
    return RapportEvaluation.model_validate_json(
        chemin.read_text(encoding="utf-8")
    )


def _milliers(nombre: int) -> str:
    """Separateur de milliers en espace, convention francaise."""
    return f"{nombre:,}".replace(",", "\u00a0")


def _bloc(texte: str, langage: str = "") -> str:
    """strip() : le code genere se termine souvent par un saut de ligne, qui
    ouvrirait une ligne vide avant la cloture du bloc."""
    return f"```{langage}\n{texte.strip()}\n```"


def _attendu(verdict: VerdictQuestion) -> str:
    morceaux = []
    if verdict.libelles_attendus:
        morceaux.append(", ".join(verdict.libelles_attendus))
    if verdict.valeurs_attendues:
        morceaux.append(
            ", ".join(f"{valeur:g}" for valeur in verdict.valeurs_attendues)
        )
    return f"{' | '.join(morceaux)} (tolerance relative {verdict.tolerance:g})"


def rendre_synthese(rapport: RapportEvaluation) -> str:
    totaux = rapport.usage["totaux"]
    reprises = sum(1 for v in rapport.verdicts if v.tentatives > 1)
    hors_contrat = sum(1 for v in rapport.verdicts if v.verdict == "hors_contrat")

    lignes = [
        "| Mesure | Valeur |",
        "| --- | --- |",
        # Espace insecable avant le signe pourcent, convention francaise.
        f"| Questions correctes | {rapport.n_correct} / {rapport.n_questions} "
        f"({rapport.taux_justesse * 100:.0f} %) |",
        f"| Appels modele | {rapport.appels_modele} |",
        f"| Questions ayant demande une reprise | {reprises} |",
        f"| Sorties hors contrat | {hors_contrat} |",
        f"| Duree | {rapport.duree_s:.0f} s |",
        f"| Tokens | {_milliers(totaux['total_tokens'])} |",
        f"| Cout equivalent | {totaux['cout_usd']:.4f} USD |",
    ]
    return "\n".join(lignes)


def rendre_tableau(rapport: RapportEvaluation) -> str:
    lignes = [
        "| Question | Verdict | Tentatives | Duree | Tokens |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for verdict in rapport.verdicts:
        lignes.append(
            f"| `{verdict.id}` | {verdict.verdict} | {verdict.tentatives} | "
            f"{verdict.duree_s:.1f} s | {_milliers(verdict.tokens)} |"
        )
    return "\n".join(lignes)


def rendre_detail(verdict: VerdictQuestion) -> str:
    blocs = [
        f"### {verdict.id}",
        "",
        f"**Verdict** : {verdict.verdict}, en {verdict.tentatives} "
        f"{'tentative' if verdict.tentatives == 1 else 'tentatives'}.",
        "",
        f"**Question posee** : {verdict.question}",
        "",
        f"**Arbitrage encode dans la question** : {verdict.note}",
        "",
        f"**Attendu** : {_attendu(verdict)}",
    ]

    if verdict.valeur_rendue:
        blocs += ["", "**Obtenu**", "", _bloc(verdict.valeur_rendue)]
    if verdict.code_execute:
        blocs += ["", "**Code execute**", "", _bloc(verdict.code_execute, "python")]
    if verdict.limites:
        blocs += ["", f"**Limites declarees par l'analyste** : {verdict.limites}"]
    if verdict.libelles_manquants or verdict.valeurs_manquantes:
        blocs += [
            "",
            f"**Introuvable dans la reponse** : "
            f"{verdict.libelles_manquants + verdict.valeurs_manquantes}",
        ]
    return "\n".join(blocs)


def rendre_markdown(rapport: RapportEvaluation) -> str:
    """Le document publie. Une campagne, une page, regeneree a chaque fois."""
    entete = [
        "# Evaluation du pipeline",
        "",
        f"Campagne du {rapport.debut}, modele `{rapport.modele}` via "
        f"{rapport.voie}, sur {_milliers(rapport.n_lignes)} lignes.",
        "",
        "Les questions ci-dessous ont une reponse connue, calculee a la main "
        "dans `notebooks/01_exploration_steam.ipynb` et figee dans "
        "`src/evaluation/reference.py`. Le harnais les rejoue a travers "
        "l'analyste, qui produit du code pandas, et compare la valeur "
        "obtenue a la valeur attendue.",
        "",
        "Ce que cette page ne mesure pas : les questions sont bien "
        "specifiees et leur arbitrage leur est donne. C'est un filet de "
        "non-regression, pas une mesure de la capacite de l'analyste a "
        "trancher une question ambigue.",
        "",
        "Regenerer : `python -m evaluation.harness` puis "
        "`python -m evaluation.publication`.",
        "",
        "## Resultat",
        "",
        rendre_synthese(rapport),
        "",
        "## Par question",
        "",
        rendre_tableau(rapport),
        "",
        "## Detail",
        "",
        "",
    ]
    return "\n".join(entete) + "\n\n".join(
        rendre_detail(verdict) for verdict in rapport.verdicts
    ) + "\n"


def main() -> None:
    chemin = derniere_campagne()
    rapport = charger(chemin)

    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(rendre_markdown(rapport), encoding="utf-8")

    print(f"Campagne lue    : {chemin}")
    print(f"Document ecrit  : {DOC_PATH}")
    print(f"Resultat publie : {rapport.n_correct}/{rapport.n_questions} correctes")


if __name__ == "__main__":
    main()
