"""FAKE starter kit for the wiring drill. NOT the official kit.

This is a deliberately different bot interface so we can rehearse the one
job that must happen fast on tournament day: adapting our strategy to an
interface we have never seen. Everything here is invented and labelled FAKE:
method names, dict keys, card spelling, action strings, raise semantics.

Interface a FAKE kit bot must implement
---------------------------------------
    class PokerBot:
        def new_table(self, config: dict) -> None
            config = {"seat_id": int, "n_seats": int, "chips": int,
                      "blind_schedule": [[sb, bb], ...], "payouts": [...], "rng_seed": int}
        def new_hand(self, hand: dict) -> None
            hand = {"hand_id": int, "dealer": int, "cards": ["AS", "KD"], "blinds": [sb, bb]}
        def decide(self, state: dict, options: list[str]) -> str

    state = {
        "street": "PREFLOP" | "FLOP" | "TURN" | "RIVER",
        "community": ["7H", "8S", "2C"],          # uppercase suits, T for ten
        "pot": int,                               # everything committed this hand so far
        "my_id": int,
        "players": [{"id": i, "chips": int, "wager": int, "paid": int,
                     "status": "active" | "folded" | "allin" | "out"}, ...],
        "to_call": int,
        "raise_by_min": int,                      # RAISE amounts are ON TOP OF the call
        "raise_by_max": int,
        "log": [{"st": "FLOP", "who": 3, "move": "RAISE", "amt": 60}, ...],  # this hand, all streets
        "hand_id": int,
    }
    options is a subset of ["FOLD", "CHECK", "CALL", "BET", "RAISE", "ALLIN"].
    Return one of: "FOLD", "CHECK", "CALL", "BET <by>", "RAISE <by>", "ALLIN".
    Anything else (or an exception) is treated like the organizer's rule 3.7:
    CHECK if possible, else FOLD.

``play_table(bots, seed)`` runs one eight-seat table through this interface
(the engine underneath is pokergym's, which is what makes the drill
checkable: a lossless adapter reproduces the engine's record hash).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokergym.agent import CALL, CHECK, FOLD, Action, ActionType, Observation, TableInfo, raise_to  # noqa: E402
from pokergym.cards import card_str  # noqa: E402
from pokergym.rules import BASELINE_RULES, GameRules  # noqa: E402
from pokergym.tournament import run_tournament  # noqa: E402

STREETS = ("PREFLOP", "FLOP", "TURN", "RIVER")
WORDS = ("FOLD", "CHECK", "CALL", "RAISE")


def fake_card(c: int) -> str:
    return card_str(c).upper()


class _EngineSide:
    """Hosts a FAKE-kit bot inside pokergym's engine (what the real kit's
    simulator would do with a participant's bot)."""

    def __init__(self, bot, rules: GameRules):
        self.bot = bot
        self.rules = rules
        self.hand = None
        self.errors = 0

    def reset(self, t: TableInfo) -> None:
        self.hand = None
        self.bot.new_table({
            "seat_id": t.seat, "n_seats": t.num_players, "chips": t.starting_stack,
            "blind_schedule": [list(l) for l in self.rules.blinds.levels],
            "payouts": list(self.rules.payouts.points),
            "rng_seed": t.seed,
        })

    def act(self, o: Observation) -> Action:
        if o.hand_number != self.hand:
            self.hand = o.hand_number
            self.bot.new_hand({"hand_id": o.hand_number, "dealer": o.button,
                               "cards": [fake_card(c) for c in o.hole_cards], "blinds": [o.small_blind, o.big_blind]})
        players = []
        for s in range(o.num_players):
            if o.stacks[s] + o.committed[s] == 0:
                status = "out"
            elif not o.in_hand[s]:
                status = "folded"
            elif o.all_in[s]:
                status = "allin"
            else:
                status = "active"
            players.append({"id": s, "chips": o.stacks[s], "wager": o.bets[s], "paid": o.committed[s], "status": status})
        current = max(o.bets)
        options = ["FOLD"]
        options.append("CHECK" if o.can_check else "CALL")
        if o.can_raise:
            options.append("BET" if current == 0 else "RAISE")
            options.append("ALLIN")
        state = {
            "street": STREETS[o.street], "community": [fake_card(c) for c in o.board], "pot": o.pot, "my_id": o.seat,
            "players": players, "to_call": o.to_call,
            "raise_by_min": (o.min_raise_to - o.bets[o.seat] - o.to_call) if o.can_raise else 0,
            "raise_by_max": (o.max_raise_to - o.bets[o.seat] - o.to_call) if o.can_raise else 0,
            "log": [{"st": STREETS[st], "who": seat, "move": WORDS[k], "amt": amt} for (st, seat, k, amt) in o.history],
            "hand_id": o.hand_number,
        }
        try:
            text = self.bot.decide(state, options)
            return self._parse(text, o, current)
        except Exception:  # noqa: BLE001
            self.errors += 1
            return CHECK if o.can_check else FOLD

    @staticmethod
    def _parse(text: str, o: Observation, current: int) -> Action:
        parts = str(text).strip().upper().split()
        if not parts:
            raise ValueError("empty")
        w = parts[0]
        if w == "FOLD":
            return FOLD
        if w == "CHECK":
            return CHECK
        if w == "CALL":
            return CALL
        if w == "ALLIN":
            return raise_to(o.max_raise_to) if o.can_raise else CALL
        if w in ("BET", "RAISE"):
            by = int(parts[1])
            return raise_to(o.bets[o.seat] + o.to_call + by)
        raise ValueError(text)


def play_table(bots, seed: int, rules: GameRules = BASELINE_RULES, keep_hands: bool = True):
    """Run one table of FAKE-kit bots. Returns pokergym's TournamentResult
    plus ``fake_errors`` (exceptions/unparseable replies per seat)."""
    sides = [_EngineSide(b, rules) for b in bots]
    res = run_tournament(sides, rules, seed=seed, keep_hands=keep_hands)
    res.fake_errors = [s.errors for s in sides]  # type: ignore[attr-defined]
    return res


class AlwaysCheckBot:
    """Minimal legal FAKE-kit bot (the kind of thing a template ships with)."""

    def new_table(self, config):
        pass

    def new_hand(self, hand):
        pass

    def decide(self, state, options):
        return "CHECK" if "CHECK" in options else "FOLD"


_ = ActionType  # re-exported for adapters that want the enum
