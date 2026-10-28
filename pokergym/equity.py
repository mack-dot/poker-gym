"""Hand classes, Monte Carlo equity, and the precomputed preflop table.

Nothing here is a tournament rule; it is plain poker mathematics used by the
sparring bots and by offline analysis. The preflop table is Monte Carlo
(see ``PREFLOP_META`` for samples, seed, and generator command), so its
values carry a standard error of roughly ``sqrt(p(1-p)/samples)``.

Hand class index (0..168): ``hi, lo = max(rank), min(rank)``;
pair -> ``hi*13 + hi``; suited -> ``hi*13 + lo``; offsuit -> ``lo*13 + hi``.
This is the usual 13x13 grid with suited hands above the diagonal.
"""
from __future__ import annotations

import json
import os
import random
from typing import Sequence

from .cards import RANKS, DECK_SIZE
from .evaluator import Evaluator, STANDARD_EVALUATOR

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "preflop_equity.json")

# Number of distinct two-card combos per class: 6 for a pair, 4 suited, 12 offsuit.
NUM_CLASSES = 169


def class_index(c1: int, c2: int) -> int:
    r1, r2 = c1 >> 2, c2 >> 2
    if r1 == r2:
        return r1 * 13 + r1
    hi, lo = (r1, r2) if r1 > r2 else (r2, r1)
    if (c1 & 3) == (c2 & 3):
        return hi * 13 + lo
    return lo * 13 + hi


def class_name(idx: int) -> str:
    a, b = divmod(idx, 13)
    if a == b:
        return RANKS[a] * 2
    if a > b:
        return RANKS[a] + RANKS[b] + "s"
    return RANKS[b] + RANKS[a] + "o"


def class_from_name(name: str) -> int:
    """'AKs' / 'AKo' / 'QQ' -> class index."""
    name = name.strip()
    r1, r2 = RANKS.index(name[0].upper()), RANKS.index(name[1].upper())
    if r1 == r2:
        return r1 * 13 + r1
    hi, lo = max(r1, r2), min(r1, r2)
    if len(name) < 3:
        raise ValueError(f"need s/o suffix for {name!r}")
    return hi * 13 + lo if name[2].lower() == "s" else lo * 13 + hi


def class_combos(idx: int) -> int:
    a, b = divmod(idx, 13)
    return 6 if a == b else (4 if a > b else 12)


def class_cards(idx: int) -> list[tuple[int, int]]:
    """All concrete two-card combos of a class."""
    a, b = divmod(idx, 13)
    out = []
    if a == b:
        for s1 in range(4):
            for s2 in range(s1 + 1, 4):
                out.append(((a << 2) | s1, (a << 2) | s2))
    elif a > b:  # suited
        for s in range(4):
            out.append(((a << 2) | s, (b << 2) | s))
    else:  # offsuit, a < b
        for s1 in range(4):
            for s2 in range(4):
                if s1 != s2:
                    out.append(((b << 2) | s1, (a << 2) | s2))
    return out


# --------------------------------------------------------------------------
# Monte Carlo
# --------------------------------------------------------------------------
def equity_vs_random(
    hole: Sequence[int],
    board: Sequence[int],
    n_opponents: int,
    samples: int,
    rng: random.Random,
    evaluator: Evaluator = STANDARD_EVALUATOR,
) -> float:
    """Share of the pot the hero expects against ``n_opponents`` random hands.

    Ties split the share. Deals the remaining board and all opponent hole
    cards from the unseen deck each sample.
    """
    if not 1 <= n_opponents <= 7:
        raise ValueError("n_opponents must be 1..7")
    seen = set(hole) | set(board)
    avail = [c for c in range(DECK_SIZE) if c not in seen]
    need_board = 5 - len(board)
    need = need_board + 2 * n_opponents
    hole = tuple(hole)
    board = tuple(board)
    ev = evaluator.evaluate
    share = 0.0
    sample = rng.sample
    for _ in range(samples):
        d = sample(avail, need)
        full = board + tuple(d[:need_board])
        hv = ev(hole + full)
        best = hv
        ties = 1
        i = need_board
        hero_best = True
        for _ in range(n_opponents):
            v = ev((d[i], d[i + 1]) + full)
            i += 2
            if v > best:
                best = v
                hero_best = False
                ties = 1
            elif v == best:
                ties += 1
        if hero_best:
            share += 1.0 / ties
    return share / samples


def equity_vs_ranges(
    hole: Sequence[int],
    board: Sequence[int],
    ranges: Sequence[Sequence[tuple[int, int]]],
    samples: int,
    rng: random.Random,
    evaluator: Evaluator = STANDARD_EVALUATOR,
) -> float:
    """Hero equity against opponents each holding a hand from their range.

    ``ranges[i]`` is a list of concrete two-card combos (see ``class_cards``
    and ``range_from_top``). Combos that collide with known cards or with each
    other are rejected and redrawn, which weights the range correctly.
    """
    seen = set(hole) | set(board)
    hole = tuple(hole)
    board = tuple(board)
    need_board = 5 - len(board)
    ev = evaluator.evaluate
    ranges = [list(r) for r in ranges]
    for r in ranges:
        if not r:
            raise ValueError("empty range")
    share = 0.0
    choice = rng.choice
    sample = rng.sample
    for _ in range(samples):
        used = set(seen)
        opp = []
        for r in ranges:
            for _try in range(1000):
                h = choice(r)
                if h[0] not in used and h[1] not in used:
                    break
            else:
                raise ValueError("range incompatible with known cards")
            used.add(h[0])
            used.add(h[1])
            opp.append(h)
        avail = [c for c in range(DECK_SIZE) if c not in used]
        full = board + tuple(sample(avail, need_board)) if need_board else board
        hv = ev(hole + full)
        best = hv
        ties = 1
        hero_best = True
        for h in opp:
            v = ev(h + full)
            if v > best:
                best = v
                hero_best = False
                ties = 1
            elif v == best:
                ties += 1
        if hero_best:
            share += 1.0 / ties
    return share / samples


# --------------------------------------------------------------------------
# Precomputed preflop table
# --------------------------------------------------------------------------
_TABLE: list[list[float]] | None = None  # _TABLE[n_opp - 1][class]
_VS_TOP: list[list[float]] | None = None  # _VS_TOP[frac_index][class]: HU equity vs a top-X% range
PREFLOP_META: dict = {}
_PERCENTILE: list[float] | None = None
_ORDER: list[int] | None = None
# Grid of "top X%" range widths for the vs-range table.
RANGE_FRACS = (0.03, 0.06, 0.10, 0.15, 0.20, 0.30, 0.40, 0.55, 0.75, 1.0)


def _percentiles(hu: Sequence[float]) -> tuple[list[int], list[float]]:
    order = sorted(range(NUM_CLASSES), key=lambda i: -hu[i])
    pct = [0.0] * NUM_CLASSES
    cum = 0
    for i in order:
        cum += class_combos(i)
        pct[i] = cum / 1326.0
    return order, pct


def _load() -> list[list[float]]:
    global _TABLE, _VS_TOP, _PERCENTILE, _ORDER
    if _TABLE is None:
        with open(_DATA_PATH) as f:
            d = json.load(f)
        _TABLE = [list(map(float, row)) for row in d["equity"]]
        _VS_TOP = [list(map(float, row)) for row in d.get("vs_top", [])] or None
        PREFLOP_META.update({k: v for k, v in d.items() if k not in ("equity", "vs_top")})
        _ORDER, _PERCENTILE = _percentiles(_TABLE[0])
    return _TABLE


def class_equity_vs_top(idx: int, fraction: float) -> float:
    """Heads-up equity of a class against an opponent holding a uniformly
    random combo from the top ``fraction`` of hands. Linear interpolation on
    ``RANGE_FRACS``; ``fraction`` >= 1 is a random hand."""
    _load()
    if _VS_TOP is None:
        return _TABLE[0][idx]
    if fraction <= RANGE_FRACS[0]:
        return _VS_TOP[0][idx]
    if fraction >= 1.0:
        return _VS_TOP[-1][idx]
    for j in range(1, len(RANGE_FRACS)):
        if fraction <= RANGE_FRACS[j]:
            a, b = RANGE_FRACS[j - 1], RANGE_FRACS[j]
            t = (fraction - a) / (b - a)
            return _VS_TOP[j - 1][idx] * (1 - t) + _VS_TOP[j][idx] * t
    return _VS_TOP[-1][idx]


def equity_vs_top(c1: int, c2: int, fraction: float) -> float:
    return class_equity_vs_top(class_index(c1, c2), fraction)


def preflop_equity(c1: int, c2: int, n_opponents: int) -> float:
    """Table lookup: equity of the hole cards vs ``n_opponents`` random hands
    with all five board cards to come."""
    return _load()[n_opponents - 1][class_index(c1, c2)]


def class_equity(idx: int, n_opponents: int) -> float:
    return _load()[n_opponents - 1][idx]


def class_percentile(idx: int) -> float:
    """Fraction of all 1326 combos that are at least as strong heads-up as
    this class (AA ~= 0.0045, 72o = 1.0). "Top 20%" means percentile <= 0.20."""
    _load()
    return _PERCENTILE[idx]


def hand_percentile(c1: int, c2: int) -> float:
    return class_percentile(class_index(c1, c2))


def classes_by_strength() -> list[int]:
    """Class indices from strongest to weakest by heads-up equity."""
    _load()
    return list(_ORDER)


def range_from_top(fraction: float) -> list[tuple[int, int]]:
    """All concrete combos in the top ``fraction`` of hands by heads-up equity."""
    out = []
    for idx in classes_by_strength():
        if class_percentile(idx) <= fraction + 1e-12:
            out.extend(class_cards(idx))
    return out


# --------------------------------------------------------------------------
# Table generation (offline; see scripts/gen_preflop_equity.py)
# --------------------------------------------------------------------------
def _cell_seed(seed: int, *parts: int) -> int:
    """Well-mixed per-cell seed (consecutive ints would be correlated draws)."""
    import hashlib

    h = hashlib.sha256((":".join(map(str, (seed,) + parts))).encode()).digest()
    return int.from_bytes(h[:8], "big")


def _gen_cell(args):
    idx, n_opp, samples, seed = args
    rng = random.Random(seed)
    combos = class_cards(idx)
    # Rotate through the concrete combos so suits are not biased.
    total = 0.0
    per = samples // len(combos)
    for h in combos:
        total += equity_vs_random(h, (), n_opp, per, rng) * per
    return idx, n_opp, total / (per * len(combos))


def _gen_vs_top_cell(args):
    idx, j, frac, samples, seed, pct = args
    rng = random.Random(seed)
    rng_combos = []
    for k in range(NUM_CLASSES):
        if pct[k] <= frac + 1e-12:
            rng_combos.extend(class_cards(k))
    combos = class_cards(idx)
    per = samples // len(combos)
    total = 0.0
    for h in combos:
        total += equity_vs_ranges(h, (), [rng_combos], per, rng) * per
    return idx, j, total / (per * len(combos))


def _run_jobs(fn, jobs, workers):
    if workers > 1:
        import multiprocessing as mp

        with mp.get_context("spawn").Pool(workers) as pool:
            yield from pool.imap_unordered(fn, jobs, chunksize=8)
    else:
        for job in jobs:
            yield fn(job)


def generate_table(samples: int, seed: int, workers: int = 1) -> dict:
    jobs = []
    for n_opp in range(1, 8):
        for idx in range(NUM_CLASSES):
            jobs.append((idx, n_opp, samples, _cell_seed(seed, 1, n_opp, idx)))
    table = [[0.0] * NUM_CLASSES for _ in range(7)]
    for idx, n_opp, eq in _run_jobs(_gen_cell, jobs, workers):
        table[n_opp - 1][idx] = eq
    # Phase 2: heads-up equity vs top-X% ranges, defined by the HU column above.
    _, pct = _percentiles(table[0])
    jobs = []
    for j, frac in enumerate(RANGE_FRACS):
        for idx in range(NUM_CLASSES):
            jobs.append((idx, j, frac, samples, _cell_seed(seed, 2, j, idx), pct))
    vs_top = [[0.0] * NUM_CLASSES for _ in RANGE_FRACS]
    for idx, j, eq in _run_jobs(_gen_vs_top_cell, jobs, workers):
        vs_top[j][idx] = eq
    return {
        "samples_per_class": samples,
        "seed": seed,
        "method": "monte_carlo_vs_random_hands; vs_top = HU vs uniform combo from top-X% (by HU equity)",
        "range_fracs": list(RANGE_FRACS),
        "classes": [class_name(i) for i in range(NUM_CLASSES)],
        "equity": [[round(x, 5) for x in row] for row in table],
        "vs_top": [[round(x, 5) for x in row] for row in vs_top],
    }
