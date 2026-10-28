"""Independent Chip Model (Malmuth-Harville).

``place_probabilities`` returns P[i][p]: probability that player i finishes in
place p (0-based, 0 = first). ``icm_equities`` folds that against a payout
vector. ``brute_force_equities`` enumerates every finishing permutation and is
used by the tests as an independent check of the recursion.
"""
from __future__ import annotations

from functools import lru_cache
from itertools import permutations
from typing import Sequence


def place_probabilities(stacks: Sequence[float]) -> list[list[float]]:
    n = len(stacks)
    stacks = [float(s) for s in stacks]
    total_players = n

    @lru_cache(maxsize=None)
    def dist(remaining: tuple[int, ...]) -> tuple[tuple[float, ...], ...]:
        """For the subset ``remaining`` (sorted seat ids), return a matrix
        M[i][q] = P(player i finishes q-th among `remaining`)."""
        m = len(remaining)
        out = [[0.0] * m for _ in range(total_players)]
        tot = sum(stacks[i] for i in remaining)
        if tot <= 0:
            # all-zero stacks: split uniformly (degenerate; never used in play)
            for i in remaining:
                for q in range(m):
                    out[i][q] = 1.0 / m
            return tuple(tuple(r) for r in out)
        for i in remaining:
            out[i][0] = stacks[i] / tot
        if m == 1:
            return tuple(tuple(r) for r in out)
        for j in remaining:
            pj = stacks[j] / tot
            if pj == 0.0:
                continue
            sub = tuple(x for x in remaining if x != j)
            subm = dist(sub)
            for i in sub:
                row = subm[i]
                oi = out[i]
                for q in range(m - 1):
                    oi[q + 1] += pj * row[q]
        return tuple(tuple(r) for r in out)

    full = dist(tuple(range(n)))
    return [list(full[i]) for i in range(n)]


def place_probabilities_for(stacks: Sequence[float], me: int) -> list[float]:
    """P(player ``me`` finishes in place p) for p = 0..n-1, by a subset DP.

    ``top[S]`` is the probability that the set ``S`` occupies the first
    ``|S|`` places in some order. Same model as ``place_probabilities`` but
    only for one player, so the cost is ``O(2^n * n)`` with small constants
    (about 20 µs for n = 5). Used by bots inside the decision deadline.
    """
    n = len(stacks)
    stacks = [float(s) for s in stacks]
    total = sum(stacks)
    if total <= 0:
        return [1.0 / n] * n
    size = 1 << n
    top = [0.0] * size
    ssum = [0.0] * size
    top[0] = 1.0
    for S in range(1, size):
        low = S & -S
        j = low.bit_length() - 1
        ssum[S] = ssum[S ^ low] + stacks[j]
    out = [0.0] * n
    mybit = 1 << me
    for S in range(size):
        pS = top[S]
        if pS == 0.0:
            continue
        rem = total - ssum[S]
        if rem <= 0:
            continue
        if not S & mybit:
            out[bin(S).count("1")] += pS * stacks[me] / rem
        for j in range(n):
            b = 1 << j
            if S & b or stacks[j] == 0.0:
                continue
            top[S | b] += pS * stacks[j] / rem
    return out


def icm_equity_for(stacks: Sequence[float], payouts: Sequence[float], me: int) -> float:
    n = len(stacks)
    pay = list(payouts) + [0.0] * max(0, n - len(payouts))
    probs = place_probabilities_for(stacks, me)
    return sum(probs[p] * pay[p] for p in range(n))


def icm_equities(stacks: Sequence[float], payouts: Sequence[float]) -> list[float]:
    """Expected payout per player. ``payouts[p]`` is the prize for place p
    (0-based). ``payouts`` may be shorter than ``stacks`` (unpaid places)."""
    n = len(stacks)
    pay = list(payouts) + [0.0] * max(0, n - len(payouts))
    probs = place_probabilities(stacks)
    return [sum(probs[i][p] * pay[p] for p in range(n)) for i in range(n)]


def brute_force_equities(stacks: Sequence[float], payouts: Sequence[float]) -> list[float]:
    """Enumerate all finishing orders (n! terms). Independent check for n <= 7."""
    n = len(stacks)
    pay = list(payouts) + [0.0] * max(0, n - len(payouts))
    eq = [0.0] * n
    for order in permutations(range(n)):
        p = 1.0
        remaining = sum(stacks)
        ok = True
        for i in order:
            if remaining <= 0:
                ok = False
                break
            p *= stacks[i] / remaining
            remaining -= stacks[i]
        if not ok:
            continue
        for place, i in enumerate(order):
            eq[i] += p * pay[place]
    return eq
