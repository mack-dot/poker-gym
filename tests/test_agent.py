import time

from pokerlab.agent import (
    CALL, CHECK, FOLD, Action, ActionType, AgentAdapter, Observation, TableInfo, raise_to,
)
from pokerlab.testing import CrashingAgent, PolicyAgent


def obs(can_check=False, can_raise=True, lo=40, hi=2000, to_call=20):
    return Observation(
        hand_number=0, street=0, seat=0, button=0, small_blind=10, big_blind=20, ante=0,
        hole_cards=(0, 1), board=(), stacks=(2000,) * 8, bets=(0,) * 8, committed=(0,) * 8,
        in_hand=(True,) * 8, all_in=(False,) * 8, pot=30, to_call=to_call, can_check=can_check,
        can_raise=can_raise, min_raise_to=lo, max_raise_to=hi, history=(), num_players=8, live_players=8,
    )


def test_action_serialization_roundtrip():
    for a in (FOLD, CHECK, CALL, raise_to(123)):
        assert Action.parse(a.serialize()) == a
        assert Action.from_dict(a.to_dict()) == a
    assert Action.parse("raise:60") == Action(ActionType.RAISE, 60)


def test_legal_actions_and_is_legal():
    o = obs()
    assert o.is_legal(FOLD) and o.is_legal(CALL) and not o.is_legal(CHECK)
    assert o.is_legal(raise_to(40)) and o.is_legal(raise_to(2000))
    assert not o.is_legal(raise_to(39)) and not o.is_legal(raise_to(2001))
    o2 = obs(can_check=True, can_raise=False)
    assert o2.is_legal(CHECK) and not o2.is_legal(CALL) and not o2.is_legal(raise_to(40))
    assert [a.kind for a in o2.legal_actions] == [ActionType.FOLD, ActionType.CHECK]


def test_adapter_fallback_on_exception():
    ad = AgentAdapter(CrashingAgent(), mode="enforce")
    assert ad.act(obs(can_check=False)) == FOLD
    assert ad.act(obs(can_check=True)) == CHECK
    assert ad.stats()["errors"] == 2


def test_adapter_fallback_on_illegal_action():
    ad = AgentAdapter(PolicyAgent(lambda o: raise_to(5)), mode="enforce")
    assert ad.act(obs()) == FOLD
    ad = AgentAdapter(PolicyAgent(lambda o: "call"), mode="enforce")  # wrong type
    assert ad.act(obs()) == FOLD
    assert ad.stats()["illegal"] == 1


def test_adapter_deadline_enforce_vs_record():
    def slow(o):
        time.sleep(0.003)
        return CALL

    ad = AgentAdapter(PolicyAgent(slow), deadline_ms=1.0, mode="enforce")
    assert ad.act(obs()) == FOLD
    assert ad.stats()["timeouts"] == 1
    ad = AgentAdapter(PolicyAgent(slow), deadline_ms=1.0, mode="record")
    assert ad.act(obs()) == CALL
    assert ad.stats()["timeouts"] == 1
    ad = AgentAdapter(PolicyAgent(slow), deadline_ms=1.0, mode="off")
    assert ad.act(obs()) == CALL
    assert ad.stats()["timeouts"] == 0


def test_adapter_records_latency():
    ad = AgentAdapter(PolicyAgent(lambda o: CALL), mode="record", record_latency=True)
    for _ in range(5):
        ad.act(obs())
    assert len(ad.latencies_ns) == 5 and all(x >= 0 for x in ad.latencies_ns)
