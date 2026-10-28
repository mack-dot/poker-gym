"""Single-hand engine: blinds, dealing, betting rounds, side pots, showdown.

Design goals: correctness first, then speed. All state is plain lists of
ints indexed by table seat. ``play_hand`` mutates ``stacks`` in place and
returns a ``HandRecord``.
"""
from __future__ import annotations

import random
from typing import Sequence

from .agent import Action, ActionType, AgentAdapter, Observation
from .cards import card_str, deal_cards
from .evaluator import Evaluator
from .rules import GameRules

STREET_NAMES = ("preflop", "flop", "turn", "river")


class HandRecord:
    __slots__ = (
        "hand_number", "button", "sb_seat", "bb_seat", "blinds", "ante", "hole", "board",
        "actions", "net", "stacks_after", "showdown_values", "pots", "start_stacks",
    )

    def __init__(self):
        self.actions: list[tuple[int, int, int, int]] = []  # (street, seat, kind, amount)
        self.pots: list[tuple[int, tuple[int, ...], tuple[int, ...]]] = []  # (amount, eligible, winners)
        self.showdown_values = None

    def to_dict(self) -> dict:
        return {
            "hand": self.hand_number,
            "button": self.button,
            "sb": self.sb_seat,
            "bb": self.bb_seat,
            "blinds": list(self.blinds),
            "ante": self.ante,
            "start_stacks": list(self.start_stacks),
            "hole": [None if h is None else [card_str(c) for c in h] for h in self.hole],
            "board": [card_str(c) for c in self.board],
            "actions": [
                [STREET_NAMES[st], seat, ActionType(k).name.lower(), amt] for (st, seat, k, amt) in self.actions
            ],
            "pots": [[amt, list(el), list(w)] for (amt, el, w) in self.pots],
            "net": list(self.net),
            "stacks_after": list(self.stacks_after),
        }


def _next_live(start: int, live_flags: Sequence[bool], n: int) -> int:
    s = (start + 1) % n
    while not live_flags[s]:
        s = (s + 1) % n
    return s


def play_hand(
    rules: GameRules,
    evaluator: Evaluator,
    stacks: list[int],
    button: int,
    hand_number: int,
    agents: Sequence[AgentAdapter],
    rng: random.Random,
    deck: list[int] | None = None,
) -> HandRecord:
    """Play one hand. ``stacks`` is mutated. ``deck`` overrides the shuffle (tests)."""
    n = len(stacks)
    live = [s > 0 for s in stacks]
    live_seats = [s for s in range(n) if live[s]]
    k = len(live_seats)
    if k < 2:
        raise ValueError("need at least two live players")

    rec = HandRecord()
    rec.hand_number = hand_number
    rec.button = button
    rec.start_stacks = tuple(stacks)
    sb_amt, bb_amt = rules.blinds.blinds_for_hand(hand_number)
    ante = rules.blinds.ante_for_hand(hand_number)
    rec.blinds = (sb_amt, bb_amt)
    rec.ante = ante

    if k == 2:
        sb_seat = button
        bb_seat = _next_live(button, live, n)
    else:
        sb_seat = _next_live(button, live, n)
        bb_seat = _next_live(sb_seat, live, n)
    rec.sb_seat, rec.bb_seat = sb_seat, bb_seat

    in_hand = list(live)
    bets = [0] * n
    paid = [0] * n
    all_in = [False] * n
    actions = rec.actions
    betting = rules.betting
    pot_limit = betting.limit == "pot_limit"
    raise_cap = betting.raise_cap_per_street

    pot_box = [0]  # running total of all chips committed this hand

    def commit(seat: int, amount: int, counts_as_bet: bool = True) -> int:
        a = amount if amount < stacks[seat] else stacks[seat]
        stacks[seat] -= a
        paid[seat] += a
        pot_box[0] += a
        if counts_as_bet:
            bets[seat] += a
        if stacks[seat] == 0:
            all_in[seat] = True
        return a

    # --- antes and blinds -------------------------------------------------
    if ante:
        for s in live_seats:
            commit(s, ante, counts_as_bet=False)
    commit(sb_seat, sb_amt)
    commit(bb_seat, bb_amt)

    # --- deal ---------------------------------------------------------------
    hc = rules.hole_cards
    board_total = sum(rules.board_streets)
    if deck is None:
        deck = deal_cards(rng, hc * k + board_total)
    hole: list[tuple[int, ...] | None] = [None] * n
    order_from_sb = []
    s = sb_seat
    for _ in range(k):
        order_from_sb.append(s)
        s = _next_live(s, live, n)
    # round-robin from the small blind: seat j gets deck[j], deck[j + k], ...
    for j, s in enumerate(order_from_sb):
        hole[s] = tuple(deck[j + r * k] for r in range(hc))
    idx = hc * k
    rec.hole = hole
    board: list[int] = []
    rec.board = board
    board_cards = deck[idx: idx + board_total]

    num_in_hand = k

    # --- betting round ----------------------------------------------------
    def betting_round(street: int, first: int, current_bet: int, min_raise_inc: int, raises: int) -> int:
        """Returns the number of players still in the hand."""
        nonlocal num_in_hand
        acted: set[int] = set()
        acted_since_full: set[int] = set()
        # cyclic order of live seats starting at `first`
        start_i = live_seats.index(first)
        order = live_seats[start_i:] + live_seats[:start_i]
        i = 0
        board_t = tuple(board)
        while True:
            if num_in_hand == 1:
                return 1
            # contenders: in the hand and not all-in
            nc = 0
            settled = True
            last_c = -1
            for c in live_seats:
                if in_hand[c] and not all_in[c]:
                    nc += 1
                    last_c = c
                    if settled and (c not in acted or bets[c] != current_bet):
                        settled = False
            if nc == 0 or settled:
                return num_in_hand
            if nc == 1 and bets[last_c] == current_bet:
                return num_in_hand  # nobody left who could respond to a bet
            s = order[i % k]
            i += 1
            if not in_hand[s] or all_in[s]:
                continue
            if s in acted and bets[s] == current_bet:
                continue

            to_call = current_bet - bets[s]
            stack = stacks[s]
            can_check = to_call == 0
            can_raise = stack > to_call and nc > 1 and s not in acted_since_full
            if can_raise and raise_cap is not None and raises >= raise_cap:
                can_raise = False
            min_to = current_bet + min_raise_inc
            max_to = bets[s] + stack
            pot = pot_box[0]
            if pot_limit:
                pl = current_bet + to_call + pot
                if pl < max_to:
                    max_to = pl
            if max_to <= current_bet:
                can_raise = False
            elif min_to > max_to:
                min_to = max_to
            if not can_raise:
                min_to = max_to = 0

            obs = Observation(
                hand_number, street, s, button, sb_amt, bb_amt, ante,
                hole[s], board_t, tuple(stacks), tuple(bets), tuple(paid), tuple(in_hand), tuple(all_in),
                pot, to_call if to_call < stack else stack, can_check,
                can_raise, min_to, max_to, tuple(actions), n, k,
            )
            a: Action = agents[s].act(obs)
            kind = a.kind
            acted.add(s)
            if kind == ActionType.FOLD:
                in_hand[s] = False
                num_in_hand -= 1
                actions.append((street, s, 0, 0))
            elif kind == ActionType.CHECK:
                acted_since_full.add(s)
                actions.append((street, s, 1, 0))
            elif kind == ActionType.CALL:
                amt = commit(s, to_call)
                acted_since_full.add(s)
                actions.append((street, s, 2, amt))
            else:  # RAISE to a.amount
                target = a.amount
                inc = target - current_bet
                commit(s, target - bets[s])
                if inc >= min_raise_inc:
                    min_raise_inc = inc
                    acted_since_full = {s}
                else:  # short all-in raise: does not reopen action
                    acted_since_full.add(s)
                current_bet = target
                raises += 1
                actions.append((street, s, 3, target))

    # --- preflop --------------------------------------------------------------
    current_bet = bb_amt if betting.bb_is_min_bet_even_if_short else bets[bb_seat]
    first = sb_seat if k == 2 else _next_live(bb_seat, live, n)
    remaining = betting_round(0, first, current_bet, bb_amt, 1)

    # --- later streets ----------------------------------------------------
    bidx = 0
    for street, ncards in enumerate(rules.board_streets, start=1):
        board.extend(board_cards[bidx: bidx + ncards])
        bidx += ncards
        if remaining <= 1:
            continue  # deal out (irrelevant) but no action; kept for record completeness
        for s in live_seats:
            bets[s] = 0
        contenders = sum(1 for c in live_seats if in_hand[c] and not all_in[c])
        if contenders >= 2:
            remaining = betting_round(street, _next_live(button, live, n), 0, bb_amt, 0)

    # --- settle ---------------------------------------------------------------
    values: dict[int, int] | None = None
    if num_in_hand > 1:
        values = {}
        for s in live_seats:
            if in_hand[s]:
                values[s] = evaluator.evaluate(hole[s] + tuple(board))
        rec.showdown_values = values

    net = [-p for p in paid]
    levels = sorted({paid[s] for s in live_seats if paid[s] > 0})
    prev = 0
    pots: list[tuple[int, tuple[int, ...]]] = []  # (amount, eligible) merged by eligibility
    for lvl in levels:
        contributors = [s for s in live_seats if paid[s] >= lvl]
        amount = (lvl - prev) * len(contributors)
        prev = lvl
        eligible = tuple(s for s in contributors if in_hand[s])
        if not eligible:  # cannot happen in legal play; refund to contributors
            eligible = tuple(contributors)
        if pots and pots[-1][1] == eligible:
            pots[-1] = (pots[-1][0] + amount, eligible)
        else:
            pots.append((amount, eligible))
    for amount, eligible in pots:
        if len(eligible) == 1 or values is None:
            winners = eligible[:1] if values is None else eligible
        else:
            best = max(values[s] for s in eligible)
            winners = [s for s in eligible if values[s] == best]
        share, rem = divmod(amount, len(winners))
        # odd chips go to the first winner(s) clockwise from the button
        if rem:
            ordered = sorted(winners, key=lambda w: (w - button - 1) % n)
        else:
            ordered = winners
        for j, w in enumerate(ordered):
            give = share + (1 if j < rem else 0)
            stacks[w] += give
            net[w] += give
        rec.pots.append((amount, eligible, tuple(winners)))
    rec.net = tuple(net)
    rec.stacks_after = tuple(stacks)
    return rec
