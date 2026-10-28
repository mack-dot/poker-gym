"""Rule mutations. Human-readable specs live in docs/variants/*.md.

Exactly two mutations are implemented for P0:

A. ``FLUSH_BEATS_FULL_HOUSE`` - hand-ranking mutation: a flush outranks a
   full house (as in short-deck poker). Everything else is standard.
B. ``POT_LIMIT`` - betting-rule mutation: the maximum raise is bounded by the
   pot (pot-limit hold'em). Everything else is standard.
"""
from __future__ import annotations

from .evaluator import FLUSH, FULL_HOUSE, STANDARD_STRENGTH
from .rules import BASELINE_RULES, BettingRules, GameRules, HandRanking


def _swap(strength: tuple[int, ...], a: int, b: int) -> tuple[int, ...]:
    s = list(strength)
    s[a], s[b] = s[b], s[a]
    return tuple(s)


FLUSH_BEATS_FULL_HOUSE_RANKING = HandRanking(
    strength=_swap(STANDARD_STRENGTH, FLUSH, FULL_HOUSE), name="flush_beats_full_house"
)

VARIANT_A_FLUSH_BEATS_FULL_HOUSE: GameRules = BASELINE_RULES.with_(
    name="variant-a-flush-beats-full-house",
    description="NLHE with one hand-ranking mutation: flush > full house. Spec: docs/variants/A_flush_beats_full_house.md",
    ranking=FLUSH_BEATS_FULL_HOUSE_RANKING,
)

VARIANT_B_POT_LIMIT: GameRules = BASELINE_RULES.with_(
    name="variant-b-pot-limit",
    description="Hold'em with one betting mutation: pot-limit raises. Spec: docs/variants/B_pot_limit.md",
    betting=BettingRules(limit="pot_limit"),
)

VARIANTS: dict[str, GameRules] = {
    "baseline": BASELINE_RULES,
    "flush-beats-full-house": VARIANT_A_FLUSH_BEATS_FULL_HOUSE,
    "pot-limit": VARIANT_B_POT_LIMIT,
}
