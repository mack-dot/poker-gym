import random

import pytest

from pokerlab.icm import brute_force_equities, icm_equities, place_probabilities


def test_hand_computed_three_player_example():
    # stacks 5000/3000/2000, payouts 50/30/20.
    # P1 first = .5; P1 second = .3*5000/7000 + .2*5000/8000 = .339286; third = .160714
    eq = icm_equities([5000, 3000, 2000], [50, 30, 20])
    assert abs(eq[0] - (50 * .5 + 30 * .339286 + 20 * .160714)) < 1e-3
    assert abs(sum(eq) - 100) < 1e-9


def test_matches_brute_force_enumeration():
    rng = random.Random(3)
    for n in (2, 3, 4, 5, 6):
        for _ in range(5):
            stacks = [rng.randint(1, 5000) for _ in range(n)]
            pay = sorted((rng.random() * 100 for _ in range(n)), reverse=True)
            a = icm_equities(stacks, pay)
            b = brute_force_equities(stacks, pay)
            for x, y in zip(a, b):
                assert abs(x - y) < 1e-9


def test_properties():
    pay = [100, 60, 40, 25, 15, 10, 5, 0]
    stacks = [4000, 3000, 2500, 2000, 1500, 1500, 1000, 500]
    eq = icm_equities(stacks, pay)
    assert abs(sum(eq) - sum(pay)) < 1e-9
    assert all(eq[i] >= eq[i + 1] - 1e-12 for i in range(7))  # monotone in stack
    assert eq[4] == pytest.approx(eq[5])  # equal stacks, equal equity
    # one player holds everything
    eq = icm_equities([16000, 0, 0], [100, 60, 40])
    assert eq[0] == pytest.approx(100)
    # equal stacks share equally
    eq = icm_equities([1000] * 4, [100, 60, 40, 25])
    assert all(abs(x - 225 / 4) < 1e-9 for x in eq)
    # probabilities are a doubly-stochastic matrix
    P = place_probabilities([3, 2, 1])
    for row in P:
        assert abs(sum(row) - 1) < 1e-12
    for p in range(3):
        assert abs(sum(P[i][p] for i in range(3)) - 1) < 1e-12


def test_fewer_payouts_than_players():
    eq = icm_equities([1000, 1000, 1000, 1000], [100])
    assert all(abs(x - 25) < 1e-9 for x in eq)
