"""A basic position-aware heuristic bot (fixture quality, not a strong player).

Preflop: Chen-formula hand score with position-dependent thresholds.
Postflop: made-hand category from the evaluator plus simple pot odds.
Uses only standard-ranking strength categories; it is deliberately unaware
of variants so that variant tests can show behaviour differences.
"""
from __future__ import annotations

import random

from ..agent import CALL, CHECK, FOLD, Action, Observation, TableInfo, raise_to
from ..evaluator import (
    FLUSH, FULL_HOUSE, PAIR, QUADS, STRAIGHT, STRAIGHT_FLUSH, TRIPS, TWO_PAIR,
    STANDARD_EVALUATOR,
)

_CHEN_HIGH = {12: 10.0, 11: 8.0, 10: 7.0, 9: 6.0}


def chen_score(c1: int, c2: int) -> float:
    r1, r2 = c1 >> 2, c2 >> 2
    if r1 < r2:
        r1, r2 = r2, r1
    hi = _CHEN_HIGH.get(r1, (r1 + 2) / 2.0)
    if r1 == r2:
        return max(5.0, hi * 2)
    score = hi
    if (c1 & 3) == (c2 & 3):
        score += 2
    gap = r1 - r2 - 1
    score -= (0, 1, 2, 4)[gap] if gap <= 3 else 5
    if gap <= 1 and r1 < 10:
        score += 1
    return score


class HeuristicBot:
    name = "heuristic"

    def __init__(self, aggression: float = 1.0):
        self.aggression = aggression
        self.rng = random.Random(0)

    def reset(self, table: TableInfo) -> None:
        self.rng = random.Random(table.seed)
        self.seat = table.seat

    # --- helpers --------------------------------------------------------------
    @staticmethod
    def _position_bucket(obs: Observation) -> int:
        """0 = early, 1 = middle, 2 = late/button, 3 = blinds."""
        n = obs.num_players
        live = [s for s in range(n) if obs.stacks[s] > 0 or obs.in_hand[s]]
        k = len(live)
        # seats after the button in order
        order = []
        s = obs.button
        for _ in range(k):
            s = (s + 1) % n
            while s not in live:
                s = (s + 1) % n
            order.append(s)
        if k == 2:
            return 2 if obs.seat == obs.button else 3
        idx = order.index(obs.seat)  # 0 = SB, 1 = BB, k-1 = button
        if idx <= 1:
            return 3
        rel = (idx - 2) / max(1, k - 3)  # 0 = UTG ... 1 = button
        return 0 if rel < 0.34 else (1 if rel < 0.67 else 2)

    def _raise_amount(self, obs: Observation, pot_frac: float) -> Action:
        target = obs.bets[obs.seat] + obs.to_call + int(obs.pot * pot_frac)
        target = max(obs.min_raise_to, min(obs.max_raise_to, target))
        return raise_to(target)

    # --- policy ---------------------------------------------------------------
    def act(self, obs: Observation) -> Action:
        if obs.street == 0:
            return self._preflop(obs)
        return self._postflop(obs)

    def _preflop(self, obs: Observation) -> Action:
        c1, c2 = obs.hole_cards
        score = chen_score(c1, c2)
        bucket = self._position_bucket(obs)
        open_threshold = (9.0, 8.0, 6.5, 7.5)[bucket]
        facing_raise = obs.to_call > obs.big_blind
        stack_bb = (obs.stacks[obs.seat] + obs.bets[obs.seat]) / obs.big_blind
        if facing_raise:
            if score >= 11 and obs.can_raise:
                return self._raise_amount(obs, 1.0)
            if score >= 8.5 or (stack_bb < 12 and score >= 7.5 and obs.can_raise):
                if stack_bb < 12 and obs.can_raise:
                    return raise_to(obs.max_raise_to)
                return CALL
            return CHECK if obs.can_check else FOLD
        if score >= open_threshold and obs.can_raise:
            if stack_bb < 10:
                return raise_to(obs.max_raise_to)
            return self._raise_amount(obs, 0.75)
        if obs.can_check:
            return CHECK
        # limp cheaply from the blinds with playable hands
        if bucket == 3 and score >= 5.5 and obs.to_call <= obs.big_blind:
            return CALL
        return FOLD

    def _postflop(self, obs: Observation) -> Action:
        value = STANDARD_EVALUATOR.evaluate(obs.hole_cards + obs.board)
        cat = STANDARD_EVALUATOR.category(value)
        board_value = STANDARD_EVALUATOR.evaluate(obs.board) if len(obs.board) >= 5 else None
        if board_value is not None and value == board_value:
            cat = -1  # playing the board
        pot = obs.pot
        to_call = obs.to_call
        strong = cat >= TWO_PAIR
        medium = cat == PAIR
        if strong:
            if obs.can_raise:
                return self._raise_amount(obs, 0.7 * self.aggression)
            return CALL if not obs.can_check else CHECK
        if obs.can_check:
            if medium and obs.can_raise and self.rng.random() < 0.3:
                return self._raise_amount(obs, 0.5)
            return CHECK
        odds = to_call / max(1, pot + to_call)
        if medium and odds < 0.34:
            return CALL
        if cat == -1 and odds < 0.15:  # playing the board: cheap call
            return CALL
        return FOLD
