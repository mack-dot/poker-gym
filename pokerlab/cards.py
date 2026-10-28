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
