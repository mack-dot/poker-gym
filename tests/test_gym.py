import os
import textwrap

import pytest

from pokergym.bots import TagBot
from pokergym.gym import LINEUPS, evaluate, ladder, load_bot_class, resolve_lineup, split_label
from pokergym.rules import BASELINE_RULES
from pokergym.tournament import run_tournament
from pokergym.variants import VARIANTS


def test_load_bot_from_registry_module_and_file(tmp_path):
    assert load_bot_class("tag") is TagBot
    assert load_bot_class("pokergym.bots.sparring:LagBot").name == "lag"
    assert load_bot_class("tag@mine") is TagBot
    assert split_label("x.py:Bot@v2") == ("x.py:Bot", "v2")
    p = tmp_path / "my_bot.py"
    p.write_text(textwrap.dedent("""
        from pokergym.agent import CHECK, FOLD
        class MyBot:
            def reset(self, table): pass
            def act(self, obs): return CHECK if obs.can_check else FOLD
    """))
    cls = load_bot_class(f"{p}:MyBot")
    assert cls.__name__ == "MyBot"
    bots = [cls() for _ in range(8)]
    res = run_tournament(bots, BASELINE_RULES, seed=1)
    assert sum(st["illegal"] for st in res.agent_stats) == 0


def test_load_bot_errors(tmp_path):
    with pytest.raises(ValueError):
        load_bot_class("nope")
    with pytest.raises(ValueError):
        load_bot_class("pokergym.bots.sparring:Missing")
    p = tmp_path / "bad.py"
    p.write_text("class NotABot:\n    pass\n")
    with pytest.raises(ValueError):
        load_bot_class(f"{p}:NotABot")


def test_resolve_lineup():
    assert resolve_lineup("sparring") == LINEUPS["sparring"]
    assert resolve_lineup("tag,lag") == ["tag", "lag"]
    assert resolve_lineup(["call"]) == ["call"]
    for name, specs in LINEUPS.items():
        assert len(specs) == 7, name
        for s in specs:
            load_bot_class(s)


def test_evaluate_is_deterministic_and_reports_sane_numbers():
    a = evaluate("tag", lineup="fixtures", tables=12, seed=5)
    b = evaluate("tag", lineup="fixtures", tables=12, seed=5)
    assert a.mean_points == b.mean_points and a.finish_hist == b.finish_hist
    assert a.tables == 12 and sum(a.finish_hist.values()) == 12
    assert 0 <= a.win_rate <= 1 and 0 <= a.cash_rate <= 1
    assert a.stats["calls"] > 0 and a.stats["illegal"] == 0
    assert set(a.opponent_points) <= set(LINEUPS["fixtures"])
    assert a.synthetic  # payouts/blinds are synthetic and must be labelled
    txt = a.format()
    assert "points/table" in txt and "SYNTHETIC" in txt
    d = a.to_dict()
    assert d["ci95"][0] <= d["mean_points"] <= d["ci95"][1]


def test_evaluate_paired_baseline_with_itself_is_exactly_zero():
    rep = evaluate("tag", lineup="sparring", tables=10, seed=9, baseline="tag")
    assert rep.diff_mean == 0.0 and rep.diff_se == 0.0
    assert rep.baseline_mean == rep.mean_points
    assert "not distinguishable" in rep.format()


def test_evaluate_candidate_seat_and_opponents_change_per_table():
    rep = evaluate("tag", lineup="mixed", tables=16, seed=2, keep_tables=True)
    seats = {r["seat"] for r in rep.per_table}
    assert len(seats) > 1
    assert all(len(r["opps"]) == 7 for r in rep.per_table)
    assert all(r["bust_hand"] is None or r["bust_hand"] < r["hands"] for r in rep.per_table)


def test_evaluate_multiprocess_matches_single_process():
    a = evaluate("lag", lineup="fixtures", tables=8, seed=4, workers=1, keep_tables=True)
    b = evaluate("lag", lineup="fixtures", tables=8, seed=4, workers=2, keep_tables=True)
    assert [r["points"] for r in a.per_table] == [r["points"] for r in b.per_table]


def test_evaluate_with_variant_rules():
    rep = evaluate("shortstack", lineup="fixtures", tables=4, seed=1, rules=VARIANTS["pot-limit"])
    assert rep.rules == VARIANTS["pot-limit"].name
    assert rep.stats["illegal"] == 0


def test_ladder_fills_and_samples_seats():
    # fewer than 8: fillers do not score, every bot scores once per table
    rep = ladder(["tag", "call", "random"], tables=6, seed=1)
    assert rep.seats_played == [6, 6, 6]
    # more than 8: each table draws 8
    specs = ["tag", "lag", "shortstack", "icm", "adaptive", "heuristic", "random", "call", "tag@second"]
    rep = ladder(specs, tables=6, seed=1)
    assert sum(rep.seats_played) == 6 * 8
    assert rep.labels[-1] == "second"
    assert "rank" in rep.format()


def test_elimination_hands_recorded():
    bots = [TagBot() for _ in range(8)]
    res = run_tournament(bots, BASELINE_RULES, seed=3)
    assert len(res.elimination_hands) == len(res.elimination_order)
    assert all(0 <= h < res.hands_played for h in res.elimination_hands)
    assert res.elimination_hands == sorted(res.elimination_hands)
    assert "elimination_hands" in res.to_dict(include_hands=False)


def test_cli_eval_and_ladder_and_equity(tmp_path, capsys):
    from pokergym.cli import main

    out = tmp_path / "eval.json"
    main(["eval", "--bot", "tag", "--vs", "fixtures", "--tables", "3", "--seed", "1", "--baseline", "call", "--out", str(out)])
    captured = capsys.readouterr().out
    assert "vs baseline call" in captured and out.exists()
    main(["ladder", "--bots", "tag,call", "--tables", "2"])
    assert "ladder: 2 bots" in capsys.readouterr().out
    main(["equity", "AsKs", "--opponents", "2", "--samples", "500"])
    txt = capsys.readouterr().out
    assert "class AKs" in txt and "monte carlo" in txt
    main(["equity", "AsKs", "--board", "Ks7d2c", "--samples", "500", "--range", "0.3"])
    assert "range" in capsys.readouterr().out
    rec = tmp_path / "run.json"
    main(["run", "--seed", "2", "--bots", "tag,lag,call,random,icm,adaptive,shortstack,heuristic", "--out", str(rec)])
    capsys.readouterr()
    main(["show", str(rec), "--hands", "0-5"])
    txt = capsys.readouterr().out
    assert "hand 0" in txt and "6 hands shown" in txt
    main(["show", str(rec), "--seat", "0", "--hands", "0-5"])
    txt = capsys.readouterr().out
    assert "hands shown" in txt and "hand 0" not in txt  # seat 0 only folded hand 0
    assert os.path.exists(rec)
