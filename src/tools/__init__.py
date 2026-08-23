"""Code deterministe du pipeline : chargement, preparation, execution."""

from pathlib import Path

# __init__.py -> parents[0]=tools, [1]=src, [2]=racine du repo
PROJECT_ROOT = Path(__file__).resolve().parents[2]

__all__ = ["PROJECT_ROOT"]
