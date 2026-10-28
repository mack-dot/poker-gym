"""Command-line entry points.

    python -m pokergym.cli run    --seed 1 --variant baseline --bots call,random,heuristic,... [--out runs/x.json] [--verify]
    python -m pokergym.cli replay runs/x.json          # re-run from the record's seed and compare hashes
    python -m pokergym.cli round  --tables 100 --seed 1 --variant baseline
    python -m pokergym.cli eval   --bot my_bot.py:MyBot --vs sparring --tables 1000 --baseline tag --workers 8
    python -m pokergym.cli ladder --bots tag,lag,shortstack,icm,adaptive,heuristic,random,call --tables 500
    python -m pokergym.cli show   runs/x.json --seat 3 --hands 0-20
    python -m pokergym.cli equity AsKd --board 7s8s2c --opponents 2 --samples 20000

Bot specs: a registry name, ``path/to/file.py:ClassName``, or ``pkg.module:ClassName``;
append ``@label`` to name it in reports.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

from .bots import BOT_REGISTRY
from .cards import card_str, parse_cards
from .checks import check_tournament
from .gym import LINEUPS, evaluate, ladder, load_bot_class, resolve_lineup, split_label
from .tournament import run_round, run_tournament
from .variants import VARIANTS

DEFAULT_BOTS = "call,random,heuristic,random,heuristic,call,random,heuristic"


def _bots(spec: str):
    names = spec.split(",")
    if len(names) != 8:
        sys.exit(f"need 8 bots, got {len(names)}: {spec}")
    try:
        classes = [load_bot_class(n) for n in names]
    except ValueError as e:
        sys.exit(str(e))
    return [split_label(n)[1] for n in names], [c() for c in classes], names


def cmd_run(a):
    rules = VARIANTS[a.variant]
    names, bots, specs = _bots(a.bots)
    t0 = time.perf_counter()
    res = run_tournament(bots, rules=rules, seed=a.seed, keep_hands=True, button_start=a.button)
    dt = time.perf_counter() - t0
    if a.verify:
        check_tournament(res, rules)
    print(f"variant={rules.name}  seed={a.seed}  hands={res.hands_played}  icm={res.icm_applied}  {dt*1000:.1f} ms")
    for s in rules.synthetic_components():
        print(f"  SYNTHETIC {s}")
    print(f"{'seat':>4} {'bot':<12} {'stack':>6} {'pos':>5} {'points':>8}  stats")
    for s in range(rules.players):
        st = res.agent_stats[s]
        print(f"{s:>4} {names[s]:<12} {res.final_stacks[s]:>6} {res.positions[s]:>5.2f} {res.points[s]:>8.3f}  {st}")
    print(f"record_hash={res.record_hash}")
    if a.verify:
        print("invariants: OK")
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        d = res.to_dict(include_hands=True)
        d["bots"] = specs
        d["variant"] = a.variant
        with open(a.out, "w") as f:
            json.dump(d, f)
        print(f"wrote {a.out}")


def cmd_replay(a):
    with open(a.record) as f:
        d = json.load(f)
    rules = VARIANTS[d["variant"]]
    names, bots, _ = _bots(",".join(d["bots"]))
    res = run_tournament(bots, rules=rules, seed=d["seed"], keep_hands=True, button_start=d["button_start"])
    ok = res.record_hash == d["record_hash"]
    print(f"replay seed={d['seed']} hands={res.hands_played} hash_match={ok}")
    if not ok:
        sys.exit(1)


def cmd_round(a):
    rules = VARIANTS[a.variant]
    names, _, specs = _bots(a.bots)
    factories = [load_bot_class(n) for n in specs]
    t0 = time.perf_counter()
    rs = run_round(factories, names, tables=a.tables, seed=a.seed, rules=rules)
    dt = time.perf_counter() - t0
    print(f"variant={rules.name} tables={a.tables} seed={a.seed} hands={rs.hands_total} {dt:.2f}s "
          f"({rs.hands_total/dt:.0f} hands/s, {a.tables/dt:.1f} tables/s)")
    for n, p in zip(rs.bot_names, rs.avg_points):
        print(f"  {n:<12} {p:8.3f}")


def cmd_eval(a):
    rules = VARIANTS[a.variant]
    try:
        rep = evaluate(a.bot, lineup=a.vs, tables=a.tables, seed=a.seed, rules=rules,
                       baseline=a.baseline, workers=a.workers, keep_tables=bool(a.out))
    except ValueError as e:
        sys.exit(str(e))
    print(rep.format())
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w") as f:
            json.dump(rep.to_dict(include_tables=True), f)
        print(f"wrote {a.out}")


def cmd_ladder(a):
    rules = VARIANTS[a.variant]
    specs = resolve_lineup(a.bots)
    try:
        rep = ladder(specs, tables=a.tables, seed=a.seed, rules=rules, workers=a.workers)
    except ValueError as e:
        sys.exit(str(e))
    print(rep.format())
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w") as f:
            json.dump(rep.to_dict(), f)
        print(f"wrote {a.out}")


def _parse_range(text: str, upper: int) -> range:
    if text is None:
        return range(upper)
    if "-" in text:
        lo, hi = text.split("-", 1)
        return range(int(lo or 0), min(upper, int(hi) + 1 if hi else upper))
    v = int(text)
    return range(v, v + 1)


def cmd_show(a):
    """Human-readable hand history from a saved record."""
    with open(a.record) as f:
        d = json.load(f)
    labels = [split_label(s)[1] for s in d.get("bots", [str(i) for i in range(8)])]
    hands = d["hands"]
    print(f"record seed={d['seed']} variant={d.get('variant')} hands={len(hands)} hash={d['record_hash'][:12]}…")
    print("seats: " + "  ".join(f"{i}={labels[i]}" for i in range(len(labels))))
    shown = 0
    for h in hands:
        if h["hand"] not in _parse_range(a.hands, len(hands)):
            continue
        if a.seat is not None and not a.all:
            s = a.seat
            played = any(seat == s and kind != "fold" for (_, seat, kind, _) in h["actions"])
            if h["start_stacks"][s] == 0 or not (played or h["net"][s] > 0):
                continue  # skip hands the seat only folded (or was not dealt in)
        shown += 1
        sb, bb = h["blinds"]
        print(f"\n--- hand {h['hand']}  blinds {sb}/{bb}  button seat {h['button']}  (SB {h['sb']}, BB {h['bb']})")
        live = [s for s in range(len(h["start_stacks"])) if h["start_stacks"][s] > 0]
        for s in live:
            hole = h["hole"][s]
            print(f"    seat {s} {labels[s]:<12} {h['start_stacks'][s]:>6}  [{' '.join(hole) if hole else '--'}]")
        street_names = ["preflop", "flop", "turn", "river"]
        board = h["board"]
        cur = None
        for (st, seat, kind, amt) in h["actions"]:
            if st != cur:
                cur = st
                idx = street_names.index(st)
                shown_board = board[: (0, 3, 4, 5)[idx]]
                print(f"  {st:<8} {' '.join(shown_board)}")
            txt = kind if kind in ("fold", "check") else (f"call {amt}" if kind == "call" else f"raise to {amt}")
            print(f"           seat {seat} {labels[seat]:<12} {txt}")
        if any(len(eligible) > 1 for (_, eligible, _) in h["pots"]):
            print(f"  showdown {' '.join(board)}")
        for amt, eligible, winners in h["pots"]:
            print(f"  pot {amt:>6} -> seats {winners}" + (f"  (eligible {eligible})" if len(eligible) > len(winners) else ""))
        net = "  ".join(f"{s}:{h['net'][s]:+d}" for s in live if h["net"][s] != 0)
        print(f"  net     {net}")
    print(f"\n{shown} hands shown")


def cmd_equity(a):
    from .equity import (
        class_index, class_name, equity_vs_random, equity_vs_top, hand_percentile, preflop_equity, range_from_top,
        equity_vs_ranges, PREFLOP_META,
    )

    hole = parse_cards(a.hand)
    board = parse_cards(a.board) if a.board else []
    if len(hole) != 2 or len(board) not in (0, 3, 4, 5):
        sys.exit("need two hole cards and 0/3/4/5 board cards")
    rng = random.Random(a.seed)
    print(f"hand {card_str(hole[0])} {card_str(hole[1])}  class {class_name(class_index(*hole))}"
          f"  percentile {hand_percentile(*hole)*100:.1f}%  (top X% by heads-up equity)")
    if not board:
        print("preflop table: " + "  ".join(f"{n}opp={preflop_equity(hole[0], hole[1], n):.3f}" for n in range(1, 8)))
        print("vs top-X% range (HU): " + "  ".join(f"{int(fr*100)}%={equity_vs_top(hole[0], hole[1], fr):.3f}" for fr in (0.05, 0.1, 0.2, 0.3, 0.5, 1.0)))
        print(f"table meta: samples/class={PREFLOP_META.get('samples_per_class')} seed={PREFLOP_META.get('seed')}")
    t0 = time.perf_counter()
    eq = equity_vs_random(hole, board, a.opponents, a.samples, rng)
    dt = time.perf_counter() - t0
    se = (eq * (1 - eq) / a.samples) ** 0.5
    print(f"monte carlo vs {a.opponents} random: {eq:.4f} ± {1.96*se:.4f} (95%)  board [{' '.join(card_str(c) for c in board)}]  {a.samples} samples in {dt*1000:.0f} ms")
    if a.range:
        rngs = [range_from_top(float(a.range))] * a.opponents
        eq2 = equity_vs_ranges(hole, board, rngs, a.samples, rng)
        print(f"vs {a.opponents} x top-{float(a.range)*100:.0f}% range: {eq2:.4f}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="pokergym")
    sub = p.add_subparsers(dest="cmd", required=True)
    variants = sorted(VARIANTS)

    r = sub.add_parser("run", help="one sit-and-go")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--variant", choices=variants, default="baseline")
    r.add_argument("--bots", default=DEFAULT_BOTS, help=f"8 comma-separated bot specs; registry: {','.join(BOT_REGISTRY)}")
    r.add_argument("--button", type=int, default=None)
    r.add_argument("--out", default=None)
    r.add_argument("--verify", action="store_true")
    r.set_defaults(fn=cmd_run)

    rp = sub.add_parser("replay", help="replay a saved record and compare hashes")
    rp.add_argument("record")
    rp.set_defaults(fn=cmd_replay)

    rd = sub.add_parser("round", help="a scored round (random seating per table)")
    rd.add_argument("--tables", type=int, default=100)
    rd.add_argument("--seed", type=int, default=0)
    rd.add_argument("--variant", choices=variants, default="baseline")
    rd.add_argument("--bots", default=DEFAULT_BOTS)
    rd.set_defaults(fn=cmd_round)

    ev = sub.add_parser("eval", help="evaluate one bot against a lineup")
    ev.add_argument("--bot", required=True, help="bot spec (registry name, file.py:Class, pkg.mod:Class)")
    ev.add_argument("--vs", default="sparring", help=f"lineup name ({', '.join(LINEUPS)}) or comma-separated specs")
    ev.add_argument("--tables", type=int, default=500)
    ev.add_argument("--seed", type=int, default=1)
    ev.add_argument("--variant", choices=variants, default="baseline")
    ev.add_argument("--baseline", default=None, help="bot spec replayed in the same seats for a paired comparison")
    ev.add_argument("--workers", type=int, default=1)
    ev.add_argument("--out", default=None)
    ev.set_defaults(fn=cmd_eval)

    ld = sub.add_parser("ladder", help="all bots against each other")
    ld.add_argument("--bots", default="tag,lag,shortstack,icm,adaptive,heuristic,random,call")
    ld.add_argument("--tables", type=int, default=300)
    ld.add_argument("--seed", type=int, default=1)
    ld.add_argument("--variant", choices=variants, default="baseline")
    ld.add_argument("--workers", type=int, default=1)
    ld.add_argument("--out", default=None)
    ld.set_defaults(fn=cmd_ladder)

    sh = sub.add_parser("show", help="print hands from a saved record")
    sh.add_argument("record")
    sh.add_argument("--seat", type=int, default=None, help="only hands this seat took part in")
    sh.add_argument("--hands", default=None, help="hand range, e.g. 0-20 or 57")
    sh.add_argument("--all", action="store_true", help="show every hand and all hole cards")
    sh.set_defaults(fn=cmd_show)

    eq = sub.add_parser("equity", help="equity of a hand")
    eq.add_argument("hand", help="e.g. AsKd")
    eq.add_argument("--board", default="")
    eq.add_argument("--opponents", type=int, default=1)
    eq.add_argument("--samples", type=int, default=20000)
    eq.add_argument("--range", default=None, help="opponents hold the top fraction of hands, e.g. 0.2")
    eq.add_argument("--seed", type=int, default=0)
    eq.set_defaults(fn=cmd_equity)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
