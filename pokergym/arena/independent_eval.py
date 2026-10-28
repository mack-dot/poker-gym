"""A deliberately naive hand evaluator used ONLY to cross-check the engine.

It shares no code with ``pokergym.evaluator``: it enumerates every 5-card
subset, classifies each by counting ranks and suits, and orders them by
``(configured category strength, tiebreak)``. Slow; fine for checks.
"""
from __future__ import annotations

from itertools import combinations
from typing import Sequence

from ..evaluator import (FLUSH, FULL_HOUSE, HIGH_CARD, PAIR, QUADS, STRAIGHT, STRAIGHT_FLUSH, TRIPS,
                         TWO_PAIR)


def classify5(cards: Sequence[int]) -> tuple[int, tuple[int, ...]]:
    ranks = sorted((c >> 2 for c in cards), reverse=True)
    suits = [c & 3 for c in cards]
    flush = len(set(suits)) == 1
    counts: dict[int, int] = {}
    for r in ranks:
        counts[r] = counts.get(r, 0) + 1
    groups = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)  # (rank, count)
    distinct = sorted(counts, reverse=True)
    straight_top = -1
    if len(distinct) == 5:
        if distinct[0] - distinct[4] == 4:
            straight_top = distinct[0]
        elif distinct == [12, 3, 2, 1, 0]:
            straight_top = 3  # wheel
    if flush and straight_top >= 0:
        return STRAIGHT_FLUSH, (straight_top,)
    if groups[0][1] == 4:
        return QUADS, (groups[0][0], groups[1][0])
    if groups[0][1] == 3 and groups[1][1] == 2:
        return FULL_HOUSE, (groups[0][0], groups[1][0])
    if flush:
        return FLUSH, tuple(ranks)
    if straight_top >= 0:
        return STRAIGHT, (straight_top,)
    if groups[0][1] == 3:
        return TRIPS, (groups[0][0],) + tuple(r for r in ranks if r != groups[0][0])
    if groups[0][1] == 2 and groups[1][1] == 2:
        return TWO_PAIR, (groups[0][0], groups[1][0], groups[2][0])
    if groups[0][1] == 2:
        return PAIR, (groups[0][0],) + tuple(r for r in ranks if r != groups[0][0])
    return HIGH_CARD, tuple(ranks)


def best_hand(cards: Sequence[int], strength: Sequence[int]) -> tuple[int, int, tuple[int, ...]]:
    """(strength, category, tiebreak) of the best 5-card subset under ``strength``."""
    best = None
    for combo in combinations(cards, 5):
        cat, tb = classify5(combo)
        key = (strength[cat], tb)
        if best is None or key > best[0]:
            best = (key, cat)
    (st, tb), cat = best
    return st, cat, tb


def winners(hands: dict[int, Sequence[int]], strength: Sequence[int]) -> set[int]:
    vals = {s: best_hand(c, strength) for s, c in hands.items()}
    top = max((v[0], v[2]) for v in vals.values())
    return {s for s, v in vals.items() if (v[0], v[2]) == top}
