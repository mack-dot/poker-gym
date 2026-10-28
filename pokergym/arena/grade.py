"""Grade a frozen challenge: hidden evaluation of the active bot (and
optionally every accepted submission, to see the trajectory), then the
postmortem."""
from __future__ import annotations

import json
import os

from . import postmortem
from .hidden_eval import format_result, hidden_evaluate
from .session import Challenge


def grade(ch: Challenge, tables: int = 1000, workers: int = 1, all_accepted: bool = False, quiet: bool = False) -> dict | None:
    if not ch.state["frozen"]:
        ch.freeze(reason="grade")
    secret = ch.secret()
    m = ch.mutation()
    active = ch.active_submission()
    per_sub = {}
    if all_accepted:
        for s in ch.state["submissions"]:
            if s["kind"] == "submit" and s["accepted"] and (active is None or s["index"] != active["index"]):
                r = hidden_evaluate(m, s["path"], os.path.join(ch.results, f"sub_{s['index']:03d}"), seed=secret["hidden_eval_seed"],
                                    workspace=ch.ws, tables=max(50, tables // 4), workers=workers, baseline_tables=50)
                per_sub[str(s["index"])] = r["score"]["points_per_table"]
                ch.event("hidden_eval_submission", index=s["index"], points=r["score"]["points_per_table"], tables=r["tables"])
    result = None
    if active is not None:
        result = hidden_evaluate(m, active["path"], ch.results, seed=secret["hidden_eval_seed"], workspace=ch.ws,
                                 tables=tables, workers=workers)
        per_sub[str(active["index"])] = result["score"]["points_per_table"]
        ch.event("hidden_eval", index=active["index"], points=result["score"]["points_per_table"], ci95=result["score"]["ci95"],
                 tables=tables, violations=result["violations"], verdict=result["verdict"])
        if not quiet:
            print(format_result(result))
    else:
        ch.event("hidden_eval", index=None, points=None, note="no accepted submission")
        if not quiet:
            print("no accepted submission: score 0 (nothing to evaluate)")
    with open(os.path.join(ch.results, "per_submission.json"), "w") as f:
        json.dump(per_sub, f, indent=1)
    path = postmortem.write(ch, result, per_sub)
    if not quiet:
        print(f"postmortem: {path}")
    return result
