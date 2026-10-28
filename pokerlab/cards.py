"""Card encoding.

A card is an int in ``range(52)``: ``rank = card >> 2`` (0 = deuce ... 12 = ace),
``suit = card & 3`` (0 = clubs, 1 = diamonds, 2 = hearts, 3 = spades).
"""
from __future__ import annotations

RANKS = "23456789TJQKA"
SUITS = "cdhs"
DECK_SIZE = 52


def make_card(rank: int, suit: int) -> int:
    return (rank << 2) | suit


def rank_of(card: int) -> int:
    return card >> 2


def suit_of(card: int) -> int:
    return card & 3


def card_str(card: int) -> str:
    return RANKS[card >> 2] + SUITS[card & 3]


def parse_card(text: str) -> int:
    text = text.strip()
    if len(text) != 2:
        raise ValueError(f"bad card {text!r}")
    r = RANKS.index(text[0].upper())
    s = SUITS.index(text[1].lower())
    return make_card(r, s)


def parse_cards(text: str) -> list[int]:
    """Parse 'AsKd' or 'As Kd' into a list of card ints."""
    text = text.replace(" ", "")
    return [parse_card(text[i : i + 2]) for i in range(0, len(text), 2)]


def cards_str(cards) -> str:
    return " ".join(card_str(c) for c in cards)


def fresh_deck() -> list[int]:
    return list(range(DECK_SIZE))


def _perm_counts():
    out = [1]
    for k in range(1, DECK_SIZE + 1):
        out.append(out[-1] * (DECK_SIZE - k + 1))
    return tuple(out)


_PERM_COUNT = _perm_counts()  # _PERM_COUNT[k] = 52! / (52-k)!
_BITS = tuple(c.bit_length() + 64 for c in _PERM_COUNT)
_LIMIT = tuple(((1 << b) // c) * c if c else 0 for b, c in zip(_BITS, _PERM_COUNT))


def deal_cards(rng, k: int) -> list[int]:
    """Exactly uniform ordered draw of ``k`` distinct cards from a fresh deck.

    Uses one large ``getrandbits`` call (with rejection to remove modulo bias)
    and decodes a k-permutation index, instead of ``rng.shuffle`` which costs
    51 Python-level ``_randbelow`` calls. Deterministic for a seeded ``rng``.
    """
    total = _PERM_COUNT[k]
    bits = _BITS[k]
    limit = _LIMIT[k]
    x = rng.getrandbits(bits)
    while x >= limit:
        x = rng.getrandbits(bits)
    x %= total
    pool = list(range(DECK_SIZE))
    out = []
    n = DECK_SIZE
    for _ in range(k):
        x, j = divmod(x, n)
        out.append(pool[j])
        n -= 1
        pool[j] = pool[n]
    return out
