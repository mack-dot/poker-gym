import pytest

from pokergym.bots import BOT_REGISTRY, SPARRING_BOTS
from pokergym.bots.sparring import push_width
from pokergym.checks import check_tournament
from pokergym.gym import ladder
from pokergym.rules import BASELINE_RULES
from pokergym.tournament import run_tournament
from pokergym.variants import VARIANTS

ALL = list(BOT_REGISTRY)


def _lineup(seed):
    import random

    rng = random.Random(seed)
    names = list(SPARRING_BOTS) + [rng.choice(ALL) for _ in range(3)]
    rng.shuffle(names)
    return names


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_sparring_bots_are_legal_and_error_free(variant):
    rules = VARIANTS[variant]
    for seed in range(12):
        names = _lineup(seed)
        res = run_tournament([BOT_REGISTRY[n]() for n in names], rules, seed=seed)
        check_tournament(res, rules)
        for n, st in zip(names, res.agent_stats):
            assert st["illegal"] == 0, (variant, seed, n, st)
            assert st["errors"] == 0, (variant, seed, n, st)


def test_sparring_bots_are_deterministic():
    names = list(SPARRING_BOTS) + ["heuristic", "random", "call"]
    a = run_tournament([BOT_REGISTRY[n]() for n in names], BASELINE_RULES, seed=77)
    b = run_tournament([BOT_REGISTRY[n]() for n in names], BASELINE_RULES, seed=77)
    assert a.record_hash == b.record_hash


def test_sparring_bots_stay_well_under_the_deadline():
    names = list(SPARRING_BOTS) + ["tag", "lag", "icm"]
    rules = BASELINE_RULES.with_(deadline_mode="record")
    calls = timeouts = 0
    worst = 0
    for seed in range(15):
        res = run_tournament([BOT_REGISTRY[n]() for n in names], rules, seed=100 + seed, record_latency=True)
        for st in res.agent_stats:
            calls += st["calls"]
            timeouts += st["timeouts"]
            worst = max(worst, max(st["latencies_ns"]) if st["latencies_ns"] else 0)
    assert calls > 5000
    # In-simulation misses on a loaded machine are OS preemption (measured
    # independent of GC; see docs/gym.md). Only a systematic problem fails.
    assert timeouts / calls < 0.003, (timeouts, calls, worst)


def test_push_width_shape():
    assert push_width(10, 1) > push_width(10, 7)
    assert push_width(5, 3) > push_width(10, 3) > push_width(20, 3)
    assert 0 < push_width(15, 7) < push_width(10, 7) <= 1.0
    assert push_width(1, 1) == 1.0


def test_sparring_bots_beat_the_fixtures():
    """Strength check: every sparring bot outscores the call and random
    fixtures by a clear margin on a mixed table."""
    specs = ["tag", "lag", "shortstack", "icm", "adaptive", "heuristic", "random", "call"]
    rep = ladder(specs, tables=160, seed=3, rules=BASELINE_RULES)
    pts = dict(zip(rep.labels, rep.mean_points))
    se = dict(zip(rep.labels, rep.se_points))
    for name in SPARRING_BOTS:
        for weak in ("random", "call"):
            margin = pts[name] - pts[weak]
            assert margin > 2 * (se[name] ** 2 + se[weak] ** 2) ** 0.5, (name, weak, pts, se)
    assert pts["tag"] > pts["heuristic"], pts
