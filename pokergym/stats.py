"""Opponent statistics from observed actions (within-table state only).

``OpponentTracker.observe(obs)`` is called by a bot on every decision; it
consumes the actions of the current hand that it has not yet seen. The
organizer's rules reset bot state at the start of each table (rule 3.8), so a
tracker lives inside a bot and starts empty at ``reset``.

Limitation of the rehearsal protocol: a bot only sees actions that occur
before its own decisions. After it folds, the rest of the hand is invisible,
so counts are biased towards early-street behaviour. ``ingest_record`` feeds a
complete ``HandRecord`` dict (post-hoc analysis, not available in play).

Rates are shrunk toward a prior with ``k`` pseudo-observations so that a bot
can use them from the first hand without wild swings.
"""
from __future__ import annotations

from .agent import ActionType, Observation

_FOLD, _CHECK, _CALL, _RAISE = (int(ActionType.FOLD), int(ActionType.CHECK), int(ActionType.CALL), int(ActionType.RAISE))

# Population priors (loose fixtures; overridden quickly by data).
PRIOR = {
    "vpip": 0.35, "pfr": 0.15, "three_bet": 0.06, "fold_to_steal": 0.6,
    "cbet": 0.6, "fold_to_cbet": 0.45, "agg": 0.4,
}


def _rate(num: int, den: int, prior: float, k: int = 8) -> float:
    return (num + prior * k) / (den + k)


class SeatStats:
    __slots__ = (
        "hands", "vpip", "pfr", "three_bet", "three_bet_opp", "steal_faced", "fold_to_steal",
        "cbet", "cbet_opp", "fold_to_cbet", "fold_to_cbet_opp", "post_bets", "post_calls",
        "post_checks", "post_folds", "showdowns", "allins",
    )

    def __init__(self):
        for k in self.__slots__:
            setattr(self, k, 0)

    # --- shrunk rates --------------------------------------------------------
    def vpip_rate(self) -> float:
        return _rate(self.vpip, self.hands, PRIOR["vpip"])

    def pfr_rate(self) -> float:
        return _rate(self.pfr, self.hands, PRIOR["pfr"])

    def three_bet_rate(self) -> float:
        return _rate(self.three_bet, self.three_bet_opp, PRIOR["three_bet"])

    def fold_to_steal_rate(self) -> float:
        return _rate(self.fold_to_steal, self.steal_faced, PRIOR["fold_to_steal"])

    def cbet_rate(self) -> float:
        return _rate(self.cbet, self.cbet_opp, PRIOR["cbet"])

    def fold_to_cbet_rate(self) -> float:
        return _rate(self.fold_to_cbet, self.fold_to_cbet_opp, PRIOR["fold_to_cbet"])

    def aggression(self) -> float:
        """Postflop (bets + raises) / (bets + raises + calls + checks + folds), shrunk."""
        tot = self.post_bets + self.post_calls + self.post_checks + self.post_folds
        return _rate(self.post_bets, tot, PRIOR["agg"])

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__slots__}
        d.update(
            vpip_rate=round(self.vpip_rate(), 3), pfr_rate=round(self.pfr_rate(), 3),
            three_bet_rate=round(self.three_bet_rate(), 3), fold_to_steal_rate=round(self.fold_to_steal_rate(), 3),
            cbet_rate=round(self.cbet_rate(), 3), fold_to_cbet_rate=round(self.fold_to_cbet_rate(), 3),
            aggression=round(self.aggression(), 3),
        )
        return d


class OpponentTracker:
    def __init__(self, num_players: int = 8):
        self.n = num_players
        self.seats = [SeatStats() for _ in range(num_players)]
        self._hand = None
        self._idx = 0
        self._reset_hand_state()

    def _reset_hand_state(self):
        self._pre_raises = 0
        self._pre_callers = 0
        self._pre_raiser = None
        self._vpip_done: set[int] = set()
        self._pfr_done: set[int] = set()
        self._three_bet_opp_done: set[int] = set()
        self._steal_open = False
        self._steal_done: set[int] = set()
        self._flop_bet = False
        self._cbet_made = False
        self._cbet_opp_done = False
        self._fold_to_cbet_done: set[int] = set()
        self._street = 0
        self._order: list[int] = []

    # --- feeding -------------------------------------------------------------
    def start_hand(self, hand_number: int, order: list[int]) -> None:
        """``order``: live seats clockwise from the small blind (button last)."""
        self._hand = hand_number
        self._idx = 0
        self._reset_hand_state()
        self._order = order
        for s in order:
            self.seats[s].hands += 1

    def observe(self, obs: Observation) -> None:
        if obs.hand_number != self._hand:
            n = obs.num_players
            dealt = [s for s in range(n) if obs.stacks[s] + obs.committed[s] > 0]
            order = []
            if len(dealt) == 2:
                order = [obs.button, next(x for x in dealt if x != obs.button)]
            else:
                s = obs.button
                for _ in range(len(dealt)):
                    s = (s + 1) % n
                    while s not in dealt:
                        s = (s + 1) % n
                    order.append(s)
            self.start_hand(obs.hand_number, order)
        hist = obs.history
        for i in range(self._idx, len(hist)):
            st, seat, kind, amount = hist[i]
            self._action(st, seat, kind, amount)
        self._idx = len(hist)

    def ingest_record(self, rec: dict) -> None:
        """Feed a complete ``HandRecord.to_dict()``."""
        from .engine import STREET_NAMES

        n = self.n
        live = [s for s in range(n) if rec["start_stacks"][s] > 0]
        order = []
        s = rec["button"]
        if len(live) == 2:
            order = [rec["button"], next(x for x in live if x != rec["button"])]
        else:
            for _ in range(len(live)):
                s = (s + 1) % n
                while s not in live:
                    s = (s + 1) % n
                order.append(s)
        self.start_hand(rec["hand"], order)
        kinds = {"fold": _FOLD, "check": _CHECK, "call": _CALL, "raise": _RAISE}
        for st_name, seat, kind, amount in rec["actions"]:
            self._action(STREET_NAMES.index(st_name), seat, kinds[kind], amount)
        for amt, eligible, winners in rec["pots"]:
            if len(eligible) > 1 and rec.get("board") and len(rec["board"]) == 5:
                for s in eligible:
                    self.seats[s].showdowns += 1
                break

    # --- core ----------------------------------------------------------------
    def _action(self, st: int, seat: int, kind: int, amount: int) -> None:
        ss = self.seats[seat]
        order = self._order
        if st == 0:
            facing = self._pre_raises
            if kind in (_CALL, _RAISE) and seat not in self._vpip_done:
                self._vpip_done.add(seat)
                ss.vpip += 1
            if facing == 1 and seat not in self._three_bet_opp_done and self._pre_raiser != seat:
                self._three_bet_opp_done.add(seat)
                ss.three_bet_opp += 1
                if kind == _RAISE:
                    ss.three_bet += 1
            if self._steal_open and facing == 1 and seat in order[:2] and seat not in self._steal_done:
                self._steal_done.add(seat)
                ss.steal_faced += 1
                if kind == _FOLD:
                    ss.fold_to_steal += 1
            if kind == _RAISE:
                if seat not in self._pfr_done:
                    self._pfr_done.add(seat)
                    ss.pfr += 1
                if facing == 0 and self._pre_callers == 0 and len(order) >= 3:
                    late = order[-2:] + order[:1]  # CO, BTN, SB
                    self._steal_open = seat in late
                self._pre_raises += 1
                self._pre_raiser = seat
            elif kind == _CALL:
                self._pre_callers += 1
            return
        # postflop
        if st != self._street:
            self._street = st
        if kind == _RAISE:
            ss.post_bets += 1
        elif kind == _CALL:
            ss.post_calls += 1
        elif kind == _CHECK:
            ss.post_checks += 1
        else:
            ss.post_folds += 1
        if st == 1:
            if not self._flop_bet:
                if seat == self._pre_raiser and not self._cbet_opp_done:
                    self._cbet_opp_done = True
                    ss.cbet_opp += 1
                    if kind == _RAISE:
                        ss.cbet += 1
                        self._cbet_made = True
                if kind == _RAISE:
                    self._flop_bet = True
            elif self._cbet_made and seat != self._pre_raiser and seat not in self._fold_to_cbet_done:
                self._fold_to_cbet_done.add(seat)
                ss.fold_to_cbet_opp += 1
                if kind == _FOLD:
                    ss.fold_to_cbet += 1

    # --- queries -------------------------------------------------------------
    def profile(self, seat: int) -> SeatStats:
        return self.seats[seat]

    def to_dict(self) -> dict:
        return {s: self.seats[s].to_dict() for s in range(self.n)}
