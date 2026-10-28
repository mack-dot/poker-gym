"""The bridge must rebuild an engine Observation from plain values so exactly
that every bot makes the same decision from either."""
import random

import pytest

from pokergym.agent import Observation, TableInfo, raise_to, CALL, CHECK, FOLD
from pokergym.bots import BOT_REGISTRY, SPARRING_BOTS
from pokergym.bridge import action_from_text, action_to_text, build_observation
from pokergym.cards import card_str
from pokergym.rules import BASELINE_RULES
from pokergym.tournament import run_tournament


class Recorder:
    def __init__(self, bot):
        self.bot = bot
        self.seen = []

    def reset(self, t):
        self.bot.reset(t)

    def act(self, o):
        self.seen.append(o)
        return self.bot.act(o)


def _rebuild(o: Observation, with_bounds: bool) -> Observation:
    """Plain values only: card strings, lists of ints, text history."""
    kw = dict(
        seat=o.seat, button=o.button,
        hole_cards=[card_str(c) for c in o.hole_cards], board=[card_str(c) for c in o.board],
        stacks=list(o.stacks), bets=list(o.bets), committed=list(o.committed),
        in_hand=list(o.in_hand), all_in=list(o.all_in),
        big_blind=o.big_blind, small_blind=o.small_blind, ante=o.ante, hand_number=o.hand_number,
        history=[(("preflop", "flop", "turn", "river")[s], seat, ("fold", "check", "call", "raise")[k], a)
                 for (s, seat, k, a) in o.history],
    )
    if with_bounds:
        kw.update(min_raise_to=o.min_raise_to, max_raise_to=o.max_raise_to, can_raise=o.can_raise)
    return build_observation(**kw)


def _collect(seed, n_tourneys=3):
    seen = []
    for t in range(n_tourneys):
        names = list(SPARRING_BOTS) + ["heuristic", "random", "call"]
        bots = [BOT_REGISTRY[n]() for n in names]
        recs = [Recorder(b) for b in bots]
        run_tournament(recs, BASELINE_RULES, seed=seed + t)
        for r in recs:
            seen.extend(r.seen)
    return seen


def test_rebuilt_observation_matches_engine_fields_when_bounds_are_given():
    for o in _collect(1):
        r = _rebuild(o, with_bounds=True)
        for k in Observation.__slots__:
            assert getattr(r, k) == getattr(o, k), (k, getattr(r, k), getattr(o, k))


def test_derived_fields_match_engine_in_the_common_cases():
    """Without raise bounds the bridge derives them from the big blind, which
    is right whenever the last raise was a min-raise or there was no raise.
    Everything else must always match."""
    exact = total = 0
    for o in _collect(2):
        r = _rebuild(o, with_bounds=False)
        for k in ("pot", "to_call", "can_check", "street", "live_players", "num_players", "in_hand", "all_in"):
            assert getattr(r, k) == getattr(o, k), k
        total += 1
        if (r.can_raise, r.min_raise_to, r.max_raise_to) == (o.can_raise, o.min_raise_to, o.max_raise_to):
            exact += 1
        else:
            # The only legitimate reason: a previous raise bigger than the BB.
            assert o.can_raise == r.can_raise or o.min_raise_to == o.max_raise_to
            assert r.max_raise_to == o.max_raise_to or not o.can_raise
    assert exact / total > 0.6, exact / total


def test_every_bot_decides_identically_from_the_rebuilt_observation():
    seen = _collect(3, 2)
    for name in BOT_REGISTRY:
        if name == "random":
            continue  # consumes RNG; compared via a fresh seeded pair below
        a, b = BOT_REGISTRY[name](), BOT_REGISTRY[name]()
        a.reset(TableInfo(0, 8, 2000, "x", 5))
        b.reset(TableInfo(0, 8, 2000, "x", 5))
        for o in seen[:1500]:
            ra, rb = a.act(o), b.act(_rebuild(o, with_bounds=True))
            assert ra == rb, (name, ra, rb)
    a, b = BOT_REGISTRY["random"](), BOT_REGISTRY["random"]()
    a.reset(TableInfo(0, 8, 2000, "x", 5))
    b.reset(TableInfo(0, 8, 2000, "x", 5))
    for o in seen[:300]:
        assert a.act(o) == b.act(_rebuild(o, with_bounds=True))


def test_text_codec_round_trip():
    seen = _collect(4, 1)
    rng = random.Random(0)
    for o in seen[:800]:
        for a in o.legal_actions + ([raise_to(rng.randint(o.min_raise_to, o.max_raise_to))] if o.can_raise else []):
            txt = action_to_text(a, o)
            back = action_from_text(txt, o)
            assert back == a or (a.kind == 2 and back == CALL), (txt, a, back)
            assert o.is_legal(back)
    o = seen[0]
    assert action_from_text("fold", o) == FOLD
    assert action_from_text("Check", o) == CHECK or not o.can_check
    with pytest.raises(ValueError):
        action_from_text("dance", o)
    with pytest.raises(ValueError):
        action_from_text("RAISE", o)


def test_build_observation_defaults():
    o = build_observation(seat=3, button=0, hole_cards=["As", "Kd"], board=[], stacks=[2000, 1990, 1980, 2000],
                          bets=[0, 10, 20, 0], big_blind=20)
    assert o.street == 0 and o.pot == 30 and o.to_call == 20 and not o.can_check and o.can_raise
    assert o.min_raise_to == 40 and o.max_raise_to == 2000 and o.live_players == 4
    # short all-in big blind: the full BB is still the amount to match preflop
    o1 = build_observation(seat=3, button=0, hole_cards=["As", "Kd"], board=[], stacks=[2000, 1990, 0, 2000],
                           bets=[0, 10, 12, 0], big_blind=20)
    assert o1.to_call == 20 and o1.min_raise_to == 40
    assert o.hole_cards_str == "As Kd"
    o2 = build_observation(seat=1, button=0, hole_cards=["As", "Kd"], board=["2c", "7d", "Jh"],
                           stacks=[500, 0, 300, 0], bets=[0, 0, 0, 0], committed=[100, 400, 100, 0], big_blind=20)
    assert o2.street == 1 and o2.all_in[1] and o2.in_hand[1] and not o2.in_hand[3]
    assert not o2.can_raise and o2.min_raise_to == 0  # hero is all-in
    o3 = build_observation(seat=0, button=0, hole_cards=["As", "Kd"], board=["2c", "7d", "Jh"],
                           stacks=[500, 300, 300, 0], bets=[0, 0, 0, 0], committed=[100, 100, 100, 0],
                           big_blind=20, last_raise_size=60, history=[("flop", 1, "check", 0)])
    assert o3.can_check and o3.min_raise_to == 60 and o3.history == ((1, 1, 1, 0),)
