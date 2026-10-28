"""The gym: load a bot, seat it against a lineup, measure it.

Bot specs
---------
  "tag"                         a registry name (see ``pokergym.bots``)
  "my_bot.py:MyBot"             a class in a Python file (path relative to cwd or absolute)
  "mypkg.module:MyBot"          a class in an importable module
A spec may end with ``@label`` to name the bot in reports ("my_bot.py:MyBot@v3").

Evaluation design
-----------------
``evaluate`` plays ``tables`` sit-and-gos. For table ``t`` the harness draws a
table seed, a hero seat, and seven opponents from the lineup, then runs the
tournament. With ``baseline`` set, the same table (same seed, seat, opponents)
is replayed with the baseline bot in the hero seat; the per-table point
difference is a paired sample, which removes most of the card luck shared by
both runs (the deck sequence is identical until the first elimination changes
the number of cards dealt). Confidence intervals are normal approximations
from the per-table standard error.

Points are the SYNTHETIC payout schedule unless ``rules`` says otherwise.
"""
from __future__ import annotations

import importlib
import importlib.util
import math
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

from .bots import BOT_REGISTRY, FIXTURE_BOTS, SPARRING_BOTS
from .rules import GameRules, BASELINE_RULES
from .tournament import run_tournament
from .variants import VARIANTS

LINEUPS: dict[str, list[str]] = {
    "fixtures": ["call", "random", "heuristic", "call", "random", "heuristic", "random"],
    "sparring": ["tag", "lag", "shortstack", "icm", "adaptive", "tag", "lag"],
    "mixed": ["tag", "lag", "shortstack", "icm", "adaptive", "heuristic", "random"],
    "tags": ["tag"] * 7,
    "lags": ["lag"] * 7,
}


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def split_label(spec: str) -> tuple[str, str]:
    if "@" in spec:
        s, label = spec.rsplit("@", 1)
        return s, label
    return spec, spec


def load_bot_class(spec: str) -> type:
    spec, _ = split_label(spec)
    if spec in BOT_REGISTRY:
        return BOT_REGISTRY[spec]
    if ":" not in spec:
        raise ValueError(f"unknown bot {spec!r}; registry: {sorted(BOT_REGISTRY)}; or use path.py:Class / pkg.mod:Class")
    target, cls_name = spec.rsplit(":", 1)
    if target.endswith(".py") or os.sep in target:
        path = os.path.abspath(target)
        mod_name = "_gymbot_" + os.path.splitext(os.path.basename(path))[0] + "_" + str(abs(hash(path)) % 10**8)
        if mod_name in sys.modules:
            module = sys.modules[mod_name]
        else:
            ms = importlib.util.spec_from_file_location(mod_name, path)
            if ms is None or ms.loader is None:
                raise ValueError(f"cannot load {path}")
            module = importlib.util.module_from_spec(ms)
            sys.modules[mod_name] = module
            ms.loader.exec_module(module)
    else:
        module = importlib.import_module(target)
    try:
        cls = getattr(module, cls_name)
    except AttributeError:
        raise ValueError(f"{target} has no attribute {cls_name!r}") from None
    for m in ("reset", "act"):
        if not callable(getattr(cls, m, None)):
            raise ValueError(f"{spec}: bot class must define {m}(...)")
    return cls


def make_factory(spec: str) -> Callable[[], object]:
    cls = load_bot_class(spec)
    return cls


def instantiate(spec: str, rules: GameRules | None = None):
    """Construct a bot and, if it defines ``configure(rules)``, tell it the
    rules in force (REHEARSAL hook; how the official kit exposes the variant
    is unknown)."""
    bot = load_bot_class(spec)()
    cfg = getattr(bot, "configure", None)
    if rules is not None and callable(cfg):
        cfg(rules)
    return bot


def resolve_lineup(lineup: str | Sequence[str]) -> list[str]:
    if isinstance(lineup, str):
        if lineup in LINEUPS:
            return list(LINEUPS[lineup])
        return [s for s in lineup.split(",") if s]
    return list(lineup)


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------
def _mean_se(xs: Sequence[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    m = statistics.fmean(xs)
    if n < 2:
        return m, 0.0
    return m, statistics.stdev(xs) / math.sqrt(n)


@dataclass
class EvalReport:
    candidate: str
    lineup: list[str]
    tables: int
    seed: int
    rules: str
    mean_points: float
    se_points: float
    finish_mean: float
    finish_hist: dict[int, int]            # rounded finishing position -> count
    win_rate: float
    cash_rate: float                       # finished in the top half (1..4)
    icm_rate: float                        # fraction of tables that hit the hand cap
    avg_hands: float
    bust_hand_mean: float | None           # mean hand number of elimination (when busted)
    stats: dict                            # calls/timeouts/errors/illegal summed
    opponent_points: dict[str, float]      # mean points per opponent spec (per seat occurrence)
    baseline: str | None = None
    baseline_mean: float | None = None
    diff_mean: float | None = None
    diff_se: float | None = None
    wall_s: float = 0.0
    per_table: list[dict] = field(default_factory=list)
    synthetic: list[str] = field(default_factory=list)

    @property
    def ci95(self) -> tuple[float, float]:
        return self.mean_points - 1.96 * self.se_points, self.mean_points + 1.96 * self.se_points

    @property
    def diff_ci95(self) -> tuple[float, float] | None:
        if self.diff_mean is None:
            return None
        return self.diff_mean - 1.96 * self.diff_se, self.diff_mean + 1.96 * self.diff_se

    def to_dict(self, include_tables: bool = False) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "per_table"}
        d["ci95"] = list(self.ci95)
        d["diff_ci95"] = None if self.diff_ci95 is None else list(self.diff_ci95)
        if include_tables:
            d["per_table"] = self.per_table
        return d

    def format(self) -> str:
        lo, hi = self.ci95
        lines = [
            f"candidate: {self.candidate}   rules: {self.rules}   tables: {self.tables}   seed: {self.seed}   {self.wall_s:.1f}s",
            f"lineup:    {', '.join(self.lineup)}",
            f"points/table: {self.mean_points:.3f}  (95% CI {lo:.3f} .. {hi:.3f}, se {self.se_points:.3f})",
            f"finish: mean {self.finish_mean:.2f}   win {self.win_rate*100:.1f}%   top-4 {self.cash_rate*100:.1f}%"
            f"   hand-cap tables {self.icm_rate*100:.1f}%   hands/table {self.avg_hands:.1f}",
        ]
        if self.bust_hand_mean is not None:
            lines.append(f"busted on hand {self.bust_hand_mean:.1f} on average (when busted)")
        hist = " ".join(f"{p}:{self.finish_hist.get(p, 0)}" for p in range(1, 9))
        lines.append(f"finish histogram (1..8): {hist}")
        st = self.stats
        lines.append(
            f"decisions: {st['calls']}   >1ms: {st['timeouts']} ({st['timeouts']/max(1,st['calls'])*100:.4f}%)"
            f"   errors: {st['errors']}   illegal: {st['illegal']}"
        )
        if self.opponent_points:
            opp = "  ".join(f"{k}={v:.2f}" for k, v in sorted(self.opponent_points.items()))
            lines.append(f"opponent points/seat: {opp}")
        if self.baseline is not None:
            dlo, dhi = self.diff_ci95
            verdict = "better" if dlo > 0 else ("worse" if dhi < 0 else "not distinguishable")
            lines.append(
                f"vs baseline {self.baseline}: {self.baseline_mean:.3f} pts/table; paired diff {self.diff_mean:+.3f}"
                f" (95% CI {dlo:+.3f} .. {dhi:+.3f}) -> {verdict}"
            )
        for s in self.synthetic:
            lines.append(f"SYNTHETIC {s}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Table plan and workers
# --------------------------------------------------------------------------
def _plan(tables: int, seed: int, lineup: list[str], players: int) -> list[tuple[int, int, int, list[str]]]:
    """Deterministic list of (table_index, table_seed, hero_seat, opponent_specs)."""
    rng = random.Random(seed)
    plan = []
    k = players - 1
    for t in range(tables):
        table_seed = rng.getrandbits(32)
        seat = rng.randrange(players)
        if len(lineup) == k:
            opps = list(lineup)
        elif len(lineup) > k:
            opps = rng.sample(lineup, k)
        else:
            opps = list(lineup) + [rng.choice(lineup) for _ in range(k - len(lineup))]
        rng.shuffle(opps)
        plan.append((t, table_seed, seat, opps))
    return plan


def _play_table(candidate: str, table_seed: int, seat: int, opps: list[str], rules: GameRules) -> dict:
    agents = []
    oi = 0
    for s in range(rules.players):
        if s == seat:
            agents.append(instantiate(candidate, rules))
        else:
            agents.append(instantiate(opps[oi], rules))
            oi += 1
    res = run_tournament(agents, rules, seed=table_seed, keep_hands=False)
    bust_hand = None
    if seat in res.elimination_order:
        bust_hand = res.elimination_hands[res.elimination_order.index(seat)]
    opp_points = {}
    oi = 0
    for s in range(rules.players):
        if s != seat:
            opp_points.setdefault(opps[oi], []).append(res.points[s])
            oi += 1
    return {
        "points": res.points[seat],
        "position": res.positions[seat],
        "hands": res.hands_played,
        "icm": res.icm_applied,
        "busted": seat in res.elimination_order,
        "bust_hand": bust_hand,
        "stats": res.agent_stats[seat],
        "opp_points": opp_points,
    }


def _worker(args):
    candidate, baseline, rules_key, items = args
    rules = _rules_from_key(rules_key)
    out = []
    for (t, table_seed, seat, opps) in items:
        r = _play_table(candidate, table_seed, seat, opps, rules)
        row = {"table": t, "seed": table_seed, "seat": seat, "opps": opps, **r}
        if baseline is not None:
            b = _play_table(baseline, table_seed, seat, opps, rules)
            row["baseline_points"] = b["points"]
            row["baseline_position"] = b["position"]
        out.append(row)
    return out


def _rules_key(rules: GameRules) -> str:
    for k, v in VARIANTS.items():
        if v is rules or v == rules:
            return k
    raise ValueError("multiprocess evaluation needs rules from pokergym.variants.VARIANTS")


def _rules_from_key(key: str) -> GameRules:
    return VARIANTS[key]


def _run_plan(candidate, baseline, rules, plan, workers):
    if workers <= 1:
        return _worker((candidate, baseline, _rules_key(rules), plan))
    import multiprocessing as mp

    chunks = [plan[i::workers] for i in range(workers)]
    rows = []
    with mp.get_context("spawn").Pool(workers) as pool:
        for part in pool.imap_unordered(_worker, [(candidate, baseline, _rules_key(rules), c) for c in chunks if c]):
            rows.extend(part)
    rows.sort(key=lambda r: r["table"])
    return rows


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def evaluate(
    candidate: str,
    lineup: str | Sequence[str] = "sparring",
    tables: int = 500,
    seed: int = 1,
    rules: GameRules = BASELINE_RULES,
    baseline: str | None = None,
    workers: int = 1,
    keep_tables: bool = False,
) -> EvalReport:
    load_bot_class(candidate)  # fail fast on a bad spec
    specs = resolve_lineup(lineup)
    for s in specs:
        load_bot_class(s)
    if baseline is not None:
        load_bot_class(baseline)
    plan = _plan(tables, seed, specs, rules.players)
    t0 = time.perf_counter()
    rows = _run_plan(candidate, baseline, rules, plan, workers)
    wall = time.perf_counter() - t0

    pts = [r["points"] for r in rows]
    mean, se = _mean_se(pts)
    positions = [r["position"] for r in rows]
    hist: dict[int, int] = {}
    for p in positions:
        hist[int(round(p))] = hist.get(int(round(p)), 0) + 1
    stats = {"calls": 0, "timeouts": 0, "errors": 0, "illegal": 0}
    for r in rows:
        for k in stats:
            stats[k] += r["stats"][k]
    opp_acc: dict[str, list[float]] = {}
    for r in rows:
        for k, v in r["opp_points"].items():
            opp_acc.setdefault(k, []).extend(v)
    rep = EvalReport(
        candidate=split_label(candidate)[1], lineup=specs, tables=tables, seed=seed, rules=rules.name,
        mean_points=mean, se_points=se, finish_mean=statistics.fmean(positions), finish_hist=hist,
        win_rate=sum(1 for p in positions if p <= 1.0) / len(rows),
        cash_rate=sum(1 for p in positions if p <= 4.0) / len(rows),
        icm_rate=sum(1 for r in rows if r["icm"]) / len(rows),
        avg_hands=statistics.fmean(r["hands"] for r in rows),
        bust_hand_mean=(statistics.fmean(busts) if (busts := [r["bust_hand"] for r in rows if r["bust_hand"] is not None]) else None),
        stats=stats,
        opponent_points={k: statistics.fmean(v) for k, v in opp_acc.items()},
        wall_s=wall,
        synthetic=rules.synthetic_components(),
    )
    if baseline is not None:
        diffs = [r["points"] - r["baseline_points"] for r in rows]
        rep.baseline = split_label(baseline)[1]
        rep.baseline_mean = statistics.fmean(r["baseline_points"] for r in rows)
        rep.diff_mean, rep.diff_se = _mean_se(diffs)
    if keep_tables:
        rep.per_table = rows
    return rep


# --------------------------------------------------------------------------
# Ladder: every bot scored against every other
# --------------------------------------------------------------------------
@dataclass
class LadderReport:
    specs: list[str]
    labels: list[str]
    tables: int
    seed: int
    rules: str
    mean_points: list[float]
    se_points: list[float]
    seats_played: list[int]
    wall_s: float
    synthetic: list[str] = field(default_factory=list)

    def format(self) -> str:
        order = sorted(range(len(self.specs)), key=lambda i: -self.mean_points[i])
        lines = [f"ladder: {len(self.specs)} bots, {self.tables} tables, rules {self.rules}, seed {self.seed}, {self.wall_s:.1f}s",
                 f"{'rank':>4} {'bot':<28} {'pts/table':>10} {'95% CI':>18} {'seats':>6}"]
        for rank, i in enumerate(order, 1):
            m, se = self.mean_points[i], self.se_points[i]
            lines.append(f"{rank:>4} {self.labels[i]:<28} {m:>10.3f} {m-1.96*se:>8.3f}..{m+1.96*se:<8.3f} {self.seats_played[i]:>6}")
        for s in self.synthetic:
            lines.append(f"SYNTHETIC {s}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _ladder_worker(args):
    specs, rules_key, items = args
    rules = _rules_from_key(rules_key)
    out = []
    for (t, table_seed, ids) in items:
        agents = [instantiate(specs[i], rules) for i in ids]
        res = run_tournament(agents, rules, seed=table_seed, keep_hands=False)
        out.append((t, ids, res.points))
    return out


def ladder(
    specs: Sequence[str],
    tables: int = 300,
    seed: int = 1,
    rules: GameRules = BASELINE_RULES,
    workers: int = 1,
) -> LadderReport:
    """Seat the bots against each other. With exactly 8 specs every table
    seats all eight in random order. With fewer, the empty seats are filled
    with random copies that do not score (rule 4.6). With more than 8, each
    table draws 8 at random."""
    specs = list(specs)
    for s in specs:
        load_bot_class(s)
    n = rules.players
    rng = random.Random(seed)
    plan = []
    for t in range(tables):
        table_seed = rng.getrandbits(32)
        if len(specs) == n:
            ids = list(range(n))
        elif len(specs) > n:
            ids = rng.sample(range(len(specs)), n)
        else:
            ids = list(range(len(specs))) + [rng.randrange(len(specs)) for _ in range(n - len(specs))]
        rng.shuffle(ids)
        plan.append((t, table_seed, ids))
    t0 = time.perf_counter()
    key = _rules_key(rules)
    if workers <= 1:
        results = _ladder_worker((specs, key, plan))
    else:
        import multiprocessing as mp

        chunks = [plan[i::workers] for i in range(workers)]
        results = []
        with mp.get_context("spawn").Pool(workers) as pool:
            for part in pool.imap_unordered(_ladder_worker, [(specs, key, c) for c in chunks if c]):
                results.extend(part)
    wall = time.perf_counter() - t0
    per_bot: list[list[float]] = [[] for _ in specs]
    for (t, ids, points) in results:
        seen = set()
        for seat, bid in enumerate(ids):
            if bid in seen:
                continue  # filler copy: first occurrence scores (rule 4.6)
            seen.add(bid)
            per_bot[bid].append(points[seat])
    means, ses = [], []
    for xs in per_bot:
        m, se = _mean_se(xs)
        means.append(m)
        ses.append(se)
    return LadderReport(
        specs=specs, labels=[split_label(s)[1] for s in specs], tables=tables, seed=seed, rules=rules.name,
        mean_points=means, se_points=ses, seats_played=[len(x) for x in per_bot], wall_s=wall,
        synthetic=rules.synthetic_components(),
    )


__all__ = [
    "LINEUPS", "FIXTURE_BOTS", "SPARRING_BOTS", "load_bot_class", "make_factory", "instantiate", "resolve_lineup",
    "evaluate", "EvalReport", "ladder", "LadderReport",
]
