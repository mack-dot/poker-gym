"""Build an ``Observation`` from plain values, and read/write actions as text.

This is the 20-line adapter we will write on tournament day, prepared in
advance. Whatever the official kit hands us (a dict, an object, a message
string), the job is to extract these plain fields and call
``build_observation``. The bot then runs unchanged.

``build_observation`` derives everything derivable: ``pot``, ``to_call``,
``can_check``, ``can_raise``, ``min_raise_to`` / ``max_raise_to`` (no-limit
unless ``max_raise_to`` is given), ``in_hand`` / ``all_in`` defaults, and
``live_players``. Any derived field can be overridden by passing it, so if the
kit tells us the legal raise bounds we use theirs.

The text action codec follows the vocabulary used by the organizer's landing
page demo ("FOLD", "CHECK", "CALL 100", "BET 200", "RAISE TO 400",
"ALL-IN 950"). That demo is not the kit; this format is a REHEARSAL guess and
lives in one place so it can be changed in one place.
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

from .agent import CALL, CHECK, FOLD, Action, ActionType, Observation, TableInfo, raise_to
from .cards import card_str, parse_card

Card = int | str

_HIST_KINDS = {"fold": 0, "check": 1, "call": 2, "raise": 3, "bet": 3, "all-in": 3, "allin": 3}


def to_card(c: Card) -> int:
    return c if isinstance(c, int) else parse_card(c)


def to_cards(cs: Iterable[Card]) -> tuple[int, ...]:
    return tuple(to_card(c) for c in cs)


def build_observation(
    *,
    seat: int,
    button: int,
    hole_cards: Sequence[Card],
    board: Sequence[Card],
    stacks: Sequence[int],
    bets: Sequence[int],
    big_blind: int,
    small_blind: int | None = None,
    committed: Sequence[int] | None = None,
    in_hand: Sequence[bool] | None = None,
    all_in: Sequence[bool] | None = None,
    hand_number: int = 0,
    street: int | None = None,
    ante: int = 0,
    pot: int | None = None,
    to_call: int | None = None,
    can_check: bool | None = None,
    can_raise: bool | None = None,
    min_raise_to: int | None = None,
    max_raise_to: int | None = None,
    last_raise_size: int | None = None,
    current_bet: int | None = None,
    history: Sequence[tuple] = (),
) -> Observation:
    """Assemble an ``Observation`` from whatever plain values the kit gives.

    ``stacks`` are chips behind (not including ``bets``). ``bets`` are chips
    put in on the current street. ``committed`` is chips put in this hand
    (defaults to ``bets`` preflop, else unknown -> ``bets``). ``history`` items
    may be ``(street, seat, kind, amount)`` with ``kind`` as int or text.
    """
    n = len(stacks)
    hole = to_cards(hole_cards)
    brd = to_cards(board)
    stacks = tuple(int(x) for x in stacks)
    bets = tuple(int(x) for x in bets)
    if street is None:
        street = {0: 0, 3: 1, 4: 2, 5: 3}[len(brd)]
    if small_blind is None:
        small_blind = big_blind // 2
    if committed is None:
        committed = bets
    committed = tuple(int(x) for x in committed)
    if in_hand is None:
        in_hand = tuple(stacks[s] + committed[s] > 0 for s in range(n))
    in_hand = tuple(bool(x) for x in in_hand)
    if all_in is None:
        all_in = tuple(in_hand[s] and stacks[s] == 0 for s in range(n))
    all_in = tuple(bool(x) for x in all_in)
    if pot is None:
        pot = sum(committed)  # antes must be inside ``committed`` or pass ``pot``
    if current_bet is None:
        current_bet = max(bets) if bets else 0
        if street == 0 and current_bet < big_blind:
            current_bet = big_blind  # a short all-in big blind still sets the BB as the bet to match
    me_stack = stacks[seat]
    if to_call is None:
        to_call = min(me_stack, max(0, current_bet - bets[seat]))
    if can_check is None:
        can_check = to_call == 0
    contenders = sum(1 for s in range(n) if in_hand[s] and not all_in[s])
    if can_raise is None:
        can_raise = me_stack > to_call and contenders > 1
    if max_raise_to is None:
        max_raise_to = bets[seat] + me_stack
    if min_raise_to is None:
        inc = last_raise_size if last_raise_size is not None else big_blind
        min_raise_to = max(current_bet + max(inc, big_blind), big_blind)
        if min_raise_to > max_raise_to:
            min_raise_to = max_raise_to
    if max_raise_to <= current_bet:
        can_raise = False
    if not can_raise:
        min_raise_to = max_raise_to = 0
    hist = tuple(_norm_hist(h) for h in history)
    live = sum(1 for s in range(n) if stacks[s] + committed[s] > 0)
    return Observation(
        hand_number, street, seat, button, small_blind, big_blind, ante,
        hole, brd, stacks, bets, committed, in_hand, all_in,
        int(pot), int(to_call), bool(can_check), bool(can_raise), int(min_raise_to), int(max_raise_to),
        hist, n, live,
    )


def _norm_hist(h) -> tuple[int, int, int, int]:
    street, seat, kind, amount = h
    if isinstance(street, str):
        street = ("preflop", "flop", "turn", "river").index(street.lower())
    if isinstance(kind, str):
        kind = _HIST_KINDS[kind.lower()]
    return int(street), int(seat), int(kind), int(amount)


def build_table_info(seat: int, num_players: int, starting_stack: int, seed: int = 0, rules_name: str = "official") -> TableInfo:
    return TableInfo(seat=seat, num_players=num_players, starting_stack=starting_stack, rules_name=rules_name, seed=seed)


# --------------------------------------------------------------------------
# Text action codec (REHEARSAL format, modelled on the landing-page demo)
# --------------------------------------------------------------------------
def action_to_text(a: Action, obs: Observation) -> str:
    """Our Action -> demo-style text. Uses the observation to tell BET from
    RAISE TO and to mark ALL-IN."""
    k = a.kind
    if k == ActionType.FOLD:
        return "FOLD"
    if k == ActionType.CHECK:
        return "CHECK"
    if k == ActionType.CALL:
        if obs.to_call >= obs.stacks[obs.seat]:
            return f"ALL-IN {obs.stacks[obs.seat]}"
        return f"CALL {obs.to_call}"
    if a.amount >= obs.max_raise_to and obs.max_raise_to == obs.bets[obs.seat] + obs.stacks[obs.seat]:
        return f"ALL-IN {a.amount}"
    current_bet = max(obs.bets) if obs.bets else 0
    return (f"BET {a.amount}" if current_bet == 0 else f"RAISE TO {a.amount}")


_ACTION_RE = re.compile(r"^\s*(FOLD|CHECK|CALL|BET|RAISE(?:\s+TO)?|ALL[- ]?IN)\s*([0-9][0-9,]*)?\s*$", re.I)


def action_from_text(text: str, obs: Observation) -> Action:
    """Demo-style text -> our Action. ``CALL``/``ALL-IN`` amounts are checked
    against the observation; a bare ``ALL-IN`` is a raise to the maximum (or a
    call when raising is not possible)."""
    m = _ACTION_RE.match(text)
    if not m:
        raise ValueError(f"unrecognised action text {text!r}")
    word = m.group(1).upper().replace(" ", "").replace("-", "")
    amt = int(m.group(2).replace(",", "")) if m.group(2) else None
    if word == "FOLD":
        return FOLD
    if word == "CHECK":
        return CHECK
    if word == "CALL":
        return CALL
    if word == "ALLIN":
        if obs.can_raise:
            return raise_to(obs.max_raise_to)
        return CALL if not obs.can_check else CHECK
    if amt is None:
        raise ValueError(f"{text!r} needs an amount")
    return raise_to(amt)


__all__ = [
    "build_observation", "build_table_info", "to_card", "to_cards", "card_str",
    "action_to_text", "action_from_text",
]
