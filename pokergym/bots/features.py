"""Cheap hand and table features for bots (all well under the 1 ms budget).

Everything here is derived from the ``Observation`` only. No Monte Carlo.
"""
from __future__ import annotations

from ..agent import Observation
from ..evaluator import (
    FLUSH, PAIR, POPCOUNT, STANDARD_EVALUATOR, STRAIGHT, STRAIGHT_FLUSH, STRAIGHT_TOP, TRIPS, TWO_PAIR,
)

__all__ = [
    "Position", "table_position", "stack_bb", "effective_stack_bb", "pot_odds", "street_raises",
    "preflop_raiser", "last_aggressor", "opponents_in_hand", "HandFeatures", "hand_features",
    "draw_equity", "MADE_NONE", "MADE_WEAK_PAIR", "MADE_MID_PAIR", "MADE_TOP_PAIR", "MADE_OVERPAIR",
    "MADE_TWO_PAIR_PLUS", "MADE_NUTTISH",
]


class Position:
    """Relative position of a seat at the current hand."""

    __slots__ = ("order", "index", "players", "behind", "is_button", "is_sb", "is_bb", "bucket")

    def __init__(self, order, index, players):
        self.order = order          # live seats clockwise from SB (SB first, button last)
        self.index = index          # hero's index in ``order``
        self.players = players      # live players dealt in
        # Players still to act after hero in an unopened preflop pot
        # (order: UTG .. BTN, then SB, BB).
        if players == 2:
            self.behind = 1 if index == 0 else 0
        elif index == 0:
            self.behind = 1
        elif index == 1:
            self.behind = 0
        else:
            self.behind = (players - 1 - index) + 2
        self.is_sb = index == 0
        self.is_bb = index == 1
        self.is_button = index == players - 1 or (players == 2 and index == 0)
        # 0 early, 1 middle, 2 late (CO/BTN), 3 SB, 4 BB  (heads-up: button = 2, bb = 4)
        if players == 2:
            self.bucket = 2 if index == 0 else 4
        elif index == 0:
            self.bucket = 3
        elif index == 1:
            self.bucket = 4
        else:
            rel = (index - 2) / max(1, players - 3)
            self.bucket = 0 if rel < 0.34 else (1 if rel < 0.67 else 2)


def table_position(obs: Observation) -> Position:
    n = obs.num_players
    # Dealt in = had chips at the start of the hand (committed chips count).
    dealt = [s for s in range(n) if obs.stacks[s] + obs.committed[s] > 0]
    k = len(dealt)
    order = []
    s = obs.button
    if k == 2:
        # heads-up: button posts SB and is listed first
        order = [obs.button, next(x for x in dealt if x != obs.button)]
    else:
        for _ in range(k):
            s = (s + 1) % n
            while s not in dealt:
                s = (s + 1) % n
            order.append(s)
    return Position(order, order.index(obs.seat), k)


def stack_bb(obs: Observation, seat: int | None = None) -> float:
    s = obs.seat if seat is None else seat
    return (obs.stacks[s] + obs.bets[s]) / obs.big_blind


def effective_stack_bb(obs: Observation) -> float:
    """Hero stack capped by the largest opponent stack still in the hand."""
    mine = obs.stacks[obs.seat] + obs.bets[obs.seat]
    opp = 0
    for s in range(obs.num_players):
        if s != obs.seat and obs.in_hand[s]:
            opp = max(opp, obs.stacks[s] + obs.bets[s])
    return min(mine, opp) / obs.big_blind


def pot_odds(obs: Observation) -> float:
    """Fraction of the final pot the hero must put in to call."""
    if obs.to_call <= 0:
        return 0.0
    return obs.to_call / (obs.pot + obs.to_call)


def street_raises(obs: Observation) -> int:
    """Raises (bets) on the current street so far (preflop: BB post not counted)."""
    st = obs.street
    return sum(1 for (s, seat, k, a) in obs.history if s == st and k == 3)


def preflop_raiser(obs: Observation) -> int | None:
    """Seat of the last preflop raiser, if any."""
    last = None
    for (s, seat, k, a) in obs.history:
        if s == 0 and k == 3:
            last = seat
    return last


def last_aggressor(obs: Observation) -> int | None:
    last = None
    for (s, seat, k, a) in obs.history:
        if k == 3:
            last = seat
    return last


def opponents_in_hand(obs: Observation) -> int:
    return sum(1 for s in range(obs.num_players) if s != obs.seat and obs.in_hand[s])


# --------------------------------------------------------------------------
# Postflop features
# --------------------------------------------------------------------------
MADE_NONE = 0           # no pair
MADE_WEAK_PAIR = 1      # bottom pair / underpair below top card
MADE_MID_PAIR = 2       # second pair or pocket pair between board cards
MADE_TOP_PAIR = 3       # top pair
MADE_OVERPAIR = 4       # pocket pair above the board
MADE_TWO_PAIR_PLUS = 5  # two pair or trips (using a hole card)
MADE_NUTTISH = 6        # straight or better (using a hole card)


class HandFeatures:
    __slots__ = (
        "value", "category", "made", "plays_board", "flush_draw", "oesd", "gutshot", "outs",
        "overcards", "board_paired", "board_flush3", "board_flush4", "board_straighty",
        "high_card", "kicker_good",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return " ".join(f"{k}={getattr(self, k)}" for k in self.__slots__)


def hand_features(hole, board) -> HandFeatures:
    f = HandFeatures()
    ev = STANDARD_EVALUATOR
    cards = tuple(hole) + tuple(board)
    f.value = v = ev.evaluate(cards)
    cat = ev.category(v)
    f.category = cat
    r1, r2 = hole[0] >> 2, hole[1] >> 2
    suited = (hole[0] & 3) == (hole[1] & 3)
    board_ranks = [c >> 2 for c in board]
    bmask = 0
    for r in board_ranks:
        bmask |= 1 << r
    top_board = max(board_ranks)
    f.high_card = max(r1, r2)
    f.board_paired = len(set(board_ranks)) < len(board_ranks)

    # Board-only value: do the hole cards improve on it?
    f.plays_board = False
    if len(board) >= 5:
        f.plays_board = ev.evaluate(board) == v

    # Suit counts
    sc = [0, 0, 0, 0]
    for c in board:
        sc[c & 3] += 1
    mx = max(sc)
    f.board_flush3 = mx >= 3
    f.board_flush4 = mx >= 4
    f.flush_draw = False
    if len(board) < 5 and cat < FLUSH:
        if suited and sc[hole[0] & 3] == 2:
            f.flush_draw = True
        elif not suited and (sc[hole[0] & 3] == 3 or sc[hole[1] & 3] == 3):
            f.flush_draw = True  # one-card flush draw on a 3-flush board (weak)

    # Straight draws: count ranks that complete a straight.
    f.oesd = f.gutshot = False
    outs_straight = 0
    if len(board) < 5 and cat < STRAIGHT:
        allm = bmask | (1 << r1) | (1 << r2)
        if STRAIGHT_TOP[allm] < 0:
            completing = 0
            for r in range(13):
                if allm >> r & 1:
                    continue
                if STRAIGHT_TOP[allm | (1 << r)] >= 0:
                    completing += 1
            if completing >= 2:
                f.oesd = True
                outs_straight = 8
            elif completing == 1:
                f.gutshot = True
                outs_straight = 4
    f.board_straighty = POPCOUNT[bmask] >= 3 and (STRAIGHT_TOP[bmask] >= 0 or _connected(bmask))

    # Made-hand class relative to the board
    f.kicker_good = False
    h1_on = bool(bmask >> r1 & 1)
    h2_on = bool(bmask >> r2 & 1)
    pocket = r1 == r2
    distinct_board = set(board_ranks)

    def one_pair_class(pr: int, kicker: int) -> int:
        if pr == top_board:
            f.kicker_good = kicker >= 10
            return MADE_TOP_PAIR
        above = sum(1 for r in distinct_board if r > pr)
        return MADE_MID_PAIR if above == 1 else MADE_WEAK_PAIR

    def pocket_class(pr: int) -> int:
        if pr > top_board:
            return MADE_OVERPAIR
        above = sum(1 for r in distinct_board if r > pr)
        return MADE_MID_PAIR if above == 1 else MADE_WEAK_PAIR

    if f.plays_board:
        f.made = MADE_NONE
    elif cat >= STRAIGHT:
        f.made = MADE_NUTTISH if (cat in (STRAIGHT, FLUSH, STRAIGHT_FLUSH) or pocket or h1_on or h2_on) else MADE_NONE
    elif cat == TRIPS:
        f.made = MADE_TWO_PAIR_PLUS if (pocket or h1_on or h2_on) else MADE_NONE
    elif cat == TWO_PAIR:
        if pocket:
            f.made = pocket_class(r1) if f.board_paired else MADE_TWO_PAIR_PLUS
        elif h1_on and h2_on:
            f.made = MADE_TWO_PAIR_PLUS
        elif h1_on or h2_on:  # board is paired; hero has one pair with it
            pr, kicker = (r1, r2) if h1_on else (r2, r1)
            f.made = one_pair_class(pr, kicker)
        else:
            f.made = MADE_NONE  # two pairs on the board
    elif cat == PAIR:
        if pocket:
            f.made = pocket_class(r1)
        elif h1_on or h2_on:
            pr, kicker = (r1, r2) if h1_on else (r2, r1)
            f.made = one_pair_class(pr, kicker)
        else:
            f.made = MADE_NONE  # board pair, hole cards unpaired
    else:
        f.made = MADE_NONE

    f.overcards = sum(1 for r in (r1, r2) if r > top_board) if r1 != r2 else 0
    outs = outs_straight
    if f.flush_draw:
        outs += 9 if suited else 2
        if f.oesd:
            outs -= 2  # overlap, rough
    if f.made == MADE_NONE and f.overcards == 2 and not f.board_paired:
        outs += 3  # discounted overcard outs
    f.outs = min(outs, 15)
    return f


def _connected(bmask: int) -> bool:
    """Three board ranks within a 5-rank window (straight draws likely)."""
    for top in range(12, 3, -1):
        window = 0
        for k in range(5):
            r = top - k
            if r < 0:
                r = 12
            window |= 1 << r
        if POPCOUNT[bmask & window] >= 3:
            return True
    return False


def draw_equity(f: HandFeatures, street: int) -> float:
    """Rough equity from outs: ~2% per out per card to come (rule of 2 and 4)."""
    cards_to_come = 2 if street == 1 else (1 if street == 2 else 0)
    if cards_to_come == 0 or f.outs == 0:
        return 0.0
    return min(0.6, f.outs * 0.02 * cards_to_come * (1.05 if cards_to_come == 2 else 1.0))
