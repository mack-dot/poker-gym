import itertools
import random

import pytest

from pokergym.cards import card_str, parse_cards, fresh_deck
from pokergym.evaluator import (
    FLUSH, FULL_HOUSE, HIGH_CARD, PAIR, QUADS, STRAIGHT, STRAIGHT_FLUSH,
    TRIPS, TWO_PAIR, Evaluator, STANDARD_EVALUATOR as E, evaluate,
)


def ev(s):
    return evaluate(parse_cards(s))


def cat(s):
    return E.category(ev(s))


def test_categories_detected():
    assert cat("As Kd Qh Jc 9s 2d 3c") == HIGH_CARD
    assert cat("As Ad Qh Jc 9s 2d 3c") == PAIR
    assert cat("As Ad Qh Qc 9s 2d 3c") == TWO_PAIR
    assert cat("As Ad Ah Qc 9s 2d 3c") == TRIPS
    assert cat("As Kd Qh Jc Ts 2d 3c") == STRAIGHT
    assert cat("As Ks Qs 9s 2s 3d 4c") == FLUSH
    assert cat("As Ad Ah Kc Ks 2d 3c") == FULL_HOUSE
    assert cat("As Ad Ah Ac Ks 2d 3c") == QUADS
    assert cat("As Ks Qs Js Ts 2d 3c") == STRAIGHT_FLUSH


def test_wheel_and_broadway():
    assert cat("As 2d 3h 4c 5s Kd Qd") == STRAIGHT
    assert ev("As 2d 3h 4c 5s Kd Qd") < ev("2s 3d 4h 5c 6s Kd Qd")  # 5-high < 6-high
    assert ev("Ts Jd Qh Kc As 2d 3d") > ev("9s Td Jh Qc Ks 2d 3d")
    # steel wheel is a straight flush, lower than a 6-high straight flush
    assert cat("As 2s 3s 4s 5s Kd Qd") == STRAIGHT_FLUSH
    assert ev("As 2s 3s 4s 5s Kd Qd") < ev("2s 3s 4s 5s 6s Kd Qd")


def test_kickers_and_ties():
    assert ev("As Ad Kh 9c 5s 2d 3c") > ev("As Ad Qh 9c 5s 2d 3c")  # pair kicker
    assert ev("As Ad Kh 9c 5s 2d 3c") == ev("Ah Ac Kd 9s 5d 2c 3h")  # suit-independent tie
    assert ev("As Ad Kh Kc 5s 2d 3c") > ev("As Ad Qh Qc Js 2d 3c")  # two pair: second pair
    assert ev("As Ad Kh Kc Qs 2d 3c") > ev("As Ad Kh Kc Js 2d 3c")  # two pair kicker
    # three pairs: best two + best remaining card (the third pair's rank counts as kicker)
    assert ev("As Ad Kh Kc Qs Qd 2c") == ev("As Ad Kh Kc Qs 3d 2c")
    # two trips -> full house, bigger trips on top (AAAKKK == AAAKKQ: both aces full of kings)
    assert ev("As Ad Ah Kc Ks Kd 2c") == ev("As Ad Ah Kc Ks Qd 2c")
    assert ev("Ks Kd Kh Ac As Ad 2c") == ev("As Ad Ah Kc Ks Kd 2c")
    assert E.category(ev("As Ad Ah Kc Ks Kd 2c")) == FULL_HOUSE
    # full house: trips rank first, then pair
    assert ev("Ks Kd Kh 2c 2s 7d 8c") > ev("Qs Qd Qh Ac As 7d 8c")
    # flush uses top five of the suit, kicker matters
    assert ev("As Ks Qs 9s 2s 3d 4c") > ev("As Ks Qs 8s 7s 3d 4c")
    assert ev("As Ks Qs 9s 2s 3d 4c") == ev("Ad Kd Qd 9d 2d 3s 4c")
    # straight beats trips, flush beats straight, full house beats flush, quads beats FH
    assert ev("As Kd Qh Jc Ts 2d 3c") > ev("As Ad Ah Qc 9s 2d 3c")
    assert ev("As Ks Qs 9s 2s 3d 4c") > ev("As Kd Qh Jc Ts 2d 3c")
    assert ev("As Ad Ah Kc Ks 2d 3c") > ev("As Ks Qs 9s 2s 3d 4c")
    assert ev("2s 2d 2h 2c Ks 3d 4c") > ev("As Ad Ah Kc Ks 2d 3c")
    # quads kicker
    assert ev("2s 2d 2h 2c Ks 3d 4c") > ev("2s 2d 2h 2c Qs 3d 4c")


def test_five_and_six_card_inputs():
    assert cat("As Ks Qs Js Ts") == STRAIGHT_FLUSH
    assert cat("As Ad Ah Kc Ks 2d") == FULL_HOUSE
    assert ev("As Kd 9h 5c 2s") == ev("Ad Kh 9s 5d 2c")


def test_best_of_seven_is_used():
    # Board straight, but hole cards make a higher straight
    assert ev("9s 8d 7h 6c 5s 4d 3c") == ev("9s 8d 7h 6c 5s Kd Qc")
    assert ev("Ts 8d 7h 6c 5s 9d 3c") > ev("9s 8d 7h 6c 5s Kd Qc")


def test_custom_ranking_reorders_categories():
    strength = list(range(9))
    strength[FLUSH], strength[FULL_HOUSE] = strength[FULL_HOUSE], strength[FLUSH]
    custom = Evaluator(strength, "fbfh")
    flush = parse_cards("As Ks Qs 9s 2s 3d 4c")
    boat = parse_cards("As Ad Ah Kc Ks 2d 3c")
    assert evaluate(boat) > evaluate(flush)
    assert custom.evaluate(flush) > custom.evaluate(boat)
    assert custom.category(custom.evaluate(flush)) == FLUSH
    # overlapping categories: straight + trips in one 7-card hand; under a
    # ranking where trips > straight the evaluator must pick trips.
    s2 = list(range(9))
    s2[TRIPS], s2[STRAIGHT] = s2[STRAIGHT], s2[TRIPS]
    e2 = Evaluator(s2)
    hand = parse_cards("9s 9d 9h 8c 7s 6d 5c")
    assert E.category(E.evaluate(hand)) == STRAIGHT
    assert e2.category(e2.evaluate(hand)) == TRIPS


def test_invalid_ranking_rejected():
    with pytest.raises(ValueError):
        Evaluator([0] * 9)


@pytest.mark.slow
def test_exhaustive_five_card_frequencies():
    expected = {0: 1302540, 1: 1098240, 2: 123552, 3: 54912, 4: 10200, 5: 5108, 6: 3744, 7: 624, 8: 40}
    counts = {k: 0 for k in expected}
    for combo in itertools.combinations(range(52), 5):
        counts[E.category(evaluate(combo))] += 1
    assert counts == expected


def test_sampled_five_card_frequencies_are_plausible():
    rng = random.Random(1)
    deck = fresh_deck()
    counts = [0] * 9
    n = 60000
    for _ in range(n):
        rng.shuffle(deck)
        counts[E.category(evaluate(deck[:5]))] += 1
    # pairs are 42.26% of five-card hands; high card 50.12%
    assert abs(counts[PAIR] / n - 0.4226) < 0.01
    assert abs(counts[HIGH_CARD] / n - 0.5012) < 0.01


pokerkit = pytest.importorskip("pokerkit")


def test_differential_against_pokerkit():
    """Independent oracle: PokerKit's StandardHighHand ordering must agree."""
    from pokerkit import StandardHighHand

    def pk(cards):
        s = "".join(card_str(c) for c in cards)
        return StandardHighHand.from_game(s[:4], s[4:])

    rng = random.Random(42)
    deck = fresh_deck()
    for _ in range(4000):
        rng.shuffle(deck)
        a, b = deck[:7], deck[7:14]
        va, vb = evaluate(a), evaluate(b)
        pa, pb = pk(a), pk(b)
        assert ((va > vb) - (va < vb)) == ((pa > pb) - (pa < pb)), (
            [card_str(c) for c in a], [card_str(c) for c in b])
