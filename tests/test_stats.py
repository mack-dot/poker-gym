from pokergym.bots import AdaptiveBot, CallBot, RandomBot, TagBot
from pokergym.rules import BASELINE_RULES
from pokergym.stats import OpponentTracker
from pokergym.tournament import run_tournament


def rec(hand, button, actions, start_stacks=None, board=("2c", "7d", "Jh", "3s", "9c"), pots=None):
    n = 8
    return {
        "hand": hand, "button": button, "sb": (button + 1) % n, "bb": (button + 2) % n, "blinds": [10, 20], "ante": 0,
        "start_stacks": start_stacks or [2000] * n, "hole": [["As", "Kd"]] * n, "board": list(board),
        "actions": actions, "pots": pots or [[60, [0], [0]]], "net": [0] * n, "stacks_after": [2000] * n,
    }


def test_vpip_pfr_and_three_bet_from_record():
    t = OpponentTracker(8)
    # button 0: SB 1, BB 2, UTG 3 raises, MP 4 3-bets, others fold, UTG calls.
    t.ingest_record(rec(0, 0, [
        ["preflop", 3, "raise", 60], ["preflop", 4, "raise", 180], ["preflop", 5, "fold", 0], ["preflop", 6, "fold", 0],
        ["preflop", 7, "fold", 0], ["preflop", 0, "fold", 0], ["preflop", 1, "fold", 0], ["preflop", 2, "fold", 0],
        ["preflop", 3, "call", 120],
    ]))
    for s in range(8):
        assert t.profile(s).hands == 1
    assert t.profile(3).vpip == 1 and t.profile(3).pfr == 1
    assert t.profile(4).vpip == 1 and t.profile(4).pfr == 1
    assert t.profile(4).three_bet == 1 and t.profile(4).three_bet_opp == 1
    assert t.profile(5).three_bet_opp == 0  # faced two raises, not one
    assert t.profile(2).vpip == 0
    # Facing exactly one raise: seats 4 only (5,6,7,0,1,2 faced two).
    assert sum(t.profile(s).three_bet_opp for s in range(8)) == 1


def test_steal_and_fold_to_steal():
    t = OpponentTracker(8)
    # Everyone folds to the button (0), who raises; SB (1) folds, BB (2) folds.
    t.ingest_record(rec(0, 0, [
        ["preflop", 3, "fold", 0], ["preflop", 4, "fold", 0], ["preflop", 5, "fold", 0], ["preflop", 6, "fold", 0],
        ["preflop", 7, "fold", 0], ["preflop", 0, "raise", 50], ["preflop", 1, "fold", 0], ["preflop", 2, "fold", 0],
    ]))
    assert t.profile(1).steal_faced == 1 and t.profile(1).fold_to_steal == 1
    assert t.profile(2).steal_faced == 1 and t.profile(2).fold_to_steal == 1
    # A UTG open is not a steal.
    t2 = OpponentTracker(8)
    t2.ingest_record(rec(0, 0, [
        ["preflop", 3, "raise", 50], ["preflop", 4, "fold", 0], ["preflop", 5, "fold", 0], ["preflop", 6, "fold", 0],
        ["preflop", 7, "fold", 0], ["preflop", 0, "fold", 0], ["preflop", 1, "fold", 0], ["preflop", 2, "fold", 0],
    ]))
    assert t2.profile(1).steal_faced == 0 and t2.profile(2).steal_faced == 0
    # A limp before the raise means it is not a steal either.
    t3 = OpponentTracker(8)
    t3.ingest_record(rec(0, 0, [
        ["preflop", 3, "call", 20], ["preflop", 4, "fold", 0], ["preflop", 5, "fold", 0], ["preflop", 6, "fold", 0],
        ["preflop", 7, "raise", 80], ["preflop", 0, "fold", 0], ["preflop", 1, "fold", 0], ["preflop", 2, "fold", 0],
    ]))
    assert t3.profile(1).steal_faced == 0


def test_cbet_and_fold_to_cbet():
    t = OpponentTracker(8)
    acts = [
        ["preflop", 3, "raise", 60], ["preflop", 4, "call", 60], ["preflop", 5, "fold", 0], ["preflop", 6, "fold", 0],
        ["preflop", 7, "fold", 0], ["preflop", 0, "fold", 0], ["preflop", 1, "fold", 0], ["preflop", 2, "call", 40],
        ["flop", 2, "check", 0], ["flop", 3, "raise", 100], ["flop", 4, "fold", 0], ["flop", 2, "call", 100],
        ["turn", 2, "check", 0], ["turn", 3, "check", 0],
    ]
    t.ingest_record(rec(0, 0, acts))
    p3 = t.profile(3)
    assert p3.cbet_opp == 1 and p3.cbet == 1
    assert t.profile(4).fold_to_cbet_opp == 1 and t.profile(4).fold_to_cbet == 1
    assert t.profile(2).fold_to_cbet_opp == 1 and t.profile(2).fold_to_cbet == 0
    assert p3.post_bets == 1 and p3.post_checks == 1
    assert t.profile(2).post_calls == 1 and t.profile(2).post_checks == 2
    # Raiser checks the flop: a missed c-bet opportunity.
    t2 = OpponentTracker(8)
    t2.ingest_record(rec(1, 0, acts[:8] + [["flop", 2, "check", 0], ["flop", 3, "check", 0], ["flop", 4, "raise", 60]]))
    assert t2.profile(3).cbet_opp == 1 and t2.profile(3).cbet == 0
    assert t2.profile(4).fold_to_cbet_opp == 0


def test_rates_shrink_to_prior_then_move():
    t = OpponentTracker(8)
    assert abs(t.profile(0).vpip_rate() - 0.35) < 1e-9
    for h in range(40):
        t.ingest_record(rec(h, 0, [["preflop", 3, "raise", 60]] + [["preflop", s, "fold", 0] for s in (4, 5, 6, 7, 0, 1, 2)]))
    assert t.profile(3).vpip_rate() > 0.85 and t.profile(3).pfr_rate() > 0.85
    assert t.profile(5).vpip_rate() < 0.08
    d = t.to_dict()
    assert d[3]["hands"] == 40 and "vpip_rate" in d[3]


def test_observe_counts_every_hand_the_bot_was_dealt():
    bot = AdaptiveBot()
    bots = [bot, CallBot(), RandomBot(), TagBot(), CallBot(), RandomBot(), TagBot(), RandomBot()]
    res = run_tournament(bots, BASELINE_RULES, seed=11)
    tr = bot.tracker
    assert tr is not None
    # The bot acted at least once in most hands while alive; hands it saw are
    # counted once each for every seat dealt in.
    my_hands = [h for h in res.hands if h.start_stacks[0] > 0]
    assert 0 < tr.profile(0).hands <= len(my_hands)
    # Every seat's hand count is no larger than hands it was dealt in.
    for s in range(8):
        assert tr.profile(s).hands <= sum(1 for h in res.hands if h.start_stacks[s] > 0)
    assert res.agent_stats[0]["illegal"] == 0 and res.agent_stats[0]["errors"] == 0


def test_observe_matches_record_for_actions_seen():
    """In-play observation and post-hoc ingestion agree on preflop stats for
    actions that happened before the observer's last decision."""
    class Spy(TagBot):
        def __init__(self):
            super().__init__()
            self.seen = []

        def act(self, obs):
            self.seen.append(obs)
            return super().act(obs)

    spy = Spy()
    bots = [CallBot(), spy, RandomBot(), TagBot(), CallBot(), RandomBot(), TagBot(), RandomBot()]
    res = run_tournament(bots, BASELINE_RULES, seed=5)
    t_obs = OpponentTracker(8)
    for o in spy.seen:
        t_obs.observe(o)
    # Replay only the prefix of each hand the spy actually saw.
    t_rec = OpponentTracker(8)
    last_seen = {}
    for o in spy.seen:
        last_seen[o.hand_number] = len(o.history)
    for h in res.hands:
        if h.hand_number not in last_seen:
            continue
        d = h.to_dict()
        d["actions"] = d["actions"][: last_seen[h.hand_number]]
        d["pots"] = []
        t_rec.ingest_record(d)
    for s in range(8):
        a, b = t_obs.profile(s), t_rec.profile(s)
        assert (a.hands, a.vpip, a.pfr, a.three_bet, a.three_bet_opp, a.steal_faced, a.fold_to_steal, a.cbet, a.cbet_opp) == \
               (b.hands, b.vpip, b.pfr, b.three_bet, b.three_bet_opp, b.steal_faced, b.fold_to_steal, b.cbet, b.cbet_opp)
