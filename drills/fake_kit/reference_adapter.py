"""Reference solution to the wiring drill: our bot inside the FAKE kit.

Written against ``fakekit.py`` only. Two translation functions and a shell
class; ``pokergym.bridge.build_observation`` does the heavy lifting. This is
the shape of what we will write on tournament day, with the official kit's
names substituted.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokergym.agent import ActionType  # noqa: E402
from pokergym.bridge import build_observation, build_table_info  # noqa: E402
from pokergym.bots import TagBot  # noqa: E402

_STREET = {"PREFLOP": 0, "FLOP": 1, "TURN": 2, "RIVER": 3}
_KIND = {"FOLD": 0, "CHECK": 1, "CALL": 2, "RAISE": 3, "BET": 3, "ALLIN": 3}


def to_observation(state: dict, hand: dict):
    me = state["my_id"]
    players = sorted(state["players"], key=lambda p: p["id"])
    can_raise = state["raise_by_max"] > 0
    bets = [p["wager"] for p in players]
    to_call = state["to_call"]
    base = bets[me] + to_call
    cur = _STREET[state["street"]]
    log = [(_STREET[e["st"]], e["who"], _KIND[e["move"]], e["amt"]) for e in state["log"]]
    return build_observation(
        seat=me, button=hand["dealer"],
        hole_cards=_fix_cards(hand["cards"]),
        board=_fix_cards(state["community"]),
        stacks=[p["chips"] for p in players], bets=bets, committed=[p["paid"] for p in players],
        in_hand=[p["status"] in ("active", "allin") for p in players],
        all_in=[p["status"] == "allin" for p in players],
        big_blind=hand["blinds"][1], small_blind=hand["blinds"][0],
        hand_number=hand["hand_id"], street=cur, pot=state["pot"], to_call=to_call,
        can_check=to_call == 0, can_raise=can_raise,
        min_raise_to=base + state["raise_by_min"] if can_raise else 0,
        max_raise_to=base + state["raise_by_max"] if can_raise else 0,
        history=log,
    )


def _fix_cards(cards):
    # FAKE kit: "AS", "TD" -> our parser wants "As", "Td"
    return [c[0] + c[1].lower() for c in cards]


def to_text(action, state: dict) -> str:
    k = action.kind
    if k == ActionType.FOLD:
        return "FOLD"
    if k == ActionType.CHECK:
        return "CHECK"
    if k == ActionType.CALL:
        return "CALL"
    me = state["my_id"]
    wager = next(p["wager"] for p in state["players"] if p["id"] == me)
    by = action.amount - wager - state["to_call"]
    if by >= state["raise_by_max"]:
        return "ALLIN"
    return ("BET " if max(p["wager"] for p in state["players"]) == 0 else "RAISE ") + str(by)


class Adapted:
    """FAKE-kit PokerBot hosting one of our bots."""

    inner_cls = TagBot

    def __init__(self, inner=None):
        self.inner = inner or self.inner_cls()
        self.hand = None

    def new_table(self, config):
        self.inner.reset(build_table_info(seat=config["seat_id"], num_players=config["n_seats"],
                                          starting_stack=config["chips"], seed=config.get("rng_seed", 0)))

    def new_hand(self, hand):
        self.hand = hand

    def decide(self, state, options):
        obs = to_observation(state, self.hand)
        return to_text(self.inner.act(obs), state)
