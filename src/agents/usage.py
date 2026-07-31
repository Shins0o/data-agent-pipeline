"""Comptabilite des tokens et des couts, partagee par tous les agents."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Tarifs publics en USD par million de tokens.
# A reverifier sur claude.com/pricing, ils bougent.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}
CACHE_WRITE_RATIO = 1.25  # ecriture de cache : 1.25x le prix d'entree
CACHE_READ_RATIO = 0.10   # lecture de cache : 10% du prix d'entree


@dataclass
class Usage:
    agent: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )

    @property
    def cost_usd(self) -> float:
        if self.model not in PRICING:
            return 0.0
        prix_in, prix_out = PRICING[self.model]
        return (
            self.input_tokens * prix_in
            + self.cache_creation_tokens * prix_in * CACHE_WRITE_RATIO
            + self.cache_read_tokens * prix_in * CACHE_READ_RATIO
            + self.output_tokens * prix_out
        ) / 1_000_000


class UsageTracker:
    """Accumule la consommation de tous les agents d'une execution."""

    def __init__(self) -> None:
        self.entries: list[Usage] = []

    def add(self, usage: Usage) -> Usage:
        self.entries.append(usage)
        return usage

    def from_client_sdk(self, agent: str, model: str, response: Any) -> Usage:
        """Lit response.usage d'une reponse du SDK `anthropic`."""
        u = response.usage
        return self.add(
            Usage(
                agent=agent,
                model=model,
                input_tokens=getattr(u, "input_tokens", 0) or 0,
                output_tokens=getattr(u, "output_tokens", 0) or 0,
                cache_creation_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
                cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            )
        )

    def from_agent_sdk(self, agent: str, result: Any) -> list[Usage]:
        """Lit un ResultMessage du SDK `claude-agent-sdk`.

        On privilegie model_usage, qui couvre l'arbre complet (agent principal
        ET sous-agents). Le champ usage n'inclut que la boucle de premier niveau.
        """
        model_usage = getattr(result, "model_usage", None) or {}
        if model_usage:
            return [
                self.add(
                    Usage(
                        agent=agent,
                        model=mu.get("canonicalModel", nom),
                        input_tokens=mu.get("inputTokens", 0),
                        output_tokens=mu.get("outputTokens", 0),
                        cache_creation_tokens=mu.get("cacheCreationInputTokens", 0),
                        cache_read_tokens=mu.get("cacheReadInputTokens", 0),
                    )
                )
                for nom, mu in model_usage.items()
            ]

        u = getattr(result, "usage", None) or {}
        return [
            self.add(
                Usage(
                    agent=agent,
                    model=getattr(result, "model", "inconnu"),
                    input_tokens=u.get("input_tokens", 0),
                    output_tokens=u.get("output_tokens", 0),
                    cache_creation_tokens=u.get("cache_creation_input_tokens", 0),
                    cache_read_tokens=u.get("cache_read_input_tokens", 0),
                )
            )
        ]

    def summary(self) -> dict:
        return {
            "par_agent": [
                asdict(e) | {"total_tokens": e.total_tokens, "cout_usd": round(e.cost_usd, 6)}
                for e in self.entries
            ],
            "totaux": {
                "input_tokens": sum(e.input_tokens for e in self.entries),
                "output_tokens": sum(e.output_tokens for e in self.entries),
                "cache_creation_tokens": sum(e.cache_creation_tokens for e in self.entries),
                "cache_read_tokens": sum(e.cache_read_tokens for e in self.entries),
                "total_tokens": sum(e.total_tokens for e in self.entries),
                "cout_usd": round(sum(e.cost_usd for e in self.entries), 4),
            },
        }

    def print_table(self) -> None:
        print(f"\n{'Agent':<20} {'Modele':<28} {'In':>9} {'Out':>8} {'Cache':>9} {'USD':>9}")
        print("-" * 88)
        for e in self.entries:
            cache = e.cache_creation_tokens + e.cache_read_tokens
            print(
                f"{e.agent:<20} {e.model:<28} {e.input_tokens:>9,} "
                f"{e.output_tokens:>8,} {cache:>9,} {e.cost_usd:>9.4f}"
            )
        t = self.summary()["totaux"]
        print("-" * 88)
        print(
            f"{'TOTAL':<20} {'':<28} {t['input_tokens']:>9,} "
            f"{t['output_tokens']:>8,} "
            f"{t['cache_creation_tokens'] + t['cache_read_tokens']:>9,} "
            f"{t['cout_usd']:>9.4f}"
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.summary(), indent=2, ensure_ascii=False), encoding="utf-8"
        )