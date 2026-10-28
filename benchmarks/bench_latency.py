"""Decision-latency benchmark.

Two measurements per bot type:
1. In-simulation latency: perf_counter_ns around every ``act`` call during
   full tournaments (deadline_mode="record", so slow calls are not replaced).
2. Isolated latency: the same observations replayed in a tight loop, which
   removes engine work and measures the agent alone.

Also reports full-simulation cost per decision (engine + agent) so the two can
be compared, and the fraction of calls above the 1 ms deadline.

    python benchmarks/bench_latency.py --tournaments 200 --out benchmarks/results/latency.json
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokerlab.agent import TableInfo  # noqa: E402
from pokerlab.bots import BOT_REGISTRY  # noqa: E402
from pokerlab.rules import BASELINE_RULES  # noqa: E402
from pokerlab.tournament import run_tournament  # noqa: E402

MIX = ["call", "random", "heuristic", "random", "heuristic", "call", "random", "heuristic"]


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))
    return xs[k]


def summarize(ns):
    return {
        "n": len(ns),
        "p50_us": pct(ns, 50) / 1000, "p90_us": pct(ns, 90) / 1000, "p99_us": pct(ns, 99) / 1000,
        "p99_9_us": pct(ns, 99.9) / 1000, "max_us": max(ns) / 1000, "mean_us": statistics.fmean(ns) / 1000,
        "over_1ms": sum(1 for x in ns if x > 1_000_000), "over_1ms_frac": sum(1 for x in ns if x > 1_000_000) / len(ns),
    }


class Recorder:
    """Wraps a bot and keeps the observations it saw (for isolated replay)."""

    def __init__(self, bot):
        self.bot = bot
        self.obs = []

    def reset(self, t):
        self.bot.reset(t)

    def act(self, o):
        self.obs.append(o)
        return self.bot.act(o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tournaments", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rules = BASELINE_RULES.with_(deadline_mode="record")
    # warm-up
    for i in range(5):
        run_tournament([BOT_REGISTRY[n]() for n in MIX], rules=rules, seed=10_000 + i, keep_hands=False)

    in_sim = {n: [] for n in BOT_REGISTRY}
    recorders = {n: Recorder(BOT_REGISTRY[n]()) for n in BOT_REGISTRY}
    total_dec = 0
    t0 = time.perf_counter()
    for i in range(a.tournaments):
        bots = [BOT_REGISTRY[n]() for n in MIX]
        r = run_tournament(bots, rules=rules, seed=a.seed + i, keep_hands=False, record_latency=True)
        for name, st in zip(MIX, r.agent_stats):
            in_sim[name].extend(st["latencies_ns"])
            total_dec += st["calls"]
    sim_wall = time.perf_counter() - t0
    # capture observations for isolated replay (separate, untimed run)
    for name, rec in recorders.items():
        bots = [BOT_REGISTRY[n]() for n in MIX]
        seat = MIX.index(name)
        bots[seat] = rec
        for i in range(20):
            run_tournament(bots, rules=rules, seed=a.seed + i, keep_hands=False)

    isolated = {}
    for name, rec in recorders.items():
        bot = BOT_REGISTRY[name]()
        bot.reset(TableInfo(seat=MIX.index(name), num_players=8, starting_stack=2000, rules_name="bench", seed=1))
        obs = rec.obs
        for o in obs[:200]:
            bot.act(o)
        ns = []
        pc = time.perf_counter_ns
        for o in obs:
            t = pc()
            bot.act(o)
            ns.append(pc() - t)
        isolated[name] = summarize(ns)

    out = {
        "command": " ".join(sys.argv),
        "tournaments": a.tournaments,
        "sim_wall_s": sim_wall,
        "sim_decisions": total_dec,
        "sim_us_per_decision_all_in": sim_wall / total_dec * 1e6,
        "in_simulation": {n: summarize(v) for n, v in in_sim.items()},
        "isolated": isolated,
        "timer_overhead_ns": _timer_overhead(),
    }
    print(f"full simulation: {total_dec} decisions in {sim_wall:.2f}s -> {out['sim_us_per_decision_all_in']:.1f} us per decision (engine + agents + timing)")
    print(f"timer overhead ~{out['timer_overhead_ns']:.0f} ns per perf_counter_ns pair")
    print(f"{'bot':<10} {'where':<9} {'n':>7} {'p50':>8} {'p99':>8} {'p99.9':>8} {'max':>9}  >1ms")
    for n in BOT_REGISTRY:
        for where, s in (("in-sim", out["in_simulation"][n]), ("isolated", isolated[n])):
            print(f"{n:<10} {where:<9} {s['n']:>7} {s['p50_us']:>7.1f}u {s['p99_us']:>7.1f}u {s['p99_9_us']:>7.1f}u {s['max_us']:>8.1f}u  {s['over_1ms']} ({s['over_1ms_frac']*100:.3f}%)")
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w") as f:
            json.dump(out, f, indent=1)
        print("wrote", a.out)


def _timer_overhead():
    pc = time.perf_counter_ns
    xs = []
    for _ in range(10000):
        t = pc()
        xs.append(pc() - t)
    return statistics.median(xs)


if __name__ == "__main__":
    main()
