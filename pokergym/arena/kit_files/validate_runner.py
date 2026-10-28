"""Submission validator (runs INSIDE the competitor sandbox; stdlib + kit only).

    python -I -S kit/validate_runner.py <agent.py> '<json config>'

Prints one JSON line. Stages (rule 3.7 rehearsal thresholds in config):
  import      file loads; startup time measured
  interface   class Agent/BOT_CLASS with reset(table) and act(obs); reset() runs
  legality    every decision on recorded observations is legal
  games       N complete tournaments (competition mode: deadline ENFORCED,
              per-decision hard watchdog) pass all engine invariants
  errors      zero exceptions / watchdog kills
  timing      share of decisions over the deadline <= max_timeout_frac;
              startup <= max_startup_s
Also reports the research-mode (deadline recorded, not enforced) points on
the same seeds so the effect of the fallbacks is visible.
"""
import importlib.util
import json
import os
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import kit  # noqa: E402
from kit.agent import Action, ActionType, TableInfo  # noqa: E402
from kit.fillers import FILLERS  # noqa: E402


class HardTimeout(Exception):
    pass


def _alarm(signum, frame):
    raise HardTimeout("decision exceeded the hard watchdog")


class Watchdog:
    """Converts a hung ``act`` into an exception after ``hard_ms`` using
    SIGALRM (main thread only). This is coarse (milliseconds, not the 1 ms
    deadline) and only stops Python-level code; a hang inside a C call that
    does not return to the interpreter cannot be interrupted."""

    def __init__(self, inner, hard_ms):
        self.inner = inner
        self.hard = hard_ms / 1000.0

    def reset(self, table):
        self.inner.reset(table)

    def act(self, obs):
        signal.setitimer(signal.ITIMER_REAL, self.hard)
        try:
            a = self.inner.act(obs)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        return Action(ActionType(int(a.kind)), int(getattr(a, "amount", 0)))


def main():
    agent_path, cfg = sys.argv[1], json.loads(sys.argv[2])
    out = {"stages": [], "metrics": {}}

    def stage(name, ok, detail=""):
        out["stages"].append({"name": name, "passed": bool(ok), "detail": detail})
        return ok

    signal.signal(signal.SIGALRM, _alarm)
    rules = kit.load_rules(competition_mode=True).with_(decision_deadline_ms=cfg.get("deadline_ms", 1.0))

    # 1. import
    t0 = time.perf_counter()
    try:
        spec = importlib.util.spec_from_file_location("submission", agent_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except BaseException as e:  # noqa: BLE001
        stage("import", False, f"{type(e).__name__}: {e}")
        print(json.dumps(out))
        return
    startup = time.perf_counter() - t0
    out["metrics"]["startup_s"] = startup
    stage("import", True, f"{startup*1000:.0f} ms")

    # 2. interface
    cls = getattr(mod, "Agent", None) or getattr(mod, "BOT_CLASS", None)
    ok = cls is not None and callable(getattr(cls, "reset", None)) and callable(getattr(cls, "act", None))
    if ok:
        try:
            probe = cls()
            probe.reset(TableInfo(seat=0, num_players=rules.players, starting_stack=rules.starting_stack,
                                  rules_name=rules.name, seed=1))
        except BaseException as e:  # noqa: BLE001
            ok = False
            stage("interface", False, f"reset() raised {type(e).__name__}: {e}")
    else:
        stage("interface", False, "need class Agent (or BOT_CLASS) with reset(table) and act(obs)")
    if not ok:
        print(json.dumps(out))
        return
    stage("interface", True, cls.__name__)

    # 3. legality on recorded observations
    seen = []

    class Rec:
        def __init__(self, b):
            self.b = b

        def reset(self, t):
            self.b.reset(t)

        def act(self, o):
            if len(seen) < 400:
                seen.append(o)
            return self.b.act(o)

    rec_agents = [Rec(FILLERS[["random", "call", "heuristic"][i % 3]]()) for i in range(rules.players)]
    kit.run_tournament(rec_agents, rules.with_(deadline_mode="off", max_hands=40), seed=cfg.get("seed", 0) + 99, keep_hands=False)
    bot = Watchdog(cls(), cfg.get("hard_ms", 200))
    bot.reset(TableInfo(seat=0, num_players=rules.players, starting_stack=rules.starting_stack, rules_name=rules.name, seed=2))
    illegal = exc = 0
    for o in seen:
        try:
            a = bot.act(o)
            if not o.is_legal(a):
                illegal += 1
        except BaseException as e:  # noqa: BLE001
            exc += 1
            last = f"{type(e).__name__}: {e}"
    if not stage("legality", illegal == 0 and exc == 0,
                 f"{len(seen)} observations, {illegal} illegal, {exc} exceptions" + (f" ({last})" if exc else "")):
        print(json.dumps(out))
        return

    # 4. complete games, competition mode (enforced) with watchdog; plus research mode on the same seeds
    tables = cfg.get("tables", 6)
    seeds = [cfg.get("seed", 0) * 7919 + t for t in range(tables)]
    stats = {"calls": 0, "timeouts": 0, "errors": 0, "illegal": 0}
    lat = []
    pts_enf, pts_rec, pts_fold = [], [], []
    inv_fail = None
    filler_cycle = ("heuristic", "call", "random")
    for mode, sink, who in (("enforce", pts_enf, "bot"), ("record", pts_rec, "bot"), ("enforce", pts_fold, "fold")):
        r = rules.with_(deadline_mode=mode)
        for t, sd in enumerate(seeds):
            seat = t % r.players
            agents = []
            fi = 0
            for s in range(r.players):
                if s == seat or (s == (seat + 4) % r.players):
                    agents.append(Watchdog(cls(), cfg.get("hard_ms", 200)) if who == "bot" else FILLERS["fold"]())
                else:
                    agents.append(FILLERS[filler_cycle[fi % 3]]())
                    fi += 1
            try:
                res = kit.run_tournament(agents, r, seed=sd, keep_hands=True, record_latency=(mode == "enforce"))
                kit.check_tournament(res, r)
            except BaseException as e:  # noqa: BLE001
                inv_fail = f"{type(e).__name__}: {e}"
                break
            sink.append(res.points[seat])
            if mode == "enforce" and who == "bot":
                for s in (seat, (seat + 4) % r.players):
                    st = res.agent_stats[s]
                    for k in stats:
                        stats[k] += st[k]
                    lat.extend(st.get("latencies_ns", []))
        if inv_fail:
            break
    if not stage("games", inv_fail is None and len(pts_enf) == tables,
                 inv_fail or f"{tables} tournaments x 2 modes, {stats['calls']} decisions, points/table {sum(pts_enf)/max(1,len(pts_enf)):.2f}"
                 f" (check/fold bot on the same seeds: {sum(pts_fold)/max(1,len(pts_fold)):.2f})"):
        print(json.dumps(out))
        return
    lat.sort()
    n = len(lat)
    out["metrics"].update({
        "decisions": stats["calls"], "illegal": stats["illegal"], "errors": stats["errors"], "timeouts": stats["timeouts"],
        "timeout_frac": stats["timeouts"] / max(1, stats["calls"]),
        "lat_p50_us": lat[n // 2] / 1e3 if n else 0, "lat_p99_us": lat[int(n * 0.99)] / 1e3 if n else 0,
        "lat_max_us": lat[-1] / 1e3 if n else 0,
        "points_enforced": sum(pts_enf) / max(1, len(pts_enf)), "points_research": sum(pts_rec) / max(1, len(pts_rec)),
        "fallback_effect_points": (sum(pts_enf) - sum(pts_rec)) / max(1, len(pts_enf)),
        "points_fold_baseline": sum(pts_fold) / max(1, len(pts_fold)),
        "edge_over_fold_bot": (sum(pts_enf) - sum(pts_fold)) / max(1, len(pts_enf)),
    })
    # 5. errors
    stage("errors", stats["errors"] == 0 and stats["illegal"] == 0,
          f"{stats['errors']} exceptions/watchdog kills, {stats['illegal']} illegal actions in games")
    # 7. timing (6 = size is checked by the host)
    frac_ok = out["metrics"]["timeout_frac"] <= cfg.get("max_timeout_frac", 0.02)
    start_ok = startup <= cfg.get("max_startup_s", 10.0)
    stage("timing", frac_ok and start_ok,
          f"{stats['timeouts']}/{stats['calls']} over {rules.decision_deadline_ms:g} ms ({out['metrics']['timeout_frac']*100:.2f}%),"
          f" p50 {out['metrics']['lat_p50_us']:.0f} us, p99 {out['metrics']['lat_p99_us']:.0f} us, max {out['metrics']['lat_max_us']:.0f} us,"
          f" startup {startup*1000:.0f} ms; fallbacks changed points by {out['metrics']['fallback_effect_points']:+.2f}/table")
    print(json.dumps(out))


if __name__ == "__main__":
    main()
