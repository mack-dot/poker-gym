import random

import pytest

from pokergym.agent import AgentAdapter
from pokergym.engine import play_hand
from pokergym.rules import BASELINE_RULES


def play_scripted(agents, stacks, button, deck, rules=BASELINE_RULES, hand_number=0):
    """Play one hand with raw agents (wrapped in adapters, timing off)."""
    adapters = [AgentAdapter(a, mode="off") for a in agents]
    from pokergym.agent import TableInfo

    for s, ad in enumerate(adapters):
        ad.reset(TableInfo(seat=s, num_players=len(stacks), starting_stack=stacks[s], rules_name=rules.name, seed=s))
    ev = rules.ranking.evaluator()
    rec = play_hand(rules, ev, stacks, button, hand_number, adapters, random.Random(0), deck=deck)
    return rec, adapters


@pytest.fixture
def scripted():
    return play_scripted
