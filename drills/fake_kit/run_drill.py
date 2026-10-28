"""Check an adapter written for the FAKE kit.

    python drills/fake_kit/run_drill.py my_adapter.py:Adapted
    python drills/fake_kit/run_drill.py reference_adapter.py:Adapted   # the answer key

Three checks, in the order they matter on the day:
  1. legality  - 4 tables through the fake kit: zero exceptions / unparseable replies
  2. parity    - the adapter hosting TagBot must make the SAME decisions as TagBot
                 run natively on the same seeds (a lossless translation). If parity
                 fails, the adapter is dropping or mistranslating a field.
  3. speed     - mean adapter overhead per decision (target: well under 1 ms)
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

import fakekit  # noqa: E402
from pokergym.bots import TagBot  # noqa: E402
from pokergym.rules import BASELINE_RULES  # noqa: E402
from pokergym.tournament import run_tournament  # noqa: E402


def load(spec: str):
    path, cls = spec.rsplit(":", 1)
    if not os.path.isabs(path):
        path = os.path.join(HERE, path) if not os.path.exists(path) else path
    s = importlib.util.spec_from_file_location("drill_adapter", path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return getattr(m, cls)


class _Rec:
    def __init__(self, bot):
        self.bot, self.out = bot, []

    def reset(self, t):
        self.bot.reset(t)

    def act(self, o):
        a = self.bot.act(o)
        self.out.append((o.hand_number, o.street, int(a.kind), a.amount))
        return a


def check(adapter_cls, tables: int = 4, rules=BASELINE_RULES) -> dict:
    report = {"tables": tables}
    # 1 + 3: legality and speed through the fake kit
    errs = 0
    decisions = 0
    t0 = time.perf_counter()
    for seed in range(tables):
        bots = [adapter_cls(TagBot()) for _ in range(8)]
        res = fakekit.play_table(bots, seed=seed, rules=rules, keep_hands=False)
        errs += sum(res.fake_errors)
        decisions += sum(st["calls"] for st in res.agent_stats)
    kit_time = time.perf_counter() - t0
    t0 = time.perf_counter()
    for seed in range(tables):
        run_tournament([TagBot() for _ in range(8)], rules, seed=seed, keep_hands=False)
    native_time = time.perf_counter() - t0
    report.update(fake_errors=errs, decisions=decisions,
                  overhead_us=(kit_time - native_time) / max(decisions, 1) * 1e6)
    # 2: parity. Seat 0 adapted vs seat 0 native, same seeds, other seats native TagBots.
    mism = 0
    compared = 0
    for seed in range(tables):
        native = [_Rec(TagBot()) for _ in range(8)]
        run_tournament(native, rules, seed=seed, keep_hands=False)
        probe = _Rec(fakekit._EngineSide(adapter_cls(TagBot()), rules))
        others = [TagBot() for _ in range(7)]
        run_tournament([probe] + others, rules, seed=seed, keep_hands=False)
        a, b = native[0].out, probe.out
        compared += min(len(a), len(b))
        mism += sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))
    report.update(parity_compared=compared, parity_mismatches=mism)
    report["pass"] = errs == 0 and mism == 0
    return report


def main():
    spec = sys.argv[1] if len(sys.argv) > 1 else "reference_adapter.py:Adapted"
    r = check(load(spec))
    print(f"adapter: {spec}")
    print(f"  legality : {r['fake_errors']} errors in {r['decisions']} decisions over {r['tables']} tables")
    print(f"  parity   : {r['parity_mismatches']} mismatches in {r['parity_compared']} compared decisions")
    print(f"  overhead : {r['overhead_us']:.0f} us per decision (adapter + fake kit translation)")
    print("  RESULT   :", "PASS" if r["pass"] else "FAIL")
    sys.exit(0 if r["pass"] else 1)


if __name__ == "__main__":
    main()
