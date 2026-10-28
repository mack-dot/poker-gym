"""Determinism is a research requirement: the same seed must always give the
same record. The 1 ms deadline is a wall-clock event, so enforcing it inside
the measuring process would make records depend on GC pauses. These tests pin
the separation: the default mode measures but never perturbs play, and
``enforce`` is opt-in and visibly non-reproducible.
"""
import time

from pokergym.agent import CALL
from pokergym.bots import CallBot, HeuristicBot, RandomBot
from pokergym.rules import BASELINE_RULES
from pokergym.tournament import run_tournament


def mixed():
    return [CallBot(), RandomBot(), HeuristicBot(), RandomBot(), HeuristicBot(), CallBot(), RandomBot(), HeuristicBot()]


def test_default_deadline_mode_is_record():
    assert BASELINE_RULES.deadline_mode == "record"


def test_default_mode_records_without_changing_play():
    slow = 0
    for seed in range(60):
        rec = run_tournament(mixed(), rules=BASELINE_RULES, seed=seed)
        off = run_tournament(mixed(), rules=BASELINE_RULES.with_(deadline_mode="off"), seed=seed)
        slow += sum(s["timeouts"] for s in rec.agent_stats)
        assert rec.record_hash == off.record_hash, f"seed {seed}: timing changed the game"
    # the measurement is real: some calls are compared against 1 ms even if none trip
    for seed in range(5):
        rec = run_tournament(mixed(), rules=BASELINE_RULES, seed=seed, record_latency=True)
        assert all("latencies_ns" in s for s in rec.agent_stats)
        assert sum(len(s["latencies_ns"]) for s in rec.agent_stats) > 0


def test_enforce_mode_is_deterministically_reproducible_when_no_call_is_slow():
    a = run_tournament(mixed(), rules=BASELINE_RULES.with_(deadline_mode="enforce"), seed=3)
    b = run_tournament(mixed(), rules=BASELINE_RULES.with_(deadline_mode="enforce"), seed=3)
    assert a.record_hash == b.record_hash


def test_enforce_mode_changes_the_game_when_a_call_exceeds_the_deadline():
    """Proves the reason enforce is not the default: a slow call is replaced by
    check/fold, which changes the record. A 2 ms sleep forces the fallback."""

    class SlowCallBot:
        def reset(self, t):
            pass

        def act(self, o):
            time.sleep(0.002)
            return CALL if not o.can_check else CALL

    bots = [SlowCallBot()] + [CallBot() for _ in range(7)]
    rec = run_tournament(bots, rules=BASELINE_RULES.with_(deadline_mode="enforce"), seed=1)
    assert sum(s["timeouts"] for s in rec.agent_stats) > 0
    # every timed-out call was replaced by fold/check, so the bot never put chips in on those
    legal = run_tournament([CallBot() for _ in range(8)], rules=BASELINE_RULES.with_(deadline_mode="enforce"), seed=1)
    assert rec.record_hash != legal.record_hash
