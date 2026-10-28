"""Challenge lifecycle: seal -> start (real clock) -> submissions -> freeze -> grade.

Directory layout of a challenge root:

    challenge.json     public: id, commitment hash of the sealed variant, clock config
    workspace/         the competitor's world (see workspace.py)
    inbox/             competitor -> host requests (submit / check / note) and results
    staging/           transient readable copy of the file under validation
    hidden/            sealed variant, hidden-eval seeds and opponents  [denied to competitor]
    submissions/       immutable copies of every submission            [denied]
    events.jsonl       append-only log with wall-clock timestamps      [denied]
    state.json         clock + submission state                        [denied]
    results/           hidden evaluation, postmortem                   [denied]

The clock is ``time.time()`` recorded at ``start()``; nothing resets it.
Default duration 3600 s and cadence 300 s (rules 3.3, 3.5). Shorter values
are allowed for smoke rehearsals and are recorded in ``challenge.json`` so a
report can never pass a 2-minute smoke off as a 60-minute session.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import stat
import time
from dataclasses import dataclass

from . import isolation
from .mutations import Mutation, generate
from .validator import DEFAULT_CONFIG, ValidationReport, validate
from .workspace import build_workspace, reveal

COMPETITIVE_EDGE = 5.0  # REHEARSAL heuristic: points/table above the check/fold bot on the validator's seeds
HOST_ONLY = ("hidden", "submissions", "results", "events.jsonl", "state.json", "challenge.json")


def _now() -> float:
    return time.time()


def _hidden_seed(salt: str, purpose: str) -> int:
    return int(hashlib.sha256(f"{salt}:{purpose}".encode()).hexdigest()[:8], 16)


@dataclass
class Submission:
    index: int
    sha256: str
    path: str
    t: float
    elapsed: float
    accepted: bool
    kind: str                    # "submit" | "check"
    report: dict
    source_name: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class Challenge:
    def __init__(self, root: str):
        self.root = os.path.realpath(root)
        self.ws = os.path.join(self.root, "workspace")
        self.inbox = os.path.join(self.root, "inbox")
        self.hidden = os.path.join(self.root, "hidden")
        self.subs_dir = os.path.join(self.root, "submissions")
        self.results = os.path.join(self.root, "results")
        self.reload()

    def reload(self) -> None:
        """Re-read the on-disk state (the serving host process is the authority;
        other readers call this before looking at `state`)."""
        self.public = self._load_json("challenge.json")
        self.state = self._load_json("state.json")

    # ------------------------------------------------------------ files
    def _path(self, *p) -> str:
        return os.path.join(self.root, *p)

    def _load_json(self, name: str) -> dict:
        p = self._path(name)
        if not os.path.exists(p):
            return {}
        with open(p) as f:
            return json.load(f)

    def _save(self) -> None:
        for name, obj in (("challenge.json", self.public), ("state.json", self.state)):
            tmp = self._path(name + ".tmp")
            with open(tmp, "w") as f:
                json.dump(obj, f, indent=1, sort_keys=True)
            os.replace(tmp, self._path(name))
        self._write_status()

    def event(self, etype: str, **data) -> dict:
        t = _now()
        ev = {"t": t, "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t)),
              "elapsed": (t - self.state["started_at"]) if self.state.get("started_at") else None, "type": etype, **data}
        with open(self._path("events.jsonl"), "a") as f:
            f.write(json.dumps(ev, sort_keys=True) + "\n")
        return ev

    def events(self) -> list[dict]:
        p = self._path("events.jsonl")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(l) for l in f if l.strip()]

    # ------------------------------------------------------------ policy
    def policy(self) -> isolation.Policy:
        return isolation.Policy(deny_read=[isolation.REPO_ROOT] + [self._path(x) for x in HOST_ONLY],
                                allow=[self.ws, self.inbox], network=False)

    # ------------------------------------------------------------ create
    @classmethod
    def create(cls, root: str, seed: int, family: str | None = None, duration_s: float = 3600.0,
               cadence_s: float = 300.0, validation: dict | None = None, self_test: bool = True) -> "Challenge":
        root = os.path.realpath(root)
        if os.path.exists(root):
            raise FileExistsError(root)
        os.makedirs(root)
        for d in ("inbox", "hidden", "submissions", "results", "staging"):
            os.makedirs(os.path.join(root, d))
        m = generate(seed, family)
        salt = secrets.token_hex(16)
        mdict = m.to_dict()
        commitment = hashlib.sha256((json.dumps(mdict, sort_keys=True) + salt).encode()).hexdigest()
        secret = {"seed": seed, "family": m.family, "mutation": mdict, "salt": salt,
                  "hidden_eval_seed": _hidden_seed(salt, "hidden-eval"),
                  "validation_seed": _hidden_seed(salt, "validation"),
                  "opponents": "pokergym.arena.hidden_opponents.HIDDEN_LINEUP"}
        with open(os.path.join(root, "hidden", "secret.json"), "w") as f:
            json.dump(secret, f, indent=1)
        build_workspace(os.path.join(root, "workspace"))
        ch = cls(root)
        ch.public = {
            "id": os.path.basename(root), "created_at": _now(), "commitment": commitment,
            "duration_s": duration_s, "cadence_s": cadence_s, "status": "sealed",
            "validation": {**DEFAULT_CONFIG, **(validation or {})},
            "isolation_level": isolation.level(),
            "note": "REHEARSAL challenge generated by pokergym.arena; the variant is sealed under `commitment` "
                    "= sha256(json(mutation) + salt).",
        }
        if duration_s != 3600.0 or cadence_s != 300.0:
            self_label = f"NON-STANDARD CLOCK: duration {duration_s:g}s, cadence {cadence_s:g}s (official: 3600/300)"
            ch.public["clock_warning"] = self_label
        ch.state = {"started_at": None, "freeze_at": None, "frozen": False, "submissions": [], "active": None,
                    "last_slot_used_at": None, "milestones": {}, "notes": []}
        if self_test:
            ch.public["isolation_self_test"] = isolation.self_test(
                ch.policy(), ch.ws,
                must_fail=[os.path.join(isolation.REPO_ROOT, "pokergym", "bots", "sparring.py"),
                           os.path.join(ch.hidden, "secret.json"), ch.hidden, ch.subs_dir],
                must_pass=[os.path.join(ch.ws, "README.md"), ch.inbox])
        ch._save()
        ch.event("created", seed=seed, family=m.family, commitment=commitment, isolation=ch.public.get("isolation_self_test"))
        return ch

    # ------------------------------------------------------------ secrets (host only)
    def secret(self) -> dict:
        with open(os.path.join(self.hidden, "secret.json")) as f:
            return json.load(f)

    def mutation(self) -> Mutation:
        return Mutation.from_dict(self.secret()["mutation"])

    def verify_commitment(self) -> bool:
        s = self.secret()
        return hashlib.sha256((json.dumps(s["mutation"], sort_keys=True) + s["salt"]).encode()).hexdigest() == self.public["commitment"]

    # ------------------------------------------------------------ clock
    def start(self) -> dict:
        if self.state.get("started_at"):
            raise RuntimeError("already started; the clock does not restart")
        m = self.mutation()
        reveal(self.ws, m, seed=self.secret()["validation_seed"])
        t = _now()
        self.state["started_at"] = t
        self.state["freeze_at"] = t + self.public["duration_s"]
        self.public["status"] = "running"
        self._save()
        return self.event("start", variant=m.name, freeze_at=self.state["freeze_at"])

    def elapsed(self) -> float | None:
        return None if not self.state.get("started_at") else _now() - self.state["started_at"]

    def tick(self) -> None:
        """Freeze when the clock has run out (called by every public operation)."""
        if self.state.get("started_at") and not self.state["frozen"] and _now() >= self.state["freeze_at"]:
            self.freeze(reason="clock")

    def freeze(self, reason: str = "manual") -> dict:
        if self.state["frozen"]:
            return {"frozen": True}
        self.state["frozen"] = True
        self.state["frozen_at"] = _now()
        self.public["status"] = "frozen"
        self._save()
        active = self.state.get("active")
        ev = self.event("freeze", reason=reason, active=active)
        if active is not None:
            self._milestone("final_verified_submission", active_sha=self.state["submissions"][active]["sha256"])
        return ev

    def next_slot_at(self) -> float | None:
        last = self.state.get("last_slot_used_at")
        if last is None:
            return self.state.get("started_at")
        return last + self.public["cadence_s"]

    # ------------------------------------------------------------ competitor requests
    def note(self, text: str) -> dict:
        self.tick()
        self.state["notes"].append({"t": _now(), "elapsed": self.elapsed(), "text": text})
        self._save()
        return self.event("note", text=text)

    def check(self, path: str, source_name: str = "") -> Submission:
        """Validate without consuming a slot. Milestones still count."""
        self.tick()
        return self._process(path, kind="check", source_name=source_name)

    def submit(self, path: str, source_name: str = "") -> Submission | dict:
        self.tick()
        if not self.state.get("started_at"):
            return {"accepted": False, "reason": "not started", "summary": "REJECTED: the challenge has not started"}
        if self.state["frozen"]:
            return {"accepted": False, "reason": "frozen", "summary": "REJECTED: submissions are frozen (minute 60 passed)"}
        nxt = self.next_slot_at()
        now = _now()
        if nxt is not None and now < nxt:
            wait = nxt - now
            self.event("submission_too_early", wait_s=wait)
            return {"accepted": False, "reason": "cadence",
                    "summary": f"REJECTED: one submission per {self.public['cadence_s']:.0f}s; next slot in {wait:.0f}s"}
        sub = self._process(path, kind="submit", source_name=source_name)
        self.state["last_slot_used_at"] = sub.t  # REHEARSAL: a validated submission (accepted or not) uses the slot
        if sub.accepted:
            self.state["active"] = sub.index
            self.event("active_changed", index=sub.index, sha256=sub.sha256)
        self._save()
        return sub

    def _process(self, path: str, kind: str, source_name: str) -> Submission:
        idx = len(self.state["submissions"])
        digest_short = hashlib.sha256(open(path, "rb").read()).hexdigest()[:12]
        dst = os.path.join(self.subs_dir, f"{idx:03d}_{kind}_{digest_short}.py")
        shutil.copyfile(path, dst)
        os.chmod(dst, stat.S_IRUSR | stat.S_IRGRP)  # immutable copy
        t = _now()
        # The sandbox cannot read submissions/, so validate a staging copy.
        staged = os.path.join(self.root, "staging", f"{idx:03d}.py")
        shutil.copyfile(dst, staged)
        try:
            rep: ValidationReport = validate(staged, self.ws, self.policy(), self.public["validation"], seed=self.secret()["validation_seed"])
        finally:
            try:
                os.remove(staged)
            except OSError:
                pass
        sub = Submission(index=idx, sha256=rep.sha256, path=dst, t=t, elapsed=(t - self.state["started_at"]) if self.state.get("started_at") else None,
                         accepted=rep.accepted and kind == "submit", kind=kind, report=rep.to_dict(), source_name=source_name)
        self.state["submissions"].append(sub.to_dict())
        self.event("validated", kind=kind, index=idx, sha256=rep.sha256, accepted=rep.accepted,
                   stages={s["name"]: s["passed"] for s in rep.stages}, metrics=rep.metrics, seconds=rep.seconds)
        # milestones
        if rep.stage_passed("import"):
            self._milestone("first_executable_bot", index=idx)
        if rep.stage_passed("legality"):
            self._milestone("first_legal_decision", index=idx)
        if rep.stage_passed("games"):
            self._milestone("first_completed_game", index=idx)
        if kind == "submit" and rep.accepted:
            self._milestone("first_accepted_submission", index=idx)
            if rep.metrics.get("edge_over_fold_bot", 0) >= COMPETITIVE_EDGE:
                self._milestone("first_competitive_policy", index=idx, edge=rep.metrics["edge_over_fold_bot"])
        self._save()
        return sub

    def _milestone(self, name: str, **data) -> None:
        if name in self.state["milestones"]:
            return
        self.state["milestones"][name] = {"t": _now(), "elapsed": self.elapsed(), **data}
        self.event("milestone", name=name, **data)

    def rollback(self, index: int) -> dict:
        """Make an earlier accepted submission the active bot (host action)."""
        subs = self.state["submissions"]
        if not (0 <= index < len(subs)) or not subs[index]["accepted"]:
            raise ValueError("can only roll back to an accepted submission")
        self.state["active"] = index
        self._save()
        return self.event("rollback", index=index, sha256=subs[index]["sha256"])

    def active_submission(self) -> dict | None:
        a = self.state.get("active")
        return None if a is None else self.state["submissions"][a]

    # ------------------------------------------------------------ status
    def status(self) -> dict:
        self.tick()
        now = _now()
        st = self.state
        subs = st["submissions"]
        active = self.active_submission()
        d = {
            "id": self.public["id"], "status": self.public["status"], "now": now,
            "started_at": st.get("started_at"), "elapsed_s": self.elapsed(),
            "remaining_s": None if not st.get("started_at") else max(0.0, st["freeze_at"] - now),
            "frozen": st["frozen"],
            "next_slot_in_s": None if not st.get("started_at") else max(0.0, (self.next_slot_at() or now) - now),
            "submissions": len([s for s in subs if s["kind"] == "submit"]),
            "checks": len([s for s in subs if s["kind"] == "check"]),
            "active": None if active is None else {"index": active["index"], "sha256": active["sha256"][:12],
                                                   "points_vs_fillers": active["report"]["metrics"].get("points_enforced")},
            "last_result": None if not subs else {"kind": subs[-1]["kind"], "accepted": subs[-1]["accepted"],
                                                   "stages": {s["name"]: s["passed"] for s in subs[-1]["report"]["stages"]}},
            "milestones": {k: v.get("elapsed") for k, v in st["milestones"].items()},
            "clock_warning": self.public.get("clock_warning"),
        }
        return d

    def _write_status(self) -> None:
        if not os.path.isdir(self.ws):
            return
        try:
            d = self.status_nocheck()
            tmp = os.path.join(self.ws, "status.json.tmp")
            with open(tmp, "w") as f:
                json.dump(d, f, indent=1)
            os.replace(tmp, os.path.join(self.ws, "status.json"))
        except Exception:  # noqa: BLE001
            pass

    def status_nocheck(self) -> dict:
        st = self.state
        now = _now()
        return {"status": self.public["status"], "elapsed_s": self.elapsed(),
                "remaining_s": None if not st.get("started_at") else max(0.0, st["freeze_at"] - now),
                "next_slot_in_s": None if not st.get("started_at") else max(0.0, (self.next_slot_at() or now) - now),
                "active": st.get("active"), "submissions": len(st["submissions"]),
                "clock_warning": self.public.get("clock_warning")}

    # ------------------------------------------------------------ inbox protocol
    def process_inbox(self) -> int:
        """Handle pending requests from workspace/submit.py. Returns count."""
        n = 0
        for name in sorted(os.listdir(self.inbox)):
            if not name.endswith(".req.json"):
                continue
            rp = os.path.join(self.inbox, name)
            try:
                with open(rp) as f:
                    req = json.load(f)
            except Exception:  # noqa: BLE001
                continue
            rid = req["id"]
            result_path = os.path.join(self.inbox, f"{rid}.result.json")
            if os.path.exists(result_path):
                os.remove(rp)
                continue
            if req["kind"] == "note":
                self.note(req.get("note") or "")
                res = {"accepted": True, "summary": "noted"}
            else:
                src = req.get("file")
                if not src or not os.path.exists(src):
                    res = {"accepted": False, "summary": "REJECTED: file missing"}
                else:
                    if req.get("note"):
                        self.note(req["note"])
                    out = self.check(src, req.get("source_name", "")) if req["kind"] == "check" else self.submit(src, req.get("source_name", ""))
                    if isinstance(out, Submission):
                        rep = ValidationReport(**{k: out.report[k] for k in ("accepted", "stages", "metrics", "sha256", "size_bytes", "seconds", "error", "config")})
                        label = "CHECK " if req["kind"] == "check" else ""
                        res = {"accepted": out.accepted if req["kind"] == "submit" else rep.accepted,
                               "summary": label + rep.summary(), "index": out.index, "sha256": out.sha256}
                    else:
                        res = out
            tmp = result_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(res, f)
            os.replace(tmp, result_path)
            os.remove(rp)
            n += 1
        return n

    def serve(self, poll_s: float = 0.5, until_frozen: bool = True, grace_s: float = 5.0, quiet: bool = False) -> None:
        """Host loop: process requests, keep status.json fresh, freeze on time."""
        last_status = 0.0
        frozen_at = None
        while True:
            self.tick()
            n = self.process_inbox()
            if n and not quiet:
                print(f"[serve] handled {n} request(s); active={self.state.get('active')}", flush=True)
            if _now() - last_status > 2.0:
                self._write_status()
                last_status = _now()
            if until_frozen and self.state["frozen"]:
                frozen_at = frozen_at or _now()
                if _now() - frozen_at > grace_s:
                    self.process_inbox()
                    return
            time.sleep(poll_s)
