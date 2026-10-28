"""Sparring partners: hand-built, table-driven bots that play recognisable
styles well enough to punish simple mistakes.

They are heuristics, not solutions. Nothing here is an optimizer or a solver.
Every decision is table lookups plus a handful of comparisons so that each
call stays far below the 1 ms deadline.

Styles (``BOT_REGISTRY`` names):
  tag         tight-aggressive: narrow opens, 3-bets premiums, c-bets, value bets
  lag         loose-aggressive: wide opens, more 3-bets and bluffs, bigger sizes
  shortstack  push/fold specialist when short; tight otherwise
  icm         tag with an ICM risk premium near the bubble and the hand cap
  adaptive    tag that reads opponents (steals vs folders, value-bets stations)

Preflop hand strength is a percentile from ``equity.hand_percentile`` (lower
is stronger). All-in calls use the HU vs-range table in ``equity``.
"""
from __future__ import annotations

import random

from ..agent import CALL, CHECK, FOLD, Action, Observation, TableInfo, raise_to
from ..equity import equity_vs_top, hand_percentile, preflop_equity
from ..evaluator import Evaluator, STANDARD_EVALUATOR
from ..icm import icm_equity_for
from ..rules import SYNTHETIC_PAYOUTS
from ..stats import OpponentTracker
from . import features as F

HAND_CAP = 200  # confirmed rule 4.4

# Rough approximation of unexploitable push widths by players left to act
# (behind). ``push_width(eff_bb, behind)`` = fraction of hands to shove.
_PUSH_C = {1: 0.60, 2: 0.42, 3: 0.32, 4: 0.26, 5: 0.22, 6: 0.19, 7: 0.17}


def push_width(eff_bb: float, behind: int) -> float:
    c = _PUSH_C.get(max(1, min(7, behind)), 0.17)
    eff_bb = max(1.0, eff_bb)
    return min(1.0, c * (10.0 / eff_bb) ** 0.6)


class Profile:
    """Style knobs. Percentiles are "top X of hands" (0..1)."""

    __slots__ = (
        "open_pct", "iso_pct", "threebet_pct", "call_open_pct", "bb_defend_pct", "fourbet_pct",
        "call_3bet_pct", "shove_bb", "reshove_pct", "call_shove_margin", "cbet_freq", "semi_bluff_freq",
        "bluff_freq", "bet_frac", "slowplay_freq", "call_margin", "open_size_bb", "steal_bonus",
    )

    def __init__(self, **kw):
        # defaults = tag
        self.open_pct = (0.11, 0.16, 0.27, 0.30, 0.0)   # early, middle, late, SB, BB
        self.iso_pct = 0.12
        self.threebet_pct = 0.045
        self.call_open_pct = 0.13
        self.bb_defend_pct = 0.30
        self.fourbet_pct = 0.025
        self.call_3bet_pct = 0.06
        self.shove_bb = 11.0
        self.reshove_pct = 0.09
        self.call_shove_margin = 0.06
        self.cbet_freq = 0.65
        self.semi_bluff_freq = 0.55
        self.bluff_freq = 0.18
        self.bet_frac = 0.6
        self.slowplay_freq = 0.12
        self.call_margin = 0.04
        self.open_size_bb = 2.5
        self.steal_bonus = 1.0
        for k, v in kw.items():
            setattr(self, k, v)


TAG = Profile()
LAG = Profile(
    open_pct=(0.20, 0.27, 0.42, 0.42, 0.0), iso_pct=0.22, threebet_pct=0.09, call_open_pct=0.20,
    bb_defend_pct=0.45, fourbet_pct=0.04, call_3bet_pct=0.10, reshove_pct=0.14, call_shove_margin=0.03,
    cbet_freq=0.85, semi_bluff_freq=0.8, bluff_freq=0.35, bet_frac=0.75, slowplay_freq=0.05,
    call_margin=0.0, open_size_bb=3.0,
)
NIT = Profile(
    open_pct=(0.07, 0.10, 0.17, 0.20, 0.0), iso_pct=0.08, threebet_pct=0.03, call_open_pct=0.08,
    bb_defend_pct=0.20, cbet_freq=0.5, semi_bluff_freq=0.3, bluff_freq=0.05, call_margin=0.08,
    call_shove_margin=0.09,
)

_MADE_EQ = {
    F.MADE_NONE: 0.12, F.MADE_WEAK_PAIR: 0.32, F.MADE_MID_PAIR: 0.45, F.MADE_TOP_PAIR: 0.58,
    F.MADE_OVERPAIR: 0.68, F.MADE_TWO_PAIR_PLUS: 0.84, F.MADE_NUTTISH: 0.93,
}


class SparringBot:
    name = "tag"
    profile: Profile = TAG
    use_icm = False
    use_tracker = False
    pushfold_only_when_short = False

    def __init__(self, profile: Profile | None = None, evaluator: Evaluator | None = None):
        if profile is not None:
            self.profile = profile
        self.evaluator = evaluator or STANDARD_EVALUATOR
        self.rng = random.Random(0)
        self.seat = 0
        self.tracker: OpponentTracker | None = None
        self._prem_cache = (-1, 0.0)

    def configure(self, rules) -> None:
        """REHEARSAL hook: the gym calls this with the ``GameRules`` in force so
        the bot can adopt the variant's hand ranking. The official kit will
        expose the variant some other way; this is where it gets wired."""
        self.evaluator = rules.ranking.evaluator()

    def reset(self, table: TableInfo) -> None:
        self.rng = random.Random(table.seed)
        self.seat = table.seat
        self.n = table.num_players
        self.tracker = OpponentTracker(table.num_players) if self.use_tracker else None
        self._prem_cache = (-1, 0.0)

    # ------------------------------------------------------------------ utils
    def _raise(self, obs: Observation, target: int) -> Action:
        if not obs.can_raise:
            return CALL if not obs.can_check else CHECK
        target = max(obs.min_raise_to, min(obs.max_raise_to, int(target)))
        return raise_to(target)

    def _shove(self, obs: Observation) -> Action:
        if obs.can_raise:
            return raise_to(obs.max_raise_to)
        return CALL if not obs.can_check else CHECK

    def _bet_pot_frac(self, obs: Observation, frac: float) -> Action:
        target = obs.bets[obs.seat] + obs.to_call + int((obs.pot + obs.to_call) * frac)
        return self._raise(obs, target)

    @staticmethod
    def _fold_or_check(obs: Observation) -> Action:
        return CHECK if obs.can_check else FOLD

    def _risk_premium(self, obs: Observation) -> float:
        """Extra equity required for a stack-risking call (ICM pressure).

        Depends only on start-of-hand stacks and the hand number, so it is
        computed once per hand and cached (the ICM recursion is the most
        expensive thing any sparring bot does)."""
        if not self.use_icm:
            return 0.0
        cached = self._prem_cache
        if cached[0] == obs.hand_number:
            return cached[1]
        prem = self._compute_risk_premium(obs)
        self._prem_cache = (obs.hand_number, prem)
        return prem

    def _compute_risk_premium(self, obs: Observation) -> float:
        live = [s for s in range(obs.num_players) if obs.stacks[s] + obs.committed[s] > 0]
        k = len(live)
        hands_left = HAND_CAP - obs.hand_number
        prem = 0.0
        if k <= 5:
            # Exact ICM for small fields: equity now vs equity after busting.
            # Payouts: the bot does not receive the schedule through TableInfo
            # (the official kit will ship one); the SYNTHETIC default is used.
            pay = SYNTHETIC_PAYOUTS.points
            remaining_pay = list(pay[:k])
            stacks = [obs.stacks[s] + obs.committed[s] for s in live]
            me = live.index(obs.seat)
            eq_now = icm_equity_for(stacks, remaining_pay, me)
            eq_bust = remaining_pay[-1]  # k-th place
            total = sum(remaining_pay)
            # share of equity at risk relative to the chip share
            chip_share = stacks[me] / max(1.0, sum(stacks))
            icm_share = (eq_now - eq_bust) / max(1e-9, total)
            prem = max(0.0, (icm_share - chip_share) * 1.5)
        if hands_left <= 40:
            # Close to the cap, survival with chips is worth more than variance.
            prem += 0.04 * (1 - hands_left / 40.0)
        return min(0.18, prem)

    # ------------------------------------------------------------------ act
    def act(self, obs: Observation) -> Action:
        if self.tracker is not None:
            self.tracker.observe(obs)
        if obs.street == 0:
            return self._preflop(obs)
        return self._postflop(obs)

    # ------------------------------------------------------------------ preflop
    def _preflop(self, obs: Observation) -> Action:
        P = self.profile
        c1, c2 = obs.hole_cards
        p = hand_percentile(c1, c2)
        pos = F.table_position(obs)
        eff = F.effective_stack_bb(obs)
        my_bb = F.stack_bb(obs)
        raises = F.street_raises(obs)
        callers = sum(1 for (s, seat, k, a) in obs.history if s == 0 and k == 2)
        opp_in = F.opponents_in_hand(obs)
        bb = obs.big_blind

        if raises == 0:
            # Nobody has raised. BB with limpers may isolate; otherwise open/limp/fold.
            if pos.is_bb and obs.can_check:
                if callers and p <= P.iso_pct and obs.can_raise:
                    return self._raise(obs, bb * (P.open_size_bb + callers))
                return CHECK
            thr = P.open_pct[min(pos.bucket, 3)] if pos.bucket != 4 else P.open_pct[3]
            if pos.players == 2:
                thr = min(1.0, thr * 2.6)
            elif pos.players == 3:
                thr = min(1.0, thr * 1.4)
            thr *= 0.85 ** callers
            thr *= self._steal_adjust(obs, pos)
            if my_bb <= P.shove_bb or (eff <= P.shove_bb and pos.bucket >= 2):
                width = push_width(eff, pos.behind) * (0.75 if callers else 1.0)
                width *= 1.0 - self._risk_premium(obs) * 2
                if p <= width:
                    return self._shove(obs)
                return self._fold_or_check(obs)
            if p <= thr and obs.can_raise:
                size = bb * P.open_size_bb + bb * callers
                if size >= 0.45 * (obs.stacks[obs.seat] + obs.bets[obs.seat]):
                    return self._shove(obs)
                return self._raise(obs, size)
            if pos.is_sb and callers and p <= thr * 1.6 and obs.to_call <= bb:
                return CALL  # complete behind limpers
            return self._fold_or_check(obs)

        prem = self._risk_premium(obs)
        pot_odds = F.pot_odds(obs)
        big_bet = obs.to_call >= 0.4 * obs.stacks[obs.seat]
        facing_allin = big_bet or (
            obs.to_call >= 8 * bb
            and any(obs.all_in[s] for s in range(obs.num_players) if s != obs.seat and obs.in_hand[s])
        )

        if raises == 1:
            opener = F.preflop_raiser(obs)
            opener_width = self._opener_width(obs, opener)
            if facing_allin or big_bet:
                return self._call_shove_decision(obs, c1, c2, opener_width, prem, P.call_shove_margin)
            if my_bb <= P.shove_bb + 3:
                width = P.reshove_pct * (1 + 0.5 * (opener_width > 0.3)) * (1 - prem * 2)
                if p <= width:
                    return self._shove(obs)
                if pos.is_bb and obs.to_call <= 2.5 * bb and p <= P.bb_defend_pct * 0.7:
                    return CALL
                return self._fold_or_check(obs)
            threebet = P.threebet_pct * (1.6 if opener_width > 0.3 else 1.0) * (1 - prem)
            if p <= threebet and obs.can_raise:
                target = obs.bets[opener] * 3 + bb * callers
                if pos.bucket >= 3:
                    target = int(target * 1.2)  # out of position: bigger
                if target >= 0.4 * (obs.stacks[obs.seat] + obs.bets[obs.seat]):
                    return self._shove(obs)
                return self._raise(obs, target)
            call_pct = P.call_open_pct * (0.8 ** callers)
            if pos.is_bb:
                call_pct = P.bb_defend_pct * (bb * 2.5 / max(obs.to_call, 1)) ** 0.5
            call_pct *= 1 - prem
            if p <= call_pct and obs.to_call <= 0.2 * (obs.stacks[obs.seat] + obs.bets[obs.seat]):
                return CALL
            return self._fold_or_check(obs)

        # Facing a 3-bet or more.
        if facing_allin or big_bet:
            return self._call_shove_decision(obs, c1, c2, 0.08, prem, P.call_shove_margin)
        if p <= P.fourbet_pct * (1 - prem):
            return self._shove(obs)
        if p <= P.call_3bet_pct * (1 - prem) and obs.to_call <= 0.25 * (obs.stacks[obs.seat] + obs.bets[obs.seat]):
            return CALL
        # Multiway all-in or very good odds: use random-hand equity.
        if pot_odds < 0.2 and preflop_equity(c1, c2, max(1, opp_in)) >= pot_odds + 0.1 + prem:
            return CALL
        return self._fold_or_check(obs)

    def _opener_width(self, obs: Observation, opener: int | None) -> float:
        """Estimated open range width of the preflop raiser."""
        if opener is None:
            return 0.2
        if self.tracker is not None:
            prof = self.tracker.profile(opener)
            if prof.hands >= 8:
                return max(0.05, min(0.9, prof.pfr_rate() * 1.6))
        return 0.2

    def _steal_adjust(self, obs: Observation, pos: F.Position) -> float:
        """Widen late-position opens vs blinds that fold to steals (adaptive)."""
        if self.tracker is None or pos.bucket < 2 or pos.players < 3:
            return 1.0
        blinds = pos.order[:2]
        f = sum(self.tracker.profile(s).fold_to_steal_rate() for s in blinds) / 2
        return 1.0 + (f - 0.6) * 1.5 * self.profile.steal_bonus  # f=0.8 -> 1.3x, f=0.4 -> 0.7x

    def _call_shove_decision(self, obs: Observation, c1, c2, width: float, prem: float, margin: float) -> Action:
        """Call an all-in (or near all-in) bet if equity vs the assumed range beats the price."""
        # Count opponents who have real money in: a tiny all-in from a
        # short stack does not make this a "multiway" decision.
        threshold = obs.bets[obs.seat] + obs.to_call * 0.5
        opp_big = sum(1 for s in range(obs.num_players)
                      if s != obs.seat and obs.in_hand[s] and obs.bets[s] >= threshold)
        need = F.pot_odds(obs) + margin + prem
        if opp_big <= 1:
            eq = equity_vs_top(c1, c2, max(0.03, width))
        else:
            eq = preflop_equity(c1, c2, opp_big) * 0.9
        if eq >= need:
            if obs.can_raise and obs.to_call < obs.stacks[obs.seat] * 0.6 and eq >= need + 0.15:
                return self._shove(obs)
            return CALL
        return self._fold_or_check(obs)

    # ------------------------------------------------------------------ postflop
    def _postflop(self, obs: Observation) -> Action:
        P = self.profile
        rng = self.rng
        f = F.hand_features(obs.hole_cards, obs.board, self.evaluator)
        opp_in = F.opponents_in_hand(obs)
        pot = obs.pot
        stack = obs.stacks[obs.seat]
        spr = stack / max(1, pot)
        made = f.made
        draw_eq = F.draw_equity(f, obs.street)
        eq = _MADE_EQ[made] * (0.87 ** max(0, opp_in - 1)) + draw_eq * (1 - _MADE_EQ[made])
        if f.board_flush4 and f.category < F.FLUSH:
            eq *= 0.7
        if f.board_paired and made in (F.MADE_TOP_PAIR, F.MADE_OVERPAIR):
            eq *= 0.9
        prem = self._risk_premium(obs)
        monster = made >= F.MADE_TWO_PAIR_PLUS
        strong = made == F.MADE_OVERPAIR or (made == F.MADE_TOP_PAIR and f.kicker_good)
        medium = made in (F.MADE_TOP_PAIR, F.MADE_MID_PAIR)
        good_draw = f.outs >= 8 and obs.street < 3
        was_aggressor = F.last_aggressor(obs) == obs.seat or (obs.street == 1 and F.preflop_raiser(obs) == obs.seat)
        station = self._opponents_are_stations(obs)

        if obs.can_check:
            if monster:
                if rng.random() < P.slowplay_freq and obs.street < 3 and opp_in == 1:
                    return CHECK
                return self._bet_pot_frac(obs, P.bet_frac if spr > 1.5 else 1.0) if obs.can_raise else CHECK
            if strong:
                return self._bet_pot_frac(obs, P.bet_frac) if obs.can_raise else CHECK
            if medium and opp_in <= 2 and obs.can_raise and rng.random() < (0.7 if station else 0.5):
                return self._bet_pot_frac(obs, 0.5)
            if good_draw and obs.can_raise and rng.random() < P.semi_bluff_freq * (0.5 if station else 1.0):
                return self._bet_pot_frac(obs, P.bet_frac)
            if was_aggressor and opp_in <= 2 and obs.can_raise and obs.street == 1:
                if rng.random() < P.cbet_freq * (0.6 if station else 1.0) * (0.8 if f.board_straighty else 1.0):
                    return self._bet_pot_frac(obs, 0.55)
            if opp_in == 1 and obs.street >= 2 and obs.can_raise and not station and rng.random() < P.bluff_freq:
                return self._bet_pot_frac(obs, P.bet_frac)
            return CHECK

        # Facing a bet.
        odds = F.pot_odds(obs)
        allin_call = obs.to_call >= stack
        if monster:
            if obs.can_raise and (spr < 4 or rng.random() < 0.6):
                return self._shove(obs) if spr < 2.5 else self._bet_pot_frac(obs, 1.0)
            return CALL
        if strong:
            if allin_call or obs.to_call > pot:
                return CALL if eq >= odds + P.call_margin + prem else FOLD
            if obs.can_raise and spr < 3 and rng.random() < 0.4:
                return self._shove(obs) if spr < 1.5 else self._bet_pot_frac(obs, 1.0)
            return CALL
        if eq >= odds + P.call_margin + prem:
            if good_draw and obs.can_raise and not allin_call and rng.random() < P.semi_bluff_freq * 0.4:
                return self._bet_pot_frac(obs, 1.0)
            return CALL
        if good_draw and obs.street < 3 and obs.to_call <= 0.33 * pot and not allin_call:
            return CALL  # implied odds
        return FOLD

    def _opponents_are_stations(self, obs: Observation) -> bool:
        if self.tracker is None:
            return False
        rates = []
        for s in range(obs.num_players):
            if s != obs.seat and obs.in_hand[s]:
                pr = self.tracker.profile(s)
                if pr.hands >= 10:
                    rates.append(pr.fold_to_cbet_rate())
        return bool(rates) and (sum(rates) / len(rates)) < 0.3


class TagBot(SparringBot):
    name = "tag"
    profile = TAG


class LagBot(SparringBot):
    name = "lag"
    profile = LAG


class ShortStackBot(SparringBot):
    """Push/fold when the effective stack is short; a nit when deep."""

    name = "shortstack"
    profile = Profile(**{k: getattr(NIT, k) for k in Profile.__slots__})
    profile.shove_bb = 14.0
    profile.reshove_pct = 0.11


class IcmBot(SparringBot):
    name = "icm"
    profile = TAG
    use_icm = True


class AdaptiveBot(SparringBot):
    name = "adaptive"
    profile = TAG
    use_tracker = True
