"""Fast pure-Python high-hand evaluator for 5 to 7 cards.

Returns an int; a higher value is a stronger hand. The value is
``(category_strength << 20) | tiebreak`` where ``tiebreak`` packs up to five
rank nibbles, most significant first.

Category strength is a configurable table so that hand-ranking variants
(for example "flush beats full house") can reuse the same detection code.
When categories overlap in a 7-card hand (for example a straight and trips),
the evaluator returns the best hand *under the configured ranking*, not under
the standard ranking.
"""
from __future__ import annotations

from typing import Sequence

# Canonical category ids (detection ids, never reordered).
HIGH_CARD = 0
PAIR = 1
TWO_PAIR = 2
TRIPS = 3
STRAIGHT = 4
FLUSH = 5
FULL_HOUSE = 6
QUADS = 7
STRAIGHT_FLUSH = 8

CATEGORY_NAMES = (
    "high_card",
    "pair",
    "two_pair",
    "trips",
    "straight",
    "flush",
    "full_house",
    "quads",
    "straight_flush",
)

# Standard poker: strength == canonical id.
STANDARD_STRENGTH: tuple[int, ...] = tuple(range(9))

_ALL13 = (1 << 13) - 1


def _build_tables():
    top5 = [0] * 8192  # packed top-5 ranks of a 13-bit mask, high nibble first
    straight = [-1] * 8192  # top rank of the best straight in the mask, else -1
    popcount = [0] * 8192
    for m in range(8192):
        bits = [r for r in range(12, -1, -1) if m >> r & 1]
        popcount[m] = len(bits)
        v = 0
        for i in range(5):
            v = (v << 4) | (bits[i] if i < len(bits) else 0)
        top5[m] = v
        # straights: A-high (top=12) down to the 5-high wheel (top=3)
        best = -1
        for top in range(12, 2, -1):
            need = 0
            for k in range(5):
                r = top - k
                if r < 0:
                    r = 12  # wheel ace
                need |= 1 << r
            if m & need == need:
                best = top
                break
        straight[m] = best
    return tuple(top5), tuple(straight), tuple(popcount)


TOP5, STRAIGHT_TOP, POPCOUNT = _build_tables()


def _top_bit(m: int) -> int:
    return m.bit_length() - 1


class Evaluator:
    """Evaluates 5..7 card hands under a configurable category ranking."""

    __slots__ = ("strength", "name")

    def __init__(self, strength: Sequence[int] = STANDARD_STRENGTH, name: str = "standard"):
        if sorted(strength) != list(range(9)):
            raise ValueError("strength must be a permutation of 0..8")
        self.strength = tuple(int(s) << 20 for s in strength)
        self.name = name

    def evaluate(self, cards: Sequence[int]) -> int:
        s0 = s1 = s2 = s3 = 0
        for c in cards:
            b = 1 << (c >> 2)
            su = c & 3
            if su == 0:
                s0 |= b
            elif su == 1:
                s1 |= b
            elif su == 2:
                s2 |= b
            else:
                s3 |= b
        st = self.strength
        all_ranks = s0 | s1 | s2 | s3
        dup = (s0 & s1) | (s0 & s2) | (s0 & s3) | (s1 & s2) | (s1 & s3) | (s2 & s3)

        # --- rank-multiplicity hand (exactly one of these applies) ---
        if dup:
            quads = s0 & s1 & s2 & s3
            if quads:
                q = _top_bit(quads)
                kick = _top_bit(all_ranks & ~quads)
                best = st[QUADS] | (q << 16) | (kick << 12)
            else:
                trips = (s0 & s1 & s2) | (s0 & s1 & s3) | (s0 & s2 & s3) | (s1 & s2 & s3)
                if trips:
                    t = _top_bit(trips)
                    rest_pairs = dup & ~(1 << t)
                    if rest_pairs:
                        best = st[FULL_HOUSE] | (t << 16) | (_top_bit(rest_pairs) << 12)
                    else:
                        kick = TOP5[all_ranks & ~(1 << t)] >> 12  # top 2 kickers
                        best = st[TRIPS] | (t << 16) | (kick << 4)
                else:
                    if POPCOUNT[dup] >= 2:
                        hi = _top_bit(dup)
                        lo = _top_bit(dup & ~(1 << hi))
                        kick = _top_bit(all_ranks & ~(1 << hi) & ~(1 << lo))
                        best = st[TWO_PAIR] | (hi << 16) | (lo << 12) | (kick << 8)
                    else:
                        p = _top_bit(dup)
                        kick = TOP5[all_ranks & ~dup] >> 8  # top 3 kickers
                        best = st[PAIR] | (p << 16) | kick
        else:
            best = st[HIGH_CARD] | TOP5[all_ranks]

        # --- straight / flush / straight flush candidates ---
        sm = 0
        if POPCOUNT[s0] >= 5:
            sm = s0
        elif POPCOUNT[s1] >= 5:
            sm = s1
        elif POPCOUNT[s2] >= 5:
            sm = s2
        elif POPCOUNT[s3] >= 5:
            sm = s3
        if sm:
            sf = STRAIGHT_TOP[sm]
            if sf >= 0:
                v = st[STRAIGHT_FLUSH] | (sf << 16)
                if v > best:
                    best = v
            v = st[FLUSH] | TOP5[sm]
            if v > best:
                best = v
        stop = STRAIGHT_TOP[all_ranks]
        if stop >= 0:
            v = st[STRAIGHT] | (stop << 16)
            if v > best:
                best = v
        return best

    def category(self, value: int) -> int:
        """Canonical category id of an evaluated value."""
        return self.strength.index((value >> 20) << 20)

    def describe(self, value: int) -> str:
        return CATEGORY_NAMES[self.category(value)]


STANDARD_EVALUATOR = Evaluator()


def evaluate(cards: Sequence[int]) -> int:
    return STANDARD_EVALUATOR.evaluate(cards)
