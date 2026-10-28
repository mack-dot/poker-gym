"""Arena environment benchmark (rehearsal infrastructure, not poker strength).

    python benchmarks/bench_arena.py --out benchmarks/results/arena.json [--eval-tables 100 1000 10000] [--workers 1 2 4 8]

Sections
  throughput      tournaments/s with the HIDDEN lineup + heuristic candidate under
                  deadline off / record / enforce (the cost of deadline enforcement)
  eval_time       wall time of a full hidden evaluation at 100 / 1000 / 10000 tables
                  (candidate + adapted reference paired, plus baseline-game and
                  naive-reference runs) for the given worker counts
  serialization   Observation.to_dict + json.dumps cost per decision (what an
                  out-of-process agent protocol would add)
  startup         sandboxed interpreter start, kit import, template validation wall time
  reproducibility hidden evaluation run twice with the same seed -> identical rows?

Caveats: numbers depend on host load (the load average is recorded). Deadline
timing in Python is wall-clock sampling around the call; it is not an
official-harness measurement.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks.bench_throughput import _machine  # noqa: E402
from pokergym.arena import isolation  # noqa: E402
from pokergym.arena.hidden_eval import hidden_evaluate  # noqa: E402
from pokergym.arena.hidden_opponents import HIDDEN_LINEUP  # noqa: E402
from pokergym.arena.session import Challenge  # noqa: E402
from pokergym.arena.workspace import AGENT_TEMPLATE  # noqa: E402
from pokergym.gym import instantiate  # noqa: E402
from pokergym.rules import BASELINE_RULES  # noqa: E402
from pokergym.tournament import run_tournament  # noqa: E402


def _load():
    try:
        return os.getloadavg()[0]
    except OSError:
        return None


def bench_throughput(n: int, seeds0: int = 1000) -> list[dict]:
    out = []
    for mode in ("off", "record", "enforce"):
        rules = BASELINE_RULES.with_(deadline_mode=mode)
        hands = dec = timeouts = 0
        t0 = time.perf_counter()
        for s in range(n):
            bots = [instantiate(x, rules) for x in HIDDEN_LINEUP] + [instantiate("heuristic", rules)]
            r = run_tournament(bots, rules, seed=seeds0 + s, keep_hands=False)
            hands += r.hands_played
            dec += sum(a["calls"] for a in r.agent_stats)
            timeouts += sum(a["timeouts"] for a in r.agent_stats)
        wall = time.perf_counter() - t0
        out.append({"deadline_mode": mode, "tournaments": n, "wall_s": wall, "tournaments_per_s": n / wall,
                    "hands_per_s": hands / wall, "decisions_per_s": dec / wall, "decisions_over_1ms": timeouts,
                    "over_1ms_frac": timeouts / max(1, dec)})
        print(f"throughput {mode:8s} {n} tournaments: {n/wall:7.1f} t/s  {hands/wall:8.0f} hands/s  "
              f"{dec/wall:8.0f} dec/s  >1ms {timeouts}/{dec}", flush=True)
    return out


def bench_serialization(samples: int = 2000) -> dict:
    """Record real observations from a tournament and time to_dict + json."""
    obs_list = []

    class Rec:
        def reset(self, table):
            pass

        def act(self, obs):
            if len(obs_list) < samples:
                obs_list.append(obs)
            from pokergym.agent import Action, ActionType
            return Action(ActionType.CHECK) if obs.can_check else Action(ActionType.FOLD)

    rules = BASELINE_RULES.with_(deadline_mode="off")
    s = 0
    while len(obs_list) < samples:
        bots = [Rec()] + [instantiate(x, rules) for x in HIDDEN_LINEUP]
        run_tournament(bots, rules, seed=50_000 + s, keep_hands=False)
        s += 1
    t0 = time.perf_counter()
    dicts = [o.to_dict() for o in obs_list]
    t1 = time.perf_counter()
    blobs = [json.dumps(d) for d in dicts]
    t2 = time.perf_counter()
    for b in blobs:
        json.loads(b)
    t3 = time.perf_counter()
    n = len(obs_list)
    r = {"samples": n, "to_dict_us": (t1 - t0) / n * 1e6, "json_dumps_us": (t2 - t1) / n * 1e6,
         "json_loads_us": (t3 - t2) / n * 1e6, "bytes_mean": statistics.fmean(len(b) for b in blobs)}
    r["round_trip_us"] = r["to_dict_us"] + r["json_dumps_us"] + r["json_loads_us"]
    print(f"serialization: to_dict {r['to_dict_us']:.1f} us, dumps {r['json_dumps_us']:.1f} us, loads {r['json_loads_us']:.1f} us, "
          f"{r['bytes_mean']:.0f} bytes/obs", flush=True)
    return r


def bench_startup(ch: Challenge) -> dict:
    py = isolation.competitor_python()
    pol = ch.policy()

    def timed(argv, cwd):
        t0 = time.perf_counter()
        cp = isolation.run(pol, argv, cwd=cwd, timeout=120)
        return time.perf_counter() - t0, cp.returncode

    rows = {}
    for i in range(3):
        rows.setdefault("sandboxed_interpreter_s", []).append(timed([py, "-I", "-S", "-c", "pass"], ch.ws)[0])
        rows.setdefault("kit_import_s", []).append(timed([py, "-I", "-S", "-c", "import kit, kit.heuristic"], ch.ws)[0])
    for i in range(2):
        p = os.path.join(ch.ws, f"bench_tpl_{i}.py")
        with open(p, "w") as f:
            f.write(AGENT_TEMPLATE)
        t0 = time.perf_counter()
        rep = ch.check(p)
        rows.setdefault("template_check_s", []).append(time.perf_counter() - t0)
        rows.setdefault("template_decision_p99_us", []).append(rep.report["metrics"].get("lat_p99_us"))
        rows.setdefault("template_startup_ms", []).append(rep.report["metrics"].get("startup_ms"))
    r = {k: statistics.median(v) for k, v in rows.items() if v and None not in v}
    print("startup: " + "  ".join(f"{k}={v:.3f}" for k, v in r.items()), flush=True)
    return r


def bench_eval(ch: Challenge, tables_list: list[int], workers_list: list[int], out_dir: str) -> list[dict]:
    m = ch.mutation()
    sub = ch.active_submission()
    seed = ch.secret()["hidden_eval_seed"]
    rows = []
    for tables in tables_list:
        for w in workers_list:
            if tables >= 10000 and w == 1:
                print("eval 10000 tables workers=1 skipped (several minutes); run with --include-slow", flush=True) if not ARGS.include_slow else None
                if not ARGS.include_slow:
                    continue
            t0 = time.perf_counter()
            r = hidden_evaluate(m, sub["path"], os.path.join(out_dir, f"e{tables}_{w}"), seed=seed, workspace=ch.ws,
                                tables=tables, workers=w, baseline_tables=max(20, tables // 10), write_json=False)
            wall = time.perf_counter() - t0
            rows.append({"tables": tables, "workers": w, "wall_s": wall, "tables_per_s_total": (tables * 3 + r["baseline_tables"] * 2 + r["replay_tables_checked"] * 2) / wall,
                         "score": r["score"]["points_per_table"], "ci95": r["score"]["ci95"], "reproducible": r["reproducible_from_seed"],
                         "load_avg": _load()})
            print(f"eval tables={tables:<6} workers={w}: {wall:7.1f}s  score {r['score']['points_per_table']:.2f} "
                  f"CI {r['score']['ci95'][0]:.2f}..{r['score']['ci95'][1]:.2f}  reproducible={r['reproducible_from_seed']}", flush=True)
    return rows


def bench_reproducibility(ch: Challenge, out_dir: str, tables: int = 200) -> dict:
    m = ch.mutation()
    sub = ch.active_submission()
    seed = ch.secret()["hidden_eval_seed"]
    a = hidden_evaluate(m, sub["path"], os.path.join(out_dir, "ra"), seed=seed, workspace=ch.ws, tables=tables, workers=1, baseline_tables=20, write_json=False)
    b = hidden_evaluate(m, sub["path"], os.path.join(out_dir, "rb"), seed=seed, workspace=ch.ws, tables=tables, workers=4, baseline_tables=20, write_json=False)
    same = a["score"] == b["score"] and a["by_archetype"] == b["by_archetype"] and a["by_level"] == b["by_level"]
    print(f"reproducibility: workers 1 vs 4, same seed, {tables} tables -> identical={same}", flush=True)
    return {"tables": tables, "identical_across_worker_counts": same, "replay_check_a": a["reproducible_from_seed"],
            "replay_check_b": b["reproducible_from_seed"]}


ARGS = None


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--throughput-tournaments", type=int, default=200)
    ap.add_argument("--eval-tables", type=int, nargs="+", default=[100, 1000, 10000])
    ap.add_argument("--workers", type=int, nargs="+", default=[1, 4, 8])
    ap.add_argument("--include-slow", action="store_true", help="also run 10000 tables single-worker")
    ap.add_argument("--seed", type=int, default=11)
    ARGS = a = ap.parse_args()
    out = {"machine": _machine(), "load_avg_start": _load(), "command": " ".join(sys.argv), "note":
           "REHEARSAL environment benchmark. Deadline figures are Python wall-clock samples around act(); not official timing."}
    print(json.dumps({"load_avg": out["load_avg_start"], "cpu": out["machine"]["cpu"]}))
    tmp = tempfile.mkdtemp(prefix="bench_arena_")
    try:
        ch = Challenge.create(os.path.join(tmp, "ch"), seed=a.seed, duration_s=36000, cadence_s=0.0, validation={"tables": 6})
        ch.start()
        p = os.path.join(ch.ws, "adapted.py")
        with open(p, "w") as f:
            f.write('import kit\nfrom kit.heuristic import HeuristicBot\n_R = kit.load_rules()\n\n\nclass Agent(HeuristicBot):\n'
                    '    def __init__(self):\n        super().__init__(aggression=1.1)\n        self.evaluator = _R.ranking.evaluator()\n')
        sub = ch.submit(p)
        assert sub.accepted, sub.report
        out["mutation"] = ch.mutation().name
        out["throughput"] = bench_throughput(a.throughput_tournaments)
        out["serialization"] = bench_serialization()
        out["startup"] = bench_startup(ch)
        out["reproducibility"] = bench_reproducibility(ch, tmp)
        out["eval_time"] = bench_eval(ch, a.eval_tables, a.workers, tmp)
        out["load_avg_end"] = _load()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w") as f:
            json.dump(out, f, indent=1, default=str)
        print("wrote", a.out)


if __name__ == "__main__":
    main()
