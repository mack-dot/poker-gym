"""Hidden evaluation of the active submission against withheld opponents.

Three paired runs on the hidden seed (same tables, seats and decks within a
rules setting):

  variant   candidate vs hidden lineup under the revealed variant   <- the score
  baseline  candidate vs hidden lineup under standard hold'em       <- general strength diagnostic
  naive     rule-naive reference vs hidden lineup under the variant <- price of ignoring the rule

Each run is paired with the adapted reference (``mutation.adapted_ref``,
configured for the variant) replayed in the same seats, so every number has a
reference next to it. The deadline is RECORDED, not enforced, so the result
is bit-reproducible from the seed (a replay of the first tables verifies
this); the candidate's over-deadline decisions are reported as violations.
Enforcing the deadline during grading would make the score depend on host
load (a slow opponent decision also changes the game), which is what the
validator's competition-mode run is for. ``mode="enforce"`` is available for
an explicit, non-reproducible competition-mode figure.
"""
from __future__ import annotations

import json
import os
import statistics
import time

from ..gym import EvalReport, evaluate, split_label
from ..rules import BASELINE_RULES
from .hidden_opponents import HIDDEN_LINEUP
from .mutations import Mutation

WRAPPER = '''"""Auto-generated: hosts a competitor submission as a pokergym agent."""
import importlib.util
import sys

from pokergym.agent import Action, ActionType

# REHEARSAL assumption: the kit shipped to the competitor is importable when
# the organizer runs the bot, so `import kit` inside a submission is allowed.
if {workspace!r} not in sys.path:
    sys.path.insert(0, {workspace!r})
_spec = importlib.util.spec_from_file_location("submission_{tag}", {path!r})
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_Inner = getattr(_mod, "Agent", None) or getattr(_mod, "BOT_CLASS")


class Wrapped:
    def __init__(self):
        self.inner = _Inner()

    def reset(self, table):
        self.inner.reset(table)

    def act(self, obs):
        a = self.inner.act(obs)
        return Action(ActionType(int(a.kind)), int(getattr(a, "amount", 0)))
'''


def wrap_submission(sub_path: str, out_dir: str, tag: str, workspace: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, f"wrap_{tag}.py")
    with open(p, "w") as f:
        f.write(WRAPPER.format(tag=tag, path=os.path.realpath(sub_path), workspace=os.path.realpath(workspace)))
    return f"{p}:Wrapped"


def _by_archetype(rep: EvalReport) -> dict:
    out: dict[str, dict] = {}
    for row in rep.per_table:
        for spec, positions in row["opp_positions"].items():
            label = split_label(spec)[1]
            d = out.setdefault(label, {"tables": 0, "finished_above": 0, "point_diff": []})
            for pos, pts in zip(positions, row["opp_points"][spec]):
                d["tables"] += 1
                d["finished_above"] += row["position"] < pos
                d["point_diff"].append(row["points"] - pts)
    return {k: {"tables": v["tables"], "finished_above_rate": v["finished_above"] / max(1, v["tables"]),
                "mean_point_diff": statistics.fmean(v["point_diff"]) if v["point_diff"] else 0.0}
            for k, v in sorted(out.items())}


def _by_level(rep: EvalReport, hands_per_level: int, levels: int) -> dict:
    bust = [0] * levels
    for row in rep.per_table:
        if row["bust_hand"] is not None:
            bust[min(levels - 1, row["bust_hand"] // hands_per_level)] += 1
    n = len(rep.per_table)
    survive = []
    alive = n
    for b in bust:
        alive -= b
        survive.append(alive / max(1, n))
    stacks = [row["final_stack"] for row in rep.per_table if not row["busted"]]
    return {"bust_by_level": bust, "survival_to_end_of_level": survive,
            "mean_final_stack_when_alive": statistics.fmean(stacks) if stacks else 0.0,
            "tables": n}


def _slim(rep: EvalReport) -> dict:
    d = rep.to_dict(include_tables=False)
    d["lineup"] = [split_label(s)[1] for s in rep.lineup]
    return d


def hidden_evaluate(m: Mutation, sub_path: str, out_dir: str, seed: int, workspace: str, tables: int = 1000,
                    workers: int = 1, baseline_tables: int | None = None, write_json: bool = True,
                    mode: str = "record", replay_tables: int = 20) -> dict:
    t0 = time.perf_counter()
    spec = wrap_submission(sub_path, out_dir, tag=os.path.basename(sub_path).split(".")[0], workspace=workspace)
    rules_v = m.rules.with_(deadline_mode=mode)
    rules_b = BASELINE_RULES.with_(deadline_mode=mode)
    bt = baseline_tables if baseline_tables is not None else max(100, tables // 2)
    rep_v = evaluate(spec, HIDDEN_LINEUP, tables=tables, seed=seed, rules=rules_v, baseline=m.adapted_ref, workers=workers, keep_tables=True)
    rep_b = evaluate(spec, HIDDEN_LINEUP, tables=bt, seed=seed, rules=rules_b, baseline=m.adapted_ref, workers=workers, keep_tables=True)
    rep_n = evaluate(m.naive_ref, HIDDEN_LINEUP, tables=tables, seed=seed, rules=rules_v, baseline=m.adapted_ref, workers=workers)

    hpl = m.rules.blinds.hands_per_level
    levels = (m.rules.max_hands + hpl - 1) // hpl
    violations = {"illegal": rep_v.stats["illegal"], "errors": rep_v.stats["errors"], "timeouts": rep_v.stats["timeouts"],
                  "decisions": rep_v.stats["calls"]}
    # Reproducibility is checked, not assumed: replay the first tables with the
    # same seed and compare every row (the plan is a prefix-stable function of the seed).
    k = min(replay_tables, tables)
    rep_r = evaluate(spec, HIDDEN_LINEUP, tables=k, seed=seed, rules=rules_v, baseline=m.adapted_ref, workers=1, keep_tables=True)
    rows_a = [{kk: v for kk, v in r.items() if kk != "stats"} for r in rep_v.per_table[:k]]
    rows_b = [{kk: v for kk, v in r.items() if kk != "stats"} for r in rep_r.per_table[:k]]
    reproducible = rows_a == rows_b

    # Verdicts (REHEARSAL heuristics, stated in the report).
    gap_ref = -(rep_n.diff_mean or 0.0)            # adapted ref - naive ref under the variant
    gap_ref_se = rep_n.diff_se or 0.0
    cand_vs_ref_v, se_v = rep_v.diff_mean, rep_v.diff_se
    cand_vs_ref_b, se_b = rep_b.diff_mean, rep_b.diff_se
    sep = abs(gap_ref) > 1.96 * gap_ref_se and gap_ref_se > 0
    strength = "stronger than the adapted reference" if cand_vs_ref_b - 1.96 * se_b > 0 else \
        ("weaker than the adapted reference" if cand_vs_ref_b + 1.96 * se_b < 0 else "about the reference's strength")
    if not sep:
        adaptation = ("not separable: for this mutation the adapted and naive references score the same "
                      f"({gap_ref:+.2f} +/- {1.96*gap_ref_se:.2f}), so adaptation cannot be priced with these references")
    else:
        # how much of the candidate's variant-vs-baseline change tracks the reference's
        delta_cand = (rep_v.mean_points - rep_b.mean_points)
        delta_ref = (rep_v.baseline_mean - rep_b.baseline_mean)
        adaptation = ("handled the rule at least as well as the adapted reference"
                      if delta_cand >= delta_ref - 1.96 * (se_v + se_b) else
                      "lost more than the adapted reference when moving from standard poker to the variant: rule not fully absorbed")
    result = {
        "mutation": m.name, "family": m.family, "seed": seed, "tables": tables, "baseline_tables": bt,
        "lineup": [split_label(s)[1] for s in HIDDEN_LINEUP], "wall_s": time.perf_counter() - t0,
        "score": {"points_per_table": rep_v.mean_points, "ci95": list(rep_v.ci95), "finish_hist": rep_v.finish_hist,
                  "finish_mean": rep_v.finish_mean, "win_rate": rep_v.win_rate, "cash_rate": rep_v.cash_rate},
        "reference_adapted": {"variant": rep_v.baseline_mean, "baseline_game": rep_b.baseline_mean},
        "candidate_baseline_game": {"points_per_table": rep_b.mean_points, "ci95": list(rep_b.ci95)},
        "reference_naive_variant": rep_n.mean_points,
        "paired": {"candidate_minus_adapted_ref_variant": [cand_vs_ref_v, list(rep_v.diff_ci95)],
                   "candidate_minus_adapted_ref_baseline": [cand_vs_ref_b, list(rep_b.diff_ci95)],
                   "adapted_ref_minus_naive_ref_variant": [gap_ref, [gap_ref - 1.96 * gap_ref_se, gap_ref + 1.96 * gap_ref_se]]},
        "by_archetype": _by_archetype(rep_v),
        "by_level": _by_level(rep_v, hpl, levels),
        "violations": violations, "reproducible_from_seed": reproducible, "replay_tables_checked": k,
        "deadline_mode": mode,
        "verdict": {"strength": strength, "adaptation": adaptation},
        "runs": {"variant": _slim(rep_v), "baseline_game": _slim(rep_b), "naive_reference": _slim(rep_n)},
        "notes": ["REHEARSAL: opponents are heuristic archetypes, payouts/blinds synthetic unless the variant sets them.",
                  f"Score = mean points per table with the 1 ms deadline {mode}ed (see deadline_mode); "
                  "over-deadline decisions are counted in violations.timeouts.",
                  "Verdicts are heuristics; see docs/arena.md for the definitions."],
    }
    if write_json:
        with open(os.path.join(out_dir, "hidden_eval.json"), "w") as f:
            json.dump(result, f, indent=1, default=str)
    return result


def format_result(r: dict) -> str:
    s = r["score"]
    lines = [
        f"HIDDEN EVALUATION  variant {r['mutation']}  tables {r['tables']}  seed {r['seed']}  {r['wall_s']:.0f}s",
        f"score: {s['points_per_table']:.2f} pts/table (95% CI {s['ci95'][0]:.2f}..{s['ci95'][1]:.2f})  finish {s['finish_mean']:.2f}"
        f"  win {s['win_rate']*100:.1f}%  top-4 {s['cash_rate']*100:.1f}%",
        f"adapted reference in the same seats: {r['reference_adapted']['variant']:.2f}; paired diff "
        f"{r['paired']['candidate_minus_adapted_ref_variant'][0]:+.2f} (CI {r['paired']['candidate_minus_adapted_ref_variant'][1][0]:+.2f}..{r['paired']['candidate_minus_adapted_ref_variant'][1][1]:+.2f})",
        f"standard hold'em diagnostic: candidate {r['candidate_baseline_game']['points_per_table']:.2f} vs reference {r['reference_adapted']['baseline_game']:.2f}",
        f"rule-naive reference under the variant: {r['reference_naive_variant']:.2f}  (adapted - naive {r['paired']['adapted_ref_minus_naive_ref_variant'][0]:+.2f})",
        f"verdict: strength (standard game) = {r['verdict']['strength']}; adaptation = {r['verdict']['adaptation']}",
        "by archetype (finished above / mean point diff): " + "  ".join(
            f"{k} {v['finished_above_rate']*100:.0f}%/{v['mean_point_diff']:+.1f}" for k, v in r["by_archetype"].items()),
        f"bust by blind level: {r['by_level']['bust_by_level']}  survival: " + " ".join(f"{x*100:.0f}%" for x in r["by_level"]["survival_to_end_of_level"]),
        f"violations: {r['violations']}  deadline {r['deadline_mode']}ed; reproducible from seed: {r['reproducible_from_seed']} "
        f"(replayed {r['replay_tables_checked']} tables)",
    ]
    return "\n".join(lines)
