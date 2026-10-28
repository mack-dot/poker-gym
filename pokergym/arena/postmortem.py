"""Postmortem report for one rehearsal: what changed, how fast we noticed,
what we tried, what scored, and where the time went.

All timings come from ``events.jsonl`` (wall clock). Time-allocation and
failure-class attributions are heuristics over the event stream and are
labelled as such in the report.
"""
from __future__ import annotations

import difflib
import json
import os
import time

from .session import Challenge

FAILURE_CLASSES = {
    "A": "Misunderstanding the game",
    "B": "Implementing the rules incorrectly",
    "C": "Weak strategy",
    "D": "Poor experimental design",
    "E": "Runtime violations",
    "F": "Wasting development time",
}


def _fmt_t(s: float | None) -> str:
    if s is None:
        return "-"
    m, sec = divmod(int(s), 60)
    return f"{m:02d}:{sec:02d}"


def _revision_stats(subs: list[dict]) -> list[dict]:
    out = []
    prev = None
    for s in subs:
        try:
            src = open(s["path"], encoding="utf-8").read().splitlines()
        except OSError:
            src = []
        added = removed = 0
        if prev is not None:
            for line in difflib.unified_diff(prev, src, lineterm="", n=0):
                if line.startswith("+") and not line.startswith("+++"):
                    added += 1
                elif line.startswith("-") and not line.startswith("---"):
                    removed += 1
        out.append({"index": s["index"], "lines": len(src), "added": added, "removed": removed})
        prev = src
    return out


def _time_allocation(events: list[dict], duration: float) -> dict:
    """Heuristic: classify the gap before each validation event by what the
    previous validation said; testing = validator wall time."""
    alloc = {"implementing": 0.0, "debugging": 0.0, "testing": 0.0, "optimizing": 0.0, "idle_after_freeze": 0.0}
    start = next((e["t"] for e in events if e["type"] == "start"), None)
    if start is None:
        return alloc
    last_t = start
    last_outcome = None  # None | "fail" | "ok"
    for e in events:
        if e["type"] != "validated":
            continue
        gap = max(0.0, e["t"] - last_t - e.get("seconds", 0.0))
        if last_outcome is None:
            alloc["implementing"] += gap
        elif last_outcome == "fail":
            alloc["debugging"] += gap
        else:
            alloc["optimizing"] += gap
        alloc["testing"] += e.get("seconds", 0.0)
        last_outcome = "ok" if e["accepted"] else "fail"
        last_t = e["t"]
    freeze = next((e["t"] for e in events if e["type"] == "freeze"), None)
    if freeze is not None:
        alloc["unused_before_freeze"] = max(0.0, freeze - last_t)
    return alloc


def classify(ch: Challenge, hidden: dict | None) -> list[dict]:
    st = ch.state
    subs = st["submissions"]
    duration = ch.public["duration_s"]
    ev = ch.events()
    out = []

    def add(code, evidence, weight):
        out.append({"code": code, "name": FAILURE_CLASSES[code], "evidence": evidence, "weight": weight})

    # E runtime
    rt = [s for s in subs if not s["report"]["accepted"] and any(x["name"] in ("timing", "errors", "import") and not x["passed"] for x in s["report"]["stages"])]
    viol = (hidden or {}).get("violations", {})
    if rt or any(viol.get(k, 0) for k in ("illegal", "errors", "timeouts")):
        add("E", f"{len(rt)} validation failures on import/errors/timing; hidden-eval violations {viol}", 2 if viol and any(viol.get(k, 0) for k in ('illegal','errors','timeouts')) else 1)
    # B rules implemented incorrectly
    leg = [s for s in subs if any(x["name"] == "legality" and not x["passed"] for x in s["report"]["stages"])]
    if leg:
        add("B", f"{len(leg)} validation(s) failed legality (illegal actions)", 1)
    # A misunderstanding / C weak strategy from hidden eval
    if hidden:
        v = hidden["verdict"]
        if "not fully absorbed" in v["adaptation"]:
            add("A", "hidden eval: candidate lost more than the adapted reference moving from standard poker to the variant", 2)
        if "weaker" in v["strength"]:
            add("C", f"hidden eval: {hidden['candidate_baseline_game']['points_per_table']:.1f} vs reference "
                     f"{hidden['reference_adapted']['baseline_game']:.1f} pts/table in standard hold'em", 2)
        if hidden["score"]["points_per_table"] < hidden["reference_naive_variant"]:
            add("C", f"scored below the rule-naive reference ({hidden['score']['points_per_table']:.1f} < {hidden['reference_naive_variant']:.1f})", 1)
    # D experimental design
    checks = [s for s in subs if s["kind"] == "check"]
    submits = [s for s in subs if s["kind"] == "submit"]
    notes = st.get("notes", [])
    if submits and len(checks) < len(submits):
        add("D", f"{len(submits)} submissions but only {len(checks)} local checks: submitting consumed slots that a free check would have saved", 1)
    if not notes:
        add("D", "no hypotheses logged (submit.py --note); the postmortem cannot tell what was being tested", 1)
    # F time
    fa = st["milestones"].get("first_accepted_submission", {}).get("elapsed")
    if fa is None:
        add("F", "no accepted submission before the freeze", 3)
    elif fa > 0.4 * duration:
        add("F", f"first accepted submission at {_fmt_t(fa)} ({fa/duration*100:.0f}% of the window); a safe bot should be in within 25%", 2)
    gaps = []
    ts = [e["t"] for e in ev if e["type"] in ("start", "validated", "note", "freeze")]
    for a, b in zip(ts, ts[1:]):
        gaps.append(b - a)
    if gaps and max(gaps) > 0.3 * duration:
        add("F", f"longest silence {_fmt_t(max(gaps))} without a check, submission or note", 1)
    out.sort(key=lambda d: -d["weight"])
    return out


def recommendations(classes: list[dict], ch: Challenge, hidden: dict | None) -> list[str]:
    codes = {c["code"] for c in classes}
    recs = []
    if "F" in codes:
        recs.append("Submit the unmodified template within the first 5 minutes, then the kit's heuristic bot wrapped for the variant by minute 15; never be without an accepted bot.")
    if "B" in codes or "E" in codes:
        recs.append("Run `submit.py --check` after every edit; it is free and records the milestone. Fix legality/exception failures before touching strategy.")
    if "A" in codes:
        recs.append("Spend the first 10 minutes writing down, from the briefing, which standard assumptions break; encode each as a unit test on the kit's evaluator/engine before coding strategy.")
    if "C" in codes:
        recs.append("Start from the strongest legal baseline you can copy (kit heuristic), then change one knob at a time and keep only paired improvements.")
    if "D" in codes:
        recs.append("Log one `--note` per hypothesis and pair every candidate against the previous accepted bot in run_local.py with the same seeds before submitting.")
    if hidden and hidden["violations"].get("timeouts", 0):
        recs.append("Decisions over 1 ms were replaced by check/fold in the hidden evaluation; profile act() with run_local.py latency output.")
    if not recs:
        recs.append("No failure class dominated. Next rehearsal: tighten the clock targets (first accepted < 10 min, first competitive < 30 min).")
    return recs


def render(ch: Challenge, hidden: dict | None, per_submission: dict | None = None) -> str:
    m = ch.mutation()
    st = ch.state
    ev = ch.events()
    subs = st["submissions"]
    duration = ch.public["duration_s"]
    ms = st["milestones"]
    start_ev = next((e for e in ev if e["type"] == "start"), None)
    first_touch = next((e["elapsed"] for e in ev if e["type"] in ("validated", "note")), None)
    lines = [
        f"# Postmortem: {ch.public['id']} ({m.name})",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M:%S')}. Clock: {duration:g}s window, {ch.public['cadence_s']:g}s cadence"
        + (f". **{ch.public['clock_warning']}**" if ch.public.get("clock_warning") else "") + ".",
        f"Isolation: {ch.public.get('isolation_level')} (self-test ok = {ch.public.get('isolation_self_test', {}).get('ok')}). "
        f"Commitment verified: {ch.verify_commitment()}.",
        "",
        "## 1. Which rule changed",
        "",
        m.headline,
        "",
        "Conventional assumptions that became invalid:",
        *[f"- {x}" for x in m.invalidated],
        "",
        "## 2. Timeline (mm:ss from start)",
        "",
        f"- start: {start_ev['iso'] if start_ev else '-'}",
        f"- first recorded activity (check/note): {_fmt_t(first_touch)}  <- proxy for 'recognized the change and acted'",
        *[f"- {k.replace('_', ' ')}: {_fmt_t(v.get('elapsed'))}" for k, v in ms.items()],
        f"- freeze: {_fmt_t(next((e['elapsed'] for e in ev if e['type'] == 'freeze'), None))}",
        "",
        "### Submissions and checks",
        "",
        "| # | at | kind | sha256 | result | failed stages | edge vs fold bot | p99 us | notes |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    revs = {r["index"]: r for r in _revision_stats(subs)}
    for s in subs:
        rep = s["report"]
        failed = ",".join(x["name"] for x in rep["stages"] if not x["passed"]) or "-"
        met = rep.get("metrics", {})
        r = revs[s["index"]]
        hs = (per_submission or {}).get(str(s["index"]))
        extra = f"+{r['added']}/-{r['removed']} lines" + (f"; hidden {hs:.1f}" if hs is not None else "")
        edge = f"{met['edge_over_fold_bot']:+.1f}" if "edge_over_fold_bot" in met else "-"
        p99 = f"{met['lat_p99_us']:.0f}" if "lat_p99_us" in met else "-"
        lines.append(f"| {s['index']} | {_fmt_t(s['elapsed'])} | {s['kind']} | {s['sha256'][:10]} | "
                     f"{'ACCEPTED' if rep['accepted'] else 'rejected'}{' (active)' if st.get('active') == s['index'] else ''} | {failed} | "
                     f"{edge} | {p99} | {extra} |")
    lines += ["", "### Hypotheses logged", ""]
    lines += [f"- {_fmt_t(n['elapsed'])} {n['text']}" for n in st.get("notes", [])] or ["- none"]
    alloc = _time_allocation(ev, duration)
    lines += ["", "## 3. Where the time went (heuristic from event gaps)", ""]
    lines += [f"- {k}: {_fmt_t(v)}" for k, v in alloc.items()]
    lines += ["", "## 4. Final score against withheld opponents", ""]
    if hidden:
        s = hidden["score"]
        lines += [
            f"- **{s['points_per_table']:.2f} points/table** (95% CI {s['ci95'][0]:.2f}..{s['ci95'][1]:.2f}) over {hidden['tables']} tables, variant `{hidden['mutation']}`.",
            f"- Adapted reference in the same seats: {hidden['reference_adapted']['variant']:.2f}; rule-naive reference: {hidden['reference_naive_variant']:.2f}.",
            f"- Standard hold'em diagnostic: candidate {hidden['candidate_baseline_game']['points_per_table']:.2f} vs reference {hidden['reference_adapted']['baseline_game']:.2f}.",
            f"- Verdict: strength = {hidden['verdict']['strength']}; adaptation = {hidden['verdict']['adaptation']}.",
            "- By archetype (finished above / point diff): " + ", ".join(
                f"{k} {v['finished_above_rate']*100:.0f}%/{v['mean_point_diff']:+.1f}" for k, v in hidden["by_archetype"].items()),
            f"- Bust by blind level: {hidden['by_level']['bust_by_level']}",
            f"- Runtime violations: {hidden['violations']} (reproducible from seed: {hidden['reproducible_from_seed']})",
        ]
    else:
        lines.append("- no hidden evaluation run (`python -m pokergym.arena grade <root>`)")
    classes = classify(ch, hidden)
    lines += ["", "## 5. Failure classification (A-F, heuristic)", ""]
    lines += [f"- **{c['code']}. {c['name']}** (weight {c['weight']}): {c['evidence']}" for c in classes] or ["- no failure class triggered"]
    lines += ["", "## 6. Highest-impact missed opportunities", ""]
    missed = []
    if hidden:
        worst = min(hidden["by_archetype"].items(), key=lambda kv: kv[1]["mean_point_diff"])
        missed.append(f"Largest point leak to a single archetype: {worst[0]} ({worst[1]['mean_point_diff']:+.1f}/table).")
        bl = hidden["by_level"]["bust_by_level"]
        if sum(bl):
            lvl = max(range(len(bl)), key=lambda i: bl[i])
            missed.append(f"Most eliminations in blind level {lvl + 1} ({bl[lvl]} of {sum(bl)}): stack-depth play there decided the finish.")
    if ms.get("first_accepted_submission") and not ms.get("first_competitive_policy"):
        missed.append("No submission beat the check/fold bot by 5 points on the validator's seeds: the active bot was safe, not competitive.")
    if alloc.get("unused_before_freeze", 0) > 0.2 * duration:
        missed.append(f"{_fmt_t(alloc['unused_before_freeze'])} between the last validation and the freeze went unused.")
    lines += [f"- {x}" for x in missed] or ["- none identified"]
    lines += ["", "## 7. Recommendations for the next rehearsal", ""]
    lines += [f"- {r}" for r in recommendations(classes, ch, hidden)]
    lines += ["", "---", "Sources: events.jsonl, state.json, results/hidden_eval.json. Attributions in sections 3 and 5 are heuristics.", ""]
    return "\n".join(lines)


def write(ch: Challenge, hidden: dict | None = None, per_submission: dict | None = None) -> str:
    if hidden is None:
        p = os.path.join(ch.results, "hidden_eval.json")
        if os.path.exists(p):
            with open(p) as f:
                hidden = json.load(f)
    if per_submission is None:
        p = os.path.join(ch.results, "per_submission.json")
        if os.path.exists(p):
            with open(p) as f:
                per_submission = json.load(f)
    text = render(ch, hidden, per_submission)
    out = os.path.join(ch.results, "postmortem.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    ch.event("postmortem", path=out)
    return out
