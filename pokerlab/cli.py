"""Command-line entry points.

    python -m pokerlab.cli run    --seed 1 --variant baseline --bots call,random,heuristic,... [--out runs/x.json] [--verify]
    python -m pokerlab.cli replay runs/x.json          # re-run from the record's seed and compare hashes
    python -m pokerlab.cli round  --tables 100 --seed 1 --variant baseline
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from .bots import BOT_REGISTRY
from .checks import check_tournament
from .tournament import run_round, run_tournament
from .variants import VARIANTS

DEFAULT_BOTS = "call,random,heuristic,random,heuristic,call,random,heuristic"


def _bots(spec: str):
    names = spec.split(",")
    if len(names) != 8:
        sys.exit(f"need 8 bots, got {len(names)}: {spec}")
    for n in names:
        if n not in BOT_REGISTRY:
            sys.exit(f"unknown bot {n!r}; known: {sorted(BOT_REGISTRY)}")
    return names, [BOT_REGISTRY[n]() for n in names]


def cmd_run(a):
    rules = VARIANTS[a.variant]
    names, bots = _bots(a.bots)
    t0 = time.perf_counter()
    res = run_tournament(bots, rules=rules, seed=a.seed, keep_hands=True, button_start=a.button)
    dt = time.perf_counter() - t0
    if a.verify:
        check_tournament(res, rules)
    print(f"variant={rules.name}  seed={a.seed}  hands={res.hands_played}  icm={res.icm_applied}  {dt*1000:.1f} ms")
    for s in rules.synthetic_components():
        print(f"  SYNTHETIC {s}")
    print(f"{'seat':>4} {'bot':<10} {'stack':>6} {'pos':>5} {'points':>8}  stats")
    for s in range(rules.players):
        st = res.agent_stats[s]
        print(f"{s:>4} {names[s]:<10} {res.final_stacks[s]:>6} {res.positions[s]:>5.2f} {res.points[s]:>8.3f}  {st}")
    print(f"record_hash={res.record_hash}")
    if a.verify:
        print("invariants: OK")
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        d = res.to_dict(include_hands=True)
        d["bots"] = names
        d["variant"] = a.variant
        with open(a.out, "w") as f:
            json.dump(d, f)
        print(f"wrote {a.out}")


def cmd_replay(a):
    with open(a.record) as f:
        d = json.load(f)
    rules = VARIANTS[d["variant"]]
    names, bots = _bots(",".join(d["bots"]))
    res = run_tournament(bots, rules=rules, seed=d["seed"], keep_hands=True, button_start=d["button_start"])
    ok = res.record_hash == d["record_hash"]
    print(f"replay seed={d['seed']} hands={res.hands_played} hash_match={ok}")
    if not ok:
        sys.exit(1)


def cmd_round(a):
    rules = VARIANTS[a.variant]
    names, _ = _bots(a.bots)
    factories = [BOT_REGISTRY[n] for n in names]
    t0 = time.perf_counter()
    rs = run_round(factories, names, tables=a.tables, seed=a.seed, rules=rules)
    dt = time.perf_counter() - t0
    print(f"variant={rules.name} tables={a.tables} seed={a.seed} hands={rs.hands_total} {dt:.2f}s "
          f"({rs.hands_total/dt:.0f} hands/s, {a.tables/dt:.1f} tables/s)")
    for n, p in zip(rs.bot_names, rs.avg_points):
        print(f"  {n:<10} {p:8.3f}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="pokerlab")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--variant", choices=sorted(VARIANTS), default="baseline")
    r.add_argument("--bots", default=DEFAULT_BOTS)
    r.add_argument("--button", type=int, default=None)
    r.add_argument("--out", default=None)
    r.add_argument("--verify", action="store_true")
    r.set_defaults(fn=cmd_run)
    rp = sub.add_parser("replay")
    rp.add_argument("record")
    rp.set_defaults(fn=cmd_replay)
    rd = sub.add_parser("round")
    rd.add_argument("--tables", type=int, default=100)
    rd.add_argument("--seed", type=int, default=0)
    rd.add_argument("--variant", choices=sorted(VARIANTS), default="baseline")
    rd.add_argument("--bots", default=DEFAULT_BOTS)
    rd.set_defaults(fn=cmd_round)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
