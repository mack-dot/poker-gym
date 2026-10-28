import random

import pytest

from pokergym.cards import parse_cards
from pokergym.equity import (
    NUM_CLASSES, PREFLOP_META, RANGE_FRACS, class_cards, class_combos, class_equity, class_equity_vs_top,
    class_from_name, class_index, class_name, class_percentile, classes_by_strength, equity_vs_random,
    equity_vs_ranges, equity_vs_top, hand_percentile, preflop_equity, range_from_top,
)


def test_class_index_is_a_bijection_with_correct_combo_counts():
    counts = [0] * NUM_CLASSES
    for c1 in range(52):
        for c2 in range(c1 + 1, 52):
            counts[class_index(c1, c2)] += 1
    assert sum(counts) == 1326
    for idx in range(NUM_CLASSES):
        assert counts[idx] == class_combos(idx), class_name(idx)
        assert len(class_cards(idx)) == class_combos(idx)
        assert class_from_name(class_name(idx)) == idx
        for h in class_cards(idx):
            assert class_index(*h) == idx


def test_class_names():
    a, k = parse_cards("AsKs")
    assert class_name(class_index(a, k)) == "AKs"
    a, k = parse_cards("AsKd")
    assert class_name(class_index(a, k)) == "AKo"
    assert class_name(class_index(*parse_cards("7c7d"))) == "77"
    assert class_index(*parse_cards("AsKd")) == class_index(*parse_cards("KhAc"))


def test_monte_carlo_matches_known_heads_up_equities():
    rng = random.Random(7)
    aa = equity_vs_random(parse_cards("AsAd"), (), 1, 20000, rng)
    assert abs(aa - 0.852) < 0.012  # AA vs random: 85.2%
    ak = equity_vs_random(parse_cards("AsKs"), (), 1, 20000, rng)
    assert abs(ak - 0.670) < 0.012  # AKs vs random: ~67.0%
    s72 = equity_vs_random(parse_cards("7c2d"), (), 1, 20000, rng)
    assert abs(s72 - 0.347) < 0.012  # 72o: ~34.6%


def test_monte_carlo_with_board():
    rng = random.Random(3)
    # Set over two pair on a dry board; the two pair has 4 outs on the river.
    hero = parse_cards("KsKd")
    board = parse_cards("Kh7c2d7h")
    eq = equity_vs_random(hero, board, 1, 5000, rng)
    assert eq > 0.95
    # Flush draw + overcard ace vs top pair, one card to come: 9 spades + 3 aces = 12/44.
    eq2 = equity_vs_ranges(parse_cards("As5s"), parse_cards("Ks9s2c7d"), [[tuple(parse_cards("KdQc"))]], 4000, rng)
    assert abs(eq2 - 12 / 44) < 0.03


def test_preflop_table_sanity():
    assert PREFLOP_META.get("samples_per_class", 0) >= 10000 or preflop_equity(48, 49, 1) > 0
    aa = class_from_name("AA")
    assert class_equity(aa, 1) == max(class_equity(i, 1) for i in range(NUM_CLASSES))
    assert abs(class_equity(aa, 1) - 0.852) < 0.006
    assert abs(class_equity(aa, 7) - 0.389) < 0.008  # AA vs 7 random ~38.9%
    assert abs(class_equity(class_from_name("AKs"), 1) - 0.670) < 0.006
    assert abs(class_equity(class_from_name("72o"), 1) - 0.346) < 0.006
    # Equity vs more opponents is lower for every class.
    for idx in range(NUM_CLASSES):
        row = [class_equity(idx, n) for n in range(1, 8)]
        assert all(row[i] > row[i + 1] for i in range(6)), class_name(idx)
    # Percentiles: AA is the top ~0.45%, the weakest class is at 1.0.
    assert abs(class_percentile(aa) - 6 / 1326) < 1e-9
    order = classes_by_strength()
    assert order[0] == aa
    assert class_percentile(order[-1]) == pytest.approx(1.0)
    assert class_name(order[-1]) in ("72o", "32o", "82o")
    assert hand_percentile(*parse_cards("AsKs")) < 0.05


def test_vs_top_range_table():
    aa = class_from_name("AA")
    # Against a wider range AA does better; against the full range it matches the HU column.
    row = [class_equity_vs_top(aa, fr) for fr in RANGE_FRACS]
    assert row[0] < row[-1]
    assert abs(row[-1] - class_equity(aa, 1)) < 0.01
    # A medium hand loses to a tight range and beats a random one.
    t9 = class_from_name("T9s")
    assert class_equity_vs_top(t9, 0.03) < 0.35
    assert class_equity_vs_top(t9, 1.0) > 0.5
    # Interpolation is between the grid points.
    mid = class_equity_vs_top(t9, (RANGE_FRACS[2] + RANGE_FRACS[3]) / 2)
    lo, hi = sorted((class_equity_vs_top(t9, RANGE_FRACS[2]), class_equity_vs_top(t9, RANGE_FRACS[3])))
    assert lo <= mid <= hi
    assert equity_vs_top(*parse_cards("AsAd"), 0.1) == class_equity_vs_top(aa, 0.1)


def test_range_from_top():
    assert len(range_from_top(1.0)) == 1326
    top10 = range_from_top(0.10)
    assert 110 <= len(top10) <= 150
    assert all(hand_percentile(*h) <= 0.10 + 1e-9 for h in top10)
