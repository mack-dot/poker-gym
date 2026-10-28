"""Every mutation in the reserve must (1) execute under all engine invariants,
(2) pass its own independent check, (3) shift its strategic signal versus
the baseline game on the same seeds, and (4) be reproducible from its seed."""
import math
import statistics

import pytest

from pokergym.arena.mutations import FAMILIES, Mutation, generate, reserve
from pokergym.bots import BOT_REGISTRY
from pokergym.gym import evaluate, instantiate
from pokergym.rules import BASELINE_RULES
from pokergym.tournament import run_tournament
from pokergym.variants import VARIANTS

LINEUP = ("tag", "lag", "shortstack", "icm", "adaptive", "tag", "lag", "icm")
RESERVE = reserve()


def _table(rules, seed):
    bots = [instantiate(n, rules) for n in LINEUP]
    return run_tournament(bots, rules, seed=seed, keep_hands=True)


_BASE_CACHE = {}


def _baseline(seed):
    if seed not in _BASE_CACHE:
        _BASE_CACHE[seed] = _table(BASELINE_RULES, seed)
    return _BASE_CACHE[seed]


@pytest.mark.parametrize("m", RESERVE, ids=[m.name for m in RESERVE])
def test_mutation_executes_and_passes_independent_check(m):
    for seed in range(3):
        res = _table(m.rules, seed)
        m.check(res, m.rules)
        assert all(st["illegal"] == 0 and st["errors"] == 0 for st in res.agent_stats), m.name


@pytest.mark.parametrize("m", RESERVE, ids=[m.name for m in RESERVE])
def test_mutation_shifts_strategic_signal(m):
    n = 24 if m.signal_kind == "mean" else 100
    base = [m.signal(_baseline(s), BASELINE_RULES) for s in range(n)]
    var = [m.signal(_table(m.rules, s), m.rules) for s in range(n)]
    if m.signal_kind == "pooled":
        assert abs(sum(var) - sum(base)) >= 6 and min(sum(var), sum(base)) == 0, (m.name, m.signal_name, sum(base), sum(var))
        return
    db, dv = statistics.pstdev(base), statistics.pstdev(var)
    se = math.sqrt((db * db + dv * dv) / n) or 1e-9
    z = (statistics.fmean(var) - statistics.fmean(base)) / se
    assert abs(z) > 3, (m.name, m.signal_name, statistics.fmean(base), statistics.fmean(var), z)


def test_generate_is_deterministic_and_serializable():
    for seed in range(12):
        a, b = generate(seed), generate(seed)
        assert a.to_dict() == b.to_dict() and a.fingerprint() == b.fingerprint()
        c = Mutation.from_dict(a.to_dict())
        assert c.rules == a.rules and c.name == a.name
    assert len({generate(s).name for s in range(60)}) >= 8, "generator should spread over the reserve"


def test_reserve_excludes_known_variants():
    known = {VARIANTS["flush-beats-full-house"].ranking.strength}
    for m in RESERVE:
        assert m.rules.ranking.strength not in known
        assert m.rules.betting.limit != "pot_limit"
        assert m.rules != BASELINE_RULES


def test_one_rule_changes_per_mutation():
    base = BASELINE_RULES
    for m in RESERVE:
        r = m.rules
        changed = [f for f in ("blinds", "payouts", "betting", "ranking", "board_streets", "hole_cards", "starting_stack")
                   if getattr(r, f) != getattr(base, f)]
        assert len(changed) == 1, (m.name, changed)


def test_briefing_mentions_the_change_and_labels_synthetic():
    for m in RESERVE:
        b = m.briefing()
        assert "REHEARSAL" in b and "synthetic" in b.lower()
        assert m.headline in b and "Legal actions" in b


@pytest.mark.slow
def test_adapting_to_payouts_is_worth_points():
    """Configured IcmBot vs its payout-naive twin under winner-take-all,
    paired on the same seats and seeds. Measured +1.4 pts/table at 400
    tables (CI -0.7..+3.5): right direction, not yet significant."""
    m = FAMILIES["payouts"](0, {"option": "winner-take-all"})
    rep = evaluate(m.adapted_ref, LINEUP[:7], tables=400, seed=3, rules=m.rules, baseline=m.naive_ref, workers=4)
    assert rep.diff_mean > 0, (m.name, rep.diff_mean, rep.diff_ci95)


@pytest.mark.slow
def test_ranking_adaptation_is_not_harmful():
    """FINDING: for category swaps the sparring bots' one-class adjustment is
    not measurably worth points (two-pair > trips+straight: -1.1 pts/table,
    CI -2.8..+0.6 at 400 tables). The hidden evaluator therefore reports
    'adaptation not separable' for this family. Guard: not significantly worse."""
    m = FAMILIES["hand_ranking"](0, {"option": "two-pair-beats-trips-and-straight"})
    rep = evaluate(m.adapted_ref, LINEUP[:7], tables=200, seed=3, rules=m.rules, baseline=m.naive_ref, workers=4)
    lo, hi = rep.diff_ci95
    assert hi > 0, (m.name, rep.diff_mean, lo, hi)
    assert BOT_REGISTRY
