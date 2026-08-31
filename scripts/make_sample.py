"""Regenere l'echantillon versionne dans data/samples/.

Cet echantillon n'est pas utilise par le pipeline : les agents travaillent
sur le dataset complet. Il sert uniquement a rendre les donnees consultables
depuis le depot, games.csv etant trop volumineux pour etre versionne.

Lancement : python scripts/make_sample.py
"""

from __future__ import annotations

from tools import PROJECT_ROOT
from tools.dataset import add_derived_columns, load_games

SORTIE = PROJECT_ROOT / "data" / "samples" / "steam_sample_500.csv"
TAILLE = 500
GRAINE = 42


def main() -> None:
    echantillon = add_derived_columns(load_games()).sample(TAILLE, random_state=GRAINE)
    echantillon.to_csv(SORTIE, index=False)
    print(
        f"Echantillon ecrit : {echantillon.shape[0]} lignes x "
        f"{echantillon.shape[1]} colonnes -> {SORTIE}"
    )


if __name__ == "__main__":
    main()
