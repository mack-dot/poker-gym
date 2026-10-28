"""Throughput benchmark: hands/s, tournaments/s, decisions/s, CPU, memory,
single-core and multi-process scaling.

    python benchmarks/bench_throughput.py --tournaments 100 1000 --workers 1 2 4 8 --out benchmarks/results/throughput.json

Methodology
- Every process runs WARMUP tournaments first; those are excluded from timing.
- Timing covers full tournaments (seating, dealing, betting, showdown, scoring).
- Seeds: tournament i uses seed = base_seed + i, so every configuration plays
  the same tournaments.
- CPU time is process_time (all threads of the measuring process); for
  multi-process runs the children report their own CPU time which is summed.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import platform
import resource
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokerlab import __version__  # noqa: E402
from pokerlab.bots import BOT_REGISTRY  # noqa: E402
from pokerlab.tournament import run_tournament  # noqa: E402
from pokerlab.variants import VARIANTS  # noqa: E402

WARMUP = 5
MIXES = {
    "mixed": ["call", "random", "heuristic", "random", "heuristic", "call", "random", "heuristic"],
    "heuristic": ["heuristic"] * 8,
    "call": ["call"] * 8,  # worst case: 200 hands, 8-way showdowns, ~24 decisions per hand
}


def _bots(mix):
    return [BOT_REGISTRY[n]() for n in MIXES[mix]]


def _machine():
    def sysctl(key):
        try:
            return subprocess.check_output(["sysctl", "-n", key], text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:  # noqa: BLE001
            return None

    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu": sysctl("machdep.cpu.brand_string") or platform.processor(),
        "cores_logical": os.cpu_count(),
        "cores_physical": sysctl("hw.physicalcpu"),
        "perf_cores": sysctl("hw.perflevel0.physicalcpu"),
        "eff_cores": sysctl("hw.perflevel1.physicalcpu"),
        "memory_bytes": sysctl("hw.memsize"),
        "python": sys.version.split()[0],
        "pokerlab": __version__,
    }


def _worker(args):
    mix, variant, seeds, deadline_mode = args
    rules = VARIANTS[variant].with_(deadline_mode=deadline_mode)
    for i in range(WARMUP):
        run_tournament(_bots(mix), rules=rules, seed=10_000_000 + i, keep_hands=False)
    hands = dec = 0
    t0 = time.perf_counter()
    c0 = time.process_time()
    for s in seeds:
        r = run_tournament(_bots(mix), rules=rules, seed=s, keep_hands=False)
        hands += r.hands_played
        dec += sum(a["calls"] for a in r.agent_stats)
    wall = time.perf_counter() - t0
    cpu = time.process_time() - c0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {"tournaments": len(seeds), "hands": hands, "decisions": dec, "wall_s": wall, "cpu_s": cpu, "max_rss_bytes": rss}


def run_config(mix, variant, n, workers, base_seed, deadline_mode):
    seeds = list(range(base_seed, base_seed + n))
    if workers == 1:
        t0 = time.perf_counter()
        res = [_worker((mix, variant, seeds, deadline_mode))]
        wall = time.perf_counter() - t0
        wall_timed = res[0]["wall_s"]
    else:
        chunks = [seeds[i::workers] for i in range(workers)]
        ctx = mp.get_context("spawn")
        with ctx.Pool(workers) as pool:
            # warm the pool (imports + warm-up tournaments) before timing
            pool.map(_worker, [(mix, variant, [], deadline_mode)] * workers)
            t0 = time.perf_counter()
            res = pool.map(_worker, [(mix, variant, c, deadline_mode) for c in chunks])
            wall = time.perf_counter() - t0
        wall_timed = wall
    hands = sum(r["hands"] for r in res)
    dec = sum(r["decisions"] for r in res)
    cpu = sum(r["cpu_s"] for r in res)
    return {
        "mix": mix, "variant": variant, "tournaments": n, "workers": workers, "base_seed": base_seed,
        "deadline_mode": deadline_mode, "hands": hands, "decisions": dec, "wall_s": wall_timed, "cpu_s": cpu,
        "hands_per_s": hands / wall_timed, "tournaments_per_s": n / wall_timed, "decisions_per_s": dec / wall_timed,
        "hands_per_tournament": hands / n, "max_rss_bytes_per_process": max(r["max_rss_bytes"] for r in res),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tournaments", type=int, nargs="+", default=[100, 1000])
    ap.add_argument("--workers", type=int, nargs="+", default=[1])
    ap.add_argument("--mix", nargs="+", default=["mixed"], choices=sorted(MIXES))
    ap.add_argument("--variant", default="baseline", choices=sorted(VARIANTS))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--deadline-mode", default="enforce", choices=["enforce", "record", "off"])
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out = {"machine": _machine(), "command": " ".join(sys.argv), "warmup_tournaments": WARMUP, "results": []}
    print(json.dumps(out["machine"], indent=1))
    for mix in a.mix:
        for n in a.tournaments:
            for w in a.workers:
                r = run_config(mix, a.variant, n, w, a.seed, a.deadline_mode)
                out["results"].append(r)
                print(f"{mix:<9} n={n:<6} workers={w} | {r['hands_per_s']:>8.0f} hands/s "
                      f"{r['tournaments_per_s']:>7.1f} t/s {r['decisions_per_s']:>8.0f} dec/s | "
                      f"wall {r['wall_s']:.2f}s cpu {r['cpu_s']:.2f}s rss {r['max_rss_bytes_per_process']/1e6:.0f}MB "
                      f"| {r['hands_per_tournament']:.0f} hands/t", flush=True)
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w") as f:
            json.dump(out, f, indent=1)
        print("wrote", a.out)


if __name__ == "__main__":
    main()
