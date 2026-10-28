"""Sparring bots adopt the variant's hand ranking through configure(rules)."""
from pokergym.bots import SPARRING_BOTS, TagBot
from pokergym.bots.features import hand_features
from pokergym.cards import parse_cards
from pokergym.checks import check_tournament
from pokergym.evaluator import FLUSH, FULL_HOUSE, STANDARD_EVALUATOR
from pokergym.gym import instantiate
from pokergym.tournament import run_tournament
from pokergym.variants import VARIANTS


def test_configure_sets_the_variant_evaluator():
    rules = VARIANTS["flush-beats-full-house"]
    bot = instantiate("tag", rules)
    assert bot.evaluator.name == rules.ranking.name
    assert bot.evaluator.strength != STANDARD_EVALUATOR.strength
    plain = TagBot()
    assert plain.evaluator is STANDARD_EVALUATOR
    assert not hasattr(instantiate("call", rules), "evaluator")  # fixtures ignore the hook


def test_features_use_the_given_evaluator():
    ev = VARIANTS["flush-beats-full-house"].ranking.evaluator()
    flush = (parse_cards("AhKh"), parse_cards("Qh9h2h3c4d"))
    boat = (parse_cards("QsQc"), parse_cards("Qh9h9c3c4d"))
    std_f, std_b = hand_features(*flush).value, hand_features(*boat).value
    var_f, var_b = hand_features(*flush, evaluator=ev).value, hand_features(*boat, evaluator=ev).value
    assert std_b > std_f and var_f > var_b
    assert hand_features(*flush, evaluator=ev).category == FLUSH
    assert hand_features(*boat, evaluator=ev).category == FULL_HOUSE


def test_sparring_bots_configured_for_each_variant_play_legally():
    for name, rules in VARIANTS.items():
        for seed in range(4):
            bots = [instantiate(s, rules) for s in list(SPARRING_BOTS) + ["tag", "lag", "icm"]]
            res = run_tournament(bots, rules, seed=seed)
            check_tournament(res, rules)
            assert all(st["illegal"] == 0 and st["errors"] == 0 for st in res.agent_stats), (name, seed)
