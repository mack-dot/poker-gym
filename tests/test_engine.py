"""Scripted single-hand scenarios. Button at seat 7 => SB 0, BB 1, UTG 2."""
import random

import pytest

from pokergym.agent import CALL, CHECK, FOLD, ActionType, AgentAdapter, raise_to
from pokergym.engine import play_hand
from pokergym.rules import BASELINE_RULES, BettingRules, BlindSchedule
from pokergym.testing import ScriptedAgent, build_deck
from pokergym.variants import VARIANT_A_FLUSH_BEATS_FULL_HOUSE, VARIANT_B_POT_LIMIT

ALL = list(range(8))
BOARD_DRY = "3h 5d 8c 9s Jh"


def agents(scripts: dict):
    return [ScriptedAgent(scripts.get(s, [])) for s in range(8)]


def test_min_raise_and_reraise_sizes(scripted):
    ag = agents({2: [raise_to(60), FOLD], 3: [raise_to(150)], 4: [FOLD], 5: [FOLD], 6: [FOLD],
                 7: [FOLD], 0: [FOLD], 1: [FOLD]})
    stacks = [2000] * 8
    deck = build_deck({}, BOARD_DRY, 0, ALL)
    rec, _ = scripted(ag, stacks, 7, deck)
    o2, o3, o4 = ag[2].observations[0], ag[3].observations[0], ag[4].observations[0]
    assert (o2.to_call, o2.min_raise_to, o2.max_raise_to) == (20, 40, 2000)
    assert (o3.to_call, o3.min_raise_to, o3.max_raise_to) == (60, 100, 2000)  # last raise was 40
    assert (o4.to_call, o4.min_raise_to) == (150, 240)  # last raise was 90
    o2b = ag[2].observations[1]
    assert o2b.to_call == 90 and o2b.can_raise and o2b.min_raise_to == 240  # full raise reopened
    assert stacks[3] == 2000 + 90 and stacks[2] == 1940 and sum(stacks) == 16000
    assert rec.net[3] == 90 and rec.showdown_values is None


def test_short_all_in_does_not_reopen_betting(scripted):
    stacks = [2000] * 8
    stacks[7] = 70
    ag = agents({2: [raise_to(60), CALL], 3: [FOLD], 4: [FOLD], 5: [FOLD], 6: [FOLD],
                 7: [raise_to(70)], 0: [FOLD], 1: [FOLD]})
    deck = build_deck({2: "Kd Kc", 7: "Ad Ac"}, BOARD_DRY, 0, ALL)
    rec, _ = scripted(ag, stacks, 7, deck)
    o7 = ag[7].observations[0]
    assert o7.can_raise and o7.min_raise_to == 70 and o7.max_raise_to == 70  # all-in short raise only
    o0 = ag[0].observations[0]
    assert o0.can_raise and o0.min_raise_to == 110  # SB has not acted: may raise; min = 70 + 40
    o2b = ag[2].observations[1]
    assert o2b.to_call == 10 and not o2b.can_raise  # already acted; short all-in does not reopen
    assert stacks[7] == 170 and stacks[2] == 1930
    assert rec.pots == [(170, (2, 7), (7,))]


def test_short_all_in_opening_bet_does_not_reopen_for_checkers(scripted):
    """TDA rule 43: a player who checked and then faces an all-in bet smaller
    than a full bet may call or fold, not raise. (PokerKit allows the raise;
    see docs/fidelity.md.)"""
    stacks = [0] * 8
    stacks[0], stacks[1], stacks[2] = 1000, 1000, 24  # seat 2 has 4 chips after calling 20
    # button 2 => SB 0, BB 1; preflop: 2 calls, 0 calls, 1 checks; flop: 0 checks, 1 checks, 2 bets 4 all-in
    ag = agents({2: [CALL, raise_to(4)], 0: [CALL, CHECK, CALL], 1: [CHECK, CHECK, CALL]})
    deck = build_deck({}, BOARD_DRY, 0, [0, 1, 2])
    rec, _ = scripted(ag, stacks, 2, deck)
    o2 = ag[2].observations[1]
    assert o2.street == 1 and o2.can_raise and (o2.min_raise_to, o2.max_raise_to) == (4, 4)
    o0 = ag[0].observations[2]
    assert o0.street == 1 and o0.to_call == 4 and not o0.can_raise
    o1 = ag[1].observations[2]
    assert o1.street == 1 and o1.to_call == 4 and not o1.can_raise


def test_multiway_side_pots_short_stack_wins_main(scripted):
    stacks = [2000] * 8
    stacks[2], stacks[3], stacks[4] = 100, 300, 1000
    ag = agents({2: [raise_to(100)], 3: [raise_to(300)], 4: [raise_to(1000)], 5: [FOLD], 6: [FOLD],
                 7: [FOLD], 0: [FOLD], 1: [FOLD]})
    deck = build_deck({2: "As Ad", 3: "Ks Kd", 4: "2s 2d"}, BOARD_DRY, 0, ALL)
    rec, _ = scripted(ag, stacks, 7, deck)
    # main pot 330 (3 x 100 + 30 blinds), side pot 400, 700 uncalled back to seat 4
    assert rec.pots == [(330, (2, 3, 4), (2,)), (400, (3, 4), (3,)), (700, (4,), (4,))]
    assert rec.net[2] == 230 and rec.net[3] == 100 and rec.net[4] == -300
    assert rec.net[0] == -10 and rec.net[1] == -20 and sum(rec.net) == 0
    assert stacks[2] == 330 and stacks[3] == 400 and stacks[4] == 700


def test_multiway_side_pots_big_stack_wins_all(scripted):
    stacks = [2000] * 8
    stacks[2], stacks[3], stacks[4] = 100, 300, 1000
    ag = agents({2: [raise_to(100)], 3: [raise_to(300)], 4: [raise_to(1000)], 5: [FOLD], 6: [FOLD],
                 7: [FOLD], 0: [FOLD], 1: [FOLD]})
    deck = build_deck({2: "Ks Kd", 3: "2s 2d", 4: "As Ad"}, BOARD_DRY, 0, ALL)
    rec, _ = scripted(ag, stacks, 7, deck)
    assert rec.net[4] == 430 and rec.net[2] == -100 and rec.net[3] == -300
    assert stacks[2] == 0 and stacks[3] == 0 and stacks[4] == 1430


def test_all_in_call_for_less_and_uncalled_portion_returned(scripted):
    stacks = [2000] * 8
    stacks[3] = 100
    ag = agents({2: [raise_to(500)], 3: [CALL], 4: [FOLD], 5: [FOLD], 6: [FOLD], 7: [FOLD], 0: [FOLD], 1: [FOLD]})
    deck = build_deck({2: "Qs Qd", 3: "As Ad"}, BOARD_DRY, 0, ALL)
    rec, _ = scripted(ag, stacks, 7, deck)
    assert ag[3].observations[0].to_call == 100  # capped at stack
    assert rec.net[3] == 130 and rec.net[2] == -100 and stacks[2] == 1900 and stacks[3] == 230


def test_split_pot_odd_chip_goes_left_of_button(scripted):
    rules = BASELINE_RULES.with_(blinds=BlindSchedule(levels=((5, 10),)))
    stacks = [0] * 8
    stacks[0] = stacks[1] = stacks[2] = 1000
    ag = agents({2: [CALL], 0: [FOLD], 1: [CHECK]})
    deck = build_deck({1: "2c 3d", 2: "2h 3s"}, "As Ks Qd Jh Tc", 0, [0, 1, 2])
    rec, _ = scripted(ag, stacks, 2, deck, rules=rules)
    assert rec.pots == [(25, (1, 2), (1, 2))]
    assert rec.net[1] == 3 and rec.net[2] == 2 and rec.net[0] == -5


def test_tied_hands_split_evenly(scripted):
    stacks = [0] * 8
    stacks[0] = stacks[1] = 1000
    ag = agents({0: [CALL], 1: [CHECK]})
    deck = build_deck({0: "2c 3d", 1: "2h 3s"}, "As Ks Qd Jh Tc", 0, [0, 1])
    rec, _ = scripted(ag, stacks, 0, deck)
    assert rec.net == (0, 0, 0, 0, 0, 0, 0, 0)


def test_big_blind_gets_option_after_limps(scripted):
    ag = agents({s: [CALL] for s in (2, 3, 4, 5, 6, 7, 0)} | {1: [raise_to(40)]})
    for s in (2, 3, 4, 5, 6, 7, 0):
        ag[s].script.append(FOLD)
    stacks = [2000] * 8
    deck = build_deck({}, BOARD_DRY, 0, ALL)
    rec, _ = scripted(ag, stacks, 7, deck)
    o1 = ag[1].observations[0]
    assert o1.can_check and o1.can_raise and o1.min_raise_to == 40 and o1.street == 0
    assert rec.net[1] == 7 * 20 and stacks[1] == 2140


def test_heads_up_button_is_small_blind_and_acts_first_preflop(scripted):
    stacks = [0] * 8
    stacks[3] = stacks[6] = 1000
    ag = agents({3: [CALL, CHECK, CHECK, CHECK], 6: [CHECK, CHECK, CHECK, CHECK]})
    deck = build_deck({3: "As Ad", 6: "2c 3d"}, BOARD_DRY, 3, [3, 6])
    rec, _ = scripted(ag, stacks, 3, deck)
    assert rec.sb_seat == 3 and rec.bb_seat == 6
    assert rec.actions[0][:2] == (0, 3)  # button acts first preflop
    assert rec.actions[2][:2] == (1, 6)  # big blind acts first on the flop
    assert rec.net[3] == 20 and rec.net[6] == -20


def test_folded_player_not_eligible_even_with_best_hand(scripted):
    ag = agents({2: [raise_to(60)], 3: [CALL, FOLD], 4: [FOLD], 5: [FOLD], 6: [FOLD], 7: [FOLD], 0: [FOLD], 1: [FOLD]})
    # seat 3 has aces but folds to a flop bet from seat 2
    ag[2].script = [raise_to(60), raise_to(100)]
    stacks = [2000] * 8
    deck = build_deck({2: "7c 2d", 3: "As Ad"}, BOARD_DRY, 0, ALL)
    rec, _ = scripted(ag, stacks, 7, deck)
    assert rec.net[2] == 90 and rec.net[3] == -60


def test_illegal_action_falls_back_to_check_or_fold(scripted):
    ag = agents({2: [raise_to(30)], 3: [FOLD], 4: [FOLD], 5: [FOLD], 6: [FOLD], 7: [FOLD], 0: [FOLD], 1: [CHECK]})
    stacks = [2000] * 8
    deck = build_deck({}, BOARD_DRY, 0, ALL)
    rec, ad = scripted(ag, stacks, 7, deck)
    assert rec.actions[0] == (0, 2, ActionType.FOLD, 0)
    assert ad[2].stats()["illegal"] == 1
    assert rec.net[1] == 10


def test_raise_cap_variant(scripted):
    rules = BASELINE_RULES.with_(betting=BettingRules(raise_cap_per_street=2))
    ag = agents({2: [raise_to(60)], 3: [CALL], 4: [FOLD], 5: [FOLD], 6: [FOLD], 7: [FOLD], 0: [FOLD], 1: [FOLD]})
    stacks = [2000] * 8
    deck = build_deck({}, BOARD_DRY, 0, ALL)
    scripted(ag, stacks, 7, deck, rules=rules)
    assert ag[2].observations[0].can_raise
    assert not ag[3].observations[0].can_raise  # BB (1) + UTG raise (2) == cap


def test_pot_limit_max_raise(scripted):
    ag = agents({2: [raise_to(70)], 3: [raise_to(240)], 4: [FOLD], 5: [FOLD], 6: [FOLD], 7: [FOLD], 0: [FOLD], 1: [FOLD], })
    ag[2].script.append(FOLD)
    stacks = [2000] * 8
    deck = build_deck({}, BOARD_DRY, 0, ALL)
    scripted(ag, stacks, 7, deck, rules=VARIANT_B_POT_LIMIT)
    o2, o3 = ag[2].observations[0], ag[3].observations[0]
    assert (o2.min_raise_to, o2.max_raise_to) == (40, 70)  # 20 + 20 + 30
    assert (o3.min_raise_to, o3.max_raise_to) == (120, 240)  # 70 + 70 + 100
    # same spot under no-limit: stack-bounded
    ag2 = agents({2: [raise_to(70)], 3: [FOLD], 4: [FOLD], 5: [FOLD], 6: [FOLD], 7: [FOLD], 0: [FOLD], 1: [FOLD]})
    scripted(ag2, [2000] * 8, 7, build_deck({}, BOARD_DRY, 0, ALL))
    assert ag2[3].observations[0].max_raise_to == 2000


def test_flush_beats_full_house_only_under_variant(scripted):
    stacks = [2000] * 8
    deck = build_deck({2: "9s 8s", 3: "Kd Kc"}, "Ks Qs 2s 2d 7h", 0, ALL)  # 2: flush, 3: full house
    scripts = {2: [CALL], 3: [CALL], 4: [FOLD], 5: [FOLD], 6: [FOLD], 7: [FOLD], 0: [FOLD], 1: [CHECK]}
    rec, _ = scripted(agents(scripts), list(stacks), 7, deck)
    assert rec.pots[-1][2] == (3,)
    rec2, _ = scripted(agents(scripts), list(stacks), 7, deck, rules=VARIANT_A_FLUSH_BEATS_FULL_HOUSE)
    assert rec2.pots[-1][2] == (2,)


def test_card_uniqueness_and_board_size(scripted):
    for seed in range(20):
        rng = random.Random(seed)
        deck = list(range(52))
        rng.shuffle(deck)
        stacks = [2000] * 8
        rec, _ = scripted(agents({}), stacks, seed % 8, deck)
        dealt = [c for h in rec.hole if h for c in h] + list(rec.board)
        assert len(dealt) == 16 + 5 and len(set(dealt)) == 21
        assert set(dealt) == set(deck[:21]) and rec.board == deck[16:21]
        # round-robin from the small blind: SB gets deck[0] and deck[8]
        assert rec.hole[rec.sb_seat] == (deck[0], deck[8])


def test_busted_seats_are_skipped_for_blinds_and_cards(scripted):
    stacks = [2000, 0, 2000, 0, 0, 2000, 2000, 0]
    deck = build_deck({}, BOARD_DRY, 2, [0, 2, 5, 6])
    rec, _ = scripted(agents({}), stacks, 0, deck)
    assert (rec.sb_seat, rec.bb_seat) == (2, 5)
    assert rec.hole[1] is None and rec.hole[3] is None and rec.hole[7] is None
    assert all(rec.hole[s] is not None for s in (0, 2, 5, 6))


# --------------------------------------------------------------------------
# Betting legality probe over random play
# --------------------------------------------------------------------------
class ProbeAgent:
    """Random legal policy that asserts observation invariants at every decision."""

    def __init__(self, rng, rules):
        self.rng = rng
        self.rules = rules
        self.n = 0

    def reset(self, table):
        pass

    def act(self, obs):
        self.n += 1
        s = obs.seat
        cur = max(obs.bets)
        assert 0 <= obs.to_call <= obs.stacks[s]
        assert obs.can_check == (obs.to_call == 0)
        assert obs.pot == sum(obs.committed)
        assert len(obs.hole_cards) == 2 and len(set(obs.hole_cards)) == 2
        assert not (set(obs.hole_cards) & set(obs.board))
        assert obs.in_hand[s] and not obs.all_in[s] and obs.stacks[s] > 0
        if obs.can_raise:
            assert 0 < obs.min_raise_to <= obs.max_raise_to <= obs.bets[s] + obs.stacks[s]
            assert obs.max_raise_to > cur
            if obs.min_raise_to != obs.max_raise_to:
                assert obs.min_raise_to >= cur + obs.big_blind
            if self.rules.betting.limit == "pot_limit":
                assert obs.max_raise_to <= cur + obs.to_call + obs.pot
            else:
                assert obs.max_raise_to == obs.bets[s] + obs.stacks[s]
        else:
            assert obs.min_raise_to == 0 and obs.max_raise_to == 0
        r = self.rng.random()
        if obs.can_raise and r < 0.35:
            return raise_to(self.rng.randint(obs.min_raise_to, obs.max_raise_to))
        if r < 0.9 or obs.can_check:
            return CHECK if obs.can_check else CALL
        return FOLD


@pytest.mark.parametrize("rules", [BASELINE_RULES, VARIANT_B_POT_LIMIT])
def test_betting_legality_random_play(rules):
    rng = random.Random(99)
    probes = [ProbeAgent(rng, rules) for _ in range(8)]
    adapters = [AgentAdapter(p, mode="off") for p in probes]
    ev = rules.ranking.evaluator()
    for hand in range(300):
        stacks = [rng.choice([0, 50, 300, 2000, 5000]) for _ in range(8)]
        if sum(1 for s in stacks if s > 0) < 2:
            continue
        total = sum(stacks)
        button = rng.choice([s for s in range(8) if stacks[s] > 0])
        rec = play_hand(rules, ev, stacks, button, hand, adapters, rng)
        assert sum(stacks) == total
        assert all(s >= 0 for s in stacks)
        assert sum(rec.net) == 0
        # every action in the record is consistent: raises strictly increase the street bet
        for st in range(4):
            cur = 0
            for (street, seat, kind, amt) in rec.actions:
                if street == st and kind == ActionType.RAISE:
                    assert amt > cur
                    cur = amt
    assert all(a.stats()["illegal"] == 0 for a in adapters)
    assert sum(p.n for p in probes) > 2000
