"""Starter bot for practice sessions in the gym.

Copy this file, edit ``act``, then measure:

    python -m pokergym.cli eval --bot examples/my_bot.py:MyBot --vs sparring --tables 2000 --workers 8 --baseline tag

Everything the bot may use at decision time is in ``obs`` (see
``pokergym.agent.Observation``). Helpers that stay far below the 1 ms budget:

    pokergym.equity.hand_percentile(c1, c2)        preflop strength, 0 = best, 1 = worst (table lookup)
    pokergym.equity.preflop_equity(c1, c2, n_opp)   equity vs n random hands (table lookup)
    pokergym.equity.equity_vs_top(c1, c2, frac)     HU equity vs a top-frac% range (table lookup)
    pokergym.bots.features.hand_features(hole, board)   made hand / draws / outs / texture
    pokergym.bots.features.table_position(obs)          position, players behind, blinds
    pokergym.stats.OpponentTracker                      VPIP / PFR / 3-bet / fold-to-steal / c-bet

This is the REHEARSAL interface. The official starter kit's Agent interface
is unknown; keep the strategy in plain functions of simple inputs so it can
be re-wired through ``pokergym.adapters`` later.
"""
from __future__ import annotations

import random

from pokergym.agent import CALL, CHECK, FOLD, Action, Observation, TableInfo, raise_to
from pokergym.bots import features as F
from pokergym.equity import equity_vs_top, hand_percentile
from pokergym.stats import OpponentTracker


class MyBot:
    name = "mybot"

    def reset(self, table: TableInfo) -> None:
        # Called when seated. State resets per table (rule 3.8).
        self.rng = random.Random(table.seed)
        self.seat = table.seat
        self.tracker = OpponentTracker(table.num_players)

    def act(self, obs: Observation) -> Action:
        self.tracker.observe(obs)
        if obs.street == 0:
            return self.preflop(obs)
        return self.postflop(obs)

    # --- preflop: open by position, shove when short, call shoves on equity ---
    def preflop(self, obs: Observation) -> Action:
        c1, c2 = obs.hole_cards
        p = hand_percentile(c1, c2)          # 0.0045 = AA ... 1.0 = 72o
        pos = F.table_position(obs)
        eff_bb = F.effective_stack_bb(obs)
        raises = F.street_raises(obs)
        bb = obs.big_blind

        if raises == 0:
            if pos.is_bb and obs.can_check:
                return CHECK
            open_width = (0.12, 0.17, 0.28, 0.32, 0.0)[pos.bucket]
            if eff_bb <= 12:
                return self._shove(obs) if p <= open_width * 1.8 else self._fold_or_check(obs)
            if p <= open_width and obs.can_raise:
                return self._raise_to(obs, int(2.5 * bb))
            return self._fold_or_check(obs)

        # Facing a raise.
        if obs.to_call >= 0.4 * obs.stacks[obs.seat]:
            need = F.pot_odds(obs) + 0.05
            return CALL if equity_vs_top(c1, c2, 0.15) >= need else self._fold_or_check(obs)
        if p <= 0.05 and obs.can_raise:
            return self._raise_to(obs, 3 * (obs.to_call + obs.bets[obs.seat]))
        if p <= 0.15 and obs.to_call <= 0.15 * obs.stacks[obs.seat]:
            return CALL
        return self._fold_or_check(obs)

    # --- postflop: made-hand class + draws against pot odds -------------------
    def postflop(self, obs: Observation) -> Action:
        f = F.hand_features(obs.hole_cards, obs.board)
        strong = f.made >= F.MADE_TOP_PAIR
        draw = f.outs >= 8 and obs.street < 3
        if obs.can_check:
            if strong or (draw and self.rng.random() < 0.5):
                return self._bet_frac(obs, 0.6)
            return CHECK
        odds = F.pot_odds(obs)
        if f.made >= F.MADE_TWO_PAIR_PLUS:
            return self._bet_frac(obs, 1.0) if obs.can_raise else CALL
        if strong:
            return CALL
        if draw and F.draw_equity(f, obs.street) >= odds:
            return CALL
        return FOLD

    # --- helpers ---------------------------------------------------------------
    def _raise_to(self, obs: Observation, target: int) -> Action:
        if not obs.can_raise:
            return CALL if not obs.can_check else CHECK
        return raise_to(max(obs.min_raise_to, min(obs.max_raise_to, target)))

    def _bet_frac(self, obs: Observation, frac: float) -> Action:
        return self._raise_to(obs, obs.bets[obs.seat] + obs.to_call + int((obs.pot + obs.to_call) * frac))

    def _shove(self, obs: Observation) -> Action:
        return raise_to(obs.max_raise_to) if obs.can_raise else (CALL if not obs.can_check else CHECK)

    @staticmethod
    def _fold_or_check(obs: Observation) -> Action:
        return CHECK if obs.can_check else FOLD
