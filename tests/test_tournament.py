import json

import pytest

from pokergym.bots import CallBot, HeuristicBot, RandomBot
from pokergym.checks import check_tournament
from pokergym.icm import brute_force_equities
from pokergym.rules import BASELINE_RULES, SYNTHETIC_PAYOUTS
from pokergym.tournament import assign_finishes, final_score, run_round, run_tournament
from pokergym.variants import VARIANTS

TOTAL_POINTS = sum(SYNTHETIC_PAYOUTS.points)


def mixed():
    return [CallBot(), RandomBot(), HeuristicBot(), RandomBot(), HeuristicBot(), CallBot(), RandomBot(), HeuristicBot()]


def test_full_tournament_invariants_many_seeds():
    for seed in range(40):
        r = run_tournament(mixed(), seed=seed)
        check_tournament(r, BASELINE_RULES)
        assert sum(r.final_stacks) == 16000
        assert abs(sum(r.points) - TOTAL_POINTS) < 1e-9


def test_all_in_heavy_play_invariants():
    """Many multi-way all-ins per hand: exercises side pots and multi-bust ranking."""
    for seed in range(40):
        bots = [RandomBot(p_raise=0.9, p_fold=0.05) for _ in range(8)]
        r = run_tournament(bots, seed=seed)
        check_tournament(r, BASELINE_RULES)


def test_deterministic_replay_and_seed_sensitivity():
    a = run_tournament(mixed(), seed=123)
    b = run_tournament(mixed(), seed=123)
    c = run_tournament(mixed(), seed=124)
    assert a.record_hash == b.record_hash
    assert a.to_json() == b.to_json()
    assert a.record_hash != c.record_hash
    # json round trip is stable
    assert json.loads(a.to_json())["record_hash"] == a.record_hash


def test_hand_cap_termination_and_icm_allocation():
    r = run_tournament([CallBot() for _ in range(8)], seed=5)
    assert r.hands_played == 200 and r.icm_applied and len(r.icm_survivors) >= 2
    check_tournament(r, BASELINE_RULES)
    # Independent ICM check by brute-force enumeration over the survivors.
    surv = r.icm_survivors
    pay = [SYNTHETIC_PAYOUTS.for_position(p) for p in range(1, len(surv) + 1)]
    if len(surv) <= 7:
        bf = brute_force_equities([r.final_stacks[s] for s in surv], pay)
        for s, e in zip(surv, bf):
            assert abs(r.points[s] - e) < 1e-6
    assert abs(sum(r.points) - TOTAL_POINTS) < 1e-9


def test_blind_schedule_applied_every_25_hands():
    r = run_tournament([CallBot() for _ in range(8)], seed=1)
    levels = BASELINE_RULES.blinds.levels
    for rec in r.hands:
        assert rec.blinds == levels[min(rec.hand_number // 25, len(levels) - 1)]
    assert r.hands[24].blinds == (10, 20) and r.hands[25].blinds == (15, 30)


def test_dealer_rotation_skips_eliminated_seats():
    found = False
    for seed in range(30):
        r = run_tournament(mixed(), seed=seed)
        check_tournament(r, BASELINE_RULES)  # includes rotation check
        for prev, cur in zip(r.hands, r.hands[1:]):
            if (prev.button + 1) % 8 != cur.button:
                # a seat was skipped: it must have been busted
                assert cur.start_stacks[(prev.button + 1) % 8] == 0
                found = True
    assert found


def test_assign_finishes_ranks_by_start_stack_and_splits_ties():
    out = assign_finishes([2, 5, 7], start_stacks=[0, 0, 500, 0, 0, 100, 0, 500], next_position=8, payouts=SYNTHETIC_PAYOUTS)
    d = {s: (pos, pts) for s, pos, pts in out}
    assert d[5] == (8.0, 0.0)  # smallest stack: 8th
    assert d[2] == (6.5, 7.5) and d[7] == (6.5, 7.5)  # tie for 6th/7th: (10 + 5) / 2


def test_single_survivor_gets_first_place():
    for seed in range(10):
        r = run_tournament([RandomBot(p_raise=0.8) for _ in range(8)], seed=seed)
        if not r.icm_applied:
            w = r.final_stacks.index(16000)
            assert r.positions[w] == 1.0 and r.points[w] == 100.0
            assert len(r.elimination_order) == 7


def test_random_bot_is_seed_deterministic():
    a = run_tournament([RandomBot() for _ in range(8)], seed=9)
    b = run_tournament([RandomBot() for _ in range(8)], seed=9)
    assert a.record_hash == b.record_hash


@pytest.mark.parametrize("name", list(VARIANTS))
def test_variants_run_full_tournaments(name):
    rules = VARIANTS[name]
    for seed in range(5):
        r = run_tournament(mixed(), rules=rules, seed=seed)
        check_tournament(r, rules)
        assert r.rules_name == rules.name


# --------------------------------------------------------------------------
# Scoring (rules 4.3, 4.6, 4.7)
# --------------------------------------------------------------------------
def test_round_scoring_eight_bots_conserves_points():
    names = ["call", "rand", "heur"] * 2 + ["call", "rand"]
    factories = [CallBot, RandomBot, HeuristicBot] * 2 + [CallBot, RandomBot]
    rs = run_round(factories, names, tables=12, seed=3)
    assert abs(sum(rs.avg_points) - TOTAL_POINTS) < 1e-9
    assert rs.tables == 12 and rs.hands_total > 0
    rs2 = run_round(factories, names, tables=12, seed=3)
    assert rs2.avg_points == rs.avg_points


def test_round_scoring_filler_bots_earn_nothing():
    rs = run_round([CallBot, HeuristicBot, RandomBot], ["c", "h", "r"], tables=10, seed=1)
    assert len(rs.avg_points) == 3
    assert sum(rs.avg_points) < TOTAL_POINTS  # fillers absorbed some points


def test_final_score_weights():
    assert final_score([1, 1, 1, 1, 1, 1]) == 21
    assert final_score([10, 0, 0, 0, 0, 5]) == 10 + 30
    with pytest.raises(ValueError):
        final_score([1, 2, 3])


def test_rules_reject_bad_payout_schedule():
    from pokergym.rules import PayoutSchedule

    with pytest.raises(ValueError):
        PayoutSchedule(points=(1, 2, 3, 4, 5, 6, 7, 8))
    with pytest.raises(ValueError):
        PayoutSchedule(points=(1, 1, 1))
