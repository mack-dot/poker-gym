"""Variant verification: behaviour changes exactly where the spec says, and
nowhere else; invariants hold; full tournaments run; replays are seeded."""
from pokerlab.bots import CallBot, HeuristicBot, RandomBot
from pokerlab.checks import check_tournament
from pokerlab.evaluator import FLUSH, FULL_HOUSE
from pokerlab.tournament import run_tournament
from pokerlab.variants import VARIANT_A_FLUSH_BEATS_FULL_HOUSE, VARIANT_B_POT_LIMIT, VARIANTS
from pokerlab.rules import BASELINE_RULES


def mixed():
    return [CallBot(), RandomBot(), HeuristicBot(), RandomBot(), HeuristicBot(), CallBot(), RandomBot(), HeuristicBot()]


def test_variant_a_diverges_only_at_flush_vs_full_house_showdowns():
    ev = BASELINE_RULES.ranking.evaluator()
    diverged = 0
    for seed in range(120):
        a = run_tournament(mixed(), rules=BASELINE_RULES, seed=seed)
        b = run_tournament(mixed(), rules=VARIANT_A_FLUSH_BEATS_FULL_HOUSE, seed=seed)
        check_tournament(b, VARIANT_A_FLUSH_BEATS_FULL_HOUSE)
        if a.record_hash == b.record_hash:
            continue
        diverged += 1
        first = next(i for i, (x, y) in enumerate(zip(a.hands, b.hands)) if x.to_dict() != y.to_dict())
        rec = a.hands[first]
        cats = {ev.category(v) for v in rec.showdown_values.values()}
        assert FLUSH in cats and FULL_HOUSE in cats, (seed, first, cats)
        # and under the variant the flush holder takes the pot the boat took in baseline
        brec = b.hands[first]
        boat_winner_pots = [p for p in rec.pots if ev.category(rec.showdown_values[p[2][0]]) == FULL_HOUSE]
        assert boat_winner_pots
        for amt, elig, winners in brec.pots:
            if any(ev.category(rec.showdown_values[w]) == FULL_HOUSE for w in winners):
                raise AssertionError("full house still won under flush-beats-full-house")
    assert diverged >= 3


def _first_open_raises(result):
    """Preflop opening raise sizes when nobody limped first."""
    out = []
    for rec in result.hands:
        pre = [a for a in rec.actions if a[0] == 0]
        for (_, seat, kind, amt) in pre:
            if kind == 0:  # fold
                continue
            if kind == 3:
                out.append(amt)
            break  # first non-fold action decides
    return out


def test_variant_b_bounds_opening_raise_to_pot():
    nl_opens = []
    pl_opens = []
    for seed in range(30):
        nl_opens += _first_open_raises(run_tournament(mixed(), rules=BASELINE_RULES, seed=seed))
        r = run_tournament(mixed(), rules=VARIANT_B_POT_LIMIT, seed=seed)
        check_tournament(r, VARIANT_B_POT_LIMIT)
        # opening raise bound at 10/20 with no ante: 20 + 20 + 30 = 70 = 3.5 BB; scale by level
        for rec in r.hands:
            sb, bb = rec.blinds
            pre = [a for a in rec.actions if a[0] == 0]
            for (_, seat, kind, amt) in pre:
                if kind == 0:
                    continue
                if kind == 3:
                    assert amt <= bb + bb + (sb + bb), (seed, rec.hand_number, amt, rec.blinds)
                    pl_opens.append(amt / bb)
                break
    assert any(o > 3.5 for o in pl_opens) is False
    assert any(o > 70 for o in nl_opens)  # no-limit lets bots open bigger


def test_variant_replays_are_seeded_and_reproducible():
    for name, rules in VARIANTS.items():
        a = run_tournament(mixed(), rules=rules, seed=2026)
        b = run_tournament(mixed(), rules=rules, seed=2026)
        assert a.record_hash == b.record_hash and a.rules_name == rules.name
