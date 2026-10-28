"""Sealed challenge lifecycle: isolation, workspace, validator, session clock,
hidden evaluation, postmortem, and one bounded end-to-end smoke rehearsal.

Everything here runs the real sandbox and real subprocesses, so a few tests
take seconds. The smoke rehearsal uses a real (short) clock and is marked slow.
"""
import json
import os
import subprocess
import threading
import time

import pytest

from pokergym.arena import isolation, postmortem, standin
from pokergym.arena.grade import grade
from pokergym.arena.hidden_eval import hidden_evaluate
from pokergym.arena.mutations import generate
from pokergym.arena.session import Challenge
from pokergym.arena.validator import validate
from pokergym.arena.workspace import AGENT_TEMPLATE, build_workspace, reveal

FAST = {"tables": 2, "wall_timeout_s": 60}

BOTS = {
    "template": AGENT_TEMPLATE,
    "broken": standin.BROKEN,
    "illegal": standin.ILLEGAL,
    "hangs": standin.HANGS_ONCE,
    "adapted": standin.ADAPTED_HEURISTIC,
    "raises": '''class Action:
    __slots__ = ("kind", "amount")
    def __init__(self, kind, amount=0):
        self.kind, self.amount = kind, amount

class Agent:
    def reset(self, table):
        pass
    def act(self, obs):
        raise RuntimeError("boom")
''',
    "hangs_forever": '''import time

class Action:
    __slots__ = ("kind", "amount")
    def __init__(self, kind, amount=0):
        self.kind, self.amount = kind, amount

class Agent:
    def reset(self, table):
        pass
    def act(self, obs):
        while True:
            time.sleep(1)
''',
    "no_agent": "x = 1\n",
    "slow": '''import time

class Action:
    __slots__ = ("kind", "amount")
    def __init__(self, kind, amount=0):
        self.kind, self.amount = kind, amount

class Agent:
    def reset(self, table):
        pass
    def act(self, obs):
        time.sleep(0.003)  # 3 ms: every decision misses the 1 ms deadline
        return Action(1) if obs.can_check else Action(0)
''',
    "reads_repo": f'''import os
class Action:
    __slots__ = ("kind", "amount")
    def __init__(self, kind, amount=0):
        self.kind, self.amount = kind, amount
class Agent:
    def reset(self, table):
        open({os.path.join(isolation.REPO_ROOT, "pokergym", "bots", "sparring.py")!r}).read()
    def act(self, obs):
        return Action(1) if obs.can_check else Action(0)
''',
}


def _write(d, name, text):
    p = os.path.join(d, name + ".py")
    with open(p, "w") as f:
        f.write(text)
    return p


@pytest.fixture(scope="module")
def challenge(tmp_path_factory):
    """One sealed, started challenge shared by the fast tests (long window so the
    clock does not expire during the module)."""
    root = tmp_path_factory.mktemp("arena") / "ch"
    ch = Challenge.create(str(root), seed=11, duration_s=3600, cadence_s=2.0, validation=FAST)
    assert not os.path.exists(os.path.join(ch.ws, "variant.json"))  # sealed
    ch.start()
    return ch


# ----------------------------------------------------------------- isolation
def test_isolation_self_test_denies_repo_hidden_and_network(challenge):
    st = challenge.public["isolation_self_test"]
    assert challenge.public["isolation_level"] == "sandbox-exec", "sandbox-exec is required for enforceable isolation on macOS"
    assert st["ok"], st
    assert st["probe"]["import_pokergym"] != "IMPORTED"
    assert st["probe"]["network"] != "OPEN"
    assert all(v != "READABLE" for k, v in st["probe"].items() if k.startswith(isolation.REPO_ROOT) or "/hidden" in k or "/submissions" in k)


def test_sandboxed_bot_cannot_read_research_code(challenge):
    p = _write(challenge.ws, "reads_repo", BOTS["reads_repo"])
    rep = validate(p, challenge.ws, challenge.policy(), FAST, seed=1)
    assert not rep.accepted
    assert not rep.stage_passed("interface")  # reset() raised PermissionError inside the sandbox


def test_competitor_interpreter_is_isolated_from_site_packages():
    cp = subprocess.run([isolation.competitor_python(), "-I", "-S", "-c", "import pytest"], capture_output=True, text=True)
    assert cp.returncode != 0


# ----------------------------------------------------------------- workspace
def test_workspace_has_kit_but_no_research_or_secrets(challenge):
    ws = challenge.ws
    for f in ("my_agent.py", "run_local.py", "submit.py", "README.md", "kit/__init__.py", "kit/engine.py", "kit/icm.py",
              "variant.json", "BRIEFING.md", "payouts.json", "blinds.json", "examples/observations.json"):
        assert os.path.exists(os.path.join(ws, f)), f
    assert not os.path.exists(os.path.join(ws, "kit", "sparring.py"))
    assert not any("mutations" in n or "hidden" in n for n in os.listdir(os.path.join(ws, "kit")))
    text = open(os.path.join(ws, "BRIEFING.md")).read()
    assert "REHEARSAL" in text and "synthetic" in text.lower()
    with open(os.path.join(ws, "variant.json")) as f:
        v = json.load(f)
    assert v["name"] == challenge.mutation().name
    with open(os.path.join(ws, "examples", "observations.json")) as f:
        ex = json.load(f)
    assert len(ex) >= 5 and any(len(o["history"]) > 0 for o in ex)  # to_dict used to raise on non-empty history
    assert all("legal_actions" in o for o in ex)
    with open(os.path.join(ws, "examples", "observations.json")) as f:
        ex = json.load(f)
    assert len(ex) >= 5 and any(len(o["history"]) > 0 for o in ex)  # to_dict used to raise on non-empty history
    assert all("legal_actions" in o for o in ex)


def test_workspace_kit_runs_standalone_under_sandbox(challenge):
    argv = [isolation.competitor_python(), "-I", "-S", os.path.join(challenge.ws, "run_local.py"), "my_agent.py", "--tables", "1", "--seed", "3"]
    cp = isolation.run(challenge.policy(), argv, cwd=challenge.ws, timeout=120)
    assert cp.returncode == 0, cp.stderr[-500:]
    assert "points" in cp.stdout


def test_reveal_is_deterministic(tmp_path):
    m = generate(5)
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        build_workspace(str(d))
        reveal(str(d), m, seed=9)
    assert open(a / "examples" / "observations.json").read() == open(b / "examples" / "observations.json").read()
    assert open(a / "variant.json").read() == open(b / "variant.json").read()


# ----------------------------------------------------------------- validator
@pytest.mark.parametrize("name,failed_stage", [
    ("template", None), ("adapted", None), ("broken", "import"), ("no_agent", "interface"),
    ("illegal", "legality"), ("raises", "legality"), ("hangs", "legality"), ("slow", "timing"),
])
def test_validator_stages(challenge, name, failed_stage):
    p = _write(challenge.ws, "v_" + name, BOTS[name])
    t0 = time.perf_counter()
    rep = validate(p, challenge.ws, challenge.policy(), FAST, seed=1)
    assert time.perf_counter() - t0 < 60
    if failed_stage is None:
        assert rep.accepted, rep.summary()
        assert {s["name"] for s in rep.stages} == {"size", "import", "interface", "legality", "games", "errors", "timing"}
    else:
        assert not rep.accepted
        assert not rep.stage_passed(failed_stage), rep.summary()


def test_validator_stops_a_hung_agent_without_hanging(challenge):
    p = _write(challenge.ws, "v_hangs_forever", BOTS["hangs_forever"])
    t0 = time.perf_counter()
    rep = validate(p, challenge.ws, challenge.policy(), {**FAST, "hard_ms": 100}, seed=1)
    assert time.perf_counter() - t0 < 30
    assert not rep.accepted
    assert "HardTimeout" in rep.summary() or rep.error == "hung"


def test_validator_enforces_size_limit(challenge, monkeypatch):
    from pokergym.arena import validator

    monkeypatch.setattr(validator, "SIZE_LIMIT", 100)
    p = _write(challenge.ws, "v_big", AGENT_TEMPLATE)
    rep = validator.validate(p, challenge.ws, challenge.policy(), FAST, seed=1)
    assert not rep.accepted and rep.stages[0]["name"] == "size" and not rep.stages[0]["passed"]


def test_competition_mode_exercises_the_fallback(challenge):
    """The 'slow' bot misses every deadline: in enforce mode its decisions are
    replaced by check/fold, so the measured fallback effect is nonzero."""
    p = _write(challenge.ws, "v_slow2", BOTS["slow"])
    rep = validate(p, challenge.ws, challenge.policy(), FAST, seed=2)
    assert rep.metrics["timeout_frac"] > 0.5
    assert rep.metrics["decisions"] > 0 and rep.metrics["timeouts"] > 0
    assert not rep.stage_passed("timing")


# ----------------------------------------------------------------- session clock / submissions
def test_session_rules(challenge):
    ch = challenge
    with pytest.raises(RuntimeError):
        ch.start()  # the clock does not restart
    assert ch.verify_commitment()
    tpl = _write(ch.ws, "s_tpl", AGENT_TEMPLATE)
    # free check does not use a slot
    sub0 = ch.check(tpl)
    assert sub0.accepted is False and sub0.report["accepted"] is True  # a check never becomes active
    # first submit uses the slot
    s1 = ch.submit(tpl)
    assert s1.accepted and ch.active_submission()["index"] == s1.index
    # immutable, hashed copy
    assert not os.access(s1.path, os.W_OK)
    assert s1.sha256 == sub0.sha256
    with pytest.raises(PermissionError):
        open(s1.path, "a")
    # cadence
    r = ch.submit(tpl)
    assert isinstance(r, dict) and r["reason"] == "cadence"
    # milestones recorded with elapsed times
    ms = ch.state["milestones"]
    for k in ("first_executable_bot", "first_legal_decision", "first_completed_game", "first_accepted_submission"):
        assert k in ms and ms[k]["elapsed"] is not None and ms[k]["elapsed"] >= 0
    # rejected submission after the cadence passes: slot used, active unchanged
    time.sleep(ch.public["cadence_s"] + 0.1)
    bad = _write(ch.ws, "s_bad", BOTS["illegal"])
    s2 = ch.submit(bad)
    assert not s2.accepted and ch.active_submission()["index"] == s1.index
    # a better bot becomes active; rollback restores the earlier one
    time.sleep(ch.public["cadence_s"] + 0.1)
    s3 = ch.submit(_write(ch.ws, "s_adapted", BOTS["adapted"]))
    assert s3.accepted and ch.active_submission()["index"] == s3.index
    with pytest.raises(ValueError):
        ch.rollback(s2.index)
    ch.rollback(s1.index)
    assert ch.active_submission()["index"] == s1.index
    ch.rollback(s3.index)
    # events are an append-only replayable record
    types = [e["type"] for e in ch.events()]
    assert types[0] == "created" and "start" in types and "submission_too_early" in types and "rollback" in types
    status = ch.status()
    assert status["active"]["index"] == s3.index and status["elapsed_s"] > 0
    assert os.path.exists(os.path.join(ch.ws, "status.json"))


def test_inbox_protocol_via_submit_py(challenge):
    """The competitor talks to the host only through workspace/submit.py -> inbox."""
    ch = challenge
    argv = [isolation.competitor_python(), "-I", "-S", os.path.join(ch.ws, "submit.py"), "my_agent.py", "--check", "--wait", "60"]
    cp = subprocess.Popen(argv, cwd=ch.ws, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          env={"PATH": os.environ.get("PATH", "")})
    # host side
    deadline = time.time() + 30
    n = 0
    while n == 0 and time.time() < deadline:
        time.sleep(0.2)
        n = ch.process_inbox()
    out, err = cp.communicate(timeout=60)
    assert n == 1 and "ACCEPTED" in out, (out, err)
    assert not [f for f in os.listdir(ch.inbox) if f.endswith(".req.json")]


def test_not_started_and_frozen_rejections(tmp_path):
    ch = Challenge.create(str(tmp_path / "c"), seed=3, duration_s=1.0, cadence_s=1.0, validation=FAST, self_test=False)
    tpl = _write(str(tmp_path), "tpl", AGENT_TEMPLATE)
    assert ch.submit(tpl)["reason"] == "not started"
    ch.start()
    time.sleep(1.1)
    r = ch.submit(tpl)
    assert r["reason"] == "frozen" and ch.state["frozen"]
    assert [e for e in ch.events() if e["type"] == "freeze"][0]["reason"] == "clock"


# ----------------------------------------------------------------- hidden evaluation
def test_hidden_eval_is_reproducible_and_separates_adaptation(challenge, tmp_path):
    ch = challenge
    active = ch.active_submission()
    seed = ch.secret()["hidden_eval_seed"]
    a = hidden_evaluate(ch.mutation(), active["path"], str(tmp_path / "a"), seed=seed, workspace=ch.ws, tables=40, workers=1, baseline_tables=20)
    b = hidden_evaluate(ch.mutation(), active["path"], str(tmp_path / "b"), seed=seed, workspace=ch.ws, tables=40, workers=2, baseline_tables=20)
    assert a["score"] == b["score"] and a["by_archetype"] == b["by_archetype"]
    assert a["reproducible_from_seed"] and a["deadline_mode"] == "record"
    assert set(a["by_archetype"]) == {"nit", "maniac", "station", "rock", "trapper", "shark", "pusher"}
    assert len(a["by_level"]["bust_by_level"]) == 8
    assert a["violations"]["illegal"] == 0 and a["violations"]["errors"] == 0
    assert {"strength", "adaptation"} <= set(a["verdict"])
    assert "candidate_minus_adapted_ref_variant" in a["paired"] and "adapted_ref_minus_naive_ref_variant" in a["paired"]
    c = hidden_evaluate(ch.mutation(), active["path"], str(tmp_path / "c"), seed=seed + 1, workspace=ch.ws, tables=40, workers=1, baseline_tables=20)
    assert c["score"] != a["score"]


# ----------------------------------------------------------------- grading + postmortem
def test_grade_and_postmortem(challenge):
    ch = challenge
    res = grade(ch, tables=40, workers=2, all_accepted=True, quiet=True)
    assert ch.state["frozen"] and res is not None
    assert os.path.exists(os.path.join(ch.results, "hidden_eval.json"))
    per = json.load(open(os.path.join(ch.results, "per_submission.json")))
    assert len(per) >= 2  # trajectory over accepted submissions
    md = open(os.path.join(ch.results, "postmortem.md")).read()
    for h in ("Which rule changed", "Timeline", "Where the time went", "Final score", "Failure classification",
              "missed opportunities", "Recommendations"):
        assert h in md, h
    assert "first accepted submission" in md
    assert ch.mutation().name in md
    assert "NON-STANDARD" in md  # the 2 s cadence is flagged; the 3600 s window alone would not be
    cls = postmortem.classify(ch, res)
    assert cls and all(c["code"] in "ABCDEF" for c in cls)
    ms = ch.state["milestones"]
    assert "final_verified_submission" in ms


# ----------------------------------------------------------------- bounded end-to-end rehearsal
@pytest.mark.slow
def test_smoke_rehearsal_with_standin_competitor(tmp_path):
    """Real clock, 45 s window, 5 s cadence, serving host in a thread, stand-in
    competitor acting only through the sandboxed submit.py."""
    root = str(tmp_path / "smoke")
    t0 = time.time()
    ch = Challenge.create(root, seed=11, duration_s=45, cadence_s=5, validation={"tables": 2})
    assert ch.public["clock_warning"].startswith("NON-STANDARD")
    ch.start()
    host = Challenge(root)
    th = threading.Thread(target=host.serve, kwargs={"until_frozen": True, "quiet": True}, daemon=True)
    th.start()
    outs = standin.run_script(ch, log=lambda *_: None)
    th.join(timeout=120)
    ch = Challenge(root)
    assert ch.state["frozen"]
    # the script's expected outcomes, in order
    assert outs[0].startswith("CHECK ACCEPTED")
    assert outs[1].startswith("REJECTED") and "import" in outs[1]
    assert "next slot" in outs[2]
    assert outs[3].startswith("REJECTED") and "legality" in outs[3]
    assert outs[4] == "noted"
    assert outs[5].startswith("ACCEPTED")
    assert outs[6].startswith("REJECTED") and "HardTimeout" in outs[6]
    assert outs[7].startswith("CHECK ACCEPTED")
    assert outs[8].startswith("ACCEPTED")
    assert ch.active_submission()["sha256"] == ch.state["submissions"][-1]["sha256"]
    res = grade(ch, tables=40, workers=2, all_accepted=True, quiet=True)
    assert res["violations"]["illegal"] == 0
    md = open(os.path.join(ch.results, "postmortem.md")).read()
    assert "NON-STANDARD CLOCK" in md
    assert time.time() - t0 < 180


def test_cli_entry_points_exist():
    from pokergym.arena import __main__ as cli

    for c in ("create", "start", "serve", "status", "check", "submit", "note", "freeze", "rollback", "grade", "postmortem",
              "smoke", "rehearse", "reserve"):
        assert hasattr(cli, "cmd_" + c.replace("-", "_"))
