"""Le document publie dit-il ce que la campagne a mesure ?

Aucun appel modele : le rapport est fabrique a la main, seul le rendu est
teste. C'est la seule partie de la chaine d'evaluation qui finit sous les
yeux d'un lecteur du depot.
"""

from __future__ import annotations

import pytest

from evaluation.harness import RapportEvaluation, VerdictQuestion
from evaluation.publication import charger, derniere_campagne, rendre_markdown


def verdict(**surcharges) -> VerdictQuestion:
    champs = {
        "id": "q_test",
        "question": "combien de jeux sont gratuits",
        "verdict": "correct",
        "note": "arbitrage de test",
        "tolerance": 0.005,
        "libelles_attendus": [],
        "libelles_manquants": [],
        "valeurs_attendues": [21.18],
        "valeurs_manquantes": [],
        "valeur_rendue": "21.18390210957054",
        "code_execute": "resultat = (df['Price'] == 0).mean() * 100",
        "limites": "Price a zero est une borne superieure du free to play",
        "tentatives": 1,
        "duree_s": 4.8,
        "tokens": 16453,
        "cout_usd": 0.0153,
    }
    return VerdictQuestion(**(champs | surcharges))


def rapport(*verdicts: VerdictQuestion) -> RapportEvaluation:
    verdicts = verdicts or (verdict(),)
    n_correct = sum(1 for v in verdicts if v.verdict == "correct")
    return RapportEvaluation(
        debut="2026-09-14T16:02:40",
        modele="claude-sonnet-5",
        voie="claude-agent-sdk (abonnement)",
        n_lignes=125_855,
        n_questions=len(verdicts),
        n_correct=n_correct,
        taux_justesse=round(n_correct / len(verdicts), 3),
        appels_modele=sum(v.tentatives for v in verdicts),
        duree_s=51.7,
        verdicts=list(verdicts),
        usage={"totaux": {"total_tokens": 115_201, "cout_usd": 0.1782}},
    )


def test_le_document_porte_le_code_execute():
    """Sans le code, le document demande qu'on le croie sur parole."""
    document = rendre_markdown(rapport())

    assert "resultat = (df['Price'] == 0).mean() * 100" in document
    assert "```python" in document


def test_le_document_porte_les_limites_declarees():
    document = rendre_markdown(rapport())
    assert "borne superieure du free to play" in document


def test_la_synthese_compte_les_reprises_et_les_hors_contrat():
    document = rendre_markdown(
        rapport(
            verdict(),
            verdict(id="q_reprise", tentatives=2),
            verdict(id="q_casse", verdict="hors_contrat", tentatives=0),
        )
    )

    assert "| Questions ayant demande une reprise | 1 |" in document
    assert "| Sorties hors contrat | 1 |" in document
    assert "2 / 3" in document


def test_une_question_manquee_affiche_ce_qui_est_introuvable():
    document = rendre_markdown(
        rapport(verdict(verdict="incorrect", valeurs_manquantes=[21.18]))
    )
    assert "**Introuvable dans la reponse**" in document


def test_derniere_campagne_prend_le_dossier_le_plus_recent(tmp_path):
    for horodatage in ["20260901-120000", "20260914-160240", "20260903-090000"]:
        dossier = tmp_path / horodatage
        dossier.mkdir()
        (dossier / "evaluation.json").write_text("{}", encoding="utf-8")

    assert derniere_campagne(tmp_path).parent.name == "20260914-160240"


def test_derniere_campagne_sans_campagne_dit_quoi_lancer(tmp_path):
    with pytest.raises(FileNotFoundError, match="evaluation.harness"):
        derniere_campagne(tmp_path)


def test_un_rapport_incomplet_est_rejete(tmp_path):
    """Un rapport d'une version anterieure du harnais ne doit pas passer."""
    chemin = tmp_path / "evaluation.json"
    chemin.write_text('{"modele": "claude-sonnet-5"}', encoding="utf-8")

    with pytest.raises(Exception):
        charger(chemin)
