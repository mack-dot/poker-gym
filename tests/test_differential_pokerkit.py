"""Independent oracle: replay identical randomized hands through PokerKit.

Same hole cards, same board, same decision stream (shove / call / fold /
check by a shared random sequence). Final stacks must match exactly. This
cross-checks betting legality, min/max raise amounts, side pots, showdown
evaluation and odd-chip splitting against an independent implementation.
"""
import random

import pytest

pokerkit = pytest.importorskip("pokerkit")
# PokerKit warns when an explicitly dealt card collides with its auto-burned card; harmless here.
pytestmark = pytest.mark.filterwarnings("ignore::UserWarning")
from pokerkit import Automation as A, NoLimitTexasHoldem  # noqa: E402

from pokergym.agent import CALL, CHECK, FOLD, AgentAdapter, TableInfo, raise_to  # noqa: E402
from pokergym.cards import card_str, fresh_deck  # noqa: E402
from pokergym.engine import play_hand  # noqa: E402
from pokergym.rules import BASELINE_RULES, BlindSchedule  # noqa: E402
from pokergym.testing import PolicyAgent, build_deck  # noqa: E402

AUTOS = (A.ANTE_POSTING, A.BET_COLLECTION, A.BLIND_OR_STRADDLE_POSTING, A.CARD_BURNING,
         A.HOLE_CARDS_SHOWING_OR_MUCKING, A.HAND_KILLING, A.CHIPS_PUSHING, A.CHIPS_PULLING,
         A.RUNOUT_COUNT_SELECTION)


def decide(r, can_raise, can_check, lo, hi, mode, short_open=False):
    # Known divergence (documented in docs/fidelity.md): after checks, a short
    # all-in *opening bet* reopens the action in PokerKit but not in pokergym
    # (TDA rule 43). The policy avoids making that bet so the rest stays strict.
    if can_raise and r < 0.35 and not short_open:
        if mode == "shove":
            return ("raise", hi)
        return ("raise", lo if r < 0.2 else lo + int((hi - lo) * (r * 7 % 1)))
    if r < 0.85 or can_check:
        return ("check" if can_check else "call", 0)
    return ("fold", 0)


def run_pokerkit(stacks, hole, board, stream, blinds, mode):
    n = len(stacks)
    s = NoLimitTexasHoldem.create_state(AUTOS, True, 0, blinds, blinds[1], tuple(stacks), n)
    for r in range(2):
        for p in range(n):
            s.deal_hole(card_str(hole[p][r]))
    i = 0
    bidx = 0
    while s.status:
        if s.can_deal_board():
            cnt = 3 if bidx == 0 else 1
            s.deal_board("".join(card_str(c) for c in board[bidx: bidx + cnt]))
            bidx += cnt
            continue
        if s.actor_index is None:
            break
        can_raise = s.can_complete_bet_or_raise_to()
        lo = s.min_completion_betting_or_raising_to_amount if can_raise else 0
        hi = s.max_completion_betting_or_raising_to_amount if can_raise else 0
        can_check = s.checking_or_calling_amount == 0
        short_open = can_raise and lo == hi and hi < blinds[1] and max(s.bets) == 0
        kind, amt = decide(stream[i], can_raise, can_check, lo, hi, mode, short_open)
        i += 1
        if kind == "raise":
            s.complete_bet_or_raise_to(amt)
        elif kind == "fold":
            s.fold()
        else:
            s.check_or_call()
    return list(s.stacks), i


def run_ours(stacks, hole, board, stream, blinds, mode):
    n = len(stacks)
    rules = BASELINE_RULES.with_(blinds=BlindSchedule(levels=(blinds,)))
    counter = {"i": 0}

    def policy(obs):
        r = stream[counter["i"]]
        counter["i"] += 1
        short_open = obs.can_raise and obs.min_raise_to == obs.max_raise_to and obs.max_raise_to < obs.big_blind and max(obs.bets) == 0
        kind, amt = decide(r, obs.can_raise, obs.can_check, obs.min_raise_to, obs.max_raise_to, mode, short_open)
        if kind == "raise":
            return raise_to(amt)
        if kind == "fold":
            return FOLD
        return CHECK if obs.can_check else CALL

    adapters = [AgentAdapter(PolicyAgent(policy), mode="off") for _ in range(n)]
    for p, ad in enumerate(adapters):
        ad.reset(TableInfo(p, n, stacks[p], "x", p))
    board_str = " ".join(card_str(c) for c in board)
    sb_seat = 0 if n > 2 else 1  # heads-up: the button (seat n-1) posts the small blind
    deck = build_deck({p: " ".join(card_str(c) for c in hole[p]) for p in range(n)}, board_str, sb_seat, list(range(n)))
    st = list(stacks)
    rec = play_hand(rules, rules.ranking.evaluator(), st, n - 1, 0, adapters, random.Random(0), deck=deck)
    return st, counter["i"], rec


@pytest.mark.parametrize("mode", ["shove", "sized"])
def test_final_stacks_match_pokerkit(mode):
    rng = random.Random(2024)
    mismatches = []
    hands = 0
    for case in range(400):
        n = rng.randint(2, 8)
        stacks = [rng.choice([40, 75, 150, 300, 650, 1000, 2000, 3500]) for _ in range(n)]
        deck = fresh_deck()
        rng.shuffle(deck)
        hole = [(deck[2 * p], deck[2 * p + 1]) for p in range(n)]
        board = deck[2 * n: 2 * n + 5]
        stream = [rng.random() for _ in range(300)]
        blinds = (10, 20)
        pk_stacks, pk_dec = run_pokerkit(stacks, hole, board, stream, blinds, mode)
        our_stacks, our_dec, rec = run_ours(stacks, hole, board, stream, blinds, mode)
        hands += 1
        if pk_stacks != our_stacks or pk_dec != our_dec:
            mismatches.append((case, n, stacks, pk_stacks, our_stacks, pk_dec, our_dec,
                               [card_str(c) for h in hole for c in h], [card_str(c) for c in board],
                               rec.to_dict()["actions"]))
    assert not mismatches, mismatches[:3]
    assert hands == 400
