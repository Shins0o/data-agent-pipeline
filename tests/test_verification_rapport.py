"""Le rapport final tient-il sa chaine de preuve, et ses chiffres ont-ils une source ?

Tout est deterministe ici : aucun appel modele, aucun dataset charge. Les
campagnes et les rapports viennent de tests/fabriques.py.
"""

from __future__ import annotations

import pandas as pd
import pytest
from pydantic import ValidationError

from agents.profiling import build_profile
from agents.synthese import fiche_qualite
from agents.verification_rapport import (
    chiffres_non_sources,
    constats_sans_donnee,
    correspond,
    lire_nombres,
)
from fabriques import CAMPAGNE, SANS_FICHE, rapport


# --- contrat : la chaine de preuve --------------------------------------------


def test_un_rapport_conforme_est_accepte():
    assert rapport().constats[0].id == "C1"


def test_une_interpretation_citant_un_constat_inexistant_est_rejetee():
    with pytest.raises(ValidationError, match="constat inexistant"):
        rapport(interpretations=[{"id": "I1", "enonce": "x", "constats": ["C9"]}])


def test_une_recommandation_citant_une_interpretation_inexistante_est_rejetee():
    with pytest.raises(ValidationError, match="interpretation inexistante"):
        rapport(recommandations=[{"enonce": "x", "appuis": ["I4"]}])


def test_un_identifiant_en_double_est_rejete():
    with pytest.raises(ValidationError, match="en double"):
        rapport(
            constats=[
                {"id": "C1", "enonce": "a", "sous_questions": [2]},
                {"id": "C1", "enonce": "b", "sous_questions": [3]},
            ]
        )


def test_un_identifiant_mal_forme_est_rejete():
    with pytest.raises(ValidationError):
        rapport(constats=[{"id": "X1", "enonce": "a", "sous_questions": [2]}])


def test_un_rapport_sans_limite_est_rejete():
    """Les limites font partie du livrable, pas d'une annexe optionnelle."""
    with pytest.raises(ValidationError):
        rapport(limites=[])


def test_un_rapport_sans_recommandation_est_accepte():
    """Exiger une recommandation que la donnee ne porte pas, c'est en faire inventer une."""
    assert rapport(recommandations=[]).recommandations == []


# --- lecture des nombres -----------------------------------------------------


def valeurs(texte: str, **options) -> list[float]:
    return [n.valeur for n in lire_nombres(texte, **options)]


def test_les_formats_francais_sont_lus():
    assert valeurs("17,6 % des jeux") == [17.6]
    assert valeurs("14 598 jeux") == [14598]
    assert valeurs("14 598 jeux") == [14598]
    assert valeurs("6 677 200 000 proprietaires") == [6_677_200_000]
    assert valeurs("une correlation de -0,02") == [-0.02]


def test_une_plage_d_annees_n_est_pas_lue_comme_un_nombre_negatif():
    assert valeurs("entre 2017-2026") == [2017, 2026]


def test_les_identifiants_ne_sont_pas_des_nombres():
    assert valeurs("voir C1, I2 et le seuil p90") == []


def test_un_rendu_pandas_ne_colle_pas_ses_colonnes():
    """En mode francais, "2596 457" serait un seul nombre : 2 596 457."""
    assert valeurs("2596 457 0.17604", milliers_espaces=False) == [2596, 457, 0.17604]
    assert valeurs("6.677200e+09", milliers_espaces=False) == [6_677_200_000]


def test_la_precision_ecrite_est_conservee():
    assert [n.decimales for n in lire_nombres("17,6 et 18 et 0,176")] == [1, 0, 3]


# --- correspondance par arrondi ----------------------------------------------


def premier(texte: str):
    return lire_nombres(texte)[0]


@pytest.mark.parametrize("ecrit", ["17,6 %", "18 %", "0,18", "0,176"])
def test_un_arrondi_legitime_de_la_source_passe(ecrit):
    assert correspond(premier(ecrit), 0.17604)


def test_un_arrondi_faux_est_signale():
    assert not correspond(premier("17,7 %"), 0.17604)


def test_un_entier_rond_a_deux_chiffres_significatifs_est_un_arrondi():
    assert correspond(premier("14 600"), 14598)


def test_un_entier_rond_a_un_seul_chiffre_significatif_doit_etre_exact():
    """Sans ce plancher, "20 000" trouverait une source entre 15 000 et 25 000."""
    assert not correspond(premier("20 000"), 14598)
    assert correspond(premier("10 000"), 10000.0)


def test_un_demi_n_est_pas_arrondi_au_pair():
    """round(2.5) donne 2 en Python : "3" doit pourtant passer pour 2,5."""
    assert correspond(premier("3"), 2.5)


# --- controles contre la campagne ----------------------------------------------


def test_un_rapport_entierement_source_ne_signale_rien():
    assert chiffres_non_sources(rapport(), CAMPAGNE, SANS_FICHE) == []


def test_le_96_6_recopie_du_hors_portee_est_signale():
    """Le cas reel : un chiffre ecrit par le planificateur sans l'avoir calcule."""
    signales = chiffres_non_sources(
        rapport(limites=["Metacritic score vaut 0 pour 96,6 % des jeux."]), CAMPAGNE, SANS_FICHE
    )

    assert [(s.champ, s.nombre) for s in signales] == [("limite 1", "96,6")]
    assert "Metacritic" in signales[0].extrait


def test_un_seuil_ecrit_dans_une_sous_question_est_une_source():
    """500 jeux est une definition posee par le plan, pas une mesure."""
    assert chiffres_non_sources(
        rapport(limites=["Seuls les genres d'au moins 500 jeux sont retenus."]), CAMPAGNE, SANS_FICHE
    ) == []


def test_un_chiffre_invente_dans_un_constat_est_signale():
    signales = chiffres_non_sources(
        rapport(
            constats=[
                {"id": "C1", "enonce": "42,3 % des jeux MMO depassent le seuil.", "sous_questions": [2]},
                {"id": "C2", "enonce": "14 598 jeux sont sortis en 2023.", "sous_questions": [3]},
            ]
        ),
        CAMPAGNE,
        SANS_FICHE,
    )
    assert [(s.champ, s.nombre) for s in signales] == [("constat C1", "42,3")]


def test_un_constat_appuye_sur_une_sous_question_sans_resultat_est_signale():
    signales = constats_sans_donnee(
        rapport(
            constats=[
                {"id": "C1", "enonce": "Le sommet concentre tout.", "sous_questions": [1, 2]},
                {"id": "C2", "enonce": "14 598 jeux en 2023.", "sous_questions": [3]},
            ]
        ),
        CAMPAGNE,
    )
    assert signales == {"C1": [1]}


def test_un_constat_citant_une_sous_question_inexistante_est_signale():
    signales = constats_sans_donnee(
        rapport(constats=[{"id": "C1", "enonce": "x", "sous_questions": [9]}], interpretations=[], recommandations=[]),
        CAMPAGNE,
    )
    assert signales == {"C1": [9]}


# --- la fiche qualite comme source -----------------------------------------------


def fiche_metacritic() -> dict[str, dict]:
    """Taux reel de Metacritic url (0.966 dans le profil), sur 1 000 lignes."""
    df = pd.DataFrame({"Metacritic url": [None] * 966 + ["https://x"] * 34})
    return fiche_qualite(build_profile(df), ["Metacritic url"])


def test_un_taux_repris_de_la_fiche_qualite_est_source():
    assert chiffres_non_sources(
        rapport(limites=["Metacritic url manque pour 96,6 % des jeux."]),
        CAMPAGNE,
        fiche_metacritic(),
    ) == []


def test_un_taux_arrondi_de_la_fiche_qualite_est_source():
    assert chiffres_non_sources(
        rapport(limites=["Metacritic url manque pour 97 % des jeux."]),
        CAMPAGNE,
        fiche_metacritic(),
    ) == []


def test_une_borne_n_est_pas_un_arrondi_meme_avec_la_fiche():
    """La phrase reelle du 21 septembre. "Plus de 96" n'arrondit pas 96,6.

    Le controle ne lit pas les bornes : il signale, un humain relit. Et la
    phrase melange deux colonnes, "manquantes ou nulles", dont une seule a
    un compte dans la fiche.
    """
    signales = chiffres_non_sources(
        rapport(
            non_etabli=[
                "La qualite critique n'a pas pu etre analysee, ces colonnes etant "
                "quasiment inutilisables (valeurs manquantes ou nulles a plus de 96%)."
            ]
        ),
        CAMPAGNE,
        fiche_metacritic(),
    )
    assert [s.nombre for s in signales] == ["96"]
