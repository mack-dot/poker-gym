"""Deliberately incorrect cases: each injected fault must be detected by the
checkers or by the oracle comparisons. If any of these tests fails, a
correctness test has lost its teeth."""
import copy
import itertools
import random

import pytest

from pokerlab import engine as engine_mod
from pokerlab.agent import CALL, CHECK, FOLD, raise_to
from pokerlab.bots import CallBot, HeuristicBot, RandomBot
from pokerlab.cards import fresh_deck, parse_cards
from pokerlab.checks import (
    InvariantError, check_card_conservation, check_chip_conservation, check_points, check_rotation,
    check_termination, check_tournament,
)
from pokerlab.evaluator import FLUSH, HIGH_CARD, Evaluator, STANDARD_EVALUATOR, evaluate
from pokerlab.icm import brute_force_equities, icm_equities
from pokerlab.rules import BASELINE_RULES
from pokerlab.testing import ScriptedAgent, build_deck
from pokerlab.tournament import run_tournament


def mixed():
    return [CallBot(), RandomBot(), HeuristicBot(), RandomBot(), HeuristicBot(), CallBot(), RandomBot(), HeuristicBot()]


def good_result():
    return run_tournament(mixed(), seed=7)


def test_duplicate_card_is_detected():
    r = good_result()
    rec = r.hands[0]
    rec.hole[2] = (rec.hole[3][0], rec.hole[2][1])  # copy a card into another hand
    with pytest.raises(InvariantError, match="duplicate card"):
        check_card_conservation(rec)


def test_card_dealt_to_busted_seat_is_detected():
    r = good_result()
    rec = next(h for h in r.hands if any(h.hole[s] is None for s in range(8)))
    s = next(s for s in range(8) if rec.hole[s] is None)
    used = {c for h in rec.hole if h for c in h} | set(rec.board)
    unused = [c for c in range(52) if c not in used]
    rec.hole[s] = (unused[0], unused[1])
    with pytest.raises(InvariantError, match="busted seat"):
        check_card_conservation(rec)


def test_chip_leak_is_detected():
    r = good_result()
    rec = r.hands[1]
    rec.stacks_after = tuple(x + (1 if i == 0 else 0) for i, x in enumerate(rec.stacks_after))
    with pytest.raises(InvariantError, match="chips not conserved"):
        check_chip_conservation(rec)
    rec = r.hands[2]
    rec.net = tuple(x + (1 if i == 0 else 0) for i, x in enumerate(rec.net))
    with pytest.raises(InvariantError, match="net does not sum"):
        check_chip_conservation(rec)


def test_wrong_button_rotation_is_detected():
    r = good_result()
    r.hands[3].button = r.hands[2].button  # button failed to move
    with pytest.raises(InvariantError, match="button"):
        check_rotation(r, BASELINE_RULES)
    r = good_result()
    r.hands[4].sb_seat, r.hands[4].bb_seat = r.hands[4].bb_seat, r.hands[4].sb_seat
    with pytest.raises(InvariantError, match="blinds"):
        check_rotation(r, BASELINE_RULES)


def test_wrong_blind_level_is_detected():
    r = run_tournament([CallBot() for _ in range(8)], seed=2)
    r.hands[30].blinds = (10, 20)  # should be level 2 by hand 30
    with pytest.raises(InvariantError, match="blinds"):
        check_rotation(r, BASELINE_RULES)


def test_point_leak_and_bad_termination_are_detected():
    r = good_result()
    r.points[0] += 1.0
    with pytest.raises(InvariantError, match="points sum"):
        check_points(r, BASELINE_RULES)
    r = run_tournament([CallBot() for _ in range(8)], seed=2)  # hits the cap -> ICM
    r.icm_applied = False
    with pytest.raises(InvariantError, match="ICM not applied"):
        check_termination(r, BASELINE_RULES)
    r = good_result()
    r.hands_played = 201
    with pytest.raises(InvariantError, match="max"):
        check_termination(r, BASELINE_RULES)


def test_broken_evaluator_is_caught_by_frequency_and_oracle_checks():
    class NoFlush(Evaluator):
        def evaluate(self, cards):
            v = Evaluator.evaluate(self, cards)
            if Evaluator.category(self, v) == FLUSH:
                return self.strength[HIGH_CARD] | (v & 0xFFFFF)
            return v

    bad = NoFlush()
    rng = random.Random(0)
    deck = fresh_deck()
    disagreements = 0
    for _ in range(3000):
        rng.shuffle(deck)
        a, b = deck[:7], deck[7:14]
        if (bad.evaluate(a) > bad.evaluate(b)) != (evaluate(a) > evaluate(b)):
            disagreements += 1
    assert disagreements > 0
    # sampled category frequencies move off the known 5-card distribution
    counts = {k: 0 for k in range(9)}
    for combo in itertools.islice(itertools.combinations(range(52), 5), 0, 2598960, 97):
        counts[bad.category(bad.evaluate(combo))] += 1
    assert counts[FLUSH] == 0  # the standard count is 5108 / 2598960 ~ 0.2%


def test_broken_icm_is_caught_by_brute_force():
    def chip_chop(stacks, payouts):
        tot = sum(stacks)
        return [s / tot * sum(payouts) for s in stacks]

    stacks, pay = [5000, 3000, 2000], [50, 30, 20]
    bf = brute_force_equities(stacks, pay)
    assert any(abs(x - y) > 1e-6 for x, y in zip(chip_chop(stacks, pay), bf))
    assert all(abs(x - y) < 1e-9 for x, y in zip(icm_equities(stacks, pay), bf))


def test_broken_side_pot_is_caught_by_scenario(scripted):
    """A tie-everything evaluator would award the side pots wrongly; the
    multiway scenario's expected numbers catch it."""

    class Tie(Evaluator):
        def evaluate(self, cards):
            return 1

    import pokerlab.rules as rules_mod

    rules = BASELINE_RULES.with_(ranking=rules_mod.HandRanking())
    stacks = [2000] * 8
    stacks[2], stacks[3], stacks[4] = 100, 300, 1000
    ag = [ScriptedAgent({2: [raise_to(100)], 3: [raise_to(300)], 4: [raise_to(1000)]}.get(s, [FOLD])) for s in range(8)]
    deck = build_deck({2: "As Ad", 3: "Ks Kd", 4: "2s 2d"}, "3h 5d 8c 9s Jh", 0, list(range(8)))
    from pokerlab.agent import AgentAdapter, TableInfo

    adapters = [AgentAdapter(a, mode="off") for a in ag]
    for s, ad in enumerate(adapters):
        ad.reset(TableInfo(s, 8, stacks[s], "x", s))
    rec = engine_mod.play_hand(rules, Tie(), stacks, 7, 0, adapters, random.Random(0), deck=deck)
    assert rec.net[2] != 230  # the correct scenario value; the fault is visible


def test_tampered_record_changes_hash():
    a = run_tournament(mixed(), seed=11)
    b = run_tournament(mixed(), seed=11)
    b.hands[0].board[0], b.hands[0].board[1] = b.hands[0].board[1], b.hands[0].board[0]
    from pokerlab.tournament import _hash_hands

    assert _hash_hands(a.hands, a.final_stacks, a.points) != _hash_hands(b.hands, b.final_stacks, b.points)


def test_engine_mutation_no_button_move_is_caught(monkeypatch):
    """Mutate the runner so the button never moves; check_tournament must fail."""
    import pokerlab.tournament as t

    original = t.play_hand

    def frozen_button(rules, ev, stacks, button, hand_number, agents, rng, deck=None):
        return original(rules, ev, stacks, 0 if stacks[0] > 0 else button, hand_number, agents, rng, deck)

    monkeypatch.setattr(t, "play_hand", frozen_button)
    r = t.run_tournament(mixed(), seed=1)
    with pytest.raises(InvariantError):
        check_tournament(r, BASELINE_RULES)
