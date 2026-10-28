"""Drill starting point. Copy this file, fill the TODOs, then run:

    python drills/fake_kit/run_drill.py my_adapter.py:Adapted

Do not open reference_adapter.py until you have a PASS or you are out of time.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokergym.agent import ActionType  # noqa: E402
from pokergym.bridge import build_observation, build_table_info  # noqa: E402,F401
from pokergym.bots import TagBot  # noqa: E402


def to_observation(state: dict, hand: dict):
    # TODO: translate the FAKE kit's state + hand dicts into build_observation(...) kwargs.
    # Read fakekit.py's docstring for the field meanings. Watch for:
    #   - card spelling, - raise-by vs raise-to, - who is 'out' vs 'folded', - history streets.
    raise NotImplementedError


def to_text(action, state: dict) -> str:
    # TODO: translate our Action (kind, amount=bet-to) into the FAKE kit's reply string.
    if action.kind == ActionType.FOLD:
        return "FOLD"
    raise NotImplementedError


class Adapted:
    inner_cls = TagBot

    def __init__(self, inner=None):
        self.inner = inner or self.inner_cls()
        self.hand = None

    def new_table(self, config):
        # TODO: call self.inner.reset(build_table_info(...)) from config
        raise NotImplementedError

    def new_hand(self, hand):
        self.hand = hand

    def decide(self, state, options):
        return to_text(self.inner.act(to_observation(state, self.hand)), state)
