"""Build the competitor's workspace: what the organizer's starter kit would be.

Contents (REHEARSAL approximation of rule 3.3): Python agent template, the
local simulator (a copy of pokergym's core engine as package ``kit``), ICM
calculator, payout and blind schedules, example observations, docs, and the
test/submit commands. Nothing from ``pokergym.bots``, ``pokergym.gym``,
``pokergym.equity``, ``pokergym.stats`` or ``pokergym.arena`` is copied.

Before challenge start the workspace holds everything except the variant.
``reveal(ws, mutation)`` writes ``variant.json``, ``BRIEFING.md``,
``payouts.json``, ``blinds.json`` and example observations.
"""
from __future__ import annotations

import json
import os
import random
import shutil

from ..agent import Observation
from ..rules import GameRules, rules_to_dict
from .mutations import Mutation

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT_MODULES = ("cards", "evaluator", "rules", "agent", "engine", "tournament", "icm", "checks")

KIT_INIT = '''"""Local simulator for this challenge (REHEARSAL kit; the official kit's
API will differ). Modules: cards, evaluator, rules, agent, engine,
tournament, icm, checks, fillers.

    from kit import load_rules, play, Observation, Action, FOLD, CHECK, CALL, raise_to
"""
import json as _json
import os as _os

from .agent import (Action, ActionType, Agent, AgentAdapter, Observation, TableInfo, CALL, CHECK, FOLD,
                    raise_to, fallback_action)
from .cards import card_str, cards_str, parse_card, parse_cards
from .checks import check_tournament, InvariantError
from .icm import icm_equities, icm_equity_for, place_probabilities
from .rules import GameRules, rules_from_dict, rules_to_dict
from .tournament import run_tournament, TournamentResult

_HERE = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))


def load_rules(competition_mode: bool = True) -> GameRules:
    """The revealed variant. ``competition_mode`` enforces the decision
    deadline (rule 3.7 fallback); set False for exact-replay research runs."""
    p = _os.path.join(_HERE, "variant.json")
    if not _os.path.exists(p):
        raise FileNotFoundError("variant.json is not here yet: the challenge has not started")
    with open(p) as f:
        r = rules_from_dict(_json.load(f)["rules"])
    return r.with_(deadline_mode="enforce" if competition_mode else "record")


def play(agents, rules=None, seed: int = 0, keep_hands: bool = True) -> TournamentResult:
    """One eight-player sit-and-go. ``agents`` are seated in order."""
    return run_tournament(agents, rules or load_rules(), seed=seed, keep_hands=keep_hands)
'''

FILLERS = '''"""Trivial opponents for local testing. They are NOT the hidden evaluation
opponents, which are stronger and withheld."""
import random

from .agent import CALL, CHECK, FOLD, raise_to


class CallBot:
    """Calls everything, never raises."""

    def reset(self, table):
        pass

    def act(self, obs):
        return CHECK if obs.can_check else CALL


class FoldBot:
    """Checks when free, otherwise folds."""

    def reset(self, table):
        pass

    def act(self, obs):
        return CHECK if obs.can_check else FOLD


class RandomBot:
    """Uniform over legal actions; raises to a random legal size."""

    def reset(self, table):
        self.rng = random.Random(table.seed)

    def act(self, obs):
        opts = [FOLD, CHECK if obs.can_check else CALL]
        if obs.can_raise:
            opts.append(raise_to(self.rng.randint(obs.min_raise_to, obs.max_raise_to)))
        return self.rng.choice(opts)


from .heuristic import HeuristicBot  # noqa: E402  (kit example bot: standard-poker heuristics, variant-unaware)

FILLERS = {"call": CallBot, "fold": FoldBot, "random": RandomBot, "heuristic": HeuristicBot}
'''

AGENT_TEMPLATE = '''"""Your bot. Keep this file self-contained: the hidden evaluator imports it
alone (plus the standard library). Do not import kit.* from here except for
type names; the evaluator supplies its own Observation objects with the same
attributes.

Interface (REHEARSAL approximation of the official Agent interface):

    class Agent:
        def reset(self, table) -> None     # once per table; table.seat, .num_players,
                                            # .starting_stack, .rules_name, .seed
        def act(self, obs) -> Action        # once per decision, within 1 ms

Observation attributes: hand_number, street, seat, button, small_blind,
big_blind, ante, hole_cards (ints: rank = c >> 2 with 0 = deuce .. 12 = ace,
suit = c & 3), board, stacks, bets, committed, in_hand, all_in, pot,
to_call, can_check, can_raise, min_raise_to, max_raise_to, history
((street, seat, kind, amount) tuples; kind 0 fold 1 check 2 call 3 raise),
num_players, live_players. ``obs.legal_actions`` lists what is legal.

Actions: FOLD, CHECK, CALL, raise_to(total_bet_for_this_street).
Illegal action, exception or > 1 ms => CHECK if legal else FOLD.
"""


class Action:
    __slots__ = ("kind", "amount")

    def __init__(self, kind, amount=0):
        self.kind, self.amount = kind, amount


FOLD, CHECK, CALL = Action(0), Action(1), Action(2)


def raise_to(amount):
    return Action(3, int(amount))


class Agent:
    def reset(self, table):
        self.seat = table.seat

    def act(self, obs):
        # TODO: read BRIEFING.md first. This placeholder is legal and loses.
        return CHECK if obs.can_check else FOLD
'''

RUN_LOCAL = '''"""Play your agent locally under the revealed variant.

    python run_local.py my_agent.py                 # 20 tables vs fillers, competition mode
    python run_local.py my_agent.py --tables 100 --vs random --self 3
    python run_local.py my_agent.py --research      # deadline recorded, not enforced (exact replays)

Reports points per table, finish distribution, illegal actions, exceptions,
decisions over 1 ms (and how many were replaced by the fallback), and the
slowest decision. Nothing here is the hidden evaluation.
"""
import argparse
import importlib.util
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kit  # noqa: E402
from kit.fillers import FILLERS  # noqa: E402
from kit.agent import Action, ActionType  # noqa: E402


def load_agent(path):
    spec = importlib.util.spec_from_file_location("competitor_agent", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cls = getattr(mod, "Agent", None) or getattr(mod, "BOT_CLASS", None)
    if cls is None:
        sys.exit("agent file must define class Agent (or BOT_CLASS)")
    return cls


class Shim:
    """Converts the agent's own Action objects to the simulator's."""

    def __init__(self, inner):
        self.inner = inner

    def reset(self, table):
        self.inner.reset(table)

    def act(self, obs):
        a = self.inner.act(obs)
        return Action(ActionType(int(a.kind)), int(getattr(a, "amount", 0)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("agent")
    ap.add_argument("--tables", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--vs", default="call,random,fold", help="filler mix")
    ap.add_argument("--self", dest="self_copies", type=int, default=0, help="extra copies of your agent at the table")
    ap.add_argument("--research", action="store_true", help="record deadline misses without enforcing them")
    a = ap.parse_args()
    rules = kit.load_rules(competition_mode=not a.research)
    cls = load_agent(a.agent)
    fillers = [FILLERS[n] for n in a.vs.split(",")]
    pts, pos, stats, lat = [], [], {"calls": 0, "timeouts": 0, "errors": 0, "illegal": 0}, []
    t0 = time.perf_counter()
    for t in range(a.tables):
        seat = t % rules.players
        agents = []
        copies = a.self_copies
        for s in range(rules.players):
            if s == seat:
                agents.append(Shim(cls()))
            elif copies > 0:
                agents.append(Shim(cls()))
                copies -= 1
            else:
                agents.append(fillers[s % len(fillers)]())
        res = kit.run_tournament(agents, rules, seed=a.seed * 100003 + t, keep_hands=True, record_latency=True)
        kit.check_tournament(res, rules)
        pts.append(res.points[seat])
        pos.append(res.positions[seat])
        st = res.agent_stats[seat]
        for k in stats:
            stats[k] += st[k]
        lat.extend(st.get("latencies_ns", []))
    wall = time.perf_counter() - t0
    se = statistics.stdev(pts) / len(pts) ** 0.5 if len(pts) > 1 else 0.0
    print(f"rules: {rules.name}   mode: {rules.deadline_mode}   tables: {a.tables}   {wall:.1f}s")
    print(f"points/table: {statistics.fmean(pts):.2f}  (95% CI +/- {1.96*se:.2f})   mean finish: {statistics.fmean(pos):.2f}")
    print(f"decisions: {stats['calls']}   illegal: {stats['illegal']}   exceptions: {stats['errors']}   "
          f">1ms: {stats['timeouts']}" + (" (replaced by check/fold)" if rules.deadline_mode == "enforce" else " (recorded only)"))
    if lat:
        lat.sort()
        print(f"latency us: p50 {lat[len(lat)//2]/1e3:.0f}  p99 {lat[int(len(lat)*0.99)]/1e3:.0f}  max {lat[-1]/1e3:.0f}")
    if stats["illegal"] or stats["errors"]:
        print("FIX ILLEGAL ACTIONS / EXCEPTIONS BEFORE SUBMITTING")


if __name__ == "__main__":
    main()
'''

SUBMIT = '''"""Submit (or just validate) your agent.

    python submit.py my_agent.py              # consumes your 5-minute submission slot if accepted/rejected
    python submit.py my_agent.py --check      # validation only; no slot consumed; milestones still recorded
    python submit.py --note "trying wider opens vs antes"   # log a hypothesis for the postmortem

The host validates in an isolated process: import, interface, legality,
complete games, exceptions, size, 1 ms benchmark. Result is printed here and
written to status.json.
"""
import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INBOX = os.path.join(os.path.dirname(HERE), "inbox")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("agent", nargs="?")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--note")
    ap.add_argument("--wait", type=float, default=300.0)
    a = ap.parse_args()
    os.makedirs(INBOX, exist_ok=True)
    rid = f"{time.time_ns()}"
    req = {"id": rid, "kind": "note" if a.note and not a.agent else ("check" if a.check else "submit"),
           "note": a.note, "client_time": time.time()}
    if a.agent:
        if not os.path.exists(a.agent):
            sys.exit(f"no such file {a.agent}")
        dst = os.path.join(INBOX, f"{rid}.py")
        shutil.copyfile(a.agent, dst)
        req["file"] = dst
        req["source_name"] = os.path.basename(a.agent)
    with open(os.path.join(INBOX, f"{rid}.req.json.tmp"), "w") as f:
        json.dump(req, f)
    os.replace(os.path.join(INBOX, f"{rid}.req.json.tmp"), os.path.join(INBOX, f"{rid}.req.json"))
    res_path = os.path.join(INBOX, f"{rid}.result.json")
    t0 = time.time()
    while time.time() - t0 < a.wait:
        if os.path.exists(res_path):
            with open(res_path) as f:
                res = json.load(f)
            print(res.get("summary", json.dumps(res, indent=1)))
            sys.exit(0 if res.get("accepted", True) else 1)
        time.sleep(0.5)
    sys.exit("no response from the host: is `python -m pokergym.arena serve <challenge>` running?")


if __name__ == "__main__":
    main()
'''

README = '''# Challenge workspace

You have 60 minutes from the start signal to build and submit a Python bot
for a poker variant you have not seen. This directory is everything you get.
Nothing outside it is readable from your processes (kernel sandbox), and
there is no network.

REHEARSAL: the agent interface, kit API and timing here approximate the
organizer's published rules (docs in the kit docstrings). Expect the real
kit to differ in names; the shape of the job is the same.

## Files

- `BRIEFING.md`, `variant.json`, `payouts.json`, `blinds.json`: appear at start. Read the briefing first.
- `my_agent.py`: your bot. Edit it. Keep it self-contained (stdlib only).
- `run_local.py`: play your bot locally under the variant (fillers only; the hidden opponents are stronger).
- `submit.py`: validate (`--check`, free) or submit (one slot per five minutes). `--note` logs a hypothesis.
- `kit/`: the local simulator (engine, rules, ICM, invariant checks) and `kit/heuristic.py`, a plain
  standard-poker example bot that knows nothing about the variant. You may read all of it.
- `examples/observations.json`: real observations under the variant, as dicts.
- `status.json`: clock, next submission slot, latest result, active bot (host-updated).

## Commands

    python run_local.py my_agent.py
    python submit.py my_agent.py --check
    python submit.py my_agent.py
    python submit.py --note "hypothesis: ..."

## Rules in force (rehearsal)

8 players, 2,000 chips, 200-hand cap, ICM at the cap, state reset per table,
1 ms per decision (check-else-fold on error/timeout), 100 MB file limit,
one submission every five minutes, latest accepted bot is active, freeze at
minute 60. Scoring: average points per table over many tables against
opponents you cannot see.
'''


def build_workspace(ws: str) -> None:
    """Fresh workspace without the variant."""
    if os.path.exists(ws):
        raise FileExistsError(ws)
    os.makedirs(os.path.join(ws, "kit"))
    os.makedirs(os.path.join(ws, "examples"))
    for m in KIT_MODULES:
        shutil.copyfile(os.path.join(PKG, m + ".py"), os.path.join(ws, "kit", m + ".py"))
    _write(os.path.join(ws, "kit", "__init__.py"), KIT_INIT)
    _write(os.path.join(ws, "kit", "fillers.py"), FILLERS)
    shutil.copyfile(os.path.join(PKG, "arena", "kit_files", "validate_runner.py"), os.path.join(ws, "kit", "validate_runner.py"))
    with open(os.path.join(PKG, "bots", "heuristic.py"), encoding="utf-8") as f:
        heur = (f.read().replace("from ..agent import", "from .agent import").replace("from ..evaluator import", "from .evaluator import")
                .replace("        self.aggression = aggression\n", "        self.aggression = aggression\n        self.evaluator = STANDARD_EVALUATOR  # set to load_rules().ranking.evaluator() for the variant\n")
                .replace("STANDARD_EVALUATOR.evaluate(", "self.evaluator.evaluate(").replace("STANDARD_EVALUATOR.category(", "self.evaluator.category("))
    _write(os.path.join(ws, "kit", "heuristic.py"), heur)
    _write(os.path.join(ws, "my_agent.py"), AGENT_TEMPLATE)
    _write(os.path.join(ws, "run_local.py"), RUN_LOCAL)
    _write(os.path.join(ws, "submit.py"), SUBMIT)
    _write(os.path.join(ws, "README.md"), README)
    _write(os.path.join(ws, "BRIEFING.md"), "# Sealed\n\nThe variant is revealed when the challenge starts.\n")


def reveal(ws: str, m: Mutation, example_hands: int = 3, seed: int = 0) -> None:
    r = m.rules
    _write(os.path.join(ws, "variant.json"), json.dumps({"name": m.name, "rules": rules_to_dict(r), "headline": m.headline,
                                                          "legal_actions": m.legal_actions}, indent=1))
    _write(os.path.join(ws, "BRIEFING.md"), m.briefing())
    _write(os.path.join(ws, "payouts.json"), json.dumps({"points_by_position": list(r.payouts.points), "label": r.payouts.label}, indent=1))
    _write(os.path.join(ws, "blinds.json"), json.dumps({"levels": [list(l) for l in r.blinds.levels], "hands_per_level": r.blinds.hands_per_level,
                                                        "ante_per_level": list(r.blinds.ante), "label": r.blinds.label}, indent=1))
    _write(os.path.join(ws, "examples", "observations.json"), json.dumps(example_observations(r, example_hands, seed), indent=1))


def example_observations(rules: GameRules, hands: int, seed: int) -> list[dict]:
    """Observations seen by seat 0 in a few hands against simple fillers."""
    from ..bots import FIXTURE_BOTS
    from ..tournament import run_tournament

    seen: list[dict] = []

    class Rec:
        def __init__(self, b):
            self.b = b

        def reset(self, t):
            self.b.reset(t)

        def act(self, o: Observation):
            if o.hand_number < hands:
                d = o.to_dict()
                d["legal_actions"] = [a.serialize() for a in o.legal_actions]
                seen.append(d)
            return self.b.act(o)

    rng = random.Random(seed)
    agents = [Rec(FIXTURE_BOTS["call"]())] + [FIXTURE_BOTS[rng.choice(["call", "random"])]() for _ in range(rules.players - 1)]
    run_tournament(agents, rules.with_(deadline_mode="off", max_hands=hands), seed=seed, keep_hands=False)
    return seen


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
