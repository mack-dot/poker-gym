import random
from collections import Counter

from pokerlab.cards import card_str, deal_cards, fresh_deck, parse_card, parse_cards


def test_roundtrip_and_deck():
    deck = fresh_deck()
    assert len(deck) == 52 and len(set(deck)) == 52
    assert all(parse_card(card_str(c)) == c for c in deck)
    assert parse_cards("AsKd2c") == [parse_card("As"), parse_card("Kd"), parse_card("2c")]
    assert card_str(parse_card("Th")) == "Th"


def test_deal_cards_distinct_and_deterministic():
    for k in (2, 7, 21, 52):
        a = deal_cards(random.Random(5), k)
        b = deal_cards(random.Random(5), k)
        assert a == b and len(a) == k and len(set(a)) == k and all(0 <= c < 52 for c in a)
    assert deal_cards(random.Random(5), 21) != deal_cards(random.Random(6), 21)


def test_deal_cards_is_uniform_per_position():
    """Each of the 52 cards should appear in each dealt position with
    frequency 1/52. Chi-square against uniform with a loose bound."""
    rng = random.Random(123)
    n = 52 * 400
    k = 21
    counts = [Counter() for _ in range(k)]
    for _ in range(n):
        d = deal_cards(rng, k)
        for pos, c in enumerate(d):
            counts[pos][c] += 1
    expected = n / 52
    for pos in range(k):
        chi2 = sum((counts[pos][c] - expected) ** 2 / expected for c in range(52))
        # 51 degrees of freedom: mean 51, sd ~10.1; 110 is > 5 sd
        assert chi2 < 110, (pos, chi2)
    # joint distribution of the first two cards: uniform over the 52*51 ordered pairs
    pair = Counter()
    rng = random.Random(7)
    m = 52 * 51 * 20
    for _ in range(m):
        d = deal_cards(rng, 2)
        pair[(d[0], d[1])] += 1
    assert all(a != b for a, b in pair)
    exp = m / (52 * 51)
    chi2 = sum((pair[(a, b)] - exp) ** 2 / exp for a in range(52) for b in range(52) if a != b)
    # 2651 degrees of freedom: mean 2651, sd ~73; 3000 is ~4.8 sd
    assert chi2 < 3000, chi2
