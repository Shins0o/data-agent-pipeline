"""Journalisation d'une execution du pipeline.

Une execution donne un dossier horodate dans runs/, contenant la trace
JSONL des evenements et un meta.json de synthese. Le critere qui a dicte
ce format : une execution doit pouvoir etre comprise et rejouee depuis son
seul dossier, sans le terminal qui l'a lancee.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from tools import PROJECT_ROOT

RUNS_DIR = PROJECT_ROOT / "runs"


class RunLogger:
    """Accumule les evenements d'une execution dans un dossier dedie."""

    def __init__(self, racine: Path = RUNS_DIR) -> None:
        self.debut = datetime.now()
        self.dossier = racine / self.debut.strftime("%Y%m%d-%H%M%S")
        self.dossier.mkdir(parents=True, exist_ok=True)
        self.trace = self.dossier / "trace.jsonl"

    def log(self, etape: str, **donnees: Any) -> None:
        """Ajoute un evenement a la trace, avec ecriture immediate.

        Pas de tampon en memoire : une execution qui plante doit laisser
        derriere elle tout ce qui a precede le plantage, c'est exactement
        la trace qu'on veut lire.

        default=str couvre les objets non serialisables (Timestamp, ndarray)
        plutot que de faire echouer la journalisation d'une execution
        par ailleurs valide.
        """
        evenement = {
            "horodatage": datetime.now().isoformat(timespec="seconds"),
            "etape": etape,
            **donnees,
        }
        with self.trace.open("a", encoding="utf-8") as fichier:
            fichier.write(json.dumps(evenement, ensure_ascii=False, default=str) + "\n")

    def ecrire_meta(self, **donnees: Any) -> None:
        """Ecrit la synthese de l'execution : duree, modele, consommation."""
        meta = {
            "debut": self.debut.isoformat(timespec="seconds"),
            "duree_s": round((datetime.now() - self.debut).total_seconds(), 1),
            **donnees,
        }
        (self.dossier / "meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
