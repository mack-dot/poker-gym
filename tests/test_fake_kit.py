"""The fake-kit drill must be runnable and the answer key must pass it."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "drills", "fake_kit"))

import fakekit  # noqa: E402
import reference_adapter  # noqa: E402
import run_drill  # noqa: E402

from pokergym.bots import BOT_REGISTRY  # noqa: E402
from pokergym.variants import VARIANTS  # noqa: E402


def test_reference_adapter_passes_drill():
    r = run_drill.check(reference_adapter.Adapted, tables=3)
    assert r["fake_errors"] == 0
    assert r["parity_mismatches"] == 0 and r["parity_compared"] > 100
    assert r["overhead_us"] < 500


def test_always_check_bot_is_legal_and_survives():
    res = fakekit.play_table([fakekit.AlwaysCheckBot() for _ in range(8)], seed=3, keep_hands=False)
    assert sum(res.fake_errors) == 0
    assert all(st["illegal"] == 0 for st in res.agent_stats)


def test_bad_replies_fall_back_without_crashing():
    class Garbage:
        def new_table(self, c):
            pass

        def new_hand(self, h):
            pass

        def decide(self, s, o):
            return "SHOVE 9999999"  # not a word the kit knows

    res = fakekit.play_table([Garbage()] + [fakekit.AlwaysCheckBot() for _ in range(7)], seed=5, keep_hands=False)
    assert res.fake_errors[0] > 0
    assert res.agent_stats[0]["illegal"] == 0  # the fallback is always legal


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_every_sparring_bot_is_legal_through_the_fake_kit(name):
    rules = VARIANTS[name]
    bots = [reference_adapter.Adapted(BOT_REGISTRY[k]()) for k in ("tag", "lag", "shortstack", "icm", "adaptive", "tag", "lag", "icm")]
    for b in bots:
        b.inner.configure(rules)
    res = fakekit.play_table(bots, seed=11, rules=rules, keep_hands=False)
    assert sum(res.fake_errors) == 0
    assert all(st["illegal"] == 0 and st["errors"] == 0 for st in res.agent_stats)
